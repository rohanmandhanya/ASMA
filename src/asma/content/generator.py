"""The single choke point for turning topics/comments into validated
content. Every call goes through Gemini's structured-output API
(`response_schema=`, via `_generate()` below) so a malformed or refused
response can never silently become a bad post — see GenerationError and how
callers are expected to handle it (log + abort the run, don't fall back to
posting something unvalidated).

Provider: Gemini (`gemini-3.5-flash` for content, `gemini-3.1-flash-lite`
for high-volume replies/judging — see config.py) — chosen specifically
because Anthropic has no free tier at all, while Gemini's free tier
comfortably covers this project's entire call volume. Swapping providers
later only touches this file plus trend_research.py.

Refusal/safety-block detection (`_generate()`'s finish_reason/prompt_feedback
checks below) is the documented 2026 Gemini API shape, not yet exercised
against a live response in this environment (no GEMINI_API_KEY here) —
verify at deploy time, same as graph_client.py's own "verify current docs"
notes elsewhere in this codebase.
"""

from __future__ import annotations

import logging

from google import genai
from google.genai import errors, types
from pydantic import BaseModel, Field

from asma.config import CONTENT_MODEL, CONTENT_MODEL_FALLBACKS, REPLY_MODEL
from asma.content.prompts import (
    ANSWER_JUDGE_SYSTEM_PROMPT,
    COMMENT_REPLY_FACT_SHARE_SYSTEM_PROMPT,
    COMMENT_REPLY_GUESS_SYSTEM_PROMPT,
    WINNER_ANNOUNCEMENT_SYSTEM_PROMPT,
    country_fact_reel_system_prompt,
    quiz_card_system_prompt,
)
from asma.models import (
    CommentAnswerJudgement,
    CommentReply,
    CountryFactScript,
    HookStyle,
    QuizCard,
    WinnerAnnouncement,
)

logger = logging.getLogger(__name__)


class GenerationError(RuntimeError):
    """Raised on a refusal/safety block or an unparseable response. Callers
    must treat this as 'abort this run, do not publish' — never
    catch-and-post-anyway."""


def _context_blob(**kwargs: object) -> str:
    lines = ["Context for this generation:"]
    for key, value in kwargs.items():
        if value:
            lines.append(f"- {key}: {value}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Gemini's response_schema rejects any Pydantic field with an explicit
# default value ("Default value is not supported in the response schema for
# the Gemini API") — QuizCard (category/stump_the_bot_prompt/sources_note),
# CountryFactScript (topic_id/category), and CommentAnswerJudgement
# (matched_answer_text) all have them, so generation uses these default-free
# mirrors instead, and the real model is constructed from the parsed result
# afterward. WinnerAnnouncement/CommentReply have no defaulted fields and are
# used directly as response_schema. `category`/`topic_id` are dropped
# entirely from the mirrors below — the caller always overwrites them, so
# there's no reason to ask the model for them at all.
# ---------------------------------------------------------------------------


class _QuizCardSchema(BaseModel):
    topic_id: str = Field(description="Stable slug identifying this topic, e.g. 'inca_quipu_records'")
    country: str = Field(description="Country or culture this fact is about, e.g. 'Peru'")
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
    stump_the_bot_prompt: str = Field(description="The comment-hook line appended to the caption or final slide.")
    sources_note: str | None = Field(description="Optional short citation/source note for accuracy transparency.")


class _CountryFactScriptSchema(BaseModel):
    country: str = Field(
        description="Country this fact is about, e.g. 'Peru' (or a pop-culture rotation-bucket label)"
    )
    hook: HookStyle
    hook_line: str = Field(description="First on-screen + spoken line — must work with audio off")
    beats: list[str] = Field(min_length=3, max_length=6, description="One on-screen text card per narration beat")
    voiceover_script: str = Field(description="Full narration script, 60-90s spoken at natural pace")
    caption: str
    hashtags: list[str] = Field(min_length=3, max_length=5)


class _CommentAnswerJudgementSchema(BaseModel):
    is_correct: bool
    matched_answer_text: str | None = Field(
        description="The portion of the comment that gave the answer, if is_correct"
    )
    is_substantive_fact_share: bool = Field(
        description="True if this looks like a 'stump the bot' style fact-share worth a genuine reply, "
        "not just a one-word guess"
    )


def _generate(
    client: genai.Client, *, model: str, system: str, user_content: str, schema: type[BaseModel]
) -> BaseModel:
    # Only CONTENT_MODEL has fallbacks configured — REPLY_MODEL is already
    # the cheap/lite tier, not the one that's been seen overloaded.
    candidate_models = [model] + (list(CONTENT_MODEL_FALLBACKS) if model == CONTENT_MODEL else [])

    response = None
    for i, candidate_model in enumerate(candidate_models):
        try:
            response = client.models.generate_content(
                model=candidate_model,
                contents=user_content,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_schema=schema,
                ),
            )
            break
        except errors.ServerError as exc:
            is_last = i == len(candidate_models) - 1
            if is_last:
                raise GenerationError(f"model(s) unavailable: {exc}") from exc
            logger.warning(
                "generation on %s failed (%s); falling back to %s",
                candidate_model,
                exc,
                candidate_models[i + 1],
            )

    feedback = getattr(response, "prompt_feedback", None)
    block_reason = getattr(feedback, "block_reason", None) if feedback else None
    if block_reason:
        raise GenerationError(f"prompt blocked before generation: block_reason={block_reason}")

    candidates = response.candidates or []
    if not candidates:
        raise GenerationError("model returned no candidates (likely blocked)")

    finish_reason = getattr(candidates[0], "finish_reason", None)
    # finish_reason may render as a bare string ("STOP") or an enum repr
    # ("FinishReason.STOP") depending on SDK version — compare on the last
    # dot-segment so either form works.
    if finish_reason is not None and str(finish_reason).rsplit(".", 1)[-1] != "STOP":
        raise GenerationError(f"generation did not complete normally: finish_reason={finish_reason}")

    try:
        parsed = response.parsed
    except Exception as exc:  # SDK-internal schema validation failure
        raise GenerationError(f"model response did not parse against the requested schema: {exc}") from exc
    if parsed is None:
        raise GenerationError("model response did not parse against the requested schema")
    return parsed


