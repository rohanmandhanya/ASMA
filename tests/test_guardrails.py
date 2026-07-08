from __future__ import annotations

from asma.content import guardrails


def test_valid_card_passes(sample_quiz_card):
    result = guardrails.validate_quiz_card(sample_quiz_card, recent_topic_ids=[], recent_captions=[])
    assert result.passed
    assert result.issues == []


def test_hashtag_count_out_of_range(sample_quiz_card):
    bad = sample_quiz_card.model_copy(update={"hashtags": ["#a", "#b"]})
    result = guardrails.check_hashtag_count(bad.hashtags)
    assert result is not None
    assert "hashtag count" in result


def test_sensational_language_flagged():
    assert guardrails.check_no_sensational_language("The SHOCKING truth they don't want you to know") is not None
    assert guardrails.check_no_sensational_language("A well-documented historical fact") is None


def test_answer_must_be_noun_form():
    assert guardrails.check_answer_is_noun_form("yes") is not None
    assert guardrails.check_answer_is_noun_form("") is not None
    assert guardrails.check_answer_is_noun_form("The Yam") is None
    assert guardrails.check_answer_is_noun_form("this is a much too long answer to be a single noun") is not None


def test_topic_recently_used_is_rejected(sample_quiz_card):
    result = guardrails.validate_quiz_card(
        sample_quiz_card, recent_topic_ids=[sample_quiz_card.topic_id], recent_captions=[]
    )
    assert not result.passed
    assert any("used within the last" in issue for issue in result.issues)


def test_caption_dedup_catches_near_duplicates(sample_quiz_card):
    near_duplicate = "Mongolia, 1200s: the horseback postal system that outran Europe by 600 years."
    result = guardrails.validate_quiz_card(sample_quiz_card, recent_topic_ids=[], recent_captions=[near_duplicate])
    assert not result.passed
    assert any("similar" in issue for issue in result.issues)


def test_caption_dedup_allows_genuinely_different_captions(sample_quiz_card):
    result = guardrails.validate_quiz_card(
        sample_quiz_card, recent_topic_ids=[], recent_captions=["Peru: the knotted-cord empire."]
    )
    assert result.passed


def test_country_fact_script_validation(sample_country_fact_script):
    result = guardrails.validate_country_fact_script(sample_country_fact_script, recent_captions=[])
    assert result.passed


def test_winner_announcement_validation():
    from asma.models import WinnerAnnouncement

    script = WinnerAnnouncement(
        winner_username="history_fan_42",
        correct_answer_count=5,
        week_of="2026-07-06",
        hook_line="This week's winner answered 5 questions correctly!",
        beats=["Huge congrats to @history_fan_42", "5 correct answers this week"],
        voiceover_script="Big congrats to this week's trivia champion.",
        caption="Weekly winner!",
        hashtags=["#history", "#trivia", "#winner"],
    )
    result = guardrails.validate_winner_announcement(script)
    assert result.passed
