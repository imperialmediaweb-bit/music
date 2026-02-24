import json
from pathlib import Path
from playwright.sync_api import sync_playwright, BrowserContext, Browser
from config import HEADLESS
from utils.logger import log


def load_cookies(cookie_file: Path) -> list[dict] | None:
    if not cookie_file.exists():
        log.warning(f"Cookie file not found: {cookie_file}")
        return None
    with open(cookie_file, "r") as f:
        cookies = json.load(f)
    log.info(f"Loaded {len(cookies)} cookies from {cookie_file}")
    return cookies


def save_cookies(context: BrowserContext, cookie_file: Path) -> None:
    cookie_file.parent.mkdir(parents=True, exist_ok=True)
    cookies = context.cookies()
    with open(cookie_file, "w") as f:
        json.dump(cookies, f, indent=2)
    log.info(f"Saved {len(cookies)} cookies to {cookie_file}")


# Stealth script injected into every page to avoid automation detection.
# TikTok checks navigator.webdriver and other fingerprints to block bots.
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5],
});
window.chrome = { runtime: {} };
"""


def get_browser_context(
    playwright,
    cookie_file: Path | None = None,
) -> tuple[Browser, BrowserContext]:
    browser = playwright.chromium.launch(
        headless=HEADLESS,
        args=[
            "--disable-blink-features=AutomationControlled",
        ],
    )
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
    )

    # Inject stealth script before any page loads
    context.add_init_script(_STEALTH_JS)

    if cookie_file:
        cookies = load_cookies(cookie_file)
        if cookies:
            context.add_cookies(cookies)

    return browser, context
