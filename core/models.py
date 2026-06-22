"""Canonical data contracts for Crucible.

★ X-01 (Delivery Assurance): the Severity/Category value sets defined here are the
SINGLE source of truth. The Phase-2 dashboard imports these same enums for its charts
and filters — a drifted enum silently breaks reporting. The model must NEVER emit a
value outside these sets; `reviewer.py` validates and coerces against them (see `coerce`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class Severity(str, Enum):
    """Finding severity. Ordered; `rank` is used for gating + filtering."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return _SEVERITY_RANK[self]

    @classmethod
    def coerce(cls, value, default: "Severity | None" = None) -> "Severity":
        """Map any model output onto the canonical set. Never invents a value
        (A9): an unknown value falls back to `default` (medium) WITH a caller-side
        log rather than being dropped — we'd rather keep a possibly-real finding."""
        if isinstance(value, cls):
            return value
        key = str(value).strip().lower()
        try:
            return cls(key)
        except ValueError:
            return _SEVERITY_SYNONYMS.get(key, default or cls.MEDIUM)


_SEVERITY_RANK = {
    Severity.LOW: 0,
    Severity.MEDIUM: 1,
    Severity.HIGH: 2,
    Severity.CRITICAL: 3,
}

# Common LLM phrasings → canonical severity.
_SEVERITY_SYNONYMS = {
    "info": Severity.LOW,
    "informational": Severity.LOW,
    "trivial": Severity.LOW,
    "nit": Severity.LOW,
    "minor": Severity.LOW,
    "warning": Severity.MEDIUM,
    "moderate": Severity.MEDIUM,
    "major": Severity.HIGH,
    "severe": Severity.HIGH,
    "blocker": Severity.CRITICAL,
    "blocking": Severity.CRITICAL,
    "fatal": Severity.CRITICAL,
}


class Category(str, Enum):
    """Finding category. Reused verbatim by the Phase-2 dashboard (X-01)."""

    BUG = "bug"
    SECURITY = "security"
    PERFORMANCE = "performance"
    TEST = "test"
    MAINTAINABILITY = "maintainability"
    STYLE = "style"

    @classmethod
    def coerce(cls, value, default: "Category | None" = None) -> "Category":
        if isinstance(value, cls):
            return value
        key = str(value).strip().lower()
        try:
            return cls(key)
        except ValueError:
            return _CATEGORY_SYNONYMS.get(key, default or cls.MAINTAINABILITY)


_CATEGORY_SYNONYMS = {
    "bugs": Category.BUG,
    "correctness": Category.BUG,
    "logic": Category.BUG,
    "sec": Category.SECURITY,
    "vulnerability": Category.SECURITY,
    "vuln": Category.SECURITY,
    "perf": Category.PERFORMANCE,
    "tests": Category.TEST,
    "testing": Category.TEST,
    "maintainable": Category.MAINTAINABILITY,
    "maintainablity": Category.MAINTAINABILITY,
    "readability": Category.MAINTAINABILITY,
    "clarity": Category.MAINTAINABILITY,
    "cleanliness": Category.MAINTAINABILITY,
    "cosmetic": Category.STYLE,
    "formatting": Category.STYLE,
}


class OverallRisk(str, Enum):
    """Top-level PR risk in the review summary (§10: low | medium | high)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @classmethod
    def coerce(cls, value, default: "OverallRisk | None" = None) -> "OverallRisk":
        if isinstance(value, cls):
            return value
        key = str(value).strip().lower()
        try:
            return cls(key)
        except ValueError:
            if key == "critical":  # model sometimes over-reaches; clamp to our top
                return cls.HIGH
            return default or cls.MEDIUM


@dataclass
class Finding:
    """One review comment, anchored to a right-side (new-file) line."""

    file: str
    line: int
    severity: Severity
    category: Category
    title: str
    comment: str
    suggestion: Optional[str] = None
    # Internal dedup key (file|category|anchored-line-content), set by the poster.
    # Not part of the §10 JSON contract. Stable across line drift AND LLM title drift.
    dedup_hash: Optional[str] = None


@dataclass
class Coverage:
    """What the agent actually reviewed — for the summary header (computed in code)."""

    files_reviewed: int = 0
    files_skipped: int = 0  # excluded by exclude_paths
    changed_lines: int = 0
    tests_missing: bool = False  # added non-test source but touched no test/spec file
    oversized: bool = False  # size guard tripped → model review skipped


@dataclass
class ReviewResult:
    """The validated output of one review run (the §10 contract, coerced)."""

    summary: str
    overall_risk: OverallRisk
    findings: List[Finding] = field(default_factory=list)
    # Set when the review could not be produced/parsed. Drives the "review
    # unavailable" note while keeping the run fail-open (never raises).
    error: Optional[str] = None
    # Internal (not in the §10 JSON contract): coverage metadata for the header.
    coverage: Optional[Coverage] = None


@dataclass
class PRContext:
    """Host-neutral PR identity, produced by a GitProvider adapter (§8)."""

    repo: str
    pr_id: int
    title: str = ""
    target_branch: str = ""
    source_branch: str = ""
    is_draft: bool = False
    head_sha: str = ""  # required by GitHub's inline-comment API (commit_id)


def finding_as_dict(f: Finding) -> dict:
    return {
        "file": f.file,
        "line": f.line,
        "severity": f.severity.value,
        "category": f.category.value,
        "title": f.title,
        "comment": f.comment,
        "suggestion": f.suggestion,
    }


def review_as_dict(r: ReviewResult) -> dict:
    return {
        "summary": r.summary,
        "overall_risk": r.overall_risk.value,
        "findings": [finding_as_dict(f) for f in r.findings],
        "error": r.error,
    }


def build_output_schema() -> str:
    """The §10 JSON shape the model must return, with the enum value sets inlined.

    Generated FROM the canonical enums so the prompt can never drift from the
    contract the dashboard reuses (X-01)."""
    sev = " | ".join(s.value for s in Severity)
    cat = " | ".join(c.value for c in Category)
    risk = " | ".join(r.value for r in OverallRisk)
    return (
        "{\n"
        '  "summary": "2-4 sentence overview: what this PR does and the overall risk.",\n'
        f'  "overall_risk": "{risk}",\n'
        '  "findings": [\n'
        "    {\n"
        '      "file": "src/app/foo.ts",\n'
        '      "line": 42,\n'
        f'      "severity": "{sev}",\n'
        f'      "category": "{cat}",\n'
        '      "title": "Short headline",\n'
        '      "comment": "What is wrong, why it matters, how to fix.",\n'
        '      "suggestion": "Optional replacement snippet, or null."\n'
        "    }\n"
        "  ]\n"
        "}"
    )
