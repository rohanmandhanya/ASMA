"""Integration coverage for the CONTENT_MODEL fallback cascade
(config.CONTENT_MODEL_FALLBACKS) — proves a 503 on the primary model
doesn't just recover in isolation (see test_generator.py's unit tests on
generator._generate() directly) but produces a real, valid published
post through the full manual_post_once orchestration: topic selection,
guardrails, real Playwright rendering, the DRY_RUN graph_client stub —
exactly like test_integration_smoke.py, except the primary model is
overloaded and the fallback is what actually carries the run.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from google.genai import errors

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from asma.config import CONTENT_MODEL, CONTENT_MODEL_FALLBACKS  # noqa: E402
from asma.models import ContentFormat  # noqa: E402


def _server_overloaded_error() -> errors.ServerError:
    response_json = {
        "error": {"code": 503, "message": "This model is currently experiencing high demand.", "status": "UNAVAILABLE"}
    }
    return errors.ServerError(503, response_json)


def _client_overloaded_once_then_success(parsed) -> MagicMock:
    """First call (the primary CONTENT_MODEL) raises 503; the next call
    succeeds — proves the cascade recovers on the very next fallback
    rather than requiring every candidate to be exhausted."""
    client = MagicMock()
    candidate = SimpleNamespace(finish_reason="STOP")
    success = SimpleNamespace(candidates=[candidate], prompt_feedback=None, parsed=parsed)
    client.models.generate_content.side_effect = [_server_overloaded_error(), success]
    return client


def test_quiz_carousel_publishes_end_to_end_when_primary_model_is_overloaded(sample_quiz_card, monkeypatch):
    import manual_post_once

    # Isolate the fallback cascade under test from the separate,
    # already-covered (test_trend_research.py) trend-research call, which
    # would otherwise consume the first mocked response itself.
    monkeypatch.setattr(manual_post_once, "is_trend_research_due", lambda: False)

    client = _client_overloaded_once_then_success(sample_quiz_card)
    record = manual_post_once._publish_carousel(client, will_attach_story=False)

    assert record is not None
    assert record.format == ContentFormat.QUIZ_CAROUSEL
    # Round-tripped through the real DRY_RUN graph_client stub, not a mock
    # standing in for the whole publish layer.
    assert record.ig_media_id == "DRYRUN_MEDIA_0000000000"

    assert client.models.generate_content.call_count == 2
    first_model = client.models.generate_content.call_args_list[0].kwargs["model"]
    second_model = client.models.generate_content.call_args_list[1].kwargs["model"]
    assert first_model == CONTENT_MODEL
    assert second_model == CONTENT_MODEL_FALLBACKS[0]


def test_country_fact_reel_publishes_end_to_end_when_primary_model_is_overloaded(sample_country_fact_script):
    import manual_post_once

    client = _client_overloaded_once_then_success(sample_country_fact_script)
    record = manual_post_once._publish_country_fact_reel(client)

    assert record is not None
    assert record.format == ContentFormat.COUNTRY_FACT_REEL
    assert record.ig_media_id == "DRYRUN_MEDIA_0000000000"
    assert client.models.generate_content.call_count == 2


def test_publish_aborts_cleanly_when_every_configured_model_is_overloaded(monkeypatch):
    """If Google's outage is broad enough to take out the primary model
    and every fallback, this must abort the run cleanly (None, no partial
    post, no uncaught crash) — never fail the way the invalid fallback
    model name did, which skipped the cascade and crashed the whole job."""
    import manual_post_once

    monkeypatch.setattr(manual_post_once, "is_trend_research_due", lambda: False)

    client = MagicMock()
    client.models.generate_content.side_effect = _server_overloaded_error()

    record = manual_post_once._publish_carousel(client, will_attach_story=False)

    assert record is None
    assert client.models.generate_content.call_count == 1 + len(CONTENT_MODEL_FALLBACKS)
