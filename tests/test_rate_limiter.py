from __future__ import annotations

from datetime import datetime, timedelta, timezone

from asma.config import GRAPH_API_ROLLING_24H_POST_CAP, MIN_HOURS_BETWEEN_POSTS
from asma.models import ContentFormat, PostRecord
from asma.publish import rate_limiter
from asma.store.jsonl_store import append_jsonl


def _post(published_at: datetime, *, has_story: bool = False, dry_run: bool = False) -> PostRecord:
    return PostRecord(
        post_id=f"p-{published_at.isoformat()}",
        ig_media_id="m1",
        format=ContentFormat.QUIZ_CAROUSEL,
        caption="c",
        hashtags=["#a", "#b", "#c"],
        has_story=has_story,
        dry_run=dry_run,
        published_at=published_at,
    )


def test_allows_publish_with_no_history():
    allowed, reason = rate_limiter.can_publish_now()
    assert allowed
    assert reason == "ok"


def test_blocks_when_posted_too_recently():
    now = datetime.now(timezone.utc)
    append_jsonl("posts.jsonl", _post(now - timedelta(minutes=10)))
    allowed, reason = rate_limiter.can_publish_now(now)
    assert not allowed
    assert "minimum spacing" in reason


def test_allows_after_min_spacing_elapsed():
    now = datetime.now(timezone.utc)
    append_jsonl("posts.jsonl", _post(now - timedelta(hours=MIN_HOURS_BETWEEN_POSTS + 0.1)))
    allowed, _ = rate_limiter.can_publish_now(now)
    assert allowed


def test_dry_run_posts_dont_count_toward_limits():
    now = datetime.now(timezone.utc)
    for _ in range(30):
        append_jsonl("posts.jsonl", _post(now - timedelta(minutes=1), dry_run=True))
    allowed, _ = rate_limiter.can_publish_now(now)
    assert allowed


def test_blocks_at_rolling_24h_cap():
    now = datetime.now(timezone.utc)
    # Space posts far enough apart to only trip the cap, not the spacing rule.
    for i in range(GRAPH_API_ROLLING_24H_POST_CAP):
        append_jsonl("posts.jsonl", _post(now - timedelta(hours=23, minutes=i)))
    allowed, reason = rate_limiter.can_publish_now(now)
    assert not allowed
    assert "cap reached" in reason


def test_stories_count_toward_the_cap():
    now = datetime.now(timezone.utc)
    # Each post-with-story uses 2 slots; just over half the nominal post cap exhausts it.
    n = GRAPH_API_ROLLING_24H_POST_CAP // 2 + 1
    for i in range(n):
        append_jsonl("posts.jsonl", _post(now - timedelta(hours=23, minutes=i), has_story=True))
    allowed, reason = rate_limiter.can_publish_now(now)
    assert not allowed
    assert "cap reached" in reason


def test_posts_outside_24h_window_dont_count():
    now = datetime.now(timezone.utc)
    append_jsonl("posts.jsonl", _post(now - timedelta(hours=30)))
    allowed, _ = rate_limiter.can_publish_now(now)
    assert allowed
