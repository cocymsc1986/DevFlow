import json
from .base import BaseAgent


class EscalationAgent(BaseAgent):
    name = "escalation"
    label = "Human Escalation"
    default_model = "claude-haiku-4-5-20251001"

    def get_system_prompt(self) -> str:
        return """You are a Human Escalation Agent. Your job is to summarise the entire pipeline run for a human reviewer.

Produce a clear, concise summary highlighting priority, concerns, and recommended next steps.

You must respond ONLY with valid JSON matching this exact structure:
{
  "human_summary": "string (markdown, 2-3 paragraphs)",
  "tldr": "string (1 sentence)",
  "priority": "low|medium|high|critical",
  "requires_human_action": true,
  "action_needed": "string or null",
  "concerns": ["string"],
  "pipeline_confidence": 0.82,
  "suggested_next_steps": ["string"],
  "flag_reason": "string"
}

Respond ONLY with valid JSON."""

    def format_input(self, context: dict) -> str:
        return json.dumps({
            "intake_output": context.get("intake", {}),
            "assessment_output": context.get("assessment", {}),
            "refinement_review_output": context.get("refinement_review", {}),
            "design_output": context.get("design"),
            "sizing_output": context.get("sizing", {}),
            "router_output": context.get("router", {}),
            "coding_output": context.get("coding", {}),
            "pr_review_output": context.get("pr_review", {}),
            "github_pr_url": context.get("github_pr_url"),
            "github_branch": context.get("github_branch"),
        }, indent=2)
