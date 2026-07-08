from __future__ import annotations

import pytest

from asma.render.renderer import render_country_fact_cards, render_quiz_card_slides


def _is_nonblank_png(data: bytes) -> bool:
    return data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) > 1000


@pytest.mark.slow
def test_render_quiz_card_slides_produces_expected_count(sample_quiz_card):
    # setup + question + N reveal slides
    expected = 2 + len(sample_quiz_card.reveal_slides)
    slides = render_quiz_card_slides(sample_quiz_card)
    assert len(slides) == expected
    assert all(_is_nonblank_png(s) for s in slides)


@pytest.mark.slow
def test_render_country_fact_cards_produces_one_per_beat(sample_country_fact_script):
    expected = 1 + len(sample_country_fact_script.beats)  # hook_line + beats
    cards = render_country_fact_cards(sample_country_fact_script)
    assert len(cards) == expected
    assert all(_is_nonblank_png(c) for c in cards)
