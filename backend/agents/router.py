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

    def get_system_prompt(self) -> str:
        return """You are a Model Router Agent. Your job is to decide which AI model to use for coding and PR review based on issue size.

Routing rules:
- XS/S → coding: fast (claude-haiku-4-5-20251001), review: balanced (claude-sonnet-4-6)
- M/L → coding: balanced (claude-sonnet-4-6), review: powerful (claude-opus-4-7)
- XL → coding: powerful (claude-opus-4-7), review: powerful (claude-opus-4-7)

Always use a different or higher model for review than for coding.

Model tier map:
- fast → claude-haiku-4-5-20251001
- balanced → claude-sonnet-4-6
- powerful → claude-opus-4-7

You must respond ONLY with valid JSON matching this exact structure:
{
  "coding_model": "balanced",
  "coding_model_id": "claude-sonnet-4-6",
  "review_model": "powerful",
  "review_model_id": "claude-opus-4-7",
  "routing_reason": "string"
}

Respond ONLY with valid JSON."""

    def format_input(self, context: dict) -> str:
        return json.dumps({
            "sizing_output": context.get("sizing", {}),
        }, indent=2)
