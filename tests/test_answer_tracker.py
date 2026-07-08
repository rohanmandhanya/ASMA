from __future__ import annotations

from unittest.mock import MagicMock, patch

from asma.engagement import answer_tracker
from asma.models import CommentAnswerJudgement, ContentFormat, PostRecord


def _post() -> PostRecord:
    return PostRecord(
        post_id="p1",
        ig_media_id="media123",
        format=ContentFormat.QUIZ_CAROUSEL,
        topic_id="mongolia_yam_relay",
        country="Mongolia",
        answer="The Yam",
        caption="What was the horseback relay network called?",
        hashtags=["#a", "#b", "#c"],
    )


def test_process_comments_credits_correct_answer_once_per_post():
    post = _post()
    raw_comments = [{"id": "c1", "username": "alice", "text": "the yam!"}]

    with patch("asma.engagement.answer_tracker.list_comments", return_value=raw_comments), \
         patch(
             "asma.engagement.answer_tracker.judge_comment_answer",
             return_value=CommentAnswerJudgement(is_correct=True, is_substantive_fact_share=False),
         ), \
         patch("asma.engagement.answer_tracker.reply_to_judged_comment", return_value="Nice, that's right!"):
        records = answer_tracker.process_comments_for_post(MagicMock(), post)

    assert len(records) == 1
    assert records[0].is_correct_answer
    assert records[0].replied
    assert answer_tracker.current_leaderboard() == {"alice": 1}


def test_same_username_not_double_credited_on_same_post():
    post = _post()
    with patch("asma.engagement.answer_tracker.list_comments", return_value=[{"id": "c1", "username": "alice", "text": "yam"}]), \
         patch("asma.engagement.answer_tracker.judge_comment_answer", return_value=CommentAnswerJudgement(is_correct=True, is_substantive_fact_share=False)), \
         patch("asma.engagement.answer_tracker.reply_to_judged_comment", return_value="Correct!"):
        answer_tracker.process_comments_for_post(MagicMock(), post)

    # Crediting the same (username, post_id) pair again directly should be a no-op.
    answer_tracker.credit_correct_answer("alice", post.post_id)
    assert answer_tracker.current_leaderboard() == {"alice": 1}


def test_already_seen_comments_are_not_reprocessed():
    post = _post()
    with patch("asma.engagement.answer_tracker.list_comments", return_value=[{"id": "c1", "username": "alice", "text": "yam"}]), \
         patch("asma.engagement.answer_tracker.judge_comment_answer", return_value=CommentAnswerJudgement(is_correct=True, is_substantive_fact_share=False)) as judge_mock, \
         patch("asma.engagement.answer_tracker.reply_to_judged_comment", return_value="Correct!"):
        answer_tracker.process_comments_for_post(MagicMock(), post)
        # Second run sees the same single comment again from the API — should be filtered as already-seen.
        second_run_records = answer_tracker.process_comments_for_post(MagicMock(), post)

    assert judge_mock.call_count == 1
    assert second_run_records == []


def test_fact_share_credited_as_substantive_not_correct():
    post = _post()
    with patch("asma.engagement.answer_tracker.list_comments", return_value=[{"id": "c1", "username": "bob", "text": "Also the Pony Express did something similar centuries later!"}]), \
         patch("asma.engagement.answer_tracker.judge_comment_answer", return_value=CommentAnswerJudgement(is_correct=False, is_substantive_fact_share=True)), \
         patch("asma.engagement.answer_tracker.reply_to_judged_comment", return_value="Great connection!"):
        records = answer_tracker.process_comments_for_post(MagicMock(), post)

    assert records[0].is_substantive_fact_share
    assert not records[0].is_correct_answer
    assert answer_tracker.current_leaderboard() == {}


def test_reset_leaderboard_clears_state():
    answer_tracker.credit_correct_answer("alice", "post1")
    assert answer_tracker.current_leaderboard() == {"alice": 1}
    answer_tracker.reset_leaderboard()
    assert answer_tracker.current_leaderboard() == {}


def test_process_comments_skips_non_quiz_or_unpublished_post():
    unpublished = PostRecord(
        post_id="p2", ig_media_id=None, format=ContentFormat.QUIZ_CAROUSEL, caption="c", hashtags=["#a", "#b", "#c"]
    )
    assert answer_tracker.process_comments_for_post(MagicMock(), unpublished) == []
