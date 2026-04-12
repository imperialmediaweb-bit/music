"""Generate music on suno.com using Playwright.

Pipeline approach:
1. Open suno.com with saved session state
2. Enter the music prompt in the Create page
3. Click Create to generate songs
4. Wait for generation to complete
5. Download the generated MP3s from the library
"""

import os
import re
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from modules.concept_generator import MusicConcept
from config import OUTPUT_DIR, INPUT_DIR, HEADLESS, SUNO_STATE_FILE
from utils.logger import log


# How long to wait after clicking Create before navigating to the library.
# Suno usually finishes in ~2-4 min, but complex prompts with lyrics can
# take longer. Configurable via SUNO_GENERATION_WAIT_SEC in .env.
GENERATION_WAIT_SEC = int(os.getenv("SUNO_GENERATION_WAIT_SEC", "240"))


def _dismiss_cookie_banner(page) -> None:
    """Dismiss the OneTrust cookie consent banner if present.

    Suno uses OneTrust; the banner overlays the page and intercepts all
    pointer events until a choice is made. Try 'Reject All' first to
    minimize tracking, fall back to 'Accept All'. Also hide the root
    element as a last resort so clicks can pass through.
    """
    # Buttons exposed by OneTrust with stable IDs
    for sel in [
        "#onetrust-reject-all-handler",
        "#onetrust-accept-btn-handler",
        "button#onetrust-reject-all-handler",
        "button#onetrust-accept-btn-handler",
    ]:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                btn.click(timeout=3_000)
                log.info(f"Dismissed OneTrust cookie banner via {sel}")
                page.wait_for_timeout(500)
                return
        except Exception:
            continue

    # Fallback: remove the blocker from the DOM entirely
    try:
        page.evaluate(
            """() => {
                const ids = ['onetrust-consent-sdk', 'onetrust-banner-sdk',
                             'onetrust-button-group-parent'];
                for (const id of ids) {
                    const el = document.getElementById(id);
                    if (el) el.remove();
                }
                document.body.style.overflow = 'auto';
            }"""
        )
    except Exception:
        pass


def _find_song_menu_buttons(page) -> list:
    """Return handles for the per-song ⋯ menu buttons in Suno's workspace list.

    Rather than finding 'rows' and then the button inside them (the button
    is a sibling of the /song/ anchor, not inside it), we locate the ⋯
    buttons directly. Each row has exactly one, so the count should match
    the number of songs on the page.
    """
    candidate_selectors = [
        'button[aria-haspopup="menu"]',
        'button[aria-label*="more" i]',
        'button[aria-label*="options" i]',
        'button[data-testid*="more" i]',
        'button[data-testid*="menu" i]',
    ]
    for sel in candidate_selectors:
        try:
            buttons = page.query_selector_all(sel)
            buttons = [b for b in buttons if b.is_visible()]
            # Filter out site-wide buttons (e.g. header nav menus) — keep
            # only buttons inside the main content area by excluding those
            # with tiny bounding boxes or that sit in header/footer.
            filtered = []
            for b in buttons:
                try:
                    box = b.bounding_box()
                    if box and box["width"] > 8 and box["height"] > 8:
                        filtered.append(b)
                except Exception:
                    filtered.append(b)
            if len(filtered) >= 2:
                log.info(f"Found {len(filtered)} ⋯ menu buttons via: {sel}")
                return filtered
        except Exception:
            continue
    return []


