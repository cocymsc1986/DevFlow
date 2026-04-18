import json
from .base import BaseAgent


class RefinementReviewAgent(BaseAgent):
    name = "refinement_review"
    label = "Refinement Review"
    default_model = "claude-sonnet-4-6"

    def get_system_prompt(self) -> str:
        return """You are a Refinement Review Agent. Your job is to provide a second-opinion review of an engineering specification.

Check for contradictions, scope creep, untestable criteria, and whether the spec is ready for implementation.

You must respond ONLY with valid JSON matching this exact structure:
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
}

Respond ONLY with valid JSON."""

    def format_input(self, context: dict) -> str:
        return json.dumps({
            "intake_output": context.get("intake", {}),
            "assessment_output": context.get("assessment", {}),
        }, indent=2)
