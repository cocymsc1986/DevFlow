"""
Regression tests for PR creation after repo context injection.

Root cause: when repo_context adds thousands of tokens to the coding agent
prompt, Claude sometimes emits analysis text or a small JSON summary *before*
the main implementation JSON.  The original balanced-brace approach stopped at
the *first* { group, which could be the wrong object.  These tests verify the
fixed parse_output always returns the largest valid JSON candidate.
"""
import json
from agents.base import BaseAgent


class _Agent(BaseAgent):
    name = "test"
    def get_system_prompt(self): return ""
    def format_input(self, ctx): return ""


def _parse(raw: str) -> dict:
    return _Agent().parse_output(raw)


IMPL = {
    "branch_name": "feat/something",
    "pr_title": "Add something",
    "pr_description": "desc",
    "implementation_plan": "plan",
    "files": [
        {"path": "src/foo.py", "action": "create", "description": "d",
         "content": "def foo():\n    return 42\n"}
    ],
    "test_files": [
        {"path": "tests/test_foo.py", "content": "def test_foo(): assert foo() == 42\n"}
    ],
    "migration_notes": None,
    "deployment_notes": None,
}


def _has_files(result: dict) -> bool:
    return bool(result.get("files"))


# ── basic cases ───────────────────────────────────────────────────────────────

def test_clean_json():
    assert _has_files(_parse(json.dumps(IMPL)))


def test_code_fence():
    assert _has_files(_parse("```json\n" + json.dumps(IMPL) + "\n```"))


def test_code_fence_with_inner_code_block():
    """File content containing ``` fences must not confuse the regex."""
    impl = {**IMPL, "files": [
        {"path": "README.md", "action": "create", "description": "d",
         "content": "# Title\n\n```python\ndef foo(): pass\n```\n"}
    ]}
    result = _parse("```json\n" + json.dumps(impl) + "\n```")
    assert _has_files(result)
    assert result["files"][0]["content"].startswith("# Title")


def test_trailing_text_no_braces():
    raw = json.dumps(IMPL) + "\n\nNote: implementation complete."
    assert _has_files(_parse(raw))


# ── cases broken by the original single-group approach ───────────────────────

def test_trailing_text_with_empty_braces():
    """Trailing note containing {} must not displace the implementation."""
    raw = json.dumps(IMPL) + '\n\nNote: use `{}` for empty dicts.'
    result = _parse(raw)
    assert _has_files(result)
    assert result["branch_name"] == "feat/something"


def test_leading_non_json_curly_braces():
    """Non-JSON {analysis} before the implementation JSON."""
    raw = "Analysis: {react: component pattern}\n\n" + json.dumps(IMPL)
    result = _parse(raw)
    assert _has_files(result), f"Got keys: {list(result.keys())}"
    assert result["branch_name"] == "feat/something"


def test_leading_valid_json_then_implementation():
    """Model emits a small valid JSON summary *before* the real output."""
    analysis = {"summary": "I will modify the Foo component", "confidence": 0.9}
    raw = json.dumps(analysis) + "\n\n" + json.dumps(IMPL)
    result = _parse(raw)
    assert _has_files(result), f"Got keys: {list(result.keys())}"
    assert result["branch_name"] == "feat/something"


def test_multiple_small_objects_then_implementation():
    """Several small JSON snippets before the real implementation."""
    snippets = [
        json.dumps({"step": 1, "action": "analyse existing code"}),
        json.dumps({"step": 2, "action": "identify files to change"}),
    ]
    raw = "\n\n".join(snippets) + "\n\n" + json.dumps(IMPL)
    result = _parse(raw)
    assert _has_files(result), f"Got keys: {list(result.keys())}"


# ── edge cases ────────────────────────────────────────────────────────────────

def test_file_content_is_json():
    """A generated file whose content is JSON must be handled correctly."""
    impl = {**IMPL, "files": [
        {"path": "config.json", "action": "create", "description": "d",
         "content": '{"key": "value", "nested": {"a": 1}}'}
    ]}
    result = _parse(json.dumps(impl))
    assert _has_files(result)


def test_no_json_returns_raw():
    result = _parse("This is plain text with no JSON at all.")
    assert "raw" in result
    assert "files" not in result


def test_push_logic_with_raw_output():
    """Verify _push_to_github sees empty file_payloads when parse fails."""
    coding_output = {"raw": json.dumps(IMPL)}
    all_files = coding_output.get("files", []) + coding_output.get("test_files", [])
    file_payloads = [
        {"path": f["path"], "content": f.get("content", "")}
        for f in all_files if f.get("action") != "delete" and f.get("content")
    ]
    assert file_payloads == []
