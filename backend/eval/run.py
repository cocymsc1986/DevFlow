"""Offline evaluation runner for DevFlow coding agent accuracy.

Runs test cases through assessment → coding → PR review and scores the results.
Does not require GitHub integration or a running server.

Usage:
    python -m eval.run                    # Run all cases
    python -m eval.run --case add-endpoint  # Run one case
    python -m eval.run --list             # List available cases
    python -m eval.run --coding-model claude-sonnet-4-6
"""

import argparse
import asyncio
import importlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.assessment import AssessmentAgent
from agents.coding import CodingAgent
from agents.pr_review import PRReviewAgent
from eval.scorer import score_output


CASES_DIR = Path(__file__).parent / "cases"
RESULTS_DIR = Path(__file__).parent / "results"


def load_cases() -> list[dict]:
    cases = []
    for f in sorted(CASES_DIR.glob("*.py")):
        if f.name.startswith("_"):
            continue
        module_name = f"eval.cases.{f.stem}"
        mod = importlib.import_module(module_name)
        if hasattr(mod, "CASE"):
            cases.append(mod.CASE)
    return cases


def build_context(case: dict) -> dict:
    """Build a pipeline context from an eval case, simulating intake output."""
    issue = case["issue"]
    return {
        "title": issue["title"],
        "description": issue["description"],
        "issue_type": issue["issue_type"],
        "has_ui": issue.get("has_ui", False),
        "intake": {
            "title": issue["title"],
            "description": issue["description"],
            "issue_type": issue["issue_type"],
            "has_ui": issue.get("has_ui", False),
            "requires_design_input": False,
            "acceptance_criteria": [issue["description"]],
            "constraints": [],
            "dependencies": [],
            "summary": issue["description"],
        },
        "repo_tree": case.get("repo_tree", []),
    }


def build_repo_context(case: dict) -> dict:
    """Build repo_context from eval case's repo_files."""
    files = []
    for path, content in case.get("repo_files", {}).items():
        files.append({"path": path, "content": content})
    return {"files": files}


