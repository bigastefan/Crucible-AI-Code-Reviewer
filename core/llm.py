"""The ONLY file that calls a model. Provider-agnostic via LiteLLM.

The vendor is NEVER named here — it comes from the `model:` string in config
(e.g. "anthropic/claude-sonnet-4-6", "gemini/gemini-2.5-pro"). Swapping providers is
a config + API-key change with NO code change. litellm is imported lazily so config-
only / dry-resolution paths never need it installed.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import List

from core.retry import with_retry

log = logging.getLogger("crucible.llm")

_TRANSIENT_HINTS = (
    "rate limit", "ratelimit", "429", "timeout", "timed out", "temporarily",
    "overloaded", "503", "502", "500", "connection", "unavailable",
)


class LLMError(RuntimeError):
    """Any failure talking to the model. Caught upstream to keep the run fail-open."""


def _is_transient(e: Exception) -> bool:
    """Retry rate-limits/timeouts/5xx; do NOT retry auth/permission errors."""
    s = str(e).lower()
    if any(k in s for k in ("auth", "api key", "api-key", "401", "403", "invalid")):
        return False
    return any(k in s for k in _TRANSIENT_HINTS)


def estimate_tokens(model: str, text: str) -> int:
    """Best-effort token count for the size guard. Uses litellm if available, else a
    chars/4 heuristic (no hard dependency for offline/dry-run)."""
    try:
        import litellm

        return int(litellm.token_counter(model=model, text=text))
    except Exception:
        return max(1, len(text or "") // 4)


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

    def _call():
        return litellm.completion(
            model=model, messages=messages, max_tokens=max_tokens, temperature=temperature
        )

    start = time.time()
    try:
        resp = with_retry(_call, attempts=3, base_delay=0.5, transient=_is_transient)
    except Exception as e:  # normalize every provider error into one type
        raise LLMError(f"model call failed ({model}): {e}") from e
    duration = time.time() - start

    # Per-call cost/duration log (never logs the prompt/diff or any secret).
    try:
        cost = litellm.completion_cost(completion_response=resp)
        log.info("llm: model=%s duration=%.2fs cost=$%.4f", model, duration, cost)
    except Exception:
        log.info("llm: model=%s duration=%.2fs", model, duration)

    try:
        return resp.choices[0].message.content or ""
    except (AttributeError, IndexError, KeyError) as e:  # pragma: no cover
        raise LLMError(f"unexpected response shape from {model}: {e}") from e
