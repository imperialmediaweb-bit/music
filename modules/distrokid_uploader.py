"""Upload tracks to DistroKid for distribution.

DistroKid accepts AI-generated music as long as it's disclosed, which makes
it the active distributor after TuneCore's GenAI rejection. This module
drives the DistroKid "Upload music" flow with Playwright using a saved
browser session (run `python main.py distrokid-login` once to create it).

Public API:
  - upload_to_distrokid(wav_path, cover_path, concept, artist) -> str | None
  - distrokid_login()  (interactive, called by the CLI command)

The upload form is long and DistroKid tweaks it often, so every field is
filled defensively (multiple selectors, best-effort) and the whole flow is
wrapped so a single missing field logs a warning instead of aborting.
"""

import os
import time
from pathlib import Path

# DistroKid's anti-bot code runs `debugger;` in a loop and freezes the page
# (greying it out) whenever a DevTools/Inspector connection is detected. The
# Playwright Inspector opens exactly such a connection, so make sure it is
# never launched for this module — otherwise the login/upload page hangs.
os.environ.pop("PWDEBUG", None)
os.environ["PLAYWRIGHT_SKIP_BROWSER_GC"] = os.environ.get("PLAYWRIGHT_SKIP_BROWSER_GC", "1")

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from modules.concept_generator import MusicConcept
from config import DISTROKID_STATE_FILE, DISTROKID_ARTIST, HEADLESS, OUTPUT_DIR
from utils.logger import log


DISTROKID_BASE = "https://distrokid.com"
UPLOAD_URL = f"{DISTROKID_BASE}/new/"


def _first_visible(page, selectors, timeout=4_000):
    """Return the first visible element matching any selector, else None."""
    for sel in selectors:
        try:
            el = page.wait_for_selector(sel, timeout=timeout)
            if el and el.is_visible():
                return el
        except PlaywrightTimeout:
            continue
        except Exception:
            continue
    return None


def _fill(page, selectors, value, label, timeout=4_000):
    """Fill the first matching input; log the outcome. Returns True on success."""
    el = _first_visible(page, selectors, timeout=timeout)
    if not el:
        log.warning(f"DistroKid: could not find field '{label}'")
        return False
    try:
        el.click()
        el.fill("")
        el.fill(str(value))
        log.info(f"DistroKid: filled '{label}'")
        return True
    except Exception as e:
        log.warning(f"DistroKid: failed to fill '{label}': {e}")
        return False


def _click(page, selectors, label, timeout=4_000):
    """Click the first matching element; log the outcome. Returns True on success."""
    el = _first_visible(page, selectors, timeout=timeout)
    if not el:
        log.warning(f"DistroKid: could not find control '{label}'")
        return False
    try:
        el.scroll_into_view_if_needed()
        el.click(force=True)
        log.info(f"DistroKid: clicked '{label}'")
        return True
    except Exception as e:
        log.warning(f"DistroKid: failed to click '{label}': {e}")
        return False


def distrokid_login():
    """Open a browser for manual DistroKid login and save the session."""
    log.info("Opening Chrome browser for DistroKid login...")
    log.info("Log in with your account, then come back and press ENTER.")
    DISTROKID_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()
        page.goto("https://distrokid.com/signin", wait_until="domcontentloaded", timeout=60_000)
        log.info("=" * 60)
        log.info("Browser is open. Please:")
        log.info("  1. Log into your DistroKid account (email/password or Google)")
        log.info("  2. Wait until you see your dashboard / My Music")
        log.info("  3. Come back here and press ENTER")
        log.info("=" * 60)
        input("\n>>> Press ENTER here after you've logged in... ")
        context.storage_state(path=str(DISTROKID_STATE_FILE))
        log.info(f"DistroKid session saved to: {DISTROKID_STATE_FILE}")
        browser.close()


