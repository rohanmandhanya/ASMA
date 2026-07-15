"""Periodic (weekly, not every run) trend-awareness pass using Gemini's
built-in Google Search grounding tool. This is the ONLY way topic selection
gets any signal about what's currently resonating — it never scrapes TikTok
or Instagram directly (both prohibited by ToS; TikTok's official Research
API is restricted to qualifying academic institutions, not available here).
Gemini searches public, secondary sources (articles, roundups) and writes
an original summary; nothing here reproduces another platform's content.
"""

from __future__ import annotations

import logging

import httpx
from google import genai
from google.genai import errors, types

from asma.config import CONTENT_MODEL, DRY_RUN
from asma.content.generator import gemini_http_options
from asma.content.prompts import trend_research_prompt

logger = logging.getLogger(__name__)

_FALLBACK_SUMMARY = (
    "No fresh trend research available this run — proceed with topic selection "
    "from the standard bandit (topic_selector.py) with no additional trend bias."
)


def research_trending_history_topics(client: genai.Client) -> str:
    if DRY_RUN:
        logger.info("[DRY_RUN] trend_research: skipping real web-search call")
        return "[DRY_RUN] " + _FALLBACK_SUMMARY

    try:
        response = client.models.generate_content(
            model=CONTENT_MODEL,
            contents=trend_research_prompt(),
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                http_options=gemini_http_options(),
            ),
        )
    except (errors.APIError, httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
        # Google Search grounding can be unavailable on some tiers/quotas
        # (e.g. 429 RESOURCE_EXHAUSTED) even when plain generate_content
        # calls work fine — this signal is a nice-to-have, never worth
        # taking down the whole scheduled-content run over. The httpx
        # transport errors (timeout, connection drop, mid-response reset)
        # get the same treatment for the same reason.
        logger.warning("trend_research: Gemini API call failed (%s); falling back", exc)
        return _FALLBACK_SUMMARY

    candidates = response.candidates or []
    finish_reason = getattr(candidates[0], "finish_reason", None) if candidates else None
    finished_normally = finish_reason is not None and str(finish_reason).rsplit(".", 1)[-1] == "STOP"
    if not candidates or not finished_normally:
        logger.warning("trend_research: model refused/blocked (finish_reason=%s); falling back", finish_reason)
        return _FALLBACK_SUMMARY

    summary = (response.text or "").strip()
    return summary or _FALLBACK_SUMMARY
