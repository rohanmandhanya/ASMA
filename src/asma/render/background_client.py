"""Prompt -> illustrated background image bytes for Reels, one per Reel
*post* (not per beat/card) — generated once and reused across all of that
Reel's cards. Quiz carousels no longer use this module at all — their
background is generated locally instead, see render/flow_art.py.

Provider: Pollinations.ai — free, no billing account, no signup required
for basic use (unlike a FLUX/Imagen/Gemini-class API, which all require a
linked payment method regardless of actual per-image cost). A single
synchronous GET request returns image bytes directly; no submit/poll/fetch
dance needed, unlike most hosted text-to-image APIs. Swapping providers
later only touches this file — everything downstream just consumes PNG
bytes.

Auth is optional, not required — this is a real difference from the FLUX
setup it replaces. With no token configured, requests still succeed
(anonymous tier: watermarked, rate-limited to roughly one request per 15
seconds). A free registered token (auth.pollinations.ai, no card) removes
the watermark and raises the rate limit. Exact query params/response shape
below are the documented 2026 API surface — verify against current docs
before the first real (non-DRY_RUN) call, same as graph_client.py's own
"verify at deploy time" notes.
"""

from __future__ import annotations

import logging
import urllib.parse

import requests

from asma.config import DRY_RUN, POLLINATIONS_API_TOKEN

logger = logging.getLogger(__name__)

_BASE_URL = "https://image.pollinations.ai/prompt"
_REQUEST_TIMEOUT_SECONDS = 60

_STYLE_SUFFIX = (
    "Simple flat illustration, clean shapes, minimal detail, muted color palette. "
    "A single plain wide scene, not busy or ornate. "
    "No text, no letters, no logos, no watermark, no photorealistic human faces."
)

_DRY_RUN_PLACEHOLDER_IMAGE = b""  # renderer.py treats DRY_RUN specially, not by decoding this


class BackgroundImageError(RuntimeError):
    pass


def build_prompt(*, fact_text: str, country: str = "", scene_hint: str = "") -> str:
    """One prompt per Reel — `fact_text` is whatever line best captures the
    post (a CountryFactScript's hook_line, a WinnerAnnouncement's hook_line).
    `country` must be a real place — formats/topics without one (the weekly
    winner Reel, or a pop-culture CountryFactScript whose `country` field is
    really a "Movies"/"Television"/"Sports" rotation-bucket label, not a
    place) should leave it empty rather than pass that label through, since
    "a scene evoking Movies" reads as a nonexistent location. `scene_hint` is
    the alternative for that case — a generic thematic phrase (e.g. "classic
    cinema and filmmaking"), used only when `country` is empty. If neither is
    given, a fully generic celebratory scene is used instead (unchanged
    behavior for the weekly winner Reel). The fixed style suffix keeps every
    generated image visually consistent with the account's look, even though
    the subject changes post to post."""
    if country:
        scene = f"A scene evoking {country}."
    elif scene_hint:
        scene = f"A scene evoking {scene_hint}."
    else:
        scene = "A warm, celebratory scene."
    return f"{fact_text} {scene} {_STYLE_SUFFIX}"


def generate_background_image(prompt: str, *, width: int, height: int) -> bytes:
    """Returns PNG/JPEG bytes. In DRY_RUN, returns empty bytes and never
    touches the network — callers must not attempt to decode these bytes,
    only log that generation was skipped (renderer.py falls back to the
    flat theme background whenever this returns empty, which is also how
    DRY_RUN behaves locally).

    Unlike the FLUX setup this replaces, a missing `POLLINATIONS_API_TOKEN`
    does NOT raise — the anonymous tier still generates real images, just
    watermarked and rate-limited. The token only unlocks `nologo` + a
    faster rate tier."""
    if DRY_RUN:
        logger.info("[DRY_RUN] background_client: skipping real image generation (prompt=%r)", prompt)
        return _DRY_RUN_PLACEHOLDER_IMAGE

    encoded_prompt = urllib.parse.quote(prompt, safe="")
    params: dict[str, str] = {"model": "flux", "width": str(width), "height": str(height)}
    headers: dict[str, str] = {}
    if POLLINATIONS_API_TOKEN:
        params["nologo"] = "true"
        headers["Authorization"] = f"Bearer {POLLINATIONS_API_TOKEN}"

    response = requests.get(
        f"{_BASE_URL}/{encoded_prompt}", params=params, headers=headers, timeout=_REQUEST_TIMEOUT_SECONDS
    )
    if response.status_code >= 400:
        raise BackgroundImageError(f"background image generation failed: status={response.status_code}")
    return response.content
