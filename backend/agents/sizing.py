import json
from .base import BaseAgent


class SizingAgent(BaseAgent):
    name = "sizing"
    label = "Sizing & Estimation"
    default_model = "claude-haiku-4-5-20251001"
    max_tokens = 512

    def get_system_prompt(self) -> str:
        return """You are a Sizing Agent. Estimate task complexity using XS/S/M/L/XL sizing. Be concise.

Sizing guide: XS<1hr/1-2 files, S=1-4hr/2-5 files, M=4-8hr/5-10 files, L=1-3d/10+ files, XL=3+d/arch changes
Size points: XS=1, S=2, M=5, L=8, XL=13

Respond ONLY with valid JSON matching this exact structure:
{
  "size": "M",
  "size_points": 5,
  "reasoning": "string",
  "complexity_factors": ["string"],
  "estimated_hours_min": 4,
  "estimated_hours_max": 8,
  "confidence": 0.8
}"""

    def format_input(self, context: dict) -> str:
        return json.dumps({
            "intake_output": context.get("intake", {}),
            "assessment_output": context.get("assessment", {}),
            "refinement_review_output": context.get("refinement_review", {}),
            "design_output": context.get("design"),
        })
