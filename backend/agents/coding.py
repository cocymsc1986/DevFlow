import json
from .base import BaseAgent


class CodingAgent(BaseAgent):
    name = "coding"
    label = "Coding Agent"
    default_model = "claude-sonnet-4-6"

    def get_system_prompt(self) -> str:
        return """You are a Coding Agent. Your job is to implement a feature based on an engineering specification.

Produce complete, working code including all necessary files, tests, a branch name, and a PR description.

For branch names: use kebab-case prefixed with feat/, fix/, or chore/ based on the issue type.

You must respond ONLY with valid JSON matching this exact structure:
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

Produce complete, working file contents — not placeholders. Respond ONLY with valid JSON."""

    def format_input(self, context: dict) -> str:
        return json.dumps({
            "intake_output": context.get("intake", {}),
            "assessment_output": context.get("assessment", {}),
            "refinement_review_output": context.get("refinement_review", {}),
            "design_output": context.get("design"),
            "sizing_output": context.get("sizing", {}),
            "router_output": context.get("router", {}),
        }, indent=2)
