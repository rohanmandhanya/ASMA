from __future__ import annotations

import pytest

from asma.publish import graph_client


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

    class _FakeErrorResponse:
        status_code = 400
        text = '{"error": {"message": "Invalid parameter"}}'

    import requests

    monkeypatch.setattr(requests, "request", lambda *a, **k: _FakeErrorResponse())

    with pytest.raises(graph_client.GraphAPIError):
        graph_client.create_image_container("https://example.invalid/x.png")


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
