"""Phase 6 — transient-error retry/backoff (core/retry.py)."""
import pytest

from core.retry import with_retry


def test_retries_transient_then_succeeds():
    calls = {"n": 0}
    slept = []

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("rate limit")
        return "ok"

    out = with_retry(fn, attempts=3, base_delay=0.01,
                     transient=lambda e: True, sleep=lambda s: slept.append(s))
    assert out == "ok" and calls["n"] == 3
    assert len(slept) == 2  # slept between the 3 attempts


def test_does_not_retry_non_transient():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise RuntimeError("AuthenticationError")

    with pytest.raises(RuntimeError, match="Authentication"):
        with_retry(fn, attempts=5, transient=lambda e: False, sleep=lambda s: None)
    assert calls["n"] == 1  # no retries


def test_raises_after_exhausting_attempts():
    def fn():
        raise RuntimeError("timeout")

    with pytest.raises(RuntimeError, match="timeout"):
        with_retry(fn, attempts=3, transient=lambda e: True, sleep=lambda s: None)


def test_llm_transient_classifier():
    from core.llm import _is_transient

    assert _is_transient(RuntimeError("429 rate limit")) is True
    assert _is_transient(RuntimeError("Read timed out")) is True
    assert _is_transient(RuntimeError("401 invalid api key")) is False
