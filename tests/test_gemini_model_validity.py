"""Live smoke test against the real Gemini API — the one thing pure unit
tests with mocked clients can never catch: whether a configured model
name actually exists and is callable. This is exactly the bug that
shipped 2026-07-15 (config.py said "gemini-3-flash"; the real name is
"gemini-3-flash-preview" — a 404, not a 503, so it skipped the fallback
cascade entirely and crashed a live scheduled-content run). Mocks can't
tell a real model name from a typo; only a live call can.

Skipped automatically unless a real GEMINI_API_KEY is in the environment
(it isn't in CI today — see ci.yml) so this never blocks the normal
suite. Run locally with `source .env && uv run pytest tests/test_gemini_model_validity.py`
after touching CONTENT_MODEL/CONTENT_MODEL_FALLBACKS/REPLY_MODEL, or add
GEMINI_API_KEY as a CI secret to run it on every push.
"""

from __future__ import annotations

import os

import pytest
from google import genai
from google.genai import errors

from asma.config import CONTENT_MODEL, CONTENT_MODEL_FALLBACKS, REPLY_MODEL

pytestmark = [
    pytest.mark.live_gemini,
    pytest.mark.skipif(not os.environ.get("GEMINI_API_KEY"), reason="requires a real GEMINI_API_KEY in the environment"),
]


@pytest.fixture
def real_client() -> genai.Client:
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


@pytest.mark.parametrize("model", [CONTENT_MODEL, *CONTENT_MODEL_FALLBACKS, REPLY_MODEL])
def test_configured_model_exists_and_is_callable(real_client, model):
    """Not just "is in ListModels" — gemini-2.5-flash appears there too and
    still 404s as 'no longer available to new users'. A real generateContent
    call is the only thing that actually proves a model works on this key."""
    try:
        response = real_client.models.generate_content(model=model, contents="Reply with exactly: OK")
    except errors.ServerError as exc:
        # A 503 means Google recognized the model name and tried to route
        # to it — it's just momentarily overloaded, which is a real,
        # recurring condition (see config.py's CONTENT_MODEL_FALLBACKS
        # comment) and not evidence of a config mistake. A 404 (invalid
        # name, wrong tier) would raise ClientError instead and still
        # fails this test for real — that's the actual bug class this
        # test exists to catch, not transient capacity.
        pytest.skip(f"{model} is temporarily overloaded, inconclusive: {exc}")
        return
    assert response.text
