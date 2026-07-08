"""Renders QuizCard / CountryFactScript / WinnerAnnouncement content into
PNG cards via Jinja2 + headless Chromium (Playwright) — not Pillow.
Variable-length AI-generated text needs the sizing heuristic below, which a
manual Pillow line-wrap loop handles far less robustly than a real browser
layout engine does. Fonts are bundled locally (assets/fonts/) and referenced
via file:// @font-face — no external font CDN at render time, which removes
a real source of nondeterminism from an unattended run.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

from asma.config import CAROUSEL_ASPECT_RATIO, REEL_ASPECT_RATIO
from asma.models import CountryFactScript, QuizCard, WinnerAnnouncement

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
        )
        page = self._browser.new_page(viewport={"width": width, "height": height})
        try:
            page.set_content(html, wait_until="load")
            return page.screenshot(type="png")
        finally:
            page.close()


def render_quiz_card_slides(card: QuizCard, *, theme_name: str = "parchment") -> list[bytes]:
    theme = THEMES[theme_name]
    width, height = CAROUSEL_ASPECT_RATIO
    slides = [
        ("TODAY'S FACT", card.setup_slide, ""),
        ("CAN YOU NAME IT?", card.question_slide, ""),
        *[("THE ANSWER" if i == 0 else "", text, "") for i, text in enumerate(card.reveal_slides)],
    ]
    total = len(slides)
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
            )
            for i, (kicker, headline, subtext) in enumerate(slides)
        ]


def render_country_fact_cards(script: CountryFactScript, *, theme_name: str = "ink") -> list[bytes]:
    theme = THEMES[theme_name]
    width, height = REEL_ASPECT_RATIO
    beats = [script.hook_line, *script.beats]
    total = len(beats)
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
            )
            for i, beat in enumerate(beats)
        ]


def render_winner_announcement_cards(script: WinnerAnnouncement, *, theme_name: str = "ink") -> list[bytes]:
    theme = THEMES[theme_name]
    width, height = REEL_ASPECT_RATIO
    beats = [script.hook_line, *script.beats]
    total = len(beats)
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
            )
            for i, beat in enumerate(beats)
        ]
