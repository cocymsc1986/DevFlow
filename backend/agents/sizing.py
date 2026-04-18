import json
from .base import BaseAgent


class SizingAgent(BaseAgent):
    name = "sizing"
    label = "Sizing & Estimation"
    default_model = "claude-haiku-4-5-20251001"

    def get_system_prompt(self) -> str:
        return """You are a Sizing Agent. Your job is to estimate task complexity using XS/S/M/L/XL sizing.

Sizing guide:
- XS: <1hr, 1-2 files
- S: 1-4hrs, 2-5 files
- M: 4-8hrs, 5-10 files
- L: 1-3 days, 10+ files
- XL: 3+ days, architectural changes

You must respond ONLY with valid JSON matching this exact structure:
{
  "size": "M",
  "size_points": 5,
  "reasoning": "string",
  "complexity_factors": ["string"],
  "estimated_hours_min": 4,
  "estimated_hours_max": 8,
  "confidence": 0.8
}

Size points: XS=1, S=2, M=5, L=8, XL=13

Respond ONLY with valid JSON."""

    def format_input(self, context: dict) -> str:
        return json.dumps({
            "intake_output": context.get("intake", {}),
            "assessment_output": context.get("assessment", {}),
            "refinement_review_output": context.get("refinement_review", {}),
            "design_output": context.get("design"),
        }, indent=2)
