"""Orchestrates engage-comments.yml: find new comments on the live quiz
post, judge each against the known correct answer via a Haiku
classification call (robust to spelling/phrasing variance — never brittle
string matching), tally correct answers per commenter for the weekly
leaderboard, and generate+post a reply for each. Everything gets appended
to comments.jsonl exactly once per comment, whether or not the reply
generation succeeded.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import anthropic

from asma.config import ENGAGE_REPLY_CAP_PER_RUN
from asma.content.generator import GenerationError, judge_comment_answer
from asma.engagement.comment_responder import reply_to_judged_comment
from asma.models import CommentRecord, PostRecord
from asma.publish.graph_client import list_comments
from asma.store.jsonl_store import append_jsonl, read_jsonl, read_raw_json_state, write_raw_json_state

logger = logging.getLogger(__name__)

LEADERBOARD_STATE_FILE = "leaderboard_state.json"


def _load_leaderboard() -> dict:
    return read_raw_json_state(LEADERBOARD_STATE_FILE, default={"entries": {}, "credited_posts": {}})


def _save_leaderboard(state: dict) -> None:
    write_raw_json_state(LEADERBOARD_STATE_FILE, state)


def _already_credited(state: dict, username: str, post_id: str) -> bool:
    return post_id in state["credited_posts"].get(username, [])


def credit_correct_answer(username: str, post_id: str, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    state = _load_leaderboard()
    if _already_credited(state, username, post_id):
        return  # already got credit for this specific post — don't let repeated comments inflate the count
    entry = state["entries"].setdefault(username, {"correct_count": 0, "first_correct_at": None})
    entry["correct_count"] += 1
    if entry["first_correct_at"] is None:
        entry["first_correct_at"] = now.isoformat()
    state["credited_posts"].setdefault(username, []).append(post_id)
    _save_leaderboard(state)


def current_leaderboard() -> dict[str, int]:
    state = _load_leaderboard()
    return {username: e["correct_count"] for username, e in state["entries"].items()}


def reset_leaderboard() -> None:
    """Called by weekly-winner.yml after the winner Reel is generated."""
    _save_leaderboard({"entries": {}, "credited_posts": {}})


def process_comments_for_post(client: anthropic.Anthropic, post: PostRecord) -> list[CommentRecord]:
    if post.answer is None or post.ig_media_id is None:
        return []  # not a quiz post, or never actually published (e.g. a DRY_RUN record)

    already_seen_ids = {c.comment_id for c in read_jsonl("comments.jsonl", CommentRecord) if c.post_id == post.post_id}
    raw_comments = list_comments(post.ig_media_id)
    new_comments = [c for c in raw_comments if c["id"] not in already_seen_ids][:ENGAGE_REPLY_CAP_PER_RUN]

    quiz_context = f"Question: {post.caption}\nCorrect answer: {post.answer}"
    records: list[CommentRecord] = []

    for raw in new_comments:
        comment_id = raw["id"]
        username = raw.get("username", "unknown")
        text = raw.get("text", "")

        try:
            judgement = judge_comment_answer(client, comment_text=text, correct_answer=post.answer, question=post.caption)
        except GenerationError as exc:
            logger.warning("answer judging failed for comment %s: %s", comment_id, exc)
            continue

        if judgement.is_correct:
            credit_correct_answer(username, post.post_id)

        reply_text = reply_to_judged_comment(
            client,
            comment_id=comment_id,
            comment_text=text,
            is_substantive_fact_share=judgement.is_substantive_fact_share,
            is_correct_guess=judgement.is_correct,
            quiz_context=quiz_context,
        )

        record = CommentRecord(
            comment_id=comment_id,
            post_id=post.post_id,
            username=username,
            text=text,
            is_correct_answer=judgement.is_correct,
            is_substantive_fact_share=judgement.is_substantive_fact_share,
            replied=reply_text is not None,
            reply_text=reply_text,
        )
        append_jsonl("comments.jsonl", record)
        records.append(record)

    return records
