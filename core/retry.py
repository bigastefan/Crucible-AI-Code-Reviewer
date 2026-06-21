"""Transient-error retry/backoff. Host-neutral (lives in core/, used by the LLM call
and optionally around provider REST calls — so no adapter needs to change)."""
from __future__ import annotations

import time as _time
from typing import Callable, Optional


def with_retry(
    fn: Callable,
    attempts: int = 3,
    base_delay: float = 0.5,
    transient: Optional[Callable[[Exception], bool]] = None,
    sleep: Optional[Callable[[float], None]] = None,
):
    """Call fn(); on a transient exception, retry up to `attempts` with exponential
    backoff. A non-transient exception (e.g. auth) is raised immediately. `sleep` is
    injectable so tests don't actually wait."""
    sleep = sleep or _time.sleep
    transient = transient or (lambda e: True)
    last: Optional[Exception] = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - we re-raise below
            last = e
            if i == attempts - 1 or not transient(e):
                raise
            sleep(base_delay * (2 ** i))
    raise last  # pragma: no cover
