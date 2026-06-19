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


def _normalize_title(title: str) -> str:
    return " ".join(str(title).lower().split())


def finding_hash(finding: Finding) -> str:
    basis = f"{finding.file}|{finding.category.value}|{_normalize_title(finding.title)}"
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
