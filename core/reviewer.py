"""Orchestrate the review: call the model, parse the ONE JSON object it must return
(§10), validate + coerce to the canonical enums, and FAIL SAFE.

Hard rule (§10, plan §5): a malformed model response must NEVER crash the run. Any
parse/validation problem yields a ReviewResult with `error` set and a single
human-readable note — the caller posts that and the pipeline stays fail-open.
"""
from __future__ import annotations

import json
import logging
from typing import Callable, Optional

from core import llm
from core.models import (
    Category,
    Finding,
    OverallRisk,
    ReviewResult,
    Severity,
)

log = logging.getLogger("crucible.reviewer")

CompleteFn = Callable[[str, str, str, int], str]

_PARSE_FAILED_NOTE = (
    "Crucible could not parse the model's response into the expected JSON contract, "
    "so no findings were produced. The run did not fail."
)
_UNAVAILABLE_NOTE = (
    "Crucible review unavailable (the model call failed). The run did not fail; "
    "this is advisory only."
)


def review(
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 8000,
    complete_fn: Optional[CompleteFn] = None,
) -> ReviewResult:
    """Run one review. Never raises — returns a ReviewResult, with `error` set on failure."""
    fn = complete_fn or llm.complete
    try:
        raw = fn(model, system_prompt, user_prompt, max_tokens)
    except Exception as e:  # LLM/transport failure → fail-open note
        log.warning("LLM call failed: %s", e)
        return ReviewResult(summary=_UNAVAILABLE_NOTE, overall_risk=OverallRisk.MEDIUM, error=str(e))
    return parse_review(raw)


def parse_review(raw: str) -> ReviewResult:
    """Parse + validate + coerce the model output. Never raises."""
    try:
        data = _extract_json(raw)
        if not isinstance(data, dict):
            log.warning("model output was not a JSON object")
            return ReviewResult(summary=_PARSE_FAILED_NOTE, overall_risk=OverallRisk.MEDIUM, error="not_a_json_object")

        summary = str(data.get("summary") or "").strip()
        overall_risk = OverallRisk.coerce(data.get("overall_risk"))

        findings = []
        raw_findings = data.get("findings")
        if isinstance(raw_findings, list):
            for item in raw_findings:
                f = _coerce_finding(item)
                if f is not None:
                    findings.append(f)

        return ReviewResult(summary=summary, overall_risk=overall_risk, findings=findings)
    except Exception as e:  # belt-and-suspenders: parsing must never crash the run
        log.warning("unexpected error parsing model output: %s", e)
        return ReviewResult(summary=_PARSE_FAILED_NOTE, overall_risk=OverallRisk.MEDIUM, error=str(e))


def _coerce_finding(item) -> Optional[Finding]:
    """Coerce one finding dict to the canonical contract. Drops a finding only if it
    can't be anchored (no file, or no usable line) — otherwise keeps it, coercing
    severity/category onto the enum sets (never invents values, X-01)."""
    if not isinstance(item, dict):
        return None
    file = str(item.get("file") or "").strip()
    if not file:
        return None
    line = _coerce_int(item.get("line"))
    if line is None or line < 1:
        # No valid right-side line → can't anchor an inline comment. Skip it; the
        # summary still reflects overall risk. (Phase 3 only posts commentable lines.)
        log.info("dropping finding without a valid line: %r", item.get("title"))
        return None
    return Finding(
        file=file,
        line=line,
        severity=Severity.coerce(item.get("severity")),
        category=Category.coerce(item.get("category")),
        title=str(item.get("title") or "").strip() or "(untitled finding)",
        comment=str(item.get("comment") or "").strip(),
        suggestion=_clean_suggestion(item.get("suggestion")),
    )


def _coerce_int(value) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _clean_suggestion(value) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() in {"null", "none", "n/a"}:
        return None
    return s


def _extract_json(raw: str):
    """Defensively pull a JSON object out of the model output: tolerate ```json
    fences and leading/trailing prose by falling back to balanced-brace extraction."""
    if raw is None:
        return None
    text = raw.strip()

    # Strip a ```json ... ``` or ``` ... ``` fence if present.
    if text.startswith("```"):
        text = text[3:]
        if text[:4].lower() == "json":
            text = text[4:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fallback: find the first balanced {...} block.
    block = _first_json_object(text)
    if block is None:
        return None
    try:
        return json.loads(block)
    except json.JSONDecodeError:
        return None


def _first_json_object(text: str) -> Optional[str]:
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None
