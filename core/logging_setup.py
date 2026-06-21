"""Structured logging + the per-run cost/duration line.

NEVER logs the diff content or any secret — only metadata (model, duration, cost,
masked secret KINDS). Log level from CRUCIBLE_LOG_LEVEL (default INFO).
"""
from __future__ import annotations

import logging
import os


def configure() -> None:
    level = os.environ.get("CRUCIBLE_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def log_run(logger: logging.Logger, model: str, duration_s: float, note: str = "") -> None:
    """One per-run summary line. Caller passes only non-sensitive metadata."""
    extra = f" {note}" if note else ""
    logger.info("run: model=%s duration=%.2fs%s", model, duration_s, extra)
