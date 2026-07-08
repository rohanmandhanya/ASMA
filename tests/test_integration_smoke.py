"""End-to-end orchestration smoke test — the one thing the per-module unit
tests don't prove: that manual_post_once.py actually wires topic
selection, generation, guardrails, real Playwright rendering, media
hosting, and the Graph API client together correctly, in order, producing
a valid committed PostRecord.

Claude's response is mocked (no live ANTHROPIC_API_KEY in CI/this
environment) — everything else is real: real Playwright renders real PNGs,
real DRY_RUN Graph API stub logic runs, real state files get written. This
is the "run once against real Claude" step in the plan's phased rollout,
minus the one piece that genuinely needs a live API key to verify (content
quality) — see README's "What's genuinely unverified" section.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from asma.config import CADENCE_RAMP  # noqa: E402
from asma.models import ContentFormat, PostRecord  # noqa: E402
from asma.store.jsonl_store import append_jsonl, read_jsonl  # noqa: E402


def _fake_client(sample_quiz_card) -> MagicMock:
    client = MagicMock()
    client.messages.parse.return_value = SimpleNamespace(stop_reason="end_turn", parsed_output=sample_quiz_card)
    return client


def test_full_carousel_orchestration_end_to_end(sample_quiz_card):
    import manual_post_once

    # Exercises the real functions manual_post_once.main() itself calls
    # (topic selection, generation, guardrails, real Playwright rendering,
    # DRY_RUN media/Graph API stubs) — going through main() directly would
    # just add argv-parsing noise without testing anything more.
    record = manual_post_once._publish_carousel(_fake_client(sample_quiz_card), will_attach_story=True)

    assert record is not None
    assert record.format == ContentFormat.QUIZ_CAROUSEL
    assert record.topic_id  # a real topic was selected from the pool
    assert record.answer == sample_quiz_card.answer
    assert record.has_story is True
    # Proves it round-tripped through the real DRY_RUN graph_client stub,
    # not a mock standing in for the whole publish layer.
    assert record.ig_media_id == "DRYRUN_MEDIA_0000000000"

    append_jsonl("posts.jsonl", record)
    persisted = read_jsonl("posts.jsonl", PostRecord)
    assert len(persisted) == 1
    assert persisted[0].post_id == record.post_id


def test_cadence_ramp_gate_blocks_second_post_same_day(sample_quiz_card, monkeypatch):
    """Proves the real (non-mocked) budget_allocator + rate_limiter chain
    actually blocks a second publish once day 0's target of 1 is met —
    the specific mechanism the plan relies on to avoid the spam-detection
    pattern flagged in research."""
    import manual_post_once
    from asma.content.topic_selector import mark_campaign_launched_if_needed

    mark_campaign_launched_if_needed()  # day 0 -> target is CADENCE_RAMP[0][1] == 1
    assert CADENCE_RAMP[0][1] == 1

    # dry_run=True records deliberately don't count toward rate limits (see
    # rate_limiter.py) — simulate a real publish by flipping just the flag
    # manual_post_once stamps onto the record. Real network calls stay
    # stubbed regardless, via graph_client's own DRY_RUN (patched true by
    # the autouse fixture) — this only affects what gets written to disk.
    monkeypatch.setattr(manual_post_once, "DRY_RUN", False)

    record = manual_post_once._publish_carousel(_fake_client(sample_quiz_card), will_attach_story=False)
    assert record is not None
    assert record.dry_run is False
    append_jsonl("posts.jsonl", record)

    allowed, reason = manual_post_once.budget_allocator.should_publish_now()
    assert not allowed
    assert "target" in reason
