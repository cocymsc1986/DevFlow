import hashlib
import hmac
import json
import logging
import os
import urllib.error
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)


class CallbackClient:
    """HMAC-signed POSTs back to DevFlow's `/qa/callback/{step_id}` endpoint.

    The shared secret lives in `QA_CALLBACK_SECRET` (set on EC2 .env and as a
    GH Actions secret). Each request body is signed with HMAC-SHA256 and the
    signature goes in `X-DevFlow-Signature`. Replays inside the same step are
    accepted — the callback handler is idempotent for non-`qa_complete` events.
    """

    def __init__(self, callback_url: str, secret: str, step_id: int):
        self.url = callback_url.rstrip("/")
        self.secret = secret.encode("utf-8") if isinstance(secret, str) else secret
        self.step_id = step_id

    def _sign(self, body: bytes) -> str:
        digest = hmac.new(self.secret, body, hashlib.sha256).hexdigest()
        return f"sha256={digest}"

    def send(self, event: dict, *, timeout: int = 15) -> Optional[dict]:
        event = {**event, "step_id": self.step_id}
        body = json.dumps(event, default=str).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "X-DevFlow-Signature": self._sign(body),
        }
        url = f"{self.url}/{self.step_id}"
        req = urllib.request.Request(url, data=body, method="POST", headers=headers)
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
            text = resp.read().decode("utf-8", errors="replace")
            try:
                return json.loads(text) if text else None
            except json.JSONDecodeError:
                return None
        except urllib.error.HTTPError as e:
            logger.warning("Callback %s returned HTTP %s: %s", event.get("type"), e.code, e.reason)
            return None
        except urllib.error.URLError as e:
            logger.warning("Callback %s failed: %s", event.get("type"), e)
            return None


def get_secret_from_env() -> str:
    secret = os.getenv("QA_CALLBACK_SECRET", "")
    if not secret:
        raise RuntimeError("QA_CALLBACK_SECRET is not set — refusing to send unauthenticated callbacks")
    return secret
