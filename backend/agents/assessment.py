import json
from .base import BaseAgent


class AssessmentAgent(BaseAgent):
    name = "assessment"
    label = "Assessment & Refinement"
    default_model = "claude-sonnet-4-6"

    def get_system_prompt(self) -> str:
        return """You are an Assessment & Refinement Agent. Your job is to produce a detailed engineering specification from a normalised issue.

Analyse the intake output and create a thorough technical specification that guides implementation.

You must respond ONLY with valid JSON matching this exact structure:
{
  "refined_title": "string",
  "problem_statement": "string",
  "technical_approach": "string",
  "tasks": [{"id": "T1", "description": "string", "type": "backend|frontend|infra|testing"}],
  "risks": ["string"],
  "edge_cases": ["string"],
  "definition_of_done": ["string"],
  "assumptions_made": ["string"],
  "missing_info": ["string"],
  "estimated_files_changed": 5,
  "key_files_to_read": ["src/components/Foo.tsx", "src/components/__tests__/Foo.test.tsx"]
}

In `key_files_to_read`, list the specific file paths (relative to repo root) in the target repo that the coding agent should study before writing code: the file(s) it will modify, any related existing test files, and 1-2 nearby files that demonstrate the conventions to follow. These paths are used to fetch actual file contents from the repo.

Respond ONLY with valid JSON."""

    def format_input(self, context: dict) -> str:
        intake = context.get("intake", {})
        return json.dumps({
            "original_issue": {
                "title": context.get("title"),
                "description": context.get("description"),
                "issue_type": context.get("issue_type"),
                "has_ui": context.get("has_ui"),
            },
            "intake_output": intake,
        }, indent=2)
