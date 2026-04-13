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
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", BASE_DIR / "output"))
INPUT_DIR = Path(os.getenv("INPUT_DIR", BASE_DIR / "input"))
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"

# Default music platform: "aimusicfactory", "suno", "udio", or "musicgen"
MUSIC_PLATFORM = os.getenv("MUSIC_PLATFORM", "aimusicfactory")
# Default number of songs to generate per clip (2, 4, 6, 8)
SONGS_PER_CLIP = int(os.getenv("SONGS_PER_CLIP", "2"))

# Suno-specific: number of times to click "Create" (each = 2 songs).
# Overrides SONGS_PER_CLIP on Suno when set. Default 1 keeps old behavior.
SUNO_GEN_COUNT = int(os.getenv("SUNO_GEN_COUNT", "0"))
# Suno-specific: split each generated song into its own YouTube video (default).
# Set to "false" (e.g. for Dark House long mixes) to merge all songs into one
# long track and upload a single video.
SUNO_SPLIT_UPLOAD = os.getenv("SUNO_SPLIT_UPLOAD", "true").lower() == "true"

# Music genre (used for concept generation)
MUSIC_GENRE = os.getenv("MUSIC_GENRE", "Afro House")
# Custom music style prompt (overrides default genre-based style)
MUSIC_STYLE_PROMPT = os.getenv("MUSIC_STYLE_PROMPT", "")
# Custom thumbnail style prompt (overrides default)
THUMBNAIL_STYLE_PROMPT = os.getenv("THUMBNAIL_STYLE_PROMPT", "")

# Skip TuneCore upload in the pipeline (set to "true" to disable)
SKIP_TUNECORE = os.getenv("SKIP_TUNECORE", "false").lower() == "true"

# Skip SoundCloud upload in the pipeline (set to "true" to disable)
SKIP_SOUNDCLOUD = os.getenv("SKIP_SOUNDCLOUD", "false").lower() == "true"

# Skip TikTok upload in the pipeline (set to "true" to disable)
SKIP_TIKTOK = os.getenv("SKIP_TIKTOK", "false").lower() == "true"

# Beat-synced video: zoom/brightness pulses on detected beats (requires librosa)
BEAT_SYNC_VIDEO = os.getenv("BEAT_SYNC_VIDEO", "false").lower() == "true"
VIDEO_FPS = int(os.getenv("VIDEO_FPS", "24"))

# Thumbnail text style: "stylized" (glow + gradient) or "classic" (plain outline)
THUMBNAIL_TEXT_STYLE = os.getenv("THUMBNAIL_TEXT_STYLE", "stylized")

# Ensure directories exist
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
INPUT_DIR.mkdir(parents=True, exist_ok=True)
