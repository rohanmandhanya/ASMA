"""Instagram Graph API client — Instagram Login flow (Business Login for
Instagram), not the Facebook Page-linked flow. Deliberately chosen: this
account only needs Instagram followers, not any Facebook Page presence, and
this flow authenticates the Instagram account directly (no Facebook Page,
no Facebook Login for Business/Messenger products in the Meta app). Every
method funnels through `_request()` — the single low-level HTTP call — so
DRY_RUN interception lives in exactly one place instead of being duplicated
per method. Under DRY_RUN, `_request` logs the intended call and returns a
structurally-valid fake response, so all the higher-level polling/logging/
error-handling logic in this file still gets exercised without ever
touching the network.

Field names and endpoint shapes below reflect the Graph API's stable,
well-documented content-publishing surface (image_url/video_url -> creation
container -> media_publish) — that part of the API surface is the same
regardless of login flow, only the host and token type differ. Graph API
specifics do drift between doc versions — verify against current Meta docs
before the first real (non-DRY_RUN) call, per the plan's phased rollout.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import requests

from asma.config import DRY_RUN, IG_ACCESS_TOKEN, IG_BUSINESS_ACCOUNT_ID

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = "v22.0"  # verify this is still current at deploy time
# graph.instagram.com (not graph.facebook.com) — the Instagram Login flow's
# host; container/publish/comments/insights endpoints share the same shape
# across both login flows, so only this base URL differs.
GRAPH_API_BASE = f"https://graph.instagram.com/{GRAPH_API_VERSION}"
IG_TOKEN_REFRESH_URL = "https://graph.instagram.com/refresh_access_token"

CONTAINER_POLL_INTERVAL_SECONDS = 5
CONTAINER_POLL_TIMEOUT_IMAGE_SECONDS = 60
CONTAINER_POLL_TIMEOUT_VIDEO_SECONDS = 600  # video processing is meaningfully slower than image


class GraphAPIError(RuntimeError):
    pass


class ContainerNotReadyError(RuntimeError):
    """Raised if a container never reaches FINISHED within the poll timeout."""


@dataclass
class _FakeResponse:
    """DRY_RUN stand-in for requests.Response — just enough surface for
    graph_client's own code to treat it identically to a real response."""

    _json: dict[str, Any] = field(default_factory=dict)
    status_code: int = 200

    def json(self) -> dict[str, Any]:
        return self._json

    def raise_for_status(self) -> None:
        return None


def _request(method: str, path: str, *, params: dict | None = None, json: dict | None = None) -> Any:
    params = dict(params or {})
    params.setdefault("access_token", IG_ACCESS_TOKEN)

    if DRY_RUN:
        logger.info("[DRY_RUN] graph_client: %s %s params=%s json=%s", method, path, _redact(params), json)
        return _FakeResponse(_json=_fake_response_for(path))

    url = path if path.startswith("http") else f"{GRAPH_API_BASE}/{path}"
    resp = requests.request(method, url, params=params, json=json, timeout=30)
    if resp.status_code >= 400:
        raise GraphAPIError(f"{method} {path} -> {resp.status_code}: {resp.text[:500]}")
    return resp


def _redact(params: dict) -> dict:
    return {k: ("***" if k == "access_token" else v) for k, v in params.items()}


def _fake_response_for(path: str) -> dict:
    """Structurally-valid fake payloads per endpoint shape, so DRY_RUN runs
    exercise the same parsing code real responses would hit."""
    if path.endswith("/media") or path == "media":
        return {"id": "DRYRUN_CONTAINER_0000000000"}
    if path.endswith("/media_publish"):
        return {"id": "DRYRUN_MEDIA_0000000000"}
    if path.endswith("/comments"):
        return {"data": []}
    if path.endswith("/replies"):
        return {"id": "DRYRUN_COMMENT_0000000000"}
    if "insights" in path:
        return {"data": []}
    if IG_TOKEN_REFRESH_URL in path:
        return {"access_token": "DRYRUN_REFRESHED_TOKEN", "expires_in": 5184000}
    return {"followers_count": 0, "id": IG_BUSINESS_ACCOUNT_ID or "DRYRUN_ACCOUNT"}


# ---------------------------------------------------------------------------
# Container create / publish
# ---------------------------------------------------------------------------


