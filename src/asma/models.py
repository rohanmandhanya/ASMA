"""Pydantic schemas shared across the pipeline.

These are the `response_schema=` targets passed to Gemini's structured
output API (see content/generator.py) and the on-disk record shapes
appended to the JSONL stores in data/. Keeping them in one module means the
generator, the renderer, the publisher, and the growth loop all agree on
field names.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ContentFormat(StrEnum):
    QUIZ_CAROUSEL = "quiz_carousel"
    COUNTRY_FACT_REEL = "country_fact_reel"
    WINNER_ANNOUNCEMENT_REEL = "winner_announcement_reel"


class HookStyle(StrEnum):
    BOLD_CLAIM = "bold_claim"
    MYTH_BUST = "myth_bust"
    QUESTION_HOOK = "question_hook"
    STAT_LED = "stat_led"


# ---------------------------------------------------------------------------
# Gemini generation targets (content/generator.py's response_schema=)
# ---------------------------------------------------------------------------


class QuizCard(BaseModel):
    """The primary format: a trivia carousel, question -> noun-form answer."""

    topic_id: str = Field(description="Stable slug identifying this topic, e.g. 'inca_quipu_records'")
    country: str = Field(description="Country or culture this fact is about, e.g. 'Peru'")
    category: str = Field(
        default="history",
        description="'history' or 'pop_culture' — selects which system-prompt guardrails generated this card, "
        "forced by the caller rather than model-chosen.",
    )
    hook: HookStyle
    setup_slide: str = Field(description="Slide 1: the striking, well-documented fact that sets up the question")
    question_slide: str = Field(description="Slide 2: a question whose answer is a single noun (person/place/thing)")
    answer: str = Field(description="The correct answer, in noun form — what answer_tracker matches comments against")
    reveal_slides: list[str] = Field(
        min_length=1,
        max_length=3,
        description="Final slide(s): reveal the answer with context. First slide should state the answer plainly.",
    )
    caption: str = Field(
        description="IG caption. First line front-loads searchable keywords (country/era/topic) for Explore SEO."
    )
    hashtags: list[str] = Field(min_length=3, max_length=5)
    stump_the_bot_prompt: str = Field(
        default="Know a wild detail about this we didn't mention? Try to stump the bot 👇",
        description="The comment-hook line appended to the caption or final slide.",
    )
    sources_note: str | None = Field(
        default=None, description="Optional short citation/source note for accuracy transparency."
    )


class CountryFactScript(BaseModel):
    """Recurring Reel: 'a beautiful old fact about <country>', randomly rotated."""

    country: str
    hook: HookStyle
    hook_line: str = Field(description="First on-screen + spoken line — must work with audio off")
    beats: list[str] = Field(min_length=3, max_length=6, description="One on-screen text card per narration beat")
    voiceover_script: str = Field(description="Full narration script, 60-90s spoken at natural pace")
    caption: str
    hashtags: list[str] = Field(min_length=3, max_length=5)


class WinnerAnnouncement(BaseModel):
    """Weekly Reel recognizing the commenter with the most correct answers."""

    winner_username: str
    correct_answer_count: int = Field(ge=1)
    week_of: str = Field(description="ISO date (Monday) of the tallied week")
    hook_line: str
    beats: list[str] = Field(min_length=2, max_length=5)
    voiceover_script: str
    caption: str
    hashtags: list[str] = Field(min_length=3, max_length=5)


class CommentAnswerJudgement(BaseModel):
    """flash-lite classification output: does this comment correctly answer the live quiz?"""

    is_correct: bool
    matched_answer_text: str | None = Field(
        default=None, description="The portion of the comment that gave the answer, if is_correct"
    )
    is_substantive_fact_share: bool = Field(
        description="True if this looks like a 'stump the bot' style fact-share worth a genuine reply, "
        "not just a one-word guess"
    )


class CommentReply(BaseModel):
    """Generated reply text for comment_responder.py."""

    reply_text: str


# ---------------------------------------------------------------------------
# On-disk records (data/*.jsonl)
# ---------------------------------------------------------------------------


class PostRecord(BaseModel):
    post_id: str = Field(description="Local id, e.g. topic_id or f'{format}-{date}'")
    ig_media_id: str | None = Field(default=None, description="Graph API media id once published; None in DRY_RUN")
    format: ContentFormat
    topic_id: str | None = None
    country: str | None = None
    hook: HookStyle | None = None
    answer: str | None = Field(default=None, description="Correct answer, for quiz_carousel posts")
    caption: str
    hashtags: list[str]
    has_story: bool = False
    dry_run: bool = True
    published_at: datetime = Field(default_factory=_utcnow)


class CommentRecord(BaseModel):
    comment_id: str
    post_id: str
    username: str
    text: str
    is_correct_answer: bool = False
    is_substantive_fact_share: bool = False
    replied: bool = False
    reply_text: str | None = None
    observed_at: datetime = Field(default_factory=_utcnow)


class MetricSnapshot(BaseModel):
    snapshot_at: datetime = Field(default_factory=_utcnow)
    follower_count: int | None = None
    post_id: str | None = Field(default=None, description="None for account-level snapshots")
    likes: int | None = None
    comments: int | None = None
    saves: int | None = None
    shares: int | None = None
    reach: int | None = None
    impressions: int | None = None
    video_watch_time_seconds: float | None = None
    video_hold_rate_3s: float | None = Field(default=None, description="Fraction of viewers who watched past 3s")


class LeaderboardEntry(BaseModel):
    username: str
    correct_count: int = 0
    first_correct_at: datetime | None = None


class MilestoneState(BaseModel):
    hundred_followers_email_sent: bool = False
    sent_at: datetime | None = None
    follower_count_at_send: int | None = None


GenerationTarget = QuizCard | CountryFactScript | WinnerAnnouncement
"""Union of the three schemas generator.py can request from client.messages.parse()."""
