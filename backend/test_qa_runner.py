import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from qa.boot_detector import detect_boot_config
from qa.runner import DockerQARunner, ExecResult, QARunnerError


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


def test_boot_detector_node(temp_repo_node):
    cfg = detect_boot_config(temp_repo_node)
    assert cfg.stack in ("node", "polyglot")
    assert "npm ci" in cfg.setup_cmds
    assert cfg.start_cmd == "npm run start"
    assert cfg.has_ui is True


def test_boot_detector_python_fastapi(temp_repo_python):
    cfg = detect_boot_config(temp_repo_python)
    assert cfg.stack in ("python", "polyglot")
    assert any("pip install" in c for c in cfg.setup_cmds)
    assert cfg.start_cmd is not None
    assert "uvicorn" in cfg.start_cmd
    assert "main:app" in cfg.start_cmd


def test_boot_detector_no_manifests(tmp_path):
    cfg = detect_boot_config(tmp_path)
    assert cfg.stack == "unknown"
    assert cfg.start_cmd is None
    assert any("No start command" in n for n in cfg.detection_notes)


def test_runner_read_file_blocks_path_escape(tmp_path):
    runner = DockerQARunner(
        repo="acme/demo", branch="main",
        artifact_dir=tmp_path / "artifacts",
    )
    runner.source_dir = tmp_path / "src"
    runner.source_dir.mkdir()
    (runner.source_dir / "good.txt").write_text("hello")

    import asyncio
    assert asyncio.run(runner.read_file("good.txt")) == "hello"

    with pytest.raises(QARunnerError, match="escapes"):
        asyncio.run(runner.read_file("../escape.txt"))


def test_runner_stop_is_idempotent_when_not_started(tmp_path):
    runner = DockerQARunner(
        repo="acme/demo", branch="main",
        artifact_dir=tmp_path / "artifacts",
    )
    import asyncio
    asyncio.run(runner.stop())


def test_runner_start_without_prepare_raises(tmp_path):
    runner = DockerQARunner(
        repo="acme/demo", branch="main",
        artifact_dir=tmp_path / "artifacts",
    )
    import asyncio
    with pytest.raises(QARunnerError, match="prepare"):
        asyncio.run(runner.start())


def test_runner_skips_when_no_start_command_detected(tmp_path):
    runner = DockerQARunner(
        repo="acme/demo", branch="main",
        artifact_dir=tmp_path / "artifacts",
    )
    runner.source_dir = tmp_path
    from qa.boot_detector import BootConfig
    runner.boot = BootConfig(stack="unknown", start_cmd=None, detection_notes=["nothing found"])

    import asyncio
    with pytest.raises(QARunnerError, match="No start command"):
        asyncio.run(runner.start())
