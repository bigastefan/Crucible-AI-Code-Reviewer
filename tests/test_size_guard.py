"""Phase 6 — size guards (GP-05 / T1-09): oversized PR → graceful notice, no model call."""
from pathlib import Path

import pytest

from core import engine
from core.config import load_config, match_repo

ROOT = Path(__file__).resolve().parent.parent
DIFF = (ROOT / "tests" / "fixtures" / "modify.diff").read_text()


def _cfg(max_lines=4000, max_tokens=60000):
    cfg = load_config(ROOT / "config.yaml")
    cfg.review.max_diff_lines = max_lines
    cfg.review.max_diff_tokens = max_tokens
    return cfg


def _boom(*a, **k):
    raise AssertionError("LLM must NOT be called when the diff is too large")


def test_line_guard_skips_llm_with_notice():
    cfg = _cfg(max_lines=1)
    repo = match_repo(cfg, "Focus Backend")
    result, files = engine.run_review(cfg, repo, DIFF, complete_fn=_boom)
    assert "too large" in result.summary.lower()
    assert files  # still parsed


def test_token_guard_skips_llm_with_notice():
    cfg = _cfg(max_tokens=1)
    repo = match_repo(cfg, "Focus Backend")
    result, _ = engine.run_review(cfg, repo, DIFF, complete_fn=_boom)
    assert "too large" in result.summary.lower()


def test_within_limits_calls_llm():
    cfg = _cfg()
    repo = match_repo(cfg, "Focus Backend")
    called = {"n": 0}

    def fake(*a, **k):
        called["n"] += 1
        return '{"summary":"ok","overall_risk":"low","findings":[]}'

    engine.run_review(cfg, repo, DIFF, complete_fn=fake)
    assert called["n"] == 1
