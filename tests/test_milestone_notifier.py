from __future__ import annotations

from asma.growth import milestone_notifier


def test_no_email_below_threshold():
    assert milestone_notifier.check_and_send_milestone_email(99) is False


def test_no_email_when_follower_count_unknown():
    assert milestone_notifier.check_and_send_milestone_email(None) is False


def test_sends_exactly_once_on_crossing():
    assert milestone_notifier.check_and_send_milestone_email(100) is True
    assert milestone_notifier.check_and_send_milestone_email(101) is False
    assert milestone_notifier.check_and_send_milestone_email(150) is False


def test_state_persisted_after_send():
    from asma.models import MilestoneState
    from asma.store.jsonl_store import read_json_state

    milestone_notifier.check_and_send_milestone_email(105)
    state = read_json_state(milestone_notifier.STATE_FILE, MilestoneState, default_factory=MilestoneState)
    assert state.hundred_followers_email_sent
    assert state.follower_count_at_send == 105


def test_never_calls_smtp_under_dry_run(monkeypatch):
    import smtplib

    def _fail(*args, **kwargs):
        raise AssertionError("smtplib.SMTP must never be constructed under DRY_RUN")

    monkeypatch.setattr(smtplib, "SMTP", _fail)
    assert milestone_notifier.check_and_send_milestone_email(200) is True
