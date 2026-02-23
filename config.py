import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
MUSIC_GENRE_POOL = os.getenv("MUSIC_GENRE_POOL", "pop,lofi,jazz,electronic,ambient,chill,hip-hop,r&b").split(",")
SCHEDULE_CRON = os.getenv("SCHEDULE_CRON", "0 10 * * *")
YOUTUBE_COOKIE_FILE = Path(os.getenv("YOUTUBE_COOKIE_FILE", BASE_DIR / "cookies" / "youtube_cookies.json"))
TIKTOK_COOKIE_FILE = Path(os.getenv("TIKTOK_COOKIE_FILE", BASE_DIR / "cookies" / "tiktok_cookies.json"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", BASE_DIR / "output"))
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"

# Ensure output directory exists
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
