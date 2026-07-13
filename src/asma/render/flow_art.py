"""Deterministic generative "flow field" background art for quiz-carousel
cards — replaces the AI-generated per-post illustration for this format
specifically (Reels still use `background_client`'s real AI illustration;
this is scoped to quiz carousels only). Chosen deliberately: a stable art
style held for a full ISO week, not regenerated per post, reads as a
consistent visual identity the account is currently running rather than a
new AI-attempted scene per fact — and it's pure local computation, so
unlike the FLUX call it replaces, there's no key, no network call, and no
failure mode to design a fallback around.

Algorithm: seed a small parameter set from the ISO year+week number, trace a
batch of particles through a simple analytic vector field using those
parameters, and render each particle's path as a translucent SVG stroke.
Same week -> identical art; the week after -> a different-looking flow,
since the seed (and therefore the field's shape) changes.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timezone

_STRAND_COUNT = 46
_STEPS_PER_STRAND = 70
_STEP_LENGTH = 16
_MARGIN = 60  # let strands drift slightly past the edges before culling them


def current_week_seed(*, now: datetime | None = None) -> int:
    """Same seed all week (Mon-Sun, ISO week) — a new one the following
    week. `now` is only a parameter for testability; production callers
    always use the real current time."""
    now = now or datetime.now(timezone.utc)
    iso_year, iso_week, _ = now.isocalendar()
    return iso_year * 100 + iso_week


def _field_angle(x: float, y: float, *, freq_x: float, freq_y: float, phase: float, swirl: float) -> float:
    return math.sin(x * freq_x + phase) * math.cos(y * freq_y - phase) * math.pi * swirl


def generate_flow_art_svg(*, width: int, height: int, ink: str, accent: str, seed: int | None = None) -> str:
    """Returns a full standalone `<svg>...</svg>` string sized to
    (width, height) — meant to be embedded as a background image via a data
    URI, the same "one full-bleed illustration" slot the AI-generated
    background used to fill. `seed` defaults to `current_week_seed()`;
    tests pass a fixed value to assert determinism without depending on the
    real calendar week."""
    rng = random.Random(seed if seed is not None else current_week_seed())

    freq_x = rng.uniform(0.0018, 0.0045)
    freq_y = rng.uniform(0.0018, 0.0045)
    phase = rng.uniform(0, math.tau)
    swirl = rng.uniform(0.5, 1.3)

    strands: list[str] = []
    for i in range(_STRAND_COUNT):
        x, y = rng.uniform(0, width), rng.uniform(0, height)
        points = [(x, y)]
        for _ in range(_STEPS_PER_STRAND):
            angle = _field_angle(x, y, freq_x=freq_x, freq_y=freq_y, phase=phase, swirl=swirl)
            x += math.cos(angle) * _STEP_LENGTH
            y += math.sin(angle) * _STEP_LENGTH
            if x < -_MARGIN or x > width + _MARGIN or y < -_MARGIN or y > height + _MARGIN:
                break
            points.append((x, y))
        if len(points) < 2:
            continue
        d = f"M {points[0][0]:.1f} {points[0][1]:.1f} " + " ".join(f"L {px:.1f} {py:.1f}" for px, py in points[1:])
        color = accent if i % 3 == 0 else ink
        stroke_width = rng.uniform(1.2, 2.6)
        opacity = rng.uniform(0.07, 0.20)
        strands.append(
            f'<path d="{d}" stroke="{color}" stroke-width="{stroke_width:.2f}" '
            f'fill="none" stroke-linecap="round" opacity="{opacity:.2f}" />'
        )

    body = "".join(strands)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">{body}</svg>'
    )
