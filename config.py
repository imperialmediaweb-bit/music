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
# Bandcamp's reCAPTCHA refuses a blank browser, so we keep a persistent
# Chrome profile here. Gets populated on `bandcamp-login` and reused by the
# uploader so the session (and reCAPTCHA trust score) survives across runs.
BANDCAMP_USER_DATA_DIR = Path(os.getenv(
    "BANDCAMP_USER_DATA_DIR", BASE_DIR / "cookies" / "bandcamp_chrome_profile"
))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", BASE_DIR / "output"))
INPUT_DIR = Path(os.getenv("INPUT_DIR", BASE_DIR / "input"))
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"

# Default music platform: "aimusicfactory", "suno", "udio", or "musicgen"
MUSIC_PLATFORM = os.getenv("MUSIC_PLATFORM", "aimusicfactory")
# Default number of songs to generate per clip (2, 4, 6, 8)
SONGS_PER_CLIP = int(os.getenv("SONGS_PER_CLIP", "2"))

# Music genre (used for concept generation)
MUSIC_GENRE = os.getenv("MUSIC_GENRE", "Afro House")
# Custom music style prompt (overrides default genre-based style)
MUSIC_STYLE_PROMPT = os.getenv("MUSIC_STYLE_PROMPT", "")
# Custom thumbnail style prompt (overrides default)
THUMBNAIL_STYLE_PROMPT = os.getenv("THUMBNAIL_STYLE_PROMPT", "")

# Skip TuneCore upload in the pipeline (set to "true" to disable)
SKIP_TUNECORE = os.getenv("SKIP_TUNECORE", "false").lower() == "true"

# Skip SoundCloud upload in the pipeline (disabled by default — uploads kept failing)
SKIP_SOUNDCLOUD = os.getenv("SKIP_SOUNDCLOUD", "true").lower() == "true"

# Skip TikTok upload in the pipeline (set to "true" to disable)
SKIP_TIKTOK = os.getenv("SKIP_TIKTOK", "false").lower() == "true"

# Skip Bandcamp upload in the pipeline (set to "true" to disable)
SKIP_BANDCAMP = os.getenv("SKIP_BANDCAMP", "false").lower() == "true"
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

# Ensure directories exist
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
INPUT_DIR.mkdir(parents=True, exist_ok=True)
