import json
from .base import BaseAgent


class AssessmentAgent(BaseAgent):
    name = "assessment"
    label = "Assessment & Refinement"
    default_model = "claude-sonnet-4-6"

    def get_system_prompt(self) -> str:
        return """You are an Assessment & Refinement Agent. Your job is to produce a detailed engineering specification from a normalised issue.

Analyse the intake output and create a thorough technical specification that guides implementation.

## Using the Repository File Tree

If `repo_tree` is provided in the input, it contains every file path in the target repository.
You MUST use this tree to:

1. **Identify the exact files to modify** — find the files that contain the relevant code.
   Look for matching module names, component names, route handlers, etc. in the tree paths.
2. **Find existing test files** — locate the test directory structure and any existing test
   files related to the code being changed.
3. **Include nearby pattern files** — pick 1-2 files in the same directory or module that
   show the conventions the coding agent should follow.
4. **Never guess paths** — only include paths that actually appear in repo_tree.

For `key_files_to_modify`, list the files that the coding agent should MODIFY (not create from
scratch). These are existing files where the new code should be integrated. This is critical:
the coding agent must know which files already exist so it can add to them rather than creating
parallel implementations.

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
  "key_files_to_read": ["src/components/Foo.tsx", "tests/Foo.test.tsx"],
  "key_files_to_modify": ["src/components/Foo.tsx"]
}

In `key_files_to_read`, list the specific file paths (relative to repo root) in the target repo
that the coding agent should study before writing code: the file(s) it will modify, any related
existing test files, and 1-2 nearby files that demonstrate conventions. These MUST be real paths
from repo_tree — do not invent paths.

In `key_files_to_modify`, list only the files that should be MODIFIED by the implementation.
This helps the coding agent understand where to integrate code rather than creating new files.

Respond ONLY with valid JSON."""

    def format_input(self, context: dict) -> str:
        intake = context.get("intake", {})
        data = {
            "original_issue": {
                "title": context.get("title"),
                "description": context.get("description"),
                "issue_type": context.get("issue_type"),
                "has_ui": context.get("has_ui"),
            },
            "intake_output": intake,
        }
        repo_tree = context.get("repo_tree")
        if repo_tree:
            data["repo_tree"] = repo_tree
        return json.dumps(data, indent=2)
