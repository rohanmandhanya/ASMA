from __future__ import annotations

import os

import pytest

os.environ.setdefault("DRY_RUN", "true")


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Every test gets its own empty data/ directory — nothing here should
    ever touch the real project data/ folder, and tests never see leftover
    state from a previous test."""
    import asma.store.jsonl_store as store

    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    yield tmp_path


@pytest.fixture(autouse=True)
def force_dry_run(monkeypatch):
    """Belt-and-suspenders alongside the DRY_RUN env var: every module that
    imported config.DRY_RUN at import time gets it forced true directly, so
    a test can never accidentally make a real network call regardless of
    import order."""
    import asma.config as config
    import asma.publish.graph_client as graph_client
    import asma.publish.media_host as media_host
    import asma.video.assembler as assembler
    import asma.video.tts as tts
    import asma.content.trend_research as trend_research
    import asma.growth.milestone_notifier as milestone_notifier
    import asma.render.background_client as background_client

    for module in (
        config,
        graph_client,
        media_host,
        assembler,
        tts,
        trend_research,
        milestone_notifier,
        background_client,
    ):
        monkeypatch.setattr(module, "DRY_RUN", True)
    yield


@pytest.fixture
def sample_quiz_card():
    from asma.models import HookStyle, QuizCard

    return QuizCard(
        topic_id="mongolia_yam_relay",
        country="Mongolia",
        hook=HookStyle.STAT_LED,
        setup_slide="In the 1200s, a message could travel 200 miles across the Mongol Empire in a single day.",
        question_slide="What was the name of this horseback relay network?",
        answer="The Yam",
        reveal_slides=["It was called the Yam, a chain of mounted relay stations."],
        caption="Mongolia, 1200s: the horseback postal network that outran Europe by 600 years.",
        hashtags=["#history", "#mongolia", "#didyouknow"],
    )


@pytest.fixture
def sample_country_fact_script():
    from asma.models import CountryFactScript, HookStyle

    return CountryFactScript(
        topic_id="peru_inca_quipu_records",
        country="Peru",
        hook=HookStyle.BOLD_CLAIM,
        hook_line="The Inca had no writing system. They ran an empire of 12 million people anyway.",
        beats=[
            "Instead of writing, they used quipu.",
            "A single quipu could track census data across the empire.",
            "Most were destroyed after the conquest.",
        ],
        voiceover_script="The Inca had no writing system, yet they ran an empire of twelve million people.",
        caption="Peru: the knotted-cord system that ran an empire without writing.",
        hashtags=["#history", "#peru", "#inca"],
    )
