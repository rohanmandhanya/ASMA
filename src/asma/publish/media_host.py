"""Public URL hosting for rendered media, required because the Graph API's
container-create call fetches the image/video FROM a public URL rather than
accepting a direct binary upload.

Deliberately NOT using raw.githubusercontent.com — its CDN propagation
delay after a push is non-deterministic, which is exactly the kind of
flakiness that's hardest to debug on an unattended scheduled run (a
container-create call 404s or times out because the CDN hadn't caught up
yet, on a run nobody's watching).

Primary: Cloudflare R2 (S3-compatible, free tier, instant read-after-write).
Fallback: GitHub Releases assets (near-instant, purpose-built for public
artifact serving, no separate credential if R2 isn't configured) — this is
the "stay fully GitHub-native" option if preferred over adding R2.
"""

from __future__ import annotations

import logging
import mimetypes
import uuid

import boto3
import requests

from asma.config import (
    DRY_RUN,
    GITHUB_REPO,
    GITHUB_TOKEN,
    R2_ACCESS_KEY_ID,
    R2_ACCOUNT_ID,
    R2_BUCKET,
    R2_SECRET_ACCESS_KEY,
)

logger = logging.getLogger(__name__)

_GITHUB_RELEASE_TAG = "media"
_DRY_RUN_PLACEHOLDER_URL = "https://example.invalid/dry-run-placeholder"


def _r2_configured() -> bool:
    return bool(R2_ACCOUNT_ID and R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY and R2_BUCKET)


def _upload_to_r2(data: bytes, filename: str, content_type: str) -> str:
    client = boto3.client(
        "s3",
        endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )
    client.put_object(Bucket=R2_BUCKET, Key=filename, Body=data, ContentType=content_type)
    # Requires the bucket's public-access/custom-domain to be configured in
    # the Cloudflare dashboard (one-time manual setup) — verify this URL
    # shape against the actual configured public bucket domain at deploy time.
    return f"https://{R2_BUCKET}.r2.dev/{filename}"


def _upload_to_github_release(data: bytes, filename: str, content_type: str) -> str:
    if not GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN is not set — cannot use the GitHub Releases media-hosting fallback")

    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}
    base = f"https://api.github.com/repos/{GITHUB_REPO}"

    resp = requests.get(f"{base}/releases/tags/{_GITHUB_RELEASE_TAG}", headers=headers, timeout=15)
    if resp.status_code == 404:
        resp = requests.post(
            f"{base}/releases",
            headers=headers,
            json={"tag_name": _GITHUB_RELEASE_TAG, "name": "Media assets", "prerelease": True},
            timeout=15,
        )
    resp.raise_for_status()
    upload_url = resp.json()["upload_url"].split("{")[0]

    resp = requests.post(
        upload_url,
        headers={**headers, "Content-Type": content_type},
        params={"name": filename},
        data=data,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["browser_download_url"]


def upload_media(data: bytes, *, extension: str) -> str:
    """Returns a public URL Meta's servers can fetch the file from.
    extension should include the dot, e.g. '.png' or '.mp4'."""
    if DRY_RUN:
        logger.info("[DRY_RUN] media_host: skipping real upload (%d bytes)", len(data))
        return _DRY_RUN_PLACEHOLDER_URL

    filename = f"{uuid.uuid4().hex}{extension}"
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

    if _r2_configured():
        return _upload_to_r2(data, filename, content_type)
    return _upload_to_github_release(data, filename, content_type)
