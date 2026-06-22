"""Phase 3/6 — posting orchestration: filter, dedup, header, gating.
Uses a FakeProvider so the provider-neutral logic is verified offline."""
from pathlib import Path

from core import dedup, poster
from core.config import load_config
from core.diff import parse_diff
from core.models import Category, Finding, OverallRisk, ReviewResult, Severity
from providers.base import GitProvider

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"


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
    review = _review([_finding(2, Severity.HIGH, "on-diff"), _finding(5, Severity.HIGH, "off-diff")])
    sel = poster.select_findings(review, _files(), _cfg().review, set())
    assert [f.title for f in sel.to_post] == ["on-diff"]
    assert sel.stats.skipped_unanchored == 1


def test_severity_filter():
    review = _review([_finding(2, Severity.LOW, "low"), _finding(11, Severity.HIGH, "high")])
    sel = poster.select_findings(review, _files(), _cfg(min_sev="medium").review, set())
    assert [f.title for f in sel.to_post] == ["high"]
    assert sel.stats.skipped_severity == 1


def test_dedup_against_existing_hashes():
    review = _review([_finding(11, Severity.HIGH, "high"), _finding(2, Severity.LOW, "low")])
    first = poster.select_findings(review, _files(), _cfg().review, set())
    high_hash = next(f.dedup_hash for f in first.surfaced if f.title == "high")
    sel = poster.select_findings(review, _files(), _cfg().review, {high_hash})
    assert [f.title for f in sel.to_post] == ["low"]      # only the new one is posted
    assert sel.stats.skipped_existing == 1
    assert len(sel.surfaced) == 2                          # header still reflects both


def test_dedup_holds_when_title_changes():
    first = poster.select_findings(
        _review([_finding(11, Severity.HIGH, "Null deref")]), _files(), _cfg().review, set())
    h = first.surfaced[0].dedup_hash
    reworded = _review([_finding(11, Severity.HIGH, "Possible null dereference here")])
    sel = poster.select_findings(reworded, _files(), _cfg().review, {h})
    assert sel.to_post == []  # title changed, content identical → no duplicate


def test_cap_keeps_highest_severity():
    review = _review([
        _finding(2, Severity.LOW, "low"),
        _finding(11, Severity.CRITICAL, "crit"),
        _finding(12, Severity.MEDIUM, "med"),
    ])
    sel = poster.select_findings(review, _files(), _cfg(max_findings=1).review, set())
    assert [f.title for f in sel.surfaced] == ["crit"]
    assert sel.stats.capped == 2


# --------------------------------------------------------------------------- post_review
def test_post_review_posts_and_upserts_one_header():
    review = _review([_finding(2, Severity.LOW, "a"), _finding(11, Severity.HIGH, "b")])
    prov = FakeProvider()
    outcome = poster.post_review(prov, review, _files(), _cfg(), model="m", duration_s=1.0)
    assert outcome.posted == 2
    assert len(prov.posted) == 2
    assert len(prov.summaries) == 1
    assert dedup.text_has_summary_marker(prov.summaries[0])
    assert prov.statuses == [("succeeded", "Crucible review complete.")]


def test_header_count_equals_posted_inline_comments():
    """The invariant: code-computed header tally == surfaced == inline comments posted."""
    review = _review([
        _finding(2, Severity.LOW, "a"), _finding(11, Severity.HIGH, "b"), _finding(12, Severity.CRITICAL, "c"),
    ])
    prov = FakeProvider()
    outcome = poster.post_review(prov, review, _files(), _cfg(), model="m")
    assert outcome.posted == len(prov.posted) == 3
    assert "**3 findings**" in prov.summaries[0]


def test_gp09_second_push_posts_zero_duplicates():
    review = _review([_finding(2, Severity.LOW, "a"), _finding(11, Severity.HIGH, "b")])
    p1 = FakeProvider()
    poster.post_review(p1, review, _files(), _cfg())
    posted_hashes = {f.dedup_hash for f in p1.posted}
    p2 = FakeProvider(existing=posted_hashes)
    outcome = poster.post_review(p2, review, _files(), _cfg())
    assert outcome.posted == 0
    assert p2.posted == []
    assert len(p2.summaries) == 1  # header still upserted (with a delta line)


def test_gate_advisory_never_fails():
    review = _review([_finding(2, Severity.CRITICAL, "crit")])
    assert poster.post_review(FakeProvider(), review, _files(), _cfg(fail="none")).gate_failed is False


def test_gate_blocks_on_fail_check_on_critical():
    review = _review([_finding(2, Severity.CRITICAL, "crit")])
    assert poster.post_review(FakeProvider(), review, _files(), _cfg(fail="critical")).gate_failed is True
    # gating uses anchored findings even if dedup would skip the (re)post
    existing = {poster.select_findings(review, _files(), _cfg().review, set()).surfaced[0].dedup_hash}
    assert poster.post_review(FakeProvider(existing=existing), review, _files(), _cfg(fail="critical")).gate_failed is True


def test_gate_passes_when_below_threshold():
    review = _review([_finding(2, Severity.HIGH, "high")])
    assert poster.post_review(FakeProvider(), review, _files(), _cfg(fail="critical")).gate_failed is False
