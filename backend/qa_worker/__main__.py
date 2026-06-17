"""QA worker CLI entrypoint — invoked from `.github/workflows/qa.yml`.

Boots the target app from a checked-out source directory, runs the QA agent
loop, and POSTs each event back to DevFlow's HMAC-authenticated callback
endpoint. The final `qa_complete` event carries the verdict, findings,
screenshots (as paths relative to the artifact root), and token usage.
"""
import argparse
import asyncio
import base64
import logging
import os
import sys
from pathlib import Path

from .agent import QAAgent
from .callback import CallbackClient, get_secret_from_env
from .runner import LocalRunner, QARunnerError

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("qa_worker")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--issue-id", type=int, required=True)
    p.add_argument("--step-id", type=int, required=True)
    p.add_argument("--branch", required=True)
    p.add_argument("--callback-url", required=True, help="e.g. http://devflow.example.com/qa/callback")
    p.add_argument("--source-dir", required=True, help="Checked-out target repo directory")
    p.add_argument("--artifact-dir", default="qa_artifacts")
    p.add_argument("--context-file", help="Optional JSON file with pipeline context (coding, assessment, etc.)")
    p.add_argument("--timeout-seconds", type=int, default=int(os.getenv("QA_TIMEOUT_SECONDS", "1500")))
    return p.parse_args(argv)


def _load_context(args: argparse.Namespace) -> dict:
    ctx: dict = {"github_branch": args.branch}
    if args.context_file and Path(args.context_file).exists():
        import json
        try:
            ctx.update(json.loads(Path(args.context_file).read_text(encoding="utf-8")))
        except Exception as e:
            logger.warning("Failed to parse context file %s: %s", args.context_file, e)
    return ctx


def _upload_screenshots(callback: CallbackClient, paths: list[str], artifact_root: Path) -> list[str]:
    """POST screenshots (≤6, ≤1MB each) as base64 to the callback in chunks.

    Returns the screenshot identifiers the server stored, so the final
    qa_complete event can reference them. Heavy artifacts (videos, traces)
    are deliberately not uploaded — they remain as GH Actions logs.
    """
    uploaded = []
    for rel in paths[:6]:
        p = artifact_root / rel
        if not p.exists():
            continue
        size = p.stat().st_size
        if size > 1024 * 1024:
            logger.info("Skipping oversize screenshot %s (%d bytes)", rel, size)
            continue
        callback.send({
            "type": "qa_artifact",
            "name": p.name,
            "rel_path": rel,
            "content_b64": base64.b64encode(p.read_bytes()).decode("ascii"),
            "mime": "image/png",
        })
        uploaded.append(rel)
    return uploaded


async def _main(args: argparse.Namespace) -> int:
    secret = get_secret_from_env()
    callback = CallbackClient(args.callback_url, secret, args.step_id)
    context = _load_context(args)

    source_dir = Path(args.source_dir).resolve()
    artifact_dir = Path(args.artifact_dir).resolve()
    runner = LocalRunner(source_dir, artifact_dir, timeout_seconds=args.timeout_seconds)

    callback.send({"type": "qa_started", "branch": args.branch})

    try:
        boot = await runner.prepare()
        context["qa_boot"] = boot.to_dict()
        callback.send({"type": "qa_boot_detected", "boot": boot.to_dict()})

        await runner.start()
        callback.send({"type": "qa_app_ready", "port": boot.port})
    except QARunnerError as e:
        logger.error("QA boot failed: %s", e)
        callback.send({"type": "qa_complete", "outcome": "boot_failed", "error": str(e)})
        await runner.stop()
        return 0  # not a worker failure — the pipeline records it as a skip-with-reason

    try:
        agent = QAAgent(runner=runner, emit=lambda evt: callback.send(evt))
        output = await agent.run(context)
        uploaded = _upload_screenshots(callback, output.get("screenshots", []), artifact_dir)
        output["screenshots"] = uploaded
        callback.send({"type": "qa_complete", "outcome": "ok", "output": output})
    except Exception as e:
        logger.exception("QA agent loop failed")
        callback.send({"type": "qa_complete", "outcome": "agent_failed", "error": str(e)})
        return 1
    finally:
        await runner.stop()

    return 0


def main():
    args = _parse_args(sys.argv[1:])
    try:
        rc = asyncio.run(_main(args))
    except KeyboardInterrupt:
        rc = 130
    sys.exit(rc)


if __name__ == "__main__":
    main()
