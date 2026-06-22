"""The GitProvider abstraction (Agent Spec §8).

This is the ONLY seam between `core/` and a git host. `core/` calls exclusively
through this Protocol; it never imports `providers/azure` or `providers/github`
directly. Adding a host = adding an adapter here, with NO `core/` change (X-04).

Adapter bodies are NOT implemented in Phase 0:
  - Azure  → Phase 3 (providers/azure.py)
  - GitHub → Phase 5 (providers/github.py)
"""
from __future__ import annotations

from typing import List, Optional, Set, Tuple

from core.models import Finding, PRContext


class GitProvider:
    """Interface every git-host adapter implements.

    Defined as a base class (not just a typing.Protocol) so the factory can return
    instances and unimplemented adapters raise a clear NotImplementedError. The
    dedup marker and the fail-open principle apply identically to every adapter.
    """

    def get_pr_context(self) -> PRContext:
        """repo, PR id, title, target/source branch, is_draft, head_sha."""
        raise NotImplementedError

    def get_diff(self) -> str:
        """Raw unified diff (right side = new). Owns host-specific ref normalization
        (refs/heads/main → main) and the git invocation. core/diff.py parses it."""
        raise NotImplementedError

    def existing_findings(self) -> List[Tuple[str, str]]:
        """The Crucible inline findings already on this PR, as (hash, ref) pairs.
        `hash` comes from the hidden <!-- crucible:{hash} --> marker; `ref` is an
        adapter-specific handle passed back to delete_inline(). Used for de-dup AND
        for resolving (deleting) findings that are no longer present."""
        raise NotImplementedError

    def existing_finding_hashes(self) -> Set[str]:
        """Convenience: just the hashes (derived from existing_findings)."""
        return {h for h, _ in self.existing_findings()}

    def post_inline(self, finding: Finding) -> None:
        """Post one comment anchored to finding.file:finding.line (right side)."""
        raise NotImplementedError

    def delete_inline(self, ref: str) -> None:
        """Delete a previously-posted inline comment by its ref (resolves a finding
        that is no longer present on re-review). Best-effort — caller tolerates failure."""
        raise NotImplementedError

    def upsert_summary(self, markdown: str) -> None:
        """Create OR edit-in-place the single Crucible summary comment."""
        raise NotImplementedError

    def set_status(self, state: str, note: str) -> None:
        """Surface pass/block. The pipeline exit code is the real gate (plan A4);
        this is the optional/cosmetic visible check."""
        raise NotImplementedError


def get_provider(name: str, *, pr_id=None, session=None, **kwargs) -> GitProvider:
    """Factory: provider string → adapter instance.

    Kept here so `core/` selects an adapter by name only. Adapters are imported
    lazily so Phase-0 (config-only) runs never need `requests`.
    """
    key = (name or "").strip().lower()
    if key == "azure":
        from providers.azure import AzureProvider

        return AzureProvider.from_env(pr_id=pr_id, session=session)
    if key == "github":
        from providers.github import GitHubProvider

        return GitHubProvider.from_env(pr_id=pr_id, session=session)
    raise ValueError(f"Unknown provider {name!r}; expected 'azure' or 'github'")