def create_image_container(image_url: str, *, caption: str | None = None, is_carousel_item: bool = False) -> str:
    params: dict[str, Any] = {"image_url": image_url}
    if caption is not None:
        params["caption"] = caption
    if is_carousel_item:
        params["is_carousel_item"] = "true"
    resp = _request("POST", f"{IG_BUSINESS_ACCOUNT_ID}/media", params=params)
    return resp.json()["id"]


def create_carousel_container(children_ids: list[str], *, caption: str) -> str:
    params = {"media_type": "CAROUSEL", "children": ",".join(children_ids), "caption": caption}
    resp = _request("POST", f"{IG_BUSINESS_ACCOUNT_ID}/media", params=params)
    return resp.json()["id"]


def create_video_container(video_url: str, *, caption: str, media_type: str = "REELS") -> str:
    params = {"media_type": media_type, "video_url": video_url, "caption": caption}
    resp = _request("POST", f"{IG_BUSINESS_ACCOUNT_ID}/media", params=params)
    return resp.json()["id"]


def create_story_container(image_url: str) -> str:
    params = {"media_type": "STORIES", "image_url": image_url}
    resp = _request("POST", f"{IG_BUSINESS_ACCOUNT_ID}/media", params=params)
    return resp.json()["id"]


def poll_container_until_finished(container_id: str, *, is_video: bool = False) -> None:
    if DRY_RUN:
        logger.info("[DRY_RUN] graph_client: skipping container poll for %s", container_id)
        return

    timeout = CONTAINER_POLL_TIMEOUT_VIDEO_SECONDS if is_video else CONTAINER_POLL_TIMEOUT_IMAGE_SECONDS
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = _request("GET", str(container_id), params={"fields": "status_code,status"})
        body = resp.json()
        status_code = body.get("status_code")
        if status_code == "FINISHED":
            return
        if status_code == "ERROR":
            # status_code alone ("ERROR") never says why — `status` carries
            # Meta's human-readable reason (e.g. a fetch failure vs. an
            # unsupported video format), which is exactly what's needed to
            # tell those failure modes apart after the fact.
            detail = body.get("status", "no further detail returned")
            raise GraphAPIError(f"container {container_id} entered ERROR state: {detail}")
        time.sleep(CONTAINER_POLL_INTERVAL_SECONDS)
    raise ContainerNotReadyError(f"container {container_id} did not finish within {timeout}s")


def publish_container(container_id: str) -> str:
    resp = _request("POST", f"{IG_BUSINESS_ACCOUNT_ID}/media_publish", params={"creation_id": container_id})
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


def list_comments(media_id: str) -> list[dict]:
    resp = _request("GET", f"{media_id}/comments", params={"fields": "id,username,text,timestamp"})
    return resp.json().get("data", [])


def reply_to_comment(comment_id: str, text: str) -> str:
    resp = _request("POST", f"{comment_id}/replies", params={"message": text})
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# Insights
# ---------------------------------------------------------------------------


def get_account_insights() -> dict:
    resp = _request("GET", str(IG_BUSINESS_ACCOUNT_ID), params={"fields": "followers_count"})
    return resp.json()


def get_media_insights(media_id: str, *, is_video: bool = False) -> dict:
    metrics = "likes,comments,saved,shares,reach,impressions"
    if is_video:
        metrics += ",video_view_total_time,ig_reels_avg_watch_time"
    resp = _request("GET", f"{media_id}/insights", params={"metric": metrics})
    return {row["name"]: row.get("values", [{}])[0].get("value") for row in resp.json().get("data", [])}


# ---------------------------------------------------------------------------
# Token refresh
# ---------------------------------------------------------------------------


def refresh_long_lived_token() -> tuple[str, int]:
    """Returns (new_token, expires_in_seconds). Called by refresh-token.yml,
    which is responsible for writing the result to the IG_ACCESS_TOKEN repo
    secret via `gh secret set` — this function only talks to Meta."""
    resp = _request(
        "GET",
        IG_TOKEN_REFRESH_URL,
        params={"grant_type": "ig_refresh_token", "access_token": IG_ACCESS_TOKEN},
    )
    data = resp.json()
    return data["access_token"], data.get("expires_in", 0)
