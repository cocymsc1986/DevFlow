import json
from .base import BaseAgent


class RefinementReviewAgent(BaseAgent):
    name = "refinement_review"
    label = "Refinement Review"
    default_model = "claude-sonnet-4-6"

    def get_system_prompt(self) -> str:
        return """You are a Refinement Review Agent. Your job is to provide a second-opinion review of an engineering specification.

Check for contradictions, scope creep, untestable criteria, and whether the spec is ready for implementation.

## File Path Validation

If `repo_tree` is provided, verify that:
1. All paths in `key_files_to_read` exist in the repo_tree. Flag any invented/guessed paths.
2. `key_files_to_modify` contains real existing files — the implementation should modify these,
   not create new parallel files.
3. The technical approach describes modifications to existing code where appropriate, rather
   than creating standalone new modules for features that belong in existing files.

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
        data = {
            "intake_output": context.get("intake", {}),
            "assessment_output": context.get("assessment", {}),
        }
        repo_tree = context.get("repo_tree")
        if repo_tree:
            data["repo_tree"] = repo_tree
        return json.dumps(data, indent=2)
