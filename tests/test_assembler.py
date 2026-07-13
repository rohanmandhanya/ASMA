from __future__ import annotations

import shutil
import subprocess

import pytest

from asma.config import REEL_ASPECT_RATIO
from asma.render.renderer import render_country_fact_cards
from asma.video.assembler import assemble_reel, select_background_bed

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _probe(path, *, entry: str, select_streams: str | None = None) -> str:
    args = ["ffprobe", "-v", "error"]
    if select_streams:
        args += ["-select_streams", select_streams]
    args += ["-show_entries", entry, "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
    result = subprocess.run(args, capture_output=True, text=True, check=True)
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


@pytest.mark.slow
def test_assemble_reel_crossfade_offset_math_holds_with_more_clips(tmp_path, monkeypatch):
    """Regression test for the chained-xfade offset formula
    (`i * (per_card_duration - _XFADE_DURATION)`) — a 3-4 clip case can
    accidentally pass even with a broken chain formula; this uses more
    clips specifically to stress the compounding offset."""
    import asma.video.assembler as assembler

    monkeypatch.setattr(assembler, "DRY_RUN", False)

    # 6 tiny solid-color PNGs stand in for real rendered cards.
    from PIL import Image
    import io

    card_images = []
    for color in [(200, 50, 50), (50, 200, 50), (50, 50, 200), (200, 200, 50), (200, 50, 200), (50, 200, 200)]:
        buf = io.BytesIO()
        Image.new("RGB", (1080, 1920), color).save(buf, format="PNG")
        card_images.append(buf.getvalue())

    voiceover_path = tmp_path / "voiceover.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=9", str(voiceover_path)],
        check=True,
    )

    output_path = tmp_path / "output.mp4"
    result_path = assembler.assemble_reel(card_images, voiceover_path.read_bytes(), output_path)

    assert result_path == output_path
    duration = float(_probe(output_path, entry="format=duration"))
    assert 8.5 < duration < 9.5  # matches the 9s voiceover despite 6 clips / 5 crossfades


@pytest.mark.slow
def test_duration_weights_give_text_heavy_cards_more_screen_time(tmp_path, monkeypatch):
    """Regression test for the actual bug reported: an even time split cut
    away from text-heavy beats before the fact landed. Two solid-color
    cards with very different weights (1 vs 3) — proves both that (a) the
    short card is long gone well before the long card's midpoint, and (b)
    the crossfade lands at the mathematically-predicted non-uniform offset,
    not just the equal-duration special case the other xfade test covers."""
    import io

    from PIL import Image

    import asma.video.assembler as assembler

    monkeypatch.setattr(assembler, "DRY_RUN", False)

    red, blue = (220, 30, 30), (30, 30, 220)
    card_images = []
    for color in (red, blue):
        buf = io.BytesIO()
        Image.new("RGB", (1080, 1920), color).save(buf, format="PNG")
        card_images.append(buf.getvalue())

    voiceover_path = tmp_path / "voiceover.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=8", str(voiceover_path)],
        check=True,
    )

    output_path = tmp_path / "output.mp4"
    assemble_reel(card_images, voiceover_path.read_bytes(), output_path, duration_weights=[1.0, 3.0])

    # target_with_overlap = 8 + 0.6*1 = 8.6; durations = [2.15, 6.45];
    # xfade offset = 2.15 - 1*0.6 = 1.55, crossfade window is [1.55, 2.15].
    def frame_at(t: float) -> tuple[int, int, int]:
        frame_path = tmp_path / f"frame_{t}.png"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t), "-i", str(output_path), "-frames:v", "1", str(frame_path)],
            check=True,
        )
        return Image.open(frame_path).convert("RGB").getpixel((540, 960))

    def close_to(actual: tuple[int, int, int], expected: tuple[int, int, int], tolerance: int = 10) -> bool:
        return all(abs(a - e) <= tolerance for a, e in zip(actual, expected))

    # H.264 quantization means even a solid-color frame isn't pixel-exact —
    # a small tolerance, not exact equality, is the honest check here.
    assert close_to(frame_at(0.5), red)  # well before the crossfade — pure red
    assert close_to(frame_at(5.0), blue)  # well after — pure blue, well past red's short 2.15s allotment

    blended = frame_at(1.85)  # crossfade midpoint
    assert not close_to(blended, red) and not close_to(blended, blue)
    assert abs(blended[0] - (red[0] + blue[0]) / 2) < 15
    assert abs(blended[2] - (red[2] + blue[2]) / 2) < 15


def test_select_background_bed_picks_one_of_the_bundled_files():
    # Exercises the real assets/audio/ directory — proves the bundled beds
    # this feature ships with actually exist and are picked up, not just
    # that the selection function's logic is sound in isolation.
    bed = select_background_bed()
    assert bed is not None
    assert bed.suffix == ".mp3"
    assert bed.exists()


def test_select_background_bed_returns_none_when_no_beds_present(tmp_path, monkeypatch):
    import asma.video.assembler as assembler

    monkeypatch.setattr(assembler, "_AUDIO_DIR", tmp_path)
    assert select_background_bed() is None


@pytest.mark.slow
def test_assemble_reel_mixes_background_bed_and_still_matches_voiceover_length(
    tmp_path, sample_country_fact_script, monkeypatch
):
    """The untested branch: assemble_reel() with a real background_audio_path
    should mix it under the voiceover (not replace it, not extend the video
    to the bed's own length) and still produce a spec-compliant file."""
    import asma.video.assembler as assembler

    monkeypatch.setattr(assembler, "DRY_RUN", False)

    cards = render_country_fact_cards(sample_country_fact_script)

    voiceover_path = tmp_path / "voiceover.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=6", str(voiceover_path)],
        check=True,
    )
    voiceover_bytes = voiceover_path.read_bytes()

    bed = select_background_bed()
    assert bed is not None  # the real bundled beds should be present in this repo checkout

    output_path = tmp_path / "output.mp4"
    result_path = assemble_reel(cards, voiceover_bytes, output_path, background_audio_path=bed)

    assert result_path == output_path
    audio_codec = _probe(output_path, entry="stream=codec_name", select_streams="a:0")
    assert audio_codec == "aac"

    duration = float(_probe(output_path, entry="format=duration"))
    assert 5.5 < duration < 6.5  # matches the 6s voiceover, not the (longer, looped) 24s bed
