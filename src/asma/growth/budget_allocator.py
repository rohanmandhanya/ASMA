"""Answers 'should this scheduled-content.yml firing actually publish
anything, and should it attach a Story?' by combining the cadence ramp
(config.CADENCE_RAMP) with what's already gone out today. This is the
policy layer; publish/rate_limiter.py is the hard safety gate underneath
it — this module decides what SHOULD happen, rate_limiter enforces what's
ALLOWED to happen regardless.
"""

from __future__ import annotations

from datetime import datetime, timezone

from asma.config import CADENCE_RAMP, GRAPH_API_ROLLING_24H_POST_CAP
from asma.content.topic_selector import days_since_launch
from asma.publish.rate_limiter import can_publish_now, posts_published_today

# A Story accompanies every main post as long as there's headroom left in
# the day's Graph API budget after accounting for today's target post count
# (each with its own Story) plus a couple of slots held back for the weekly
# winner Reel / country-fact Reel. At the 5/day target this is never a real
# constraint (5 posts + 5 Stories = 10, well under 25) — this function is
# what keeps that true automatically if the target is ever raised later.
_RESERVED_SLOTS_FOR_OTHER_REELS = 3


def todays_target_post_count(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    day = days_since_launch(now)
    target = CADENCE_RAMP[0][1]
    for threshold_day, posts_per_day in CADENCE_RAMP:
        if day >= threshold_day:
            target = posts_per_day
    return target


def should_publish_now(now: datetime | None = None) -> tuple[bool, str]:
    now = now or datetime.now(timezone.utc)
    target = todays_target_post_count(now)
    already_today = len(posts_published_today(now))
    if already_today >= target:
        return False, f"today's target of {target} posts already met ({already_today} published)"
    return can_publish_now(now)


def should_attach_story(now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    today_posts = posts_published_today(now)
    slots_used_today = sum(1 + (1 if p.has_story else 0) for p in today_posts)
    target = todays_target_post_count(now)
    # Reserve enough room for the rest of today's planned posts (each +1 for
    # its own potential Story) plus a small buffer for other Reel formats.
    remaining_planned = max(0, target - len(today_posts))
    projected_max_usage = slots_used_today + (remaining_planned * 2) + _RESERVED_SLOTS_FOR_OTHER_REELS
    return projected_max_usage <= GRAPH_API_ROLLING_24H_POST_CAP
