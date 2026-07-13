from __future__ import annotations

from datetime import datetime, timezone

from asma.render.flow_art import current_week_seed, generate_flow_art_svg


def test_same_seed_produces_byte_identical_svg():
    a = generate_flow_art_svg(width=1080, height=1350, ink="#241C13", accent="#B5502D", seed=12345)
    b = generate_flow_art_svg(width=1080, height=1350, ink="#241C13", accent="#B5502D", seed=12345)
    assert a == b


def test_different_seed_produces_different_svg():
    a = generate_flow_art_svg(width=1080, height=1350, ink="#241C13", accent="#B5502D", seed=1)
    b = generate_flow_art_svg(width=1080, height=1350, ink="#241C13", accent="#B5502D", seed=2)
    assert a != b


def test_svg_is_well_formed_and_sized_to_canvas():
    svg = generate_flow_art_svg(width=1080, height=1350, ink="#241C13", accent="#B5502D", seed=1)
    assert svg.startswith('<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1350"')
    assert svg.endswith("</svg>")
    assert svg.count("<path") > 0


def test_current_week_seed_stable_within_the_same_iso_week():
    monday = datetime(2026, 7, 6, 3, tzinfo=timezone.utc)  # 2026-07-06 is a Monday
    sunday = datetime(2026, 7, 12, 23, tzinfo=timezone.utc)  # same ISO week
    assert current_week_seed(now=monday) == current_week_seed(now=sunday)


def test_current_week_seed_changes_the_following_week():
    this_week = datetime(2026, 7, 6, tzinfo=timezone.utc)
    next_week = datetime(2026, 7, 13, tzinfo=timezone.utc)
    assert current_week_seed(now=this_week) != current_week_seed(now=next_week)


def test_current_week_seed_changes_across_year_boundary():
    """Two different years' ISO week 1 must not collide — otherwise the art
    would silently repeat every January."""
    week_2026 = current_week_seed(now=datetime(2026, 1, 5, tzinfo=timezone.utc))
    week_2027 = current_week_seed(now=datetime(2027, 1, 4, tzinfo=timezone.utc))
    assert week_2026 != week_2027
