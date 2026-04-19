import asyncio
import json
import re
import logging
from datetime import datetime, timezone
import anthropic

logger = logging.getLogger(__name__)

_client = None

MAX_RETRIES = 3
RETRY_BASE_DELAY = 2
API_TIMEOUT = 120


def get_anthropic_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic()
    return _client


class BaseAgent:
    name: str = "base"
    label: str = "Base Agent"
    default_model: str = "claude-haiku-4-5-20251001"

    def __init__(self, model: str = None):
        self.model = model or self.default_model

    def get_system_prompt(self) -> str:
        raise NotImplementedError

    def format_input(self, context: dict) -> str:
        raise NotImplementedError

    def parse_output(self, raw: str) -> dict:
        cleaned = raw.strip()
        cleaned = re.sub(r"^```json\s*", "", cleaned)
        cleaned = re.sub(r"^```\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("Agent %s failed to parse JSON, returning raw", self.name)
            return {"raw": raw}

    async def run(self, context: dict) -> dict:
        client = get_anthropic_client()
        started_at = datetime.now(timezone.utc)

        user_message = self.format_input(context)
        system_prompt = self.get_system_prompt()

        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                response = await client.messages.create(
                    model=self.model,
                    max_tokens=8192,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_message}],
                    timeout=API_TIMEOUT,
                )
                break
            except (anthropic.APITimeoutError, anthropic.APIConnectionError, anthropic.RateLimitError) as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning("Agent %s attempt %d failed (%s), retrying in %ds", self.name, attempt + 1, type(e).__name__, delay)
                    await asyncio.sleep(delay)
                else:
                    raise
            except anthropic.APIStatusError as e:
                if e.status_code >= 500 and attempt < MAX_RETRIES - 1:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning("Agent %s attempt %d got %d, retrying in %ds", self.name, attempt + 1, e.status_code, delay)
                    await asyncio.sleep(delay)
                    last_error = e
                else:
                    raise

        completed_at = datetime.now(timezone.utc)
        raw_output = response.content[0].text
        parsed = self.parse_output(raw_output)
        tokens = response.usage.input_tokens + response.usage.output_tokens

        return {
            "output": parsed,
            "raw_output": raw_output,
            "model": self.model,
            "tokens_used": tokens,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_seconds": (completed_at - started_at).total_seconds(),
        }
