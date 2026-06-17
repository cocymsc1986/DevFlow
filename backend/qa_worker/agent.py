import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import anthropic

from .runner import LocalRunner, QARunnerError

logger = logging.getLogger(__name__)

QA_MAX_TOOL_TURNS = int(os.getenv("QA_MAX_TOOL_TURNS", "30"))
QA_MODEL = os.getenv("QA_MODEL", "claude-opus-4-7")
QA_MODEL_MAX_TOKENS = 4096
API_TIMEOUT = 300
MAX_RETRIES = 2
RETRY_BASE_DELAY = 2

TOOLS = [
    {
        "name": "read_file",
        "description": (
            "Read a file from the PR branch's checked-out source tree. "
            "Use to inspect changed files in detail. Paths are relative to repo root."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "bash",
        "description": (
            "Run a shell command alongside the running app. Use for `curl` probes, log inspection, "
            "or filesystem inspection. NOT for installing packages — the app is already booted."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "cmd": {"type": "string"},
                "timeout_seconds": {"type": "integer", "default": 30, "minimum": 1, "maximum": 180},
            },
            "required": ["cmd"],
        },
    },
    {
        "name": "http",
        "description": (
            "Make an HTTP request to the running app under test. Use this to exercise "
            "endpoints, send adversarial payloads, and observe responses."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"]},
                "path": {"type": "string", "description": "Path on the app, e.g. /api/users"},
                "body": {"description": "Optional JSON or string body"},
                "headers": {"type": "object", "additionalProperties": {"type": "string"}},
            },
            "required": ["method", "path"],
        },
    },
    {
        "name": "playwright",
        "description": (
            "Run a Playwright spec against the app's UI. The spec runs in a real Chromium browser. "
            "Use `page.goto('/')` — baseURL is preconfigured. Screenshots are captured on failure."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Short kebab-case identifier for this spec"},
                "script": {
                    "type": "string",
                    "description": (
                        "Full Playwright spec file content. Must `import { test, expect } from '@playwright/test'`. "
                        "Should contain one or more `test('...', async ({ page }) => { ... })` blocks."
                    ),
                },
            },
            "required": ["name", "script"],
        },
    },
    {
        "name": "record_finding",
        "description": (
            "Record a defect or QA observation. Call this for EVERY finding you want to "
            "include in the final report. The verdict will be QA_FAIL if any 'critical' or "
            "'major' finding is recorded."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "severity": {"type": "string", "enum": ["critical", "major", "minor"]},
                "category": {
                    "type": "string",
                    "enum": ["functional", "security", "ui", "performance", "regression", "integration"],
                },
                "title": {"type": "string"},
                "repro": {"type": "string", "description": "Concrete steps to reproduce"},
                "evidence": {"type": "string", "description": "What was observed (response, log, screenshot ref)"},
                "file": {"type": "string", "description": "Source file the defect lives in, if known"},
            },
            "required": ["severity", "category", "title", "repro", "evidence"],
        },
    },
    {
        "name": "finish",
        "description": (
            "Signal that QA is complete. Provide a final verdict and summary. "
            "If you have recorded any 'critical' or 'major' findings, the verdict MUST be QA_FAIL."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "enum": ["QA_PASS", "QA_FAIL"]},
                "summary": {"type": "string"},
            },
            "required": ["verdict", "summary"],
        },
    },
]