async def run_case(case: dict, coding_model: str, review_model: str, verbose: bool = False) -> dict:
    """Run a single eval case through assessment → coding → review."""
    print(f"\n{'='*60}")
    print(f"  Case: {case['name']}")
    print(f"  {case['description']}")
    print(f"  Coding model: {coding_model}")
    print(f"{'='*60}")

    context = build_context(case)

    # Step 1: Assessment
    print("  [1/3] Running assessment agent...")
    assessment_agent = AssessmentAgent()
    try:
        assessment_result = await assessment_agent.run(context)
        context["assessment"] = assessment_result["output"]
        assessment_tokens = assessment_result.get("tokens_used", 0)
        print(f"        Done ({assessment_tokens} tokens)")
        if verbose:
            print(f"        key_files_to_read: {context['assessment'].get('key_files_to_read', [])}")
            print(f"        key_files_to_modify: {context['assessment'].get('key_files_to_modify', [])}")
    except Exception as e:
        print(f"        FAILED: {e}")
        return {"case": case["name"], "error": f"assessment failed: {e}", "scores": {}}

    # Step 2: Coding
    print("  [2/3] Running coding agent...")
    context["repo_context"] = build_repo_context(case)
    coding_agent = CodingAgent(model=coding_model)
    try:
        coding_result = await coding_agent.run(context)
        context["coding"] = coding_result["output"]
        coding_tokens = coding_result.get("tokens_used", 0)
        print(f"        Done ({coding_tokens} tokens)")
        if verbose:
            output_files = context["coding"].get("files", [])
            print(f"        Files: {[(f.get('path'), f.get('action')) for f in output_files]}")
    except Exception as e:
        print(f"        FAILED: {e}")
        return {"case": case["name"], "error": f"coding failed: {e}", "scores": {}}

    # Step 3: PR Review
    print("  [3/3] Running PR review agent...")
    review_agent = PRReviewAgent(model=review_model)
    try:
        review_result = await review_agent.run(context)
        review_output = review_result["output"]
        review_tokens = review_result.get("tokens_used", 0)
        print(f"        Done ({review_tokens} tokens)")
        print(f"        Verdict: {review_output.get('verdict', 'UNKNOWN')}")
    except Exception as e:
        print(f"        FAILED: {e}")
        review_output = {}

    # Score
    coding_output = context.get("coding", {})
    eval_scores = score_output(coding_output, case)
    review_scores = {
        "correctness": review_output.get("correctness_score"),
        "quality": review_output.get("quality_score"),
        "test_coverage": review_output.get("test_coverage_score"),
        "security": review_output.get("security_score"),
        "integration": review_output.get("integration_score"),
        "verdict": review_output.get("verdict"),
    }

    total_tokens = assessment_tokens + coding_tokens + review_tokens

    result = {
        "case": case["name"],
        "coding_model": coding_model,
        "review_model": review_model,
        "eval_scores": eval_scores["scores"],
        "eval_details": eval_scores["details"],
        "review_scores": review_scores,
        "review_blocking_issues": review_output.get("blocking_issues", []),
        "total_tokens": total_tokens,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Print summary
    print(f"\n  Eval Scores:")
    for dim, val in eval_scores["scores"].items():
        bar = "█" * int(val * 20) + "░" * (20 - int(val * 20))
        print(f"    {dim:20s} {bar} {val:.2f}")
    if review_scores.get("verdict"):
        print(f"\n  Review Verdict: {review_scores['verdict']}")
    if review_output.get("blocking_issues"):
        print(f"  Blocking Issues: {len(review_output['blocking_issues'])}")
        for issue in review_output["blocking_issues"][:3]:
            print(f"    - [{issue.get('severity')}] {issue.get('file')}: {issue.get('issue', '')[:80]}")
    print(f"  Total Tokens: {total_tokens}")

    return result


async def main():
    parser = argparse.ArgumentParser(description="DevFlow offline evaluation")
    parser.add_argument("--case", help="Run a specific case by name")
    parser.add_argument("--list", action="store_true", help="List available cases")
    parser.add_argument("--coding-model", default="claude-sonnet-4-6", help="Model for coding agent")
    parser.add_argument("--review-model", default="claude-sonnet-4-6", help="Model for PR review agent")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    parser.add_argument("--save", action="store_true", help="Save results to eval/results/")
    args = parser.parse_args()

    cases = load_cases()

    if args.list:
        print("Available eval cases:")
        for c in cases:
            print(f"  {c['name']:30s} {c['description']}")
        return

    if args.case:
        cases = [c for c in cases if c["name"] == args.case]
        if not cases:
            print(f"Case '{args.case}' not found. Use --list to see available cases.")
            return

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable is required.")
        return

    results = []
    for case in cases:
        result = await run_case(case, args.coding_model, args.review_model, args.verbose)
        results.append(result)

    # Summary
    print(f"\n{'='*60}")
    print(f"  SUMMARY ({len(results)} cases)")
    print(f"{'='*60}")

    overall_scores = [r["eval_scores"].get("overall", 0) for r in results if "eval_scores" in r]
    if overall_scores:
        avg = sum(overall_scores) / len(overall_scores)
        print(f"  Average overall score: {avg:.2f}")
        for r in results:
            score = r.get("eval_scores", {}).get("overall", 0)
            status = "PASS" if score >= 0.7 else "FAIL"
            verdict = r.get("review_scores", {}).get("verdict", "N/A")
            print(f"    {r['case']:30s} {score:.2f} [{status}]  review: {verdict}")

    total_tokens = sum(r.get("total_tokens", 0) for r in results)
    print(f"\n  Total tokens used: {total_tokens}")

    if args.save:
        RESULTS_DIR.mkdir(exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_path = RESULTS_DIR / f"eval_{timestamp}.json"
        summary = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "coding_model": args.coding_model,
            "review_model": args.review_model,
            "average_overall": avg if overall_scores else None,
            "total_tokens": total_tokens,
            "results": results,
        }
        with open(out_path, "w") as f:
            json.dump(summary, f, indent=2)
        print(f"\n  Results saved to {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
