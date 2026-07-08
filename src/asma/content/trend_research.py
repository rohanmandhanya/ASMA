"""Periodic (weekly, not every run) trend-awareness pass using Claude's own
web-search tool. This is the ONLY way topic selection gets any signal about
what's currently resonating — it never scrapes TikTok or Instagram directly
(both prohibited by ToS; TikTok's official Research API is restricted to
qualifying academic institutions, not available here). Claude searches
public, secondary sources (articles, roundups) and writes an original
summary; nothing here reproduces another platform's content.
"""

from __future__ import annotations

import logging

import anthropic

from asma.config import CONTENT_MODEL, DRY_RUN
from asma.content.prompts import trend_research_prompt

logger = logging.getLogger(__name__)

_FALLBACK_SUMMARY = (
    "No fresh trend research available this run — proceed with topic selection "
    "from the standard bandit (topic_selector.py) with no additional trend bias."
)


def research_trending_history_topics(client: anthropic.Anthropic) -> str:
    if DRY_RUN:
        logger.info("[DRY_RUN] trend_research: skipping real web-search call")
        return "[DRY_RUN] " + _FALLBACK_SUMMARY

    response = client.messages.create(
        model=CONTENT_MODEL,
        max_tokens=1024,
        tools=[{"type": "web_search_20260209", "name": "web_search"}],
        messages=[{"role": "user", "content": trend_research_prompt()}],
    )

    if response.stop_reason == "refusal":
        logger.warning("trend_research: model refused; falling back to no-bias summary")
        return _FALLBACK_SUMMARY

    text_parts = [block.text for block in response.content if block.type == "text"]
    summary = "\n".join(text_parts).strip()
    return summary or _FALLBACK_SUMMARY
