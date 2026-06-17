import asyncio
import json
import logging
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .boot_detector import BootConfig, detect_boot_config

logger = logging.getLogger(__name__)


class QARunnerError(RuntimeError):
    """A recoverable error during a QA tool invocation."""


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False

    def to_dict(self) -> dict:
        return {
            "exit_code": self.exit_code,
            "stdout": self.stdout[-8000:],
            "stderr": self.stderr[-8000:],
            "timed_out": self.timed_out,
        }


@dataclass
class PlaywrightResult:
    name: str
    passed: bool
    output: str
    screenshots: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "output": self.output[-8000:],
            "screenshots": self.screenshots,
        }


def _run_sync(cmd: list[str] | str, *, cwd: Optional[Path] = None,
              env: Optional[dict] = None, timeout: int = 60,
              shell: bool = False) -> ExecResult:
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            check=False, cwd=cwd, env=env, shell=shell,
        )
        return ExecResult(exit_code=proc.returncode, stdout=proc.stdout or "", stderr=proc.stderr or "")
    except subprocess.TimeoutExpired as e:
        return ExecResult(
            exit_code=-1,
            stdout=(e.stdout or "") if isinstance(e.stdout, str) else "",
            stderr=(e.stderr or "") if isinstance(e.stderr, str) else "",
            timed_out=True,
        )


