import json
from .base import BaseAgent


class IntakeAgent(BaseAgent):
    name = "intake"
    label = "Issue Intake"
    default_model = "claude-haiku-4-5-20251001"

    def get_system_prompt(self) -> str:
        return """You are an Issue Intake Agent. Your job is to normalise a raw issue submission into a structured format.

Analyse the issue and produce a clean, structured representation with clear acceptance criteria, constraints, and dependencies.

You must respond ONLY with valid JSON matching this exact structure:
{
  "title": "string",
  "description": "string",
  "issue_type": "feature|bug|chore",
  "has_ui": true,
  "acceptance_criteria": ["string"],
  "constraints": ["string"],
  "dependencies": ["string"],
  "summary": "string"
}

Respond ONLY with valid JSON."""

    def format_input(self, context: dict) -> str:
        return json.dumps({
            "title": context.get("title", ""),
            "description": context.get("description", ""),
            "issue_type": context.get("issue_type", "feature"),
            "has_ui": context.get("has_ui", False),
        }, indent=2)
