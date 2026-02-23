import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
SCHEDULE_CRON = os.getenv("SCHEDULE_CRON", "0 10 * * *")
YOUTUBE_COOKIE_FILE = Path(os.getenv("YOUTUBE_COOKIE_FILE", BASE_DIR / "cookies" / "youtube_cookies.json"))
TIKTOK_COOKIE_FILE = Path(os.getenv("TIKTOK_COOKIE_FILE", BASE_DIR / "cookies" / "tiktok_cookies.json"))
AIMUSICFACTORY_STATE_FILE = Path(os.getenv("AIMUSICFACTORY_STATE_FILE", BASE_DIR / "cookies" / "aimusicfactory_state.json"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", BASE_DIR / "output"))
INPUT_DIR = Path(os.getenv("INPUT_DIR", BASE_DIR / "input"))
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"

# Ensure directories exist
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
INPUT_DIR.mkdir(parents=True, exist_ok=True)