SYSTEM_PROMPT = """You are an adversarial QA engineer reviewing a pull request against a running instance of the app.

Your job is to find runtime defects in the **changed surface area** of the PR — not to re-review the diff statically (that already happened) and not to run unit tests (those run in CI).

## Process

1. Look at `coding_output.files` to see exactly which files changed and what surface area is at risk.
2. Use `read_file` on a few of the most-changed files to understand the change in detail.
3. For backend changes: design HTTP probes (`http` tool) that target edge cases, malformed inputs, auth bypass, injection, and broken happy paths. Run them.
4. For UI changes (`has_ui: true`): write **Playwright** specs (`playwright` tool) that exercise the changed flows. Test the happy path AND deliberately break it (missing inputs, invalid values, navigation edge cases).
5. For every defect you observe, call `record_finding` with severity, repro steps, and evidence.
6. Call `finish` when you have enough signal. Cap yourself at ~10-15 probes total — don't loop forever.

## What counts as a finding

- **critical**: the app crashes, returns 500 on documented happy paths, leaks secrets, or has an obvious auth/injection hole.
- **major**: a documented feature in the PR description doesn't work, UI is broken, an edge case the change should have handled is unhandled.
- **minor**: usability issues, unhelpful error messages, missing validation that doesn't cause a crash.

## What does NOT count as a finding

- Style/code quality issues — those are PR Review's job.
- Missing unit tests — out of scope.
- Pre-existing bugs not touched by this PR.
- Speculative concerns you haven't actually reproduced.

## Constraints

- All probes go through the provided tools.
- The app is already booted. Do NOT try to install packages or restart the app.
- Be concise in tool inputs — tool results are appended to your context.
- Stop calling tools and call `finish` as soon as you have a verdict.
"""


def _preview(value, limit: int = 200) -> str:
    try:
        text = json.dumps(value)
    except Exception:
        text = str(value)
    return text[:limit] + ("..." if len(text) > limit else "")


def _format_initial_user_message(context: dict) -> str:
    coding = context.get("coding") or {}
    assessment = context.get("assessment") or {}
    files = coding.get("files", [])
    test_files = coding.get("test_files", [])
    boot = context.get("qa_boot") or {}

    changed_summary = [
        {"path": f.get("path"), "action": f.get("action"), "description": f.get("description")}
        for f in files
    ]
    return json.dumps(
        {
            "pr_title": coding.get("pr_title"),
            "pr_description": coding.get("pr_description"),
            "branch": context.get("github_branch"),
            "has_ui": context.get("has_ui", False),
            "boot_config": {
                "stack": boot.get("stack"),
                "workdir": boot.get("workdir"),
                "start_cmd": boot.get("start_cmd"),
                "port": boot.get("port"),
                "detection_notes": boot.get("detection_notes", []),
            },
            "implementation_plan": coding.get("implementation_plan"),
            "changed_files": changed_summary,
            "added_test_files": [f.get("path") for f in test_files],
            "spec_summary": {
                "key_files_to_modify": assessment.get("key_files_to_modify"),
                "acceptance_criteria": assessment.get("acceptance_criteria"),
            },
        },
        indent=2,
    )


