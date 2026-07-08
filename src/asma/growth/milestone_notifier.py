"""One-time email to nate@kiloforge.com the moment the account first
crosses 100 followers — the actual deliverable signal for the assignment.
Sent via plain SMTP (an app password on an existing email account — no new
third-party service required). Idempotent: data/milestone_state.json is
checked before sending and set immediately after, so a follower count that
stays >=100 across many days never sends a second email.
"""

from __future__ import annotations

import logging
import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText

from asma.config import (
    DRY_RUN,
    MILESTONE_EMAIL_TO,
    SMTP_APP_PASSWORD,
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USERNAME,
)
from asma.models import MilestoneState
from asma.store.jsonl_store import read_json_state, write_json_state

logger = logging.getLogger(__name__)

STATE_FILE = "milestone_state.json"
FOLLOWER_MILESTONE = 100


def _build_email(follower_count: int, account_url: str) -> MIMEText:
    body = (
        f"We just hit {follower_count} followers. 🎉\n\n"
        f"Account: {account_url}\n"
        f"Crossed 100 on: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n\n"
        f"Buy me lunch now 😛"
    )
    msg = MIMEText(body)
    msg["Subject"] = "The Instagram agent just hit 100 followers"
    msg["From"] = SMTP_USERNAME or "asma-agent@localhost"
    msg["To"] = MILESTONE_EMAIL_TO
    return msg


def _send(msg: MIMEText) -> None:
    if not (SMTP_USERNAME and SMTP_APP_PASSWORD):
        raise RuntimeError("SMTP_USERNAME/SMTP_APP_PASSWORD are not set — cannot send the milestone email")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_APP_PASSWORD)
        server.send_message(msg)


def check_and_send_milestone_email(follower_count: int | None, *, account_url: str = "") -> bool:
    """Returns True if an email was sent (or would have been, under
    DRY_RUN) this call, False otherwise (below threshold, or already
    sent previously)."""
    if follower_count is None or follower_count < FOLLOWER_MILESTONE:
        return False

    state = read_json_state(STATE_FILE, MilestoneState, default_factory=MilestoneState)
    if state.hundred_followers_email_sent:
        return False

    msg = _build_email(follower_count, account_url)

    if DRY_RUN:
        logger.info("[DRY_RUN] milestone_notifier: would send milestone email now (%d followers)", follower_count)
    else:
        _send(msg)

    write_json_state(
        STATE_FILE,
        MilestoneState(
            hundred_followers_email_sent=True,
            sent_at=datetime.now(timezone.utc),
            follower_count_at_send=follower_count,
        ),
    )
    return True
