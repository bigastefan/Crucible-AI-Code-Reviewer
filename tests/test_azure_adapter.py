"""Phase 3 — Azure adapter request-building, offline via a fake HTTP session.
Live posting is the manual Gate-A acceptance on an Azure test PR."""
import json
from types import SimpleNamespace

import pytest

from core import dedup
from core.models import Category, Finding, Severity
from providers.azure import AzureProvider


class FakeResponse:
    def __init__(self, status=200, payload=None, text=None):
        self.status_code = status
        self._payload = payload
        self.text = text if text is not None else (json.dumps(payload) if payload is not None else "")

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, threads_payload=None, pr_payload=None, status_code_for_status=200):
        self.calls = []
        self.threads_payload = threads_payload if threads_payload is not None else {"value": []}
        self.pr_payload = pr_payload or {}
        self.status_code_for_status = status_code_for_status

    def request(self, method, url, headers=None, json=None):
        self.calls.append(SimpleNamespace(method=method, url=url, json=json, headers=headers))
        if method == "GET" and "/threads" in url:
            return FakeResponse(200, self.threads_payload)
        if method == "GET":
            return FakeResponse(200, self.pr_payload)
        if "/statuses" in url:
            return FakeResponse(self.status_code_for_status, {}, text="status-resp")
        return FakeResponse(200, None, text="")


def make(session, **kw):
    params = dict(
        collection_url="https://dev.azure.com/org/",
        project="My Project",
        repository="repo-id",
        pr_id=42,
        auth_header="Bearer tok",
        session=session,
        target_branch="refs/heads/main",
    )
    params.update(kw)
    return AzureProvider(**params)


def _finding():
    return Finding("src/calc.py", 12, Severity.HIGH, Category.BUG, "Null deref", "x may be None", "if x:")


def test_existing_finding_hashes_extracted_from_threads():
    h = dedup.finding_hash(_finding())
    threads = {"value": [
        {"id": 1, "comments": [{"id": 1, "content": f"body <!-- crucible:{h} -->"}]},
        {"id": 2, "comments": [{"id": 1, "content": "a human comment, no marker"}]},
    ]}
    prov = make(FakeSession(threads_payload=threads))
    assert prov.existing_finding_hashes() == {h}


def test_post_inline_payload_and_anchor():
    sess = FakeSession()
    prov = make(sess)
    prov.post_inline(_finding())
    call = sess.calls[-1]
    assert call.method == "POST" and "/threads?" in call.url
    assert "api-version=7.1" in call.url
    assert "My%20Project" in call.url  # project is url-encoded
    tc = call.json["threadContext"]
    assert tc["filePath"] == "/src/calc.py"  # leading slash, forward slashes
    assert tc["rightFileStart"]["line"] == 12 and tc["rightFileEnd"]["line"] == 12
    content = call.json["comments"][0]["content"]
    assert dedup.extract_finding_hashes(content) == {dedup.finding_hash(_finding())}


def test_upsert_summary_posts_when_absent():
    sess = FakeSession(threads_payload={"value": []})
    prov = make(sess)
    prov.upsert_summary("SUMMARY BODY " + dedup.SUMMARY_MARKER)
    post = [c for c in sess.calls if c.method == "POST"][-1]
    assert "/threads?" in post.url
    assert "threadContext" not in post.json  # general PR comment, not anchored
    assert post.json["comments"][0]["content"].startswith("SUMMARY BODY")


def test_upsert_summary_patches_when_present():
    threads = {"value": [
        {"id": 5, "comments": [{"id": 7, "content": "old summary " + dedup.SUMMARY_MARKER}]},
    ]}
    sess = FakeSession(threads_payload=threads)
    prov = make(sess)
    prov.upsert_summary("new summary " + dedup.SUMMARY_MARKER)
    patch = [c for c in sess.calls if c.method == "PATCH"][-1]
    assert "/threads/5/comments/7?" in patch.url
    assert patch.json["content"].startswith("new summary")


def test_set_status_does_not_raise_on_error():
    sess = FakeSession(status_code_for_status=400)
    prov = make(sess)
    prov.set_status("succeeded", "ok")  # must swallow the 400 (cosmetic only)
    assert [c for c in sess.calls if "/statuses" in c.url]


def test_get_pr_context_reads_pr_json():
    pr = {
        "title": "My PR", "isDraft": True,
        "sourceRefName": "refs/heads/feature", "targetRefName": "refs/heads/main",
        "lastMergeSourceCommit": {"commitId": "abc123"},
    }
    prov = make(FakeSession(pr_payload=pr))
    ctx = prov.get_pr_context()
    assert ctx.title == "My PR" and ctx.is_draft is True
    assert ctx.source_branch == "feature" and ctx.target_branch == "main"
    assert ctx.head_sha == "abc123"


def test_rest_error_raises_for_posting_paths():
    class Err(FakeSession):
        def request(self, method, url, headers=None, json=None):
            return FakeResponse(403, None, text="Forbidden")

    prov = make(Err())
    with pytest.raises(RuntimeError, match="403"):
        prov.post_inline(_finding())
