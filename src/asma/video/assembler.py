"""Card PNGs + voiceover MP3 -> a Reels-spec MP4, via ffmpeg subprocess
calls. No stock footage, no generative-video API — each card gets a subtle
Ken Burns zoom (via ffmpeg's zoompan filter) so it reads as motion rather
than a static slideshow, captions are burned in via the card text itself
(rendered into the image, not a separate subtitle track), and the
voiceover is optionally mixed with a low-volume bundled background bed.

ffmpeg ships preinstalled on GitHub's Ubuntu runners — no extra setup step
in CI for this.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

from asma.config import DRY_RUN, REEL_ASPECT_RATIO, REEL_MIN_SECONDS

logger = logging.getLogger(__name__)

_FPS = 25
_ZOOM_PER_FRAME = 0.0012
_ZOOM_MAX = 1.3
_BACKGROUND_BED_VOLUME = 0.12  # mixed low under the voiceover, never competing with it


def _run_ffmpeg(args: list[str]) -> None:
    result = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", *args],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr.strip()[-2000:]}")


def _probe_duration_seconds(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(f"ffprobe failed to read duration for {path}: {result.stderr}")
    return float(result.stdout.strip())


def _make_ken_burns_clip(image_path: Path, out_path: Path, *, duration_seconds: float) -> None:
    width, height = REEL_ASPECT_RATIO
    _run_ffmpeg(
        [
            "-loop", "1",
            "-framerate", str(_FPS),
            "-i", str(image_path),
            "-vf",
            f"scale={width * 4}:-1,"
            f"zoompan=z='min(zoom+{_ZOOM_PER_FRAME},{_ZOOM_MAX})':d=1:s={width}x{height}:fps={_FPS}",
            "-t", f"{duration_seconds:.3f}",
            "-pix_fmt", "yuv420p",
            "-c:v", "libx264",
            str(out_path),
        ]
    )


def assemble_reel(
    card_images: list[bytes],
    voiceover_mp3: bytes,
    output_path: Path,
    *,
    background_audio_path: Path | None = None,
) -> Path:
    """Returns output_path. In DRY_RUN, writes a zero-byte placeholder and
    never invokes ffmpeg at all — every higher-level caller still gets a
    real Path back to log/reference, just no actual encode."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if DRY_RUN:
        logger.info("[DRY_RUN] assembler: skipping real ffmpeg encode (%d cards)", len(card_images))
        output_path.write_bytes(b"")
        return output_path

    if not card_images:
        raise ValueError("assemble_reel requires at least one card image")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        voiceover_path = tmp / "voiceover.mp3"
        voiceover_path.write_bytes(voiceover_mp3)
        voiceover_duration = _probe_duration_seconds(voiceover_path)
        total_duration = max(voiceover_duration, REEL_MIN_SECONDS)
        per_card_duration = total_duration / len(card_images)

        clip_paths: list[Path] = []
        for i, img_bytes in enumerate(card_images):
            img_path = tmp / f"card_{i:02d}.png"
            img_path.write_bytes(img_bytes)
            clip_path = tmp / f"clip_{i:02d}.mp4"
            _make_ken_burns_clip(img_path, clip_path, duration_seconds=per_card_duration)
            clip_paths.append(clip_path)

        concat_list = tmp / "concat.txt"
        concat_list.write_text("\n".join(f"file '{p}'" for p in clip_paths) + "\n")
        concatenated = tmp / "concatenated.mp4"
        _run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(concatenated)])

        if background_audio_path and background_audio_path.exists():
            _run_ffmpeg(
                [
                    "-i", str(concatenated),
                    "-i", str(voiceover_path),
                    "-i", str(background_audio_path),
                    "-filter_complex",
                    f"[2:a]volume={_BACKGROUND_BED_VOLUME},aloop=loop=-1:size=2e9[bg];"
                    f"[1:a][bg]amix=inputs=2:duration=first:dropout_transition=0[aout]",
                    "-map", "0:v",
                    "-map", "[aout]",
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac",
                    "-ar", "48000",
                    "-shortest",
                    str(output_path),
                ]
            )
        else:
            _run_ffmpeg(
                [
                    "-i", str(concatenated),
                    "-i", str(voiceover_path),
                    "-map", "0:v",
                    "-map", "1:a",
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac",
                    "-ar", "48000",
                    "-shortest",
                    str(output_path),
                ]
            )

    return output_path
