"""Tiny helper so trend_research.py's web-search pass runs periodically
(weekly), not on every scheduled-content.yml firing — the research itself
is cheap, but there's no reason to burn a search call multiple times a day
when the underlying trends don't move that fast.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from asma.store.jsonl_store import read_raw_json_state, write_raw_json_state

_STATE_FILE = "trend_research_state.json"
_INTERVAL_DAYS = 7


def is_trend_research_due(now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    state = read_raw_json_state(_STATE_FILE, default={})
    last_run = state.get("last_run_at")
    if last_run is None:
        return True
    return (now - datetime.fromisoformat(last_run)) >= timedelta(days=_INTERVAL_DAYS)


def mark_trend_research_ran(now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    write_raw_json_state(_STATE_FILE, {"last_run_at": now.isoformat()})
