"""Generates and posts the actual reply text for one already-judged
comment. Two distinct behaviors, not one generic acknowledgment: plain
guesses get a short confirm/deny; substantive "stump the bot" fact-shares
get a genuine, specific reply — those are the comments that matter most
for Instagram's 2026 comment-quality signal, so they're worth a better
reply than a template.
"""

from __future__ import annotations

import logging

from google import genai

from asma.content.generator import GenerationError, generate_comment_reply
from asma.publish.graph_client import reply_to_comment

logger = logging.getLogger(__name__)


def reply_to_judged_comment(
    client: genai.Client,
    *,
    comment_id: str,
    comment_text: str,
    is_substantive_fact_share: bool,
    is_correct_guess: bool | None,
    quiz_context: str,
) -> str | None:
    """Returns the reply text if a reply was generated and posted, else
    None (on a generation failure — logged, not raised, so one bad
    generation doesn't abort the whole engage-comments.yml run)."""
    try:
        reply_text = generate_comment_reply(
            client,
            comment_text=comment_text,
            is_substantive_fact_share=is_substantive_fact_share,
            is_correct_guess=is_correct_guess,
            quiz_context=quiz_context,
        )
    except GenerationError as exc:
        logger.warning("comment reply generation failed for comment %s: %s", comment_id, exc)
        return None

    reply_to_comment(comment_id, reply_text)
    return reply_text
