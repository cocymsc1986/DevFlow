import asyncio
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

STAGE_ORDER = [
    "intake", "assessment", "refinement_review", "design",
    "sizing", "router", "coding", "pr_review", "escalation",
]


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
            result = await agent.run(context)
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

    async def _execute_stages(
        self, issue_id: int, run: PipelineRun, issue: Issue,
        steps: dict, context: dict, start_stage: str
    ) -> bool:
        """
        Execute pipeline stages from start_stage to the end.
        Returns True on success, False if a stage failed (pipeline already marked as failed).
        """
        start_idx = STAGE_ORDER.index(start_stage)

        router_output = context.get("router") or {}
        coding_model = router_output.get("coding_model_id", "claude-sonnet-4-6")
        review_model = router_output.get("review_model_id", "claude-opus-4-7")
        intake_output = context.get("intake") or {}

        for stage in STAGE_ORDER[start_idx:]:
            step = steps.get(stage)

            if stage == "intake":
                output = await self._run_agent(issue_id, run, step, IntakeAgent(), context)
                if output is None:
                    await self._fail_pipeline(run, issue, issue_id, "Intake agent failed")
                    return False
                intake_output = output
                context["intake"] = output

            elif stage == "assessment":
                output = await self._run_agent(issue_id, run, step, AssessmentAgent(), context)
                if output is None:
                    await self._fail_pipeline(run, issue, issue_id, "Assessment agent failed")
                    return False
                context["assessment"] = output

            elif stage == "refinement_review":
                output = await self._run_agent(issue_id, run, step, RefinementReviewAgent(), context)
                if output is None:
                    await self._fail_pipeline(run, issue, issue_id, "Refinement review agent failed")
                    return False
                context["refinement_review"] = output

            elif stage == "design":
                requires_design = intake_output.get("requires_design_input", False)
                if requires_design:
                    output = await self._run_agent(issue_id, run, step, DesignAgent(), context)
                    if output is None:
                        await self._fail_pipeline(run, issue, issue_id, "Design agent failed")
                        return False
                    context["design"] = output
                else:
                    reason = "No design/layout changes required"
                    self._skip_step(step, reason)
                    await self._emit(issue_id, {
                        "type": "agent_skipped",
                        "step_id": step.id,
                        "agent": "design",
                        "label": "Design Input",
                        "step_number": step.step_number,
                        "reason": reason,
                    })
                    context["design"] = None

            elif stage == "sizing":
                output = await self._run_agent(issue_id, run, step, SizingAgent(), context)
                if output is None:
                    await self._fail_pipeline(run, issue, issue_id, "Sizing agent failed")
                    return False
                context["sizing"] = output

            elif stage == "router":
                output = await self._run_agent(issue_id, run, step, RouterAgent(), context)
                if output is None:
                    await self._fail_pipeline(run, issue, issue_id, "Router agent failed")
                    return False
                context["router"] = output
                coding_model = output.get("coding_model_id", "claude-sonnet-4-6")
                review_model = output.get("review_model_id", "claude-opus-4-7")

            elif stage == "coding":
                output = await self._run_agent(issue_id, run, step, CodingAgent(model=coding_model), context)
                if output is None:
                    await self._fail_pipeline(run, issue, issue_id, "Coding agent failed")
                    return False
                context["coding"] = output

                if self.github.is_configured and issue.github_repo:
                    await self._push_to_github(issue, output, issue_id)
                elif not self.github.is_configured:
                    logger.warning("GitHub not configured — skipping push for issue %s. Set GH_TOKEN env var.", issue_id)
                    await self._emit(issue_id, {"type": "github_skipped", "reason": "GitHub not configured — set GH_TOKEN env var"})
                elif not issue.github_repo:
                    logger.info("No GitHub repo selected — skipping push for issue %s", issue_id)

                context["github_pr_url"] = issue.github_pr_url
                context["github_branch"] = issue.github_branch

            elif stage == "pr_review":
                output = await self._run_agent(issue_id, run, step, PRReviewAgent(model=review_model), context)
                if output is None:
                    await self._fail_pipeline(run, issue, issue_id, "PR Review agent failed")
                    return False
                context["pr_review"] = output

                MAX_REVISIONS = 2
                revision = 0
                next_step_num = max(s.step_number for s in run.agent_steps) + 1

                while output.get("verdict") == "REQUEST_CHANGES" and revision < MAX_REVISIONS:
                    revision += 1
                    context["revision_number"] = revision

                    rev_coding_step = self._create_step(
                        run.id, f"coding_revision_{revision}",
                        f"Coding Agent (Revision {revision})", next_step_num,
                    )
                    next_step_num += 1

                    coding_output = await self._run_agent(
                        issue_id, run, rev_coding_step,
                        CodingAgent(model=coding_model), context,
                    )
                    if coding_output is None:
                        await self._fail_pipeline(run, issue, issue_id, f"Coding revision {revision} failed")
                        return False
                    context["coding"] = coding_output

                    if self.github.is_configured and issue.github_repo and issue.github_branch:
                        await self._update_github_branch(issue, coding_output, issue_id)

                    context["github_pr_url"] = issue.github_pr_url
                    context["github_branch"] = issue.github_branch

                    rev_review_step = self._create_step(
                        run.id, f"pr_review_revision_{revision}",
                        f"PR Review (Revision {revision})", next_step_num,
                    )
                    next_step_num += 1

                    output = await self._run_agent(
                        issue_id, run, rev_review_step,
                        PRReviewAgent(model=review_model), context,
                    )
                    if output is None:
                        await self._fail_pipeline(run, issue, issue_id, f"PR review revision {revision} failed")
                        return False
                    context["pr_review"] = output

                if revision > 0:
                    escalation_step = steps.get("escalation")
                    if escalation_step:
                        escalation_step.step_number = next_step_num
                        self.db.commit()

            elif stage == "escalation":
                output = await self._run_agent(issue_id, run, step, EscalationAgent(), context)
                if output is None:
                    await self._fail_pipeline(run, issue, issue_id, "Escalation agent failed")
                    return False
                context["escalation"] = output

        return True

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
            success = await self._execute_stages(issue_id, run, issue, steps, context, "intake")
            if success:
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
                    "escalation": context.get("escalation"),
                })
        except Exception as e:
            logger.exception("Pipeline failed unexpectedly: %s", e)
            await self._fail_pipeline(run, issue, issue_id, str(e))

        return run

    async def run_from_stage(self, issue_id: int, stage_name: str) -> PipelineRun:
        """Retry pipeline from a specific stage, reusing outputs from prior completed stages."""
        db = self.db
        issue = db.query(Issue).filter(Issue.id == issue_id).first()
        if not issue:
            raise ValueError(f"Issue {issue_id} not found")
        if stage_name not in STAGE_ORDER:
            raise ValueError(f"Unknown stage: {stage_name}")

        if not issue.pipeline_runs:
            raise ValueError(f"No pipeline runs found for issue {issue_id}")
        latest_run = max(issue.pipeline_runs, key=lambda r: r.id)

        retry_idx = STAGE_ORDER.index(stage_name)
        stages_before = STAGE_ORDER[:retry_idx]

        # Reconstruct context from completed steps before the retry point
        context = {
            "title": issue.title,
            "description": issue.description,
            "issue_type": issue.issue_type,
            "has_ui": issue.has_ui,
            "github_repo": issue.github_repo,
        }

        steps_by_name = {step.agent_name: step for step in latest_run.agent_steps}

        for stage in stages_before:
            step = steps_by_name.get(stage)
            if step and step.status in ("completed", "skipped") and step.output_data:
                try:
                    output = json.loads(step.output_data)
                    context[stage] = None if (stage == "design" and output.get("skipped")) else output
                except Exception:
                    context[stage] = None
            elif stage == "design":
                context["design"] = None

        # Clear GitHub info when retrying from coding or earlier so a fresh PR is created
        coding_idx = STAGE_ORDER.index("coding")
        if retry_idx <= coding_idx:
            issue.github_pr_url = None
            issue.github_branch = None

        context["github_pr_url"] = issue.github_pr_url
        context["github_branch"] = issue.github_branch

        # Reset the failed step and any downstream pending steps
        for stage in STAGE_ORDER[retry_idx:]:
            step = steps_by_name.get(stage)
            if step and step.status in ("failed", "pending"):
                step.status = "pending"
                step.error_message = None
                step.output_data = None
                step.input_data = None
                step.started_at = None
                step.completed_at = None
                step.duration_seconds = None
                step.model_used = None
                step.tokens_used = None

        issue.status = "running"
        issue.updated_at = datetime.now(timezone.utc)
        latest_run.status = "running"
        latest_run.completed_at = None
        db.commit()

        await self._emit(issue_id, {"type": "pipeline_start", "run_id": latest_run.id, "issue_id": issue_id})

        try:
            success = await self._execute_stages(issue_id, latest_run, issue, steps_by_name, context, stage_name)
            if success:
                latest_run.status = "completed"
                latest_run.completed_at = datetime.now(timezone.utc)
                issue.status = "awaiting_review"
                issue.updated_at = datetime.now(timezone.utc)
                db.commit()

                await self._emit(issue_id, {
                    "type": "pipeline_complete",
                    "run_id": latest_run.id,
                    "issue_id": issue_id,
                    "pr_url": issue.github_pr_url,
                    "escalation": context.get("escalation"),
                })
        except Exception as e:
            logger.exception("Pipeline stage retry failed unexpectedly: %s", e)
            await self._fail_pipeline(latest_run, issue, issue_id, str(e))

        return latest_run

    async def _push_to_github(self, issue: Issue, coding_output: dict, issue_id: int):
        try:
            repo = issue.github_repo
            branch_name = coding_output.get("branch_name", f"feat/issue-{issue.id}")
            pr_title = coding_output.get("pr_title", issue.title)
            pr_description = coding_output.get("pr_description", "")

            await asyncio.to_thread(self.github.create_branch, repo, branch_name)

            all_files = coding_output.get("files", []) + coding_output.get("test_files", [])
            file_payloads = [
                {"path": f["path"], "content": f.get("content", "")}
                for f in all_files if f.get("action") != "delete" and f.get("content")
            ]

            if file_payloads:
                await asyncio.to_thread(self.github.push_files, repo, branch_name, file_payloads, f"feat: {pr_title}")

            pr = await asyncio.to_thread(self.github.create_pr, repo, branch_name, pr_title, pr_description)

            issue.github_pr_url = pr.get("url")
            issue.github_branch = branch_name
            self.db.commit()

            await self._emit(issue_id, {
                "type": "github_push_success",
                "branch": branch_name,
                "pr_url": pr.get("url"),
                "pr_number": pr.get("number"),
            })

        except Exception as e:
            logger.error("GitHub push failed (non-fatal): %s", e)
            await self._emit(issue_id, {"type": "github_error", "error": str(e)})

    async def _update_github_branch(self, issue: Issue, coding_output: dict, issue_id: int):
        try:
            repo = issue.github_repo
            branch_name = issue.github_branch
            pr_title = coding_output.get("pr_title", issue.title)

            all_files = coding_output.get("files", []) + coding_output.get("test_files", [])
            file_payloads = [
                {"path": f["path"], "content": f.get("content", "")}
                for f in all_files if f.get("action") != "delete" and f.get("content")
            ]

            if file_payloads:
                await asyncio.to_thread(
                    self.github.push_files, repo, branch_name, file_payloads,
                    f"fix: address review feedback - {pr_title}",
                )
        except Exception as e:
            logger.error("GitHub branch update failed (non-fatal): %s", e)
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
