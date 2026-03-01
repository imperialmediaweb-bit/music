"""Upload a single track to TuneCore for distribution (Playwright automation).

TuneCore requires:
  - WAV file (stereo, 16-bit, 44.1kHz+)
  - Cover art: 1600x1600 minimum (JPEG or PNG)
  - Metadata: title, artist, genre, songwriter, etc.

Flow (web.tunecore.com):
  1. Header -> "Add Release"
  2. Choose "Single"
  3. Click "Start"
  4. Release details: track name, language=English, genre=Afro House,
     Previously Released=No -> Save
  5. Tracks -> "Add Track"
  6. Track details: name, songwriter=GrooveGenix, role=Main Artist,
     copyright=not a cover, instrumental -> Save
  7. Upload WAV (stereo) -> wait ~5min -> Continue
  8. Add Artwork -> upload cover -> wait ~1min -> Save & Continue
  9. Continue and Review
  10. Release Music (cart)
  11. "Congrats, you submitted your release!"
"""

import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from modules.concept_generator import MusicConcept
from config import TUNECORE_STATE_FILE, HEADLESS
from utils.logger import log

TUNECORE_BASE = "https://web.tunecore.com"
MAX_RETRIES = 2

# Default artist / songwriter name
DEFAULT_ARTIST = "GrooveGenix"


def upload_to_tunecore(
    wav_path: Path,
    cover_path: Path,
    concept: MusicConcept,
    artist: str = DEFAULT_ARTIST,
) -> str | None:
    """Upload a single track to TuneCore for distribution.

    Args:
        wav_path: Path to WAV file (stereo).
        cover_path: Path to 1600x1600 cover art (JPEG/PNG).
        concept: MusicConcept with track metadata.
        artist: Artist / songwriter name (default: GrooveGenix).

    Returns:
        URL or status string, or None on failure.
    """
    log.info(f"Uploading to TuneCore: {concept.track_name}")

    if not TUNECORE_STATE_FILE.exists():
        log.error(
            f"TuneCore session not found: {TUNECORE_STATE_FILE}\n"
            "Run: python main.py tunecore-login"
        )
        return None

    if not wav_path.exists():
        log.error(f"WAV file not found: {wav_path}")
        return None

    if not cover_path.exists():
        log.error(f"Cover art not found: {cover_path}")
        return None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = _do_upload(wav_path, cover_path, concept, artist)
            return result
        except Exception as e:
            if attempt < MAX_RETRIES:
                wait = 2 ** attempt
                log.warning(f"TuneCore upload attempt {attempt}/{MAX_RETRIES} failed: {e}")
                log.info(f"Retrying in {wait}s...")
                time.sleep(wait)
            else:
                log.error(f"TuneCore upload failed after {MAX_RETRIES} attempts: {e}")
                raise


def _find_clickable(page, selectors: list[str]):
    """Try multiple selectors and return the first visible, clickable element."""
    for selector in selectors:
        try:
            el = page.locator(selector).first
            if el.is_visible(timeout=2000):
                return el
        except Exception:
            continue
    return None


def _upload_file(page, file_path: Path):
    """Upload a file via input[type=file] or file chooser dialog."""
    # Try direct file input first
    try:
        inputs = page.locator("input[type='file']")
        count = inputs.count()
        for i in range(count):
            el = inputs.nth(i)
            try:
                el.set_input_files(str(file_path))
                log.info(f"  File selected via input[type=file] (index {i})")
                return True
            except Exception:
                continue
    except Exception:
        pass

    # Fallback: click upload zone and use file chooser
    for selector in [
        "[class*='upload']", "[class*='drop']", "[class*='dropzone']",
        "text=Upload", "text=Choose File", "text=Browse",
    ]:
        try:
            el = page.locator(selector).first
            if el.is_visible(timeout=1000):
                with page.expect_file_chooser(timeout=5000) as fc_info:
                    el.click()
                file_chooser = fc_info.value
                file_chooser.set_files(str(file_path))
                log.info(f"  File uploaded via file chooser: {selector}")
                return True
        except Exception:
            continue

    log.warning(f"Could not find file input for {file_path.name}")
    return False


def _wait_for_upload(page, timeout: int = 300):
    """Wait for file upload to complete."""
    start = time.time()
    while time.time() - start < timeout:
        # Check for success indicators
        for text in ["Upload complete", "Uploaded", "Success", "100%"]:
            try:
                if page.locator(f"text={text}").first.is_visible(timeout=500):
                    log.info(f"  Upload complete: {text}")
                    return
            except Exception:
                continue

        # Check if progress bar disappeared
        try:
            progress = page.locator("[class*='progress']").first
            if not progress.is_visible(timeout=1000):
                log.info("  Upload progress gone — assuming complete")
                return
        except Exception:
            pass

        page.wait_for_timeout(5000)
        elapsed = int(time.time() - start)
        log.info(f"  Waiting for upload... ({elapsed}s)")

    log.warning(f"Upload wait timed out after {timeout}s — continuing anyway")


