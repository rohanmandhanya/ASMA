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
import random
import subprocess
import tempfile
from pathlib import Path

from asma.config import DRY_RUN, REEL_ASPECT_RATIO, REEL_MIN_SECONDS

logger = logging.getLogger(__name__)

_FPS = 25
_ZOOM_PER_FRAME = 0.0012
_ZOOM_MAX = 1.3
_BACKGROUND_BED_VOLUME = 0.12  # mixed low under the voiceover, never competing with it
_XFADE_DURATION = 0.6  # seconds — a deliberate, unhurried crossfade, not a quick blend

# Bundled ambient background beds: originally synthesized (ffmpeg sine-tone
# layering), never a licensed/sampled track — same "no reproducing someone
# else's copyrighted work" principle the rest of the pipeline follows for
# visuals. assemble_reel() loops whichever one is picked to match the
# voiceover's length, so these only need to be a short, seamless-at-silence
# loop (each fades to ~silence at both ends), not full-length.
_AUDIO_DIR = (Path(__file__).resolve().parents[3] / "assets" / "audio").resolve()


def select_background_bed() -> Path | None:
    """Picks one of the bundled beds at random for variety across posts, or
    None if assets/audio/ is empty — assemble_reel() already treats a
    missing background_audio_path as "voiceover only", so this degrades
    gracefully with zero beds present too, same as it did before this
    feature existed."""
    beds = sorted(_AUDIO_DIR.glob("*.mp3"))
    return random.choice(beds) if beds else None


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


def _concat_with_crossfade(clip_paths: list[Path], durations: list[float], output_path: Path) -> None:
    """Chains Ken Burns clips with a short xfade crossfade instead of a hard
    cut. ffmpeg's concat demuxer (`-c copy`, the old approach here) can only
    do hard cuts — a real crossfade needs re-encoding through a chained
    `xfade` filtergraph instead, one xfade per clip boundary.

    Clips are NOT equal length (each card gets time proportional to how much
    of the narration it represents — see assemble_reel), so the offset for
    the i-th join is the cumulative duration of everything joined so far,
    minus the crossfade-widths already "eaten" by prior joins: `offset_i =
    sum(durations[:i]) - i * _XFADE_DURATION`. (ffmpeg's xfade offset is
    relative to the start of the first input of *that* xfade call, which is
    itself the result of all prior joins, so this compounds across the
    chain — the equal-duration case is just this formula's special case.)"""
    if len(clip_paths) == 1:
        _run_ffmpeg(["-i", str(clip_paths[0]), "-c", "copy", str(output_path)])
        return

    inputs: list[str] = []
    for p in clip_paths:
        inputs += ["-i", str(p)]

    filter_parts = []
    prev_label = "0:v"
    cumulative = durations[0]
    for i in range(1, len(clip_paths)):
        offset = cumulative - i * _XFADE_DURATION
        out_label = f"v{i}" if i < len(clip_paths) - 1 else "vout"
        filter_parts.append(
            f"[{prev_label}][{i}:v]xfade=transition=fade:duration={_XFADE_DURATION}:offset={offset:.3f}[{out_label}]"
        )
        prev_label = out_label
        cumulative += durations[i]

    _run_ffmpeg(
        [
            *inputs,
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "[vout]",
            "-r",
            str(_FPS),
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            str(output_path),
        ]
    )


def assemble_reel(
    card_images: list[bytes],
    voiceover_mp3: bytes,
    output_path: Path,
    *,
    background_audio_path: Path | None = None,
    duration_weights: list[float] | None = None,
) -> Path:
    """Returns output_path. In DRY_RUN, writes a zero-byte placeholder and
    never invokes ffmpeg at all — every higher-level caller still gets a
    real Path back to log/reference, just no actual encode.

    `duration_weights` (one per card, e.g. each beat's character count):
    gives cards proportionally more on-screen time the more there is to say
    about them, instead of splitting the narration's total length evenly
    across every card regardless of how much of it that card represents —
    an even split under-times text-heavy cards (cut away before the fact
    lands) and over-times short ones. Omit for an even split."""
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

        n = len(card_images)
        weights = duration_weights if duration_weights else [1.0] * n
        if len(weights) != n:
            raise ValueError(f"duration_weights has {len(weights)} entries but there are {n} cards")
        weight_sum = sum(weights)

        # Each of the (n-1) crossfades overlaps two clips by _XFADE_DURATION,
        # so clips need to run a bit longer than their raw proportional share
        # — this keeps the *post-crossfade* total matching total_duration
        # exactly, rather than coming up short by n-1 crossfade-widths.
        overlap_total = _XFADE_DURATION * (n - 1) if n > 1 else 0
        target_with_overlap = total_duration + overlap_total
        card_durations = [target_with_overlap * (w / weight_sum) for w in weights]

        clip_paths: list[Path] = []
        for i, img_bytes in enumerate(card_images):
            img_path = tmp / f"card_{i:02d}.png"
            img_path.write_bytes(img_bytes)
            clip_path = tmp / f"clip_{i:02d}.mp4"
            _make_ken_burns_clip(img_path, clip_path, duration_seconds=card_durations[i])
            clip_paths.append(clip_path)

        concatenated = tmp / "concatenated.mp4"
        _concat_with_crossfade(clip_paths, card_durations, concatenated)

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
