from __future__ import annotations

from asma.content.prompts import (
    QUIZ_CARD_SYSTEM_PROMPT_HISTORY,
    QUIZ_CARD_SYSTEM_PROMPT_POP_CULTURE,
    quiz_card_system_prompt,
)


def test_quiz_card_system_prompt_routes_by_category():
    assert quiz_card_system_prompt("history") == QUIZ_CARD_SYSTEM_PROMPT_HISTORY
    assert quiz_card_system_prompt("pop_culture") == QUIZ_CARD_SYSTEM_PROMPT_POP_CULTURE
    assert quiz_card_system_prompt("anything_else") == QUIZ_CARD_SYSTEM_PROMPT_HISTORY


def test_pop_culture_prompt_has_spoiler_and_no_ranking_guardrails():
    assert "spoil" in QUIZ_CARD_SYSTEM_PROMPT_POP_CULTURE.lower()
    assert "subjective ranking" in QUIZ_CARD_SYSTEM_PROMPT_POP_CULTURE.lower()
    assert "verbatim" in QUIZ_CARD_SYSTEM_PROMPT_POP_CULTURE.lower()


def test_pop_culture_prompt_forbids_title_as_the_answer():
    # Regression: the quiz mystery must be a hidden detail, not "which movie/show is
    # this" — the title should be named openly, not held back as the reveal.
    lowered = QUIZ_CARD_SYSTEM_PROMPT_POP_CULTURE.lower()
    assert "which movie/show is" in lowered
    assert "name the movie/show/event openly" in lowered


def test_history_and_pop_culture_prompts_share_the_same_quiz_structure():
    # Both categories generate the same QuizCard schema via the same
    # setup/question/reveal structure — only the niche-core guardrails differ.
    assert "setup_slide" in QUIZ_CARD_SYSTEM_PROMPT_HISTORY
    assert "setup_slide" in QUIZ_CARD_SYSTEM_PROMPT_POP_CULTURE
