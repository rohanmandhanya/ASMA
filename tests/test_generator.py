from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from google.genai import errors

from asma.config import CONTENT_MODEL, CONTENT_MODEL_FALLBACKS
from asma.content import generator
from asma.models import CommentAnswerJudgement, CommentReply, HookStyle, QuizCard


def _fake_client(*, finish_reason: str = "STOP", parsed=None, blocked: bool = False) -> MagicMock:
    client = MagicMock()
    if blocked:
        # Prompt rejected before generation even started — candidates is
        # empty and prompt_feedback.block_reason is set, a distinct code
        # path from a mid-generation finish_reason like SAFETY.
        response = SimpleNamespace(candidates=[], prompt_feedback=SimpleNamespace(block_reason="SAFETY"), parsed=None)
    else:
        candidate = SimpleNamespace(finish_reason=finish_reason)
        response = SimpleNamespace(candidates=[candidate], prompt_feedback=None, parsed=parsed)
    client.models.generate_content.return_value = response
    return client


def _server_overloaded_error() -> errors.ServerError:
    response_json = {
        "error": {
            "code": 503,
            "message": "This model is currently experiencing high demand. Please try again later.",
            "status": "UNAVAILABLE",
        }
    }
    return errors.ServerError(503, response_json)


def test_generate_quiz_card_success(sample_quiz_card):
    client = _fake_client(parsed=sample_quiz_card)
    card = generator.generate_quiz_card(
        client,
        topic_id=sample_quiz_card.topic_id,
        country=sample_quiz_card.country,
        seed_angle="some seed angle",
        hook=HookStyle.STAT_LED,
    )
    assert card.topic_id == sample_quiz_card.topic_id
    assert card.answer == sample_quiz_card.answer
    client.models.generate_content.assert_called_once()


def test_generate_quiz_card_forces_requested_topic_country_hook(sample_quiz_card):
    # Even if the model echoes back something else for these fields, the
    # caller-specified values win — we already decided them before calling.
    drifted = sample_quiz_card.model_copy(update={"topic_id": "wrong_topic", "country": "Nowhere"})
    client = _fake_client(parsed=drifted)
    card = generator.generate_quiz_card(
        client,
        topic_id="mongolia_yam_relay",
        country="Mongolia",
        seed_angle="x",
        hook=HookStyle.STAT_LED,
    )
    assert card.topic_id == "mongolia_yam_relay"
    assert card.country == "Mongolia"


def test_generate_quiz_card_forces_requested_category(sample_quiz_card):
    # Even if the model echoes back "history" (its default), an explicitly
    # requested pop_culture category must win, same as topic_id/country/hook.
    client = _fake_client(parsed=sample_quiz_card)
    card = generator.generate_quiz_card(
        client,
        topic_id="movie_jaws_mechanical_shark",
        country="Movies",
        seed_angle="x",
        hook=HookStyle.STAT_LED,
        category="pop_culture",
    )
    assert card.category == "pop_culture"
    used_config = client.models.generate_content.call_args.kwargs["config"]
    from asma.content.prompts import QUIZ_CARD_SYSTEM_PROMPT_POP_CULTURE

    assert used_config.system_instruction == QUIZ_CARD_SYSTEM_PROMPT_POP_CULTURE


def test_generate_quiz_card_raises_on_refusal():
    client = _fake_client(finish_reason="SAFETY", parsed=None)
    with pytest.raises(generator.GenerationError, match="finish_reason"):
        generator.generate_quiz_card(client, topic_id="t", country="c", seed_angle="s", hook=HookStyle.BOLD_CLAIM)


def test_generate_quiz_card_raises_when_prompt_blocked_before_generation():
    """Distinct from a mid-generation refusal: the prompt itself was
    rejected, so there are no candidates at all — a separate check in
    _generate() from the finish_reason path above."""
    client = _fake_client(blocked=True)
    with pytest.raises(generator.GenerationError, match="blocked"):
        generator.generate_quiz_card(client, topic_id="t", country="c", seed_angle="s", hook=HookStyle.BOLD_CLAIM)


def test_generate_quiz_card_raises_on_unparseable_response():
    client = _fake_client(finish_reason="STOP", parsed=None)
    with pytest.raises(generator.GenerationError, match="did not parse"):
        generator.generate_quiz_card(client, topic_id="t", country="c", seed_angle="s", hook=HookStyle.BOLD_CLAIM)


def test_generate_quiz_card_falls_back_to_next_model_on_503(sample_quiz_card):
    """gemini-3.5-flash overloaded (503) shouldn't lose the whole run —
    retry against the next configured fallback model before giving up."""
    client = MagicMock()
    candidate = SimpleNamespace(finish_reason="STOP")
    success_response = SimpleNamespace(candidates=[candidate], prompt_feedback=None, parsed=sample_quiz_card)
    client.models.generate_content.side_effect = [_server_overloaded_error(), success_response]

    card = generator.generate_quiz_card(
        client, topic_id=sample_quiz_card.topic_id, country=sample_quiz_card.country, seed_angle="s",
        hook=HookStyle.STAT_LED,
    )

    assert card.answer == sample_quiz_card.answer
    assert client.models.generate_content.call_count == 2
    first_model = client.models.generate_content.call_args_list[0].kwargs["model"]
    second_model = client.models.generate_content.call_args_list[1].kwargs["model"]
    assert first_model == CONTENT_MODEL
    assert second_model == CONTENT_MODEL_FALLBACKS[0]


