"""Text -> voiceover audio. Provider: Piper — a local, free, offline neural
TTS engine (no API key, no per-character cost, no network call at synthesis
time). Chosen over a paid provider (e.g. ElevenLabs) specifically to avoid
the one recurring cost in this pipeline that had no graceful fallback: a
missing/failed voiceover breaks the whole Reel, unlike the background-image
generation this project already treats as optional. Swapping providers
later only touches this file — everything downstream just consumes MP3
bytes.

Piper's voice model (~60MB) is committed to git directly in assets/tts/,
which this module reads from — deliberately not fetched at workflow runtime.
It was originally downloaded on demand instead (same convention as
Playwright's browser binaries), but that made every run depend on Hugging
Face's CDN being up; a real, confirmed outage there (HTTP 403 from
cas-bridge.xethub.hf.co, HF's large-file storage backend, affecting
unrelated projects too) took down every workflow that needed real TTS,
for a fixed, unchanging 60MB file. Committing it once removes that
dependency and the redownload latency entirely.

Known issue (verified, not a guess): the piper-tts PyPI wheel for macOS
(at least 1.4.2) ships with a hardcoded, build-machine-specific path to its
bundled espeak-ng phoneme data, which breaks local synthesis on macOS
entirely — confirmed via direct testing, independent of a working system
espeak-ng install. The Linux wheel (what GitHub Actions' ubuntu-latest
runners actually use) does not have this bug — confirmed by running the
identical synthesis call inside a python:3.12-slim container. Local
DRY_RUN=false testing of this module on macOS will fail until upstream
fixes the macOS wheel; DRY_RUN=true (the default) never touches Piper at
all, so this doesn't block anything except manually testing real audio
output locally on a Mac.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

from asma.config import DRY_RUN

logger = logging.getLogger(__name__)

DEFAULT_VOICE = "en_GB-alan-medium"  # deep, unhurried British male — picked over the
# single-speaker American voices in a real side-by-side listening comparison for a
# more "wise narrator" quality that fits history-fact content better than a neutral
# conversational voice.
# >1.0 stretches the audio (slower speech). 1.0 is Piper's natural pace, which
# reads as rushed for factual narration meant to actually be absorbed — 1.08
# slows it just enough for a deliberate pace without dragging (1.15 was tried
# and felt a half-step too slow for this particular voice).
DEFAULT_LENGTH_SCALE = 1.08
_MODEL_DIR = (Path(__file__).resolve().parents[3] / "assets" / "tts").resolve()
_DRY_RUN_SILENT_MP3 = b""  # placeholder bytes; assembler.py treats DRY_RUN specially, not by parsing this


def synthesize_voiceover(
    text: str, *, voice: str = DEFAULT_VOICE, length_scale: float = DEFAULT_LENGTH_SCALE
) -> bytes:
    """Returns MP3 bytes. In DRY_RUN, returns empty bytes and never touches
    Piper — callers must not attempt to probe/play these bytes, only log
    that synthesis was skipped."""
    if DRY_RUN:
        logger.info("[DRY_RUN] tts: skipping real synthesis (%d chars)", len(text))
        return _DRY_RUN_SILENT_MP3

    model_path = _MODEL_DIR / f"{voice}.onnx"
    if not model_path.exists():
        raise RuntimeError(
            f"Piper voice model not found at {model_path} — run "
            f"`uv run python -m piper.download_voices {voice} --download-dir {_MODEL_DIR}` "
            "before synthesizing outside DRY_RUN"
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        wav_path = tmp / "voiceover.wav"
        mp3_path = tmp / "voiceover.mp3"

        piper_result = subprocess.run(
            ["piper", "-m", str(model_path), "-f", str(wav_path), "--length-scale", str(length_scale)],
            input=text.encode("utf-8"),
            capture_output=True,
        )
        if piper_result.returncode != 0:
            raise RuntimeError(f"piper synthesis failed: {piper_result.stderr.decode(errors='replace')[-2000:]}")

        ffmpeg_result = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_path), "-ar", "44100", "-b:a", "128k", str(mp3_path)],
            capture_output=True,
        )
        if ffmpeg_result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg mp3 conversion failed: {ffmpeg_result.stderr.decode(errors='replace')[-2000:]}"
            )

        return mp3_path.read_bytes()
