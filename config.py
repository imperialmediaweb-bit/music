import os
from pathlib import Path
from dotenv import load_dotenv

# Optional profile (e.g. "darkhouse") selects an additional .env.<profile> file
# that is loaded BEFORE .env. Variables in the profile take precedence; .env
# fills in everything the profile does not override. When LUTH_PROFILE is unset,
# behavior is identical to loading just .env.
_profile = os.getenv("LUTH_PROFILE", "").strip()
if _profile:
    load_dotenv(Path(__file__).parent / f".env.{_profile}", override=False)
load_dotenv(override=False)

BASE_DIR = Path(__file__).parent

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
HF_API_KEY = os.getenv("HF_API_KEY", "")
SCHEDULE_CRON = os.getenv("SCHEDULE_CRON", "0 10 * * *")
YOUTUBE_COOKIE_FILE = Path(os.getenv("YOUTUBE_COOKIE_FILE", BASE_DIR / "cookies" / "youtube_cookies.json"))
# OAuth token for the YouTube Data API. Use a separate file per profile so
# each channel has its own token (required — the YouTube API uploads to the
# channel the token was authorized against, regardless of cookies).
YOUTUBE_TOKEN_FILE = Path(os.getenv("YOUTUBE_TOKEN_FILE", BASE_DIR / "youtube_token.pickle"))
TIKTOK_COOKIE_FILE = Path(os.getenv("TIKTOK_COOKIE_FILE", BASE_DIR / "cookies" / "tiktok_cookies.json"))
AIMUSICFACTORY_STATE_FILE = Path(os.getenv("AIMUSICFACTORY_STATE_FILE", BASE_DIR / "cookies" / "aimusicfactory_state.json"))
SUNO_STATE_FILE = Path(os.getenv("SUNO_STATE_FILE", BASE_DIR / "cookies" / "suno_state.json"))
UDIO_STATE_FILE = Path(os.getenv("UDIO_STATE_FILE", BASE_DIR / "cookies" / "udio_state.json"))
TUNECORE_STATE_FILE = Path(os.getenv("TUNECORE_STATE_FILE", BASE_DIR / "cookies" / "tunecore_state.json"))
SOUNDCLOUD_STATE_FILE = Path(os.getenv("SOUNDCLOUD_STATE_FILE", BASE_DIR / "cookies" / "soundcloud_state.json"))
BANDCAMP_STATE_FILE = Path(os.getenv("BANDCAMP_STATE_FILE", BASE_DIR / "cookies" / "bandcamp_state.json"))
DISTROKID_STATE_FILE = Path(os.getenv("DISTROKID_STATE_FILE", BASE_DIR / "cookies" / "distrokid_state.json"))
# Artist's Bandcamp subdomain (e.g. "groovegenix" → https://groovegenix.bandcamp.com)
BANDCAMP_ARTIST_SUBDOMAIN = os.getenv("BANDCAMP_ARTIST_SUBDOMAIN", "groovegenix")
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", BASE_DIR / "output"))
INPUT_DIR = Path(os.getenv("INPUT_DIR", BASE_DIR / "input"))
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"

# Default music platform: "aimusicfactory", "suno", "udio", or "musicgen"
MUSIC_PLATFORM = os.getenv("MUSIC_PLATFORM", "aimusicfactory")
# Default number of songs to generate per clip (2, 4, 6, 8).
# 8 songs ≈ 16 min after merge — matches the long-form profile target.
SONGS_PER_CLIP = int(os.getenv("SONGS_PER_CLIP", "8"))

# Music genre (used for concept generation)
MUSIC_GENRE = os.getenv("MUSIC_GENRE", "Afro House")
# Custom music style prompt (overrides default genre-based style)
MUSIC_STYLE_PROMPT = os.getenv("MUSIC_STYLE_PROMPT", "")
# Custom thumbnail style prompt (overrides default)
THUMBNAIL_STYLE_PROMPT = os.getenv("THUMBNAIL_STYLE_PROMPT", "")

# Skip TuneCore upload in the pipeline.
# Default: TRUE — disabled (TuneCore rejects AI-generated music under its
# GenAI framework). Distribute via DistroKid instead. Override with
# SKIP_TUNECORE=false to re-enable.
SKIP_TUNECORE = os.getenv("SKIP_TUNECORE", "true").lower() == "true"

