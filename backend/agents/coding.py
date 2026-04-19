import json
from .base import BaseAgent

CODING_MODEL_CONFIG = {
    "claude-haiku-4-5-20251001": {"max_tokens": 8192, "timeout": 120},
    "claude-sonnet-4-6": {"max_tokens": 16384, "timeout": 300},
    "claude-opus-4-7": {"max_tokens": 32768, "timeout": 600},
}


class CodingAgent(BaseAgent):
    name = "coding"
    label = "Coding Agent"
    default_model = "claude-sonnet-4-6"

    def __init__(self, model: str = None):
        super().__init__(model)
        config = CODING_MODEL_CONFIG.get(self.model, {"max_tokens": 16384, "timeout": 300})
        self.max_tokens = config["max_tokens"]
        self.api_timeout = config["timeout"]

    def get_system_prompt(self) -> str:
        return """You are a Coding Agent. Your job is to implement a feature based on an engineering specification.

If you receive pr_review_feedback in the input, you are revising a previous implementation.
Address ALL blocking_issues from the review and incorporate relevant suggestions.
Keep the same branch_name and pr_title as the previous implementation.
Produce complete, updated file contents — not just diffs.

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
        data = {
            "intake_output": context.get("intake", {}),
            "assessment_output": context.get("assessment", {}),
            "refinement_review_output": context.get("refinement_review", {}),
            "design_output": context.get("design"),
            "sizing_output": context.get("sizing", {}),
            "router_output": context.get("router", {}),
        }

        if context.get("pr_review"):
            data["pr_review_feedback"] = context["pr_review"]
            data["previous_code"] = context.get("coding", {})
            data["revision_number"] = context.get("revision_number", 1)

        return json.dumps(data, indent=2)
