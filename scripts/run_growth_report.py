#!/usr/bin/env python3
"""Daily follower digest + 100-follower milestone check. Run by
growth-report.yml."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from asma.config import GITHUB_REPO  # noqa: E402
from asma.growth import growth_report, metrics_collector, milestone_notifier  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("run_growth_report")


def main() -> int:
    snapshot = metrics_collector.collect_account_snapshot()
    follower_count = snapshot.follower_count

    growth_report.post_daily_digest(follower_count)

    account_url = f"https://github.com/{GITHUB_REPO}"  # placeholder link until the real IG handle is set
    sent = milestone_notifier.check_and_send_milestone_email(follower_count, account_url=account_url)
    if sent:
        logger.info("100-follower milestone email sent (followers=%s)", follower_count)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
