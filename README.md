# ASMA — Autonomous Social Media Agent

A fully autonomous Instagram agent: no human in the loop once running. It generates history-trivia content, renders it, posts it, replies to comments, tracks a weekly leaderboard, and reports its own growth — built for a take-home assignment (grow a brand-new account to 100 real followers, zero bots/bought engagement).

The full product reasoning — niche selection, format research, cadence design, risk tradeoffs — lives in [`/Users/rohan/.claude/plans/hey-rohan-great-meeting-typed-meteor.md`](/Users/rohan/.claude/plans/hey-rohan-great-meeting-typed-meteor.md). This README is the practical "how to actually run it" doc.

## What it posts

- **Trivia quiz carousels** (primary format): a striking historical fact → a question with a noun-form answer → the reveal. Ends with *"Try to stump the bot"* to pull substantive comments, not one-word guesses.
- **"A beautiful old fact about [country]" Reels**: recurring format, rotates across ~80 countries — deliberately never concentrates on one culture.
- **Weekly winner Reels**: recognizes whoever answered the most quiz questions correctly that week.
- Every quiz carousel gets an accompanying Story.

Niche is forgotten/lesser-known history — historian-consensus facts only, respectful tone, never a contested statistic stated as settled. See `src/asma/content/prompts.py` and `guardrails.py` for exactly what's enforced by the model vs. enforced in code.

## Non-goals (enforced, not just documented)

No follow/unfollow automation, no auto-liking, no DM automation, no purchased engagement, no scraping any platform (Instagram or TikTok — both against ToS), no reproducing real copyrighted footage/artwork. Every visual is an original rendered card; every Reel is TTS narration over those same cards with a Ken Burns pan — nothing pulled from elsewhere.

## Architecture

```
src/asma/
├── config.py              # secrets, cadence ramp, rate limits, the 88-entry topic/country pool
├── models.py               # Pydantic schemas — the client.messages.parse() targets + on-disk record shapes
├── content/                 # topic selection, trend research, guardrails, Claude generation
├── render/                  # Jinja2 + Playwright → PNG cards
├── video/                    # TTS + ffmpeg Ken Burns assembly → Reels-spec MP4
├── publish/                  # Instagram Graph API client, media hosting, rate limiting
├── engagement/               # comment reply + answer-tracking/leaderboard
└── growth/                    # metrics, EMA feedback loop, cadence budget, growth digest, milestone email

scripts/                       # one entrypoint per GitHub Actions workflow
.github/workflows/             # the entire runtime — see each file for its cron schedule
data/                          # committed, append-only JSONL/JSON — the agent's entire memory
```

**Everything funnels through one low-level `_request()`/subprocess call per external system** (`publish/graph_client.py`, `video/tts.py`, `video/assembler.py`, `growth/milestone_notifier.py`) — that's where `DRY_RUN` is intercepted, so dry-run mode exercises every layer of real logic (polling, error handling, retries) without ever touching a real network call.

## Local setup

```bash
uv sync
uv run playwright install --with-deps chromium
brew install ffmpeg   # or apt-get install ffmpeg — GitHub Actions runners have it preinstalled
cp .env.example .env  # fill in what you have; DRY_RUN=true needs none of it
```

Run the test suite (58 tests, all offline — mocked Claude/Graph API, but real Playwright rendering and real ffmpeg encoding):

```bash
uv run pytest -v
uv run ruff check src/ tests/ scripts/
```

Generate one real post end-to-end without touching Instagram (this **does** call the real Anthropic API and render real cards — only the Graph API/TTS/media-hosting side effects are stubbed):

```bash
DRY_RUN=true ANTHROPIC_API_KEY=sk-... uv run python scripts/manual_post_once.py --format quiz_carousel
```

## Manual setup steps (not automatable — do these once, in order)

1. **Meta app + Page + Instagram Business account.** Create a Meta Business/Developer app, a Facebook Page, convert the (new) Instagram account to Professional/Business, and link it to the Page.
2. **Add the Instagram account as a tester** on the Meta app, in Development Mode. This is what lets the app act on this one account indefinitely without Meta's multi-week App Review — that review is only required to serve *other* users' accounts, which this app never does.
3. **Mint a long-lived access token** with `instagram_business_basic` + `instagram_business_content_publish`. Add it, the business account ID, and the app ID/secret as repo secrets (see the table below).
4. **Set the bio** to disclose the account is AI-run. One-time, done by hand in the Instagram app — not cleanly reachable via this permission scope.
5. **TTS provider**: sign up for ElevenLabs (or swap providers in `video/tts.py`), add the API key as a secret.
6. **Media hosting**: either set up a free Cloudflare R2 bucket (`R2_*` secrets) or leave it unset — `media_host.py` falls back to GitHub Releases automatically, using the repo's own `GITHUB_TOKEN`, no extra signup required.
7. **Milestone email**: generate an SMTP app password on an existing email account (Gmail: Settings → 2-Step Verification → App Passwords) and add `SMTP_USERNAME`/`SMTP_APP_PASSWORD` as secrets.
8. **Secret-rotation PAT**: create a fine-grained GitHub PAT scoped to this repo's "Secrets: write" permission only, add it as `GH_PAT_FOR_SECRETS`. This is deliberately the *only* place a broad token is used — everything else uses the workflow's own scoped `GITHUB_TOKEN`.

### Repo secrets

| Secret | Used by |
|---|---|
| `ANTHROPIC_API_KEY` | content generation, comment replies, trend research |
| `TTS_API_KEY` | Reel voiceovers |
| `IG_ACCESS_TOKEN`, `IG_BUSINESS_ACCOUNT_ID` | every Graph API call |
| `FB_APP_ID`, `FB_APP_SECRET` | reference for the manual token-minting step |
| `GH_PAT_FOR_SECRETS` | **only** `refresh-token.yml`'s `gh secret set` call |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` | optional — media hosting; omit to use the GitHub Releases fallback |
| `SMTP_USERNAME`, `SMTP_APP_PASSWORD` | the one-time 100-follower email |

## Phased rollout

1. Dry-run the carousel path locally (above) until the content and card design look right.
2. Dry-run the Reel path (`--format country_fact_reel`) — needs a real `TTS_API_KEY` to hear actual output.
3. Do the manual setup steps above.
4. Trigger `scheduled-content.yml` manually with `dry_run=false` for one carousel, confirm it *and* its Story publish correctly in the actual app. Then one Reel. Then one manual `engage-comments.yml` run against a seeded test comment. Then one manual `refresh-token.yml` run — **do this now**, not on day ~55 when the token is actually about to expire.
5. Enable all five workflow schedules. Cadence starts at 1 post/day and ramps to 5/day over roughly two weeks (`config.CADENCE_RAMP`) — deliberately slow, because Instagram's own guidance names sudden high-volume posting on a new account as a spam-detection trigger.
6. Watch the pinned "📈 Growth Tracker" GitHub Issue for the daily digest. The 100-follower email fires once, automatically, the day it happens.

## What's genuinely unverified

Everything above ran and passed against real Playwright, real ffmpeg, and a fully mocked Graph API/Claude — see `tests/`. What hasn't been exercised against the *live* Instagram Graph API (no Meta app exists yet, and this environment has no `ANTHROPIC_API_KEY` to test real content generation either): exact container field names for Reels/Stories, real container-processing timing, real Insights payload shape on a brand-new account, and the real SMTP send. All flagged inline in the relevant modules (`graph_client.py`, `milestone_notifier.py`) with what to verify before trusting them unattended — that's step 4 above, not a formality.
