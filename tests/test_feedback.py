from __future__ import annotations

from asma.growth import feedback
from asma.models import ContentFormat, MetricSnapshot, PostRecord


def test_carousel_score_weights_saves_and_shares():
    post = PostRecord(
        post_id="p1", ig_media_id="m1", format=ContentFormat.QUIZ_CAROUSEL, caption="c", hashtags=["#a", "#b", "#c"]
    )
    high_saves = MetricSnapshot(post_id="p1", reach=1000, saves=100, shares=50, comments=10, likes=200)
    low_saves = MetricSnapshot(post_id="p1", reach=1000, saves=0, shares=0, comments=0, likes=10)

    assert feedback.compute_engagement_score(post, high_saves) > feedback.compute_engagement_score(post, low_saves)


def test_reel_score_uses_hold_rate():
    post = PostRecord(
        post_id="p1", ig_media_id="m1", format=ContentFormat.COUNTRY_FACT_REEL, caption="c", hashtags=["#a", "#b", "#c"]
    )
    strong = MetricSnapshot(post_id="p1", video_hold_rate_3s=0.8)
    weak = MetricSnapshot(post_id="p1", video_hold_rate_3s=0.2)
    assert feedback.compute_engagement_score(post, strong) > feedback.compute_engagement_score(post, weak)


def test_sparse_insights_degrade_gracefully_not_crash():
    post = PostRecord(
        post_id="p1", ig_media_id="m1", format=ContentFormat.QUIZ_CAROUSEL, caption="c", hashtags=["#a", "#b", "#c"]
    )
    empty_snapshot = MetricSnapshot(post_id="p1")  # brand-new account, no reach data yet
    score = feedback.compute_engagement_score(post, empty_snapshot)
    assert 0.0 <= score <= 1.0


def test_performance_summary_empty_when_no_posts():
    summary = feedback.build_performance_summary()
    assert "No recent post performance data" in summary
