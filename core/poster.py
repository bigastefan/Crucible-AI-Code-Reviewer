"""Provider-neutral posting orchestration: filter → dedup → post → header → gate.

Calls ONLY the GitProvider interface; names no host (X-04). The fail-open WRAPPER lives
in crucible.py; this module lets provider calls propagate up to it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from core import dedup, summary
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
class Selection:
    to_post: List[Finding]       # NEW findings to post this run
    surfaced: List[Finding]      # all findings shown (deduped + capped) == inline comments on the PR
    anchored: List[Finding]      # all on-diff findings >= threshold (uncapped) — for gating
    stats: SelectionStats


@dataclass
class PostOutcome:
    posted: int = 0
    resolved: int = 0  # stale comments deleted (findings no longer present)
    stats: SelectionStats = field(default_factory=SelectionStats)
    gate_failed: bool = False
    surfaced: List[Finding] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# selection (pure + unit-tested)
# --------------------------------------------------------------------------- #
def _commentable_map(files: List[FileDiff]) -> Dict[str, Set[int]]:
    return {f.path: f.added_line_numbers for f in files if f.added_line_numbers}


def _line_content_map(files: List[FileDiff]) -> Dict[tuple, str]:
    """(file, right_line) → added-line code, for content-based dedup hashing."""
    out: Dict[tuple, str] = {}
    for f in files:
        for h in f.hunks:
            for ln in h.added_lines:
                if ln.right_line is not None:
                    out[(f.path, ln.right_line)] = ln.content
    return out


def resolve_file(file: str, commentable: Dict[str, Set[int]]) -> Optional[str]:
    """Map a finding's file onto a parsed diff path. Exact match first, then a unique
    suffix match (tolerates the model emitting a slightly different path prefix)."""
    if file in commentable:
        return file
    cands = [p for p in commentable if p.endswith("/" + file) or file.endswith("/" + p)]
    return cands[0] if len(cands) == 1 else None


def select_findings(
    review: ReviewResult, files: List[FileDiff], cfg: ReviewConfig, existing_hashes: Set[str]
) -> Selection:
    """Filter to changed lines + severity, set content-based dedup hashes, dedup within
    the run, sort, cap. `surfaced` == the inline comments on the PR (header counts use
    it); `to_post` == only the NEW ones this run; `anchored` == uncapped, for gating."""
    commentable = _commentable_map(files)
    content = _line_content_map(files)
    min_rank = Severity(cfg.min_severity_to_post).rank
    stats = SelectionStats(total=len(review.findings))

    anchored: List[Finding] = []
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
        f.dedup_hash = dedup.content_hash(path, content.get((path, f.line), f.title))
        anchored.append(f)

    # Unique within the run (by content hash), highest severity first, then capped.
    uniq: List[Finding] = []
    seen: Set[str] = set()
    for f in sorted(anchored, key=lambda f: (-f.severity.rank, f.file, f.line)):
        if f.dedup_hash in seen:
            continue
        seen.add(f.dedup_hash)
        uniq.append(f)

    surfaced = uniq[: cfg.max_findings]
    stats.capped = len(uniq) - len(surfaced)
    to_post = [f for f in surfaced if f.dedup_hash not in existing_hashes]
    stats.skipped_existing = len(surfaced) - len(to_post)

    return Selection(to_post=to_post, surfaced=surfaced, anchored=anchored, stats=stats)


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #
def post_review(
    provider, review: ReviewResult, files: List[FileDiff], cfg, model: str = "", duration_s: float = 0.0
) -> PostOutcome:
    """Post new findings, resolve stale ones, upsert the single header, compute the gate."""
    existing_pairs = provider.existing_findings()
    existing_hashes = {h for h, _ in existing_pairs}
    sel = select_findings(review, files, cfg.review, existing_hashes)

    for f in sel.to_post:
        provider.post_inline(f)

    # B: resolve (delete) comments whose finding is no longer present this run, so the
    # PR always shows exactly the current finding set — no accumulation across pushes.
    current_hashes = {f.dedup_hash for f in sel.surfaced}
    resolved = 0
    for h, ref in existing_pairs:
        if h not in current_hashes:
            try:
                provider.delete_inline(ref)
                resolved += 1
            except Exception as e:  # best-effort; never break the run
                log.warning("could not resolve stale comment %s: %s", ref, e)

    mode = "blocking" if cfg.review.fail_check_on != "none" else "advisory"
    meta = summary.SummaryMeta(
        mode=mode, model=model, duration_s=duration_s,
        delta=summary.compute_delta(existing_hashes, current_hashes),
        name=cfg.branding.name, logo_url=cfg.branding.logo_url,
    )
    provider.upsert_summary(summary.build_header(review, sel.surfaced, meta))

    gate_failed = False
    if cfg.review.fail_check_on != "none":
        fail_rank = Severity(cfg.review.fail_check_on).rank
        gate_failed = any(f.severity.rank >= fail_rank for f in sel.anchored)

    state = "failed" if gate_failed else "succeeded"
    provider.set_status(state, "Crucible found a blocking issue." if gate_failed else "Crucible review complete.")

    return PostOutcome(posted=len(sel.to_post), resolved=resolved, stats=sel.stats,
                       gate_failed=gate_failed, surfaced=sel.surfaced)
