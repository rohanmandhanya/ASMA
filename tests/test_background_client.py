from __future__ import annotations

import pytest

from asma.render import background_client


def test_dry_run_never_makes_a_real_http_call(monkeypatch):
    monkeypatch.setattr(background_client, "DRY_RUN", True)

    def _fail(*args, **kwargs):
        raise AssertionError("requests must never be called under DRY_RUN")

    import requests

    monkeypatch.setattr(requests, "get", _fail)

    image_bytes = background_client.generate_background_image("a prompt", width=1080, height=1350)
    assert image_bytes == b""


def test_generates_with_no_token_configured(monkeypatch):
    """Unlike the FLUX setup this replaced, a missing token must NOT raise —
    Pollinations' anonymous tier still generates real (watermarked) images."""
    monkeypatch.setattr(background_client, "DRY_RUN", False)
    monkeypatch.setattr(background_client, "POLLINATIONS_API_TOKEN", None)

    import requests

    class _ImageResponse:
        status_code = 200
        content = b"fake-image-bytes"

    captured = {}

    def _fake_get(url, *, params, headers, timeout):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        return _ImageResponse()

    monkeypatch.setattr(requests, "get", _fake_get)

    image_bytes = background_client.generate_background_image("a prompt", width=1080, height=1350)
    assert image_bytes == b"fake-image-bytes"
    assert captured["url"].startswith(background_client._BASE_URL)
    assert "nologo" not in captured["params"]
    assert "Authorization" not in captured["headers"]


def test_generates_with_token_configured_adds_auth_and_nologo(monkeypatch):
    monkeypatch.setattr(background_client, "DRY_RUN", False)
    monkeypatch.setattr(background_client, "POLLINATIONS_API_TOKEN", "test-token")

    import requests

    class _ImageResponse:
        status_code = 200
        content = b"fake-image-bytes"

    captured = {}

    def _fake_get(url, *, params, headers, timeout):
        captured["params"] = params
        captured["headers"] = headers
        return _ImageResponse()

    monkeypatch.setattr(requests, "get", _fake_get)

    background_client.generate_background_image("a prompt", width=1080, height=1350)
    assert captured["params"]["nologo"] == "true"
    assert captured["headers"]["Authorization"] == "Bearer test-token"


def test_raises_on_http_error_status(monkeypatch):
    monkeypatch.setattr(background_client, "DRY_RUN", False)
    monkeypatch.setattr(background_client, "POLLINATIONS_API_TOKEN", None)

    import requests

    class _ErrorResponse:
        status_code = 500
        content = b""

    monkeypatch.setattr(requests, "get", lambda *a, **k: _ErrorResponse())

    with pytest.raises(background_client.BackgroundImageError):
        background_client.generate_background_image("a prompt", width=1080, height=1350)


def test_build_prompt_includes_country_and_fact_and_style():
    prompt = background_client.build_prompt(country="Peru", fact_text="The Inca ran an empire without writing.")
    assert "Peru" in prompt
    assert "Inca" in prompt
    assert "no text" in prompt.lower()  # style suffix present, keeps generated images text-free


def test_build_prompt_without_country_uses_generic_celebratory_scene():
    prompt = background_client.build_prompt(fact_text="This week's leaderboard champion answered seven in a row.")
    assert "leaderboard champion" in prompt
    assert "celebratory" in prompt.lower()
