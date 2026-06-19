"""Phase 3 — dedup hash + marker. The headline property (plan A3): the hash is STABLE
across line drift, so a re-pushed PR never re-posts an existing finding (GP-09)."""
from core import dedup
from core.models import Category, Finding, Severity


def f(file="a.py", line=10, sev=Severity.HIGH, cat=Category.BUG, title="Null deref", comment="c", sug=None):
    return Finding(file, line, sev, cat, title, comment, sug)


def test_hash_is_stable_across_line_drift():
    # Same finding, different line (a later commit shifted it) → SAME hash.
    assert dedup.finding_hash(f(line=10)) == dedup.finding_hash(f(line=87))


def test_hash_ignores_comment_and_suggestion():
    assert dedup.finding_hash(f(comment="x", sug="a")) == dedup.finding_hash(f(comment="y", sug="b"))


def test_hash_is_case_and_whitespace_insensitive_on_title():
    assert dedup.finding_hash(f(title="Null Deref")) == dedup.finding_hash(f(title="  null   deref "))


def test_hash_differs_on_file_category_title():
    base = dedup.finding_hash(f())
    assert dedup.finding_hash(f(file="b.py")) != base
    assert dedup.finding_hash(f(cat=Category.SECURITY)) != base
    assert dedup.finding_hash(f(title="Off by one")) != base


def test_marker_round_trip():
    body = dedup.render_inline_body(f())
    assert dedup.extract_finding_hashes(body) == {dedup.finding_hash(f())}


def test_summary_marker_not_counted_as_finding_hash():
    text = f"some summary {dedup.SUMMARY_MARKER}"
    assert dedup.extract_finding_hashes(text) == set()
    assert dedup.text_has_summary_marker(text) is True


def test_render_inline_body_contains_parts():
    body = dedup.render_inline_body(f(sug="if x is not None:"))
    assert "HIGH" in body and "bug" in body and "Null deref" in body
    assert "```suggestion" in body and "if x is not None:" in body
    assert dedup.SUMMARY_MARKER not in body  # inline comments are not the summary


def test_extract_handles_multiple_and_empty():
    assert dedup.extract_finding_hashes("") == set()
    txt = "<!-- crucible:aaaaaaaa1111 --> ... <!-- crucible:bbbbbbbb2222 -->"
    assert dedup.extract_finding_hashes(txt) == {"aaaaaaaa1111", "bbbbbbbb2222"}
