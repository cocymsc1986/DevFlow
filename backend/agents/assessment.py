import json
from .base import BaseAgent


class AssessmentAgent(BaseAgent):
    name = "assessment"
    label = "Assessment & Refinement"
    default_model = "claude-sonnet-4-6"
    max_tokens = 3072

    def get_system_prompt(self) -> str:
        return """You are an Assessment & Refinement Agent. Produce a concise engineering specification from a normalised issue. Keep all strings brief and direct.

Respond ONLY with valid JSON matching this exact structure:
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
  "estimated_files_changed": 5
}"""

    def format_input(self, context: dict) -> str:
        return json.dumps({
            "original_issue": {
                "title": context.get("title"),
                "description": context.get("description"),
                "issue_type": context.get("issue_type"),
                "has_ui": context.get("has_ui"),
            },
            "intake_output": context.get("intake", {}),
        })
