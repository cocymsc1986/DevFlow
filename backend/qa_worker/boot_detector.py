import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SUBDIR_CANDIDATES = ["", "backend", "server", "api", "app", "frontend", "web", "client"]


@dataclass
class BootConfig:
    stack: str  # "node" | "python" | "polyglot" | "unknown"
    workdir: str = "."  # subdir within source tree to run setup/start from
    setup_cmds: list[str] = field(default_factory=list)
    start_cmd: Optional[str] = None
    port: int = 8000
    health_path: str = "/"
    has_ui: bool = False
    detection_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "stack": self.stack,
            "workdir": self.workdir,
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


def _detect_node(workdir: Path, source_root: Path, cfg: BootConfig) -> bool:
    pkg_path = workdir / "package.json"
    pkg_text = _read(pkg_path)
    if not pkg_text:
        return False
    try:
        pkg = json.loads(pkg_text)
    except json.JSONDecodeError:
        cfg.detection_notes.append(f"package.json at {workdir.relative_to(source_root)} unparseable")
        return False

    cfg.stack = "node" if cfg.stack == "unknown" else "polyglot"
    rel = workdir.relative_to(source_root)
    cfg.workdir = "." if rel == Path(".") else str(rel)

    if (workdir / "package-lock.json").exists():
        cfg.setup_cmds.append("npm ci")
    elif (workdir / "yarn.lock").exists():
        cfg.setup_cmds.append("yarn install --frozen-lockfile")
    elif (workdir / "pnpm-lock.yaml").exists():
        cfg.setup_cmds.append("pnpm install --frozen-lockfile")
    else:
        cfg.setup_cmds.append("npm install")

    scripts = pkg.get("scripts") or {}
    for candidate in ("start", "dev", "serve"):
        if candidate in scripts:
            cfg.start_cmd = f"npm run {candidate}"
            cfg.detection_notes.append(f"Using {workdir.name}/package.json script: {candidate}")
            break

    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    if any(k in deps for k in ("react", "vue", "svelte", "next", "vite")):
        cfg.has_ui = True

    port = _scan_for_port(scripts.get("start"), scripts.get("dev"), pkg_text)
    if port:
        cfg.port = port
    return True


def _detect_python(workdir: Path, source_root: Path, cfg: BootConfig) -> bool:
    req = workdir / "requirements.txt"
    pyproject = workdir / "pyproject.toml"
    if not (req.exists() or pyproject.exists()):
        return False

    cfg.stack = "python" if cfg.stack == "unknown" else "polyglot"
    if cfg.workdir == ".":
        rel = workdir.relative_to(source_root)
        cfg.workdir = "." if rel == Path(".") else str(rel)

    if req.exists():
        cfg.setup_cmds.append("pip install -r requirements.txt")
    elif pyproject.exists():
        cfg.setup_cmds.append("pip install .")

    req_text = _read(req) or ""
    py_text = _read(pyproject) or ""
    combined = (req_text + "\n" + py_text).lower()

    if "fastapi" in combined or "uvicorn" in combined:
        for candidate in ("main.py", "app.py", "src/main.py"):
            if (workdir / candidate).exists():
                module = candidate.replace("/", ".").removesuffix(".py")
                if not cfg.start_cmd:
                    cfg.start_cmd = f"uvicorn {module}:app --host 0.0.0.0 --port {cfg.port}"
                    cfg.detection_notes.append(f"Detected FastAPI/uvicorn in {workdir.name}")
                break
    elif "flask" in combined:
        for candidate in ("app.py", "main.py"):
            if (workdir / candidate).exists() and not cfg.start_cmd:
                cfg.start_cmd = f"FLASK_APP={candidate} flask run --host 0.0.0.0 --port {cfg.port}"
                cfg.detection_notes.append(f"Detected Flask in {workdir.name}")
                break
    elif "django" in combined:
        if (workdir / "manage.py").exists() and not cfg.start_cmd:
            cfg.start_cmd = f"python manage.py runserver 0.0.0.0:{cfg.port}"
            cfg.detection_notes.append(f"Detected Django in {workdir.name}")
    return True


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


def _candidate_dirs(source_root: Path) -> list[Path]:
    """Return search order: root first, then well-known service subdirs."""
    candidates = [source_root]
    for name in SUBDIR_CANDIDATES:
        if not name:
            continue
        p = source_root / name
        if p.is_dir():
            candidates.append(p)
    # apps/* monorepo convention
    apps_dir = source_root / "apps"
    if apps_dir.is_dir():
        for child in sorted(apps_dir.iterdir()):
            if child.is_dir():
                candidates.append(child)
    return candidates


def detect_boot_config(source_dir: str | os.PathLike, has_ui_hint: bool = False) -> BootConfig:
    """Inspect a cloned repo and return how to install and start it.

    Searches root, then `backend/server/api/app/frontend/web/client/apps/*` for
    a manifest with a usable start command. Returns the first viable hit —
    prefers backend-style services over UI-only when both exist.
    """
    source_root = Path(source_dir)
    cfg = BootConfig(stack="unknown", has_ui=has_ui_hint)

    # Search backend-style first so an API takes priority over the UI dev server
    # (the QA agent's HTTP probes are more interesting against a real backend).
    backend_first = [source_root]
    for name in ("backend", "server", "api", "app"):
        p = source_root / name
        if p.is_dir():
            backend_first.append(p)

    for workdir in backend_first:
        if _detect_python(workdir, source_root, cfg):
            break

    # If nothing Python found, try Node — root first, then frontend/web/client and apps/*.
    if not cfg.start_cmd:
        for workdir in _candidate_dirs(source_root):
            if _detect_node(workdir, source_root, cfg):
                if cfg.start_cmd:
                    break

    _detect_from_readme(source_root, cfg)

    if not cfg.start_cmd:
        cfg.detection_notes.append("No start command detected from manifests or README")

    logger.info("Boot detection for %s: %s", source_root, cfg.to_dict())
    return cfg