def test_generate_quiz_card_raises_when_every_model_is_overloaded(sample_quiz_card):
    client = MagicMock()
    client.models.generate_content.side_effect = _server_overloaded_error()

    with pytest.raises(generator.GenerationError, match="unavailable"):
        generator.generate_quiz_card(
            client, topic_id="t", country="c", seed_angle="s", hook=HookStyle.BOLD_CLAIM
        )

    # Primary model + every fallback, no more, no fewer.
    assert client.models.generate_content.call_count == 1 + len(CONTENT_MODEL_FALLBACKS)


def test_judge_comment_answer_raises_generation_error_on_503_with_no_fallback():
    """REPLY_MODEL has no configured fallbacks (it's already the cheap
    tier) — a 503 there should abort cleanly, not retry indefinitely."""
    client = MagicMock()
    client.models.generate_content.side_effect = _server_overloaded_error()

    with pytest.raises(generator.GenerationError, match="unavailable"):
        generator.judge_comment_answer(client, comment_text="x", correct_answer="y", question="q")

    client.models.generate_content.assert_called_once()


def test_generate_country_fact_script_success(sample_country_fact_script):
    client = _fake_client(parsed=sample_country_fact_script)
    script = generator.generate_country_fact_script(
        client,
        topic_id=sample_country_fact_script.topic_id,
        country=sample_country_fact_script.country,
        seed_angle="some seed angle",
        hook=HookStyle.STAT_LED,
    )
    assert script.topic_id == sample_country_fact_script.topic_id
    client.models.generate_content.assert_called_once()


def test_generate_country_fact_script_forces_requested_topic_country_hook(sample_country_fact_script):
    drifted = sample_country_fact_script.model_copy(update={"topic_id": "wrong_topic", "country": "Nowhere"})
    client = _fake_client(parsed=drifted)
    script = generator.generate_country_fact_script(
        client, topic_id="peru_inca_quipu_records", country="Peru", seed_angle="x", hook=HookStyle.STAT_LED
    )
    assert script.topic_id == "peru_inca_quipu_records"
    assert script.country == "Peru"


def test_generate_country_fact_script_forces_requested_category(sample_country_fact_script):
    # Even if the model echoes back "history" (its default), an explicitly
    # requested pop_culture category must win, same as generate_quiz_card.
    client = _fake_client(parsed=sample_country_fact_script)
    script = generator.generate_country_fact_script(
        client,
        topic_id="movie_jaws_mechanical_shark",
        country="Movies",
        seed_angle="x",
        hook=HookStyle.STAT_LED,
        category="pop_culture",
    )
    assert script.category == "pop_culture"
    used_config = client.models.generate_content.call_args.kwargs["config"]
    from asma.content.prompts import COUNTRY_FACT_REEL_SYSTEM_PROMPT_POP_CULTURE

    assert used_config.system_instruction == COUNTRY_FACT_REEL_SYSTEM_PROMPT_POP_CULTURE


def test_generate_country_fact_script_raises_on_refusal():
    client = _fake_client(finish_reason="SAFETY", parsed=None)
    with pytest.raises(generator.GenerationError, match="finish_reason"):
        generator.generate_country_fact_script(
            client, topic_id="t", country="c", seed_angle="s", hook=HookStyle.BOLD_CLAIM
        )


def test_judge_comment_answer_returns_parsed_judgement():
    judgement_out = CommentAnswerJudgement(is_correct=True, matched_answer_text="the Yam", is_substantive_fact_share=False)
    client = _fake_client(parsed=judgement_out)
    judgement = generator.judge_comment_answer(
        client, comment_text="It's the Yam!", correct_answer="The Yam", question="What was it called?"
    )
    assert judgement.is_correct is True
    assert judgement.matched_answer_text == "the Yam"


def test_generate_comment_reply_returns_text():
    client = _fake_client(parsed=CommentReply(reply_text="Nice guess, close but not quite!"))
    reply = generator.generate_comment_reply(
        client,
        comment_text="Is it the Yam?",
        is_substantive_fact_share=False,
        is_correct_guess=True,
        quiz_context="Q: ... A: The Yam",
    )
    assert reply == "Nice guess, close but not quite!"


def test_generate_comment_reply_raises_on_refusal():
    client = _fake_client(finish_reason="SAFETY", parsed=None)
    with pytest.raises(generator.GenerationError):
        generator.generate_comment_reply(
            client, comment_text="x", is_substantive_fact_share=True, is_correct_guess=None, quiz_context="c"
        )


def test_never_falls_back_to_posting_unvalidated_content(sample_quiz_card):
    """The core reliability property from the plan: a refusal or parse
    failure must abort, never silently produce a QuizCard anyway."""
    client = _fake_client(finish_reason="SAFETY", parsed=None)
    with pytest.raises(generator.GenerationError):
        result = generator.generate_quiz_card(client, topic_id="t", country="c", seed_angle="s", hook=HookStyle.BOLD_CLAIM)
        assert not isinstance(result, QuizCard)  # unreachable if the raise above works, which is the point
