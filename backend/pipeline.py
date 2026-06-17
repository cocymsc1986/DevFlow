import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional
from sqlalchemy.orm import Session

from database import Issue, PipelineRun, AgentStep
from github_client import GitHubClient
from agents import (
    IntakeAgent, AssessmentAgent, RefinementReviewAgent, DesignAgent,
    SizingAgent, CodingAgent, PRReviewAgent, EscalationAgent,
)
from observability import create_pipeline_trace, get_langfuse
import qa_callback

logger = logging.getLogger(__name__)


def _finalize_trace(trace, context: dict, issue, run):
    """Log final pipeline metrics and quality scores to Langfuse."""
    if trace is None:
        return
    pr_review_output = context.get("pr_review") or {}
    sizing_output = context.get("sizing") or {}
    final_verdict = pr_review_output.get("verdict", "UNKNOWN")
    total_tokens = sum(s.tokens_used or 0 for s in run.agent_steps)

    trace.update(
        output={"verdict": final_verdict, "pr_url": issue.github_pr_url},
        metadata={
            "complexity": sizing_output.get("size"),
            "total_tokens_used": total_tokens,
            "revision_count": context.get("revision_number", 0),
            "final_verdict": final_verdict,
        },
        tags=[
            issue.issue_type or "unknown",
            f"verdict:{final_verdict.lower()}",
            f"size:{(sizing_output.get('size') or 'unknown').lower()}",
        ],
    )

    verdict_map = {"APPROVE": 1.0, "COMMENT": 0.5, "REQUEST_CHANGES": 0.0}
    for score_name, output_key in [
        ("correctness", "correctness_score"),
        ("quality", "quality_score"),
        ("security", "security_score"),
        ("test_coverage", "test_coverage_score"),
        ("integration", "integration_score"),
    ]:
        val = pr_review_output.get(output_key)
        if val is not None:
            trace.score(name=score_name, value=float(val), data_type="NUMERIC")

    trace.score(
        name="verdict",
        value=verdict_map.get(final_verdict, 0.0),
        data_type="NUMERIC",
        comment=final_verdict,
    )

    qa_output = context.get("qa") or {}
    qa_verdict = qa_output.get("verdict")
    if qa_verdict:
        trace.score(
            name="qa_verdict",
            value=1.0 if qa_verdict == "QA_PASS" else 0.0,
            data_type="NUMERIC",
            comment=qa_verdict,
        )
        trace.score(
            name="qa_findings_count",
            value=float(len(qa_output.get("findings", []))),
            data_type="NUMERIC",
        )

    get_langfuse().flush()

STAGE_ORDER = [
    "intake", "assessment", "refinement_review", "design",
    "sizing", "router", "coding", "ci_observe", "pr_review", "qa", "escalation",
]

CI_OBSERVE_ENABLED = os.getenv("CI_OBSERVE_ENABLED", "true").lower() in ("1", "true", "yes")
CI_OBSERVE_TIMEOUT = int(os.getenv("CI_OBSERVE_TIMEOUT_SECONDS", "600"))
CI_OBSERVE_POLL_INTERVAL = int(os.getenv("CI_OBSERVE_POLL_SECONDS", "15"))
CI_MAX_REVISIONS = int(os.getenv("CI_MAX_REVISIONS", "1"))
_CI_FAILURE_CONCLUSIONS = {"failure", "cancelled", "timed_out", "action_required"}

QA_ENABLED = os.getenv("QA_ENABLED", "false").lower() in ("1", "true", "yes")
QA_ARTIFACT_DIR = Path(os.getenv("QA_ARTIFACT_DIR", "./qa_artifacts")).resolve()
QA_MAX_REVISIONS = 1
QA_WORKFLOW_REPO = os.getenv("QA_WORKFLOW_REPO", "")  # owner/name of the devflow repo hosting qa.yml
QA_WORKFLOW_FILE = os.getenv("QA_WORKFLOW_FILE", "qa.yml")
QA_WORKFLOW_REF = os.getenv("QA_WORKFLOW_REF", "main")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
QA_WORKFLOW_TIMEOUT = int(os.getenv("QA_WORKFLOW_TIMEOUT_SECONDS", "2100"))  # 35 min — workflow has 30 min limit

