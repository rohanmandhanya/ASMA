"""Simple, nameable heuristic bandit over TOPIC_POOL and HookStyle — not ML.
Excludes anything used in the last TOPIC_NO_REPEAT_DAYS days, then either
explores an under-used topic or exploits the best-scoring eligible one via
softmax sampling. See growth/feedback.py for how ema_score gets updated
from real engagement data.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

from asma.config import TOPIC_EXPLORATION_RATE, TOPIC_NO_REPEAT_DAYS, TOPIC_POOL, Topic
from asma.models import HookStyle
from asma.store.jsonl_store import read_raw_json_state, write_raw_json_state

STATE_FILE = "topics_state.json"
_DEFAULT_SCORE = 0.5  # neutral prior for a topic/hook never used yet


def _load_state() -> dict:
    return read_raw_json_state(
        STATE_FILE,
        default={"_meta": {}, "topics": {}, "countries": {}, "hooks": {}},
    )


def _save_state(state: dict) -> None:
    write_raw_json_state(STATE_FILE, state)


def mark_campaign_launched_if_needed(now: datetime | None = None) -> datetime:
    """Idempotent: records the first time scheduled-content.yml actually ran.
    The cadence ramp in config.CADENCE_RAMP counts days from here, not from
    wall-clock 'today' — a paused rollout doesn't silently skip ramp steps."""
    now = now or datetime.now(timezone.utc)
    state = _load_state()
    if "launched_at" not in state["_meta"]:
        state["_meta"]["launched_at"] = now.isoformat()
        _save_state(state)
        return now
    return datetime.fromisoformat(state["_meta"]["launched_at"])


def days_since_launch(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    launched_at = mark_campaign_launched_if_needed(now)
    return max(0, (now - launched_at).days)


def _softmax_sample(items: list, scores: list[float]) -> object:
    max_score = max(scores)
    weights = [math.exp(s - max_score) for s in scores]  # subtract max for numerical stability
    return random.choices(items, weights=weights, k=1)[0]


def _eligible_topics(state: dict, now: datetime) -> list[Topic]:
    cutoff = now - timedelta(days=TOPIC_NO_REPEAT_DAYS)
    eligible = []
    for topic in TOPIC_POOL:
        entry = state["topics"].get(topic.topic_id)
        if entry and entry.get("last_used_at"):
            last_used = datetime.fromisoformat(entry["last_used_at"])
            if last_used > cutoff:
                continue
        eligible.append(topic)
    # If the pool is ever fully exhausted (shouldn't happen at TOPIC_POOL's
    # size and the configured cadence), fall back to the full pool rather
    # than crashing the pipeline.
    return eligible or list(TOPIC_POOL)


def select_topic(now: datetime | None = None) -> Topic:
    now = now or datetime.now(timezone.utc)
    state = _load_state()
    eligible = _eligible_topics(state, now)

    times_used = [state["topics"].get(t.topic_id, {}).get("times_used", 0) for t in eligible]
    min_uses = min(times_used)
    under_used = [t for t, n in zip(eligible, times_used) if n == min_uses]

    if random.random() < TOPIC_EXPLORATION_RATE or min_uses == 0:
        return random.choice(under_used)

    scores = [state["topics"].get(t.topic_id, {}).get("ema_score", _DEFAULT_SCORE) for t in eligible]
    return _softmax_sample(eligible, scores)


def select_hook(now: datetime | None = None) -> HookStyle:
    state = _load_state()
    hooks = list(HookStyle)
    if random.random() < TOPIC_EXPLORATION_RATE:
        return random.choice(hooks)
    scores = [state["hooks"].get(h.value, {}).get("ema_score", _DEFAULT_SCORE) for h in hooks]
    return _softmax_sample(hooks, scores)


def select_country_fact_country(now: datetime | None = None) -> str:
    """For the recurring country-fact Reel: rotate across TOPIC_POOL's
    countries directly (a lighter draw than the full topic bandit, since
    this format doesn't need a specific pre-written topic — just a country
    seed for Claude to pick a fact from)."""
    now = now or datetime.now(timezone.utc)
    state = _load_state()
    cutoff = now - timedelta(days=TOPIC_NO_REPEAT_DAYS)
    all_countries = sorted({t.country for t in TOPIC_POOL})
    eligible = []
    for country in all_countries:
        entry = state["countries"].get(country)
        if entry and entry.get("last_used_at"):
            last_used = datetime.fromisoformat(entry["last_used_at"])
            if last_used > cutoff:
                continue
        eligible.append(country)
    return random.choice(eligible or all_countries)


def record_topic_used(topic: Topic, hook: HookStyle, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    state = _load_state()
    topic_entry = state["topics"].setdefault(topic.topic_id, {"times_used": 0, "ema_score": _DEFAULT_SCORE})
    topic_entry["times_used"] += 1
    topic_entry["last_used_at"] = now.isoformat()
    state["countries"].setdefault(topic.country, {})["last_used_at"] = now.isoformat()
    state["hooks"].setdefault(hook.value, {"ema_score": _DEFAULT_SCORE})["last_used_at"] = now.isoformat()
    _save_state(state)


def record_country_fact_used(country: str, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    state = _load_state()
    state["countries"].setdefault(country, {})["last_used_at"] = now.isoformat()
    _save_state(state)


def update_ema_score(kind: str, key: str, latest_score: float, *, alpha: float = 0.3) -> None:
    """kind is 'topics' or 'hooks'. Called from growth/feedback.py once
    real engagement metrics are in for a post."""
    state = _load_state()
    entry = state[kind].setdefault(key, {"ema_score": _DEFAULT_SCORE})
    old = entry.get("ema_score", _DEFAULT_SCORE)
    entry["ema_score"] = (1 - alpha) * old + alpha * latest_score
    _save_state(state)
