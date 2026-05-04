import asyncio
import json
import re
import logging
from datetime import datetime, timezone
import anthropic

logger = logging.getLogger(__name__)

_client = None

MAX_RETRIES = 2
RETRY_BASE_DELAY = 2
API_TIMEOUT = 300


def get_anthropic_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic()
    return _client


class BaseAgent:
    name: str = "base"
    label: str = "Base Agent"
    default_model: str = "claude-haiku-4-5-20251001"
    max_tokens: int = 8192
    api_timeout: int = API_TIMEOUT
    allow_truncation: bool = False

    def __init__(self, model: str = None):
        self.model = model or self.default_model

    def get_system_prompt(self) -> str:
        raise NotImplementedError

    def format_input(self, context: dict) -> str:
        raise NotImplementedError

    def parse_output(self, raw: str) -> dict:
        cleaned = raw.strip()

        # Try extracting JSON from a fenced code block first
        code_block = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?\s*```", cleaned)
        if code_block:
            try:
                return json.loads(code_block.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Try the whole response as JSON
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Find the outermost {...} and parse that
        start = cleaned.find('{')
        end = cleaned.rfind('}')
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                pass

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
                    max_tokens=self.max_tokens,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_message}],
                    timeout=self.api_timeout,
                )
                break
            except anthropic.APITimeoutError:
                raise RuntimeError(
                    f"Agent {self.name} timed out after {self.api_timeout}s. "
                    f"The model took too long to respond. Not retrying to avoid wasting credits."
                )
            except (anthropic.APIConnectionError, anthropic.RateLimitError) as e:
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

        if response.stop_reason == "max_tokens":
            if not self.allow_truncation:
                raise RuntimeError(
                    f"Agent {self.name} output was truncated (hit max_tokens={self.max_tokens}). "
                    f"The response is incomplete and cannot be used."
                )
            logger.warning(
                "Agent %s output was truncated (hit max_tokens=%d) but truncation is allowed",
                self.name, self.max_tokens,
            )

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
