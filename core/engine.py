"""The shared review path used by BOTH the dry-run and posting flows, and BOTH the
Azure and GitHub adapters. This is where Phase-6 hardening attaches (redaction, size
guards, secret findings) — once, host-neutrally (no provider change).

Order (per the build directive): redact secrets BEFORE the LLM call → size guard →
review → merge deterministic secret findings.
"""
from __future__ import annotations

import logging
from typing import Callable, List, Optional, Tuple

from core import llm, prompt_builder, reviewer, secrets
from core.diff import ADDED, REMOVED, FileDiff, filter_excluded, parse_diff
from core.models import OverallRisk, ReviewResult

log = logging.getLogger("crucible.engine")


def _changed_line_count(files: List[FileDiff]) -> int:
    n = 0
    for f in files:
        for h in f.hunks:
            for ln in h.lines:
                if ln.kind in (ADDED, REMOVED):
                    n += 1
    return n


def run_review(
    cfg, repo, diff_text: str, complete_fn: Optional[Callable] = None
) -> Tuple[ReviewResult, List[FileDiff]]:
    """Produce a ReviewResult for a diff. Returns (result, files) where `files` is the
    post-exclusion parse used for line-anchoring. Never raises for content reasons
    (reviewer fails safe); provider/LLM transport errors propagate to the fail-open
    wrapper in crucible.py."""
    files = filter_excluded(parse_diff(diff_text), cfg.exclude_paths)
    model = cfg.model_for(repo)

    # GP-06: nothing left to review after exclusions.
    if not files:
        return ReviewResult(
            summary="Nothing to review — no changed files after exclusions.",
            overall_risk=OverallRisk.LOW,
        ), files

    # 1) Secret redaction BEFORE the LLM call (host-neutral).
    secret_findings = []
    outbound = diff_text
    if cfg.agent.redact_secrets:
        outbound, kinds = secrets.mask_secrets(diff_text)
        secret_findings = secrets.find_secret_findings(files)
        if kinds:
            log.info("redaction: masked secret kinds=%s (values never logged)", sorted(kinds))

    # 2) Size guard — skip the LLM, post a graceful notice. Still report any secrets.
    changed = _changed_line_count(files)
    tokens = llm.estimate_tokens(model, outbound)
    if changed > cfg.review.max_diff_lines or tokens > cfg.review.max_diff_tokens:
        log.info("size-guard: skipped LLM (%d changed lines, ~%d tokens)", changed, tokens)
        notice = (
            f"PR too large to auto-review: {changed} changed lines / ~{tokens} tokens exceeds "
            f"limits ({cfg.review.max_diff_lines} lines, {cfg.review.max_diff_tokens} tokens). "
            "Crucible skipped the model review."
        )
        return ReviewResult(
            summary=notice, overall_risk=OverallRisk.MEDIUM, findings=secret_findings
        ), files

    # 3) Review the (redacted) diff.
    system_prompt, user_prompt = prompt_builder.build_prompts(cfg, repo, outbound)
    result = reviewer.review(model, system_prompt, user_prompt, cfg.model.max_tokens, complete_fn=complete_fn)

    # 4) Merge deterministic secret findings (critical) ahead of model findings.
    if secret_findings:
        result.findings = secret_findings + result.findings
    return result, files
