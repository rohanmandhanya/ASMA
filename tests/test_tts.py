from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from asma.video import tts

_MODEL_PATH = Path(__file__).resolve().parents[1] / "assets" / "tts" / f"{tts.DEFAULT_VOICE}.onnx"


def test_dry_run_never_touches_piper(monkeypatch):
    monkeypatch.setattr(tts, "DRY_RUN", True)

    def _fail(*args, **kwargs):
        raise AssertionError("piper/ffmpeg must never be invoked under DRY_RUN")

    monkeypatch.setattr(subprocess, "run", _fail)

    assert tts.synthesize_voiceover("some narration text") == b""


def test_raises_clear_error_when_model_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(tts, "DRY_RUN", False)
    monkeypatch.setattr(tts, "_MODEL_DIR", tmp_path)  # empty dir, no .onnx file present

    with pytest.raises(RuntimeError, match="download_voices"):
        tts.synthesize_voiceover("some narration text")


@pytest.mark.slow
@pytest.mark.skipif(
    sys.platform == "darwin",
    reason="piper-tts's macOS wheel has a verified hardcoded-path bug that breaks real synthesis "
    "entirely (see assets/tts/README.md) — real synthesis only works on Linux (the actual "
    "GitHub Actions target) until upstream fixes the macOS wheel",
)
@pytest.mark.skipif(not _MODEL_PATH.exists(), reason="Piper voice model not downloaded — see assets/tts/README.md")
def test_real_synthesis_produces_valid_mp3(monkeypatch):
    monkeypatch.setattr(tts, "DRY_RUN", False)
    audio_bytes = tts.synthesize_voiceover("Testing one two three, this is real synthesized speech.")
    assert len(audio_bytes) > 1000
    assert audio_bytes[:3] == b"ID3"  # ffmpeg's default MP3 muxer writes an ID3v2 header
