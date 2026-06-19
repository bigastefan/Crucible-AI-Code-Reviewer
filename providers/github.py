"""GitHub adapter (Agent Spec §8.2). The only GitHub-specific code.

Second adapter behind the SAME GitProvider interface — reuses all of `core/`
(diff parser, dedup marker, poster, reviewer) unchanged (X-04). The HTTP session is
injectable so request-building is unit-testable offline.

Secret safety (workflow enforces the rest): this code never reads/prints the LLM key,
and never executes any code from the PR — it only `git diff`s and posts via REST.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from typing import List, Optional, Set

from core import dedup
from core.models import Finding, PRContext
from providers.base import GitProvider

log = logging.getLogger("crucible.github")
API_VERSION = "2022-11-28"


class GitHubConfigError(RuntimeError):
    pass


class GitHubProvider(GitProvider):
    def __init__(
        self,
        *,
        owner: str,
        repo: str,
        pr_number: int,
        token: str,
        session=None,
        api_url: str = "https://api.github.com",
        base_ref: str = "",
        head_sha: str = "",
        title: str = "",
        source_branch: str = "",
        is_draft: bool = False,
        ctx_known: bool = False,
    ):
        self.owner = owner
        self.repo = repo
        self.pr_number = int(pr_number)
        self.token = token
        self.api_url = api_url.rstrip("/")
        self._base_ref = base_ref
        self._head_sha = head_sha
        self._title = title
        self._source_branch = source_branch
        self._is_draft = is_draft
        self._ctx_known = ctx_known
        self._ctx: Optional[PRContext] = None
        if session is None:
            import requests  # lazy: only needed for a live call

            session = requests.Session()
        self.session = session

    # ----------------------------------------------------------------- env wiring
    @classmethod
    def from_env(cls, pr_id: Optional[int] = None, session=None) -> "GitHubProvider":
        token = os.environ.get("GITHUB_TOKEN", "")
        repo_full = os.environ.get("GITHUB_REPOSITORY", "")
        if "/" not in repo_full:
            raise GitHubConfigError("GITHUB_REPOSITORY missing/invalid (expected 'owner/repo').")
        owner, repo = repo_full.split("/", 1)

        event = _load_event()
        pr = event.get("pull_request") or {}
        number = pr_id or pr.get("number") or _int_env("GITHUB_PR_NUMBER")
        if not number:
            raise GitHubConfigError("No PR number (set --pr, or run on a pull_request event).")

        base_ref = os.environ.get("GITHUB_BASE_REF", "") or (pr.get("base") or {}).get("ref", "")
        head = pr.get("head") or {}
        return cls(
            owner=owner, repo=repo, pr_number=int(number), token=token, session=session,
            base_ref=base_ref, head_sha=head.get("sha", ""), title=pr.get("title", ""),
            source_branch=head.get("ref", ""), is_draft=bool(pr.get("draft", False)),
            ctx_known=bool(pr),
        )

    # ----------------------------------------------------------------- REST plumbing
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
        }

    def _request(self, method: str, path: str, json_body=None, params=None):
        url = f"{self.api_url}{path}"
        resp = self.session.request(method, url, headers=self._headers(), json=json_body, params=params)
        if resp.status_code >= 400:
            raise RuntimeError(f"GitHub REST {method} {path} → {resp.status_code}: {resp.text[:300]}")
        return resp.json() if resp.text else None

    def _paginated_get(self, path: str) -> List[dict]:
        results: List[dict] = []
        page = 1
        while True:
            batch = self._request("GET", path, params={"per_page": 100, "page": page})
            if not isinstance(batch, list) or not batch:
                break
            results.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return results

    def _repo_path(self, suffix: str) -> str:
        return f"/repos/{self.owner}/{self.repo}{suffix}"

    # ----------------------------------------------------------------- GitProvider
    def get_pr_context(self) -> PRContext:
        if self._ctx is None:
            if not self._ctx_known or not self._head_sha or not self._base_ref:
                pr = self._request("GET", self._repo_path(f"/pulls/{self.pr_number}")) or {}
                self._head_sha = self._head_sha or (pr.get("head") or {}).get("sha", "")
                self._base_ref = self._base_ref or (pr.get("base") or {}).get("ref", "")
                self._source_branch = self._source_branch or (pr.get("head") or {}).get("ref", "")
                self._title = self._title or pr.get("title", "")
                self._is_draft = self._is_draft or bool(pr.get("draft", False))
            self._ctx = PRContext(
                repo=f"{self.owner}/{self.repo}", pr_id=self.pr_number, title=self._title,
                target_branch=self._base_ref, source_branch=self._source_branch,
                is_draft=self._is_draft, head_sha=self._head_sha,
            )
        return self._ctx

    def get_diff(self) -> str:
        """Local `git diff origin/<base>...HEAD` (workflow checks out fetch-depth:0)."""
        target = self._base_ref or self.get_pr_context().target_branch
        if not target:
            raise RuntimeError("GitHub: no base ref resolved for diff.")
        result = subprocess.run(
            ["git", "diff", f"origin/{target}...HEAD"], capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"git diff failed: {result.stderr.strip()}")
        return result.stdout

    def existing_finding_hashes(self) -> Set[str]:
        hashes: Set[str] = set()
        for c in self._paginated_get(self._repo_path(f"/pulls/{self.pr_number}/comments")):
            hashes |= dedup.extract_finding_hashes(c.get("body", ""))
        return hashes

    def post_inline(self, finding: Finding) -> None:
        sha = self._head_sha or self.get_pr_context().head_sha
        body = {
            "body": dedup.render_inline_body(finding),
            "commit_id": sha,
            "path": finding.file.replace("\\", "/"),  # repo-relative, no leading slash
            "line": finding.line,
            "side": "RIGHT",
        }
        self._request("POST", self._repo_path(f"/pulls/{self.pr_number}/comments"), json_body=body)

    def upsert_summary(self, markdown: str) -> None:
        existing_id = self._find_summary_comment_id()
        if existing_id is not None:
            self._request("PATCH", self._repo_path(f"/issues/comments/{existing_id}"), json_body={"body": markdown})
        else:
            self._request("POST", self._repo_path(f"/issues/{self.pr_number}/comments"), json_body={"body": markdown})

    def set_status(self, state: str, note: str) -> None:
        """Optional/cosmetic commit status (plan A4: the workflow exit code is the gate)."""
        gh_state = {"succeeded": "success", "failed": "failure"}.get(state, state)
        try:
            sha = self._head_sha or self.get_pr_context().head_sha
            if not sha:
                return
            self._request(
                "POST", self._repo_path(f"/statuses/{sha}"),
                json_body={"state": gh_state, "context": "crucible", "description": note[:140]},
            )
        except Exception as e:  # never let the cosmetic status break the run
            log.warning("GitHub set_status failed (non-fatal): %s", e)

    # ----------------------------------------------------------------- helpers
    def _find_summary_comment_id(self):
        for c in self._paginated_get(self._repo_path(f"/issues/{self.pr_number}/comments")):
            if dedup.text_has_summary_marker(c.get("body", "")):
                return c.get("id")
        return None


def _load_event() -> dict:
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:  # pragma: no cover
        return {}


def _int_env(name: str) -> Optional[int]:
    v = os.environ.get(name)
    return int(v) if v and v.isdigit() else None
