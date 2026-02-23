"""Generate music on aimusicfactory.ai using Playwright.

Each generation produces 2 MP3 files. We run multiple generations
to get 6-8 MP3s, then merge them later.
"""

import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from modules.concept_generator import MusicConcept
from config import OUTPUT_DIR, HEADLESS
from utils.logger import log

MAX_RETRIES = 3
GENERATION_TIMEOUT_MS = 300_000  # 5 minutes


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
        page.goto("https://aimusicfactory.ai/#Generate", wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(3000)

        for batch_num in range(1, count + 1):
            log.info(f"\n--- Generation {batch_num}/{count} ---")

            try:
                mp3s = _single_generation(page, concept, safe_name, batch_num)
                all_mp3s.extend(mp3s)
                log.info(f"Generation {batch_num} done: {len(mp3s)} MP3(s) downloaded")
            except Exception as e:
                log.warning(f"Generation {batch_num} failed: {e}")
                # Take screenshot for debugging
                page.screenshot(path=str(OUTPUT_DIR / f"debug_gen_{batch_num}.png"))
                # Try to reload and continue
                try:
                    page.goto("https://aimusicfactory.ai/#Generate", wait_until="networkidle", timeout=60_000)
                    page.wait_for_timeout(3000)
                except Exception:
                    pass

        browser.close()

    if not all_mp3s:
        raise RuntimeError(f"No MP3s generated after {count} attempts")

    log.info(f"Total MP3s downloaded: {len(all_mp3s)}")
    return all_mp3s


def _single_generation(page, concept: MusicConcept, safe_name: str, batch_num: int) -> list[Path]:
    """Run one generation cycle on the page, downloading all resulting MP3s."""

    prompt_text = concept.music_prompt

    # Fill the text input
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
                element.fill("")  # Clear first
                element.fill(prompt_text)
                filled = True
                log.info(f"Filled text input: {selector}")
                break
        except PlaywrightTimeout:
            continue

    if not filled:
        page.screenshot(path=str(OUTPUT_DIR / f"debug_no_input_{batch_num}.png"))
        raise RuntimeError("Could not find text input")

    # Click Generate button
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
                log.info(f"Clicked generate: {selector}")
                break
        except PlaywrightTimeout:
            continue

    if not clicked:
        raise RuntimeError("Could not find generate button")

    # Wait for generation to complete
    log.info("Waiting for music generation...")
    download_selectors = [
        'a:has-text("Download")',
        'button:has-text("Download")',
        'a[download]',
        ".download-btn",
        '[href*=".mp3"]',
        '[href*="download"]',
    ]

    # Wait for download buttons to appear
    page.wait_for_timeout(5000)  # Give it time to start generating

    download_elements = []
    for selector in download_selectors:
        try:
            page.wait_for_selector(selector, timeout=GENERATION_TIMEOUT_MS)
            elements = page.query_selector_all(selector)
            visible = [el for el in elements if el.is_visible()]
            if visible:
                download_elements = visible
                log.info(f"Found {len(visible)} download button(s): {selector}")
                break
        except PlaywrightTimeout:
            continue

    if not download_elements:
        raise RuntimeError("No download buttons found")

    # Download all available MP3s
    downloaded = []
    for i, dl_btn in enumerate(download_elements):
        try:
            output_path = OUTPUT_DIR / f"{safe_name}_gen{batch_num}_{i + 1}.mp3"
            with page.expect_download(timeout=60_000) as download_info:
                dl_btn.click()
            download = download_info.value
            download.save_as(str(output_path))
            downloaded.append(output_path)
            log.info(f"Downloaded: {output_path.name}")
            page.wait_for_timeout(1000)
        except Exception as e:
            log.warning(f"Download {i + 1} failed: {e}")

    return downloaded


def generate_music(concept: MusicConcept) -> Path:
    """Generate a single music track (backward compatibility)."""
    mp3s = generate_music_batch(concept, count=1)
    return mp3s[0]
