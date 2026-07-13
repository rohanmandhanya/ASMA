from __future__ import annotations

from asma.content.prompts import (
    QUIZ_CARD_SYSTEM_PROMPT_HISTORY,
    QUIZ_CARD_SYSTEM_PROMPT_POP_CULTURE,
    country_fact_reel_system_prompt,
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


def test_country_fact_reel_system_prompt_routes_by_category():
    history_prompt = country_fact_reel_system_prompt("history", country="Peru")
    assert "beautiful old fact about Peru" in history_prompt

    # The pop-culture pool's "country" field is really a rotation-bucket
    # label ("Movies"/"Television"/"Sports"), not a place — the pop-culture
    # variant is a static prompt that never templates it in at all (unlike
    # the history variant above, which correctly templates a real country
    # in). Proven directly: two different `country` values produce identical
    # output for this category, so there's no leakage possible.
    pop_culture_prompt_a = country_fact_reel_system_prompt("pop_culture", country="Movies")
    pop_culture_prompt_b = country_fact_reel_system_prompt("pop_culture", country="Television")
    assert pop_culture_prompt_a == pop_culture_prompt_b
    assert "spoil" in pop_culture_prompt_a.lower()
