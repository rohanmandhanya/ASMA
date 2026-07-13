"""Renders QuizCard / CountryFactScript / WinnerAnnouncement content into
PNG cards via Jinja2 + headless Chromium (Playwright) — not Pillow.
Variable-length AI-generated text needs the sizing heuristic below, which a
manual Pillow line-wrap loop handles far less robustly than a real browser
layout engine does. Fonts are bundled locally (assets/fonts/) and referenced
via file:// @font-face — no external font CDN at render time, which removes
a real source of nondeterminism from an unattended run.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

from asma.config import CAROUSEL_ASPECT_RATIO, REEL_ASPECT_RATIO, TOPIC_CATEGORY_HISTORY
from asma.models import CountryFactScript, QuizCard, WinnerAnnouncement
from asma.render import background_client
from asma.render.flow_art import generate_flow_art_svg

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_FONTS_DIR = (Path(__file__).resolve().parents[3] / "assets" / "fonts").resolve()
_ACCOUNT_HANDLE = "@forgottenfacts"  # placeholder; set to the real handle once the account exists

_env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)))
_template = _env.get_template("card.html.jinja")


@dataclass(frozen=True)
class Theme:
    bg: str
    ink: str
    accent: str
    rule: str


THEMES: dict[str, Theme] = {
    # Warm parchment/museum-placard look — the default; fits the niche without
    # reading as generic "AI slop" (no purple gradients, no Inter-on-white default).
    "parchment": Theme(bg="#F3ECDC", ink="#241C13", accent="#B5502D", rule="#D9CBA9"),
    # Deeper, higher-contrast variant for visual variety across posts.
    "ink": Theme(bg="#171B26", ink="#F2EEE2", accent="#D7A93B", rule="#333A4C"),
}


def _headline_font_size(text: str, *, width: int) -> int:
    """Deterministic length -> size bucketing, scaled to the card width.
    Chosen over a JS shrink-to-fit loop so rendering stays fully
    predictable and doesn't depend on Playwright measuring/re-laying-out
    at render time — simpler to reason about and to test."""
    n = len(text)
    scale = width / 1080
    if n <= 40:
        base = 84
    elif n <= 80:
        base = 64
    elif n <= 140:
        base = 48
    else:
        base = 38
    return round(base * scale)


class CardRenderer:
    """Owns one headless Chromium instance for the duration of a render
    batch — launching Chromium per-slide would be needlessly slow across a
    5-6 slide carousel or Reel."""

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None

    def __enter__(self) -> "CardRenderer":
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    def render_card(
        self,
        *,
        headline: str,
        kicker: str = "",
        subtext: str = "",
        theme: Theme,
        width: int,
        height: int,
        slide_index: int = 0,
        total_slides: int = 1,
        background_image_data_uri: str | None = None,
    ) -> bytes:
        html = _template.render(
            fonts_dir=str(_FONTS_DIR),
            theme=theme,
            width=width,
            height=height,
            kicker=kicker,
            headline=headline,
            subtext=subtext,
            headline_size=_headline_font_size(headline, width=width),
            slide_index=slide_index,
            total_slides=total_slides,
            handle=_ACCOUNT_HANDLE,
            background_image_data_uri=background_image_data_uri,
        )
        page = self._browser.new_page(viewport={"width": width, "height": height})
        try:
            page.set_content(html, wait_until="load")
            return page.screenshot(type="png")
        finally:
            page.close()


def _quiz_background(*, theme: Theme, width: int, height: int) -> str:
    """Full-bleed generative flow-art background for quiz carousels — see
    render/flow_art.py. Consistent for an entire ISO week (not per-post) so
    the account has a recognizable, current "look" rather than a new
    AI-attempted scene per fact. Pure local computation, so unlike the
    per-post AI illustration Reels still use (_reel_illustration below),
    there's no key, no network call, and no failure mode to fall back from."""
    svg = generate_flow_art_svg(width=width, height=height, ink=theme.ink, accent=theme.accent)
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def _reel_illustration(
    *, fact_text: str, country: str, width: int, height: int, log_id: str, scene_hint: str = ""
) -> str | None:
    """Per-post AI-generated illustration for Reels — unlike quiz carousels'
    flow-art background (_quiz_background above), Reels still use a real
    per-post AI illustration tied to that Reel's own fact/country. No
    fallback icon exists for this failure case, so a failed generation just
    means no background image: the card still renders against the existing
    flat theme, exactly like before this feature existed. `scene_hint` is
    the placeless-topic alternative to `country` (see build_prompt())."""
    prompt = background_client.build_prompt(country=country, scene_hint=scene_hint, fact_text=fact_text)
    try:
        image_bytes = background_client.generate_background_image(prompt, width=width, height=height)
    except background_client.BackgroundImageError:
        logger.warning(
            "background image generation failed for %s; falling back to the flat theme background",
            log_id,
            exc_info=True,
        )
        image_bytes = b""

    if not image_bytes:
        return None
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def render_quiz_card_slides(card: QuizCard, *, theme_name: str = "parchment") -> list[bytes]:
    theme = THEMES[theme_name]
    width, height = CAROUSEL_ASPECT_RATIO
    slides = [
        ("TODAY'S FACT", card.setup_slide, ""),
        ("CAN YOU NAME IT?", card.question_slide, ""),
        *[("THE ANSWER" if i == 0 else "", text, "") for i, text in enumerate(card.reveal_slides)],
    ]
    total = len(slides)
    # One background per post (not per slide) — generated once so every
    # slide in the swipe sequence shares the same art, and the same art
    # holds across every post for the current ISO week.
    background_image_data_uri = _quiz_background(theme=theme, width=width, height=height)
    with CardRenderer() as renderer:
        return [
            renderer.render_card(
                headline=headline,
                kicker=kicker,
                subtext=subtext,
                theme=theme,
                width=width,
                height=height,
                slide_index=i,
                total_slides=total,
                background_image_data_uri=background_image_data_uri,
            )
            for i, (kicker, headline, subtext) in enumerate(slides)
        ]


