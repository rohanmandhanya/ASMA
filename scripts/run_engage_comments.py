#!/usr/bin/env python3
"""Processes new comments on recently-published quiz posts: judges answers,
tallies the leaderboard, and replies. Run by engage-comments.yml."""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import anthropic  # noqa: E402

from asma.config import ANTHROPIC_API_KEY  # noqa: E402
from asma.engagement.answer_tracker import process_comments_for_post  # noqa: E402
from asma.models import ContentFormat, PostRecord  # noqa: E402
from asma.store.jsonl_store import read_jsonl  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("run_engage_comments")

# Comments matter most in the day or so after a quiz posts — no need to
# keep polling a week-old post for new guesses.
_LOOKBACK_DAYS = 7


def main() -> int:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else anthropic.Anthropic()

    cutoff = datetime.now(timezone.utc) - timedelta(days=_LOOKBACK_DAYS)
    quiz_posts = [
        p
        for p in read_jsonl("posts.jsonl", PostRecord)
        if p.format == ContentFormat.QUIZ_CAROUSEL and p.published_at > cutoff and not p.dry_run
    ]

    total_new = 0
    for post in quiz_posts:
        records = process_comments_for_post(client, post)
        total_new += len(records)

    logger.info("processed %d new comments across %d recent quiz posts", total_new, len(quiz_posts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
