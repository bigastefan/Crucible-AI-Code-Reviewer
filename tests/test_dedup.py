"""Phase 3/6 — dedup hash + marker. The hash is keyed on the anchored line's CONTENT
(not its number, not the LLM title) so re-pushes never re-post (P1-01/GP-09), even when
the line moves OR the model rewords the title."""
from core import dedup
from core.models import Category, Finding, Severity


def f(file="a.py", line=10, sev=Severity.HIGH, cat=Category.BUG, title="Null deref", comment="c", sug=None, h=None):
    return Finding(file, line, sev, cat, title, comment, sug, dedup_hash=h)


# --- content_hash (the canonical basis: file | line-content) ------------------
def test_content_hash_ignores_line_number():
    # The line number is NOT an input → stable when the line drifts.
    assert dedup.content_hash("a.py", "return x.foo()") == dedup.content_hash("a.py", "return x.foo()")


def test_content_hash_ignores_whitespace_and_case():
    assert dedup.content_hash("a.py", "  return  X.foo() ") == dedup.content_hash("a.py", "return x.foo()")


def test_content_hash_differs_on_file_and_content_only():
    base = dedup.content_hash("a.py", "return x.foo()")
    assert dedup.content_hash("b.py", "return x.foo()") != base   # file matters
    assert dedup.content_hash("a.py", "return y.bar()") != base   # content matters
    # category is NOT part of the hash (it's not even a parameter) → category drift can't dup


# --- finding_hash prefers the content-based dedup_hash, else falls back to title
def test_finding_hash_uses_dedup_hash_when_set():
    assert dedup.finding_hash(f(h="abc123abc123")) == "abc123abc123"


def test_finding_hash_title_fallback_when_no_dedup_hash():
    assert dedup.finding_hash(f(title="A")) != dedup.finding_hash(f(title="B"))


# --- marker round-trip --------------------------------------------------------
def test_marker_round_trip():
    body = dedup.render_inline_body(f(h="deadbeef0001"))
    assert dedup.extract_finding_hashes(body) == {"deadbeef0001"}


def test_summary_marker_not_counted_as_finding_hash():
    text = f"some summary {dedup.SUMMARY_MARKER}"
    assert dedup.extract_finding_hashes(text) == set()
    assert dedup.text_has_summary_marker(text) is True


def test_render_inline_body_contains_parts():
    body = dedup.render_inline_body(f(sug="if x is not None:"))
    assert "HIGH" in body and "bug" in body and "Null deref" in body
    assert "```suggestion" in body and "if x is not None:" in body
    assert dedup.SUMMARY_MARKER not in body


def test_extract_handles_multiple_and_empty():
    assert dedup.extract_finding_hashes("") == set()
    txt = "<!-- crucible:aaaaaaaa1111 --> ... <!-- crucible:bbbbbbbb2222 -->"
    assert dedup.extract_finding_hashes(txt) == {"aaaaaaaa1111", "bbbbbbbb2222"}
