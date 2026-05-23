"""Tests for the eval scorer — runs offline without API calls."""

from eval.scorer import score_output


def _case(checks=None, repo_tree=None):
    return {
        "name": "test",
        "repo_tree": repo_tree or [],
        "checks": checks or {},
    }


def test_perfect_integration_score():
    coding_output = {
        "branch_name": "feat/foo",
        "pr_title": "Add foo",
        "files": [
            {"path": "src/app.py", "action": "modify", "content": "..."},
        ],
        "test_files": [],
    }
    case = _case(
        checks={"must_modify": ["src/app.py"]},
        repo_tree=["src/app.py", "src/utils.py"],
    )
    result = score_output(coding_output, case)
    assert result["scores"]["integration"] == 1.0


def test_missed_integration():
    coding_output = {
        "branch_name": "feat/foo",
        "pr_title": "Add foo",
        "files": [
            {"path": "src/new_thing.py", "action": "create", "content": "..."},
        ],
        "test_files": [],
    }
    case = _case(
        checks={"must_modify": ["src/app.py"]},
        repo_tree=["src/app.py"],
    )
    result = score_output(coding_output, case)
    assert result["scores"]["integration"] == 0.0


def test_no_duplicate_penalty():
    coding_output = {
        "branch_name": "feat/foo",
        "pr_title": "Add foo",
        "files": [
            {"path": "src/app.py", "action": "create", "content": "..."},
        ],
        "test_files": [],
    }
    case = _case(repo_tree=["src/app.py", "src/utils.py"])
    result = score_output(coding_output, case)
    assert result["scores"]["no_duplicate"] < 1.0
    assert "src/app.py" in result["details"]["no_duplicate"]["created_existing_files"]


def test_correct_action_accuracy():
    coding_output = {
        "branch_name": "feat/foo",
        "pr_title": "Add foo",
        "files": [
            {"path": "src/existing.py", "action": "modify", "content": "..."},
            {"path": "src/brand_new.py", "action": "create", "content": "..."},
        ],
        "test_files": [],
    }
    case = _case(repo_tree=["src/existing.py"])
    result = score_output(coding_output, case)
    assert result["scores"]["action_accuracy"] == 1.0


def test_wrong_action_accuracy():
    coding_output = {
        "branch_name": "feat/foo",
        "pr_title": "Add foo",
        "files": [
            {"path": "src/existing.py", "action": "create", "content": "..."},
        ],
        "test_files": [],
    }
    case = _case(repo_tree=["src/existing.py"])
    result = score_output(coding_output, case)
    assert result["scores"]["action_accuracy"] == 0.0


def test_file_coverage_matching():
    coding_output = {
        "branch_name": "feat/foo",
        "pr_title": "Add foo",
        "files": [
            {"path": "src/routes/users.ts", "action": "create", "content": "..."},
        ],
        "test_files": [],
    }
    case = _case(checks={"expect_files_matching": ["src/routes/users"]})
    result = score_output(coding_output, case)
    assert result["scores"]["file_coverage"] == 1.0


def test_test_framework_detection_jest():
    coding_output = {
        "branch_name": "feat/foo",
        "pr_title": "Add foo",
        "files": [],
        "test_files": [
            {"path": "tests/foo.test.ts", "content": 'describe("foo", () => { it("works", () => { expect(1).toBe(1); }); });'},
        ],
    }
    case = _case(checks={"test_framework": "jest"})
    result = score_output(coding_output, case)
    assert result["scores"]["test_framework"] >= 0.8


def test_test_framework_detection_pytest():
    coding_output = {
        "branch_name": "feat/foo",
        "pr_title": "Add foo",
        "files": [],
        "test_files": [
            {"path": "tests/test_foo.py", "content": "import pytest\n\ndef test_something():\n    assert 1 == 1\n"},
        ],
    }
    case = _case(checks={"test_framework": "pytest"})
    result = score_output(coding_output, case)
    assert result["scores"]["test_framework"] >= 0.8


def test_format_score_all_keys():
    coding_output = {
        "branch_name": "feat/foo",
        "pr_title": "Add foo",
        "files": [],
        "test_files": [],
    }
    result = score_output(coding_output, _case())
    assert result["scores"]["format"] == 1.0


def test_format_score_missing_keys():
    coding_output = {"raw": "something went wrong"}
    result = score_output(coding_output, _case())
    assert result["scores"]["format"] < 1.0


def test_overall_is_weighted():
    coding_output = {
        "branch_name": "feat/foo",
        "pr_title": "Add foo",
        "files": [
            {"path": "src/app.py", "action": "modify", "content": "..."},
        ],
        "test_files": [
            {"path": "tests/test_app.py", "content": "def test_it(): assert True"},
        ],
    }
    case = _case(
        checks={"must_modify": ["src/app.py"], "test_framework": "pytest"},
        repo_tree=["src/app.py"],
    )
    result = score_output(coding_output, case)
    assert 0.0 < result["scores"]["overall"] <= 1.0
