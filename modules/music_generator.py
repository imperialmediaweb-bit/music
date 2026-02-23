import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from modules.concept_generator import MusicConcept
from config import OUTPUT_DIR, HEADLESS
from utils.logger import log

MAX_RETRIES = 3
GENERATION_TIMEOUT_MS = 300_000  # 5 minutes


def generate_music(concept: MusicConcept) -> Path:
    log.info(f"Generating music on aimusicfactory.ai for: {concept.track_name}")

    safe_name = "".join(c if c.isalnum() or c in "-_ " else "" for c in concept.track_name)
    safe_name = safe_name.strip().replace(" ", "_")[:50]

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return _attempt_generation(concept, safe_name)
        except Exception as e:
            log.warning(f"Attempt {attempt}/{MAX_RETRIES} failed: {e}")
            if attempt < MAX_RETRIES:
                wait = 2 ** attempt
                log.info(f"Retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise RuntimeError(f"Music generation failed after {MAX_RETRIES} attempts") from e


def _attempt_generation(concept: MusicConcept, safe_name: str) -> Path:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        # Navigate to aimusicfactory.ai
        log.info("Navigating to aimusicfactory.ai...")
        page.goto("https://aimusicfactory.ai/", wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(3000)

        # Build the prompt text
        prompt_text = (
            f"{concept.description}\n"
            f"Genre: {concept.genre}\n"
            f"Mood: {concept.mood}\n"
            f"{concept.lyrics}"
        )

        # Find and fill the text input area
        # Try common selectors for text input on music generation sites
        textarea_selectors = [
            "textarea",
            'input[type="text"]',
            '[contenteditable="true"]',
            ".prompt-input",
            "#prompt",
            '[placeholder*="lyrics"]',
            '[placeholder*="describe"]',
            '[placeholder*="prompt"]',
        ]

        filled = False
        for selector in textarea_selectors:
            try:
                element = page.wait_for_selector(selector, timeout=3000)
                if element and element.is_visible():
                    element.click()
                    element.fill(prompt_text)
                    filled = True
                    log.info(f"Filled text input using selector: {selector}")
                    break
            except PlaywrightTimeout:
                continue

        if not filled:
            # Fallback: try to find any visible input/textarea
            page.screenshot(path=str(OUTPUT_DIR / "debug_music_page.png"))
            raise RuntimeError("Could not find text input on aimusicfactory.ai")

        # Click the generate/create button
        generate_selectors = [
            'button:has-text("Generate")',
            'button:has-text("Create")',
            'button:has-text("Make")',
            'button:has-text("Start")',
            '[type="submit"]',
            ".generate-btn",
            "#generate",
        ]

        clicked = False
        for selector in generate_selectors:
            try:
                btn = page.wait_for_selector(selector, timeout=3000)
                if btn and btn.is_visible():
                    btn.click()
                    clicked = True
                    log.info(f"Clicked generate button: {selector}")
                    break
            except PlaywrightTimeout:
                continue

        if not clicked:
            page.screenshot(path=str(OUTPUT_DIR / "debug_no_generate_btn.png"))
            raise RuntimeError("Could not find generate button on aimusicfactory.ai")

        # Wait for music generation to complete and download button to appear
        log.info("Waiting for music generation to complete...")
        download_selectors = [
            'a:has-text("Download")',
            'button:has-text("Download")',
            'a[download]',
            ".download-btn",
            '[href*=".mp3"]',
            '[href*="download"]',
        ]

        download_element = None
        for selector in download_selectors:
            try:
                download_element = page.wait_for_selector(selector, timeout=GENERATION_TIMEOUT_MS)
                if download_element and download_element.is_visible():
                    log.info(f"Download button found: {selector}")
                    break
                download_element = None
            except PlaywrightTimeout:
                continue

        if not download_element:
            page.screenshot(path=str(OUTPUT_DIR / "debug_no_download.png"))
            raise RuntimeError("Music generation timed out or download button not found")

        # Download the file
        output_path = OUTPUT_DIR / f"{safe_name}.mp3"
        with page.expect_download(timeout=60_000) as download_info:
            download_element.click()

        download = download_info.value
        download.save_as(str(output_path))
        log.info(f"Music downloaded to: {output_path}")

        browser.close()
        return output_path
