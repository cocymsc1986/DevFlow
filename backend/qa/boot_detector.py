import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class BootConfig:
    stack: str  # "node" | "python" | "polyglot" | "unknown"
    setup_cmds: list[str] = field(default_factory=list)
    start_cmd: Optional[str] = None
    port: int = 8000
    health_path: str = "/"
    has_ui: bool = False
    detection_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "stack": self.stack,
            "setup_cmds": self.setup_cmds,
            "start_cmd": self.start_cmd,
            "port": self.port,
            "health_path": self.health_path,
            "has_ui": self.has_ui,
            "detection_notes": self.detection_notes,
        }


_PORT_PATTERNS = [
    re.compile(r"localhost:(\d{2,5})"),
    re.compile(r"127\.0\.0\.1:(\d{2,5})"),
    re.compile(r"PORT[=:]\s*(\d{2,5})"),
    re.compile(r"listen\(\s*(\d{2,5})", re.IGNORECASE),
    re.compile(r"--port[\s=](\d{2,5})"),
]


def _read(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, UnicodeDecodeError):
        return None


def _scan_for_port(*texts: Optional[str]) -> Optional[int]:
    for text in texts:
        if not text:
            continue
        for pat in _PORT_PATTERNS:
            m = pat.search(text)
            if m:
                try:
                    p = int(m.group(1))
                    if 1024 <= p <= 65535:
                        return p
                except ValueError:
                    continue
    return None


def _detect_node(source_dir: Path, cfg: BootConfig) -> None:
    pkg_path = source_dir / "package.json"
    pkg_text = _read(pkg_path)
    if not pkg_text:
        return
    try:
        pkg = json.loads(pkg_text)
    except json.JSONDecodeError:
        cfg.detection_notes.append("package.json present but unparseable")
        return

    cfg.stack = "node" if cfg.stack == "unknown" else "polyglot"

    if (source_dir / "package-lock.json").exists():
        cfg.setup_cmds.append("npm ci")
    elif (source_dir / "yarn.lock").exists():
        cfg.setup_cmds.append("yarn install --frozen-lockfile")
    elif (source_dir / "pnpm-lock.yaml").exists():
        cfg.setup_cmds.append("pnpm install --frozen-lockfile")
    else:
        cfg.setup_cmds.append("npm install")

    scripts = pkg.get("scripts") or {}
    for candidate in ("start", "dev", "serve"):
        if candidate in scripts:
            cfg.start_cmd = f"npm run {candidate}"
            cfg.detection_notes.append(f"Using package.json script: {candidate}")
            break

    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    if any(k in deps for k in ("react", "vue", "svelte", "next", "vite")):
        cfg.has_ui = True

    port = _scan_for_port(scripts.get("start"), scripts.get("dev"), pkg_text)
    if port:
        cfg.port = port


def _detect_python(source_dir: Path, cfg: BootConfig) -> None:
    req = source_dir / "requirements.txt"
    pyproject = source_dir / "pyproject.toml"
    if not (req.exists() or pyproject.exists()):
        return

    cfg.stack = "python" if cfg.stack == "unknown" else "polyglot"

    if req.exists():
        cfg.setup_cmds.append("pip install -r requirements.txt")
    elif pyproject.exists():
        cfg.setup_cmds.append("pip install .")

    req_text = _read(req) or ""
    py_text = _read(pyproject) or ""
    combined = req_text + "\n" + py_text

    if "fastapi" in combined.lower() or "uvicorn" in combined.lower():
        entry = None
        for candidate in ("main.py", "app.py", "backend/main.py", "src/main.py"):
            if (source_dir / candidate).exists():
                module = candidate.replace("/", ".").removesuffix(".py")
                entry = f"uvicorn {module}:app --host 0.0.0.0 --port {cfg.port}"
                break
        if entry and not cfg.start_cmd:
            cfg.start_cmd = entry
            cfg.detection_notes.append("Detected FastAPI/uvicorn")
    elif "flask" in combined.lower():
        for candidate in ("app.py", "main.py"):
            if (source_dir / candidate).exists():
                if not cfg.start_cmd:
                    cfg.start_cmd = f"FLASK_APP={candidate} flask run --host 0.0.0.0 --port {cfg.port}"
                    cfg.detection_notes.append("Detected Flask")
                break
    elif "django" in combined.lower():
        if (source_dir / "manage.py").exists() and not cfg.start_cmd:
            cfg.start_cmd = f"python manage.py runserver 0.0.0.0:{cfg.port}"
            cfg.detection_notes.append("Detected Django")


def _detect_from_readme(source_dir: Path, cfg: BootConfig) -> None:
    for name in ("README.md", "README.rst", "README.txt"):
        text = _read(source_dir / name)
        if not text:
            continue
        port = _scan_for_port(text)
        if port:
            cfg.port = port
            cfg.detection_notes.append(f"Port {port} found in {name}")
            return


def detect_boot_config(source_dir: str | os.PathLike, has_ui_hint: bool = False) -> BootConfig:
    """Inspect a cloned repo and return how to install and start it.

    Heuristic-only — keeps QA deterministic. Callers should treat an empty
    start_cmd as "cannot boot" and skip the QA stage gracefully.
    """
    path = Path(source_dir)
    cfg = BootConfig(stack="unknown", has_ui=has_ui_hint)

    _detect_node(path, cfg)
    _detect_python(path, cfg)
    _detect_from_readme(path, cfg)

    if not cfg.start_cmd:
        cfg.detection_notes.append("No start command detected from manifests or README")

    logger.info("Boot detection for %s: %s", path, cfg.to_dict())
    return cfg
