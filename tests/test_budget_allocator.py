from __future__ import annotations

from datetime import datetime, timedelta, timezone

from asma.config import CADENCE_RAMP, TARGET_POSTS_PER_DAY
from asma.content import topic_selector
from asma.growth import budget_allocator
from asma.models import ContentFormat, PostRecord
from asma.store.jsonl_store import append_jsonl


def test_target_post_count_starts_low_and_ramps():
    now = datetime.now(timezone.utc)
    topic_selector.mark_campaign_launched_if_needed(now)  # day 0

    assert budget_allocator.todays_target_post_count(now) == CADENCE_RAMP[0][1]

    far_future = now + timedelta(days=30)
    assert budget_allocator.todays_target_post_count(far_future) == TARGET_POSTS_PER_DAY


def test_should_publish_now_respects_daily_target():
    now = datetime.now(timezone.utc)
    topic_selector.mark_campaign_launched_if_needed(now)  # day 0 -> target is 1/day

    allowed, _ = budget_allocator.should_publish_now(now)
    assert allowed

    append_jsonl(
        "posts.jsonl",
        PostRecord(
            post_id="p1",
            ig_media_id="m1",
            format=ContentFormat.QUIZ_CAROUSEL,
            caption="c",
            hashtags=["#a", "#b", "#c"],
            published_at=now - timedelta(minutes=1),
            dry_run=False,
        ),
    )
    allowed, reason = budget_allocator.should_publish_now(now)
    assert not allowed
    assert "target" in reason


def test_should_attach_story_true_when_headroom_available():
    now = datetime.now(timezone.utc)
    topic_selector.mark_campaign_launched_if_needed(now)
    assert budget_allocator.should_attach_story(now)
