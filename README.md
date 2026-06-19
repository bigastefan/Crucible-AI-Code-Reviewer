# Crucible — AI Code Reviewer

A self-hosted, **multi-provider** AI pull-request reviewer that runs **inside your CI**
(Azure DevOps pipeline *or* GitHub Actions). On each PR it reads the diff, asks an LLM of
your choice to review it against your editable prompts + per-project rules, and posts the
findings back as inline comments plus a single summary — using **your own API key**.

Part of the *Forge* family — **Planner** designs, **Implementer** forges, **Crucible** tests.

## Why it's built this way

- **Provider-agnostic git host.** All host code lives behind one `GitProvider` interface in
  [`providers/`](providers/); `core/` never names a host. Azure is the first adapter, GitHub the
  second — adding a host is a new adapter, not a `core/` change.
- **LLM-agnostic.** Every model call goes through [`core/llm.py`](core/llm.py) via
  [LiteLLM](https://docs.litellm.ai). Swap Claude → Gemini → GPT by changing one config line
  and the matching API key. No vendor SDK, no hard-coded vendor.
- **Incremental.** Findings are de-duplicated across pushes via a hidden
  `<!-- crucible:{hash} -->` marker; one summary comment is edited in place, never re-posted.
- **Fail-open.** Any agent/LLM/REST error finishes the CI step as success with a "review
  unavailable" note — a broken run never blocks a merge. Only `fail_check_on` findings can fail
  the check (pilot default: `none`, advisory only).
- **Safe by default.** The diff is treated as untrusted (prompt-injection hardened); secrets are
  redacted before the LLM call and raised as Critical findings.

## Layout

```
crucible.py        CLI entrypoint:  crucible --pr <id> [--dry-run]
config.yaml        repos → rules, model, provider, thresholds
core/              provider- & model-neutral engine (diff parse, prompt, LLM, dedup, posting)
providers/         git-host adapters behind one GitProvider interface (azure.py, github.py)
prompts/ rules/    the editable content: how Crucible reviews
tests/             unit tests + authentic git-diff fixtures
docs/              the authoritative specs + delivery plan
```

## Quick start (local dry-run)

```bash
python -m venv .venv && source .venv/bin/activate     # Python 3.11+
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python crucible.py --pr <id> --repo "<repo in config>" --diff-file tests/fixtures/modify.diff --dry-run
```

`--dry-run` reviews and prints the findings JSON; it posts nothing.

### Local testing without an API key

For fast offline iteration you can feed a canned model response and a fixture diff — no key,
no network:

```bash
# CRUCIBLE_FAKE_LLM returns the file's contents instead of calling a provider
CRUCIBLE_FAKE_LLM=response.json python crucible.py \
  --pr 1 --repo "<repo in config>" --diff-file tests/fixtures/modify.diff --dry-run
```

## Status

Phase 1 (the agent) — in progress. Engine, diff parser, dedup, fail-open, the **Azure** adapter
and the **GitHub** adapter + Actions workflow are built and unit-tested. Azure CI pipeline wiring
is deferred to pilot onboarding. See [`plan.md`](plan.md) and [`docs/`](docs/) for the full plan.

## License

Internal project — all rights reserved (for now).
