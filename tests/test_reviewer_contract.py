"""Phase 2 — the JSON output contract: validate, coerce to canonical enums, fail safe.
A malformed model response must NEVER raise (§10)."""
import json

from core.models import Category, OverallRisk, Severity
from core.reviewer import parse_review, review

VALID = json.dumps({
    "summary": "Adds a helper and a test.",
    "overall_risk": "low",
    "findings": [
        {"file": "a.py", "line": 12, "severity": "high", "category": "bug",
         "title": "Null deref", "comment": "x may be None", "suggestion": "if x:"},
    ],
})


def test_parses_valid_contract():
    r = parse_review(VALID)
    assert r.error is None
    assert r.overall_risk is OverallRisk.LOW
    assert len(r.findings) == 1
    f = r.findings[0]
    assert f.file == "a.py" and f.line == 12
    assert f.severity is Severity.HIGH and f.category is Category.BUG
    assert f.suggestion == "if x:"


def test_strips_json_code_fence():
    r = parse_review("```json\n" + VALID + "\n```")
    assert r.error is None and len(r.findings) == 1


def test_extracts_json_amid_prose():
    r = parse_review("Sure! Here is the review:\n" + VALID + "\nHope that helps.")
    assert r.error is None and len(r.findings) == 1


def test_malformed_json_fails_safe():
    r = parse_review("{ this is not valid json ")
    assert r.error is not None
    assert "could not parse" in r.summary.lower()
    assert r.findings == []


def test_non_object_fails_safe():
    r = parse_review("[1, 2, 3]")
    assert r.error == "not_a_json_object"


def test_coerces_out_of_set_enums():
    raw = json.dumps({
        "summary": "x", "overall_risk": "critical",  # not in OverallRisk → clamps to high
        "findings": [
            {"file": "a", "line": 1, "severity": "blocker", "category": "perf",
             "title": "t", "comment": "c"},
        ],
    })
    r = parse_review(raw)
    assert r.overall_risk is OverallRisk.HIGH
    assert r.findings[0].severity is Severity.CRITICAL
    assert r.findings[0].category is Category.PERFORMANCE


def test_drops_unanchorable_findings():
    raw = json.dumps({
        "summary": "x", "overall_risk": "low",
        "findings": [
            {"file": "a", "severity": "low", "category": "style", "title": "t", "comment": "c"},  # no line
            {"line": 5, "severity": "low", "category": "style", "title": "t", "comment": "c"},     # no file
            {"file": "b", "line": "not-an-int", "severity": "low", "category": "style", "title": "t", "comment": "c"},
            {"file": "c", "line": 9, "severity": "low", "category": "style", "title": "ok", "comment": "c"},
        ],
    })
    r = parse_review(raw)
    assert [f.file for f in r.findings] == ["c"]


def test_null_suggestion_normalized():
    raw = json.dumps({
        "summary": "x", "overall_risk": "low",
        "findings": [{"file": "a", "line": 1, "severity": "low", "category": "style",
                      "title": "t", "comment": "c", "suggestion": "null"}],
    })
    assert parse_review(raw).findings[0].suggestion is None


def test_missing_findings_list_is_empty():
    r = parse_review(json.dumps({"summary": "ok", "overall_risk": "low"}))
    assert r.error is None and r.findings == []


def test_review_is_fail_open_on_llm_error():
    def boom(model, system, user, max_tokens):
        raise RuntimeError("bad key")

    r = review("anthropic/claude-sonnet-4-6", "sys", "usr", complete_fn=boom)
    assert r.error == "bad key"
    assert "unavailable" in r.summary.lower()
    assert r.findings == []


def test_review_with_fake_complete_fn():
    r = review("any/model", "sys", "usr", complete_fn=lambda *_: VALID)
    assert r.error is None and len(r.findings) == 1
