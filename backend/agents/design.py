import json
from .base import BaseAgent


class DesignAgent(BaseAgent):
    name = "design"
    label = "Design Input"
    default_model = "claude-sonnet-4-6"
    max_tokens = 2048

    def get_system_prompt(self) -> str:
        return """You are a UX/UI Design Agent. Provide concise design input for UI features. Short strings only — no prose explanations.

Respond ONLY with valid JSON matching this exact structure:
{
  "components_needed": [{"name": "string", "purpose": "string", "type": "page|component|modal|form"}],
  "user_flows": [{"flow": "string", "steps": ["string"]}],
  "layout_suggestions": "string",
  "interaction_patterns": ["string"],
  "accessibility_notes": ["string"],
  "design_system_notes": ["string"],
  "responsive_considerations": ["string"],
  "design_summary": "string"
}"""

    def format_input(self, context: dict) -> str:
        return json.dumps({
            "intake_output": context.get("intake", {}),
            "assessment_output": context.get("assessment", {}),
            "refinement_review_output": context.get("refinement_review", {}),
        })
