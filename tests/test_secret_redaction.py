"""Phase 6 — secret redaction (GP-03 / T1-07). The value must never reach the model,
appear in a finding, or be logged; each secret is raised as a Critical/security finding."""
import json
from pathlib import Path

from core import engine, secrets
from core.config import load_config, match_repo
from core.diff import parse_diff
from core.models import Category, Severity

ROOT = Path(__file__).resolve().parent.parent

AWS = "AKIAIOSFODNN7EXAMPLE"
SK = "sk-abcdefghijklmnopqrstuvwxyz1234"
PWD = "hunter2longpassword"
SECRET_VALUES = [AWS, SK, PWD]

SECRET_DIFF = (
    "diff --git a/cfg.py b/cfg.py\n--- a/cfg.py\n+++ b/cfg.py\n"
    "@@ -1,1 +1,4 @@\n"
    " print()\n"
    f'+AWS_KEY = "{AWS}"\n'
    f'+api_key = "{SK}"\n'
    f'+password = "{PWD}"\n'
)

NORMAL_DIFF = (
    "diff --git a/app.ts b/app.ts\n--- a/app.ts\n+++ b/app.ts\n"
    "@@ -1,1 +1,2 @@\n const a = 1;\n"
    '+const name = "anonymous";\n'
)


def test_mask_removes_every_secret_value():
    masked, kinds = secrets.mask_secrets(SECRET_DIFF)
    for v in SECRET_VALUES:
        assert v not in masked
    assert "***REDACTED:" in masked
    assert kinds  # something detected


def test_findings_are_critical_security_at_right_lines_without_values():
    findings = secrets.find_secret_findings(parse_diff(SECRET_DIFF))
    assert len(findings) >= 3
    for f in findings:
        assert f.severity is Severity.CRITICAL and f.category is Category.SECURITY
        assert f.file == "cfg.py" and f.line in (2, 3, 4)
        blob = f.title + f.comment + (f.suggestion or "")
        for v in SECRET_VALUES:
            assert v not in blob  # value NEVER in the finding


def test_no_false_positive_on_ordinary_code():
    masked, kinds = secrets.mask_secrets(NORMAL_DIFF)
    assert "anonymous" in masked and not kinds
    assert secrets.find_secret_findings(parse_diff(NORMAL_DIFF)) == []


def test_engine_redacts_before_the_model_call_and_flags_critical():
    cfg = load_config(ROOT / "config.yaml")
    repo = match_repo(cfg, "Focus Backend")
    captured = {}

    def capture(model, system, user, max_tokens):
        captured["user"] = user  # exactly what would be sent to the provider
        return json.dumps({"summary": "ok", "overall_risk": "low", "findings": []})

    result, files = engine.run_review(cfg, repo, SECRET_DIFF, complete_fn=capture)

    # The outbound prompt contains NONE of the secret values.
    for v in SECRET_VALUES:
        assert v not in captured["user"]
    # Critical security findings were still raised (deterministically, not by the model).
    sec = [f for f in result.findings if f.category is Category.SECURITY]
    assert sec and all(f.severity is Severity.CRITICAL for f in sec)
