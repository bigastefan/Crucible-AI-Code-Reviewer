"""Phase 5 — the fail-open guarantee on the POSTING path (T1-18 / GP-10).

A missing/bad LLM key, a posting error, or an unmatched repo must NEVER block a merge:
crucible exits 0 and (best-effort) posts a 'review unavailable' note.
"""
import json
from pathlib import Path

import pytest

import crucible
from core import llm
from core.config import load_config, match_repo
from providers.base import GitProvider

ROOT = Path(__file__).resolve().parent.parent
DIFF = (ROOT / "tests" / "fixtures" / "modify.diff").read_text()
VALID = json.dumps({
    "summary": "ok", "overall_risk": "low",
    "findings": [{"file": "calc.py", "line": 2, "severity": "high", "category": "bug",
                  "title": "t", "comment": "c"}],
})


class FakeProvider(GitProvider):
    def __init__(self, raise_on_diff=False, raise_on_post=False):
        self.raise_on_diff = raise_on_diff
        self.raise_on_post = raise_on_post
        self.summaries = []
        self.statuses = []
        self.posted = []

    def get_diff(self):
        if self.raise_on_diff:
            raise RuntimeError("git diff exploded")
        return DIFF

    def existing_findings(self):
        return []

    def delete_inline(self, ref):
        pass

    def post_inline(self, finding):
        if self.raise_on_post:
            raise RuntimeError("403 Forbidden (read-only token on fork PR)")
        self.posted.append(finding)

    def upsert_summary(self, markdown):
        self.summaries.append(markdown)

    def set_status(self, state, note):
        self.statuses.append((state, note))


def _args(extra=None):
    return crucible.parse_args(["--pr", "1", "--repo", "Focus Backend"] + (extra or []))


def _cfg():
    return load_config(ROOT / "config.yaml")


def test_failopen_when_llm_key_missing(monkeypatch):
    """Empty/bad ANTHROPIC_API_KEY → LLM call raises → review unavailable, exit 0."""
    def boom(*a, **k):
        raise RuntimeError("AuthenticationError: missing api key")

    monkeypatch.setattr(llm, "complete", boom)
    prov = FakeProvider()
    monkeypatch.setattr(crucible, "get_provider", lambda *a, **k: prov)

    cfg = _cfg()
    rc = crucible.run_post(cfg, match_repo(cfg, "Focus Backend"), "github", _args())
    assert rc == 0
    # The review-unavailable note still gets upserted (reviewer fails safe, then poster posts it).
    assert prov.summaries and "unavailable" in prov.summaries[-1].lower()
    assert prov.posted == []  # no findings produced


def test_failopen_when_posting_raises(monkeypatch):
    """Valid review but the inline POST fails (e.g. read-only token) → exit 0, note posted."""
    monkeypatch.setattr(llm, "complete", lambda *a, **k: VALID)
    prov = FakeProvider(raise_on_post=True)
    monkeypatch.setattr(crucible, "get_provider", lambda *a, **k: prov)

    cfg = _cfg()
    rc = crucible.run_post(cfg, match_repo(cfg, "Focus Backend"), "github", _args())
    assert rc == 0
    assert prov.summaries  # fell into the except → posted the 'unavailable' note


def test_failopen_when_diff_acquisition_raises(monkeypatch):
    monkeypatch.setattr(crucible, "get_provider", lambda *a, **k: FakeProvider(raise_on_diff=True))
    cfg = _cfg()
    rc = crucible.run_post(cfg, match_repo(cfg, "Focus Backend"), "github", _args())
    assert rc == 0


def test_failopen_when_provider_construction_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no credentials")

    monkeypatch.setattr(crucible, "get_provider", boom)
    cfg = _cfg()
    rc = crucible.run_post(cfg, match_repo(cfg, "Focus Backend"), "github", _args())
    assert rc == 0


def test_unmatched_repo_failopen_on_posting_path():
    # Non-dry-run + unmatched repo must exit 0 (a missing config entry can't block merges).
    rc = crucible.main(["--pr", "1", "--repo", "no-such-repo-xyz"])
    assert rc == 0


def test_unmatched_repo_returns_2_in_dry_run():
    rc = crucible.main(["--pr", "1", "--repo", "no-such-repo-xyz", "--dry-run"])
    assert rc == 2
