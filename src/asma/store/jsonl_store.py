"""Thin persistence layer over data/*.jsonl (append-only logs) and
data/*.json (small mutable state files). Every workflow run reads state,
does its work, and writes state back — the calling workflow is responsible
for `git add data/ && git commit && git push` (see .github/workflows/).

No database. At this scale (a handful of posts/day) plain files committed
to git are simpler, free, and give a versioned audit trail for free.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

DATA_DIR = Path(__file__).resolve().parents[3] / "data"

M = TypeVar("M", bound=BaseModel)


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def append_jsonl(filename: str, record: BaseModel) -> None:
    """Append one record's JSON representation as a new line."""
    _ensure_data_dir()
    path = DATA_DIR / filename
    with path.open("a", encoding="utf-8") as f:
        f.write(record.model_dump_json() + "\n")


def read_jsonl(filename: str, model: type[M]) -> list[M]:
    """Read all records from a JSONL file, oldest first. Empty list if the
    file doesn't exist yet (first run)."""
    path = DATA_DIR / filename
    if not path.exists():
        return []
    records: list[M] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(model.model_validate_json(line))
    return records


def read_json_state(filename: str, model: type[M], default_factory) -> M:
    """Read a small mutable JSON state file, or construct a default if this
    is the first run and the file doesn't exist yet."""
    path = DATA_DIR / filename
    if not path.exists():
        return default_factory()
    return model.model_validate_json(path.read_text(encoding="utf-8"))


def write_json_state(filename: str, state: BaseModel) -> None:
    _ensure_data_dir()
    path = DATA_DIR / filename
    path.write_text(state.model_dump_json(indent=2), encoding="utf-8")


def read_raw_json_state(filename: str, default: dict) -> dict:
    """For state shapes that aren't a single Pydantic model (e.g. the
    per-topic dict in topics_state.json) — read as a plain dict."""
    path = DATA_DIR / filename
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_raw_json_state(filename: str, state: dict) -> None:
    _ensure_data_dir()
    path = DATA_DIR / filename
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
