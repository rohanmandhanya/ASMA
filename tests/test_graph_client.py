from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from asma.publish import graph_client


class _FakeResponse:
    """Minimal stand-in for requests.Response covering everything
    graph_client's own code touches: status_code, .json(), and .text
    (used in error messages)."""

    def __init__(self, status_code: int, body: dict) -> None:
        self.status_code = status_code
        self._body = body
        self.text = str(body)

    def json(self) -> dict:
        return self._body

    def raise_for_status(self) -> None:
        return None


def test_dry_run_never_makes_a_real_http_call(monkeypatch):
    """The core safety property of DRY_RUN: assert it, don't just eyeball
    the logs. Any call to requests.request under DRY_RUN is a bug."""
    monkeypatch.setattr(graph_client, "DRY_RUN", True)

    def _fail(*args, **kwargs):
        raise AssertionError("requests.request must never be called under DRY_RUN")

    import requests

    monkeypatch.setattr(requests, "request", _fail)

    container_id = graph_client.create_image_container("https://example.invalid/x.png", is_carousel_item=True)
    graph_client.poll_container_until_finished(container_id, is_video=False)
    carousel_id = graph_client.create_carousel_container([container_id], caption="c")
    graph_client.poll_container_until_finished(carousel_id, is_video=False)
    media_id = graph_client.publish_container(carousel_id)
    graph_client.list_comments(media_id)
    graph_client.reply_to_comment("c1", "nice!")
    graph_client.get_account_insights()
    graph_client.get_media_insights(media_id)
    graph_client.refresh_long_lived_token()
    # Reaching here without the monkeypatched requests.request firing is the assertion.


def test_dry_run_responses_are_structurally_valid(monkeypatch):
    monkeypatch.setattr(graph_client, "DRY_RUN", True)
    container_id = graph_client.create_image_container("https://example.invalid/x.png")
    assert isinstance(container_id, str) and container_id

    media_id = graph_client.publish_container(container_id)
    assert isinstance(media_id, str) and media_id

    comments = graph_client.list_comments(media_id)
    assert comments == []

    insights = graph_client.get_account_insights()
    assert "followers_count" in insights

    token, expires_in = graph_client.refresh_long_lived_token()
    assert isinstance(token, str) and isinstance(expires_in, int)


def test_live_request_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(graph_client, "DRY_RUN", False)

    response = _FakeResponse(400, {"error": {"code": 100, "message": "Invalid parameter"}})

    import requests

    monkeypatch.setattr(requests, "request", lambda *a, **k: response)

    with pytest.raises(graph_client.GraphAPIError):
        graph_client.create_image_container("https://example.invalid/x.png")