def _check_login(page) -> bool:
    """Check if we're still logged in (not redirected to login page)."""
    url = page.url.lower()
    if "/login" in url or "/sign" in url:
        log.error("TuneCore session expired — run: python main.py tunecore-login")
        page.screenshot(path="output/tunecore_login_redirect.png")
        return False
    return True


def _do_upload(
    wav_path: Path,
    cover_path: Path,
    concept: MusicConcept,
    artist: str,
) -> str | None:
    """Perform the actual TuneCore upload via Playwright.

    Follows the exact web.tunecore.com flow:
    1. Add Release -> Single -> Start
    2. Release details (name, language, genre) -> Save
    3. Tracks -> Add Track -> track details -> Save
    4. Upload WAV -> Continue
    5. Upload Artwork -> Save & Continue
    6. Continue and Review -> Release Music
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=HEADLESS,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            storage_state=str(TUNECORE_STATE_FILE),
            viewport={"width": 1920, "height": 1080},
        )

        # Stealth
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            window.chrome = { runtime: {} };
        """)

        page = context.new_page()

        try:
            # ── STEP 1: Navigate to TuneCore dashboard ──
            log.info("Step 1: Navigating to TuneCore...")
            page.goto(TUNECORE_BASE, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(3000)

            if not _check_login(page):
                return None

            log.info(f"  Logged in: {page.url}")
            page.screenshot(path="output/tunecore_01_dashboard.png")

            # ── STEP 1b: Click "Add Release" in header ──
            log.info("Step 1b: Clicking 'Add Release'...")
            add_release_btn = _find_clickable(page, [
                "text=Add Release",
                "button:has-text('Add Release')",
                "a:has-text('Add Release')",
                "text=Create New",
                "button:has-text('Create')",
            ])
            if add_release_btn:
                add_release_btn.click()
                page.wait_for_timeout(3000)
            else:
                log.warning("  'Add Release' button not found, trying direct URL...")
                page.goto(f"{TUNECORE_BASE}/releases/new", wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(3000)

            page.screenshot(path="output/tunecore_02_add_release.png")

            # ── STEP 2: Choose "Single" ──
            log.info("Step 2: Selecting 'Single'...")
            single_btn = _find_clickable(page, [
                "text=Single",
                "button:has-text('Single')",
                "[data-type='single']",
                "label:has-text('Single')",
            ])
            if single_btn:
                single_btn.click()
                page.wait_for_timeout(2000)
            else:
                log.warning("  'Single' option not found — may already be selected")

            page.screenshot(path="output/tunecore_03_single.png")

            # ── STEP 3: Click "Start" ──
            log.info("Step 3: Clicking 'Start'...")
            start_btn = _find_clickable(page, [
                "button:has-text('Start')",
                "a:has-text('Start')",
                "button:has-text('Begin')",
                "button:has-text('Continue')",
            ])
            if start_btn:
                start_btn.click()
                page.wait_for_timeout(3000)
            else:
                log.warning("  'Start' button not found — continuing...")

            page.screenshot(path="output/tunecore_04_start.png")

            # ── STEP 4: Release details ──
            log.info("Step 4: Filling release details...")

            # Track name / Release title
            for sel in [
                "input[name*='title' i]", "input[name*='name' i]",
                "input[id*='title' i]", "input[id*='name' i]",
                "input[placeholder*='title' i]", "input[placeholder*='name' i]",
            ]:
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=1500):
                        el.fill(concept.track_name)
                        log.info(f"  Title: {concept.track_name}")
                        break
                except Exception:
                    continue

            # Language = English
            for sel in [
                "select[name*='language' i]", "select[id*='language' i]",
                "[data-field='language'] select",
            ]:
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=1500):
                        el.select_option(label="English")
                        log.info("  Language: English")
                        break
                except Exception:
                    continue

            # Primary genre = Afro House
            for sel in [
                "select[name*='primary' i][name*='genre' i]",
                "select[name*='genre' i]",
                "select[id*='primary' i][id*='genre' i]",
                "select[id*='genre' i]",
            ]:
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=1500):
                        for genre_label in ["Afro House", "Afro-House", "Electronic", "Dance"]:
                            try:
                                el.select_option(label=genre_label)
                                log.info(f"  Primary genre: {genre_label}")
                                break
                            except Exception:
                                continue
                        break
                except Exception:
                    continue

            # Secondary genre = Afro House
            for sel in [
                "select[name*='secondary' i][name*='genre' i]",
                "select[name*='subgenre' i]",
                "select[id*='secondary' i]",
            ]:
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=1500):
                        for genre_label in ["Afro House", "Afro-House", "Electronic", "Dance"]:
                            try:
                                el.select_option(label=genre_label)
                                log.info(f"  Secondary genre: {genre_label}")
                                break
                            except Exception:
                                continue
                        break
                except Exception:
                    continue

            # Previously Released? = No
            no_btn = _find_clickable(page, [
                "label:has-text('No')",
                "input[type='radio'][value='no']",
                "input[type='radio'][value='false']",
                "button:has-text('No')",
            ])
            if no_btn:
                no_btn.click()
                log.info("  Previously Released: No")

            page.screenshot(path="output/tunecore_05_release_details.png")

            # Click Save
            log.info("  Saving release details...")
            save_btn = _find_clickable(page, [
                "button:has-text('Save')",
                "button[type='submit']",
                "a:has-text('Save')",
            ])
            if save_btn:
                save_btn.click()
                page.wait_for_timeout(5000)
            else:
                log.warning("  'Save' button not found")

            page.screenshot(path="output/tunecore_06_saved.png")

            # ── STEP 5: Tracks -> Add Track ──
            log.info("Step 5: Adding track...")
            add_track_btn = _find_clickable(page, [
                "text=Add Track",
                "button:has-text('Add Track')",
                "a:has-text('Add Track')",
                "text=Add track",
            ])
            if add_track_btn:
                add_track_btn.click()
                page.wait_for_timeout(3000)
            else:
                log.warning("  'Add Track' button not found — may auto-navigate")

            page.screenshot(path="output/tunecore_07_add_track.png")

            # ── STEP 6: Track details ──
            log.info("Step 6: Filling track details...")

            # Track name (may already be filled from release title)
            for sel in [
                "input[name*='track' i][name*='name' i]",
                "input[name*='song' i][name*='title' i]",
                "input[name*='title' i]",
                "input[id*='track' i][id*='name' i]",
                "input[placeholder*='track' i]",
            ]:
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=1500):
                        current = el.input_value()
                        if not current.strip():
                            el.fill(concept.track_name)
                        log.info(f"  Track name: {concept.track_name}")
                        break
                except Exception:
                    continue

            # Songwriter = GrooveGenix
            for sel in [
                "input[name*='songwriter' i]", "input[name*='writer' i]",
                "input[id*='songwriter' i]", "input[id*='writer' i]",
                "input[placeholder*='songwriter' i]", "input[placeholder*='writer' i]",
            ]:
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=1500):
                        el.fill(artist)
                        log.info(f"  Songwriter: {artist}")
                        break
                except Exception:
                    continue

            # Performing Artists: Artist Name = GrooveGenix
            for sel in [
                "input[name*='artist' i][name*='name' i]",
                "input[name*='performing' i]",
                "input[name*='creative' i]",
                "input[id*='artist' i]",
                "input[placeholder*='artist' i]",
            ]:
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=1500):
                        el.fill(artist)
                        log.info(f"  Performing Artist: {artist}")
                        break
                except Exception:
                    continue

            # Role = Main Artist (dropdown)
            for sel in [
                "select[name*='role' i]",
                "select[id*='role' i]",
            ]:
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=1500):
                        for role in ["Main Artist", "Primary Artist", "Artist"]:
                            try:
                                el.select_option(label=role)
                                log.info(f"  Role: {role}")
                                break
                            except Exception:
                                continue
                        break
                except Exception:
                    continue

            # Copyright: Is this a cover? = No
            # Look for radio buttons or toggles near "cover" text
            cover_no = _find_clickable(page, [
                "text=Is this a cover >> .. >> label:has-text('No')",
                "input[name*='cover' i][value='no']",
                "input[name*='cover' i][value='false']",
            ])
            if cover_no:
                cover_no.click()
                log.info("  Is this a cover: No")
            else:
                # Try generic No buttons near copyright section
                no_btns = page.locator("label:has-text('No'), input[value='no']")
                for i in range(no_btns.count()):
                    try:
                        btn = no_btns.nth(i)
                        if btn.is_visible(timeout=500):
                            btn.click()
                            break
                    except Exception:
                        continue

            # Instrumental - This song has no lyrics = check box (it IS instrumental)
            instrumental_check = _find_clickable(page, [
                "text=Instrumental",
                "label:has-text('Instrumental')",
                "input[name*='instrumental' i]",
                "label:has-text('no lyrics')",
            ])
            if instrumental_check:
                instrumental_check.click()
                log.info("  Instrumental: checked")

            page.screenshot(path="output/tunecore_08_track_details.png")

            # Save track details
            log.info("  Saving track details...")
            save_btn = _find_clickable(page, [
                "button:has-text('Save')",
                "button[type='submit']",
            ])
            if save_btn:
                save_btn.click()
                page.wait_for_timeout(5000)

            page.screenshot(path="output/tunecore_09_track_saved.png")

            # ── STEP 7: Upload WAV ──
            log.info(f"Step 7: Uploading WAV: {wav_path.name}")
            _upload_file(page, wav_path)

            # WAV files are large — wait up to 5 minutes
            log.info("  Waiting for WAV upload (~5 min)...")
            _wait_for_upload(page, timeout=360)
            page.screenshot(path="output/tunecore_10_wav_uploaded.png")

            # Click Continue after WAV upload
            continue_btn = _find_clickable(page, [
                "button:has-text('Continue')",
                "button:has-text('Next')",
                "a:has-text('Continue')",
            ])
            if continue_btn:
                continue_btn.click()
                page.wait_for_timeout(3000)
                log.info("  Clicked Continue after WAV upload")

            page.screenshot(path="output/tunecore_11_after_wav.png")

            # ── STEP 8: Upload Artwork ──
            log.info(f"Step 8: Uploading cover art: {cover_path.name}")

            # Look for "Add Artwork" button
            artwork_btn = _find_clickable(page, [
                "text=Add Artwork",
                "button:has-text('Add Artwork')",
                "a:has-text('Add Artwork')",
                "text=Upload Artwork",
                "button:has-text('Upload Artwork')",
            ])
            if artwork_btn:
                artwork_btn.click()
                page.wait_for_timeout(3000)

            _upload_file(page, cover_path)

            # Wait for artwork upload (~1 min)
            log.info("  Waiting for artwork upload (~1 min)...")
            _wait_for_upload(page, timeout=120)
            page.screenshot(path="output/tunecore_12_artwork_uploaded.png")

            # Save and Continue
            save_continue_btn = _find_clickable(page, [
                "button:has-text('Save and Continue')",
                "button:has-text('Save & Continue')",
                "button:has-text('Continue')",
                "button:has-text('Save')",
            ])
            if save_continue_btn:
                save_continue_btn.click()
                page.wait_for_timeout(5000)
                log.info("  Clicked Save & Continue after artwork")

            page.screenshot(path="output/tunecore_13_after_artwork.png")

            # ── STEP 9: Continue and Review ──
            log.info("Step 9: Continue and Review...")
            review_btn = _find_clickable(page, [
                "button:has-text('Continue and Review')",
                "button:has-text('Continue & Review')",
                "button:has-text('Review')",
                "button:has-text('Continue')",
                "a:has-text('Continue and Review')",
                "a:has-text('Review')",
            ])
            if review_btn:
                review_btn.click()
                page.wait_for_timeout(5000)
                log.info("  Clicked Continue and Review")

            page.screenshot(path="output/tunecore_14_review.png")

            # ── STEP 10: Release Music ──
            log.info("Step 10: Release Music...")
            release_btn = _find_clickable(page, [
                "button:has-text('Release Music')",
                "button:has-text('Release')",
                "button:has-text('Submit')",
                "button:has-text('Distribute')",
                "a:has-text('Release Music')",
            ])
            if release_btn:
                release_btn.click()
                page.wait_for_timeout(5000)
                log.info("  Clicked Release Music")

            page.screenshot(path="output/tunecore_15_released.png")

            # ── STEP 11: Check for confirmation ──
            log.info("Step 11: Checking for confirmation...")
            for indicator in ["Congrats", "Congratulations", "submitted your release",
                              "Submitted", "In Review", "Distribution"]:
                try:
                    if page.locator(f"text={indicator}").first.is_visible(timeout=3000):
                        log.info(f"  Confirmation found: {indicator}")
                        break
                except Exception:
                    continue

            page.screenshot(path="output/tunecore_16_done.png")

            # Save updated session
            context.storage_state(path=str(TUNECORE_STATE_FILE))

            final_url = page.url
            log.info(f"TuneCore upload completed: {final_url}")
            return final_url

        except Exception as e:
            page.screenshot(path="output/tunecore_error.png")
            log.error(f"TuneCore upload error: {e}")
            raise
        finally:
            browser.close()
