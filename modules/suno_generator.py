"""Generate music on suno.com using Playwright.

Pipeline approach:
1. Open suno.com with saved session state
2. Enter the music prompt in the Create page
3. Click Create to generate songs
4. Wait for generation to complete
5. Download the generated MP3s from the library
"""

import re
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from modules.concept_generator import MusicConcept
from config import OUTPUT_DIR, INPUT_DIR, HEADLESS, SUNO_STATE_FILE
from utils.logger import log


GENERATION_WAIT_SEC = 120  # Suno typically takes ~1-2 min per generation


def _validate_mp3(path: Path) -> bool:
    """Check if a file is a valid MP3."""
    if not path.exists():
        return False
    size = path.stat().st_size
    if size < 50_000:
        log.warning(f"Validation: file too small ({size} bytes): {path.name}")
        return False
    header = path.read_bytes()[:16]
    if header[:3] == b'ID3':
        return True
    if len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0:
        return True
    return False


def generate_music_batch(concept: MusicConcept, count: int = 1) -> list[Path]:
    """Generate music on suno.com.

    Each generation on Suno creates 2 songs.

    Args:
        concept: The music concept with the prompt.
        count: Number of times to hit Create (each gives 2 MP3s).

    Returns:
        List of downloaded MP3 file paths.
    """
    log.info(f"Generating {count} batch(es) on suno.com for: {concept.track_name}")

    safe_name = "".join(c if c.isalnum() or c in "-_ " else "" for c in concept.track_name)
    safe_name = safe_name.strip().replace(" ", "_")[:50]

    all_mp3s = []
    download_dir = INPUT_DIR / "suno_downloads"
    download_dir.mkdir(parents=True, exist_ok=True)

    state_file = SUNO_STATE_FILE

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=HEADLESS,
            args=["--disable-blink-features=AutomationControlled"],
        )

        # Load saved session state if available
        context_opts = {"viewport": {"width": 1920, "height": 1080}}
        if state_file.exists():
            context_opts["storage_state"] = str(state_file)
            log.info(f"Loading Suno session from: {state_file}")
        else:
            log.warning(f"No Suno session found at {state_file} — run 'python main.py suno-login' first")

        context = browser.new_context(**context_opts)

        # Set up download handling
        page = context.new_page()

        for batch_idx in range(count):
            log.info(f"--- Suno batch {batch_idx + 1}/{count} ---")

            try:
                # Navigate to Suno create page
                log.info("Opening suno.com/create ...")
                page.goto("https://suno.com/create", wait_until="domcontentloaded", timeout=60_000)
                time.sleep(3)

                # Check if we're logged in (look for the create form)
                if page.url and "login" in page.url.lower():
                    log.error("Not logged in to Suno! Run 'python main.py suno-login' first.")
                    break

                # Find and fill the prompt textarea
                log.info("Filling in music prompt...")
                prompt_text = concept.music_prompt or concept.description

                # Try multiple selectors for the prompt input
                prompt_selectors = [
                    'textarea[placeholder*="song"]',
                    'textarea[placeholder*="describe"]',
                    'textarea[placeholder*="prompt"]',
                    'textarea[data-testid="prompt-input"]',
                    'textarea',
                    '[contenteditable="true"]',
                ]

                prompt_filled = False
                for sel in prompt_selectors:
                    try:
                        el = page.wait_for_selector(sel, timeout=5_000)
                        if el:
                            el.click()
                            el.fill(prompt_text)
                            prompt_filled = True
                            log.info(f"Prompt filled using selector: {sel}")
                            break
                    except PlaywrightTimeout:
                        continue

                if not prompt_filled:
                    log.error("Could not find prompt input on Suno create page")
                    page.screenshot(path=str(OUTPUT_DIR / "debug_suno_prompt.png"))
                    break

                # Click Create / Generate button
                log.info("Clicking Create button...")
                # Give the UI a moment to enable the Create button after filling
                # the prompt (Suno often disables it until the textarea has text).
                time.sleep(1.5)
                create_selectors = [
                    'button[data-testid="create-button"]',
                    'button[aria-label="Create"]',
                    'button:has-text("Create")',
                    'button:has-text("Generate")',
                    'button[type="submit"]',
                    # Fallbacks that match nested spans / icons inside the button
                    'button >> text=Create',
                    'button >> text=Generate',
                    '[role="button"]:has-text("Create")',
                ]

                create_clicked = False
                for sel in create_selectors:
                    try:
                        btn = page.wait_for_selector(sel, timeout=3_000, state="visible")
                        if not btn:
                            continue
                        # Skip disabled buttons
                        if btn.is_disabled():
                            log.info(f"Selector matched but button is disabled: {sel}")
                            continue
                        btn.scroll_into_view_if_needed()
                        btn.click()
                        create_clicked = True
                        log.info(f"Create button clicked: {sel}")
                        break
                    except PlaywrightTimeout:
                        continue
                    except Exception as e:
                        log.info(f"Selector {sel} failed: {e}")
                        continue

                if not create_clicked:
                    # Last-resort: enumerate every enabled button and pick one
                    # whose text contains "create" (case-insensitive).
                    try:
                        buttons = page.query_selector_all("button, [role='button']")
                        log.info(f"Found {len(buttons)} button-like elements; scanning for 'Create'...")
                        button_texts = []
                        for b in buttons:
                            try:
                                if not b.is_visible() or b.is_disabled():
                                    continue
                                txt = (b.inner_text() or "").strip()
                                if txt:
                                    button_texts.append(txt)
                                if txt and "create" in txt.lower() and len(txt) < 30:
                                    b.scroll_into_view_if_needed()
                                    b.click()
                                    create_clicked = True
                                    log.info(f"Create button clicked via text scan: '{txt}'")
                                    break
                            except Exception:
                                continue
                        if not create_clicked:
                            log.error(f"Enabled button texts on page: {button_texts[:30]}")
                    except Exception as e:
                        log.error(f"Button text scan failed: {e}")

                if not create_clicked:
                    log.error("Could not find Create button on Suno")
                    page.screenshot(path=str(OUTPUT_DIR / "debug_suno_create.png"), full_page=True)
                    break

                # Wait for generation to complete
                log.info(f"Waiting for Suno generation (~{GENERATION_WAIT_SEC}s)...")
                time.sleep(GENERATION_WAIT_SEC)

                # Navigate to library to find and download the generated songs
                log.info("Going to library to download songs...")
                page.goto("https://suno.com/me", wait_until="domcontentloaded", timeout=60_000)
                time.sleep(5)

                # Find download buttons for the latest songs
                # Suno shows songs in a list — look for download/three-dot menus
                song_cards = page.query_selector_all('[data-testid="song-card"], .song-row, [class*="song"], [class*="track"]')
                if not song_cards:
                    # Fallback: try to find any clickable song items
                    song_cards = page.query_selector_all('a[href*="/song/"]')

                songs_to_download = song_cards[:2]  # Latest 2 songs from this batch
                log.info(f"Found {len(song_cards)} songs, downloading latest {len(songs_to_download)}")

                for i, card in enumerate(songs_to_download):
                    try:
                        card.click()
                        time.sleep(2)

                        # Look for download option in the song detail/menu
                        download_selectors = [
                            'button:has-text("Download")',
                            'a:has-text("Download")',
                            '[data-testid="download-button"]',
                            'button[aria-label*="download" i]',
                            'a[download]',
                        ]

                        # Try three-dot menu first
                        for menu_sel in ['button[aria-label*="more" i]', 'button:has-text("...")', '[data-testid="menu-button"]']:
                            try:
                                menu = page.wait_for_selector(menu_sel, timeout=3_000)
                                if menu:
                                    menu.click()
                                    time.sleep(1)
                                    break
                            except PlaywrightTimeout:
                                continue

                        for dl_sel in download_selectors:
                            try:
                                with page.expect_download(timeout=30_000) as dl_info:
                                    dl_btn = page.wait_for_selector(dl_sel, timeout=5_000)
                                    if dl_btn:
                                        dl_btn.click()

                                download = dl_info.value
                                mp3_path = download_dir / f"{safe_name}_suno_{batch_idx}_{i}.mp3"
                                download.save_as(str(mp3_path))

                                if _validate_mp3(mp3_path):
                                    all_mp3s.append(mp3_path)
                                    log.info(f"Downloaded: {mp3_path.name}")
                                else:
                                    log.warning(f"Invalid MP3: {mp3_path.name}")
                                break
                            except (PlaywrightTimeout, Exception) as e:
                                continue

                        # Go back to library for next song
                        page.goto("https://suno.com/me", wait_until="domcontentloaded", timeout=30_000)
                        time.sleep(2)

                    except Exception as e:
                        log.warning(f"Failed to download song {i}: {e}")
                        continue

            except Exception as e:
                log.error(f"Suno batch {batch_idx + 1} failed: {e}")
                page.screenshot(path=str(OUTPUT_DIR / f"debug_suno_batch_{batch_idx}.png"))
                continue

        # Save session state for next time
        try:
            context.storage_state(path=str(state_file))
            log.info(f"Suno session saved to: {state_file}")
        except Exception:
            pass

        browser.close()

    if not all_mp3s:
        raise RuntimeError(
            "No MP3 files downloaded from Suno. "
            "Make sure you're logged in (run 'python main.py suno-login') "
            "and have enough credits."
        )

    log.info(f"Suno: downloaded {len(all_mp3s)} MP3 files total")
    return all_mp3s


