"""Pulls Insights from the Graph API (account-level follower count, and
per-post engagement/video metrics) and appends them to metrics.jsonl. This
is the one place that reads live performance data — feedback.py and
growth_report.py both build on top of what's collected here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from asma.models import ContentFormat, MetricSnapshot, PostRecord
from asma.publish.graph_client import get_account_insights, get_media_insights
from asma.store.jsonl_store import append_jsonl, read_jsonl

_VIDEO_FORMATS = {ContentFormat.COUNTRY_FACT_REEL, ContentFormat.WINNER_ANNOUNCEMENT_REEL}


def collect_account_snapshot() -> MetricSnapshot:
    data = get_account_insights()
    snapshot = MetricSnapshot(follower_count=data.get("followers_count"))
    append_jsonl("metrics.jsonl", snapshot)
    return snapshot


def collect_post_metrics(post: PostRecord) -> MetricSnapshot | None:
    """Returns None (and appends nothing) for posts that never actually
    published — DRY_RUN records, or a post whose ig_media_id is otherwise
    missing. Insights on a brand-new account can also come back sparse
    (some fields are gated behind a minimum follower/view count) — treat
    missing fields as 'no signal yet', not an error."""
    if post.dry_run or post.ig_media_id is None:
        return None

    is_video = post.format in _VIDEO_FORMATS
    data = get_media_insights(post.ig_media_id, is_video=is_video)
    snapshot = MetricSnapshot(
        post_id=post.post_id,
        likes=data.get("likes"),
        comments=data.get("comments"),
        saves=data.get("saved"),
        shares=data.get("shares"),
        reach=data.get("reach"),
        impressions=data.get("impressions"),
        video_watch_time_seconds=data.get("video_view_total_time"),
        video_hold_rate_3s=data.get("ig_reels_avg_watch_time"),
    )
    append_jsonl("metrics.jsonl", snapshot)
    return snapshot


def collect_recent_posts_metrics(*, days: int = 14, now: datetime | None = None) -> list[MetricSnapshot]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    recent_posts = [p for p in read_jsonl("posts.jsonl", PostRecord) if p.published_at > cutoff and not p.dry_run]
    snapshots = []
    for post in recent_posts:
        snapshot = collect_post_metrics(post)
        if snapshot is not None:
            snapshots.append(snapshot)
    return snapshots


def latest_follower_count() -> int | None:
    snapshots = [s for s in read_jsonl("metrics.jsonl", MetricSnapshot) if s.follower_count is not None]
    if not snapshots:
        return None
    return max(snapshots, key=lambda s: s.snapshot_at).follower_count
