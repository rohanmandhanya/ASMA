from __future__ import annotations

from asma.models import ContentFormat, PostRecord
from asma.store.jsonl_store import append_jsonl, read_jsonl, read_raw_json_state, write_raw_json_state


def test_read_jsonl_returns_empty_list_when_file_missing():
    assert read_jsonl("does_not_exist.jsonl", PostRecord) == []


def test_append_and_read_roundtrip():
    record = PostRecord(
        post_id="p1", ig_media_id="m1", format=ContentFormat.QUIZ_CAROUSEL, caption="c", hashtags=["#a", "#b", "#c"]
    )
    append_jsonl("posts.jsonl", record)
    append_jsonl("posts.jsonl", record.model_copy(update={"post_id": "p2"}))

    records = read_jsonl("posts.jsonl", PostRecord)
    assert [r.post_id for r in records] == ["p1", "p2"]


def test_raw_json_state_roundtrip():
    assert read_raw_json_state("state.json", default={"x": 1}) == {"x": 1}
    write_raw_json_state("state.json", {"x": 2})
    assert read_raw_json_state("state.json", default={"x": 1}) == {"x": 2}
