"""Generate music on aimusicfactory.ai using Playwright.

Each generation produces 2 MP3 files. We run multiple generations
to get 6-8 MP3s, then merge them later.
"""

import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from modules.concept_generator import MusicConcept
from config import OUTPUT_DIR, HEADLESS, AIMUSICFACTORY_STATE_FILE
from utils.logger import log

MAX_RETRIES = 3
GENERATION_WAIT_SEC = 360  # 6 minutes wait for generation


def generate_music_batch(concept: MusicConcept, count: int = 4) -> list[Path]:
    """Generate music on aimusicfactory.ai multiple times.

    Each generation produces 2 MP3s. With count=4 we get ~8 MP3s.

    Args:
        concept: The music concept with the prompt.
        count: Number of times to hit Generate (each gives 2 MP3s).

    Returns:
        List of downloaded MP3 file paths.
    """
    log.info(f"Generating {count} batches on aimusicfactory.ai for: {concept.track_name}")
    log.info(f"Expected output: ~{count * 2} MP3 files")

    safe_name = "".join(c if c.isalnum() or c in "-_ " else "" for c in concept.track_name)
    safe_name = safe_name.strip().replace(" ", "_")[:50]

    all_mp3s = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)

        # Load saved session (cookies from 'python main.py login')
        context_opts = {
            "viewport": {"width": 1920, "height": 1080},
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }
        if AIMUSICFACTORY_STATE_FILE.exists():
            context_opts["storage_state"] = str(AIMUSICFACTORY_STATE_FILE)
            log.info("Using saved aimusicfactory.ai session (logged in)")
        else:
            log.warning("No saved session. Run 'python main.py login' to use your subscription.")

        context = browser.new_context(**context_opts)
        context.set_default_timeout(60_000)
        page = context.new_page()

        for batch_num in range(1, count + 1):
            log.info(f"\n--- Generation {batch_num}/{count} ---")

            try:
                mp3s = _single_generation(page, context, concept, safe_name, batch_num)
                all_mp3s.extend(mp3s)
                log.info(f"Generation {batch_num} done: {len(mp3s)} MP3(s) downloaded")
            except Exception as e:
                log.warning(f"Generation {batch_num} failed: {e}")
                page.screenshot(path=str(OUTPUT_DIR / f"debug_gen_{batch_num}.png"))
                log.info(f"Debug screenshot saved: debug_gen_{batch_num}.png")

        browser.close()

    if not all_mp3s:
        raise RuntimeError(f"No MP3s generated after {count} attempts")

    log.info(f"Total MP3s downloaded: {len(all_mp3s)}")
    return all_mp3s


