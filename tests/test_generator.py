from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from asma.content import generator
from asma.models import CommentReply, HookStyle, QuizCard


def _fake_client(*, stop_reason: str = "end_turn", parsed_output=None) -> MagicMock:
    client = MagicMock()
    client.messages.parse.return_value = SimpleNamespace(stop_reason=stop_reason, parsed_output=parsed_output)
    return client


def test_generate_quiz_card_success(sample_quiz_card):
    client = _fake_client(parsed_output=sample_quiz_card)
    card = generator.generate_quiz_card(
        client,
        topic_id=sample_quiz_card.topic_id,
        country=sample_quiz_card.country,
        seed_angle="some seed angle",
        hook=HookStyle.STAT_LED,
    )
    assert card.topic_id == sample_quiz_card.topic_id
    assert card.answer == sample_quiz_card.answer
    client.messages.parse.assert_called_once()


def test_generate_quiz_card_forces_requested_topic_country_hook(sample_quiz_card):
    # Even if the model echoes back something else for these fields, the
    # caller-specified values win — we already decided them before calling.
    drifted = sample_quiz_card.model_copy(update={"topic_id": "wrong_topic", "country": "Nowhere"})
    client = _fake_client(parsed_output=drifted)
    card = generator.generate_quiz_card(
        client,
        topic_id="mongolia_yam_relay",
        country="Mongolia",
        seed_angle="x",
        hook=HookStyle.STAT_LED,
    )
    assert card.topic_id == "mongolia_yam_relay"
    assert card.country == "Mongolia"


def test_generate_quiz_card_raises_on_refusal():
    client = _fake_client(stop_reason="refusal", parsed_output=None)
    with pytest.raises(generator.GenerationError, match="refused"):
        generator.generate_quiz_card(
            client, topic_id="t", country="c", seed_angle="s", hook=HookStyle.BOLD_CLAIM
        )


def test_generate_quiz_card_raises_on_unparseable_response():
    client = _fake_client(stop_reason="end_turn", parsed_output=None)
    with pytest.raises(generator.GenerationError, match="did not parse"):
        generator.generate_quiz_card(
            client, topic_id="t", country="c", seed_angle="s", hook=HookStyle.BOLD_CLAIM
        )


def test_generate_comment_reply_returns_text():
    client = _fake_client(parsed_output=CommentReply(reply_text="Nice guess, close but not quite!"))
    reply = generator.generate_comment_reply(
        client,
        comment_text="Is it the Yam?",
        is_substantive_fact_share=False,
        is_correct_guess=True,
        quiz_context="Q: ... A: The Yam",
    )
    assert reply == "Nice guess, close but not quite!"


def test_generate_comment_reply_raises_on_refusal():
    client = _fake_client(stop_reason="refusal", parsed_output=None)
    with pytest.raises(generator.GenerationError):
        generator.generate_comment_reply(
            client, comment_text="x", is_substantive_fact_share=True, is_correct_guess=None, quiz_context="c"
        )


def test_never_falls_back_to_posting_unvalidated_content(sample_quiz_card, monkeypatch):
    """The core reliability property from the plan: a refusal or parse
    failure must abort, never silently produce a QuizCard anyway."""
    client = _fake_client(stop_reason="refusal", parsed_output=None)
    with pytest.raises(generator.GenerationError):
        result = generator.generate_quiz_card(
            client, topic_id="t", country="c", seed_angle="s", hook=HookStyle.BOLD_CLAIM
        )
        assert not isinstance(result, QuizCard)  # unreachable if the raise above works, which is the point