def test_request_does_not_retry_non_rate_limit_errors(monkeypatch):
    """Only Meta's specific app-level rate limit (code 4) is worth
    retrying -- any other error (bad request, safety block, expired
    token) should fail on the first attempt, not burn through retries
    for something a retry can't fix."""
    monkeypatch.setattr(graph_client, "DRY_RUN", False)
    call_count = 0

    def _fake_request(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return _FakeResponse(400, {"error": {"code": 100, "message": "Invalid parameter"}})

    import requests

    monkeypatch.setattr(requests, "request", _fake_request)

    with pytest.raises(graph_client.GraphAPIError):
        graph_client.create_image_container("https://example.invalid/x.png")

    assert call_count == 1


def test_request_retries_app_rate_limit_and_recovers(monkeypatch):
    """Meta's app-level rate limit (code 4, 'Application request limit
    reached') is often transient -- if no phantom post is found on the
    first error (checked FIRST, before any retry), a retry should get a
    clean response once the limit clears, rather than losing the run."""
    monkeypatch.setattr(graph_client, "DRY_RUN", False)
    monkeypatch.setattr(graph_client, "GRAPH_API_RATE_LIMIT_RETRY_DELAY_SECONDS", 0)
    monkeypatch.setattr(graph_client, "_PHANTOM_POST_RECONCILE_DELAY_SECONDS", 0)

    rate_limited = _FakeResponse(403, {"error": {"code": 4, "message": "Application request limit reached"}})
    success = _FakeResponse(200, {"id": "media123"})
    no_recent_post = _FakeResponse(200, {"data": []})
    publish_attempts = 0

    def _fake_request(method, url, **kwargs):
        nonlocal publish_attempts
        if "media_publish" in url:
            publish_attempts += 1
            return rate_limited if publish_attempts == 1 else success
        return no_recent_post  # reconciliation lookup finds nothing, forcing the retry

    import requests

    monkeypatch.setattr(requests, "request", _fake_request)

    media_id = graph_client.publish_container("container1")
    assert media_id == "media123"
    assert publish_attempts == 2


def test_request_raises_rate_limit_error_after_exhausting_retries(monkeypatch):
    monkeypatch.setattr(graph_client, "DRY_RUN", False)
    monkeypatch.setattr(graph_client, "GRAPH_API_RATE_LIMIT_RETRY_ATTEMPTS", 2)
    monkeypatch.setattr(graph_client, "GRAPH_API_RATE_LIMIT_RETRY_DELAY_SECONDS", 0)
    monkeypatch.setattr(graph_client, "_PHANTOM_POST_RECONCILE_DELAY_SECONDS", 0)

    rate_limited = _FakeResponse(403, {"error": {"code": 4, "message": "Application request limit reached"}})
    call_count = 0

    def _fake_request(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return rate_limited

    import requests

    monkeypatch.setattr(requests, "request", _fake_request)

    with pytest.raises(graph_client.GraphAPIRateLimitError):
        graph_client.publish_container("container1")

    # 2 media_publish attempts, each followed by its own reconciliation
    # lookup (which also gets the same fake 403 here, so it correctly
    # finds nothing to recover each time) = 4 calls total.
    assert call_count == 4


def test_publish_container_recovers_phantom_success(monkeypatch):
    """Meta has repeatedly been observed to actually publish successfully
    server-side while still returning the app-rate-limit error on the
    response -- this must recover the real media id from the account's
    recent media on the very FIRST error, without ever retrying (a retry
    would blindly re-submit a container that's already been consumed)."""
    monkeypatch.setattr(graph_client, "DRY_RUN", False)
    monkeypatch.setattr(graph_client, "GRAPH_API_RATE_LIMIT_RETRY_ATTEMPTS", 2)
    monkeypatch.setattr(graph_client, "GRAPH_API_RATE_LIMIT_RETRY_DELAY_SECONDS", 0)
    monkeypatch.setattr(graph_client, "_PHANTOM_POST_RECONCILE_DELAY_SECONDS", 0)

    rate_limited = _FakeResponse(403, {"error": {"code": 4, "message": "Application request limit reached"}})
    recent_media = _FakeResponse(
        200, {"data": [{"id": "recovered_media_id", "timestamp": datetime.now(timezone.utc).isoformat()}]}
    )
    publish_attempts = 0

    def _fake_request(method, url, **kwargs):
        nonlocal publish_attempts
        if "media_publish" in url:
            publish_attempts += 1
            return rate_limited
        return recent_media

    import requests

    monkeypatch.setattr(requests, "request", _fake_request)

    media_id = graph_client.publish_container("container1")
    assert media_id == "recovered_media_id"
    assert publish_attempts == 1  # recovered on the first error, no retry attempted


def test_publish_container_recovers_from_non_rate_limit_error_too(monkeypatch):
    """The reconciliation net is deliberately not limited to the rate-limit
    error type -- media_publish's response has been seen lying about the
    outcome under a completely different Meta error too (code -1, generic
    'Fatal'/internal error), still after the post actually published. The
    tight recency window in _find_recently_published_media is what keeps
    this safe, not which error code triggered it."""
    monkeypatch.setattr(graph_client, "DRY_RUN", False)
    monkeypatch.setattr(graph_client, "_PHANTOM_POST_RECONCILE_DELAY_SECONDS", 0)

    generic_error = _FakeResponse(
        400, {"error": {"code": -1, "message": "Fatal", "error_subcode": 2207085, "error_user_title": "Generic Internal Error"}}
    )
    recent_media = _FakeResponse(
        200, {"data": [{"id": "recovered_media_id", "timestamp": datetime.now(timezone.utc).isoformat()}]}
    )

    def _fake_request(method, url, **kwargs):
        return generic_error if "media_publish" in url else recent_media

    import requests

    monkeypatch.setattr(requests, "request", _fake_request)

    media_id = graph_client.publish_container("container1")
    assert media_id == "recovered_media_id"


def test_publish_container_raises_when_no_recent_post_found(monkeypatch):
    """If reconciliation finds nothing recently published, this is a
    genuine failure -- must not silently swallow it."""
    monkeypatch.setattr(graph_client, "DRY_RUN", False)
    monkeypatch.setattr(graph_client, "GRAPH_API_RATE_LIMIT_RETRY_ATTEMPTS", 2)
    monkeypatch.setattr(graph_client, "GRAPH_API_RATE_LIMIT_RETRY_DELAY_SECONDS", 0)
    monkeypatch.setattr(graph_client, "_PHANTOM_POST_RECONCILE_DELAY_SECONDS", 0)

    rate_limited = _FakeResponse(403, {"error": {"code": 4, "message": "Application request limit reached"}})
    old_media = _FakeResponse(
        200, {"data": [{"id": "old_media_id", "timestamp": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()}]}
    )

    def _fake_request(method, url, **kwargs):
        return rate_limited if "media_publish" in url else old_media

    import requests

    monkeypatch.setattr(requests, "request", _fake_request)

    with pytest.raises(graph_client.GraphAPIRateLimitError):
        graph_client.publish_container("container1")


def test_poll_container_raises_when_never_finished(monkeypatch):
    monkeypatch.setattr(graph_client, "DRY_RUN", False)
    monkeypatch.setattr(graph_client, "CONTAINER_POLL_TIMEOUT_IMAGE_SECONDS", 0.05)
    monkeypatch.setattr(graph_client, "CONTAINER_POLL_INTERVAL_SECONDS", 0.01)

    class _FakeInProgressResponse:
        status_code = 200

        def json(self):
            return {"status_code": "IN_PROGRESS"}

        def raise_for_status(self):
            return None

    import requests

    monkeypatch.setattr(requests, "request", lambda *a, **k: _FakeInProgressResponse())

    with pytest.raises(graph_client.ContainerNotReadyError):
        graph_client.poll_container_until_finished("c1", is_video=False)


def test_poll_container_raises_on_error_status(monkeypatch):
    monkeypatch.setattr(graph_client, "DRY_RUN", False)

    class _FakeErrorStatusResponse:
        status_code = 200

        def json(self):
            return {"status_code": "ERROR"}

        def raise_for_status(self):
            return None

    import requests

    monkeypatch.setattr(requests, "request", lambda *a, **k: _FakeErrorStatusResponse())

    with pytest.raises(graph_client.GraphAPIError):
        graph_client.poll_container_until_finished("c1", is_video=False)


def test_poll_container_error_includes_meta_status_detail(monkeypatch):
    """A bare 'ERROR' status_code never says why — the human-readable
    `status` field is what actually lets a failure (e.g. media Meta
    couldn't fetch vs. an unsupported format) get diagnosed after the
    fact, instead of a dead-end 'entered ERROR state'."""
    monkeypatch.setattr(graph_client, "DRY_RUN", False)

    class _FakeErrorStatusResponse:
        status_code = 200

        def json(self):
            return {"status_code": "ERROR", "status": "Media could not be fetched from the provided URL."}

        def raise_for_status(self):
            return None

    import requests

    monkeypatch.setattr(requests, "request", lambda *a, **k: _FakeErrorStatusResponse())

    with pytest.raises(graph_client.GraphAPIError, match="Media could not be fetched"):
        graph_client.poll_container_until_finished("c1", is_video=False)
