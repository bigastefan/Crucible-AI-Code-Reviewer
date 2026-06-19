"""Phase 0 — canonical enums + coercion (X-01). The model must never produce a
value outside these sets; coercion maps anything else onto the contract."""
from core.models import Category, OverallRisk, Severity


def test_severity_canonical_values():
    assert [s.value for s in Severity] == ["low", "medium", "high", "critical"]


def test_severity_ordering():
    assert Severity.LOW.rank < Severity.MEDIUM.rank < Severity.HIGH.rank < Severity.CRITICAL.rank


def test_category_canonical_values():
    assert {c.value for c in Category} == {
        "bug", "security", "performance", "test", "maintainability", "style"
    }


def test_severity_coerce_exact_and_case():
    assert Severity.coerce("HIGH") is Severity.HIGH
    assert Severity.coerce(" critical ") is Severity.CRITICAL


def test_severity_coerce_synonyms():
    assert Severity.coerce("blocker") is Severity.CRITICAL
    assert Severity.coerce("warning") is Severity.MEDIUM
    assert Severity.coerce("nit") is Severity.LOW


def test_severity_coerce_unknown_defaults_medium():
    # Never invent a value; fall back rather than drop (A9).
    assert Severity.coerce("???") is Severity.MEDIUM
    assert Severity.coerce("???", default=Severity.LOW) is Severity.LOW


def test_category_coerce_synonyms_and_unknown():
    assert Category.coerce("perf") is Category.PERFORMANCE
    assert Category.coerce("vulnerability") is Category.SECURITY
    assert Category.coerce("whatever") is Category.MAINTAINABILITY


def test_overall_risk_clamps_critical_to_high():
    assert OverallRisk.coerce("critical") is OverallRisk.HIGH
    assert OverallRisk.coerce("LOW") is OverallRisk.LOW
