"""Phase 6 — the shared engine path: nothing-to-review, finding merge, kill switch,
draft-PR skip (GP-06 / T1-12 / T1-13)."""
import json
from pathlib import Path

import crucible
from core import engine
from core.config import load_config, match_repo
from core.models import Category, PRContext, Severity
from providers.base import GitProvider

ROOT = Path(__file__).resolve().parent.parent


def _cfg():
    return load_config(ROOT / "config.yaml")


# --- GP-06: excluded-only diff → nothing to review (no LLM call) ---------------
EXCLUDED_DIFF = (
    "diff --git a/package-lock.json b/package-lock.json\n"
    "--- a/package-lock.json\n+++ b/package-lock.json\n"
    "@@ -1,1 +1,2 @@\n {\n+  \"x\": 1\n"
)


def test_nothing_to_review_when_only_excluded():
    cfg = _cfg()
    repo = match_repo(cfg, "Focus Backend")
    result, files = engine.run_review(cfg, repo, EXCLUDED_DIFF, complete_fn=lambda *a: (_ for _ in ()).throw(AssertionError()))
    assert files == []
    assert "nothing to review" in result.summary.lower()


# --- secret findings are merged ahead of model findings ------------------------
SECRET_DIFF = (
    "diff --git a/cfg.py b/cfg.py\n--- a/cfg.py\n+++ b/cfg.py\n"
    "@@ -1,1 +1,2 @@\n print()\n"
    '+token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"\n'
)


def test_secret_findings_prepended():
    cfg = _cfg()
    repo = match_repo(cfg, "Focus Backend")

    def model(*a, **k):
        return json.dumps({"summary": "s", "overall_risk": "low", "findings": [
            {"file": "cfg.py", "line": 2, "severity": "low", "category": "style",
             "title": "style nit", "comment": "c"}]})

    result, _ = engine.run_review(cfg, repo, SECRET_DIFF, complete_fn=model)
    assert result.findings[0].category is Category.SECURITY
    assert result.findings[0].severity is Severity.CRITICAL


# --- T1-12: master kill switch -------------------------------------------------
def test_kill_switch_posts_nothing(tmp_path, capsys):
    cfg_text = (
        "model:\n  default: anthropic/claude-sonnet-4-6\n"
        "agent:\n  enabled: false\n"
        "repos:\n  - name: A\n    provider: azure\n    match: A\n    project_rules: a\n"
    )
    p = tmp_path / "config.yaml"
    p.write_text(cfg_text)
    rc = crucible.main(["--pr", "1", "--repo", "A", "--config", str(p), "--dry-run"])
    assert rc == 0
    assert "disabled" in capsys.readouterr().out.lower()


# --- T1-13: draft-PR skip ------------------------------------------------------
class DraftProvider(GitProvider):
    def __init__(self):
        self.posted = []
        self.summaries = []

    def get_pr_context(self):
        return PRContext(repo="x", pr_id=1, is_draft=True)

    def get_diff(self):
        raise AssertionError("draft PR must be skipped before diff acquisition")

    def existing_finding_hashes(self):
        return set()

    def post_inline(self, finding):
        self.posted.append(finding)

    def upsert_summary(self, md):
        self.summaries.append(md)

    def set_status(self, state, note):
        pass


def test_draft_pr_skipped(monkeypatch):
    prov = DraftProvider()
    monkeypatch.setattr(crucible, "get_provider", lambda *a, **k: prov)
    cfg = _cfg()
    args = crucible.parse_args(["--pr", "1", "--repo", "Focus Backend"])
    rc = crucible.run_post(cfg, match_repo(cfg, "Focus Backend"), "azure", args)
    assert rc == 0
    assert prov.posted == [] and prov.summaries == []
