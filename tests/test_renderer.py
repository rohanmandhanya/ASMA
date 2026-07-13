from __future__ import annotations

import base64

import pytest

from asma.render import background_client
from asma.render.renderer import (
    render_country_fact_cards,
    render_quiz_card_slides,
    render_winner_announcement_cards,
)

_TINY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="


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
def test_background_image_text_actually_differs_between_slides(sample_quiz_card):
    """Regression test for a real stacking-context bug: `.bg-image`/`.bg-scrim`
    were `position: absolute` with no `z-index`, which — per default CSS paint
    order — placed them ABOVE the static in-flow `.bubble`/headline rather
    than behind it, silently hiding the text under the background+scrim. A
    plain byte-level diff between slides didn't catch this (the footer's
    pagination dots still differed), so this asserts on pixel-count difference
    specifically, comparing against a same-headline control. Both cards render
    in the same ISO week, so the flow-art background itself is identical
    between them — isolating the headline-text difference is exactly the point."""
    import io

    from PIL import Image

    card_a = sample_quiz_card.model_copy(update={"setup_slide": "AAAA completely different headline text AAAA"})
    card_b = sample_quiz_card.model_copy(update={"setup_slide": "ZZZZ a totally other headline goes here ZZZZ"})

    slides_a = render_quiz_card_slides(card_a)
    slides_b = render_quiz_card_slides(card_b)

    img_a = Image.open(io.BytesIO(slides_a[0])).convert("RGB")
    img_b = Image.open(io.BytesIO(slides_b[0])).convert("RGB")
    bytes_a, bytes_b = img_a.tobytes(), img_b.tobytes()
    diff_pixels = sum(1 for i in range(0, len(bytes_a), 3) if bytes_a[i : i + 3] != bytes_b[i : i + 3])

    # Different headline text over the same background must change far more
    # than just the (identical here) footer/pagination pixels.
    assert diff_pixels > 5000, f"only {diff_pixels} pixels differ — headline text may be hidden behind the background"


@pytest.mark.slow
def test_render_quiz_card_slides_background_consistent_within_same_week(sample_quiz_card):
    """The whole point of switching to generative flow-art backgrounds: the
    same art should hold across every post in a given ISO week, not vary
    per-post like the AI illustration it replaced. Two independent render
    calls for the same card should produce byte-identical output, since
    both the card content and the (same-week) background seed are fixed."""
    slides = render_quiz_card_slides(sample_quiz_card)
    slides_rerun = render_quiz_card_slides(sample_quiz_card)
    assert slides[0] == slides_rerun[0]


@pytest.mark.slow
def test_render_country_fact_cards_produces_one_per_beat(sample_country_fact_script):
    expected = 1 + len(sample_country_fact_script.beats)  # hook_line + beats
    cards = render_country_fact_cards(sample_country_fact_script)
    assert len(cards) == expected
    assert all(_is_nonblank_png(c) for c in cards)


@pytest.mark.slow
def test_render_country_fact_cards_renders_with_background_image(sample_country_fact_script, monkeypatch):
    """Reels reuse the same z-indexed background/bubble layering the quiz
    carousel's stacking-context regression test already covers — this just
    confirms the wiring (background_client actually gets called, cards still
    render) rather than re-proving the CSS itself."""
    fixed_background = base64.b64decode(_TINY_PNG_B64)
    monkeypatch.setattr(background_client, "generate_background_image", lambda *a, **k: fixed_background)

    cards = render_country_fact_cards(sample_country_fact_script)
    assert len(cards) == 1 + len(sample_country_fact_script.beats)
    assert all(_is_nonblank_png(c) for c in cards)


@pytest.mark.slow
def test_render_country_fact_cards_pop_culture_never_passes_bucket_label_as_country(
    sample_country_fact_script, monkeypatch
):
    """Pop-culture CountryFactScripts' `country` field is really a rotation-
    bucket label ("Movies"/"Television"/"Sports"), not a place — this
    confirms it's never handed to build_prompt() as a literal country
    (which would produce an awkward "a scene evoking Movies" prompt),
    routing through scene_hint instead."""
    captured = {}
    original_build_prompt = background_client.build_prompt

    def _capture(*, fact_text, country="", scene_hint=""):
        captured["country"] = country
        captured["scene_hint"] = scene_hint
        return original_build_prompt(fact_text=fact_text, country=country, scene_hint=scene_hint)

    monkeypatch.setattr(background_client, "build_prompt", _capture)
    monkeypatch.setattr(background_client, "generate_background_image", lambda *a, **k: b"")

    pop_culture_script = sample_country_fact_script.model_copy(
        update={"category": "pop_culture", "country": "Movies", "topic_id": "movie_jaws_mechanical_shark"}
    )
    render_country_fact_cards(pop_culture_script)
    assert captured["country"] == ""
    assert captured["scene_hint"] and captured["scene_hint"] != "Movies"


@pytest.mark.slow
def test_render_country_fact_cards_falls_back_to_flat_theme_when_background_generation_fails(
    sample_country_fact_script, monkeypatch
):
    """No icon fallback exists for Reels — a failed generation should just
    mean the card renders against the plain theme background, same as
    before this feature existed, not a crash."""

    def _raise(*args, **kwargs):
        raise background_client.BackgroundImageError("simulated provider failure")

    monkeypatch.setattr(background_client, "generate_background_image", _raise)

    cards = render_country_fact_cards(sample_country_fact_script)
    assert len(cards) == 1 + len(sample_country_fact_script.beats)
    assert all(_is_nonblank_png(c) for c in cards)


@pytest.mark.slow
def test_render_winner_announcement_cards_uses_generic_scene_no_country_needed(monkeypatch):
    """The weekly winner Reel has no natural country/location — this just
    confirms that format still renders cleanly end to end with a background
    image in play (build_prompt's empty-country fallback is unit-tested
    separately in test_background_client.py)."""
    from asma.models import WinnerAnnouncement

    fixed_background = base64.b64decode(_TINY_PNG_B64)
    monkeypatch.setattr(background_client, "generate_background_image", lambda *a, **k: fixed_background)

    script = WinnerAnnouncement(
        winner_username="history_fan_42",
        correct_answer_count=5,
        week_of="2026-07-06",
        hook_line="This week's winner answered 5 questions correctly!",
        beats=["Huge congrats to @history_fan_42", "5 correct answers this week"],
        voiceover_script="Big congrats to this week's trivia champion.",
        caption="Weekly winner!",
        hashtags=["#history", "#trivia", "#winner"],
    )
    cards = render_winner_announcement_cards(script)
    assert len(cards) == 1 + len(script.beats)
    assert all(_is_nonblank_png(c) for c in cards)
