"""Daily follower-count/delta/leaderboard digest, posted as a comment on a
single pinned 'Growth Tracker' GitHub Issue — reusing GitHub's own
notification system instead of adding a new secret or service. See
milestone_notifier.py for the separate one-time 100-follower email.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from asma.config import DRY_RUN, GITHUB_REPO, GITHUB_TOKEN
from asma.engagement.answer_tracker import current_leaderboard
from asma.models import MetricSnapshot
from asma.publish.rate_limiter import posts_published_today
from asma.store.jsonl_store import read_jsonl

logger = logging.getLogger(__name__)

_TRACKER_TITLE = "📈 Growth Tracker"
_TRACKER_LABEL = "growth-tracker"


def _headers() -> dict:
    return {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}


def _find_or_create_tracker_issue() -> int:
    base = f"https://api.github.com/repos/{GITHUB_REPO}"
    resp = requests.get(f"{base}/issues", headers=_headers(), params={"state": "open", "labels": _TRACKER_LABEL}, timeout=15)
    resp.raise_for_status()
    matches = [i for i in resp.json() if i["title"] == _TRACKER_TITLE]
    if matches:
        return matches[0]["number"]

    resp = requests.post(
        f"{base}/issues",
        headers=_headers(),
        json={
            "title": _TRACKER_TITLE,
            "body": "Automated daily growth digest. Comments are appended here by growth-report.yml — nothing to do.",
            "labels": [_TRACKER_LABEL],
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["number"]


def _follower_delta(current: int | None) -> str:
    if current is None:
        return "n/a (no Insights data yet)"
    snapshots = sorted(
        (s for s in read_jsonl("metrics.jsonl", MetricSnapshot) if s.follower_count is not None),
        key=lambda s: s.snapshot_at,
    )
    if len(snapshots) < 2:
        return "n/a (first snapshot)"
    previous = snapshots[-2].follower_count
    delta = current - previous
    return f"{'+' if delta >= 0 else ''}{delta} since last check"


def build_digest_text(follower_count: int | None) -> str:
    now = datetime.now(timezone.utc)
    today_posts = posts_published_today(now)
    leaderboard = current_leaderboard()
    leader_line = "no correct answers yet this week"
    if leaderboard:
        top_user, top_count = max(leaderboard.items(), key=lambda kv: kv[1])
        leader_line = f"@{top_user} leading with {top_count} correct answers"

    lines = [
        f"**{now.strftime('%Y-%m-%d')}**",
        f"- Followers: {follower_count if follower_count is not None else 'n/a'} ({_follower_delta(follower_count)})",
        f"- Posts published in the last 24h: {len(today_posts)}",
        f"- Weekly leaderboard: {leader_line}",
    ]
    return "\n".join(lines)


def post_daily_digest(follower_count: int | None) -> None:
    digest = build_digest_text(follower_count)
    if DRY_RUN:
        logger.info("[DRY_RUN] growth_report: would post digest:\n%s", digest)
        return
    issue_number = _find_or_create_tracker_issue()
    base = f"https://api.github.com/repos/{GITHUB_REPO}"
    resp = requests.post(f"{base}/issues/{issue_number}/comments", headers=_headers(), json={"body": digest}, timeout=15)
    resp.raise_for_status()
