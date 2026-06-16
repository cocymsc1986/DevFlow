import asyncio
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .boot_detector import BootConfig, detect_boot_config

logger = logging.getLogger(__name__)


QA_IMAGE = os.getenv("QA_DOCKER_IMAGE", "devflow/qa-runner:latest")
QA_NETWORK = os.getenv("QA_DOCKER_NETWORK", "devflow-qa")
QA_ARTIFACT_DIR = Path(os.getenv("QA_ARTIFACT_DIR", "./qa_artifacts")).resolve()
QA_TIMEOUT_SECONDS = int(os.getenv("QA_TIMEOUT_SECONDS", "600"))
QA_CONTAINER_CPUS = os.getenv("QA_DOCKER_CPUS", "2")
QA_CONTAINER_MEMORY = os.getenv("QA_DOCKER_MEMORY", "4g")
QA_HOST_PORT_RANGE = (44000, 45000)


class QARunnerError(RuntimeError):
    """A recoverable error during a QA tool invocation."""


class QARunnerUnavailable(RuntimeError):
    """Docker is missing, broken, or refusing to start a container.

    Pipeline should catch this and skip the QA stage gracefully — it indicates
    infra is not ready, not a defect in the PR.
    """


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


def _free_port(rng: tuple[int, int] = QA_HOST_PORT_RANGE) -> int:
    import socket
    for p in range(rng[0], rng[1]):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise QARunnerUnavailable(f"No free port in range {rng}")


def _run(cmd: list[str], timeout: int = 60) -> ExecResult:
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False,
        )
        return ExecResult(exit_code=proc.returncode, stdout=proc.stdout or "", stderr=proc.stderr or "")
    except subprocess.TimeoutExpired as e:
        return ExecResult(
            exit_code=-1, stdout=(e.stdout or "") if isinstance(e.stdout, str) else "",
            stderr=(e.stderr or "") if isinstance(e.stderr, str) else "",
            timed_out=True,
        )
    except FileNotFoundError as e:
        raise QARunnerUnavailable(f"Required binary missing: {cmd[0]} ({e})")


def _check_docker_available() -> None:
    r = _run(["docker", "version", "--format", "{{.Server.Version}}"], timeout=10)
    if r.exit_code != 0:
        raise QARunnerUnavailable(f"Docker daemon not reachable: {r.stderr.strip()}")


def _ensure_network() -> None:
    r = _run(["docker", "network", "inspect", QA_NETWORK], timeout=10)
    if r.exit_code != 0:
        create = _run(["docker", "network", "create", "--driver", "bridge", QA_NETWORK], timeout=10)
        if create.exit_code != 0:
            raise QARunnerUnavailable(f"Failed to create docker network {QA_NETWORK}: {create.stderr}")


def _ensure_image(image: str = QA_IMAGE) -> None:
    r = _run(["docker", "image", "inspect", image], timeout=10)
    if r.exit_code != 0:
        raise QARunnerUnavailable(
            f"QA runner image {image} not found. Build it with `make qa-image` or "
            f"`docker build -t {image} backend/qa/images`."
        )


