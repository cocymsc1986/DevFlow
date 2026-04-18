import json
from .base import BaseAgent


class PRReviewAgent(BaseAgent):
    name = "pr_review"
    label = "PR Review"
    default_model = "claude-sonnet-4-6"

    def get_system_prompt(self) -> str:
        return """You are a PR Review Agent. Your job is to review generated code against the engineering specification.

Check for correctness, code quality, edge case handling, security vulnerabilities, and test coverage.

You must respond ONLY with valid JSON matching this exact structure:
{
  "verdict": "APPROVE|REQUEST_CHANGES|COMMENT",
  "confidence": 0.9,
  "summary": "string",
  "correctness_score": 8,
  "quality_score": 7,
  "test_coverage_score": 6,
  "security_score": 9,
  "blocking_issues": [
    {"file": "string", "line": "string or null", "issue": "string", "severity": "critical|major|minor"}
  ],
  "suggestions": [
    {"file": "string", "suggestion": "string", "type": "enhancement|nit|question"}
  ],
  "positive_notes": ["string"],
  "spec_alignment": "string",
  "overall_notes": "string"
}

Respond ONLY with valid JSON."""

    def format_input(self, context: dict) -> str:
        return json.dumps({
            "assessment_output": context.get("assessment", {}),
            "refinement_review_output": context.get("refinement_review", {}),
            "coding_output": context.get("coding", {}),
            "github_pr_url": context.get("github_pr_url"),
        }, indent=2)
