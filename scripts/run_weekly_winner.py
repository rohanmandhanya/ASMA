#!/usr/bin/env python3
"""Reads the weekly leaderboard, generates + publishes the winner Reel, and
resets the tally. Run by weekly-winner.yml."""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import anthropic  # noqa: E402

from asma.config import ANTHROPIC_API_KEY, DRY_RUN  # noqa: E402
from asma.content import generator, guardrails  # noqa: E402
from asma.engagement.answer_tracker import current_leaderboard, reset_leaderboard  # noqa: E402
from asma.models import ContentFormat, PostRecord  # noqa: E402
from asma.publish import graph_client, media_host  # noqa: E402
from asma.render.renderer import render_winner_announcement_cards  # noqa: E402
from asma.store.jsonl_store import append_jsonl  # noqa: E402
from asma.video.assembler import assemble_reel  # noqa: E402
from asma.video.tts import synthesize_voiceover  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("run_weekly_winner")


def main() -> int:
    leaderboard = current_leaderboard()
    if not leaderboard:
        logger.info("no correct answers recorded this week — skipping the winner Reel")
        return 0

    winner_username, correct_count = max(leaderboard.items(), key=lambda kv: kv[1])
    week_of = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else anthropic.Anthropic()

    try:
        script = generator.generate_winner_announcement(
            client, winner_username=winner_username, correct_answer_count=correct_count, week_of=week_of
        )
    except generator.GenerationError as exc:
        logger.error("winner announcement generation failed/refused, aborting: %s", exc)
        return 1

    result = guardrails.validate_winner_announcement(script)
    if not result.passed:
        logger.error("winner announcement failed guardrails, aborting: %s", result.issues)
        return 1

    cards = render_winner_announcement_cards(script)
    voiceover = synthesize_voiceover(script.voiceover_script)
    video_path = assemble_reel(cards, voiceover, Path("assets/rendered") / "winner.mp4")
    video_url = media_host.upload_media(video_path.read_bytes(), extension=".mp4")

    container_id = graph_client.create_video_container(video_url, caption=script.caption, media_type="REELS")
    graph_client.poll_container_until_finished(container_id, is_video=True)
    media_id = graph_client.publish_container(container_id)

    record = PostRecord(
        post_id=f"winner-{week_of}",
        ig_media_id=media_id,
        format=ContentFormat.WINNER_ANNOUNCEMENT_REEL,
        caption=script.caption,
        hashtags=script.hashtags,
        dry_run=DRY_RUN,
    )
    append_jsonl("posts.jsonl", record)
    logger.info("published winner announcement for @%s (%d correct answers)", winner_username, correct_count)

    reset_leaderboard()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
