import asyncio
import hashlib
import hmac
import json
from pathlib import Path

import pytest

from qa_worker.boot_detector import detect_boot_config
from qa_worker.runner import LocalRunner, QARunnerError
from qa_worker.callback import CallbackClient


@pytest.fixture
def temp_repo_node(tmp_path: Path) -> Path:
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "demo",
        "scripts": {"start": "node server.js", "dev": "vite"},
        "dependencies": {"react": "^18.0.0", "express": "^4.0.0"},
    }))
    (tmp_path / "package-lock.json").write_text("{}")
    (tmp_path / "server.js").write_text("require('http').createServer().listen(3000);")
    return tmp_path


@pytest.fixture
def temp_repo_python(tmp_path: Path) -> Path:
    (tmp_path / "requirements.txt").write_text("fastapi==0.115.5\nuvicorn==0.32.1\n")
    (tmp_path / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    return tmp_path


@pytest.fixture
def temp_repo_monorepo(tmp_path: Path) -> Path:
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "requirements.txt").write_text("fastapi==0.115.5\nuvicorn==0.32.1\n")
    (tmp_path / "backend" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package.json").write_text(json.dumps({
        "name": "ui",
        "scripts": {"dev": "vite"},
        "dependencies": {"react": "^18.0.0"},
    }))
    return tmp_path


def test_boot_detector_node(temp_repo_node):
    cfg = detect_boot_config(temp_repo_node)
    assert cfg.stack in ("node", "polyglot")
    assert "npm ci" in cfg.setup_cmds
    assert cfg.start_cmd == "npm run start"
    assert cfg.has_ui is True
    assert cfg.workdir == "."


def test_boot_detector_python_fastapi(temp_repo_python):
    cfg = detect_boot_config(temp_repo_python)
    assert cfg.stack in ("python", "polyglot")
    assert any("pip install" in c for c in cfg.setup_cmds)
    assert cfg.start_cmd is not None
    assert "uvicorn" in cfg.start_cmd
    assert "main:app" in cfg.start_cmd


def test_boot_detector_monorepo_prefers_backend(temp_repo_monorepo):
    """DevFlow-style monorepos: a backend/ + frontend/ tree should boot the backend
    (the QA agent's HTTP probes are far more interesting against a real API)."""
    cfg = detect_boot_config(temp_repo_monorepo)
    assert cfg.start_cmd is not None
    assert "uvicorn" in cfg.start_cmd
    assert cfg.workdir == "backend"


def test_boot_detector_no_manifests(tmp_path):
    cfg = detect_boot_config(tmp_path)
    assert cfg.stack == "unknown"
    assert cfg.start_cmd is None
    assert any("No start command" in n for n in cfg.detection_notes)


def test_runner_read_file_blocks_path_escape(tmp_path):
    runner = LocalRunner(source_dir=tmp_path / "src", artifact_dir=tmp_path / "artifacts")
    runner.source_dir.mkdir()
    (runner.source_dir / "good.txt").write_text("hello")

    assert asyncio.run(runner.read_file("good.txt")) == "hello"
    with pytest.raises(QARunnerError, match="escapes"):
        asyncio.run(runner.read_file("../escape.txt"))


def test_runner_start_without_prepare_raises(tmp_path):
    runner = LocalRunner(source_dir=tmp_path, artifact_dir=tmp_path / "artifacts")
    with pytest.raises(QARunnerError, match="prepare"):
        asyncio.run(runner.start())


def test_runner_skips_when_no_start_command_detected(tmp_path):
    runner = LocalRunner(source_dir=tmp_path, artifact_dir=tmp_path / "artifacts")
    from qa_worker.boot_detector import BootConfig
    runner.boot = BootConfig(stack="unknown", start_cmd=None, detection_notes=["nothing found"])
    runner.workdir = tmp_path
    with pytest.raises(QARunnerError, match="No start command"):
        asyncio.run(runner.start())


def test_callback_signs_body_with_hmac():
    """The callback client must sign every POST so the receiver can verify origin."""
    secret = "topsecret"
    client = CallbackClient(callback_url="http://example.com/qa/callback", secret=secret, step_id=42)
    body_dict = {"type": "qa_started", "branch": "feat/x", "step_id": 42}
    body = json.dumps(body_dict, default=str).encode("utf-8")
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert client._sign(body) == expected
