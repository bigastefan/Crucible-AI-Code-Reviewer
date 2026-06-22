"""De-duplication: the hidden `<!-- crucible:{hash} -->` marker + comment rendering.

Shared by EVERY adapter (X-04) so dedup behaves identically on Azure and GitHub.

★ Hash basis (plan A3): sha1(file | category | normalized_title). The LINE IS NOT IN
THE HASH — a still-unfixed finding whose line shifts after an unrelated commit must
keep the same hash, or it would be re-posted as a duplicate (the #1 adoption killer,
P1-01/GP-09). temperature=0 keeps titles stable run-to-run.
"""
from __future__ import annotations

import hashlib
import re
from typing import Set

from core.models import Finding

SUMMARY_MARKER = "<!-- crucible:summary -->"

# Matches a finding marker's hex hash; the summary marker uses the word "summary",
# so it deliberately does NOT match here (summary is excluded from finding hashes).
_MARKER_RE = re.compile(r"<!--\s*crucible:([0-9a-f]{8,40})\s*-->")


def _normalize(text: str) -> str:
    return " ".join(str(text).lower().split())


def content_hash(file: str, line_content: str) -> str:
    """The canonical dedup hash: file | normalized anchored-line CODE.

    Keyed on the changed line's CONTENT — NOT its number, NOT the LLM title, and NOT the
    category. This is the property that prevents duplicate comments on re-push
    (P1-01/GP-09): stable across line drift, title rewording, AND category drift (the
    model labelling the same issue 'security' one run and 'maintainability' the next).
    Once the dev edits that line, the content (and hash) changes — correct, it's a new
    state. Trade-off: two distinct findings on the SAME line collapse to one comment."""
    basis = f"{file}|{_normalize(line_content)}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]


def finding_hash(finding: Finding) -> str:
    """Use the content-based dedup_hash when the poster has set it; otherwise fall back
    to a title-based hash (kept only so callers without diff context still work)."""
    if finding.dedup_hash:
        return finding.dedup_hash
    basis = f"{finding.file}|{_normalize(finding.title)}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]


def inline_marker(h: str) -> str:
    return f"<!-- crucible:{h} -->"


def extract_finding_hashes(text: str) -> Set[str]:
    if not text:
        return set()
    return set(_MARKER_RE.findall(text))


def text_has_summary_marker(text: str) -> bool:
    return bool(text) and SUMMARY_MARKER in text


def render_inline_body(finding: Finding) -> str:
    """The inline comment markdown + hidden dedup marker. Identical across adapters."""
    sev = finding.severity.value.upper()
    parts = [
        f"**🔥 Crucible · {sev} · {finding.category.value}** — {finding.title}",
        "",
        finding.comment or "",
    ]
    if finding.suggestion:
        parts += ["", "```suggestion", finding.suggestion, "```"]
    parts += ["", inline_marker(finding_hash(finding))]
    return "\n".join(parts)