def _single_generation(page, context, concept: MusicConcept, safe_name: str, batch_num: int) -> list[Path]:
    """Run one generation cycle: fill prompt, generate, wait, download from My Music."""

    prompt_text = concept.music_prompt

    # Step 1: Navigate to Generate page
    log.info("Navigating to Generate page...")
    page.goto("https://aimusicfactory.ai/#Generate", wait_until="networkidle", timeout=60_000)
    page.wait_for_timeout(3000)

    # Take debug screenshot to see what we're working with
    page.screenshot(path=str(OUTPUT_DIR / f"debug_before_gen_{batch_num}.png"))

    # Step 2: Fill the prompt text
    filled = False
    textarea_selectors = [
        "textarea",
        'input[type="text"]',
        '[contenteditable="true"]',
        ".prompt-input",
        "#prompt",
        '[placeholder*="lyrics"]',
        '[placeholder*="describe"]',
        '[placeholder*="prompt"]',
        '[placeholder*="Describe"]',
        '[placeholder*="Enter"]',
    ]

    for selector in textarea_selectors:
        try:
            element = page.wait_for_selector(selector, timeout=3000)
            if element and element.is_visible():
                element.click()
                element.fill("")
                element.fill(prompt_text)
                filled = True
                log.info(f"Filled text input: {selector}")
                break
        except PlaywrightTimeout:
            continue

    if not filled:
        page.screenshot(path=str(OUTPUT_DIR / f"debug_no_input_{batch_num}.png"))
        raise RuntimeError("Could not find text input on Generate page")

    # Step 3: Click Generate button
    clicked = False
    generate_selectors = [
        'button:has-text("Generate")',
        'button:has-text("Create")',
        'button:has-text("Make")',
        'button:has-text("Start")',
        '[type="submit"]',
        ".generate-btn",
        "#generate",
    ]

    for selector in generate_selectors:
        try:
            btn = page.wait_for_selector(selector, timeout=3000)
            if btn and btn.is_visible():
                btn.click()
                clicked = True
                log.info(f"Clicked generate: {selector}")
                break
        except PlaywrightTimeout:
            continue

    if not clicked:
        page.screenshot(path=str(OUTPUT_DIR / f"debug_no_button_{batch_num}.png"))
        raise RuntimeError("Could not find Generate button")

    # Step 4: Wait for generation (takes 4-6 minutes)
    log.info(f"Waiting {GENERATION_WAIT_SEC // 60} minutes for music generation...")
    for elapsed in range(0, GENERATION_WAIT_SEC, 30):
        page.wait_for_timeout(30_000)
        remaining = GENERATION_WAIT_SEC - elapsed - 30
        if remaining > 0:
            log.info(f"  Still generating... {remaining // 60}m {remaining % 60}s remaining")

    page.screenshot(path=str(OUTPUT_DIR / f"debug_after_wait_{batch_num}.png"))

    # Step 5: Try to download from current page first
    downloaded = _try_download_from_page(page, safe_name, batch_num)

    if not downloaded:
        # Step 6: Go to My Music page to find and download
        log.info("Checking My Music page for downloads...")
        page.goto("https://aimusicfactory.ai/#MyMusic", wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(3000)
        page.screenshot(path=str(OUTPUT_DIR / f"debug_mymusic_{batch_num}.png"))
        downloaded = _try_download_from_page(page, safe_name, batch_num)

    if not downloaded:
        page.screenshot(path=str(OUTPUT_DIR / f"debug_no_download_{batch_num}.png"))
        raise RuntimeError("Could not find any download buttons")

    return downloaded


def _try_download_from_page(page, safe_name: str, batch_num: int) -> list[Path]:
    """Try to find and click download buttons on the current page."""
    download_selectors = [
        'a:has-text("Download")',
        'button:has-text("Download")',
        'a[download]',
        ".download-btn",
        '[href*=".mp3"]',
        '[href*="download"]',
        'a[href*=".mp3"]',
        'button:has-text("download")',
        # Icon-based download buttons
        '[aria-label*="download"]',
        '[aria-label*="Download"]',
        '[title*="Download"]',
        '[title*="download"]',
        # SVG download icons inside buttons/links
        'a svg',
        'button svg',
    ]

    download_elements = []
    for selector in download_selectors:
        try:
            elements = page.query_selector_all(selector)
            visible = [el for el in elements if el.is_visible()]
            if visible:
                download_elements = visible[:2]  # Take max 2 per generation
                log.info(f"Found {len(visible)} download element(s): {selector}")
                break
        except Exception:
            continue

    if not download_elements:
        return []

    downloaded = []
    for i, dl_btn in enumerate(download_elements):
        try:
            output_path = OUTPUT_DIR / f"{safe_name}_gen{batch_num}_{i + 1}.mp3"
            with page.expect_download(timeout=120_000) as download_info:
                dl_btn.click()
            download = download_info.value
            download.save_as(str(output_path))
            downloaded.append(output_path)
            log.info(f"Downloaded: {output_path.name}")
            page.wait_for_timeout(2000)
        except Exception as e:
            log.warning(f"Download {i + 1} failed: {e}")

    return downloaded


def generate_music(concept: MusicConcept) -> Path:
    """Generate a single music track (backward compatibility)."""
    mp3s = generate_music_batch(concept, count=1)
    return mp3s[0]
