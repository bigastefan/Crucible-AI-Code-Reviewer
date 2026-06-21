"""Phase 3 — posting orchestration: filter, dedup, summary upsert, gating.
Uses a FakeProvider so the provider-neutral logic is verified offline."""
from pathlib import Path

from core import dedup, poster
from core.config import load_config
from core.diff import parse_diff
from core.models import Category, Finding, OverallRisk, ReviewResult, Severity
from providers.base import GitProvider

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "fixtures" if (ROOT / "fixtures").exists() else ROOT / "tests" / "fixtures"


class FakeProvider(GitProvider):
    def __init__(self, existing=None):
        self.existing = set(existing or [])
        self.posted = []
        self.summaries = []
        self.statuses = []

    def existing_finding_hashes(self):
        return set(self.existing)

    def post_inline(self, finding):
        self.posted.append(finding)

    def upsert_summary(self, markdown):
        self.summaries.append(markdown)

    def set_status(self, state, note):
        self.statuses.append((state, note))


def _files():
    # modify.diff → calc.py, commentable right-side lines {2, 11, 12}
    return parse_diff((FIX / "modify.diff").read_text())


def _cfg(min_sev="low", fail="none", max_findings=30):
    cfg = load_config(ROOT / "config.yaml")
    cfg.review.min_severity_to_post = min_sev
    cfg.review.fail_check_on = fail
    cfg.review.max_findings = max_findings
    return cfg


def _finding(line, sev, title, file="calc.py", cat=Category.BUG):
    return Finding(file, line, sev, cat, title, "comment", None)


def _review(findings, risk=OverallRisk.LOW):
    return ReviewResult(summary="s", overall_risk=risk, findings=findings)


# --------------------------------------------------------------------------- selection
def test_drops_off_diff_findings():
    review = _review([
        _finding(2, Severity.HIGH, "on-diff"),
        _finding(5, Severity.HIGH, "off-diff"),  # line 5 not in {2,11,12}
    ])
    to_post, anchored, stats = poster.select_findings(review, _files(), _cfg().review, set())
    assert [f.title for f in to_post] == ["on-diff"]
    assert stats.skipped_unanchored == 1


def test_severity_filter():
    review = _review([
        _finding(2, Severity.LOW, "low"),
        _finding(11, Severity.HIGH, "high"),
    ])
    to_post, _, stats = poster.select_findings(review, _files(), _cfg(min_sev="medium").review, set())
    assert [f.title for f in to_post] == ["high"]
    assert stats.skipped_severity == 1


def test_dedup_against_existing_hashes():
    review = _review([_finding(11, Severity.HIGH, "high"), _finding(2, Severity.LOW, "low")])
    # First pass sets the content-based dedup hashes.
    first, _, _ = poster.select_findings(review, _files(), _cfg().review, set())
    high_hash = next(f.dedup_hash for f in first if f.title == "high")
    # Second pass: that finding is already on the PR → dropped.
    to_post, _, stats = poster.select_findings(review, _files(), _cfg().review, {high_hash})
    assert [f.title for f in to_post] == ["low"]
    assert stats.skipped_existing == 1


def test_dedup_holds_when_title_changes():
    # Same anchored line, model reworded the title → still deduped (the live GP-09 fix).
    first, _, _ = poster.select_findings(
        _review([_finding(11, Severity.HIGH, "Null deref")]), _files(), _cfg().review, set())
    h = first[0].dedup_hash
    reworded = _review([_finding(11, Severity.HIGH, "Possible null dereference here")])
    to_post, _, _ = poster.select_findings(reworded, _files(), _cfg().review, {h})
    assert to_post == []  # title changed, content identical → no duplicate


def test_cap_keeps_highest_severity():
    review = _review([
        _finding(2, Severity.LOW, "low"),
        _finding(11, Severity.CRITICAL, "crit"),
        _finding(12, Severity.MEDIUM, "med"),
    ])
    to_post, _, stats = poster.select_findings(review, _files(), _cfg(max_findings=1).review, set())
    assert [f.title for f in to_post] == ["crit"]  # sorted by severity desc, capped to 1
    assert stats.capped == 2


# --------------------------------------------------------------------------- post_review
def test_post_review_posts_and_upserts_one_summary():
    review = _review([_finding(2, Severity.LOW, "a"), _finding(11, Severity.HIGH, "b")])
    prov = FakeProvider()
    outcome = poster.post_review(prov, review, _files(), _cfg())
    assert outcome.posted == 2
    assert len(prov.posted) == 2
    assert len(prov.summaries) == 1
    assert dedup.text_has_summary_marker(prov.summaries[0])
    assert prov.statuses == [("succeeded", "Crucible review complete.")]


def test_gp09_second_push_posts_zero_duplicates():
    review = _review([_finding(2, Severity.LOW, "a"), _finding(11, Severity.HIGH, "b")])
    # First push.
    p1 = FakeProvider()
    poster.post_review(p1, review, _files(), _cfg())
    posted_hashes = {dedup.finding_hash(f) for f in p1.posted}
    # Second push: the same findings are already on the PR.
    p2 = FakeProvider(existing=posted_hashes)
    outcome = poster.post_review(p2, review, _files(), _cfg())
    assert outcome.posted == 0
    assert p2.posted == []           # ZERO duplicate inline comments
    assert len(p2.summaries) == 1    # summary still upserted (PATCH in the real adapter)


def test_gate_advisory_never_fails():
    review = _review([_finding(2, Severity.CRITICAL, "crit")])
    outcome = poster.post_review(FakeProvider(), review, _files(), _cfg(fail="none"))
    assert outcome.gate_failed is False


def test_gate_blocks_on_fail_check_on_critical():
    review = _review([_finding(2, Severity.CRITICAL, "crit")])
    outcome = poster.post_review(FakeProvider(), review, _files(), _cfg(fail="critical"))
    assert outcome.gate_failed is True
    # gating uses anchored findings even if dedup would skip the post
    p = FakeProvider(existing={dedup.finding_hash(_finding(2, Severity.CRITICAL, "crit"))})
    assert poster.post_review(p, review, _files(), _cfg(fail="critical")).gate_failed is True


def test_gate_passes_when_below_threshold():
    review = _review([_finding(2, Severity.HIGH, "high")])
    outcome = poster.post_review(FakeProvider(), review, _files(), _cfg(fail="critical"))
    assert outcome.gate_failed is False


def test_summary_reflects_error_note():
    review = ReviewResult(summary="x", overall_risk=OverallRisk.MEDIUM, error="boom")
    md = poster.render_summary(review, [], _cfg().root)
    assert "⚠️" in md and dedup.text_has_summary_marker(md)


def test_summary_strips_all_leading_html_comments():
    # The posted summary must not leak internal template/version comments.
    review = _review([_finding(2, Severity.LOW, "a")])
    md = poster.render_summary(review, [], _cfg().root)
    assert "RENDER TEMPLATE" not in md
    assert "version:" not in md
    assert md.lstrip().startswith("###")  # begins at the real heading
