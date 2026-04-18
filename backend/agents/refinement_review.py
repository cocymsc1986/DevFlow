import json
from .base import BaseAgent


class RefinementReviewAgent(BaseAgent):
    name = "refinement_review"
    label = "Refinement Review"
    default_model = "claude-sonnet-4-6"
    max_tokens = 1024

    def get_system_prompt(self) -> str:
        return """You are a Refinement Review Agent. Review an engineering spec for contradictions, scope creep, and untestable criteria. Be concise — bullet points only, no prose padding.

Respond ONLY with valid JSON matching this exact structure:
{
  "verdict": "PASS|FAIL",
  "confidence": 0.85,
  "issues_found": ["string"],
  "scope_concerns": ["string"],
  "approach_concerns": ["string"],
  "suggestions": ["string"],
  "recommended_changes": ["string"],
  "ready_to_proceed": true,
  "reviewer_notes": "string"
}"""

    def format_input(self, context: dict) -> str:
        return json.dumps({
            "intake_output": context.get("intake", {}),
            "assessment_output": context.get("assessment", {}),
        })