def generate_quiz_card(
    client: genai.Client,
    *,
    topic_id: str,
    country: str,
    seed_angle: str,
    hook: HookStyle,
    category: str = "history",
    recent_posts_summary: str = "",
    performance_summary: str = "",
    trend_summary: str = "",
) -> QuizCard:
    user_content = (
        f"Write today's quiz carousel.\nTopic seed: {seed_angle}\n"
        f"Use topic_id='{topic_id}', country='{country}', hook='{hook.value}'.\n\n"
        + _context_blob(
            recent_posts=recent_posts_summary,
            performance=performance_summary,
            trend_research=trend_summary,
        )
    )
    system = quiz_card_system_prompt(category)
    parsed = _generate(client, model=CONTENT_MODEL, system=system, user_content=user_content, schema=_QuizCardSchema)
    # Belt-and-suspenders: force the fields we already decided rather than
    # trusting the model to echo them back verbatim.
    data = parsed.model_dump()
    data.update(topic_id=topic_id, country=country, hook=hook, category=category)
    return QuizCard(**data)


def generate_country_fact_script(
    client: genai.Client,
    *,
    topic_id: str,
    country: str,
    seed_angle: str,
    hook: HookStyle,
    category: str = "history",
    recent_posts_summary: str = "",
    performance_summary: str = "",
) -> CountryFactScript:
    user_content = (
        f"Write today's country-fact Reel.\nTopic seed: {seed_angle}\n"
        f"Use topic_id='{topic_id}', country='{country}', hook='{hook.value}'.\n\n"
        + _context_blob(recent_posts=recent_posts_summary, performance=performance_summary)
    )
    system = country_fact_reel_system_prompt(category, country=country)
    parsed = _generate(
        client, model=CONTENT_MODEL, system=system, user_content=user_content, schema=_CountryFactScriptSchema
    )
    data = parsed.model_dump()
    data.update(topic_id=topic_id, country=country, hook=hook, category=category)
    return CountryFactScript(**data)


def generate_winner_announcement(
    client: genai.Client,
    *,
    winner_username: str,
    correct_answer_count: int,
    week_of: str,
) -> WinnerAnnouncement:
    user_content = (
        f"This week's winner: @{winner_username}, {correct_answer_count} correct answers. "
        f"week_of='{week_of}'."
    )
    parsed = _generate(
        client,
        model=CONTENT_MODEL,
        system=WINNER_ANNOUNCEMENT_SYSTEM_PROMPT,
        user_content=user_content,
        schema=WinnerAnnouncement,
    )
    data = parsed.model_dump()
    data.update(winner_username=winner_username, correct_answer_count=correct_answer_count, week_of=week_of)
    return WinnerAnnouncement(**data)


def judge_comment_answer(
    client: genai.Client, *, comment_text: str, correct_answer: str, question: str
) -> CommentAnswerJudgement:
    user_content = f"Question: {question}\nCorrect answer: {correct_answer}\nComment: {comment_text}"
    parsed = _generate(
        client,
        model=REPLY_MODEL,
        system=ANSWER_JUDGE_SYSTEM_PROMPT,
        user_content=user_content,
        schema=_CommentAnswerJudgementSchema,
    )
    return CommentAnswerJudgement(**parsed.model_dump())


def generate_comment_reply(
    client: genai.Client,
    *,
    comment_text: str,
    is_substantive_fact_share: bool,
    is_correct_guess: bool | None,
    quiz_context: str,
) -> str:
    system = COMMENT_REPLY_FACT_SHARE_SYSTEM_PROMPT if is_substantive_fact_share else COMMENT_REPLY_GUESS_SYSTEM_PROMPT
    user_content = (
        f"Quiz context: {quiz_context}\nCommenter wrote: {comment_text}\n"
        f"Their guess was: {'correct' if is_correct_guess else 'incorrect' if is_correct_guess is not None else 'n/a'}"
    )
    # Cheap, high-volume call — flash-lite, not the content model.
    parsed = _generate(client, model=REPLY_MODEL, system=system, user_content=user_content, schema=CommentReply)
    return parsed.reply_text
