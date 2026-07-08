#!/usr/bin/env python3
"""Refreshes the long-lived Instagram access token and writes it back as a
GitHub Actions repo secret via `gh secret set` — the default GITHUB_TOKEN
cannot write secrets, which is why GH_PAT_FOR_SECRETS (a dedicated
fine-grained PAT scoped to this repo's Secrets: write permission) exists.
Run weekly, well inside the ~60-day token lifetime. On failure, opens/
updates a tracking GitHub Issue as a zero-infra alert.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import requests  # noqa: E402

from asma.config import DRY_RUN, GH_PAT_FOR_SECRETS, GITHUB_REPO  # noqa: E402
from asma.publish.graph_client import refresh_long_lived_token  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("run_refresh_token")

_FAILURE_ISSUE_TITLE = "🔴 Token refresh failed"


def _open_or_update_failure_issue(error_text: str) -> None:
    headers = {"Authorization": f"Bearer {GH_PAT_FOR_SECRETS}", "Accept": "application/vnd.github+json"}
    base = f"https://api.github.com/repos/{GITHUB_REPO}"
    resp = requests.get(f"{base}/issues", headers=headers, params={"state": "open"}, timeout=15)
    resp.raise_for_status()
    existing = [i for i in resp.json() if i["title"] == _FAILURE_ISSUE_TITLE]
    if existing:
        requests.post(
            f"{base}/issues/{existing[0]['number']}/comments",
            headers=headers,
            json={"body": f"Still failing:\n\n```\n{error_text}\n```"},
            timeout=15,
        ).raise_for_status()
    else:
        requests.post(
            f"{base}/issues",
            headers=headers,
            json={"title": _FAILURE_ISSUE_TITLE, "body": f"```\n{error_text}\n```", "labels": ["ops"]},
            timeout=15,
        ).raise_for_status()


def main() -> int:
    try:
        new_token, expires_in = refresh_long_lived_token()
    except Exception as exc:  # noqa: BLE001 — deliberately broad: any failure here must alert, not crash silently
        logger.error("token refresh failed: %s", exc)
        if not DRY_RUN:
            _open_or_update_failure_issue(str(exc))
        return 1

    if DRY_RUN:
        logger.info("[DRY_RUN] would set IG_ACCESS_TOKEN secret (expires_in=%s)", expires_in)
        return 0

    result = subprocess.run(
        ["gh", "secret", "set", "IG_ACCESS_TOKEN", "--body", new_token, "--repo", GITHUB_REPO],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error("gh secret set failed: %s", result.stderr)
        _open_or_update_failure_issue(result.stderr)
        return 1

    logger.info("IG_ACCESS_TOKEN refreshed (expires_in=%s seconds)", expires_in)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
