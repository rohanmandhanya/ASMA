"""Turns metrics.jsonl into the two things generator.py actually consumes:
an EMA score update per topic/hook (feeding topic_selector's bandit), and a
short natural-language performance summary handed to Claude so the actual
writing is informed by real data, not just the mechanical picker. Simple,
nameable heuristics — not ML.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from asma.content.topic_selector import update_ema_score
from asma.models import ContentFormat, MetricSnapshot, PostRecord
from asma.store.jsonl_store import read_jsonl

_VIDEO_FORMATS = {ContentFormat.COUNTRY_FACT_REEL, ContentFormat.WINNER_ANNOUNCEMENT_REEL}


def compute_engagement_score(post: PostRecord, snapshot: MetricSnapshot) -> float:
    """Returns a score roughly in [0, 1]. Carousels: saves/shares weighted
    highest (the strongest 'useful, worth returning to' signal for
    tip/trivia content). Reels: 3-second hold rate weighted highest (the
    strongest discovery signal per the 2026 algorithm research)."""
    if post.format in _VIDEO_FORMATS:
        if snapshot.video_hold_rate_3s is not None:
            return max(0.0, min(1.0, snapshot.video_hold_rate_3s))
        return 0.5  # no signal yet — neutral, not punishing

    reach = snapshot.reach or 0
    if reach <= 0:
        return 0.5  # sparse Insights on a brand-new account — degrade gracefully, don't crash or punish
    weighted = (snapshot.saves or 0) * 3 + (snapshot.shares or 0) * 3 + (snapshot.comments or 0) * 2 + (snapshot.likes or 0)
    return max(0.0, min(1.0, weighted / reach))


def update_topic_and_hook_scores(post: PostRecord, snapshot: MetricSnapshot) -> None:
    score = compute_engagement_score(post, snapshot)
    if post.topic_id:
        update_ema_score("topics", post.topic_id, score)
    if post.hook:
        update_ema_score("hooks", post.hook.value, score)


def build_performance_summary(*, days: int = 14, now: datetime | None = None) -> str:
    """Short text summary fed into generator.py's context — e.g. 'post
    about X did well, high saves; post about Y underperformed'."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)

    posts = {p.post_id: p for p in read_jsonl("posts.jsonl", PostRecord) if p.published_at > cutoff}
    if not posts:
        return "No recent post performance data yet — this may be an early run."

    scores_by_post: dict[str, list[float]] = defaultdict(list)
    for snap in read_jsonl("metrics.jsonl", MetricSnapshot):
        if snap.post_id and snap.post_id in posts:
            scores_by_post[snap.post_id].append(compute_engagement_score(posts[snap.post_id], snap))

    ranked = sorted(
        ((post_id, max(scores)) for post_id, scores in scores_by_post.items() if scores),
        key=lambda pair: pair[1],
        reverse=True,
    )
    if not ranked:
        return "Recent posts have no Insights data yet — too early to have signal."

    lines = []
    for post_id, score in ranked[:3]:
        post = posts[post_id]
        lines.append(f"- {post.topic_id or post.format.value} ({post.country or 'n/a'}): score {score:.2f}, hook={post.hook.value if post.hook else 'n/a'}")
    if len(ranked) > 3:
        for post_id, score in ranked[-2:]:
            post = posts[post_id]
            lines.append(f"- (underperformed) {post.topic_id or post.format.value}: score {score:.2f}")

    return "Recent performance (higher score = more saves/shares or better video hold rate):\n" + "\n".join(lines)
