from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from asma.content import topic_selector
from asma.config import TOPIC_POOL
from asma.models import HookStyle


def test_select_topic_returns_pool_member():
    topic = topic_selector.select_topic()
    assert topic in TOPIC_POOL


def test_record_and_no_repeat_within_window():
    now = datetime.now(timezone.utc)
    topic = TOPIC_POOL[0]
    topic_selector.record_topic_used(topic, HookStyle.BOLD_CLAIM, now=now)

    # Immediately after, this topic should not be eligible again within the window.
    for _ in range(20):
        picked = topic_selector.select_topic(now=now + timedelta(hours=1))
        assert picked.topic_id != topic.topic_id


def test_topic_eligible_again_after_no_repeat_window():
    from asma.config import TOPIC_NO_REPEAT_DAYS

    now = datetime.now(timezone.utc)
    topic = TOPIC_POOL[0]
    topic_selector.record_topic_used(topic, HookStyle.BOLD_CLAIM, now=now)

    later = now + timedelta(days=TOPIC_NO_REPEAT_DAYS + 1)
    # Mark every other topic as recently used so the pool is forced down to
    # just this one, proving it becomes eligible again after the window.
    for other in TOPIC_POOL:
        if other.topic_id != topic.topic_id:
            topic_selector.record_topic_used(other, HookStyle.BOLD_CLAIM, now=later)

    picked = topic_selector.select_topic(now=later)
    assert picked.topic_id == topic.topic_id


def test_ema_score_biases_selection_toward_higher_scoring_topics():
    now = datetime.now(timezone.utc)
    good_topic, bad_topic = TOPIC_POOL[0], TOPIC_POOL[1]

    # Give both some usage history (so neither counts as "under-used" and
    # forces pure exploration), then push their EMA scores far apart.
    for t in (good_topic, bad_topic):
        topic_selector.record_topic_used(t, HookStyle.BOLD_CLAIM, now=now - timedelta(days=20))
    topic_selector.update_ema_score("topics", good_topic.topic_id, 1.0, alpha=1.0)
    topic_selector.update_ema_score("topics", bad_topic.topic_id, 0.0, alpha=1.0)

    # Force every OTHER topic out of eligibility so selection is a contest
    # strictly between good_topic and bad_topic.
    for other in TOPIC_POOL:
        if other.topic_id not in (good_topic.topic_id, bad_topic.topic_id):
            topic_selector.record_topic_used(other, HookStyle.BOLD_CLAIM, now=now)

    picks = Counter(
        topic_selector.select_topic(now=now).topic_id
        for _ in range(300)
    )
    # With exploration at 30%, the higher-scoring topic should still win decisively more often.
    assert picks[good_topic.topic_id] > picks[bad_topic.topic_id]


def test_days_since_launch_is_stable_across_calls():
    now = datetime.now(timezone.utc)
    first = topic_selector.days_since_launch(now)
    later = topic_selector.days_since_launch(now + timedelta(days=3))
    assert later - first == 3
