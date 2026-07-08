"""Environment/secrets loading, cadence ramp schedule, rate-limit constants,
and the topic/country pool. Nothing here talks to a network — it's pure
configuration other modules import from.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str | None = None, *, required: bool = False) -> str | None:
    val = os.environ.get(name, default)
    if required and not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val


# ---------------------------------------------------------------------------
# Safety valve — checked by every network call in publish/graph_client.py,
# video/tts.py, growth/milestone_notifier.py. Defaults true so a missing env
# var fails closed (no accidental live posting), not open.
# ---------------------------------------------------------------------------
DRY_RUN: bool = _env("DRY_RUN", "true").strip().lower() in ("1", "true", "yes")

# ---------------------------------------------------------------------------
# Secrets (all optional at import time — only required when actually used,
# so `DRY_RUN=true` local dev works with no secrets configured at all)
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY = _env("ANTHROPIC_API_KEY")
TTS_API_KEY = _env("TTS_API_KEY")
IG_ACCESS_TOKEN = _env("IG_ACCESS_TOKEN")
IG_BUSINESS_ACCOUNT_ID = _env("IG_BUSINESS_ACCOUNT_ID")
FB_APP_ID = _env("FB_APP_ID")
FB_APP_SECRET = _env("FB_APP_SECRET")
GH_PAT_FOR_SECRETS = _env("GH_PAT_FOR_SECRETS")
# The default GITHUB_TOKEN (auto-provided every workflow run, scoped via
# `permissions:` in the workflow YAML) is used for everything that only
# needs contents/issues write — GH_PAT_FOR_SECRETS is reserved for the one
# operation that genuinely needs more (writing repo *secrets*, which
# GITHUB_TOKEN cannot do — see scripts/run_refresh_token.py).
GITHUB_TOKEN = _env("GITHUB_TOKEN")
# owner/repo, used by media_host.py's GitHub Releases fallback and by
# growth_report.py's pinned-issue digest. GITHUB_REPOSITORY is set
# automatically inside every GitHub Actions run; the literal default below
# only matters for local dev and should be updated once the repo exists.
GITHUB_REPO = _env("GITHUB_REPOSITORY", "rohanmandhanya/ASMA")
R2_ACCOUNT_ID = _env("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = _env("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = _env("R2_SECRET_ACCESS_KEY")
R2_BUCKET = _env("R2_BUCKET")
SMTP_HOST = _env("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(_env("SMTP_PORT", "587"))
SMTP_USERNAME = _env("SMTP_USERNAME")
SMTP_APP_PASSWORD = _env("SMTP_APP_PASSWORD")
MILESTONE_EMAIL_TO = _env("MILESTONE_EMAIL_TO", "nate@kiloforge.com")

# ---------------------------------------------------------------------------
# Model tiering — quality where it's judged, cheap where volume is high.
# ---------------------------------------------------------------------------
CONTENT_MODEL = "claude-opus-4-8"
CONTENT_MODEL_EFFORT = "high"
REPLY_MODEL = "claude-haiku-4-5"

# ---------------------------------------------------------------------------
# Instagram Graph API limits (verify against current docs at deploy time —
# these are the researched 2026 values, and Graph API specifics drift).
# ---------------------------------------------------------------------------
GRAPH_API_ROLLING_24H_POST_CAP = 25  # carousels + Stories + Reels share this bucket
GRAPH_API_HOURLY_CALL_CAP = 200

# ---------------------------------------------------------------------------
# Cadence ramp — deliberately slow, per the spam-detection research in the
# plan. `day_index` is days since scheduled-content.yml was first enabled
# (persisted in data/topics_state.json, not wall-clock date, so a paused
# rollout doesn't skip steps). Each step defines the posts/day target
# starting from that day index; the target holds until the next threshold.
# Reaches and holds at TARGET_POSTS_PER_DAY.
# ---------------------------------------------------------------------------
TARGET_POSTS_PER_DAY = 5
CADENCE_RAMP: list[tuple[int, int]] = [
    (0, 1),   # days 0-3:  1 post/day — build a posting history + engagement baseline
    (4, 2),   # days 4-6:  2 posts/day
    (7, 3),   # days 7-9:  3 posts/day
    (10, 4),  # days 10-12: 4 posts/day
    (13, TARGET_POSTS_PER_DAY),  # day 13 onward: hold at target
]
MIN_HOURS_BETWEEN_POSTS = 2.5  # spreads the day's budget out; avoids "short window" spam trigger

TOPIC_NO_REPEAT_DAYS = 14
TOPIC_EXPLORATION_RATE = 0.30  # fraction of picks that go to under-used topics rather than best-EMA

ENGAGE_REPLY_CAP_PER_RUN = 20  # keeps engage-comments.yml well under the ~140 interactions/day spam threshold
CAPTION_DEDUP_WINDOW_DAYS = 30
HASHTAGS_MIN = 3
HASHTAGS_MAX = 5

# ---------------------------------------------------------------------------
# Reel video spec (Reels-tab eligibility requires landing inside this range)
# ---------------------------------------------------------------------------
REEL_MIN_SECONDS = 5
REEL_MAX_SECONDS = 90
REEL_ASPECT_RATIO = (1080, 1920)
CAROUSEL_ASPECT_RATIO = (1080, 1350)


@dataclass(frozen=True)
class Topic:
    topic_id: str
    country: str
    seed_angle: str


# ---------------------------------------------------------------------------
# Topic/country pool. Deliberately spread across every inhabited continent —
# this is the guardrail against "digital colonialism"/single-culture
# concentration as much as it is a content-sourcing list. `seed_angle` gives
# Claude a starting point; it still does its own historian-consensus
# generation and citation, guided by content/prompts.py's guardrails — this
# list is not a source of truth for facts, just a topic-rotation seed.
#
# Sized to 75+ entries: at the 5/day target cadence and a 14-day no-repeat
# window, at least 14*5=70 distinct entries are needed to avoid repeating;
# this pool has real exploration headroom above that floor.
# ---------------------------------------------------------------------------
TOPIC_POOL: list[Topic] = [
    # Asia
    Topic("mongolia_yam_relay", "Mongolia", "the Mongol Empire's Yam postal relay system, centuries ahead of European mail networks"),
    Topic("china_zheng_he_fleet", "China", "Zheng He's early-1400s treasure fleet, decades before and vastly larger than Columbus's ships"),
    Topic("india_nalanda_university", "India", "Nalanda, a residential university drawing students from across Asia a thousand years before Oxford"),
    Topic("japan_edo_recycling", "Japan", "Edo-period Japan's closed-loop recycling economy — almost nothing was thrown away"),
    Topic("indonesia_borobudur", "Indonesia", "Borobudur's construction and rediscovery after centuries buried under volcanic ash and jungle"),
    Topic("cambodia_angkor_hydraulics", "Cambodia", "Angkor's hydraulic engineering — a medieval city larger than any in Europe at the time"),
    Topic("iran_cyrus_cylinder", "Iran", "the Cyrus Cylinder and its early declaration of religious tolerance"),
    Topic("iraq_house_of_wisdom", "Iraq", "Baghdad's House of Wisdom and its role preserving and translating classical knowledge"),
    Topic("turkey_hagia_sophia_dome", "Turkey", "the engineering of Hagia Sophia's dome, unmatched for centuries"),
    Topic("sri_lanka_ancient_tanks", "Sri Lanka", "Sri Lanka's ancient irrigation tank cascade systems, still partly functional today"),
    Topic("vietnam_trung_sisters", "Vietnam", "the Trung Sisters' rebellion against Han rule"),
    Topic("korea_hangul_invention", "Korea", "King Sejong's deliberate invention of Hangul to make literacy accessible"),
    Topic("philippines_precolonial_trade", "Philippines", "pre-colonial Philippine trade networks linking it to China, India, and the Islamic world"),
    Topic("thailand_ayutthaya_trade_hub", "Thailand", "Ayutthaya as one of the world's great cosmopolitan trade cities before its fall"),
    Topic("bhutan_isolation_choice", "Bhutan", "Bhutan's deliberate, centuries-long choice of isolation from global trade"),
    Topic("nepal_kathmandu_urban_planning", "Nepal", "the Kathmandu Valley's dense, ancient urban planning"),
    Topic("mongolia_paiza_passport", "Mongolia", "the paiza, a Mongol-era metal passport that guaranteed safe passage across the empire"),
    Topic("uzbekistan_samarkand_silk_road", "Uzbekistan", "Samarkand's role as a Silk Road crossroads of science and trade"),
    Topic("kazakhstan_horse_domestication", "Kazakhstan", "evidence for some of the earliest horse domestication on the steppe"),
    Topic("armenia_state_christianity", "Armenia", "Armenia becoming the first state to adopt Christianity officially"),
    Topic("azerbaijan_fire_temples", "Azerbaijan", "Azerbaijan's ancient fire temples tied to natural gas seeps"),
    Topic("laos_plain_of_jars", "Laos", "the still-unexplained Plain of Jars megaliths"),
    Topic("mongolia_genghis_law_code", "Mongolia", "the Yassa legal code and its surprising provisions for the era"),
    # Africa
    Topic("mali_mansa_musa_wealth", "Mali", "Mansa Musa's pilgrimage and its lasting effect on gold markets he passed through"),
    Topic("ethiopia_aksum_stelae", "Ethiopia", "Aksum's carved stone stelae and Ethiopia's unbroken independence"),
    Topic("egypt_womens_legal_rights", "Egypt", "property and legal rights held by women in ancient Egypt, unusual for the era"),
    Topic("zimbabwe_great_zimbabwe", "Zimbabwe", "Great Zimbabwe's stone architecture, built without mortar"),
    Topic("mali_timbuktu_manuscripts", "Mali", "the hundreds of thousands of manuscripts preserved in Timbuktu's libraries"),
    Topic("benin_bronze_craftsmanship", "Nigeria", "the lost-wax casting technique behind the Benin Bronzes"),
    Topic("sudan_nubian_pyramids", "Sudan", "Nubia/Kush having more pyramids than Egypt itself"),
    Topic("madagascar_austronesian_migration", "Madagascar", "Madagascar's population descending from Southeast Asian sailors, not mainland Africa"),
    Topic("morocco_fez_oldest_university", "Morocco", "the University of al-Qarawiyyin in Fez, the oldest continually operating degree-granting institution"),
    Topic("tunisia_carthage_naval_innovation", "Tunisia", "Carthage's naval engineering and the circular military harbor at Carthage"),
    Topic("algeria_timgad_roman_grid", "Algeria", "Timgad's precise Roman grid city plan, preserved almost intact in the desert"),
    Topic("nigeria_ife_bronze_naturalism", "Nigeria", "the naturalistic bronze and terracotta heads of Ife, centuries before comparable European work"),
    Topic("ghana_akan_gold_weights", "Ghana", "Akan gold weights functioning as a visual, near-written measurement system"),
    Topic("kenya_rift_valley_origins", "Kenya", "the Great Rift Valley's fossil record and its role in tracing human origins"),
    Topic("tanzania_zanzibar_spice_routes", "Tanzania", "Zanzibar's centrality to the Indian Ocean spice and trade routes"),
    Topic("south_africa_blombos_art", "South Africa", "73,000-year-old engraved ochre from Blombos Cave, among the oldest known deliberate art"),
    Topic("senegal_goree_island_history", "Senegal", "Gorée Island's layered, contested history as a trade port"),
    Topic("rwanda_precolonial_governance", "Rwanda", "pre-colonial Rwandan governance structures and their complexity"),
    Topic("egypt_rosetta_stone_decoding", "Egypt", "how the Rosetta Stone actually cracked the code of hieroglyphs"),
    Topic("ethiopia_lalibela_churches", "Ethiopia", "the rock-hewn churches of Lalibela, carved downward from solid stone"),
    # Europe
    Topic("ireland_monks_preserving_texts", "Ireland", "Irish monasteries copying and preserving classical texts through Europe's early medieval period"),
    Topic("iceland_althing_parliament", "Iceland", "the Althing, one of the world's oldest still-existing parliamentary institutions"),
    Topic("netherlands_tulip_mania", "Netherlands", "Tulip mania and what actually happened versus the popular legend"),
    Topic("italy_roman_concrete_durability", "Italy", "why Roman marine concrete has outlasted much modern concrete"),
    Topic("greece_antikythera_mechanism", "Greece", "the Antikythera mechanism, an analog astronomical computer far ahead of its time"),
    Topic("portugal_navigation_techniques", "Portugal", "the navigational innovations that enabled Portugal's early ocean voyages"),
    Topic("poland_warsaw_reconstruction", "Poland", "Warsaw's old town, rebuilt after WWII using paintings as blueprints"),
    Topic("finland_sauna_culture_history", "Finland", "the surprisingly old, socially central history of the Finnish sauna"),
    Topic("switzerland_permanent_neutrality", "Switzerland", "how and why Switzerland's permanent neutrality actually began"),
    Topic("georgia_birthplace_of_wine", "Georgia", "8,000-year-old evidence for winemaking in Georgia's qvevri clay vessels"),
    Topic("spain_alhambra_tile_mathematics", "Spain", "the mathematical symmetry groups embedded in the Alhambra's tilework"),
    Topic("france_lascaux_cave_paintings", "France", "the Lascaux cave paintings and what their accidental rediscovery revealed"),
    Topic("germany_gutenberg_press_mechanics", "Germany", "the actual mechanical innovation behind Gutenberg's press"),
    Topic("scotland_skara_brae_age", "United Kingdom", "Skara Brae, a Neolithic village older than Stonehenge and the Great Pyramids"),
    Topic("sweden_vasa_ship_disaster", "Sweden", "the Vasa warship's disastrous maiden voyage and what it revealed on recovery"),
    Topic("norway_viking_navigation", "Norway", "Viking open-ocean navigation techniques without a magnetic compass"),
    Topic("denmark_jelling_stones", "Denmark", "the Jelling stones marking Denmark's conversion to Christianity"),
    Topic("hungary_thermal_bath_history", "Hungary", "the layered Roman-Ottoman history behind Budapest's thermal baths"),
    Topic("czechia_astronomical_clock", "Czechia", "the medieval engineering behind Prague's astronomical clock"),
    Topic("malta_hypogeum_underground", "Malta", "the Hypogeum of Ħal Saflieni, an underground Neolithic complex predating the pyramids"),
    # Americas
    Topic("peru_inca_quipu_records", "Peru", "quipu, the Inca knotted-cord system used to record complex information without writing"),
    Topic("mexico_aztec_chinampas", "Mexico", "chinampas, the Aztec floating-garden farming system that fed a massive city"),
    Topic("bolivia_tiwanaku_agriculture", "Bolivia", "Tiwanaku's raised-field agriculture engineered for high-altitude frost resistance"),
    Topic("canada_vinland_norse_settlement", "Canada", "L'Anse aux Meadows, the confirmed Norse settlement predating Columbus by centuries"),
    Topic("usa_cahokia_ancient_city", "United States", "Cahokia, a city near modern St. Louis once larger than contemporary London"),
    Topic("brazil_amazonian_terra_preta", "Brazil", "terra preta, engineered fertile soil created by pre-Columbian Amazonian societies"),
    Topic("haiti_first_slave_revolt_nation", "Haiti", "the Haitian Revolution and the world's first nation founded by a successful slave revolt"),
    Topic("guatemala_maya_calendar_precision", "Guatemala", "the astronomical precision behind the Maya calendar system"),
    Topic("colombia_el_dorado_origins", "Colombia", "the real Muisca ritual behind the El Dorado legend"),
    Topic("chile_moai_transport_theories", "Chile", "competing theories for how Easter Island's moai were actually moved"),
    Topic("peru_machu_picchu_engineering", "Peru", "Machu Picchu's earthquake-resistant stone engineering"),
    Topic("mexico_maya_underground_reservoirs", "Mexico", "the engineered underground water systems that sustained Maya cities"),
    Topic("usa_transcontinental_railroad_labor", "United States", "the specific engineering feats accomplished by transcontinental railroad crews"),
    Topic("argentina_patagonia_early_settlement", "Argentina", "surprisingly early human presence in Patagonia"),
    # Oceania
    Topic("new_zealand_maori_navigation", "New Zealand", "Polynesian wayfinding navigation across thousands of miles of open Pacific"),
    Topic("australia_firestick_farming", "Australia", "Aboriginal fire-stick farming, a deliberate land-management technique used for tens of thousands of years"),
    Topic("papua_new_guinea_language_diversity", "Papua New Guinea", "how one country came to hold over 800 distinct languages"),
    Topic("fiji_pacific_star_navigation", "Fiji", "traditional Pacific navigation using stars, swells, and birds"),
    Topic("australia_oldest_continuous_culture", "Australia", "evidence for one of the longest continuous cultural traditions on Earth"),
    # Middle East
    Topic("jordan_petra_water_system", "Jordan", "Petra's rock-cut water channels that made a desert city thrive"),
    Topic("saudi_arabia_nabatean_trade_routes", "Saudi Arabia", "the Nabatean trade routes that made Petra's wealth possible"),
    Topic("oman_frankincense_trade", "Oman", "the ancient frankincense trade routes that connected Oman to the Mediterranean"),
    Topic("yemen_queen_of_sheba_legends", "Yemen", "what's historically supported versus legendary in the Queen of Sheba accounts"),
    Topic("lebanon_phoenician_alphabet", "Lebanon", "the Phoenician alphabet's outsized influence on nearly every modern writing system"),
    Topic("israel_ancient_aqueduct_engineering", "Israel", "the engineering precision behind ancient Levantine aqueduct systems"),
]

assert len(TOPIC_POOL) >= 70, "topic pool must sustain a 14-day no-repeat window at 5 posts/day"