# Skip DistroKid upload in the pipeline. Default: FALSE — DistroKid is the
# active distributor (accepts AI music with disclosure). Set SKIP_DISTROKID=true
# to disable. Requires a saved session (run 'python main.py distrokid-login').
SKIP_DISTROKID = os.getenv("SKIP_DISTROKID", "false").lower() == "true"
# DistroKid artist name used on the release form.
DISTROKID_ARTIST = os.getenv("DISTROKID_ARTIST", "GrooveGenix")
# Optional: path to your REAL Chrome "User Data" folder. When set, DistroKid
# automation reuses the browser profile where you're already logged in — no
# login form is ever submitted, which is what DistroKid's anti-bot blocks.
# Windows example:
#   DISTROKID_CHROME_PROFILE=C:\Users\deals\AppData\Local\Google\Chrome\User Data
DISTROKID_CHROME_PROFILE = os.getenv("DISTROKID_CHROME_PROFILE", "")
# Songwriter legal name DistroKid requires (real name, not stage name).
# Provide as "First Last"; a single word is used as the first name.
DISTROKID_SONGWRITER = os.getenv("DISTROKID_SONGWRITER", "Imperial Media")
# Connect to an already-running Chrome via its DevTools endpoint instead of
# launching one. DistroKid's sign-in uses invisible reCAPTCHA/Turnstile that
# blocks automated logins, so log in MANUALLY in a real Chrome started with
#   chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\dk-profile"
# then set DISTROKID_CDP_URL=http://localhost:9222 and the pipeline drives
# that already-authenticated session (captcha already passed by you).
DISTROKID_CDP_URL = os.getenv("DISTROKID_CDP_URL", "")
TUNECORE_EMAIL = os.getenv("TUNECORE_EMAIL", "")
TUNECORE_PASSWORD = os.getenv("TUNECORE_PASSWORD", "")

# Skip SoundCloud upload in the pipeline (disabled by default — uploads kept failing)
SKIP_SOUNDCLOUD = os.getenv("SKIP_SOUNDCLOUD", "true").lower() == "true"

# Skip TikTok upload in the pipeline (set to "true" to disable)
SKIP_TIKTOK = os.getenv("SKIP_TIKTOK", "false").lower() == "true"

# Skip Bandcamp upload in the pipeline (set to "true" to disable)
SKIP_BANDCAMP = os.getenv("SKIP_BANDCAMP", "false").lower() == "true"

# Skip YouTube Shorts creation/upload in the pipeline.
# Default: FALSE — Shorts ARE the channel's discovery engine, posted right
# after each long video. Override with SKIP_SHORTS=true to disable.
SKIP_SHORTS = os.getenv("SKIP_SHORTS", "false").lower() == "true"

# Skip reusing archived MP3s in hybrid mode. When FALSE, older tracks from
# the pool are mixed into the MIDDLE of new tracks (never at the very start),
# so we keep reusing the back catalogue without a stale opening.
# Default: FALSE — hybrid reuse ON. Override with SKIP_ARCHIVE=true to disable.
SKIP_ARCHIVE = os.getenv("SKIP_ARCHIVE", "false").lower() == "true"

# Skip post-merge mastering chain (EQ + stereo widen + -14 LUFS + 320 kbps).
# Default: FALSE — mastering ON so tracks sit alongside commercial releases
# on Spotify/YouTube playlists. Override with SKIP_MASTERING=true to disable.
SKIP_MASTERING = os.getenv("SKIP_MASTERING", "false").lower() == "true"

# Inject World Cup themed energy into the Afro House concept prompt
# (stadium chants, anthem build-ups, flag/crowd imagery on thumbnails,
# #worldcup hashtags). Default: FALSE — flipped on per-run with --world-cup
# (the scheduler enables it only for the 09:00 slot).
WORLD_CUP_THEME = os.getenv("WORLD_CUP_THEME", "false").lower() == "true"
# Bandcamp track price in USD (default: $1.50)
BANDCAMP_TRACK_PRICE = os.getenv("BANDCAMP_TRACK_PRICE", "1.50")

# Artist profile URLs appended to YouTube/TikTok descriptions so viewers can
# jump straight to the paid-streaming pages.
SPOTIFY_ARTIST_URL = os.getenv(
    "SPOTIFY_ARTIST_URL",
    "https://open.spotify.com/artist/2mfn67J1VKg3CavV9K99j7",
)
BEATPORT_ARTIST_URL = os.getenv(
    "BEATPORT_ARTIST_URL",
    "https://www.beatport.com/artist/groovegenix/2354993/releases",
)

