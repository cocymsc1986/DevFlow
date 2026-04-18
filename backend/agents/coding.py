import json
from .base import BaseAgent


class CodingAgent(BaseAgent):
    name = "coding"
    label = "Coding Agent"
    default_model = "claude-sonnet-4-6"
    max_tokens = 8192

    def get_system_prompt(self) -> str:
        return """You are a Coding Agent. Implement a feature from an engineering specification.

If pr_review_feedback is provided, address all blocking_issues before anything else.

Produce complete, working code. Branch names: kebab-case with feat/, fix/, or chore/ prefix.

Respond ONLY with valid JSON matching this exact structure:
{
  "branch_name": "feat/feature-name",
  "pr_title": "string",
  "pr_description": "string (markdown)",
  "implementation_plan": "string",
  "files": [
    {"path": "src/foo.py", "action": "create|modify|delete", "description": "string", "content": "string"}
  ],
  "test_files": [
    {"path": "tests/test_foo.py", "content": "string"}
  ],
  "migration_notes": null,
  "deployment_notes": null
}

Produce complete file contents — not placeholders."""

    def format_input(self, context: dict) -> str:
        return json.dumps({
            "intake_output": context.get("intake", {}),
            "assessment_output": context.get("assessment", {}),
            "refinement_review_output": context.get("refinement_review", {}),
            "design_output": context.get("design"),
            "sizing_output": context.get("sizing", {}),
            "router_output": context.get("router", {}),
            "pr_review_feedback": context.get("pr_review_feedback"),
        })
