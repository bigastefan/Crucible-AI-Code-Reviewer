"""The ONLY file that calls a model. Provider-agnostic via LiteLLM.

The vendor is NEVER named here — it comes from the `model:` string in config
(e.g. "anthropic/claude-sonnet-4-6", "gemini/gemini-2.5-pro"). Swapping providers is
a config + API-key change with NO code change. litellm is imported lazily so config-
only / dry-resolution paths never need it installed.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List


class LLMError(RuntimeError):
    """Any failure talking to the model. Caught upstream to keep the run fail-open."""


def complete(
    model: str,
    system: str,
    user: str,
    max_tokens: int = 8000,
    temperature: float = 0.0,
) -> str:
    """Single completion call. Returns the raw response text (the JSON contract is
    parsed/validated in reviewer.py — this layer makes no assumptions about content).

    Local-testing hook: if CRUCIBLE_FAKE_LLM points to a file, its contents are
    returned verbatim instead of calling a provider. Lets the full --dry-run pipeline
    run offline with no API key. It NEVER bypasses LiteLLM in CI (the env var is unset).
    """
    fake = os.environ.get("CRUCIBLE_FAKE_LLM")
    if fake:
        return Path(fake).read_text()

    try:
        import litellm  # lazy: only needed for a real call
    except ImportError as e:  # pragma: no cover
        raise LLMError(
            "litellm is not installed; `pip install -r requirements.txt`"
        ) from e

    messages: List[dict] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    try:
        resp = litellm.completion(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    except Exception as e:  # normalize every provider error into one type
        raise LLMError(f"model call failed ({model}): {e}") from e

    try:
        return resp.choices[0].message.content or ""
    except (AttributeError, IndexError, KeyError) as e:  # pragma: no cover
        raise LLMError(f"unexpected response shape from {model}: {e}") from e
