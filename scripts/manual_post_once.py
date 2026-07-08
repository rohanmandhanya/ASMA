#!/usr/bin/env python3
"""Generate, render, and publish exactly one post. This is the single
entrypoint both `scheduled-content.yml` and manual local testing use — see
the plan's phased rollout: run this locally under DRY_RUN before the
account ever exists, then via `workflow_dispatch(dry_run=false)` for the
first real posts, then on the cron schedule.

Usage:
    DRY_RUN=true uv run python scripts/manual_post_once.py --format quiz_carousel
    DRY_RUN=true uv run python scripts/manual_post_once.py --format auto
"""

from __future__ import annotations

import argparse
import logging
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import anthropic  # noqa: E402

from asma.config import ANTHROPIC_API_KEY, DRY_RUN  # noqa: E402
from asma.content import generator, guardrails, topic_selector  # noqa: E402
from asma.content.trend_research import research_trending_history_topics  # noqa: E402
from asma.content.trend_research_schedule import is_trend_research_due, mark_trend_research_ran  # noqa: E402
from asma.growth import budget_allocator, feedback  # noqa: E402
from asma.models import ContentFormat, PostRecord  # noqa: E402
from asma.publish import graph_client, media_host  # noqa: E402
from asma.render.renderer import render_country_fact_cards, render_quiz_card_slides  # noqa: E402
from asma.store.jsonl_store import append_jsonl, read_jsonl  # noqa: E402
from asma.video.assembler import assemble_reel  # noqa: E402
from asma.video.tts import synthesize_voiceover  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("manual_post_once")

# Format mix for --format auto: carousel-led (the data-validated flagship
# format for the quiz mechanic) with Reels running alongside for the reach
# a brand-new account needs to break past its own follower base.
_AUTO_FORMAT_WEIGHTS = {ContentFormat.QUIZ_CAROUSEL: 0.6, ContentFormat.COUNTRY_FACT_REEL: 0.4}


def _recent_context(days: int = 14) -> tuple[list[str], list[str], str]:
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    recent_posts = [p for p in read_jsonl("posts.jsonl", PostRecord) if p.published_at > cutoff]
    recent_topic_ids = [p.topic_id for p in recent_posts if p.topic_id]
    recent_captions = [p.caption for p in recent_posts]
    summary = "; ".join(f"{p.topic_id or p.format.value} ({p.country})" for p in recent_posts[-10:]) or "none yet"
    return recent_topic_ids, recent_captions, summary


def _publish_carousel(client: anthropic.Anthropic, *, will_attach_story: bool) -> PostRecord | None:
    topic = topic_selector.select_topic()
    hook = topic_selector.select_hook()
    recent_topic_ids, recent_captions, recent_summary = _recent_context()
    performance_summary = feedback.build_performance_summary()

    trend_summary = ""
    if is_trend_research_due():
        trend_summary = research_trending_history_topics(client)
        mark_trend_research_ran()

    try:
        card = generator.generate_quiz_card(
            client,
            topic_id=topic.topic_id,
            country=topic.country,
            seed_angle=topic.seed_angle,
            hook=hook,
            recent_posts_summary=recent_summary,
            performance_summary=performance_summary,
            trend_summary=trend_summary,
        )
    except generator.GenerationError as exc:
        logger.error("quiz card generation failed/refused, aborting this run: %s", exc)
        return None

    result = guardrails.validate_quiz_card(card, recent_topic_ids=recent_topic_ids, recent_captions=recent_captions)
    if not result.passed:
        logger.error("quiz card failed guardrails, aborting this run: %s", result.issues)
        return None

    slides = render_quiz_card_slides(card)
    image_urls = [media_host.upload_media(png, extension=".png") for png in slides]

    container_ids = [graph_client.create_image_container(url, is_carousel_item=True) for url in image_urls]
    for cid in container_ids:
        graph_client.poll_container_until_finished(cid, is_video=False)

    full_caption = f"{card.caption}\n\n{card.stump_the_bot_prompt}\n\n" + " ".join(card.hashtags)
    carousel_id = graph_client.create_carousel_container(container_ids, caption=full_caption)
    graph_client.poll_container_until_finished(carousel_id, is_video=False)
    media_id = graph_client.publish_container(carousel_id)

    if will_attach_story:
        story_id = graph_client.create_story_container(image_urls[0])
        graph_client.poll_container_until_finished(story_id, is_video=False)
        graph_client.publish_container(story_id)

    topic_selector.record_topic_used(topic, hook)

    return PostRecord(
        post_id=f"{topic.topic_id}-{datetime.now(timezone.utc):%Y%m%d%H%M%S}",
        ig_media_id=media_id,
        format=ContentFormat.QUIZ_CAROUSEL,
        topic_id=topic.topic_id,
        country=topic.country,
        hook=hook,
        answer=card.answer,
        caption=full_caption,
        hashtags=card.hashtags,
        has_story=will_attach_story,
        dry_run=DRY_RUN,
    )


