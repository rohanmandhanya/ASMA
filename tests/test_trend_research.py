from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
from google.genai import errors

from asma.config import GEMINI_HTTP_TIMEOUT_MS, GEMINI_RETRY_ATTEMPTS
from asma.content import trend_research


def _fake_client(*, finish_reason: str = "STOP", text: str = "some trend summary") -> MagicMock:
    client = MagicMock()
    candidate = SimpleNamespace(finish_reason=finish_reason)
    client.models.generate_content.return_value = SimpleNamespace(candidates=[candidate], text=text)
    return client


def _rate_limit_error() -> errors.ClientError:
    response_json = {
        "error": {
            "code": 429,
            "message": "You exceeded your current quota, please check your plan and billing details.",
            "status": "RESOURCE_EXHAUSTED",
        }
    }
    return errors.ClientError(429, response_json)


def test_research_trending_history_topics_success(monkeypatch):
    monkeypatch.setattr(trend_research, "DRY_RUN", False)
    client = _fake_client(text="Mansa Musa content is trending this week.")
    summary = trend_research.research_trending_history_topics(client)
    assert summary == "Mansa Musa content is trending this week."


def test_research_trending_history_topics_sets_bounded_timeout_and_retry_options(monkeypatch):
    monkeypatch.setattr(trend_research, "DRY_RUN", False)
    client = _fake_client()
    trend_research.research_trending_history_topics(client)
    used_config = client.models.generate_content.call_args.kwargs["config"]
    assert used_config.http_options.timeout == GEMINI_HTTP_TIMEOUT_MS
    assert used_config.http_options.retry_options.attempts == GEMINI_RETRY_ATTEMPTS


def test_research_trending_history_topics_falls_back_on_connection_reset(monkeypatch):
    """A mid-response connection reset gets the same graceful-fallback
    treatment as a 429/refusal — never worth taking down the whole run
    over a nice-to-have weekly signal."""
    monkeypatch.setattr(trend_research, "DRY_RUN", False)
    client = MagicMock()
    client.models.generate_content.side_effect = httpx.RemoteProtocolError(
        "Server disconnected without sending a response"
    )

    summary = trend_research.research_trending_history_topics(client)

    assert summary == trend_research._FALLBACK_SUMMARY


def test_research_trending_history_topics_falls_back_on_429(monkeypatch):
    """Google Search grounding can be quota-exhausted (429 RESOURCE_EXHAUSTED)
    even when plain generate_content calls on the same model/key work fine —
    this must fall back gracefully, never take down the whole
    scheduled-content run over a nice-to-have weekly signal."""
    monkeypatch.setattr(trend_research, "DRY_RUN", False)
    client = MagicMock()
    client.models.generate_content.side_effect = _rate_limit_error()

    summary = trend_research.research_trending_history_topics(client)

    assert summary == trend_research._FALLBACK_SUMMARY


def test_research_trending_history_topics_falls_back_on_refusal(monkeypatch):
    monkeypatch.setattr(trend_research, "DRY_RUN", False)
    client = _fake_client(finish_reason="SAFETY")
    summary = trend_research.research_trending_history_topics(client)
    assert summary == trend_research._FALLBACK_SUMMARY


def test_research_trending_history_topics_skips_real_call_under_dry_run(monkeypatch):
    monkeypatch.setattr(trend_research, "DRY_RUN", True)
    client = MagicMock()
    summary = trend_research.research_trending_history_topics(client)
    client.models.generate_content.assert_not_called()
    assert trend_research._FALLBACK_SUMMARY in summary