def _download_song_mp3(page, menu_btn, target_path: Path) -> bool:
    """Given a ⋯ menu button for a song row, drive the menu → Download → MP3 flow.

    Returns True if an MP3 landed at target_path, False otherwise.
    """
    try:
        menu_btn.scroll_into_view_if_needed()
        menu_btn.click()
    except Exception as e:
        log.warning(f"⋯ menu click failed: {e}")
        return False
    page.wait_for_timeout(500)

    # Step 2: hover/click the "Download" item to expand submenu
    download_item = None
    for sel in [
        '[role="menuitem"]:has-text("Download")',
        'li:has-text("Download")',
        'button:has-text("Download")',
        ':text("Download")',
    ]:
        try:
            el = page.wait_for_selector(sel, timeout=2_000, state="visible")
            if el:
                download_item = el
                break
        except PlaywrightTimeout:
            continue
        except Exception:
            continue

    if not download_item:
        log.warning("Could not find 'Download' menu item")
        return False

    try:
        download_item.hover()
        page.wait_for_timeout(400)
    except Exception:
        pass

    # Step 3: click "MP3 Audio" in the submenu and capture the download
    mp3_selectors = [
        '[role="menuitem"]:has-text("MP3")',
        'li:has-text("MP3 Audio")',
        'button:has-text("MP3 Audio")',
        ':text("MP3 Audio")',
        ':text("MP3")',
    ]

    for sel in mp3_selectors:
        try:
            with page.expect_download(timeout=30_000) as dl_info:
                mp3_item = page.wait_for_selector(sel, timeout=3_000, state="visible")
                if not mp3_item:
                    continue
                mp3_item.click()
            download = dl_info.value
            download.save_as(str(target_path))
            return True
        except PlaywrightTimeout:
            continue
        except Exception as e:
            log.info(f"MP3 Audio selector {sel} failed: {e}")
            continue

    # Fallback: click Download directly (older Suno UIs without submenu)
    try:
        with page.expect_download(timeout=30_000) as dl_info:
            download_item.click()
        download = dl_info.value
        download.save_as(str(target_path))
        return True
    except Exception:
        pass

    return False


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
                _dismiss_cookie_banner(page)

                # Check if we're logged in (look for the create form)
                if page.url and "login" in page.url.lower():
                    log.error("Not logged in to Suno! Run 'python main.py suno-login' first.")
                    break

                # Suno's create page has Simple | Advanced | Sounds tabs.
                # We use Advanced: Lyrics (from OpenAI) + Styles (music_prompt)
                # + Create. For instrumental genres the lyrics string is empty
                # and Lyrics stays blank — Suno then generates an instrumental.
                style_text = concept.music_prompt or concept.description
                lyrics_text = (concept.lyrics or "").strip()

                # Switch to Advanced tab
                for adv_sel in ['button:has-text("Advanced")', '[role="tab"]:has-text("Advanced")']:
                    try:
                        tab = page.wait_for_selector(adv_sel, timeout=2_000)
                        if tab and tab.is_visible():
                            tab.click()
                            log.info("Switched to Suno 'Advanced' tab")
                            time.sleep(1.0)
                            break
                    except PlaywrightTimeout:
                        continue
                    except Exception:
                        continue

                # Locate the Lyrics textarea (1st) and Styles textarea (2nd)
                lyrics_ta = None
                styles_ta = None
                for sel in [
                    'section:has(:text("Lyrics")) textarea',
                    'div:has(> :text("Lyrics")) textarea',
                    'textarea[placeholder*="lyrics" i]',
                    'textarea[placeholder*="instrumental" i]',
                ]:
                    try:
                        el = page.wait_for_selector(sel, timeout=2_000, state="visible")
                        if el:
                            lyrics_ta = el
                            log.info(f"Lyrics textarea located: {sel}")
                            break
                    except PlaywrightTimeout:
                        continue
                    except Exception:
                        continue

                for sel in [
                    'section:has(:text("Styles")) textarea',
                    'div:has(> :text("Styles")) textarea',
                    'textarea[placeholder*="style" i]',
                    'textarea[placeholder*="genre" i]',
                ]:
                    try:
                        el = page.wait_for_selector(sel, timeout=2_000, state="visible")
                        if el:
                            styles_ta = el
                            log.info(f"Styles textarea located: {sel}")
                            break
                    except PlaywrightTimeout:
                        continue
                    except Exception:
                        continue

                # Fallback by order (Lyrics first, Styles second) if the
                # structural selectors above didn't match
                if not lyrics_ta or not styles_ta:
                    textareas = [t for t in page.query_selector_all("textarea") if t.is_visible()]
                    log.info(f"Advanced fallback: {len(textareas)} visible textareas")
                    if len(textareas) >= 2:
                        lyrics_ta = lyrics_ta or textareas[0]
                        styles_ta = styles_ta or textareas[1]

                if not styles_ta:
                    log.error("Could not find Styles textarea on Suno Advanced tab")
                    page.screenshot(path=str(OUTPUT_DIR / "debug_suno_prompt.png"), full_page=True)
                    break

                # Fill Lyrics (or leave empty for instrumental)
                if lyrics_ta and lyrics_text:
                    try:
                        lyrics_ta.click()
                        lyrics_ta.fill(lyrics_text)
                        log.info(f"Lyrics filled ({len(lyrics_text)} chars)")
                    except Exception as e:
                        log.warning(f"Lyrics fill failed: {e}")
                else:
                    log.info("Lyrics left empty (instrumental)")

                # Fill Styles (required for Create button to enable)
                try:
                    styles_ta.click()
                    styles_ta.fill(style_text)
                    log.info(f"Styles filled ({len(style_text)} chars)")
                    prompt_filled = True
                except Exception as e:
                    log.error(f"Styles fill failed: {e}")
                    page.screenshot(path=str(OUTPUT_DIR / "debug_suno_prompt.png"), full_page=True)
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
                _dismiss_cookie_banner(page)

                # Find ⋯ menu buttons for the latest 2 songs in the workspace
                menu_buttons = _find_song_menu_buttons(page)[:2]
                log.info(f"Downloading latest {len(menu_buttons)} song(s)")

                for i, menu_btn in enumerate(menu_buttons):
                    mp3_path = download_dir / f"{safe_name}_suno_{batch_idx}_{i}.mp3"
                    try:
                        ok = _download_song_mp3(page, menu_btn, mp3_path)
                        if ok and _validate_mp3(mp3_path):
                            all_mp3s.append(mp3_path)
                            log.info(f"Downloaded: {mp3_path.name}")
                        else:
                            log.warning(f"Download failed or invalid MP3 for song {i}")
                        # Close any open menu before next iteration
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(400)
                    except Exception as e:
                        log.warning(f"Failed to download song {i}: {e}")
                        try:
                            page.keyboard.press("Escape")
                        except Exception:
                            pass
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
        _dismiss_cookie_banner(page)

        menu_buttons = _find_song_menu_buttons(page)[:max_cards]
        log.info(f"Downloading latest {len(menu_buttons)} song(s) from library")

        for i, menu_btn in enumerate(menu_buttons):
            mp3_path = download_dir / f"{safe_name}_{i}.mp3"
            try:
                ok = _download_song_mp3(page, menu_btn, mp3_path)
                if ok and _validate_mp3(mp3_path):
                    all_mp3s.append(mp3_path)
                    log.info(f"Downloaded: {mp3_path.name}")
                else:
                    log.warning(f"Download failed or invalid MP3 for song {i}")
                page.keyboard.press("Escape")
                page.wait_for_timeout(400)
            except Exception as e:
                log.warning(f"Failed to download song {i}: {e}")
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass

        try:
            context.storage_state(path=str(state_file))
        except Exception:
            pass

        browser.close()

    log.info(f"Suno: downloaded {len(all_mp3s)} MP3 files")
    return all_mp3s