_POP_CULTURE_SCENE_HINTS: dict[str, str] = {
    "Movies": "classic cinema and filmmaking",
    "Television": "vintage television broadcasting",
    "Sports": "athletic competition and stadiums",
}


def render_country_fact_cards(script: CountryFactScript, *, theme_name: str = "ink") -> list[bytes]:
    theme = THEMES[theme_name]
    width, height = REEL_ASPECT_RATIO
    beats = [script.hook_line, *script.beats]
    total = len(beats)
    # One illustration per Reel (not per beat), same z-indexed background/bubble
    # layering the quiz carousel uses. Pop-culture Reels' `country` field is a
    # rotation-diversity bucket label ("Movies"/"Television"/"Sports"), not a
    # real place, so it's never handed to build_prompt() as a literal
    # location (that produced an awkward "a scene evoking Movies" prompt) —
    # pass a themed scene_hint instead, same idea as the winner-announcement
    # Reel's existing empty-country fallback.
    is_history = script.category == TOPIC_CATEGORY_HISTORY
    background_image_data_uri = _reel_illustration(
        fact_text=script.hook_line,
        country=script.country if is_history else "",
        scene_hint="" if is_history else _POP_CULTURE_SCENE_HINTS.get(script.country, "movies, television, and sports"),
        width=width,
        height=height,
        log_id=f"topic={script.topic_id}",
    )
    with CardRenderer() as renderer:
        return [
            renderer.render_card(
                headline=beat,
                kicker=script.country.upper() if i == 0 else "",
                theme=theme,
                width=width,
                height=height,
                slide_index=i,
                total_slides=total,
                background_image_data_uri=background_image_data_uri,
            )
            for i, beat in enumerate(beats)
        ]


def render_winner_announcement_cards(script: WinnerAnnouncement, *, theme_name: str = "ink") -> list[bytes]:
    theme = THEMES[theme_name]
    width, height = REEL_ASPECT_RATIO
    beats = [script.hook_line, *script.beats]
    total = len(beats)
    # No natural "country" for a leaderboard win — build_prompt() falls back
    # to a generic celebratory scene instead.
    background_image_data_uri = _reel_illustration(
        fact_text=script.hook_line, country="", width=width, height=height, log_id=f"winner={script.winner_username}"
    )
    with CardRenderer() as renderer:
        return [
            renderer.render_card(
                headline=beat,
                kicker="WEEKLY WINNER" if i == 0 else "",
                theme=theme,
                width=width,
                height=height,
                slide_index=i,
                total_slides=total,
                background_image_data_uri=background_image_data_uri,
            )
            for i, beat in enumerate(beats)
        ]
