import os
import logging
from langfuse import Langfuse

logger = logging.getLogger(__name__)

_lf = None


def get_langfuse() -> Langfuse:
    global _lf
    if _lf is None:
        _lf = Langfuse()
        if _lf.enabled:
            logger.info("Langfuse observability enabled (host=%s)", os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"))
        else:
            logger.info("Langfuse observability disabled — set LANGFUSE_PUBLIC_KEY to enable")
    return _lf


def create_pipeline_trace(run_id: int, issue_id: int, issue_title: str, issue_type: str, has_ui: bool):
    try:
        lf = get_langfuse()
        return lf.trace(
            name="devflow-pipeline",
            session_id=str(run_id),
            input={"issue_id": issue_id, "title": issue_title},
            metadata={
                "issue_id": issue_id,
                "run_id": run_id,
                "issue_type": issue_type,
                "has_ui": has_ui,
            },
            tags=[issue_type, "has_ui" if has_ui else "no_ui"],
        )
    except Exception as e:
        logger.warning("Langfuse trace creation failed, observability disabled for this run: %s", e)
        return None


def flush_langfuse():
    if _lf is not None:
        _lf.flush()