def upload_to_distrokid(
    wav_path: Path,
    cover_path: Path,
    concept: MusicConcept,
    artist: str = DISTROKID_ARTIST,
) -> str | None:
    """Upload a single track to DistroKid.

    Args:
        wav_path: Path to the WAV/MP3 audio file.
        cover_path: Path to the square cover art (>=3000x3000 recommended).
        concept: MusicConcept with track metadata (title, genre, etc.).
        artist: Artist name shown on the release.

    Returns:
        A status string on success, or None on failure.
    """
    log.info(f"Uploading to DistroKid: {concept.track_name}")

    if not DISTROKID_STATE_FILE.exists():
        log.error(
            f"DistroKid session not found: {DISTROKID_STATE_FILE}\n"
            "Run: python main.py distrokid-login"
        )
        return None
    if not wav_path.exists():
        log.error(f"Audio file not found: {wav_path}")
        return None
    if not cover_path.exists():
        log.error(f"Cover art not found: {cover_path}")
        return None

    title = concept.track_name

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        context = browser.new_context(storage_state=str(DISTROKID_STATE_FILE))
        page = context.new_page()
        try:
            log.info("Opening DistroKid upload page...")
            page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=60_000)
            time.sleep(4)

            if "signin" in page.url.lower() or "login" in page.url.lower():
                log.error("DistroKid session expired — run 'python main.py distrokid-login'")
                page.screenshot(path=str(OUTPUT_DIR / "distrokid_session_expired.png"))
                return None

            # Number of songs: 1 (single)
            _fill(page, [
                'input[name="howManySongs"]',
                'input#howManySongs',
                'select[name="howManySongs"]',
            ], "1", "number of songs")

            # Artist / band name
            _fill(page, [
                'input[name="artistName"]',
                'input[id*="artist" i]',
                'input[placeholder*="artist" i]',
            ], artist, "artist name")

            # Record label (optional) — leave DistroKid default

            # Language / Primary genre — best effort via visible dropdowns
            _select_genre(page)

            # Track title
            _fill(page, [
                'input[name="title1"]',
                'input[id*="songtitle" i]',
                'input[placeholder*="song title" i]',
                'input[placeholder*="track title" i]',
            ], title, "track title")

            # Songwriter real name (DistroKid requires a real legal name field)
            _fill(page, [
                'input[name="songwriterRealName1"]',
                'input[id*="songwriter" i]',
                'input[placeholder*="songwriter" i]',
            ], artist, "songwriter name")

            # Instrumental? Afro House is typically instrumental — say yes when
            # the concept carries no lyrics.
            is_instrumental = not getattr(concept, "lyrics", "")
            if is_instrumental:
                _click(page, [
                    'input[name="instrumental1"][value="yes"]',
                    'label:has-text("Yes, this song is an instrumental")',
                    'input[type="radio"][value="instrumental"]',
                ], "instrumental = yes")

            # AI disclosure — check any AI-usage box honestly if present
            _click(page, [
                'input[id*="ai" i][type="checkbox"]',
                'label:has-text("AI") input[type="checkbox"]',
            ], "AI disclosure")

            # Upload audio file
            _upload_file(page, wav_path, [
                'input[type="file"][name*="audio" i]',
                'input[type="file"][accept*="audio" i]',
                'input[type="file"]',
            ], "audio file")

            # Upload cover art
            _upload_file(page, cover_path, [
                'input[type="file"][name*="cover" i]',
                'input[type="file"][accept*="image" i]',
            ], "cover art")

            # Give uploads time to process
            log.info("Waiting for uploads to process...")
            time.sleep(30)

            # Accept mandatory disclosure checkboxes at the bottom
            _accept_disclosures(page)

            # Continue / submit
            submitted = _click(page, [
                'button:has-text("Continue")',
                'a:has-text("Continue")',
                'button:has-text("Submit")',
                'button[type="submit"]',
            ], "Continue/Submit")

            if not submitted:
                log.warning("DistroKid: could not find final Continue button")
                page.screenshot(path=str(OUTPUT_DIR / "distrokid_no_continue.png"))
                return None

            time.sleep(5)
            log.info(f"DistroKid upload submitted for: {title}")
            return f"distrokid:submitted:{title}"

        except Exception as e:
            log.error(f"DistroKid upload failed: {e}")
            try:
                page.screenshot(path=str(OUTPUT_DIR / "distrokid_error.png"))
            except Exception:
                pass
            return None
        finally:
            browser.close()


def _select_genre(page):
    """Best-effort primary-genre selection (Dance / Electronic / House)."""
    for genre in ["Dance", "Electronic", "House"]:
        try:
            sel = page.query_selector('select[name*="genre" i], select[id*="genre" i]')
            if sel:
                sel.select_option(label=genre)
                log.info(f"DistroKid: primary genre = {genre}")
                return
        except Exception:
            continue
    log.warning("DistroKid: primary genre not set (will use default)")


def _upload_file(page, file_path, selectors, label):
    """Set an <input type=file> to the given path."""
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el:
                el.set_input_files(str(file_path))
                log.info(f"DistroKid: uploaded {label} ({file_path.name})")
                return True
        except Exception:
            continue
    log.warning(f"DistroKid: could not upload {label}")
    return False


def _accept_disclosures(page):
    """Tick every visible unchecked mandatory-disclosure checkbox at the bottom."""
    try:
        checkboxes = page.query_selector_all('input[type="checkbox"]')
        ticked = 0
        for cb in checkboxes:
            try:
                if cb.is_visible() and not cb.is_checked():
                    cb.check()
                    ticked += 1
            except Exception:
                continue
        if ticked:
            log.info(f"DistroKid: accepted {ticked} disclosure checkbox(es)")
    except Exception as e:
        log.warning(f"DistroKid: disclosure step skipped: {e}")
