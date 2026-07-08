"""The single choke point for turning topics/comments into validated
content. Every call goes through `client.messages.parse(output_format=...)`
so a malformed or refused response can never silently become a bad post —
see GenerationError and how callers are expected to handle it (log + abort
the run, don't fall back to posting something unvalidated).
"""

from __future__ import annotations

import logging

import anthropic

from asma.config import CONTENT_MODEL, CONTENT_MODEL_EFFORT, REPLY_MODEL
from asma.content.prompts import (
    ANSWER_JUDGE_SYSTEM_PROMPT,
    COMMENT_REPLY_FACT_SHARE_SYSTEM_PROMPT,
    COMMENT_REPLY_GUESS_SYSTEM_PROMPT,
    COUNTRY_FACT_REEL_SYSTEM_PROMPT,
    QUIZ_CARD_SYSTEM_PROMPT,
    WINNER_ANNOUNCEMENT_SYSTEM_PROMPT,
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
    """Raised on a refusal or an unparseable response. Callers must treat
    this as 'abort this run, do not publish' — never catch-and-post-anyway."""


def _context_blob(**kwargs: object) -> str:
    lines = ["Context for this generation:"]
    for key, value in kwargs.items():
        if value:
            lines.append(f"- {key}: {value}")
    return "\n".join(lines)


def _parse_or_raise(client: anthropic.Anthropic, *, system: str, user_content: str, output_format):
    response = client.messages.parse(
        model=CONTENT_MODEL,
        max_tokens=4096,
        system=system,
        output_config={"effort": CONTENT_MODEL_EFFORT},
        messages=[{"role": "user", "content": user_content}],
        output_format=output_format,
    )
    if response.stop_reason == "refusal":
        raise GenerationError(f"model refused generation: {getattr(response, 'stop_details', None)}")
    if response.parsed_output is None:
        raise GenerationError("model response did not parse against the requested schema")
    return response.parsed_output


def generate_quiz_card(
    client: anthropic.Anthropic,
    *,
    topic_id: str,
    country: str,
    seed_angle: str,
    hook: HookStyle,
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
    card = _parse_or_raise(client, system=QUIZ_CARD_SYSTEM_PROMPT, user_content=user_content, output_format=QuizCard)
    # Belt-and-suspenders: force the fields we already decided rather than
    # trusting the model to echo them back verbatim.
    return card.model_copy(update={"topic_id": topic_id, "country": country, "hook": hook})


def generate_country_fact_script(
    client: anthropic.Anthropic,
    *,
    country: str,
    hook: HookStyle,
    recent_posts_summary: str = "",
    performance_summary: str = "",
) -> CountryFactScript:
    system = COUNTRY_FACT_REEL_SYSTEM_PROMPT.format(country=country)
    user_content = (
        f"Write today's country-fact Reel about {country}. Use hook='{hook.value}'.\n\n"
        + _context_blob(recent_posts=recent_posts_summary, performance=performance_summary)
    )
    script = _parse_or_raise(client, system=system, user_content=user_content, output_format=CountryFactScript)
    return script.model_copy(update={"country": country, "hook": hook})


def generate_winner_announcement(
    client: anthropic.Anthropic,
    *,
    winner_username: str,
    correct_answer_count: int,
    week_of: str,
) -> WinnerAnnouncement:
    user_content = (
        f"This week's winner: @{winner_username}, {correct_answer_count} correct answers. "
        f"week_of='{week_of}'."
    )
    script = _parse_or_raise(
        client, system=WINNER_ANNOUNCEMENT_SYSTEM_PROMPT, user_content=user_content, output_format=WinnerAnnouncement
    )
    return script.model_copy(
        update={"winner_username": winner_username, "correct_answer_count": correct_answer_count, "week_of": week_of}
    )


def judge_comment_answer(
    client: anthropic.Anthropic, *, comment_text: str, correct_answer: str, question: str
) -> CommentAnswerJudgement:
    user_content = f"Question: {question}\nCorrect answer: {correct_answer}\nComment: {comment_text}"
    return _parse_or_raise(
        client,
        system=ANSWER_JUDGE_SYSTEM_PROMPT,
        user_content=user_content,
        output_format=CommentAnswerJudgement,
    )


def generate_comment_reply(
    client: anthropic.Anthropic,
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
    # Cheap, high-volume call — Haiku, not the content model.
    response = client.messages.parse(
        model=REPLY_MODEL,
        max_tokens=512,
        system=system,
        messages=[{"role": "user", "content": user_content}],
        output_format=CommentReply,
    )
    if response.stop_reason == "refusal" or response.parsed_output is None:
        raise GenerationError("comment reply generation failed or was refused")
    return response.parsed_output.reply_text
