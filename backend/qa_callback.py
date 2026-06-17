"""HMAC-authenticated QA callback endpoint + async coordination.

The QA worker runs in GitHub Actions and posts events back to DevFlow as the
QA loop progresses. The pipeline awaits an asyncio.Event keyed by step_id;
the callback handler sets it on `qa_complete` so the pipeline can pick up
the verdict and continue.
"""
import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request

logger = logging.getLogger(__name__)

router = APIRouter()

QA_ARTIFACT_ROOT = Path(os.getenv("QA_ARTIFACT_DIR", "./qa_artifacts")).resolve()
QA_CALLBACK_SECRET = os.getenv("QA_CALLBACK_SECRET", "")


@dataclass
class _PendingQA:
    """Mutable state shared between the QA workflow callbacks and the pipeline await."""
    event: asyncio.Event = field(default_factory=asyncio.Event)
    issue_id: Optional[int] = None
    output: Optional[dict] = None
    error: Optional[str] = None
    findings: list[dict] = field(default_factory=list)
    tests_written: list[dict] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    boot: Optional[dict] = None
    tool_calls: list[dict] = field(default_factory=list)


_pending: dict[int, _PendingQA] = {}
_broadcast = None  # set by main.py at startup


def register_broadcast(broadcast_fn) -> None:
    """Wire the WebSocket broadcaster from main.py so we can rebroadcast QA events."""
    global _broadcast
    _broadcast = broadcast_fn


def register_pending(step_id: int, issue_id: int) -> _PendingQA:
    """Called by the pipeline before triggering the workflow."""
    state = _PendingQA(issue_id=issue_id)
    _pending[step_id] = state
    return state


def clear_pending(step_id: int) -> None:
    _pending.pop(step_id, None)


def _verify_signature(body: bytes, signature_header: Optional[str]) -> bool:
    if not QA_CALLBACK_SECRET:
        logger.error("QA_CALLBACK_SECRET not configured — rejecting callback")
        return False
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(
        QA_CALLBACK_SECRET.encode("utf-8"), body, hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header[len("sha256="):])


def _save_artifact(step_id: int, issue_id: int, name: str, rel_path: str, b64: str) -> Optional[str]:
    try:
        raw = base64.b64decode(b64, validate=True)
    except (ValueError, TypeError):
        logger.warning("qa_artifact for step %s had invalid base64", step_id)
        return None
    if len(raw) > 2 * 1024 * 1024:
        logger.warning("qa_artifact %s for step %s too large (%d bytes), skipping", name, step_id, len(raw))
        return None

    base = QA_ARTIFACT_ROOT / f"issue_{issue_id}" / f"step_{step_id}"
    target = (base / rel_path).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        logger.warning("qa_artifact rel_path %r escapes base — rejecting", rel_path)
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return str(target.relative_to(QA_ARTIFACT_ROOT))


@router.post("/qa/callback/{step_id}")
async def qa_callback(
    step_id: int,
    request: Request,
    x_devflow_signature: Optional[str] = Header(default=None, alias="X-DevFlow-Signature"),
):
    body = await request.body()
    if not _verify_signature(body, x_devflow_signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    state = _pending.get(step_id)
    if state is None:
        # Callback arrived after the pipeline gave up (e.g. timeout fired, box
        # restarted). Log and drop — the worker has nothing useful to do here.
        logger.warning("Received QA callback for unknown step %s — dropping", step_id)
        return {"acknowledged": False, "reason": "no pending step"}

    event_type = event.get("type")

    if event_type == "qa_boot_detected":
        state.boot = event.get("boot")
    elif event_type == "qa_finding":
        finding = event.get("finding")
        if isinstance(finding, dict):
            state.findings.append(finding)
    elif event_type == "qa_tool_use":
        state.tool_calls.append({
            "tool": event.get("tool"),
            "turn": event.get("turn"),
            "input_preview": event.get("input_preview"),
        })
    elif event_type == "qa_artifact":
        saved_rel = _save_artifact(
            step_id, state.issue_id,
            event.get("name", "artifact"),
            event.get("rel_path", event.get("name", "artifact")),
            event.get("content_b64", ""),
        )
        if saved_rel:
            state.screenshots.append(
                f"/artifacts/{state.issue_id}/{step_id}/{Path(saved_rel).relative_to(Path(f'issue_{state.issue_id}') / f'step_{step_id}')}"
            )
        # Artifacts are heavy — don't rebroadcast their bytes on the WebSocket.
        return {"acknowledged": True}
    elif event_type == "qa_complete":
        outcome = event.get("outcome")
        if outcome == "ok":
            output = event.get("output") or {}
            # Reconcile worker-side screenshots with the URLs we built locally.
            if state.screenshots:
                output["screenshots"] = state.screenshots
            state.output = output
        else:
            state.error = event.get("error") or f"QA worker reported outcome={outcome}"
        state.event.set()

    if _broadcast and state.issue_id is not None and event_type != "qa_artifact":
        try:
            await _broadcast(state.issue_id, {**event, "step_id": step_id})
        except Exception as e:
            logger.debug("Failed to rebroadcast QA event: %s", e)

    return {"acknowledged": True}
