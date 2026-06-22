"""Phase 0 — config loading, validation, and repo→rules/provider resolution."""
from pathlib import Path

import pytest

from core.config import ConfigError, load_config, match_repo

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config.yaml"


def test_loads_real_config():
    cfg = load_config(CONFIG)
    assert cfg.model.default == "anthropic/claude-sonnet-4-6"
    assert cfg.review.fail_check_on == "none"  # pilot advisory default (D3)
    assert cfg.agent.enabled is True
    assert cfg.agent.on_error == "pass"
    assert len(cfg.repos) == 4
    assert cfg.exclude_paths  # non-empty


def test_match_by_exact_name():
    cfg = load_config(CONFIG)
    repo = match_repo(cfg, "Focus Backend")
    assert repo is not None and repo.provider == "azure"
    assert repo.project_rules == "focus-backend"
    assert repo.language_rules == ["csharp", "sql"]


def test_match_by_substring_match_key():
    cfg = load_config(CONFIG)
    # An Azure repo name that contains the configured match key "Focus.Api".
    repo = match_repo(cfg, "MyOrg/Focus.Api")
    assert repo is not None and repo.name == "Focus Backend"


def test_match_github_owner_repo():
    cfg = load_config(CONFIG)
    repo = match_repo(cfg, "bigastefan/Crucible-AI-Code-Reviewer")
    assert repo is not None and repo.provider == "github"
    assert repo.language_rules == ["python"]


def test_no_match_returns_none():
    cfg = load_config(CONFIG)
    assert match_repo(cfg, "totally-unknown-repo") is None


def test_model_override_per_repo(tmp_path):
    cfg_text = (
        "model:\n  default: anthropic/claude-sonnet-4-6\n"
        "repos:\n"
        "  - name: A\n    provider: azure\n    match: A\n    project_rules: a\n"
        "    model: gemini/gemini-2.5-pro\n"
        "  - name: B\n    provider: github\n    match: B\n    project_rules: b\n"
    )
    p = tmp_path / "config.yaml"
    p.write_text(cfg_text)
    cfg = load_config(p)
    assert cfg.model_for(match_repo(cfg, "A")) == "gemini/gemini-2.5-pro"
    assert cfg.model_for(match_repo(cfg, "B")) == "anthropic/claude-sonnet-4-6"


def test_rule_paths_existence():
    cfg = load_config(CONFIG)
    rules = cfg.rule_paths(match_repo(cfg, "Focus Backend"))
    assert rules["global"][1] is True
    assert rules["project"][1] is True  # rules/projects/focus-backend.md exists
    langs = {p.name: exists for p, exists in rules["languages"]}
    assert langs == {"csharp.md": True, "sql.md": True}


def _write(tmp_path, body):
    p = tmp_path / "config.yaml"
    p.write_text(body)
    return p


def test_rejects_unknown_provider(tmp_path):
    body = (
        "model:\n  default: x\n"
        "repos:\n  - name: A\n    provider: gitlab\n    match: A\n    project_rules: a\n"
    )
    with pytest.raises(ConfigError, match="provider"):
        load_config(_write(tmp_path, body))


def test_rejects_bad_fail_check_on(tmp_path):
    body = "model:\n  default: x\nreview:\n  fail_check_on: sometimes\n"
    with pytest.raises(ConfigError, match="fail_check_on"):
        load_config(_write(tmp_path, body))


def test_rejects_bad_min_severity(tmp_path):
    body = "model:\n  default: x\nreview:\n  min_severity_to_post: spicy\n"
    with pytest.raises(ConfigError, match="min_severity_to_post"):
        load_config(_write(tmp_path, body))


def test_rejects_bad_on_error(tmp_path):
    body = "model:\n  default: x\nagent:\n  on_error: explode\n"
    with pytest.raises(ConfigError, match="on_error"):
        load_config(_write(tmp_path, body))


def test_missing_model_default(tmp_path):
    body = "model:\n  max_tokens: 8000\nreview:\n  fail_check_on: none\n"
    with pytest.raises(ConfigError, match="default"):
        load_config(_write(tmp_path, body))


def test_missing_file():
    with pytest.raises(ConfigError, match="not found"):
        load_config("/nope/does-not-exist.yaml")


def test_branding_parsed_from_real_config():
    cfg = load_config(CONFIG)
    assert cfg.branding.name == "Crucible"
    assert cfg.branding.logo_url and cfg.branding.logo_url.endswith("crucible-logo.png")


def test_branding_defaults_when_absent(tmp_path):
    body = "model:\n  default: x\nrepos:\n  - name: A\n    provider: azure\n    match: A\n    project_rules: a\n"
    cfg = load_config(_write(tmp_path, body))
    assert cfg.branding.name == "Crucible" and cfg.branding.logo_url is None


def test_default_repo_uses_global_rules_only():
    # O1: a repo not in config falls back to global rules (minimal stub onboarding).
    from core.config import default_repo
    from core.prompt_builder import load_rules

    cfg = load_config(CONFIG)
    repo = default_repo("some-org/brand-new", "github")
    assert repo.provider == "github" and repo.project_rules == "" and repo.language_rules == []
    g, p, l = load_rules(cfg, repo)
    assert "hard-coded secret" in g  # global rules apply
    assert p == "(none)" and l == "(none)"
