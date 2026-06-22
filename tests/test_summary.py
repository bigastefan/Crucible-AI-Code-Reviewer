"""Enhancement — the Tech-Lead summary header. Counts are CODE-computed; the header's
tallies must always equal the findings list (never LLM-counted)."""
from core import dedup, summary
from core.models import Category, Coverage, Finding, OverallRisk, ReviewResult, Severity


def f(line, sev, cat, title, file="a.ts"):
    return Finding(file, line, sev, cat, title, "c", None)


def _review(findings, summ="Adds a service and a query.", risk=OverallRisk.HIGH, cov=None, error=None):
    return ReviewResult(summary=summ, overall_risk=risk, findings=findings, error=error, coverage=cov)


def _meta(mode="advisory", delta=None):
    return summary.SummaryMeta(mode=mode, model="anthropic/claude-sonnet-4-6", duration_s=8.8, delta=delta)


FINDINGS = [
    f(4, Severity.CRITICAL, Category.SECURITY, "Hardcoded secret"),
    f(16, Severity.CRITICAL, Category.SECURITY, "SQL injection"),
    f(12, Severity.CRITICAL, Category.BUG, "Null deref"),
    f(21, Severity.HIGH, Category.BUG, "Floating promise"),
    f(28, Severity.MEDIUM, Category.MAINTAINABILITY, "Empty catch"),
]


# --- the invariant ------------------------------------------------------------
def test_counts_equal_findings_count():
    header = summary.build_header(_review(FINDINGS), FINDINGS, _meta())
    # header says "5 findings"; the severity tally sums to 5; category tally sums to 5.
    assert "**5 findings**" in header
    assert "🟥 3 critical" in header and "🟧 1 high" in header and "🟨 1 medium" in header
    # category counts sum to len(findings)
    assert "security 2" in header and "bug 2" in header and "maintainability 1" in header


def test_verdict_derived_in_code():
    assert summary.verdict(FINDINGS, "advisory") == ("🟥", "Needs attention")
    assert summary.verdict(FINDINGS, "blocking") == ("⛔", "Blocking")
    assert summary.verdict([f(1, Severity.HIGH, Category.BUG, "x")], "advisory") == ("🟧", "Review suggested")
    assert summary.verdict([f(1, Severity.LOW, Category.STYLE, "x")], "advisory") == ("✅", "Looks good")
    assert summary.verdict([], "advisory") == ("✅", "Looks good")


def test_top_three_by_severity():
    header = summary.build_header(_review(FINDINGS), FINDINGS, _meta())
    top_line = next(l for l in header.splitlines() if l.startswith("**Top:**"))
    # the three criticals lead, with file:line anchors
    assert "Hardcoded secret" in top_line and "SQL injection" in top_line and "Null deref" in top_line
    assert "Floating promise" not in top_line  # only top 3
    assert "`a.ts:4`" in top_line


def test_one_liner_is_the_llm_summary():
    header = summary.build_header(_review(FINDINGS), FINDINGS, _meta())
    assert "Adds a service and a query." in header


def test_coverage_and_tests_flag():
    cov = Coverage(files_reviewed=2, files_skipped=1, changed_lines=41, tests_missing=True)
    header = summary.build_header(_review(FINDINGS, cov=cov), FINDINGS, _meta())
    assert "2 files reviewed" in header and "1 skipped" in header and "41 changed lines" in header
    assert "no tests added for new logic" in header


def test_delta_omitted_on_first_review():
    # compute_delta returns None when there are no prior hashes.
    assert summary.compute_delta(set(), {"a", "b"}) is None
    header = summary.build_header(_review(FINDINGS), FINDINGS, _meta(delta=None))
    assert "Since last push" not in header


def test_delta_present_on_repush():
    delta = summary.compute_delta({"old1", "keep"}, {"keep", "new1"})
    assert delta == (1, 1, 1)  # new, resolved, unchanged
    header = summary.build_header(_review(FINDINGS), FINDINGS, _meta(delta=delta))
    assert "Since last push:** 1 new · 1 resolved · 1 unchanged" in header


def test_footer_has_mode_model_duration():
    header = summary.build_header(_review(FINDINGS), FINDINGS, _meta())
    assert "🤖 Crucible · advisory · anthropic/claude-sonnet-4-6 · 8.8s" in header
    assert dedup.text_has_summary_marker(header)


def test_no_findings_header():
    header = summary.build_header(_review([], summ="Doc-only change.", risk=OverallRisk.LOW), [], _meta())
    assert "Looks good" in header and "No issues found" in header


def test_error_header_is_unavailable_and_marked():
    header = summary.build_header(_review([], error="bad key"), [], _meta())
    assert "unavailable" in header.lower()
    assert dedup.text_has_summary_marker(header)
