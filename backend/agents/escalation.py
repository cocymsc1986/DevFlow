import json
from .base import BaseAgent


class EscalationAgent(BaseAgent):
    name = "escalation"
    label = "Human Escalation"
    default_model = "claude-haiku-4-5-20251001"
    max_tokens = 1024

    def get_system_prompt(self) -> str:
        return """You are a Human Escalation Agent. Summarise the pipeline run for a human reviewer. Be concise — tldr is one sentence, human_summary is 2-3 short sentences max, all lists ≤3 items.

Respond ONLY with valid JSON matching this exact structure:
{
  "human_summary": "string",
  "tldr": "string",
  "priority": "low|medium|high|critical",
  "requires_human_action": true,
  "action_needed": "string or null",
  "concerns": ["string"],
  "pipeline_confidence": 0.82,
  "suggested_next_steps": ["string"],
  "flag_reason": "string"
}"""

    def format_input(self, context: dict) -> str:
        return json.dumps({
            "intake_output": context.get("intake", {}),
            "assessment_output": context.get("assessment", {}),
            "refinement_review_output": context.get("refinement_review", {}),
            "sizing_output": context.get("sizing", {}),
            "coding_output": context.get("coding", {}),
            "pr_review_output": context.get("pr_review", {}),
            "github_pr_url": context.get("github_pr_url"),
            "github_branch": context.get("github_branch"),
        })
