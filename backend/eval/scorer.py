"""Deterministic scorer for coding agent output against eval case expectations."""

import re


def score_output(coding_output: dict, case: dict) -> dict:
    """Score a coding agent's output against a test case's expected outcomes.

    Returns a dict with individual dimension scores (0.0-1.0) and an overall score.
    """
    checks = case.get("checks", {})
    repo_tree = case.get("repo_tree", [])
    scores = {}
    details = {}

    output_files = coding_output.get("files", [])
    output_tests = coding_output.get("test_files", [])
    all_output_files = output_files + output_tests
    output_paths = [f.get("path", "") for f in all_output_files]
    output_actions = {f.get("path", ""): f.get("action", "create") for f in output_files}

    # 1. Format score — valid structure with required keys
    required_keys = ["branch_name", "pr_title", "files"]
    present = sum(1 for k in required_keys if k in coding_output)
    scores["format"] = present / len(required_keys)
    details["format"] = {
        "required": required_keys,
        "present": [k for k in required_keys if k in coding_output],
        "missing": [k for k in required_keys if k not in coding_output],
    }

    # 2. Integration score — did it modify the files it should have?
    must_modify = checks.get("must_modify", [])
    if must_modify:
        modified = []
        missed = []
        for path in must_modify:
            if path in output_paths and output_actions.get(path) == "modify":
                modified.append(path)
            elif path in output_paths:
                modified.append(path)  # at least touched it, even if action is wrong
            else:
                missed.append(path)
        scores["integration"] = len(modified) / len(must_modify) if must_modify else 1.0
        details["integration"] = {"expected": must_modify, "modified": modified, "missed": missed}
    else:
        scores["integration"] = 1.0
        details["integration"] = {"expected": [], "modified": [], "missed": []}

    # 3. No-duplicate score — avoided creating files that already exist
    should_not_create = checks.get("should_not_create", [])
    existing_paths_set = set(repo_tree)
    created_existing = []
    for f in output_files:
        path = f.get("path", "")
        action = f.get("action", "create")
        if action == "create" and path in existing_paths_set:
            created_existing.append(path)
    for path in should_not_create:
        if path in output_paths and output_actions.get(path) == "create":
            if path not in created_existing:
                created_existing.append(path)

    if existing_paths_set:
        scores["no_duplicate"] = 1.0 if not created_existing else max(0.0, 1.0 - len(created_existing) / max(len(output_files), 1))
    else:
        scores["no_duplicate"] = 1.0
    details["no_duplicate"] = {"created_existing_files": created_existing}

    # 4. File coverage — produced files matching expected patterns
    expect_patterns = checks.get("expect_files_matching", [])
    if expect_patterns:
        matched = []
        unmatched = []
        for pattern in expect_patterns:
            found = any(re.search(pattern, p) for p in output_paths)
            if found:
                matched.append(pattern)
            else:
                unmatched.append(pattern)
        scores["file_coverage"] = len(matched) / len(expect_patterns)
        details["file_coverage"] = {"expected_patterns": expect_patterns, "matched": matched, "unmatched": unmatched}
    else:
        scores["file_coverage"] = 1.0
        details["file_coverage"] = {"expected_patterns": [], "matched": [], "unmatched": []}

    # 5. Test framework — do tests reference the correct framework?
    expected_framework = checks.get("test_framework")
    if expected_framework and output_tests:
        framework_indicators = {
            "jest": ["describe(", "it(", "expect(", "jest", "toBe(", "toEqual("],
            "pytest": ["def test_", "import pytest", "assert "],
            "vitest": ["describe(", "it(", "expect(", "vitest", "from 'vitest'"],
            "mocha": ["describe(", "it(", "chai", "should", "expect("],
            "go": ["func Test", "testing.T", "t.Run("],
        }
        indicators = framework_indicators.get(expected_framework, [])
        if indicators:
            test_content = " ".join(f.get("content", "") for f in output_tests)
            found = [ind for ind in indicators if ind in test_content]
            scores["test_framework"] = min(1.0, len(found) / max(2, len(indicators) // 2))
            details["test_framework"] = {
                "expected": expected_framework,
                "indicators_found": found,
                "indicators_checked": indicators,
            }
        else:
            scores["test_framework"] = 1.0
            details["test_framework"] = {"expected": expected_framework, "note": "no indicators defined"}
    else:
        scores["test_framework"] = 1.0 if not expected_framework else 0.0
        details["test_framework"] = {
            "expected": expected_framework,
            "has_tests": bool(output_tests),
        }

    # 6. Action accuracy — used correct action for each file
    action_correct = 0
    action_total = 0
    action_issues = []
    for f in output_files:
        path = f.get("path", "")
        action = f.get("action", "create")
        action_total += 1
        if path in existing_paths_set:
            if action == "modify":
                action_correct += 1
            else:
                action_issues.append(f"{path}: used '{action}' but file exists (should be 'modify')")
        else:
            if action == "create":
                action_correct += 1
            else:
                action_issues.append(f"{path}: used '{action}' but file doesn't exist (should be 'create')")
    scores["action_accuracy"] = action_correct / action_total if action_total > 0 else 1.0
    details["action_accuracy"] = {"correct": action_correct, "total": action_total, "issues": action_issues}

    # Overall weighted score
    weights = {
        "integration": 3.0,
        "no_duplicate": 2.0,
        "action_accuracy": 2.0,
        "file_coverage": 1.5,
        "test_framework": 1.0,
        "format": 0.5,
    }
    weighted_sum = sum(scores[k] * weights.get(k, 1.0) for k in scores)
    weight_total = sum(weights.get(k, 1.0) for k in scores)
    scores["overall"] = round(weighted_sum / weight_total, 4)

    return {"scores": scores, "details": details}
