"""Upload a single track to TuneCore for distribution (Playwright automation).

TuneCore requires:
  - WAV file (16-bit, 44.1kHz+)
  - Cover art: 1600x1600 minimum (JPEG or PNG)
  - Metadata: title, artist, genre, etc.

Flow:
  1. Go to TuneCore dashboard → Create New Single
  2. Fill in metadata (title, artist, genre)
  3. Upload WAV file
  4. Upload cover art
  5. Set release date + pricing
  6. Submit for distribution
"""

import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from modules.concept_generator import MusicConcept
from config import TUNECORE_STATE_FILE, HEADLESS
from utils.logger import log

TUNECORE_BASE = "https://www.tunecore.com"
MAX_RETRIES = 2

# Default artist name — override via .env or concept
DEFAULT_ARTIST = "LUTH"


def upload_to_tunecore(
    wav_path: Path,
    cover_path: Path,
    concept: MusicConcept,
    artist: str = DEFAULT_ARTIST,
) -> str | None:
    """Upload a single track to TuneCore for distribution.

    Args:
        wav_path: Path to WAV file.
        cover_path: Path to 1600x1600 cover art (JPEG/PNG).
        concept: MusicConcept with track metadata.
        artist: Artist name (default: LUTH).

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


def _do_upload(
    wav_path: Path,
    cover_path: Path,
    concept: MusicConcept,
    artist: str,
) -> str | None:
    """Perform the actual TuneCore upload via Playwright."""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=HEADLESS,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            storage_state=str(TUNECORE_STATE_FILE),
            viewport={"width": 1920, "height": 1080},
        )

        # Inject stealth script
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            window.chrome = { runtime: {} };
        """)

        page = context.new_page()

        try:
            # Step 1: Navigate to TuneCore and check login
            log.info("Navigating to TuneCore...")
            page.goto(f"{TUNECORE_BASE}/music", wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(3000)

            # Check if redirected to login
            if "/login" in page.url or "/sign" in page.url:
                log.error("TuneCore session expired — run: python main.py tunecore-login")
                page.screenshot(path="output/tunecore_login_redirect.png")
                return None

            log.info(f"Logged in, current page: {page.url}")
            page.screenshot(path="output/tunecore_dashboard.png")

            # Step 2: Create new single
            log.info("Creating new single...")
            # Look for "Create New" or "New Release" button
            new_release_btn = _find_clickable(page, [
                "text=Create New",
                "text=New Release",
                "text=New Single",
                "text=Add New",
                "a[href*='new']",
                "button:has-text('Create')",
            ])
            if new_release_btn:
                new_release_btn.click()
                page.wait_for_timeout(3000)
            else:
                # Try direct URL
                log.info("Trying direct URL for new single...")
                page.goto(f"{TUNECORE_BASE}/music/new", wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(3000)

            page.screenshot(path="output/tunecore_new_release.png")
            log.info(f"New release page: {page.url}")

            # Step 3: Select "Single" type if prompted
            single_btn = _find_clickable(page, [
                "text=Single",
                "button:has-text('Single')",
                "[data-type='single']",
            ])
            if single_btn:
                single_btn.click()
                page.wait_for_timeout(2000)

            # Step 4: Fill metadata
            log.info("Filling track metadata...")
            _fill_metadata(page, concept, artist)
            page.screenshot(path="output/tunecore_metadata.png")

            # Step 5: Upload cover art
            log.info(f"Uploading cover art: {cover_path.name}")
            _upload_file(page, cover_path, file_type="image")
            page.wait_for_timeout(5000)
            page.screenshot(path="output/tunecore_cover_uploaded.png")

            # Step 6: Upload WAV file
            log.info(f"Uploading WAV: {wav_path.name}")
            _upload_file(page, wav_path, file_type="audio")

            # Wait for upload to complete (WAV files are large)
            log.info("Waiting for WAV upload to complete...")
            _wait_for_upload(page, timeout=300)
            page.screenshot(path="output/tunecore_wav_uploaded.png")

            # Step 7: Continue / Next / Submit
            log.info("Proceeding through submission steps...")
            _click_through_steps(page)
            page.screenshot(path="output/tunecore_submitted.png")

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


def _fill_metadata(page, concept: MusicConcept, artist: str):
    """Fill in track metadata fields on the TuneCore form."""
    # Common field patterns on TuneCore
    field_map = {
        "title": concept.track_name,
        "artist": artist,
        "song_title": concept.track_name,
        "primary_artist": artist,
    }

    for field_name, value in field_map.items():
        for selector in [
            f"input[name*='{field_name}' i]",
            f"input[id*='{field_name}' i]",
            f"input[placeholder*='{field_name}' i]",
        ]:
            try:
                el = page.locator(selector).first
                if el.is_visible(timeout=1000):
                    el.fill(value)
                    log.info(f"  Filled {field_name}: {value}")
                    break
            except Exception:
                continue

    # Genre selection — try dropdown or input
    genre_selectors = [
        "select[name*='genre' i]",
        "input[name*='genre' i]",
        "[data-field='genre']",
    ]
    for selector in genre_selectors:
        try:
            el = page.locator(selector).first
            if el.is_visible(timeout=1000):
                tag = el.evaluate("el => el.tagName.toLowerCase()")
                if tag == "select":
                    # Try to select Afro House or Electronic
                    for genre in [concept.genre, "Electronic", "Dance"]:
                        try:
                            el.select_option(label=genre)
                            log.info(f"  Selected genre: {genre}")
                            break
                        except Exception:
                            continue
                else:
                    el.fill(concept.genre)
                    log.info(f"  Filled genre: {concept.genre}")
                break
        except Exception:
            continue


def _upload_file(page, file_path: Path, file_type: str = "audio"):
    """Upload a file using the file input on TuneCore."""
    # Find file input elements
    input_selectors = [
        f"input[type='file'][accept*='{file_type}']",
        "input[type='file']",
    ]
    if file_type == "image":
        input_selectors = [
            "input[type='file'][accept*='image']",
            "input[type='file'][accept*='jpg']",
            "input[type='file'][accept*='jpeg']",
            "input[type='file'][accept*='png']",
        ] + input_selectors
    elif file_type == "audio":
        input_selectors = [
            "input[type='file'][accept*='audio']",
            "input[type='file'][accept*='wav']",
        ] + input_selectors

    for selector in input_selectors:
        try:
            inputs = page.locator(selector)
            count = inputs.count()
            for i in range(count):
                el = inputs.nth(i)
                try:
                    el.set_input_files(str(file_path))
                    log.info(f"  File selected via: {selector} (index {i})")
                    return
                except Exception:
                    continue
        except Exception:
            continue

    # Fallback: try drag-and-drop zone or click-to-upload
    drop_zones = [
        "[class*='upload']",
        "[class*='drop']",
        "[class*='dropzone']",
        "text=Upload",
        "text=Choose File",
        "text=Browse",
    ]
    for selector in drop_zones:
        try:
            el = page.locator(selector).first
            if el.is_visible(timeout=1000):
                # Click to trigger file dialog, then use file chooser
                with page.expect_file_chooser(timeout=5000) as fc_info:
                    el.click()
                file_chooser = fc_info.value
                file_chooser.set_files(str(file_path))
                log.info(f"  File uploaded via file chooser: {selector}")
                return
        except Exception:
            continue

    log.warning(f"Could not find file input for {file_type} — manual upload may be needed")


def _wait_for_upload(page, timeout: int = 300):
    """Wait for file upload to complete (progress bar disappears or success indicator)."""
    start = time.time()
    while time.time() - start < timeout:
        # Check for common upload completion indicators
        try:
            # Progress bar gone
            progress = page.locator("[class*='progress']").first
            if not progress.is_visible(timeout=1000):
                log.info("  Upload progress indicator gone — assuming complete")
                return
        except Exception:
            pass

        # Check for success text
        for text in ["Upload complete", "Uploaded", "Success", "100%"]:
            try:
                if page.locator(f"text={text}").first.is_visible(timeout=500):
                    log.info(f"  Upload complete indicator found: {text}")
                    return
            except Exception:
                continue

        page.wait_for_timeout(5000)
        elapsed = int(time.time() - start)
        log.info(f"  Waiting for upload... ({elapsed}s)")

    log.warning(f"Upload wait timed out after {timeout}s — continuing anyway")


def _click_through_steps(page):
    """Click Continue/Next/Submit buttons to progress through TuneCore's multi-step form."""
    for step in range(10):  # Max 10 steps
        page.wait_for_timeout(2000)

        # Look for next/continue/submit buttons
        btn = _find_clickable(page, [
            "button:has-text('Continue')",
            "button:has-text('Next')",
            "button:has-text('Submit')",
            "button:has-text('Save')",
            "button:has-text('Distribute')",
            "button:has-text('Release')",
            "a:has-text('Continue')",
            "a:has-text('Next')",
        ])

        if btn:
            btn_text = btn.inner_text()
            log.info(f"  Step {step + 1}: Clicking '{btn_text}'")
            btn.click()
            page.wait_for_timeout(3000)

            # Check if we've reached a confirmation/success page
            for indicator in ["Congratulations", "Submitted", "In Review", "Distribution"]:
                try:
                    if page.locator(f"text={indicator}").first.is_visible(timeout=1000):
                        log.info(f"  Reached submission confirmation: {indicator}")
                        return
                except Exception:
                    continue
        else:
            log.info(f"  No more navigation buttons found at step {step + 1}")
            break
