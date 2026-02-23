"""Generate music on aimusicfactory.ai using Playwright.

Flow:
1. Go to #Generate page
2. Fill ONLY the "Title" input with the track name (e.g. "Zanu")
   (Style of Music is already set by the user and stays the same)
3. Click Generate
4. Wait ~6 minutes for generation
5. Go to My Music, find the new track, open its page
6. Download the MP3s from the track page
"""

import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from modules.concept_generator import MusicConcept
from config import OUTPUT_DIR, HEADLESS, AIMUSICFACTORY_STATE_FILE
from utils.logger import log

GENERATION_WAIT_SEC = 360  # 6 minutes wait for generation


def generate_music_batch(concept: MusicConcept, count: int = 4) -> list[Path]:
    """Generate music on aimusicfactory.ai multiple times.

    Args:
        concept: The music concept with the prompt.
        count: Number of times to hit Generate (each gives 2 MP3s).

    Returns:
        List of downloaded MP3 file paths.
    """
    log.info(f"Generating {count} batches on aimusicfactory.ai for: {concept.track_name}")

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
            log.warning("No saved session. Run 'python main.py login' first.")

        context = browser.new_context(**context_opts)
        context.set_default_timeout(60_000)
        page = context.new_page()

        for batch_num in range(1, count + 1):
            log.info(f"\n--- Generation {batch_num}/{count} ---")

            try:
                mp3s = _single_generation(page, concept, safe_name, batch_num)
                all_mp3s.extend(mp3s)
                log.info(f"Generation {batch_num} done: {len(mp3s)} MP3(s) downloaded")
            except Exception as e:
                log.warning(f"Generation {batch_num} failed: {e}")
                page.screenshot(path=str(OUTPUT_DIR / f"debug_gen_{batch_num}.png"))

        browser.close()

    if not all_mp3s:
        raise RuntimeError(f"No MP3s generated after {count} attempts")

    log.info(f"Total MP3s downloaded: {len(all_mp3s)}")
    return all_mp3s


