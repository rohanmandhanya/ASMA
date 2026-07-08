"""Local, code-enforced rate limiting — independent of trusting Meta's own
enforcement. This is deliberate belt-and-suspenders: even if a workflow
somehow fires twice, or the day's budget_allocator logic has a bug, this
is the last gate before anything actually publishes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from asma.config import GRAPH_API_ROLLING_24H_POST_CAP, MIN_HOURS_BETWEEN_POSTS
from asma.models import ContentFormat, PostRecord
from asma.store.jsonl_store import read_jsonl


def can_publish_now(now: datetime | None = None) -> tuple[bool, str]:
    """Hard gate checked immediately before every real (non-DRY_RUN)
    publish call in graph_client.py. Returns (allowed, reason)."""
    now = now or datetime.now(timezone.utc)
    posts = [p for p in read_jsonl("posts.jsonl", PostRecord) if not p.dry_run]
    cutoff = now - timedelta(hours=24)
    recent = [p for p in posts if p.published_at > cutoff]

    # Stories count toward the same Graph API bucket as carousels/Reels.
    slots_used = sum(1 + (1 if p.has_story else 0) for p in recent)
    if slots_used >= GRAPH_API_ROLLING_24H_POST_CAP:
        return False, f"rolling-24h Graph API cap reached ({slots_used}/{GRAPH_API_ROLLING_24H_POST_CAP})"

    if recent:
        most_recent = max(p.published_at for p in recent)
        gap_hours = (now - most_recent).total_seconds() / 3600
        if gap_hours < MIN_HOURS_BETWEEN_POSTS:
            return False, f"last post was {gap_hours:.1f}h ago, minimum spacing is {MIN_HOURS_BETWEEN_POSTS}h"

    return True, "ok"


def posts_published_today(now: datetime | None = None) -> list[PostRecord]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    return [
        p
        for p in read_jsonl("posts.jsonl", PostRecord)
        if not p.dry_run and p.published_at > cutoff
    ]


def count_by_format(posts: list[PostRecord], fmt: ContentFormat) -> int:
    return sum(1 for p in posts if p.format == fmt)
