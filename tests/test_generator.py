from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

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
