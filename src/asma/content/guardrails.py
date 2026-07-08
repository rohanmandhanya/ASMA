"""Mechanical, code-checkable guardrails — the layer that runs *in addition
to* the system-prompt instructions in prompts.py, not instead of them.
Prompt instructions ("only historian-consensus facts") rely on model
judgment; everything here is a hard, deterministic check that can actually
block a publish.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from asma.config import CAPTION_DEDUP_WINDOW_DAYS, HASHTAGS_MAX, HASHTAGS_MIN, TOPIC_NO_REPEAT_DAYS
from asma.models import CountryFactScript, QuizCard, WinnerAnnouncement

# Defense-in-depth against sensationalized framing, on top of the system
# prompt's tone instruction — catches drift the prompt alone might not.
_SENSATIONAL_PHRASES = (
    "shocking",
    "they don't want you to know",
    "the truth they hid",
    "banned",
    "you won't believe",
    "the government doesn't want",
    "cover-up",
    "conspiracy",
)

CAPTION_SIMILARITY_THRESHOLD = 0.82


@dataclass
class GuardrailResult:
    passed: bool
    issues: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.passed


def _issues_from_checks(*checks: str | None) -> list[str]:
    return [c for c in checks if c]


def check_hashtag_count(hashtags: list[str]) -> str | None:
    if not (HASHTAGS_MIN <= len(hashtags) <= HASHTAGS_MAX):
        return f"hashtag count {len(hashtags)} outside [{HASHTAGS_MIN}, {HASHTAGS_MAX}]"
    return None


def check_no_sensational_language(*texts: str) -> str | None:
    lowered = " ".join(texts).lower()
    hits = [p for p in _SENSATIONAL_PHRASES if p in lowered]
    if hits:
        return f"sensationalized phrasing detected: {hits}"
    return None


def check_answer_is_noun_form(answer: str) -> str | None:
    stripped = answer.strip().rstrip("?.!")
    if not stripped:
        return "answer is empty"
    if stripped.lower() in {"yes", "no", "yes.", "no."}:
        return "answer is yes/no, not a noun"
    if len(stripped.split()) > 6:
        return f"answer '{answer}' looks too long to be a single noun-form answer"
    return None


def check_topic_not_recently_used(topic_id: str, recent_topic_ids: list[str]) -> str | None:
    if topic_id in recent_topic_ids:
        return f"topic_id '{topic_id}' used within the last {TOPIC_NO_REPEAT_DAYS} days"
    return None


def check_caption_not_duplicate(caption: str, recent_captions: list[str]) -> str | None:
    for prior in recent_captions:
        ratio = SequenceMatcher(None, caption.lower(), prior.lower()).ratio()
        if ratio >= CAPTION_SIMILARITY_THRESHOLD:
            return (
                f"caption is {ratio:.0%} similar to a caption used within the last "
                f"{CAPTION_DEDUP_WINDOW_DAYS} days"
            )
    return None


def validate_quiz_card(
    card: QuizCard,
    *,
    recent_topic_ids: list[str],
    recent_captions: list[str],
) -> GuardrailResult:
    issues = _issues_from_checks(
        check_hashtag_count(card.hashtags),
        check_no_sensational_language(card.setup_slide, card.question_slide, card.caption, *card.reveal_slides),
        check_answer_is_noun_form(card.answer),
        check_topic_not_recently_used(card.topic_id, recent_topic_ids),
        check_caption_not_duplicate(card.caption, recent_captions),
    )
    return GuardrailResult(passed=not issues, issues=issues)


def validate_country_fact_script(
    script: CountryFactScript,
    *,
    recent_captions: list[str],
) -> GuardrailResult:
    issues = _issues_from_checks(
        check_hashtag_count(script.hashtags),
        check_no_sensational_language(script.hook_line, script.voiceover_script, script.caption, *script.beats),
        check_caption_not_duplicate(script.caption, recent_captions),
    )
    return GuardrailResult(passed=not issues, issues=issues)


def validate_winner_announcement(script: WinnerAnnouncement) -> GuardrailResult:
    issues = _issues_from_checks(
        check_hashtag_count(script.hashtags),
        check_no_sensational_language(script.hook_line, script.voiceover_script, script.caption),
    )
    return GuardrailResult(passed=not issues, issues=issues)
