"""Load + validate config.yaml and resolve a repo to its rules + provider.

`core/` is provider- and model-NEUTRAL. This module reads the `provider:` string
and the `model:` string but never imports an adapter or an LLM SDK.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from core.models import Severity

VALID_PROVIDERS = {"azure", "github"}
VALID_FAIL_CHECK_ON = {"none"} | {s.value for s in Severity}
VALID_MIN_SEVERITY = {s.value for s in Severity}


class ConfigError(ValueError):
    """Raised on a malformed or invalid config.yaml. Surfaced clearly to the user."""


@dataclass
class ModelConfig:
    default: str
    max_tokens: int = 8000


@dataclass
class ReviewConfig:
    min_severity_to_post: str = "low"
    fail_check_on: str = "none"  # pilot default: advisory, never blocks a merge (D3)
    max_diff_lines: int = 4000
    max_diff_tokens: int = 60000
    max_findings: int = 30


@dataclass
class AgentConfig:
    enabled: bool = True  # master kill switch
    on_error: str = "pass"  # fail-open
    skip_draft_prs: bool = True
    redact_secrets: bool = True


@dataclass
class BrandingConfig:
    name: str = "Crucible"
    logo_url: Optional[str] = None  # raw image URL; None/blank → text-only header


@dataclass
class RepoConfig:
    name: str
    provider: str
    match: str
    project_rules: str
    language_rules: List[str] = field(default_factory=list)
    model: Optional[str] = None  # optional per-repo provider/model override


@dataclass
class Config:
    model: ModelConfig
    review: ReviewConfig
    agent: AgentConfig
    branding: BrandingConfig
    repos: List[RepoConfig]
    exclude_paths: List[str]
    path: Path  # where config.yaml was loaded from (rules/ resolves relative to its parent)

    @property
    def root(self) -> Path:
        return self.path.parent

    def model_for(self, repo: Optional[RepoConfig]) -> str:
        """Per-repo model override, else the global default."""
        if repo is not None and repo.model:
            return repo.model
        return self.model.default

    def rule_paths(self, repo: RepoConfig) -> Dict[str, object]:
        """Resolve the rule files this repo maps to. Reports existence so Phase 0
        can surface a missing rule file without an API call."""
        root = self.root
        glob = root / "rules" / "global.md"
        project = root / "rules" / "projects" / f"{repo.project_rules}.md"
        languages = [
            root / "rules" / "languages" / f"{lang}.md" for lang in repo.language_rules
        ]
        return {
            "global": (glob, glob.exists()),
            "project": (project, project.exists()),
            "languages": [(p, p.exists()) for p in languages],
        }


def _require(d: dict, key: str, where: str):
    if key not in d:
        raise ConfigError(f"Missing required key '{key}' in {where}")
    return d[key]


def load_config(path) -> Config:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:  # pragma: no cover - passthrough of parse error
        raise ConfigError(f"config.yaml is not valid YAML: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError("config.yaml must be a mapping at the top level")

    model_raw = _require(raw, "model", "config.yaml")
    model = ModelConfig(
        default=_require(model_raw, "default", "model"),
        max_tokens=int(model_raw.get("max_tokens", 8000)),
    )

    review_raw = raw.get("review", {}) or {}
    review = ReviewConfig(
        min_severity_to_post=str(review_raw.get("min_severity_to_post", "low")).lower(),
        fail_check_on=str(review_raw.get("fail_check_on", "none")).lower(),
        max_diff_lines=int(review_raw.get("max_diff_lines", 4000)),
        max_diff_tokens=int(review_raw.get("max_diff_tokens", 60000)),
        max_findings=int(review_raw.get("max_findings", 30)),
    )
    if review.fail_check_on not in VALID_FAIL_CHECK_ON:
        raise ConfigError(
            f"review.fail_check_on={review.fail_check_on!r} invalid; "
            f"expected one of {sorted(VALID_FAIL_CHECK_ON)}"
        )
    if review.min_severity_to_post not in VALID_MIN_SEVERITY:
        raise ConfigError(
            f"review.min_severity_to_post={review.min_severity_to_post!r} invalid; "
            f"expected one of {sorted(VALID_MIN_SEVERITY)}"
        )

    agent_raw = raw.get("agent", {}) or {}
    agent = AgentConfig(
        enabled=bool(agent_raw.get("enabled", True)),
        on_error=str(agent_raw.get("on_error", "pass")).lower(),
        skip_draft_prs=bool(agent_raw.get("skip_draft_prs", True)),
        redact_secrets=bool(agent_raw.get("redact_secrets", True)),
    )
    if agent.on_error not in {"pass", "fail"}:
        raise ConfigError(f"agent.on_error={agent.on_error!r} invalid; expected 'pass' or 'fail'")

    repos_raw = raw.get("repos", []) or []
    if not isinstance(repos_raw, list):
        raise ConfigError("repos must be a list")
    repos: List[RepoConfig] = []
    for i, r in enumerate(repos_raw):
        where = f"repos[{i}]"
        provider = str(_require(r, "provider", where)).lower()
        if provider not in VALID_PROVIDERS:
            raise ConfigError(
                f"{where}.provider={provider!r} invalid; expected one of {sorted(VALID_PROVIDERS)}"
            )
        repos.append(
            RepoConfig(
                name=_require(r, "name", where),
                provider=provider,
                match=_require(r, "match", where),
                project_rules=_require(r, "project_rules", where),
                language_rules=list(r.get("language_rules", []) or []),
                model=r.get("model"),
            )
        )

    branding_raw = raw.get("branding", {}) or {}
    logo_url = branding_raw.get("logo_url")
    branding = BrandingConfig(
        name=str(branding_raw.get("name", "Crucible")),
        logo_url=(str(logo_url).strip() or None) if logo_url else None,
    )

    exclude_paths = list(raw.get("exclude_paths", []) or [])

    return Config(
        model=model,
        review=review,
        agent=agent,
        branding=branding,
        repos=repos,
        exclude_paths=exclude_paths,
        path=path,
    )


def default_repo(name: str, provider: str) -> RepoConfig:
    """Fallback config for a repo NOT listed in config.yaml (minimal onboarding, O1):
    review with global rules only (no project/language rules)."""
    return RepoConfig(name=name, provider=provider, match=name, project_rules="", language_rules=[])


def match_repo(config: Config, repo_name: str) -> Optional[RepoConfig]:
    """Resolve a repo name to its config block.

    Priority: exact `name` match → exact `match` match → substring `match`.
    `match` is the substring/exact key from §6.3 ("Focus.Api", "acme-org/acme-web").
    Returns None if nothing matches (caller decides how to handle).
    """
    if not repo_name:
        return None
    for repo in config.repos:  # exact name
        if repo.name == repo_name:
            return repo
    for repo in config.repos:  # exact match key
        if repo.match == repo_name:
            return repo
    for repo in config.repos:  # substring on the match key
        if repo.match and repo.match in repo_name:
            return repo
    return None
