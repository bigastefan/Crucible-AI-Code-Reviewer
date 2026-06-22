"""Builds the PR summary header markdown for a Tech Lead. Host-agnostic.

★ CRITICAL principle: every count/tally here is COMPUTED IN CODE from the findings
list — never produced or counted by the LLM. The only LLM-authored text is the
one-line "what this PR does" sentence (reused from ReviewResult.summary). The header's
counts therefore always equal the surfaced findings = the inline comments posted.

The provider adapters are unchanged — they just receive this markdown via upsert_summary().
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from core import dedup
from core.models import Category, Finding, ReviewResult, Severity

_SEV_EMOJI = {
    Severity.CRITICAL: "🟥",
    Severity.HIGH: "🟧",
    Severity.MEDIUM: "🟨",
    Severity.LOW: "⬜",
}
_SEV_ORDER = [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW]
_CAT_ORDER = [Category.SECURITY, Category.BUG, Category.PERFORMANCE,
              Category.TEST, Category.MAINTAINABILITY, Category.STYLE]


@dataclass
class SummaryMeta:
    mode: str = "advisory"          # advisory | blocking
    model: str = ""
    duration_s: float = 0.0
    # (new, resolved, unchanged) vs the previous review; None on the first review.
    delta: Optional[Tuple[int, int, int]] = None
    # Cosmetic branding of the header CONTENT (not the comment author).
    name: str = "Crucible"
    logo_url: Optional[str] = None


def _title(meta: SummaryMeta, verdict_str: str) -> str:
    """Branded h2 title. Graceful fallback: the logo carries alt text AND the name is
    always present as words, so a broken image never leaves a nameless box."""
    name = meta.name or "Crucible"
    if meta.logo_url:
        mark = f'<img src="{meta.logo_url}" width="16" align="top" alt="{name}"> '
    else:
        mark = "🔥 "
    return f"## {mark}{name} Review — {verdict_str}"


def verdict(findings: List[Finding], mode: str) -> Tuple[str, str]:
    """Derived in code from severity counts (never the LLM)."""
    has_crit = any(f.severity is Severity.CRITICAL for f in findings)
    has_high = any(f.severity is Severity.HIGH for f in findings)
    if mode == "blocking" and has_crit:
        return "⛔", "Blocking"
    if has_crit:
        return "🟥", "Needs attention"
    if has_high:
        return "🟧", "Review suggested"
    return "✅", "Looks good"


def _one_liner(text: str) -> str:
    text = " ".join((text or "").split())
    if not text:
        return "_No summary provided._"
    # first sentence, capped
    for end in (". ", "! ", "? "):
        i = text.find(end)
        if 0 < i < 220:
            return text[: i + 1]
    return text if len(text) <= 220 else text[:217].rstrip() + "…"


def _trim(s: str, n: int = 70) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def compute_delta(existing_hashes, current_hashes) -> Optional[Tuple[int, int, int]]:
    """(new, resolved, unchanged) from dedup hashes. None on the first review
    (no prior Crucible findings present)."""
    existing = set(existing_hashes or set())
    if not existing:
        return None
    current = set(current_hashes or set())
    new = len(current - existing)
    resolved = len(existing - current)
    unchanged = len(current & existing)
    return (new, resolved, unchanged)


def build_header(review: ReviewResult, findings: List[Finding], meta: SummaryMeta) -> str:
    """Render the compact header. `findings` is the SURFACED set (== inline comments)."""
    footer = (
        f"\n🤖 Crucible · {meta.mode} · {meta.model or 'model'} · "
        f"{meta.duration_s:.1f}s\n\n{dedup.SUMMARY_MARKER}"
    )

    # Fail-open / unavailable: keep it minimal but honest.
    if review.error:
        return (
            _title(meta, "⚠️ Review unavailable") + "\n\n"
            f"{_one_liner(review.summary)}\n\n"
            "_This is advisory only and did not block the merge._"
            + footer
        )

    v_emoji, v_text = verdict(findings, meta.mode)
    lines: List[str] = [_title(meta, f"{v_emoji} {v_text}"), "", _one_liner(review.summary), ""]

    # Severity tally (sums to len(findings) — the invariant).
    if findings:
        sev_counts = {s: 0 for s in _SEV_ORDER}
        for f in findings:
            sev_counts[f.severity] += 1
        parts = [f"{_SEV_EMOJI[s]} {sev_counts[s]} {s.value}" for s in _SEV_ORDER if sev_counts[s]]
        lines.append(f"**{len(findings)} finding{'s' if len(findings) != 1 else ''}** · " + " · ".join(parts))

        cat_counts = {c: 0 for c in _CAT_ORDER}
        for f in findings:
            cat_counts[f.category] += 1
        cat_parts = [f"{c.value} {cat_counts[c]}" for c in _CAT_ORDER if cat_counts[c]]
        lines.append("**By area:** " + " · ".join(cat_parts))

        top = sorted(findings, key=lambda f: (-f.severity.rank, f.file, f.line))[:3]
        top_parts = [f"{_SEV_EMOJI[f.severity]} {_trim(f.title)} (`{f.file}:{f.line}`)" for f in top]
        lines.append("**Top:** " + " · ".join(top_parts))
    else:
        lines.append("**No issues found on the changed lines.**")

    # Coverage.
    cov = review.coverage
    if cov is not None:
        cov_bits = [
            f"{cov.files_reviewed} file{'s' if cov.files_reviewed != 1 else ''} reviewed",
            f"{cov.files_skipped} skipped",
            f"{cov.changed_lines} changed line{'s' if cov.changed_lines != 1 else ''}",
        ]
        cov_line = "**Coverage:** " + " · ".join(cov_bits)
        if cov.oversized:
            cov_line += " · ⚠️ diff too large, model review skipped"
        if cov.tests_missing:
            cov_line += " · ⚠️ no tests added for new logic"
        lines.append(cov_line)

    # Since-last-push delta (omitted on the first review).
    if meta.delta is not None:
        new, resolved, unchanged = meta.delta
        lines.append(f"**Since last push:** {new} new · {resolved} resolved · {unchanged} unchanged")

    return "\n".join(lines) + footer
