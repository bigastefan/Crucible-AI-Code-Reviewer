#!/usr/bin/env python3
"""Crucible CLI entrypoint.

    crucible --pr <id> [--dry-run] [--repo NAME] [--diff-file PATH]
             [--config config.yaml] [--provider azure|github]

Phase 0: resolve config → provider/model/rules and print them.
Phase 2: in --dry-run, acquire a diff (via --diff-file locally, or the provider once
         it exists), parse it, build the prompt, call the model through LiteLLM, and
         print the validated findings JSON. Posts NOTHING.
Phase 3+: the non-dry-run path posts via the GitProvider adapter.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

from core import engine, logging_setup, poster, summary
from core.config import Config, ConfigError, RepoConfig, load_config, match_repo
from core.models import OverallRisk, ReviewResult, review_as_dict
from providers.base import get_provider

log = logging.getLogger("crucible")


def detect_repo_name() -> str | None:
    return (
        os.environ.get("BUILD_REPOSITORY_NAME")  # Azure DevOps
        or os.environ.get("GITHUB_REPOSITORY")  # GitHub (owner/repo)
        or None
    )


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="crucible", description="AI PR-review agent (Phase 1).")
    p.add_argument("--pr", type=int, required=True, help="Pull request id.")
    p.add_argument("--dry-run", action="store_true", help="Review locally; post nothing.")
    p.add_argument("--repo", default=None, help="Repo name to match in config (else CI env, else first repo).")
    p.add_argument("--diff-file", default=None, help="Read the diff from a file (local dry-run testing).")
    p.add_argument("--config", default="config.yaml", help="Path to config.yaml.")
    p.add_argument("--provider", default=None, choices=["azure", "github"], help="Override the matched repo's provider.")
    return p.parse_args(argv)


def _fmt_path(pair) -> str:
    path, exists = pair
    return f"{path}  {'✓' if exists else '✗ MISSING'}"


def resolve_repo(cfg: Config, args) -> tuple[RepoConfig | None, str, bool]:
    repo_name = args.repo or detect_repo_name()
    fallback = False
    if not repo_name:
        if not cfg.repos:
            raise ConfigError("no repos configured in config.yaml")
        repo_name = cfg.repos[0].name
        fallback = True
    return match_repo(cfg, repo_name), repo_name, fallback


def print_resolution(cfg: Config, repo: RepoConfig, repo_name: str, fallback: bool, args) -> None:
    provider = args.provider or repo.provider
    rules = cfg.rule_paths(repo)
    print("Crucible — resolution")
    print(f"  config       : {cfg.path}")
    print(f"  PR id        : {args.pr}")
    print(f"  repo name    : {repo_name}" + ("  (fallback: first configured repo)" if fallback else ""))
    print(f"  matched repo : {repo.name}   (match key: {repo.match!r})")
    print(f"  provider     : {provider}" + ("  (overridden via --provider)" if args.provider else ""))
    print(f"  model        : {cfg.model_for(repo)}")
    print(f"  dry-run      : {args.dry_run}")
    print("  rules:")
    print(f"    global     : {_fmt_path(rules['global'])}")
    print(f"    project    : {_fmt_path(rules['project'])}")
    if rules["languages"]:
        print("    languages  :")
        for pair in rules["languages"]:
            print(f"      - {_fmt_path(pair)}")
    else:
        print("    languages  : (none)")
    print(f"  exclude_paths: {len(cfg.exclude_paths)} pattern(s)")


def acquire_diff(args, repo: RepoConfig, provider_name: str) -> str | None:
    """Return the raw unified diff, or None if no source is available yet."""
    if args.diff_file:
        return Path(args.diff_file).read_text()
    try:
        prov = get_provider(provider_name, config=None, pr_id=args.pr)
    except NotImplementedError:
        return None  # adapter not built yet (Phase 3/5)
    return prov.get_diff()


def run_engine(cfg: Config, repo: RepoConfig, diff_text: str) -> int:
    """Phase 2 dry-run: redact → guard → review → JSON + the summary header. No posting."""
    t0 = time.time()
    result, files = engine.run_review(cfg, repo, diff_text)
    duration = time.time() - t0
    commentable = sum(len(f.added_line_numbers) for f in files)
    print(f"\nParsed {len(files)} file(s); {commentable} commentable line(s).")

    print("\n--- review (JSON, posts nothing) ---")
    print(json.dumps(review_as_dict(result), indent=2, ensure_ascii=False))

    # Render the exact summary header that would be posted (no existing → no delta line).
    sel = poster.select_findings(result, files, cfg.review, set())
    mode = "blocking" if cfg.review.fail_check_on != "none" else "advisory"
    meta = summary.SummaryMeta(mode=mode, model=cfg.model_for(repo), duration_s=duration,
                              name=cfg.branding.name, logo_url=cfg.branding.logo_url)
    print("\n--- summary header (preview) ---")
    print(summary.build_header(result, sel.surfaced, meta))

    logging_setup.log_run(log, cfg.model_for(repo), duration, note="(dry-run)")
    if result.error:
        print(f"\nNOTE: fail-open — review unavailable/unparsed ({result.error}).")
    return 0


def run(args) -> int:
    cfg = load_config(args.config)
    if not cfg.agent.enabled:  # master kill switch
        print("Crucible is disabled (agent.enabled=false). Nothing reviewed or posted.")
        return 0
    repo, repo_name, fallback = resolve_repo(cfg, args)
    if repo is None:
        if args.dry_run:  # local feedback
            print(f"ERROR: no repo in config matches {repo_name!r}", file=sys.stderr)
            print(f"  configured: {[r.name for r in cfg.repos]}", file=sys.stderr)
            return 2
        # Posting path: a missing config entry must NOT block a merge (fail-open).
        log.warning("no repo matches %r; failing open (nothing to review)", repo_name)
        print(f"\nFAIL-OPEN: no repo in config matches {repo_name!r}; nothing to review, exiting success.")
        return 0

    print_resolution(cfg, repo, repo_name, fallback, args)
    provider_name = args.provider or repo.provider

    if not args.dry_run:
        return run_post(cfg, repo, provider_name, args)

    diff_text = acquire_diff(args, repo, provider_name)
    if diff_text is None:
        print("\nNOTE: no diff source. Pass --diff-file <path> for local dry-run; "
              "in CI the provider supplies the diff.")
        return 0
    return run_engine(cfg, repo, diff_text)


def _unavailable_summary(cfg: Config, reason: str) -> str:
    result = ReviewResult(
        summary="Crucible review unavailable (an internal error occurred).",
        overall_risk=OverallRisk.MEDIUM,
        error=reason,
    )
    mode = "blocking" if cfg.review.fail_check_on != "none" else "advisory"
    meta = summary.SummaryMeta(mode=mode, model=cfg.model.default,
                               name=cfg.branding.name, logo_url=cfg.branding.logo_url)
    return summary.build_header(result, [], meta)


def run_post(cfg: Config, repo: RepoConfig, provider_name: str, args) -> int:
    """Non-dry-run: review → post. FAIL-OPEN — any agent/LLM/REST error finishes the
    step as success (exit 0) + a 'review unavailable' note. Only a fail_check_on
    finding (and only when gating is enabled) exits non-zero (§4 step 9, §8 CRITICAL)."""
    try:
        provider = get_provider(provider_name, pr_id=args.pr)
    except Exception as e:
        # Can't even construct the adapter → nothing to post to; stay fail-open.
        log.warning("provider unavailable, failing open: %s", e)
        print(f"\nFAIL-OPEN: provider unavailable ({e}); exiting success, merge not blocked.")
        return 0

    try:
        ctx = provider.get_pr_context()
        if cfg.agent.skip_draft_prs and ctx.is_draft:  # draft-PR skip
            print("\nDraft PR — skipped (agent.skip_draft_prs). Nothing posted.")
            return 0

        t0 = time.time()
        diff_text = Path(args.diff_file).read_text() if args.diff_file else provider.get_diff()
        result, files = engine.run_review(cfg, repo, diff_text)
        duration = time.time() - t0
        outcome = poster.post_review(provider, result, files, cfg,
                                     model=cfg.model_for(repo), duration_s=duration)
        logging_setup.log_run(log, cfg.model_for(repo), duration, note=f"(posted={outcome.posted})")

        s = outcome.stats
        print(
            f"\nPosted {outcome.posted} new comment(s). "
            f"(skipped: {s.skipped_existing} dup, {s.skipped_severity} below-severity, "
            f"{s.skipped_unanchored} off-diff, {s.capped} over-cap)"
        )
        if cfg.review.fail_check_on != "none" and outcome.gate_failed:
            print(f"GATE: a finding ≥ {cfg.review.fail_check_on} → check FAILED (merge blocked).")
            return 1
        print("GATE: check passed (advisory)." if cfg.review.fail_check_on == "none"
              else f"GATE: no finding ≥ {cfg.review.fail_check_on} → check passed.")
        return 0
    except Exception as e:
        log.warning("review run failed, failing open: %s", e)
        print(f"\nFAIL-OPEN: review error ({e}); posting 'review unavailable' note, merge not blocked.")
        try:
            provider.upsert_summary(_unavailable_summary(cfg, str(e)))
        except Exception as e2:
            log.warning("could not post 'review unavailable' note: %s", e2)
        try:
            provider.set_status("succeeded", "Crucible review unavailable")
        except Exception:
            pass
        return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    logging_setup.configure()
    try:
        return run(args)
    except ConfigError as e:
        print(f"CONFIG ERROR: {e}", file=sys.stderr)
        return 2
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
