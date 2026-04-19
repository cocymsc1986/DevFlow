import json
from .base import BaseAgent


class IntakeAgent(BaseAgent):
    name = "intake"
    label = "Issue Intake"
    default_model = "claude-haiku-4-5-20251001"

    def get_system_prompt(self) -> str:
        return """You are an Issue Intake Agent. Your job is to normalise a raw issue submission into a structured format.

Analyse the issue and produce a clean, structured representation with clear acceptance criteria, constraints, and dependencies.

For the requires_design_input field: set to true ONLY if the change involves new UI layouts, new visual components, significant visual/UX redesigns, or new user flows. Set to false for bug fixes, functional/logic changes to existing UI, backend changes, API changes, refactors, or any change that does not alter the visual design or layout of the interface.

You must respond ONLY with valid JSON matching this exact structure:
{
  "title": "string",
  "description": "string",
  "issue_type": "feature|bug|chore",
  "has_ui": true,
  "requires_design_input": false,
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