def _single_generation(page, concept: MusicConcept, safe_name: str, batch_num: int) -> list[Path]:
    """Generate one track: fill ONLY Title, click Generate, wait, download.

    Style of Music is already set by the user and stays the same.
    We only change the Title field with the track name.
    """

    # Step 1: Go to Generate page
    log.info("Navigating to Generate page...")
    page.goto("https://aimusicfactory.ai/#Generate", wait_until="networkidle", timeout=60_000)
    page.wait_for_timeout(3000)
    page.screenshot(path=str(OUTPUT_DIR / f"debug_before_gen_{batch_num}.png"))

    # Step 2: Fill ONLY the "Title" input with the track name
    # (Style of Music textarea is already filled by the user — don't touch it)
    title_filled = False

    # Try finding input fields (Title is an input, not textarea)
    text_inputs = page.query_selector_all('input[type="text"]')
    visible_inputs = [inp for inp in text_inputs if inp.is_visible()]
    log.info(f"Found {len(visible_inputs)} visible text input(s)")

    if visible_inputs:
        title_inp = visible_inputs[0]
        title_inp.click()
        title_inp.fill("")
        title_inp.fill(concept.track_name)
        title_filled = True
        log.info(f"Filled 'Title' with: {concept.track_name}")

    if not title_filled:
        # Fallback: try placeholder-based selectors
        for sel in ['input[placeholder*="itle"]', 'input[placeholder*="Title"]',
                     'input[placeholder*="name"]', 'input[placeholder*="Name"]',
                     'input[placeholder*="song"]', 'input[placeholder*="Song"]']:
            try:
                el = page.wait_for_selector(sel, timeout=3000)
                if el and el.is_visible():
                    el.click()
                    el.fill("")
                    el.fill(concept.track_name)
                    title_filled = True
                    log.info(f"Filled 'Title' via {sel}")
                    break
            except PlaywrightTimeout:
                continue

    if not title_filled:
        page.screenshot(path=str(OUTPUT_DIR / f"debug_no_title_{batch_num}.png"))
        raise RuntimeError("Could not find 'Title' input")

    page.screenshot(path=str(OUTPUT_DIR / f"debug_title_filled_{batch_num}.png"))

    # Step 3: Click Generate button
    clicked = False
    for selector in ['button:has-text("Generate")', 'button:has-text("Create")',
                      'button:has-text("Make")', '[type="submit"]',
                      ".generate-btn", "#generate"]:
        try:
            btn = page.wait_for_selector(selector, timeout=3000)
            if btn and btn.is_visible():
                btn.click()
                clicked = True
                log.info(f"Clicked: {selector}")
                break
        except PlaywrightTimeout:
            continue

    if not clicked:
        page.screenshot(path=str(OUTPUT_DIR / f"debug_no_button_{batch_num}.png"))
        raise RuntimeError("Could not find Generate button")

    # Step 4: Wait for generation (~6 minutes)
    log.info(f"Generating... waiting {GENERATION_WAIT_SEC // 60} minutes")
    for elapsed in range(0, GENERATION_WAIT_SEC, 30):
        page.wait_for_timeout(30_000)
        remaining = GENERATION_WAIT_SEC - elapsed - 30
        if remaining > 0:
            log.info(f"  {remaining // 60}m {remaining % 60}s remaining...")

    # Step 5: Go to My Music and find the newest track
    log.info("Going to My Music to download...")
    page.goto("https://aimusicfactory.ai/myMusic", wait_until="networkidle", timeout=60_000)
    page.wait_for_timeout(3000)
    page.screenshot(path=str(OUTPUT_DIR / f"debug_mymusic_{batch_num}.png"))

    # Step 6: Click on the first/newest track card to open its page
    track_link = None
    for selector in ['a[href*="/myMusic/"]', '[href*="/myMusic/"]',
                      '.track-card a', '.music-card a',
                      'a:has-text("' + concept.track_name + '")']:
        try:
            links = page.query_selector_all(selector)
            visible = [l for l in links if l.is_visible()]
            if visible:
                track_link = visible[0]  # First = newest
                log.info(f"Found track link: {selector}")
                break
        except Exception:
            continue

    if track_link:
        href = track_link.get_attribute("href") or ""
        log.info(f"Opening track page: {href}")
        track_link.click()
        page.wait_for_timeout(3000)
        page.screenshot(path=str(OUTPUT_DIR / f"debug_track_page_{batch_num}.png"))

    # Step 7: Download MP3s from track page
    downloaded = _download_mp3s(page, safe_name, batch_num)

    if not downloaded:
        page.screenshot(path=str(OUTPUT_DIR / f"debug_no_download_{batch_num}.png"))
        raise RuntimeError("Could not download MP3")

    return downloaded


def _download_mp3s(page, safe_name: str, batch_num: int) -> list[Path]:
    """Find and click download buttons on the current page."""
    for selector in ['a:has-text("Download")', 'button:has-text("Download")',
                      'a[download]', '[href*=".mp3"]', '[href*="download"]',
                      '[aria-label*="ownload"]', '[title*="ownload"]',
                      '.download-btn', 'a:has-text("download")',
                      'button:has-text("download")',
                      'svg[data-testid*="download"]']:
        try:
            elements = page.query_selector_all(selector)
            visible = [el for el in elements if el.is_visible()]
            if visible:
                log.info(f"Found {len(visible)} download button(s): {selector}")
                downloaded = []
                for i, btn in enumerate(visible[:2]):
                    try:
                        output_path = OUTPUT_DIR / f"{safe_name}_gen{batch_num}_{i + 1}.mp3"
                        with page.expect_download(timeout=120_000) as dl_info:
                            btn.click()
                        download = dl_info.value
                        download.save_as(str(output_path))
                        downloaded.append(output_path)
                        log.info(f"Downloaded: {output_path.name}")
                        page.wait_for_timeout(2000)
                    except Exception as e:
                        log.warning(f"Download {i + 1} failed: {e}")
                if downloaded:
                    return downloaded
        except Exception:
            continue

    return []


def generate_music(concept: MusicConcept) -> Path:
    """Generate a single music track (backward compatibility)."""
    mp3s = generate_music_batch(concept, count=1)
    return mp3s[0]
