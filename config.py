import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
HF_API_KEY = os.getenv("HF_API_KEY", "")
SCHEDULE_CRON = os.getenv("SCHEDULE_CRON", "0 10 * * *")
YOUTUBE_COOKIE_FILE = Path(os.getenv("YOUTUBE_COOKIE_FILE", BASE_DIR / "cookies" / "youtube_cookies.json"))
TIKTOK_COOKIE_FILE = Path(os.getenv("TIKTOK_COOKIE_FILE", BASE_DIR / "cookies" / "tiktok_cookies.json"))
AIMUSICFACTORY_STATE_FILE = Path(os.getenv("AIMUSICFACTORY_STATE_FILE", BASE_DIR / "cookies" / "aimusicfactory_state.json"))
SUNO_STATE_FILE = Path(os.getenv("SUNO_STATE_FILE", BASE_DIR / "cookies" / "suno_state.json"))
UDIO_STATE_FILE = Path(os.getenv("UDIO_STATE_FILE", BASE_DIR / "cookies" / "udio_state.json"))
TUNECORE_STATE_FILE = Path(os.getenv("TUNECORE_STATE_FILE", BASE_DIR / "cookies" / "tunecore_state.json"))
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

# Ensure directories exist
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
INPUT_DIR.mkdir(parents=True, exist_ok=True)
