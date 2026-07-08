"""Text -> voiceover audio. Provider: ElevenLabs (Flash model — cheap and
fast; a 60-90s script is well under 1,500 characters, so cost per Reel is a
few cents regardless of provider). Swapping providers later only touches
this file — everything downstream just consumes MP3 bytes.
"""

from __future__ import annotations

import logging

import requests

from asma.config import DRY_RUN, TTS_API_KEY

logger = logging.getLogger(__name__)

_ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
# A default ElevenLabs premade voice (neutral, clear narration). Swap via
# TTS_VOICE_ID env var if a different voice is preferred once the account
# is live and the tone can actually be judged by ear.
DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # "Rachel" — ElevenLabs premade voice
_DRY_RUN_SILENT_MP3 = b""  # placeholder bytes; assembler.py treats DRY_RUN specially, not by parsing this


def synthesize_voiceover(text: str, *, voice_id: str = DEFAULT_VOICE_ID) -> bytes:
    """Returns MP3 bytes. In DRY_RUN, returns empty bytes and never touches
    the network — callers must not attempt to probe/play these bytes,
    only log that synthesis was skipped."""
    if DRY_RUN:
        logger.info("[DRY_RUN] tts: skipping real synthesis (%d chars)", len(text))
        return _DRY_RUN_SILENT_MP3

    if not TTS_API_KEY:
        raise RuntimeError("TTS_API_KEY is not set — cannot synthesize voiceover outside DRY_RUN")

    response = requests.post(
        _ELEVENLABS_TTS_URL.format(voice_id=voice_id),
        headers={"xi-api-key": TTS_API_KEY, "Content-Type": "application/json"},
        json={
            "text": text,
            "model_id": "eleven_flash_v2_5",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.content
