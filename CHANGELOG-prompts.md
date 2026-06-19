# CHANGELOG — prompts, rules & dependencies

Every prompt/rule change and every dependency pin lands here: what changed + why.
This is the prompt-versioning discipline applied to the reviewer (Agent Spec §13.3).

---

## 2026-06-19 — Phase 0 scaffold

- **Created** starter `prompts/` (`system.md`, `review.md`, `summary.md`) and `rules/`
  (`global.md`, `projects/focus-*.md`, `languages/*.md`) at version `1.0` (Agent Spec §6).
- **Pinned** dependencies in `requirements.txt` / `pyproject.toml`:
  `litellm==1.55.10`, `requests==2.32.3`, `pyyaml==6.0.2`, `unidiff==0.7.5`, `pytest==8.3.4`.
  > ⚠️ Pins chosen offline — **verify/bump against the live index** before CI use (A10).
  > litellm is pinned deliberately (supply-chain hygiene, Agent Spec §7); never float `latest`.
- **Config default** `review.fail_check_on: none` — advisory pilot mode, never blocks a merge (D3).