class LocalRunner:
    """Runs the target app and QA probes directly on the host (the GH Actions runner).

    No nested Docker — the GH runner is itself an ephemeral VM destroyed after
    the workflow finishes, so it IS the sandbox. Compared to the old
    DockerQARunner, this drops ~400 lines of container plumbing and removes
    the t2.micro memory blocker entirely.

    Workflow:
        runner = LocalRunner(source_dir, artifact_dir, timeout_seconds)
        runner.prepare()           # detect stack
        runner.start()             # setup + boot + health probe
        ... agent uses runner.exec / runner.http / runner.playwright ...
        runner.stop()              # always called, even on failure
    """

    def __init__(
        self,
        source_dir: Path,
        artifact_dir: Path,
        timeout_seconds: int = 600,
    ):
        self.source_dir = Path(source_dir).resolve()
        self.artifact_dir = Path(artifact_dir).resolve()
        self.timeout_seconds = timeout_seconds

        self.boot: Optional[BootConfig] = None
        self.workdir: Optional[Path] = None
        self.app_log_path: Optional[Path] = None
        self.app_proc: Optional[subprocess.Popen] = None
        self.deadline: Optional[float] = None
        self._started = False

    def _time_left(self) -> int:
        if self.deadline is None:
            return self.timeout_seconds
        return max(1, int(self.deadline - time.time()))

    async def prepare(self) -> BootConfig:
        """Detect how to start the app (the GH workflow does the clone)."""
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.boot = await asyncio.to_thread(detect_boot_config, self.source_dir)
        self.workdir = self.source_dir / self.boot.workdir if self.boot.workdir != "." else self.source_dir
        return self.boot

    async def start(self) -> None:
        if self.boot is None:
            raise QARunnerError("prepare() must be called before start()")
        if not self.boot.start_cmd:
            raise QARunnerError(
                f"No start command detected — cannot boot app for QA. "
                f"Notes: {'; '.join(self.boot.detection_notes)}"
            )

        self.deadline = time.time() + self.timeout_seconds
        self.app_log_path = self.artifact_dir / "app.log"

        env = {
            **os.environ,
            "PORT": str(self.boot.port),
            "HOST": "0.0.0.0",
        }

        for cmd in self.boot.setup_cmds:
            logger.info("[qa] setup: %s (cwd=%s)", cmd, self.workdir)
            res = await asyncio.to_thread(
                _run_sync, cmd, cwd=self.workdir, env=env,
                timeout=min(self._time_left(), 300), shell=True,
            )
            if res.exit_code != 0:
                raise QARunnerError(
                    f"Setup command failed (exit={res.exit_code}): {cmd}\n"
                    f"stderr tail:\n{res.stderr[-2000:]}"
                )

        logger.info("[qa] boot: %s (cwd=%s, port=%d)", self.boot.start_cmd, self.workdir, self.boot.port)
        log_fh = self.app_log_path.open("w")
        self.app_proc = subprocess.Popen(
            self.boot.start_cmd,
            cwd=self.workdir, env=env, shell=True,
            stdout=log_fh, stderr=subprocess.STDOUT,
        )
        self._started = True

        await self._wait_for_health()

    async def _wait_for_health(self) -> None:
        url = f"http://127.0.0.1:{self.boot.port}{self.boot.health_path}"
        deadline = time.time() + min(self._time_left(), 120)
        last_err = None
        while time.time() < deadline:
            if self.app_proc and self.app_proc.poll() is not None:
                tail = self._tail_log()
                raise QARunnerError(
                    f"App process exited early (code={self.app_proc.returncode}) before becoming healthy.\n"
                    f"Log tail:\n{tail}"
                )
            try:
                req = urllib.request.Request(url, method="GET")
                resp = await asyncio.to_thread(urllib.request.urlopen, req, None, 5)
                if 200 <= resp.status < 500:
                    logger.info("[qa] app reachable on :%d (HTTP %d)", self.boot.port, resp.status)
                    return
            except (urllib.error.URLError, urllib.error.HTTPError, ConnectionError, TimeoutError, OSError) as e:
                last_err = e
            await asyncio.sleep(1.5)

        raise QARunnerError(
            f"App did not become healthy on port {self.boot.port} within boot window. "
            f"Last error: {last_err}\nLog tail:\n{self._tail_log()}"
        )

    def _tail_log(self, lines: int = 80) -> str:
        if not self.app_log_path or not self.app_log_path.exists():
            return "(no log file)"
        try:
            text = self.app_log_path.read_text(encoding="utf-8", errors="replace")
            return "\n".join(text.splitlines()[-lines:])
        except OSError as e:
            return f"(failed to read log: {e})"

    async def exec(self, cmd: str, timeout: int = 60) -> ExecResult:
        effective = min(timeout, self._time_left())
        return await asyncio.to_thread(
            _run_sync, cmd, cwd=self.workdir, timeout=effective, shell=True,
        )

    async def read_file(self, rel_path: str) -> str:
        target = (self.source_dir / rel_path).resolve()
        try:
            target.relative_to(self.source_dir)
        except ValueError:
            raise QARunnerError(f"Path escapes source dir: {rel_path}")
        if not target.exists():
            raise QARunnerError(f"File not found: {rel_path}")
        if target.stat().st_size > 512 * 1024:
            raise QARunnerError(f"File too large to read: {rel_path}")
        return target.read_text(encoding="utf-8", errors="replace")

    async def http(
        self,
        method: str,
        path: str,
        body: Optional[object] = None,
        headers: Optional[dict] = None,
    ) -> dict:
        if not path.startswith("/"):
            path = "/" + path
        url = f"http://127.0.0.1:{self.boot.port}{path}"

        data = None
        req_headers = dict(headers or {})
        if body is not None:
            if isinstance(body, (dict, list)):
                data = json.dumps(body).encode("utf-8")
                req_headers.setdefault("Content-Type", "application/json")
            elif isinstance(body, str):
                data = body.encode("utf-8")
            else:
                data = str(body).encode("utf-8")

        req = urllib.request.Request(url, data=data, method=method.upper(), headers=req_headers)
        try:
            resp = await asyncio.to_thread(urllib.request.urlopen, req, None, 30)
            text = resp.read().decode("utf-8", errors="replace")
            return {
                "status": resp.status,
                "headers": dict(resp.headers),
                "body": text[:16000],
                "truncated": len(text) > 16000,
            }
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", errors="replace") if e.fp else ""
            return {"status": e.code, "headers": dict(e.headers or {}), "body": text[:16000], "truncated": len(text) > 16000}
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
            return {"status": 0, "error": str(e), "body": ""}

    async def playwright(self, name: str, script: str) -> PlaywrightResult:
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:60] or "spec"
        spec_dir = self.artifact_dir / "playwright" / safe_name
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "tests").mkdir(exist_ok=True)

        spec_path = spec_dir / "tests" / f"{safe_name}.spec.ts"
        spec_path.write_text(script, encoding="utf-8")

        config = (
            "import { defineConfig } from '@playwright/test';\n"
            "export default defineConfig({\n"
            "  testDir: './tests',\n"
            "  timeout: 30000,\n"
            "  reporter: [['list'], ['json', { outputFile: 'result.json' }]],\n"
            "  use: {\n"
            f"    baseURL: 'http://127.0.0.1:{self.boot.port}',\n"
            "    screenshot: 'only-on-failure',\n"
            "    trace: 'retain-on-failure',\n"
            "  },\n"
            "});\n"
        )
        (spec_dir / "playwright.config.ts").write_text(config, encoding="utf-8")

        run_cmd = "npx --yes playwright@1 test --config playwright.config.ts"
        result = await asyncio.to_thread(
            _run_sync, run_cmd, cwd=spec_dir,
            timeout=min(self._time_left(), 180), shell=True,
        )

        screenshots = []
        for p in spec_dir.rglob("*.png"):
            screenshots.append(str(p.relative_to(self.artifact_dir)))

        return PlaywrightResult(
            name=safe_name,
            passed=result.exit_code == 0,
            output=(result.stdout + "\n" + result.stderr)[-8000:],
            screenshots=screenshots,
        )

    async def stop(self) -> None:
        if self.app_proc is not None and self.app_proc.poll() is None:
            try:
                self.app_proc.terminate()
                try:
                    self.app_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.app_proc.kill()
            except Exception as e:
                logger.warning("Failed to stop app process: %s", e)
        self._started = False