def _publish_country_fact_reel(client: anthropic.Anthropic) -> PostRecord | None:
    country = topic_selector.select_country_fact_country()
    hook = topic_selector.select_hook()
    _, recent_captions, _ = _recent_context()
    performance_summary = feedback.build_performance_summary()

    try:
        script = generator.generate_country_fact_script(
            client, country=country, hook=hook, performance_summary=performance_summary
        )
    except generator.GenerationError as exc:
        logger.error("country fact script generation failed/refused, aborting this run: %s", exc)
        return None

    result = guardrails.validate_country_fact_script(script, recent_captions=recent_captions)
    if not result.passed:
        logger.error("country fact script failed guardrails, aborting this run: %s", result.issues)
        return None

    cards = render_country_fact_cards(script)
    voiceover = synthesize_voiceover(script.voiceover_script)
    video_path = assemble_reel(cards, voiceover, Path("assets/rendered") / "country_fact.mp4")
    video_url = media_host.upload_media(video_path.read_bytes(), extension=".mp4")

    container_id = graph_client.create_video_container(video_url, caption=script.caption, media_type="REELS")
    graph_client.poll_container_until_finished(container_id, is_video=True)
    media_id = graph_client.publish_container(container_id)

    topic_selector.record_country_fact_used(country)

    return PostRecord(
        post_id=f"country-{country.lower().replace(' ', '_')}-{datetime.now(timezone.utc):%Y%m%d%H%M%S}",
        ig_media_id=media_id,
        format=ContentFormat.COUNTRY_FACT_REEL,
        country=country,
        hook=hook,
        caption=script.caption,
        hashtags=script.hashtags,
        has_story=False,
        dry_run=DRY_RUN,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=["quiz_carousel", "country_fact_reel", "auto"], default="auto")
    parser.add_argument("--force", action="store_true", help="skip the budget_allocator gate (still respects rate_limiter)")
    args = parser.parse_args()

    logger.info("DRY_RUN=%s", DRY_RUN)

    if not args.force:
        allowed, reason = budget_allocator.should_publish_now()
        if not allowed:
            logger.info("not publishing this firing: %s", reason)
            return 0

    if not DRY_RUN and not ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY is not set and DRY_RUN is false — refusing to run")
        return 1

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else anthropic.Anthropic()

    chosen_format = args.format
    if chosen_format == "auto":
        chosen_format = random.choices(
            list(_AUTO_FORMAT_WEIGHTS.keys()), weights=list(_AUTO_FORMAT_WEIGHTS.values()), k=1
        )[0].value

    if chosen_format == "quiz_carousel":
        will_attach_story = budget_allocator.should_attach_story()
        record = _publish_carousel(client, will_attach_story=will_attach_story)
    else:
        record = _publish_country_fact_reel(client)

    if record is None:
        return 1  # generation/guardrail failure — already logged, don't post anything

    append_jsonl("posts.jsonl", record)
    logger.info("published: %s", record.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