_ROUTING_TABLE: dict[str, tuple[str, str]] = {
    "XS": ("claude-haiku-4-5-20251001", "claude-sonnet-4-6"),
    "S":  ("claude-haiku-4-5-20251001", "claude-sonnet-4-6"),
    "M":  ("claude-sonnet-4-6",          "claude-opus-4-7"),
    "L":  ("claude-sonnet-4-6",          "claude-opus-4-7"),
    "XL": ("claude-opus-4-7",            "claude-opus-4-7"),
}
_TIER_NAMES: dict[str, str] = {
    "claude-haiku-4-5-20251001": "fast",
    "claude-sonnet-4-6": "balanced",
    "claude-opus-4-7": "powerful",
}


def _resolve_models(size: str) -> dict:
    coding_id, review_id = _ROUTING_TABLE.get(size, ("claude-sonnet-4-6", "claude-opus-4-7"))
    return {
        "coding_model": _TIER_NAMES[coding_id],
        "coding_model_id": coding_id,
        "review_model": _TIER_NAMES[review_id],
        "review_model_id": review_id,
        "routing_reason": (
            f"Deterministic routing: {size} → "
            f"{_TIER_NAMES[coding_id]} coding, {_TIER_NAMES[review_id]} review"
        ),
    }


class Pipeline:
    def __init__(self, db: Session, broadcast: Callable = None):
        self.db = db
        self.broadcast = broadcast or (lambda issue_id, event: None)
        self.github = GitHubClient()
        self._current_trace = None

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
        step.input_data = agent.format_input(context)
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
            result = await agent.run(context, langfuse_trace=self._current_trace)
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
                if "repo_tree" not in context and context.get("github_repo"):
                    context["repo_tree"] = await self._fetch_repo_tree(context["github_repo"])
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

                if not output.get("ready_to_proceed", True):
                    issues = "; ".join(output.get("issues_found", []) or output.get("recommended_changes", []))
                    msg = f"Spec not ready for implementation — refinement review blocked: {issues}"
                    await self._fail_pipeline(run, issue, issue_id, msg)
                    return False

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
                size = (context.get("sizing") or {}).get("size", "M")
                output = _resolve_models(size)
                context["router"] = output
                coding_model = output["coding_model_id"]
                review_model = output["review_model_id"]
                # Store the routing result (not just a skip reason) so run_from_stage can
                # reconstruct the correct coding/review model IDs from output_data.
                step.status = "skipped"
                step.output_data = json.dumps(output)
                step.completed_at = datetime.now(timezone.utc)
                self.db.commit()
                await self._emit(issue_id, {
                    "type": "agent_skipped",
                    "step_id": step.id,
                    "agent": "router",
                    "label": "Model Router",
                    "step_number": step.step_number,
                    "reason": output["routing_reason"],
                })

            elif stage == "coding":
                assessment_output = context.get("assessment") or {}
                key_files = assessment_output.get("key_files_to_read", [])
                context["repo_context"] = await self._fetch_repo_context(
                    context.get("github_repo"), key_files
                )
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

            elif stage == "ci_observe":
                if not await self._observe_ci_stage(issue_id, run, step, issue, context):
                    return False

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

            elif stage == "qa":
                if not await self._run_qa_stage(issue_id, run, step, issue, context):
                    return False

            elif stage == "escalation":
                output = await self._run_agent(issue_id, run, step, EscalationAgent(), context)
                if output is None:
                    await self._fail_pipeline(run, issue, issue_id, "Escalation agent failed")
                    return False
                context["escalation"] = output

        return True

    async def _observe_ci_stage(
        self, issue_id: int, run: PipelineRun, step: AgentStep,
        issue: Issue, context: dict,
    ) -> bool:
        skip_reason = None
        if not CI_OBSERVE_ENABLED:
            skip_reason = "CI observation disabled (set CI_OBSERVE_ENABLED=true to enable)"
        elif not self.github.is_configured:
            skip_reason = "GitHub not configured — no CI to observe"
        elif not issue.github_branch:
            skip_reason = "No GitHub branch — PR was not created"

        if skip_reason:
            self._skip_step(step, skip_reason)
            await self._emit(issue_id, {
                "type": "agent_skipped",
                "step_id": step.id, "agent": "ci_observe", "label": step.agent_label,
                "step_number": step.step_number, "reason": skip_reason,
            })
            return True

        self._start_step(step)
        await self._emit(issue_id, {
            "type": "agent_start",
            "step_id": step.id, "agent": "ci_observe",
            "label": step.agent_label, "step_number": step.step_number,
        })

        checks, outcome = await self._poll_ci_checks(issue_id, step, issue.github_repo, issue.github_branch)

        result_output = {"checks": checks, "outcome": outcome}
        if outcome == "failure":
            result_output["failed_count"] = sum(
                1 for c in checks if c.get("conclusion") in _CI_FAILURE_CONCLUSIONS
            )

        self._complete_step(step, {"output": result_output, "completed_at": datetime.now(timezone.utc)}, result_output)
        await self._emit(issue_id, {
            "type": "agent_complete",
            "step_id": step.id, "agent": "ci_observe", "label": step.agent_label,
            "step_number": step.step_number, "output": result_output,
        })

        if outcome == "failure":
            context["ci_failures"] = [c for c in checks if c.get("conclusion") in _CI_FAILURE_CONCLUSIONS]
            await self._run_ci_revision_loop(issue_id, run, issue, context)

        return True

    async def _poll_ci_checks(
        self, issue_id: int, step: AgentStep, repo: str, branch: str,
    ) -> tuple[list[dict], str]:
        """Poll GitHub check runs until all complete or timeout. Returns (checks, outcome)."""
        elapsed = 0
        no_checks_threshold = CI_OBSERVE_POLL_INTERVAL * 2  # two polls with no checks → skip

        while elapsed < CI_OBSERVE_TIMEOUT:
            await asyncio.sleep(CI_OBSERVE_POLL_INTERVAL)
            elapsed += CI_OBSERVE_POLL_INTERVAL

            try:
                sha = await asyncio.to_thread(self.github.get_branch_head_sha, repo, branch)
                checks = await asyncio.to_thread(self.github.get_check_runs, repo, sha)
            except Exception as e:
                logger.warning("CI check poll failed (non-fatal): %s", e)
                checks = []

            if not checks:
                if elapsed >= no_checks_threshold:
                    logger.info("No CI checks found for branch %s after %ds — skipping CI observation", branch, elapsed)
                    return [], "no_checks"
                continue

            await self._emit(issue_id, {
                "type": "ci_check_update",
                "step_id": step.id,
                "branch": branch,
                "checks": checks,
            })

            pending = [c for c in checks if c.get("status") != "completed"]
            if pending:
                continue

            # All completed — classify outcome
            failed = [c for c in checks if c.get("conclusion") in _CI_FAILURE_CONCLUSIONS]
            if failed:
                return checks, "failure"
            return checks, "success"

        logger.warning("CI check observation timed out after %ds for branch %s", CI_OBSERVE_TIMEOUT, branch)
        try:
            sha = await asyncio.to_thread(self.github.get_branch_head_sha, repo, branch)
            checks = await asyncio.to_thread(self.github.get_check_runs, repo, sha)
        except Exception:
            checks = []
        return checks, "timeout"

    async def _run_ci_revision_loop(
        self, issue_id: int, run: PipelineRun, issue: Issue, context: dict,
    ) -> None:
        router_output = context.get("router") or {}
        coding_model = router_output.get("coding_model_id", "claude-sonnet-4-6")

        next_step_num = max(s.step_number for s in run.agent_steps) + 1
        revision = 0

        while context.get("ci_failures") and revision < CI_MAX_REVISIONS:
            revision += 1

            rev_coding_step = self._create_step(
                run.id, f"coding_ci_revision_{revision}",
                f"Coding Agent (CI Revision {revision})", next_step_num,
            )
            next_step_num += 1

            coding_output = await self._run_agent(
                issue_id, run, rev_coding_step,
                CodingAgent(model=coding_model), context,
            )
            if coding_output is None:
                return
            context["coding"] = coding_output

            if self.github.is_configured and issue.github_repo and issue.github_branch:
                await self._update_github_branch(issue, coding_output, issue_id)
                context["github_pr_url"] = issue.github_pr_url
                context["github_branch"] = issue.github_branch

            rev_ci_step = self._create_step(
                run.id, f"ci_observe_revision_{revision}",
                f"CI Observer (Revision {revision})", next_step_num,
            )
            next_step_num += 1

            self._start_step(rev_ci_step)
            await self._emit(issue_id, {
                "type": "agent_start",
                "step_id": rev_ci_step.id, "agent": rev_ci_step.agent_name,
                "label": rev_ci_step.agent_label, "step_number": rev_ci_step.step_number,
            })

            checks, outcome = await self._poll_ci_checks(
                issue_id, rev_ci_step, issue.github_repo, issue.github_branch,
            )
            result_output = {"checks": checks, "outcome": outcome}
            if outcome == "failure":
                result_output["failed_count"] = sum(
                    1 for c in checks if c.get("conclusion") in _CI_FAILURE_CONCLUSIONS
                )

            self._complete_step(rev_ci_step, {"output": result_output, "completed_at": datetime.now(timezone.utc)}, result_output)
            await self._emit(issue_id, {
                "type": "agent_complete",
                "step_id": rev_ci_step.id, "agent": rev_ci_step.agent_name,
                "label": rev_ci_step.agent_label, "step_number": rev_ci_step.step_number,
                "output": result_output,
            })

            if outcome == "failure":
                context["ci_failures"] = [c for c in checks if c.get("conclusion") in _CI_FAILURE_CONCLUSIONS]
            else:
                context.pop("ci_failures", None)

    async def _run_qa_stage(
        self, issue_id: int, run: PipelineRun, step: AgentStep,
        issue: Issue, context: dict,
    ) -> bool:
        pr_review = context.get("pr_review") or {}
        skip_reason = None
        if not QA_ENABLED:
            skip_reason = "QA stage disabled (set QA_ENABLED=true to enable)"
        elif pr_review.get("verdict") != "APPROVE":
            skip_reason = f"Skipped: PR Review verdict was {pr_review.get('verdict', 'unknown')}, not APPROVE"
        elif not issue.github_repo or not issue.github_branch:
            skip_reason = "Skipped: no GitHub branch to check out"
        elif not QA_WORKFLOW_REPO or not PUBLIC_BASE_URL:
            skip_reason = "Skipped: QA_WORKFLOW_REPO or PUBLIC_BASE_URL not configured"

        if skip_reason:
            self._skip_step(step, skip_reason)
            await self._emit(issue_id, {
                "type": "agent_skipped",
                "step_id": step.id, "agent": "qa", "label": step.agent_label,
                "step_number": step.step_number, "reason": skip_reason,
            })
            return True

        output = await self._dispatch_qa_workflow(issue_id, run, step, issue, context)
        if output is None:
            return True
        context["qa"] = output

        if output.get("verdict") == "QA_FAIL":
            await self._run_qa_revision_loop(issue_id, run, issue, context, output)

        return True

    async def _dispatch_qa_workflow(
        self, issue_id: int, run: PipelineRun, step: AgentStep,
        issue: Issue, context: dict,
    ) -> Optional[dict]:
        """Trigger qa.yml on QA_WORKFLOW_REPO and await the qa_complete callback."""
        step.input_data = json.dumps({
            "target_repo": issue.github_repo,
            "target_branch": issue.github_branch,
            "workflow_repo": QA_WORKFLOW_REPO,
        })
        self._start_step(step)
        await self._emit(issue_id, {
            "type": "agent_start",
            "step_id": step.id, "agent": step.agent_name,
            "label": step.agent_label, "step_number": step.step_number,
        })

        state = qa_callback.register_pending(step.id, issue_id)
        callback_url = f"{PUBLIC_BASE_URL}/qa/callback"

        try:
            await asyncio.to_thread(
                self.github.dispatch_workflow,
                QA_WORKFLOW_REPO, QA_WORKFLOW_FILE, QA_WORKFLOW_REF,
                {
                    "target_repo": issue.github_repo,
                    "target_branch": issue.github_branch,
                    "issue_id": issue_id,
                    "step_id": step.id,
                    "callback_url": callback_url,
                },
            )
        except Exception as e:
            error_msg = f"Failed to dispatch QA workflow: {e}"
            logger.error(error_msg)
            qa_callback.clear_pending(step.id)
            self._fail_step(step, error_msg)
            await self._emit(issue_id, {"type": "agent_error", "step_id": step.id, "agent": "qa", "error": error_msg})
            return None

        await self._emit(issue_id, {
            "type": "qa_workflow_dispatched", "step_id": step.id,
            "workflow_repo": QA_WORKFLOW_REPO,
        })

        try:
            await asyncio.wait_for(state.event.wait(), timeout=QA_WORKFLOW_TIMEOUT)
        except asyncio.TimeoutError:
            qa_callback.clear_pending(step.id)
            error_msg = f"QA workflow did not call back within {QA_WORKFLOW_TIMEOUT}s"
            self._fail_step(step, error_msg)
            await self._emit(issue_id, {"type": "agent_error", "step_id": step.id, "agent": "qa", "error": error_msg})
            return None

        qa_callback.clear_pending(step.id)

        if state.error or state.output is None:
            error_msg = state.error or "QA worker reported no output"
            self._fail_step(step, error_msg)
            await self._emit(issue_id, {"type": "agent_error", "step_id": step.id, "agent": "qa", "error": error_msg})
            return None

        output = state.output
        if state.boot:
            context["qa_boot"] = state.boot
        # Reconcile callback-collected findings/screenshots so the persisted
        # step matches what the user saw in real time.
        if state.findings and not output.get("findings"):
            output["findings"] = state.findings
        if state.screenshots:
            output["screenshots"] = state.screenshots

        result = {
            "output": output,
            "model": output.get("model"),
            "tokens_used": output.get("tokens_used"),
            "duration_seconds": output.get("duration_seconds"),
            "completed_at": datetime.now(timezone.utc),
        }
        self._complete_step(step, result, output)
        await self._emit(issue_id, {
            "type": "agent_complete",
            "step_id": step.id, "agent": step.agent_name,
            "label": step.agent_label, "step_number": step.step_number,
            "output": output,
            "model": result.get("model"),
            "tokens": result.get("tokens_used"),
            "duration": result.get("duration_seconds"),
        })
        return output

    async def _run_qa_revision_loop(
        self, issue_id: int, run: PipelineRun, issue: Issue,
        context: dict, qa_output: dict,
    ) -> None:
        router_output = context.get("router") or {}
        coding_model = router_output.get("coding_model_id", "claude-sonnet-4-6")

        next_step_num = max(s.step_number for s in run.agent_steps) + 1
        revision = 0

        while qa_output.get("verdict") == "QA_FAIL" and revision < QA_MAX_REVISIONS:
            revision += 1
            context["qa_findings"] = qa_output.get("findings", [])
            context["qa_summary"] = qa_output.get("summary")

            rev_coding_step = self._create_step(
                run.id, f"coding_qa_revision_{revision}",
                f"Coding Agent (QA Revision {revision})", next_step_num,
            )
            next_step_num += 1

            coding_output = await self._run_agent(
                issue_id, run, rev_coding_step,
                CodingAgent(model=coding_model), context,
            )
            if coding_output is None:
                return
            context["coding"] = coding_output

            if self.github.is_configured and issue.github_repo and issue.github_branch:
                await self._update_github_branch(issue, coding_output, issue_id)
                context["github_pr_url"] = issue.github_pr_url
                context["github_branch"] = issue.github_branch

            rev_qa_step = self._create_step(
                run.id, f"qa_revision_{revision}",
                f"QA Agent (Revision {revision})", next_step_num,
            )
            next_step_num += 1

            output = await self._dispatch_qa_workflow(issue_id, run, rev_qa_step, issue, context)
            if output is None:
                return
            qa_output = output
            context["qa"] = qa_output

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
            ("ci_observe", "CI Observer", 8),
            ("pr_review", "PR Review", 9),
            ("qa", "QA Agent", 10),
            ("escalation", "Human Escalation", 11),
        ]

        steps = {name: self._create_step(run.id, name, label, num) for name, label, num in steps_config}

        try:
            self._current_trace = create_pipeline_trace(
                run_id=run.id, issue_id=issue_id, issue_title=issue.title,
                issue_type=issue.issue_type or "unknown", has_ui=bool(issue.has_ui),
            )
            success = await self._execute_stages(issue_id, run, issue, steps, context, "intake")
            if success:
                run.status = "completed"
                run.completed_at = datetime.now(timezone.utc)
                issue.status = "awaiting_review"
                issue.updated_at = datetime.now(timezone.utc)
                db.commit()
                _finalize_trace(self._current_trace, context, issue, run)

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
            issue.github_error = None

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
            self._current_trace = create_pipeline_trace(
                run_id=latest_run.id, issue_id=issue_id, issue_title=issue.title,
                issue_type=issue.issue_type or "unknown", has_ui=bool(issue.has_ui),
            )
            success = await self._execute_stages(issue_id, latest_run, issue, steps_by_name, context, stage_name)
            if success:
                latest_run.status = "completed"
                latest_run.completed_at = datetime.now(timezone.utc)
                issue.status = "awaiting_review"
                issue.updated_at = datetime.now(timezone.utc)
                db.commit()
                _finalize_trace(self._current_trace, context, issue, latest_run)

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

    async def _fetch_repo_tree(self, repo: str) -> list[str]:
        if not self.github.is_configured or not repo:
            return []
        try:
            return await asyncio.to_thread(self.github.fetch_repo_tree, repo)
        except Exception as e:
            logger.warning("Repo tree fetch failed (non-fatal): %s", e)
            return []

    async def _fetch_repo_context(self, repo: str, key_files: list[str]) -> dict:
        if not self.github.is_configured or not repo:
            return {}
        try:
            return await asyncio.to_thread(self.github.fetch_repo_context, repo, key_files)
        except Exception as e:
            logger.warning("Repo context fetch failed (non-fatal): %s", e)
            return {}

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

            if not file_payloads:
                raise ValueError(
                    f"Coding agent produced no file content to push "
                    f"(files={len(coding_output.get('files', []))}, "
                    f"test_files={len(coding_output.get('test_files', []))}, "
                    f"raw_output={'raw' in coding_output})"
                )

            await asyncio.to_thread(self.github.push_files, repo, branch_name, file_payloads, f"feat: {pr_title}")

            pr = await asyncio.to_thread(self.github.create_pr, repo, branch_name, pr_title, pr_description)

            issue.github_pr_url = pr.get("url")
            issue.github_branch = branch_name
            issue.github_error = None
            self.db.commit()

            await self._emit(issue_id, {
                "type": "github_push_success",
                "branch": branch_name,
                "pr_url": pr.get("url"),
                "pr_number": pr.get("number"),
            })

        except Exception as e:
            logger.error("GitHub push failed (non-fatal): %s", e)
            issue.github_error = str(e)
            self.db.commit()
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
                issue.github_error = None
                self.db.commit()
        except Exception as e:
            logger.error("GitHub branch update failed (non-fatal): %s", e)
            issue.github_error = str(e)
            self.db.commit()
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
        if self._current_trace is not None:
            self._current_trace.update(output={"error": error, "status": "failed"})
            get_langfuse().flush()
        return run
