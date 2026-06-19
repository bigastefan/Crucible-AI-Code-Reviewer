"""Azure DevOps adapter (Agent Spec §8.1). The only Azure-specific code.

Implements GitProvider via the Azure DevOps REST API (api-version=7.1). The HTTP
session is injectable so the request-building is unit-testable offline; live posting
is the manual Gate-A acceptance on an Azure test PR.

Auth (§8.1):
  - In a pipeline: Bearer $(System.AccessToken) (build service identity). Requires the
    Project Build Service to have "Contribute to pull requests" or posting silently fails.
  - Off-pipeline (CLI): AZURE_DEVOPS_PAT via Basic auth.
"""
from __future__ import annotations

import base64
import logging
import os
import subprocess
from typing import Optional, Set
from urllib.parse import quote

from core import dedup
from core.models import Finding, PRContext
from providers.base import GitProvider

log = logging.getLogger("crucible.azure")
API = "7.1"


class AzureConfigError(RuntimeError):
    pass


class AzureProvider(GitProvider):
    def __init__(
        self,
        *,
        collection_url: str,
        project: str,
        repository: str,
        pr_id: int,
        auth_header: str,
        session=None,
        target_branch: str = "",
    ):
        if not collection_url.endswith("/"):
            collection_url += "/"
        self.collection_url = collection_url
        self.project = project
        self.repository = repository
        self.pr_id = pr_id
        self.auth_header = auth_header
        self._target_branch = target_branch
        if session is None:
            import requests  # lazy: only needed for a live call

            session = requests.Session()
        self.session = session
        self._threads_cache = None
        self._ctx: Optional[PRContext] = None

    # ----------------------------------------------------------------- env wiring
    @classmethod
    def from_env(cls, pr_id: Optional[int] = None, session=None) -> "AzureProvider":
        if os.environ.get("SYSTEM_ACCESSTOKEN"):  # running in a pipeline
            token = os.environ["SYSTEM_ACCESSTOKEN"]
            auth = f"Bearer {token}"
            collection = os.environ.get("SYSTEM_TEAMFOUNDATIONCOLLECTIONURI", "")
            project = os.environ.get("SYSTEM_TEAMPROJECT", "")
            repo = os.environ.get("BUILD_REPOSITORY_ID") or os.environ.get("BUILD_REPOSITORY_NAME", "")
            pr = pr_id or _int_env("SYSTEM_PULLREQUEST_PULLREQUESTID")
            target = os.environ.get("SYSTEM_PULLREQUEST_TARGETBRANCH", "")
        else:  # off-pipeline CLI
            pat = os.environ.get("AZURE_DEVOPS_PAT")
            if not pat:
                raise AzureConfigError(
                    "No Azure credentials: set SYSTEM_ACCESSTOKEN (pipeline) or AZURE_DEVOPS_PAT (CLI)."
                )
            auth = "Basic " + base64.b64encode(f":{pat}".encode()).decode()
            collection = os.environ.get("AZURE_DEVOPS_ORG_URL", "")
            project = os.environ.get("AZURE_DEVOPS_PROJECT", "")
            repo = os.environ.get("AZURE_DEVOPS_REPO", "")
            pr = pr_id
            target = os.environ.get("AZURE_DEVOPS_TARGET_BRANCH", "")

        missing = [n for n, v in [("collection", collection), ("project", project), ("repo", repo), ("pr", pr)] if not v]
        if missing:
            raise AzureConfigError(f"Azure config incomplete; missing: {missing}")
        return cls(
            collection_url=collection, project=project, repository=repo,
            pr_id=int(pr), auth_header=auth, session=session, target_branch=target,
        )

    # ----------------------------------------------------------------- REST plumbing
    def _base(self) -> str:
        proj = quote(self.project, safe="")
        repo = quote(str(self.repository), safe="")
        return f"{self.collection_url}{proj}/_apis/git/repositories/{repo}/pullRequests/{self.pr_id}"

    def _request(self, method: str, url: str, json=None):
        headers = {"Authorization": self.auth_header, "Content-Type": "application/json"}
        resp = self.session.request(method, url, headers=headers, json=json)
        if resp.status_code >= 400:
            raise RuntimeError(f"Azure REST {method} {url} → {resp.status_code}: {resp.text[:300]}")
        if resp.text:
            return resp.json()
        return None

    def _url(self, suffix: str) -> str:
        sep = "&" if "?" in suffix else "?"
        return f"{self._base()}{suffix}{sep}api-version={API}"

    def _get_threads(self):
        if self._threads_cache is None:
            data = self._request("GET", self._url("/threads")) or {}
            self._threads_cache = data.get("value", [])
        return self._threads_cache

    # ----------------------------------------------------------------- GitProvider
    def get_pr_context(self) -> PRContext:
        if self._ctx is None:
            pr = self._request("GET", self._url("")) or {}
            target = pr.get("targetRefName") or self._target_branch
            self._target_branch = target
            self._ctx = PRContext(
                repo=str(self.repository),
                pr_id=self.pr_id,
                title=pr.get("title", ""),
                target_branch=_strip_ref(target),
                source_branch=_strip_ref(pr.get("sourceRefName", "")),
                is_draft=bool(pr.get("isDraft", False)),
                head_sha=(pr.get("lastMergeSourceCommit") or {}).get("commitId", ""),
            )
        return self._ctx

    def get_diff(self) -> str:
        """Local `git diff origin/<target>...HEAD` (pipeline checks out with fetchDepth:0)."""
        target = _strip_ref(self._target_branch) or _strip_ref(self.get_pr_context().target_branch)
        if not target:
            raise RuntimeError("Azure: no target branch resolved for diff.")
        result = subprocess.run(
            ["git", "diff", f"origin/{target}...HEAD"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git diff failed: {result.stderr.strip()}")
        return result.stdout

    def existing_finding_hashes(self) -> Set[str]:
        hashes: Set[str] = set()
        for thread in self._get_threads():
            for comment in thread.get("comments", []) or []:
                hashes |= dedup.extract_finding_hashes(comment.get("content", ""))
        return hashes

    def post_inline(self, finding: Finding) -> None:
        body = {
            "comments": [{"parentCommentId": 0, "commentType": 1, "content": dedup.render_inline_body(finding)}],
            "status": 1,  # active
            "threadContext": {
                "filePath": _azure_path(finding.file),
                "rightFileStart": {"line": finding.line, "offset": 1},
                "rightFileEnd": {"line": finding.line, "offset": 1},
            },
        }
        self._request("POST", self._url("/threads"), json=body)

    def upsert_summary(self, markdown: str) -> None:
        existing = self._find_summary_thread()
        if existing is not None:
            thread_id, comment_id = existing
            self._request(
                "PATCH",
                self._url(f"/threads/{thread_id}/comments/{comment_id}"),
                json={"content": markdown},
            )
        else:
            self._request(
                "POST",
                self._url("/threads"),
                json={"comments": [{"parentCommentId": 0, "commentType": 1, "content": markdown}], "status": 1},
            )

    def set_status(self, state: str, note: str) -> None:
        """Optional/cosmetic visible check (plan A4: the pipeline exit code is the real gate)."""
        try:
            self._request(
                "POST",
                self._url("/statuses"),
                json={
                    "state": state,
                    "description": note[:300],
                    "context": {"name": "crucible", "genre": "crucible"},
                },
            )
        except Exception as e:  # never let the cosmetic status break the run
            log.warning("Azure set_status failed (non-fatal): %s", e)

    # ----------------------------------------------------------------- helpers
    def _find_summary_thread(self):
        for thread in self._get_threads():
            for comment in thread.get("comments", []) or []:
                if dedup.text_has_summary_marker(comment.get("content", "")):
                    return thread.get("id"), comment.get("id")
        return None


def _strip_ref(ref: str) -> str:
    return (ref or "").replace("refs/heads/", "")


def _azure_path(path: str) -> str:
    p = path.replace("\\", "/")
    return p if p.startswith("/") else "/" + p


def _int_env(name: str) -> Optional[int]:
    v = os.environ.get(name)
    return int(v) if v and v.isdigit() else None