class DockerQARunner:
    """Owns the Docker container lifecycle for one QA run.

    Workflow:
        runner = DockerQARunner(repo, branch, github_token, artifact_dir)
        runner.prepare()      # git clone, detect stack
        runner.start()        # docker run, setup, boot, health probe
        ... agent uses runner.exec / runner.http / runner.playwright ...
        runner.stop()         # always called, even on failure
    """

    def __init__(
        self,
        repo: str,
        branch: str,
        artifact_dir: Path,
        github_token: Optional[str] = None,
        timeout_seconds: int = QA_TIMEOUT_SECONDS,
    ):
        self.repo = repo
        self.branch = branch
        self.github_token = github_token
        self.artifact_dir = Path(artifact_dir).resolve()
        self.timeout_seconds = timeout_seconds

        self.container_name = f"devflow-qa-{uuid.uuid4().hex[:8]}"
        self.source_dir: Optional[Path] = None
        self.boot: Optional[BootConfig] = None
        self.host_port: Optional[int] = None
        self.app_log_path: Optional[Path] = None
        self.deadline: Optional[float] = None
        self._started = False

    def _time_left(self) -> int:
        if self.deadline is None:
            return self.timeout_seconds
        return max(1, int(self.deadline - time.time()))

    async def prepare(self) -> BootConfig:
        """Clone the PR branch and detect how to start the app."""
        _check_docker_available()
        _ensure_image()

        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.source_dir = Path(tempfile.mkdtemp(prefix="devflow-qa-src-")).resolve()

        clone_url = f"https://github.com/{self.repo}.git"
        if self.github_token:
            clone_url = f"https://x-access-token:{self.github_token}@github.com/{self.repo}.git"

        r = await asyncio.to_thread(
            _run,
            ["git", "clone", "--depth", "1", "--branch", self.branch, clone_url, str(self.source_dir)],
            120,
        )
        if r.exit_code != 0:
            raise QARunnerError(f"git clone failed: {r.stderr.strip()}")

        self.boot = await asyncio.to_thread(detect_boot_config, self.source_dir)
        return self.boot

    async def start(self) -> None:
        """Start container, install deps, boot the app, wait for health."""
        if self.source_dir is None or self.boot is None:
            raise QARunnerError("prepare() must be called before start()")
        if not self.boot.start_cmd:
            raise QARunnerError(
                "No start command detected — cannot boot app for QA. "
                f"Notes: {'; '.join(self.boot.detection_notes)}"
            )

        _ensure_network()
        self.deadline = time.time() + self.timeout_seconds
        self.host_port = _free_port()

        run_cmd = [
            "docker", "run", "-d",
            "--name", self.container_name,
            "--network", QA_NETWORK,
            "--cpus", QA_CONTAINER_CPUS,
            "--memory", QA_CONTAINER_MEMORY,
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "-p", f"127.0.0.1:{self.host_port}:{self.boot.port}",
            "-v", f"{self.source_dir}:/workspace",
            "-w", "/workspace",
            "-e", f"PORT={self.boot.port}",
            "-e", f"HOST=0.0.0.0",
            QA_IMAGE,
            "sleep", "infinity",
        ]
        r = await asyncio.to_thread(_run, run_cmd, 30)
        if r.exit_code != 0:
            raise QARunnerUnavailable(f"docker run failed: {r.stderr.strip()}")
        self._started = True

        for cmd in self.boot.setup_cmds:
            logger.info("[%s] setup: %s", self.container_name, cmd)
            res = await self.exec(cmd, timeout=min(self._time_left(), 300))
            if res.exit_code != 0:
                raise QARunnerError(
                    f"Setup command failed (exit={res.exit_code}): {cmd}\n"
                    f"stderr tail:\n{res.stderr[-2000:]}"
                )

        log_path = f"/tmp/devflow-app.log"
        boot_shell = f"nohup sh -c {json.dumps(self.boot.start_cmd)} > {log_path} 2>&1 &"
        logger.info("[%s] boot: %s", self.container_name, self.boot.start_cmd)
        await self.exec(boot_shell, timeout=10)

        await self._wait_for_health()

    async def _wait_for_health(self) -> None:
        import urllib.request
        import urllib.error
        url = f"http://127.0.0.1:{self.host_port}{self.boot.health_path}"
        deadline = time.time() + min(self._time_left(), 120)
        last_err = None
        while time.time() < deadline:
            try:
                req = urllib.request.Request(url, method="GET")
                resp = await asyncio.to_thread(urllib.request.urlopen, req, None, 5)
                if 200 <= resp.status < 500:
                    logger.info("[%s] app reachable on :%d (HTTP %d)", self.container_name, self.host_port, resp.status)
                    return
            except (urllib.error.URLError, urllib.error.HTTPError, ConnectionError, TimeoutError, OSError) as e:
                last_err = e
            await asyncio.sleep(1.5)

        log = await self.exec(f"tail -n 80 /tmp/devflow-app.log || true", timeout=10)
        raise QARunnerError(
            f"App did not become healthy on port {self.boot.port} within boot window. "
            f"Last error: {last_err}\nApp log tail:\n{log.stdout}{log.stderr}"
        )

    async def exec(self, cmd: str, timeout: int = 60) -> ExecResult:
        if not self._started:
            raise QARunnerError("Container not started")
        effective = min(timeout, self._time_left())
        return await asyncio.to_thread(
            _run, ["docker", "exec", self.container_name, "sh", "-c", cmd], effective,
        )

    async def read_file(self, rel_path: str) -> str:
        if self.source_dir is None:
            raise QARunnerError("Source not prepared")
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
        import urllib.request
        import urllib.error

        if self.host_port is None:
            raise QARunnerError("App not running")
        if not path.startswith("/"):
            path = "/" + path
        url = f"http://127.0.0.1:{self.host_port}{path}"

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

    async def playwright(self, name: str, script: str, run_dir: Path) -> PlaywrightResult:
        if not self._started:
            raise QARunnerError("Container not started")

        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:60] or "spec"
        spec_dir = run_dir / "playwright" / safe_name
        spec_dir.mkdir(parents=True, exist_ok=True)

        host_screenshot_dir = spec_dir / "screenshots"
        host_screenshot_dir.mkdir(exist_ok=True)

        container_workdir = f"/tmp/devflow-playwright/{safe_name}"
        await self.exec(f"mkdir -p {container_workdir}/tests", timeout=10)

        spec_path = spec_dir / f"{safe_name}.spec.ts"
        spec_path.write_text(script, encoding="utf-8")

        # Copy spec into container
        copy = await asyncio.to_thread(
            _run,
            ["docker", "cp", str(spec_path), f"{self.container_name}:{container_workdir}/tests/{safe_name}.spec.ts"],
            30,
        )
        if copy.exit_code != 0:
            raise QARunnerError(f"docker cp failed: {copy.stderr}")

        config = (
            "import { defineConfig } from '@playwright/test';\n"
            f"export default defineConfig({{\n"
            f"  testDir: './tests',\n"
            f"  timeout: 30000,\n"
            f"  reporter: [['list'], ['json', {{ outputFile: 'result.json' }}]],\n"
            f"  use: {{\n"
            f"    baseURL: 'http://127.0.0.1:{self.boot.port}',\n"
            f"    screenshot: 'only-on-failure',\n"
            f"    trace: 'retain-on-failure',\n"
            f"  }},\n"
            f"}});\n"
        )
        config_local = spec_dir / "playwright.config.ts"
        config_local.write_text(config, encoding="utf-8")
        await asyncio.to_thread(
            _run,
            ["docker", "cp", str(config_local), f"{self.container_name}:{container_workdir}/playwright.config.ts"],
            30,
        )

        run_cmd = (
            f"cd {container_workdir} && "
            f"npx --yes playwright@1 test --config playwright.config.ts"
        )
        result = await self.exec(run_cmd, timeout=min(self._time_left(), 180))

        await asyncio.to_thread(
            _run,
            ["docker", "cp", f"{self.container_name}:{container_workdir}/test-results", str(host_screenshot_dir)],
            30,
        )

        screenshots = []
        if host_screenshot_dir.exists():
            for p in host_screenshot_dir.rglob("*.png"):
                rel = p.relative_to(self.artifact_dir.parent) if self.artifact_dir in p.parents else p.name
                screenshots.append(str(p))

        return PlaywrightResult(
            name=safe_name,
            passed=result.exit_code == 0,
            output=(result.stdout + "\n" + result.stderr)[-8000:],
            screenshots=screenshots,
        )

    async def stop(self) -> None:
        if self._started:
            try:
                await asyncio.to_thread(_run, ["docker", "rm", "-f", self.container_name], 30)
            except Exception as e:
                logger.warning("Failed to remove container %s: %s", self.container_name, e)
            self._started = False
        if self.source_dir and self.source_dir.exists():
            try:
                shutil.rmtree(self.source_dir, ignore_errors=True)
            except Exception as e:
                logger.warning("Failed to clean source dir %s: %s", self.source_dir, e)