class QAAgent:
    """Multi-turn adversarial QA agent. Runs entirely inside the GH Actions worker."""

    def __init__(
        self,
        runner: LocalRunner,
        emit: Optional[Callable[[dict], None]] = None,
        model: str = QA_MODEL,
        max_turns: int = QA_MAX_TOOL_TURNS,
    ):
        self.runner = runner
        self.model = model
        self.max_turns = max_turns
        self.emit = emit or (lambda evt: None)
        self.findings: list[dict] = []
        self.tests_written: list[dict] = []
        self.screenshots: list[str] = []
        self.tool_calls_made = 0

    async def _dispatch_tool(self, name: str, args: dict) -> tuple[str, bool]:
        self.tool_calls_made += 1
        try:
            if name == "read_file":
                text = await self.runner.read_file(args["path"])
                if len(text) > 12000:
                    text = text[:12000] + f"\n\n... [truncated, {len(text)} bytes total]"
                return text, False

            if name == "bash":
                res = await self.runner.exec(args["cmd"], timeout=args.get("timeout_seconds", 30))
                return json.dumps(res.to_dict()), False

            if name == "http":
                res = await self.runner.http(
                    args["method"], args["path"],
                    body=args.get("body"), headers=args.get("headers"),
                )
                return json.dumps(res), False

            if name == "playwright":
                res = await self.runner.playwright(args["name"], args["script"])
                self.tests_written.append({"name": res.name, "passed": res.passed})
                self.screenshots.extend(res.screenshots)
                return json.dumps(res.to_dict()), False

            if name == "record_finding":
                finding = {
                    "severity": args["severity"],
                    "category": args["category"],
                    "title": args["title"],
                    "repro": args["repro"],
                    "evidence": args["evidence"],
                    "file": args.get("file"),
                }
                self.findings.append(finding)
                self.emit({"type": "qa_finding", "finding": finding})
                return json.dumps({"recorded": True, "total_findings": len(self.findings)}), False

            if name == "finish":
                return json.dumps({"acknowledged": True}), False

            return f"Unknown tool: {name}", True
        except QARunnerError as e:
            return f"QARunnerError: {e}", True
        except Exception as e:
            logger.exception("QA tool %s raised", name)
            return f"Tool error: {type(e).__name__}: {e}", True

    def _final_verdict(self, claimed_verdict: Optional[str]) -> str:
        critical_or_major = any(f["severity"] in ("critical", "major") for f in self.findings)
        if critical_or_major:
            return "QA_FAIL"
        if claimed_verdict in ("QA_PASS", "QA_FAIL"):
            return claimed_verdict
        return "QA_PASS"

    async def run(self, context: dict) -> dict:
        client = anthropic.AsyncAnthropic()
        started_at = datetime.now(timezone.utc)
        user_message = _format_initial_user_message(context)
        messages = [{"role": "user", "content": user_message}]

        total_input_tokens = 0
        total_output_tokens = 0
        claimed_verdict: Optional[str] = None
        claimed_summary: Optional[str] = None
        finished = False
        last_text = ""
        turn = 0

        for turn in range(self.max_turns):
            response = None
            for attempt in range(MAX_RETRIES):
                try:
                    response = await client.messages.create(
                        model=self.model,
                        max_tokens=QA_MODEL_MAX_TOKENS,
                        system=SYSTEM_PROMPT,
                        tools=TOOLS,
                        messages=messages,
                        timeout=API_TIMEOUT,
                    )
                    break
                except anthropic.APITimeoutError:
                    raise RuntimeError(f"QA agent turn {turn} timed out after {API_TIMEOUT}s")
                except (anthropic.APIConnectionError, anthropic.RateLimitError):
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                    else:
                        raise
                except anthropic.APIStatusError as e:
                    if e.status_code >= 500 and attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                    else:
                        raise

            total_input_tokens += response.usage.input_tokens
            total_output_tokens += response.usage.output_tokens

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            texts = [b.text for b in response.content if b.type == "text"]
            if texts:
                last_text = texts[-1]

            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn" and not tool_uses:
                break
            if not tool_uses:
                break

            tool_results = []
            for tu in tool_uses:
                self.emit({
                    "type": "qa_tool_use",
                    "tool": tu.name,
                    "turn": turn,
                    "input_preview": _preview(tu.input),
                })
                result_text, is_error = await self._dispatch_tool(tu.name, tu.input or {})
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": result_text,
                    "is_error": is_error,
                })
                if tu.name == "finish":
                    claimed_verdict = (tu.input or {}).get("verdict")
                    claimed_summary = (tu.input or {}).get("summary")
                    finished = True

            messages.append({"role": "user", "content": tool_results})
            if finished:
                break

        verdict = self._final_verdict(claimed_verdict)
        completed_at = datetime.now(timezone.utc)
        summary = claimed_summary or (
            f"QA completed after {self.tool_calls_made} tool calls with {len(self.findings)} findings."
        )
        return {
            "verdict": verdict,
            "summary": summary,
            "findings": self.findings,
            "tests_written": self.tests_written,
            "screenshots": self.screenshots,
            "tool_calls": self.tool_calls_made,
            "turns_used": turn + 1,
            "explicit_finish": finished,
            "last_model_message": last_text[:2000],
            "model": self.model,
            "tokens_used": total_input_tokens + total_output_tokens,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "duration_seconds": (completed_at - started_at).total_seconds(),
        }