# Beat-synced video: zoom/brightness pulses on detected beats (requires librosa)
BEAT_SYNC_VIDEO = os.getenv("BEAT_SYNC_VIDEO", "false").lower() == "true"
VIDEO_FPS = int(os.getenv("VIDEO_FPS", "24"))

# Thumbnail text style: "stylized" (glow + gradient) or "classic" (plain outline)
THUMBNAIL_TEXT_STYLE = os.getenv("THUMBNAIL_TEXT_STYLE", "stylized")

# ─────────────────────────────────────────────────────────────────────────
# RECOVERY PIPELINE v3 — Phase 1: Scheduling
# Cut volume from ~60 uploads/month (2/day) to 12/month (3/week) to let the
# channel's algorithmic distribution recover. Times are in SCHEDULER_TIMEZONE.
# ─────────────────────────────────────────────────────────────────────────
# Timezone all schedule times are interpreted in. Romania (Europe/Bucharest)
# is GMT+3 during summer (EEST), matching the audience heatmap peak.
SCHEDULER_TIMEZONE = os.getenv("SCHEDULER_TIMEZONE", "Europe/Bucharest")

# The upload schedule: a list of (day_of_week, hour, minute) tuples. day_of_week
# uses APScheduler short names: mon tue wed thu fri sat sun. Publishing at 17:00
# leaves the video indexed BEFORE the 18:00–21:00 traffic window opens.
# Edit this list to change frequency/timing — the scheduler reads it from here,
# never from hardcoded values.
UPLOAD_SCHEDULE = [
    ("tue", 17, 0),
    ("thu", 17, 0),
    ("sat", 17, 0),
]

# Hard cap on uploads per rolling 7-day window, enforced before ANY upload
# (independent of the scheduler — a manual run without --force is capped too).
MAX_UPLOADS_PER_WEEK = int(os.getenv("MAX_UPLOADS_PER_WEEK", "3"))

# Minimum hours between two uploads. Doubles as the anti-duplication safety
# lock: if a process restart re-fires a job, the <24h gap blocks the repeat.
MIN_HOURS_BETWEEN_UPLOADS = int(os.getenv("MIN_HOURS_BETWEEN_UPLOADS", "24"))

# Persistent record of completed uploads (survives process restarts) so the
# volume cap and the anti-duplication lock cannot be reset by a crash/restart.
UPLOAD_HISTORY_FILE = Path(
    os.getenv("UPLOAD_HISTORY_FILE", BASE_DIR / "upload_history.json")
)

# ─────────────────────────────────────────────────────────────────────────
# RECOVERY PIPELINE v3 — Phase 2: Audio diversification
# Break the "one product multiplied" uniformity — vary the generation prompt
# and the track duration so the catalogue reads as many different releases.
# ─────────────────────────────────────────────────────────────────────────
# Pool of structurally distinct style prompts (see the file for the format).
PROMPT_POOL_FILE = Path(
    os.getenv("PROMPT_POOL_FILE", BASE_DIR / "prompts" / "pool.json")
)
# Persistent list of recently-used prompt ids (non-repetition rule).
PROMPT_HISTORY_FILE = Path(
    os.getenv("PROMPT_HISTORY_FILE", BASE_DIR / "prompt_history.json")
)
# A prompt may not repeat within this many consecutive picks.
PROMPT_HISTORY_WINDOW = int(os.getenv("PROMPT_HISTORY_WINDOW", "8"))

# Weighted duration buckets: (label, min_minutes, max_minutes, weight).
# Weights need not sum to 1 — they are normalised at selection time. The long
# bucket is favoured because the channel's best performers are extended mixes.
DURATION_BUCKETS = [
    ("short",  4,  8,  0.20),
    ("medium", 15, 25, 0.30),
    ("long",   30, 45, 0.50),
]

# Persistent log of chosen duration buckets (for the Phase 6 measurement join).
DURATION_HISTORY_FILE = Path(
    os.getenv("DURATION_HISTORY_FILE", BASE_DIR / "duration_history.json")
)

# Ensure directories exist
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
INPUT_DIR.mkdir(parents=True, exist_ok=True)
