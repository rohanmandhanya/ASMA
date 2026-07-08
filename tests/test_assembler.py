from __future__ import annotations

import shutil
import subprocess

import pytest

from asma.config import REEL_ASPECT_RATIO
from asma.render.renderer import render_country_fact_cards
from asma.video.assembler import assemble_reel

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _probe(path, *, entry: str) -> str:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", entry, "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.mark.slow
def test_assemble_reel_meets_spec(tmp_path, sample_country_fact_script, monkeypatch):
    import asma.video.assembler as assembler

    monkeypatch.setattr(assembler, "DRY_RUN", False)

    cards = render_country_fact_cards(sample_country_fact_script)

    # A short synthetic tone stands in for a real TTS voiceover — this test
    # validates the ffmpeg pipeline's spec compliance, not voice quality.
    voiceover_path = tmp_path / "voiceover.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=6", str(voiceover_path)],
        check=True,
    )
    voiceover_bytes = voiceover_path.read_bytes()

    output_path = tmp_path / "output.mp4"
    result_path = assemble_reel(cards, voiceover_bytes, output_path)

    assert result_path == output_path
    assert output_path.stat().st_size > 0

    width, height = REEL_ASPECT_RATIO
    video_stream = _probe(output_path, entry="stream=codec_name,width,height").splitlines()
    assert video_stream[0] == "h264"
    assert video_stream[1] == str(width)
    assert video_stream[2] == str(height)

    duration = float(_probe(output_path, entry="format=duration"))
    assert 5.5 < duration < 6.5  # matches the 6s synthetic voiceover, within encoding rounding


def test_assemble_reel_dry_run_writes_placeholder_without_ffmpeg(tmp_path, sample_country_fact_script, monkeypatch):
    import asma.video.assembler as assembler

    monkeypatch.setattr(assembler, "DRY_RUN", True)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ffmpeg should not run under DRY_RUN")))

    output_path = tmp_path / "output.mp4"
    result_path = assemble_reel([b"fake"], b"fake-audio", output_path)
    assert result_path == output_path
    assert output_path.exists()
