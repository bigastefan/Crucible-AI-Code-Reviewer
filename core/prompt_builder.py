"""Assemble the final prompt: system.md + global/project/language rules + the
(already-redacted) diff, via review.md. Provider- and model-neutral.

Prompts/rules are read from files — NEVER hard-coded here (Agent Spec §12). The diff
is placed under an explicitly-labelled untrusted section; system.md carries the
injection-hardening that tells the model to treat it as data, never instructions.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple

from core.config import Config, RepoConfig
from core.models import build_output_schema

_HEADER_RE = re.compile(r"^\s*<!--.*?-->\s*", re.DOTALL)


def _read(path: Path) -> str:
    return path.read_text()


def _strip_version_header(text: str) -> str:
    """Crucible reads the body and ignores the leading `<!-- version ... -->` header (§6.1)."""
    return _HEADER_RE.sub("", text, count=1).lstrip("\n")


def _read_body(path: Path) -> str:
    return _strip_version_header(_read(path)).strip()


def load_rules(config: Config, repo: Optional[RepoConfig]) -> Tuple[str, str, str]:
    """Return (global_rules, project_rules, language_rules) as text blocks.

    Unmatched file types / no project rule → that block reads "(none)"; global rules
    still apply everywhere (gap P1-13 / plan A8: review with global rules only)."""
    root = config.root
    global_path = root / "rules" / "global.md"
    global_rules = _read_body(global_path) if global_path.exists() else "(none)"

    if repo is None:
        return global_rules, "(none)", "(none)"

    project_path = root / "rules" / "projects" / f"{repo.project_rules}.md"
    project_rules = _read_body(project_path) if project_path.exists() else "(none)"

    lang_blocks: List[str] = []
    for lang in repo.language_rules:
        p = root / "rules" / "languages" / f"{lang}.md"
        if p.exists():
            lang_blocks.append(f"### {lang}\n{_read_body(p)}")
    language_rules = "\n\n".join(lang_blocks) if lang_blocks else "(none)"

    return global_rules, project_rules, language_rules


def build_prompts(
    config: Config, repo: Optional[RepoConfig], diff_text: str
) -> Tuple[str, str]:
    """Return (system_prompt, user_prompt). The diff must already be redacted."""
    root = config.root
    system_prompt = _read_body(root / "prompts" / "system.md")
    template = _read_body(root / "prompts" / "review.md")

    global_rules, project_rules, language_rules = load_rules(config, repo)
    project_name = repo.name if repo is not None else "(unmatched repo)"

    # str.replace (not str.format) so braces in the diff/rules/schema are never
    # interpreted as format fields.
    replacements = {
        "{global_rules}": global_rules,
        "{project_name}": project_name,
        "{project_rules}": project_rules,
        "{language_rules}": language_rules,
        "{diff}": diff_text,
        "{output_schema}": build_output_schema(),
    }
    user_prompt = template
    for key, val in replacements.items():
        user_prompt = user_prompt.replace(key, val)

    return system_prompt, user_prompt