def download_existing_tracks(track_name: str = "", max_cards: int = 4) -> list[Path]:
    """Download existing tracks from Suno library.

    Goes to the user's library and downloads the latest tracks.
    """
    log.info(f"Downloading existing tracks from Suno library...")

    download_dir = INPUT_DIR / "suno_downloads"
    download_dir.mkdir(parents=True, exist_ok=True)

    safe_name = "".join(c if c.isalnum() or c in "-_ " else "" for c in track_name)
    safe_name = safe_name.strip().replace(" ", "_")[:50] or "suno"

    all_mp3s = []
    state_file = SUNO_STATE_FILE

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=HEADLESS,
            args=["--disable-blink-features=AutomationControlled"],
        )

        context_opts = {"viewport": {"width": 1920, "height": 1080}}
        if state_file.exists():
            context_opts["storage_state"] = str(state_file)

        context = browser.new_context(**context_opts)
        page = context.new_page()

        page.goto("https://suno.com/me", wait_until="domcontentloaded", timeout=60_000)
        time.sleep(5)

        # Find song cards
        song_cards = page.query_selector_all('[data-testid="song-card"], .song-row, a[href*="/song/"]')
        cards_to_process = song_cards[:max_cards]
        log.info(f"Found {len(song_cards)} songs, processing {len(cards_to_process)}")

        for i, card in enumerate(cards_to_process):
            try:
                card.click()
                time.sleep(2)

                # Open menu and click download
                for menu_sel in ['button[aria-label*="more" i]', 'button:has-text("...")']:
                    try:
                        menu = page.wait_for_selector(menu_sel, timeout=3_000)
                        if menu:
                            menu.click()
                            time.sleep(1)
                            break
                    except PlaywrightTimeout:
                        continue

                for dl_sel in ['button:has-text("Download")', 'a:has-text("Download")', 'a[download]']:
                    try:
                        with page.expect_download(timeout=30_000) as dl_info:
                            dl_btn = page.wait_for_selector(dl_sel, timeout=5_000)
                            if dl_btn:
                                dl_btn.click()

                        download = dl_info.value
                        mp3_path = download_dir / f"{safe_name}_{i}.mp3"
                        download.save_as(str(mp3_path))

                        if _validate_mp3(mp3_path):
                            all_mp3s.append(mp3_path)
                            log.info(f"Downloaded: {mp3_path.name}")
                        break
                    except (PlaywrightTimeout, Exception):
                        continue

                page.goto("https://suno.com/me", wait_until="domcontentloaded", timeout=30_000)
                time.sleep(2)

            except Exception as e:
                log.warning(f"Failed to download song {i}: {e}")

        try:
            context.storage_state(path=str(state_file))
        except Exception:
            pass

        browser.close()

    log.info(f"Suno: downloaded {len(all_mp3s)} MP3 files")
    return all_mp3s
