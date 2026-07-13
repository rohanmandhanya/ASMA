# ASMA — Autonomous Social Media Agent

A fully autonomous Instagram agent: no human in the loop once running. It generates history-trivia content, renders it, posts it, replies to comments, tracks a weekly leaderboard, and reports its own growth — built for a take-home assignment (grow a brand-new account to 100 real followers, zero bots/bought engagement).

The full product reasoning — niche selection, format research, cadence design, risk tradeoffs — lives in [`/Users/rohan/.claude/plans/hey-rohan-great-meeting-typed-meteor.md`](/Users/rohan/.claude/plans/hey-rohan-great-meeting-typed-meteor.md). This README is the practical "how to actually run it" doc.

## What it posts

- **"A beautiful old fact about [country]" Reels** (lead format for the launch push, ~70% of the mix): narrated over one full-bleed AI-generated illustration per Reel (`render/background_client.py`, prompted from that Reel's country/fact), rotating across ~80 countries and deliberately never concentrating on one culture. Reels reach 3-5x more non-followers than carousels, which is the audience a brand-new account actually needs. Falls back to the existing flat theme background if generation is ever unavailable.
- **Trivia quiz carousels** (~30% of the mix): a striking fact → a question with a noun-form answer → the reveal. Each post gets one full-bleed generative "flow field" background behind its text (`render/flow_art.py` — deterministic line-art traced through a simple vector field, no API, no key). The background is stable for an entire ISO week and rotates the following week, so the account has a consistent, recognizable "current look" rather than a different AI-attempted scene per fact. Pure local computation, so it never fails or degrades — unlike the Reels' per-post AI illustration below. Ends with *"Try to stump the bot"* to pull substantive comments, not one-word guesses — the account is openly run by an AI agent, so "the bot" reads as a plain, literal invitation.
  - **~30% of carousel topics are pop culture** (movies/TV/sports production trivia, records, and real-world facts — never plot spoilers or subjective rankings, and never simply "which movie/show is this" — the title is named openly, the quiz mystery is a specific hidden detail), the rest history — see "Niche" below for why this stays scoped to the carousel share only, not the Reels.
- **Weekly winner Reels**: recognizes whoever answered the most quiz questions correctly that week — also with a generated background (no country to seed the prompt with, so it falls back to a generic celebratory scene instead).
- Every quiz carousel gets an accompanying Story.

## Niche: history-primary, pop culture as a scoped minority

The core niche is forgotten/lesser-known history — historian-consensus facts only, respectful tone, never a contested statistic stated as settled. Alongside it, `config.POP_CULTURE_TOPIC_WEIGHT` (0.3) sends a minority of quiz-carousel *topic picks* to a second, separately-guardrailed pool: movies/TV/sports trivia (`config.POP_CULTURE_TOPIC_POOL`), scoped to production trivia, records, and real-world facts — never plot spoilers, never a subjective ranking presented as fact, never verbatim copyrighted dialogue/lyrics (`content/prompts.py`'s pop-culture system prompt + `guardrails.check_no_spoiler_cues`).

This is a deliberate trade-off, not a free lunch: Instagram's 2026 ranking reads an account's last 9-12 posts to build a "topic graph" for Explore/Reels-tab targeting, and mixed-category content measurably hurts that categorization relative to a single focused niche — confirmed by research at the time this was added, done specifically to check the cost before making the call. Two things bound the damage:
- **Reels stay pure history.** `topic_selector.select_country_fact_country()` explicitly filters to history-category topics only, so the majority-weight (~70%), reach-optimized Reel format never dilutes. The mix lives entirely inside the minority-weight (~30%) carousel format.
- **Both categories flow through the same mechanism, topic-tagged.** `config.Topic.category` (`"history"` / `"pop_culture"`) drives which system-prompt guardrails a post gets (`content/prompts.py:quiz_card_system_prompt()`) and is force-set on the generated `QuizCard` the same way `topic_id`/`country`/`hook` already are — never model-chosen.

See `src/asma/content/prompts.py` and `guardrails.py` for exactly what's enforced by the model vs. enforced in code.

Reels' illustration is a still AI-generated image, not a talking avatar — a much lighter ask of a generative API (Pollinations.ai, free — see below), seconds not a lip-sync pipeline. Quiz carousels don't use that API at all — their background is generated locally (`render/flow_art.py`), which is also why they have no failure mode to fall back from.

## Non-goals (enforced, not just documented)

No follow/unfollow automation, no auto-liking, no DM automation, no purchased engagement, no scraping any platform (Instagram or TikTok — both against ToS), no reproducing real copyrighted footage/artwork. Every visual is an original rendered card; every Reel is TTS narration over those same cards with a Ken Burns pan — cards are joined with a short crossfade (ffmpeg `xfade`, chained across all of a Reel's cards) rather than a hard cut — mixed with a low-volume background bed, nothing pulled from elsewhere. That bed is originally synthesized (`assets/audio/*.mp3` — layered sine tones via ffmpeg, not a sampled or licensed track), same "don't reproduce someone else's copyrighted work" principle applied to audio.

## Architecture

```
src/asma/
├── config.py              # secrets, cadence ramp, rate limits, the 88-entry topic/country pool
├── models.py               # Pydantic schemas — the client.messages.parse() targets + on-disk record shapes
├── content/                 # topic selection, trend research, guardrails, Gemini generation
├── render/                  # Jinja2 + Playwright → PNG cards
├── video/                    # TTS + ffmpeg Ken Burns assembly + background bed mixing → Reels-spec MP4
├── publish/                  # Instagram Graph API client, media hosting, rate limiting
├── engagement/               # comment reply + answer-tracking/leaderboard
└── growth/                    # metrics, EMA feedback loop, cadence budget, growth digest, milestone email

scripts/                       # one entrypoint per GitHub Actions workflow
.github/workflows/             # the entire runtime — see each file for its cron schedule
data/                          # committed, append-only JSONL/JSON — the agent's entire memory
```

**Everything funnels through one low-level `_request()`/subprocess call per external system** (`publish/graph_client.py`, `video/tts.py`, `video/assembler.py`, `growth/milestone_notifier.py`, `render/background_client.py`) — that's where `DRY_RUN` is intercepted, so dry-run mode exercises every layer of real logic (polling, error handling, retries) without ever touching a real network call.

## Local setup

```bash
uv sync
uv run playwright install --with-deps chromium
brew install ffmpeg   # or apt-get install ffmpeg — GitHub Actions runners have it preinstalled
cp .env.example .env  # fill in what you have; DRY_RUN=true needs none of it
```

Run the test suite (94 tests, all offline — mocked Gemini/Graph API/background-image API, but real Playwright rendering (including real, locally-generated flow-art quiz backgrounds) and real ffmpeg encoding, including real audio mixing, crossfade transitions, and real Piper speech synthesis on Linux — 1 test skips on macOS due to the wheel bug noted above):

```bash
uv run pytest -v
uv run ruff check src/ tests/ scripts/
```

Generate one real post end-to-end without touching Instagram (this **does** call the real Gemini API and render real cards — only the Graph API/media-hosting side effects are stubbed):

```bash
DRY_RUN=true GEMINI_API_KEY=... uv run python scripts/manual_post_once.py --format quiz_carousel
```

To hear real voiceover output too (`DRY_RUN=false`), download the Piper voice model once:

```bash
uv run python -m piper.download_voices en_GB-alan-medium --download-dir assets/tts
```

**macOS note**: `piper-tts`'s macOS PyPI wheel has a verified packaging bug (a hardcoded build-machine path to its bundled espeak-ng data) that breaks real synthesis on Mac entirely, independent of any system `espeak-ng` install — confirmed by direct testing. The Linux wheel (what the actual GitHub Actions runners use) does not have this bug — confirmed by running the identical synthesis call inside a `python:3.12-slim` container. `DRY_RUN=true` never touches Piper at all, so this only blocks manually testing real audio locally on a Mac, not production. See `assets/tts/README.md`.

## Manual setup steps (not automatable — do these once, in order)

1. **Meta app + Instagram Professional account.** Create a Meta Business/Developer app and add the **"Instagram API setup with Instagram login"** product (not Facebook Login for Business/Messenger — this project deliberately uses the Instagram Login flow, not the Facebook Page-linked one, since the account only needs Instagram followers). Convert the (new) Instagram account to Professional (Business or Creator both work here) — no Facebook Page required.
2. **Add the Instagram account as a tester** on the Meta app (App Roles → Roles → Add People → Instagram Tester), in Development Mode. Accept the invite from the Instagram account itself (Settings → Website permissions → Apps and websites → Tester invitations). This is what lets the app act on this one account indefinitely without Meta's multi-week App Review — that review is only required to serve *other* users' accounts, which this app never does.
3. **Mint a long-lived access token** with `instagram_business_basic` + `instagram_business_content_publish`, authenticating directly as the Instagram account (Instagram Login, not a Facebook Page token). Add it, the Instagram user ID, and the app ID/secret as repo secrets (see the table below).
4. **Set the bio** to disclose the account is AI-run. One-time, done by hand in the Instagram app — not cleanly reachable via this permission scope.
5. **Background-image provider** (optional, and free either way): Reel illustrations use Pollinations.ai (`render/background_client.py`), which needs **no signup at all** to work — anonymous requests generate real images, just watermarked and rate-limited to ~1 request/15s. Optionally register a free account at auth.pollinations.ai (no card) and set `POLLINATIONS_API_TOKEN` to remove the watermark and get a faster rate tier. Used only by Reels (both types) — quiz carousels generate their own background locally and never call this API. Falls back to the flat theme background if a call ever fails. (Voiceovers, background music, and quiz-carousel backgrounds also need **no signup at all** — Piper (TTS), the bundled ambient beds, and `render/flow_art.py` are all free and self-contained; see above, `assets/audio/`, and `render/flow_art.py`.)
6. **Media hosting**: either set up a free Cloudflare R2 bucket (`R2_*` secrets) or leave it unset — `media_host.py` falls back to GitHub Releases automatically, using the repo's own `GITHUB_TOKEN`, no extra signup required.
7. **Milestone email**: generate an SMTP app password on an existing email account (Gmail: Settings → 2-Step Verification → App Passwords) and add `SMTP_USERNAME`/`SMTP_APP_PASSWORD` as secrets.
8. **Secret-rotation PAT**: create a fine-grained GitHub PAT scoped to this repo's "Secrets: write" permission only, add it as `GH_PAT_FOR_SECRETS`. This is deliberately the *only* place a broad token is used — everything else uses the workflow's own scoped `GITHUB_TOKEN`.

### Repo secrets

| Secret | Used by |
|---|---|
| `GEMINI_API_KEY` | content generation, comment replies, trend research — free tier covers this project's entire call volume |
| `POLLINATIONS_API_TOKEN` | Reel background illustrations only, and optional even there — Pollinations.ai works with no token (watermarked); a free token just removes the watermark and raises the rate limit. Quiz carousels never call this, see `render/flow_art.py` |
| `IG_ACCESS_TOKEN`, `IG_BUSINESS_ACCOUNT_ID` | every Graph API call |
| `IG_APP_ID`, `IG_APP_SECRET` | reference for the manual token-minting step (Instagram Login flow, not a Facebook app) |
| `GH_PAT_FOR_SECRETS` | **only** `refresh-token.yml`'s `gh secret set` call |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` | optional — media hosting; omit to use the GitHub Releases fallback |
| `SMTP_USERNAME`, `SMTP_APP_PASSWORD` | the one-time 100-follower email |

No TTS secret — voiceovers use Piper (local, free, offline neural TTS), not a paid API. This was a deliberate swap: unlike the background-image generation, `synthesize_voiceover()` has no graceful fallback (a Reel with no narration is a broken Reel), so it was the one recurring paid dependency in the whole pipeline with no optional-ness to it. Piper removes that cost entirely.

## Phased rollout

1. Dry-run the carousel path locally (above) until the content and card design look right.
2. Dry-run the Reel path (`--format country_fact_reel`) — download the Piper voice model first (`uv run python -m piper.download_voices en_GB-alan-medium --download-dir assets/tts`) to hear actual narrated output; no API key needed.
3. Do the manual setup steps above.
4. Trigger `scheduled-content.yml` manually with `dry_run=false` for one carousel, confirm it *and* its Story publish correctly in the actual app. Then one Reel. Then one manual `engage-comments.yml` run against a seeded test comment. Then one manual `refresh-token.yml` run — **do this now**, not on day ~55 when the token is actually about to expire.
5. Enable all five workflow schedules. Cadence starts at 3 posts/day on day 0 and holds at 5/day from day 1 onward (`config.CADENCE_RAMP`) — compressed for a 7-day, 100-follower push rather than an open-ended timeline. Still a ramp (not an instant jump on a zero-history account), and `MIN_HOURS_BETWEEN_POSTS` plus the Graph API 24h cap are what actually guard against the spam-detection triggers Instagram's own guidance names (clustered bursts, not a fast ramp per se).
6. Watch the pinned "📈 Growth Tracker" GitHub Issue for the daily digest. The 100-follower email fires once, automatically, the day it happens.

## What's genuinely unverified

Everything above ran and passed against real Playwright, real ffmpeg, real Piper speech synthesis (verified in an actual `python:3.12-slim` container matching the GitHub Actions runner, not just assumed), real locally-generated flow-art quiz backgrounds, real Pollinations.ai image generation (no key needed to verify this one — see below), and a fully mocked Graph API/Gemini API — see `tests/`. The Gemini structured-output shape (`content/generator.py`'s `response_schema=`, refusal/safety-block detection) is the documented 2026 API surface, not yet exercised against a live response in this environment (no `GEMINI_API_KEY` here) — verify at deploy time, same as the Graph API notes below. What else hasn't been exercised for real (no Meta app exists yet): exact container field names for Reels/Stories, real container-processing timing, real Insights payload shape on a brand-new account, and the real SMTP send. All flagged inline in the relevant modules (`graph_client.py`, `milestone_notifier.py`, `content/generator.py`) with what to verify before trusting them unattended — that's step 4 above, not a formality.
