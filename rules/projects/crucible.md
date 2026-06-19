<!-- version: 1.0 | project: Crucible (this repo) -->

- `core/` must stay provider- AND model-neutral: flag any import of `providers/*` or a vendor
  SDK (e.g. `anthropic`, `openai`) inside `core/`. All model calls go through `core/llm.py`.
- Git-host specifics belong only in `providers/`; flag host names (Azure/GitHub) leaking into `core/`.
- Fail-open is sacred: flag any new top-level code path that could raise and block a CI merge
  instead of finishing success with a "review unavailable" note.
- Never hard-code prompts/rules in `.py` — they live in `prompts/` and `rules/`.
- Flag any logging/printing of secrets or the diff content to logs/artifacts.
- New behaviour in `core/` should come with a unit test under `tests/`.
