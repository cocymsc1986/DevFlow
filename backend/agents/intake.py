import json
from .base import BaseAgent


class IntakeAgent(BaseAgent):
    name = "intake"
    label = "Issue Intake"
    default_model = "claude-haiku-4-5-20251001"
    max_tokens = 1024

    def get_system_prompt(self) -> str:
        return """You are an Issue Intake Agent. Normalise a raw issue into structured JSON. Be concise — short strings only.

Respond ONLY with valid JSON matching this exact structure:
{
  "title": "string",
  "description": "string",
  "issue_type": "feature|bug|chore",
  "has_ui": true,
  "acceptance_criteria": ["string"],
  "constraints": ["string"],
  "dependencies": ["string"],
  "summary": "string"
}"""

    def format_input(self, context: dict) -> str:
        return json.dumps({
            "title": context.get("title", ""),
            "description": context.get("description", ""),
            "issue_type": context.get("issue_type", "feature"),
            "has_ui": context.get("has_ui", False),
        })
