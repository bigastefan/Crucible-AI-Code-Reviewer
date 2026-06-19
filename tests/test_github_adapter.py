"""Phase 5 — GitHub adapter request-building, offline via a fake HTTP session.
Live posting is the manual Gate-B acceptance on the private test repo."""
import json
from types import SimpleNamespace

import pytest

from core import dedup
from core.models import Category, Finding, Severity
from providers.github import GitHubProvider


class FakeResponse:
    def __init__(self, status=200, payload=None, text=None):
        self.status_code = status
        self._payload = payload
        self.text = text if text is not None else (json.dumps(payload) if payload is not None else "")

    def json(self):
        return self._payload


class FakeSession:
    """Routes GET list endpoints to canned payloads; records every call."""

    def __init__(self, pull_comments=None, issue_comments=None, pr_payload=None):
        self.calls = []
        self.pull_comments = pull_comments or []
        self.issue_comments = issue_comments or []
        self.pr_payload = pr_payload or {}

    def request(self, method, url, headers=None, json=None, params=None):
        self.calls.append(SimpleNamespace(method=method, url=url, json=json, params=params, headers=headers))
        if method == "GET" and "/pulls/" in url and url.endswith("/comments"):
            return self._page(self.pull_comments, params)
        if method == "GET" and "/issues/" in url and url.endswith("/comments"):
            return self._page(self.issue_comments, params)
        if method == "GET" and "/pulls/" in url:
            return FakeResponse(200, self.pr_payload)
        return FakeResponse(200, None, text="")

    @staticmethod
    def _page(items, params):
        page = (params or {}).get("page", 1)
        return FakeResponse(200, items if page == 1 else [])


def make(session, **kw):
    params = dict(
        owner="bigastefan", repo="test", pr_number=7, token="tok",
        session=session, base_ref="main", head_sha="deadbeef", ctx_known=True,
    )
    params.update(kw)
    return GitHubProvider(**params)


def _finding():
    return Finding("src/calc.ts", 12, Severity.HIGH, Category.BUG, "Null deref", "x may be None", "if (x) {}")


def test_existing_finding_hashes_from_review_comments():
    h = dedup.finding_hash(_finding())
    comments = [
        {"id": 1, "body": f"old finding <!-- crucible:{h} -->"},
        {"id": 2, "body": "a human review comment"},
    ]
    prov = make(FakeSession(pull_comments=comments))
    assert prov.existing_finding_hashes() == {h}


def test_post_inline_payload_side_right_and_anchor():
    sess = FakeSession()
    prov = make(sess)
    prov.post_inline(_finding())
    call = sess.calls[-1]
    assert call.method == "POST" and call.url.endswith("/repos/bigastefan/test/pulls/7/comments")
    assert call.json["path"] == "src/calc.ts"  # repo-relative, NO leading slash (unlike Azure)
    assert call.json["line"] == 12 and call.json["side"] == "RIGHT"
    assert call.json["commit_id"] == "deadbeef"  # PR head sha, not the merge commit
    assert dedup.extract_finding_hashes(call.json["body"]) == {dedup.finding_hash(_finding())}


def test_auth_header_uses_bearer_token():
    sess = FakeSession()
    make(sess).post_inline(_finding())
    assert sess.calls[-1].headers["Authorization"] == "Bearer tok"


def test_upsert_summary_posts_issue_comment_when_absent():
    sess = FakeSession(issue_comments=[])
    make(sess).upsert_summary("SUMMARY " + dedup.SUMMARY_MARKER)
    post = [c for c in sess.calls if c.method == "POST"][-1]
    assert post.url.endswith("/repos/bigastefan/test/issues/7/comments")
    assert post.json["body"].startswith("SUMMARY")


def test_upsert_summary_patches_existing_issue_comment():
    issue_comments = [{"id": 99, "body": "old summary " + dedup.SUMMARY_MARKER}]
    sess = FakeSession(issue_comments=issue_comments)
    make(sess).upsert_summary("new summary " + dedup.SUMMARY_MARKER)
    patch = [c for c in sess.calls if c.method == "PATCH"][-1]
    assert patch.url.endswith("/repos/bigastefan/test/issues/comments/99")
    assert patch.json["body"].startswith("new summary")


def test_set_status_maps_state_and_swallows_errors():
    class Err(FakeSession):
        def request(self, method, url, headers=None, json=None, params=None):
            self.calls.append(SimpleNamespace(method=method, url=url, json=json))
            return FakeResponse(403, None, text="Forbidden")

    sess = Err()
    make(sess).set_status("succeeded", "ok")  # must not raise
    call = [c for c in sess.calls if "/statuses/" in c.url][-1]
    assert call.json["state"] == "success"  # "succeeded" → GitHub "success"


def test_posting_error_raises_for_failopen_wrapper():
    class Err(FakeSession):
        def request(self, method, url, headers=None, json=None, params=None):
            return FakeResponse(401, None, text="Bad credentials")

    with pytest.raises(RuntimeError, match="401"):
        make(Err()).post_inline(_finding())


def test_get_pr_context_falls_back_to_rest_when_unknown():
    pr = {
        "title": "T", "draft": False,
        "head": {"sha": "abc", "ref": "feature"},
        "base": {"ref": "main"},
    }
    prov = make(FakeSession(pr_payload=pr), head_sha="", base_ref="", ctx_known=False)
    ctx = prov.get_pr_context()
    assert ctx.head_sha == "abc" and ctx.target_branch == "main" and ctx.source_branch == "feature"
