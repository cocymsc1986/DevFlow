import json
from .base import BaseAgent


MODEL_TIERS = {
    "fast": "claude-haiku-4-5-20251001",
    "balanced": "claude-sonnet-4-6",
    "powerful": "claude-opus-4-7",
}


class RouterAgent(BaseAgent):
    name = "router"
    label = "Model Router"
    default_model = "claude-haiku-4-5-20251001"
    max_tokens = 256

    def get_system_prompt(self) -> str:
        return """You are a Model Router Agent. Select coding and review models based on issue size.

Rules: XS/S→coding=fast/review=balanced, M/L→coding=balanced/review=powerful, XL→coding=powerful/review=powerful
Tiers: fast=claude-haiku-4-5-20251001, balanced=claude-sonnet-4-6, powerful=claude-opus-4-7

Respond ONLY with valid JSON matching this exact structure:
{
  "coding_model": "balanced",
  "coding_model_id": "claude-sonnet-4-6",
  "review_model": "powerful",
  "review_model_id": "claude-opus-4-7",
  "routing_reason": "string"
}"""

    def format_input(self, context: dict) -> str:
        return json.dumps({"sizing_output": context.get("sizing", {})})
