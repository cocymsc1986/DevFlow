import json
import logging
from datetime import datetime, timezone
from typing import Callable, Optional
from sqlalchemy.orm import Session

from database import Issue, PipelineRun, AgentStep
from github_client import GitHubClient
from agents import (
    IntakeAgent, AssessmentAgent, RefinementReviewAgent, DesignAgent,
    SizingAgent, RouterAgent, CodingAgent, PRReviewAgent, EscalationAgent,
)

logger = logging.getLogger(__name__)


class Pipeline:
    def __init__(self, db: Session, broadcast: Callable = None):
        self.db = db
        self.broadcast = broadcast or (lambda issue_id, event: None)
        self.github = GitHubClient()

    async def _emit(self, issue_id: int, event: dict):
        try:
            await self.broadcast(issue_id, event)
        except Exception as e:
            logger.warning("WebSocket emit failed: %s", e)

    def _create_step(self, run_id: int, name: str, label: str, number: int) -> AgentStep:
        step = AgentStep(
            pipeline_run_id=run_id,
            agent_name=name,
            agent_label=label,
            step_number=number,
            status="pending",
        )
        self.db.add(step)
        self.db.commit()
        self.db.refresh(step)
        return step

    def _start_step(self, step: AgentStep):
        step.status = "running"
        step.started_at = datetime.now(timezone.utc)
        self.db.commit()

    def _complete_step(self, step: AgentStep, result: dict, output: dict):
        step.status = "completed"
        step.output_data = json.dumps(output)
        step.model_used = result.get("model")
        step.tokens_used = result.get("tokens_used")
        step.duration_seconds = result.get("duration_seconds")
        step.completed_at = result.get("completed_at") or datetime.now(timezone.utc)
        self.db.commit()

    def _fail_step(self, step: AgentStep, error: str):
        step.status = "failed"
        step.error_message = error
        step.completed_at = datetime.now(timezone.utc)
        self.db.commit()

    def _skip_step(self, step: AgentStep, reason: str):
        step.status = "skipped"
        step.output_data = json.dumps({"skipped": True, "reason": reason})
        step.completed_at = datetime.now(timezone.utc)
        self.db.commit()

    async def _run_agent(self, issue_id: int, run: PipelineRun, step: AgentStep, agent, context: dict) -> Optional[dict]:
        step.input_data = json.dumps(context)
        self.db.commit()

        self._start_step(step)
        await self._emit(issue_id, {
            "type": "agent_start",
            "step_id": step.id,
            "agent": step.agent_name,
            "label": step.agent_label,
            "step_number": step.step_number,
        })

        try:
            result = agent.run(context)
            output = result["output"]
            self._complete_step(step, result, output)
            await self._emit(issue_id, {
                "type": "agent_complete",
                "step_id": step.id,
                "agent": step.agent_name,
                "label": step.agent_label,
                "step_number": step.step_number,
                "output": output,
                "model": result.get("model"),
                "tokens": result.get("tokens_used"),
                "duration": result.get("duration_seconds"),
            })
            return output
        except Exception as e:
            error_msg = str(e)
            logger.error("Agent %s failed: %s", step.agent_name, error_msg)
            self._fail_step(step, error_msg)
            await self._emit(issue_id, {
                "type": "agent_error",
                "step_id": step.id,
                "agent": step.agent_name,
                "error": error_msg,
            })
            return None

    async def run(self, issue_id: int) -> PipelineRun:
        db = self.db
        issue = db.query(Issue).filter(Issue.id == issue_id).first()
        if not issue:
            raise ValueError(f"Issue {issue_id} not found")

        issue.status = "running"
        issue.updated_at = datetime.now(timezone.utc)
        db.commit()

        run = PipelineRun(issue_id=issue_id, status="running", started_at=datetime.now(timezone.utc))
        db.add(run)
        db.commit()
        db.refresh(run)

        await self._emit(issue_id, {"type": "pipeline_start", "run_id": run.id, "issue_id": issue_id})

        context = {
            "title": issue.title,
            "description": issue.description,
            "issue_type": issue.issue_type,
            "has_ui": issue.has_ui,
            "github_repo": issue.github_repo,
        }

        steps_config = [
            ("intake", "Issue Intake", 1),
            ("assessment", "Assessment & Refinement", 2),
            ("refinement_review", "Refinement Review", 3),
            ("design", "Design Input", 4),
            ("sizing", "Sizing & Estimation", 5),
            ("router", "Model Router", 6),
            ("coding", "Coding Agent", 7),
            ("pr_review", "PR Review", 8),
            ("escalation", "Human Escalation", 9),
        ]

        steps = {name: self._create_step(run.id, name, label, num) for name, label, num in steps_config}

        try:
            # Step 1 - Intake
            intake_output = await self._run_agent(issue_id, run, steps["intake"], IntakeAgent(), context)
            if intake_output is None:
                return await self._fail_pipeline(run, issue, issue_id, "Intake agent failed")
            context["intake"] = intake_output

            # Step 2 - Assessment
            assessment_output = await self._run_agent(issue_id, run, steps["assessment"], AssessmentAgent(), context)
            if assessment_output is None:
                return await self._fail_pipeline(run, issue, issue_id, "Assessment agent failed")
            context["assessment"] = assessment_output

            # Step 3 - Refinement Review
            review_output = await self._run_agent(issue_id, run, steps["refinement_review"], RefinementReviewAgent(), context)
            if review_output is None:
                return await self._fail_pipeline(run, issue, issue_id, "Refinement review agent failed")
            context["refinement_review"] = review_output

            # Step 4 - Design (conditional)
            has_ui = intake_output.get("has_ui", issue.has_ui)
            if has_ui:
                design_output = await self._run_agent(issue_id, run, steps["design"], DesignAgent(), context)
                if design_output is None:
                    return await self._fail_pipeline(run, issue, issue_id, "Design agent failed")
                context["design"] = design_output
            else:
                reason = "No UI involvement"
                self._skip_step(steps["design"], reason)
                await self._emit(issue_id, {
                    "type": "agent_skipped",
                    "step_id": steps["design"].id,
                    "agent": "design",
                    "label": "Design Input",
                    "step_number": 4,
                    "reason": reason,
                })
                context["design"] = None

            # Step 5 - Sizing
            sizing_output = await self._run_agent(issue_id, run, steps["sizing"], SizingAgent(), context)
            if sizing_output is None:
                return await self._fail_pipeline(run, issue, issue_id, "Sizing agent failed")
            context["sizing"] = sizing_output

            # Step 6 - Router
            router_output = await self._run_agent(issue_id, run, steps["router"], RouterAgent(), context)
            if router_output is None:
                return await self._fail_pipeline(run, issue, issue_id, "Router agent failed")
            context["router"] = router_output

            coding_model = router_output.get("coding_model_id", "claude-sonnet-4-6")
            review_model = router_output.get("review_model_id", "claude-opus-4-7")

            # Step 7 - Coding
            coding_output = await self._run_agent(issue_id, run, steps["coding"], CodingAgent(model=coding_model), context)
            if coding_output is None:
                return await self._fail_pipeline(run, issue, issue_id, "Coding agent failed")
            context["coding"] = coding_output

            # GitHub push (non-fatal)
            if self.github.is_configured and issue.github_repo:
                await self._push_to_github(issue, coding_output, issue_id)

            context["github_pr_url"] = issue.github_pr_url
            context["github_branch"] = issue.github_branch

            # Step 8 - PR Review
            pr_review_output = await self._run_agent(issue_id, run, steps["pr_review"], PRReviewAgent(model=review_model), context)
            if pr_review_output is None:
                return await self._fail_pipeline(run, issue, issue_id, "PR Review agent failed")
            context["pr_review"] = pr_review_output

            # Step 9 - Escalation
            escalation_output = await self._run_agent(issue_id, run, steps["escalation"], EscalationAgent(), context)
            if escalation_output is None:
                return await self._fail_pipeline(run, issue, issue_id, "Escalation agent failed")
            context["escalation"] = escalation_output

            # Complete pipeline
            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc)
            issue.status = "awaiting_review"
            issue.updated_at = datetime.now(timezone.utc)
            db.commit()

            await self._emit(issue_id, {
                "type": "pipeline_complete",
                "run_id": run.id,
                "issue_id": issue_id,
                "pr_url": issue.github_pr_url,
                "escalation": escalation_output,
            })

        except Exception as e:
            logger.exception("Pipeline failed unexpectedly: %s", e)
            await self._fail_pipeline(run, issue, issue_id, str(e))

        return run

    async def _push_to_github(self, issue: Issue, coding_output: dict, issue_id: int):
        try:
            repo = issue.github_repo
            branch_name = coding_output.get("branch_name", f"feat/issue-{issue.id}")
            pr_title = coding_output.get("pr_title", issue.title)
            pr_description = coding_output.get("pr_description", "")

            self.github.create_branch(repo, branch_name)

            all_files = coding_output.get("files", []) + coding_output.get("test_files", [])
            file_payloads = [
                {"path": f["path"], "content": f.get("content", "")}
                for f in all_files if f.get("action") != "delete" and f.get("content")
            ]

            if file_payloads:
                self.github.push_files(repo, branch_name, file_payloads, f"feat: {pr_title}")

            pr = self.github.create_pr(repo, branch_name, pr_title, pr_description)

            issue.github_pr_url = pr.get("url")
            issue.github_branch = branch_name
            self.db.commit()

        except Exception as e:
            logger.error("GitHub push failed (non-fatal): %s", e)
            await self._emit(issue_id, {"type": "github_error", "error": str(e)})

    async def _fail_pipeline(self, run: PipelineRun, issue: Issue, issue_id: int, error: str) -> PipelineRun:
        run.status = "failed"
        run.completed_at = datetime.now(timezone.utc)
        issue.status = "failed"
        issue.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        await self._emit(issue_id, {
            "type": "pipeline_error",
            "run_id": run.id,
            "issue_id": issue_id,
            "error": error,
        })
        return run
