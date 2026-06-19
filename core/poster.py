"""Provider-neutral posting orchestration: filter → dedup → post → summary → gate.

Calls ONLY the GitProvider interface; names no host. The §4 step-7/8/9 logic lives
here so both adapters share it (X-04). The fail-open WRAPPER lives in crucible.py;
this module assumes the provider calls may raise and lets them propagate up to it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

from core import dedup
from core.config import ReviewConfig
from core.diff import FileDiff
from core.models import Finding, ReviewResult, Severity

log = logging.getLogger("crucible.poster")


@dataclass
class SelectionStats:
    total: int = 0
    skipped_severity: int = 0
    skipped_unanchored: int = 0
    skipped_existing: int = 0
    capped: int = 0


@dataclass
class PostOutcome:
    posted: int = 0
    stats: SelectionStats = field(default_factory=SelectionStats)
    gate_failed: bool = False  # a finding >= fail_check_on exists (and gating is on)
    anchored_findings: List[Finding] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# selection (pure + unit-tested)
# --------------------------------------------------------------------------- #
def _commentable_map(files: List[FileDiff]) -> Dict[str, Set[int]]:
    return {f.path: f.added_line_numbers for f in files if f.added_line_numbers}


def resolve_file(file: str, commentable: Dict[str, Set[int]]) -> Optional[str]:
    """Map a finding's file onto a parsed diff path. Exact match first, then a unique
    suffix match (tolerates the model emitting a slightly different path prefix)."""
    if file in commentable:
        return file
    cands = [p for p in commentable if p.endswith("/" + file) or file.endswith("/" + p)]
    return cands[0] if len(cands) == 1 else None


def select_findings(
    review: ReviewResult,
    files: List[FileDiff],
    cfg: ReviewConfig,
    existing_hashes: Set[str],
):
    """Return (findings_to_post, anchored_findings, stats).

    - drop below min_severity_to_post
    - drop findings not on a changed (right-side) line  (§4 step 7)
    - drop hashes already posted on the PR  (dedup, GP-09)
    - de-dup within this run; sort by severity desc; cap at max_findings
    `anchored_findings` = all on-diff findings at/above threshold (used for GATING,
    independent of dedup — a previously-posted critical still gates).
    """
    commentable = _commentable_map(files)
    min_rank = Severity(cfg.min_severity_to_post).rank
    stats = SelectionStats(total=len(review.findings))

    anchored: List[Finding] = []
    candidates: List[Finding] = []
    for f in review.findings:
        if f.severity.rank < min_rank:
            stats.skipped_severity += 1
            continue
        path = resolve_file(f.file, commentable)
        if path is None or f.line not in commentable[path]:
            stats.skipped_unanchored += 1
            continue
        if path != f.file:
            f = Finding(path, f.line, f.severity, f.category, f.title, f.comment, f.suggestion)
        anchored.append(f)
        candidates.append(f)

    seen: Set[str] = set()
    to_post: List[Finding] = []
    for f in candidates:
        h = dedup.finding_hash(f)
        if h in existing_hashes:
            stats.skipped_existing += 1
            continue
        if h in seen:  # duplicate within this same run
            continue
        seen.add(h)
        to_post.append(f)

    to_post.sort(key=lambda f: (-f.severity.rank, f.file, f.line))
    if len(to_post) > cfg.max_findings:
        stats.capped = len(to_post) - cfg.max_findings
        to_post = to_post[: cfg.max_findings]

    return to_post, anchored, stats


# --------------------------------------------------------------------------- #
# summary rendering (uses prompts/summary.md as a render template, plan A5)
# --------------------------------------------------------------------------- #
_SEV_EMOJI = {"critical": "🟥", "high": "🟧", "medium": "🟨", "low": "⬜"}


def render_summary(review: ReviewResult, posted: List[Finding], root: Path) -> str:
    template = _read_summary_template(root)
    if review.error:
        table = f"> ⚠️ {review.summary}"
    elif posted:
        rows = ["| Severity | Location | Finding |", "|---|---|---|"]
        for f in posted:
            emoji = _SEV_EMOJI.get(f.severity.value, "")
            rows.append(f"| {emoji} {f.severity.value} | `{f.file}:{f.line}` | {f.title} |")
        table = "\n".join(rows)
    else:
        table = "_No issues found on the changed lines._"

    body = template
    for key, val in {
        "{summary}": review.summary or "",
        "{overall_risk}": review.overall_risk.value,
        "{findings_table}": table,
    }.items():
        body = body.replace(key, val)

    if not dedup.text_has_summary_marker(body):
        body = f"{body}\n\n{dedup.SUMMARY_MARKER}"
    return body


def _read_summary_template(root: Path) -> str:
    import re

    raw = (root / "prompts" / "summary.md").read_text()
    # Strip EVERY leading HTML comment (version header + dev notes) so none leak into
    # the posted summary. Only leading comments are removed (the SUMMARY_MARKER is
    # appended later by render_summary, not taken from the template).
    prev = None
    while prev != raw:
        prev = raw
        raw = re.sub(r"^\s*<!--.*?-->\s*", "", raw, count=1, flags=re.DOTALL)
    return raw.strip()


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #
def post_review(provider, review: ReviewResult, files: List[FileDiff], cfg) -> PostOutcome:
    """Post new findings + upsert the single summary; compute the gate. Provider
    calls may raise — the caller (crucible.py) wraps this for fail-open."""
    existing = provider.existing_finding_hashes()
    to_post, anchored, stats = select_findings(review, files, cfg.review, existing)

    for f in to_post:
        provider.post_inline(f)

    provider.upsert_summary(render_summary(review, to_post, cfg.root))

    gate_failed = False
    if cfg.review.fail_check_on != "none":
        fail_rank = Severity(cfg.review.fail_check_on).rank
        gate_failed = any(f.severity.rank >= fail_rank for f in anchored)

    state = "failed" if gate_failed else "succeeded"
    note = "Crucible found a blocking issue." if gate_failed else "Crucible review complete."
    provider.set_status(state, note)

    return PostOutcome(posted=len(to_post), stats=stats, gate_failed=gate_failed, anchored_findings=anchored)
