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
from config import (
    DISTROKID_STATE_FILE, DISTROKID_ARTIST, DISTROKID_CHROME_PROFILE,
    HEADLESS, OUTPUT_DIR,
)
from utils.logger import log


DISTROKID_BASE = "https://distrokid.com"
UPLOAD_URL = f"{DISTROKID_BASE}/new/"

# A persistent Chrome profile dir. Using launch_persistent_context (instead of
# a throwaway context) makes the browser look like a real, returning user:
# cookies, localStorage and history survive between runs, and once you log in
# here the session stays put — so the pipeline never has to submit the login
# form (which is exactly where DistroKid's anti-bot freezes automation).
#
# Where automation actually launches Chrome from. We never point Chrome at the
# real "User Data" folder directly: modern Chrome refuses to start with a
# remote-debugging pipe against the live profile (exits with code 21). Instead,
# when DISTROKID_CHROME_PROFILE is set we COPY the logged-in profile into this
# working dir (cookies + login only, no caches) and launch from the copy.
PROFILE_DIR = DISTROKID_STATE_FILE.parent / "distrokid_profile"

# Cache-like subfolders that are huge and irrelevant to staying logged in —
# skipped when copying the real profile so the copy stays small and fast.
_SKIP_PROFILE_DIRS = {
    "Cache", "Code Cache", "GPUCache", "GraphiteDawnCache", "DawnCache",
    "DawnGraphiteCache", "DawnWebGPUCache", "Service Worker", "ShaderCache",
    "GrShaderCache", "component_crx_cache", "extensions_crx_cache",
    "Crashpad", "BrowserMetrics", "optimization_guide_model_store",
    "segmentation_platform", "AutofillStates", "PnaclTranslationCache",
}


def _copy_real_profile():
    """Copy the logged-in real Chrome profile into the working PROFILE_DIR.

    Copies 'Local State' (holds the cookie-encryption key) and the 'Default'
    profile, skipping cache folders. Locked files (Chrome still running) are
    skipped with a warning rather than aborting. Returns True on success.
    """
    import shutil

    src = Path(DISTROKID_CHROME_PROFILE)
    if not src.exists():
        log.error(f"DISTROKID_CHROME_PROFILE not found: {src}")
        return False

    dst = PROFILE_DIR
    dst.mkdir(parents=True, exist_ok=True)

    # Local State — needed to decrypt cookies on Windows.
    try:
        if (src / "Local State").exists():
            shutil.copy2(src / "Local State", dst / "Local State")
    except Exception as e:
        log.warning(f"Could not copy Local State: {e}")

    # The Default profile (cookies, login data, prefs), minus cache dirs.
    src_default = src / "Default"
    dst_default = dst / "Default"
    if not src_default.exists():
        log.error(f"No 'Default' profile in {src}")
        return False
    dst_default.mkdir(parents=True, exist_ok=True)

    copied, skipped = 0, 0
    for item in src_default.iterdir():
        if item.name in _SKIP_PROFILE_DIRS:
            continue
        target = dst_default / item.name
        try:
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns(*_SKIP_PROFILE_DIRS))
            else:
                shutil.copy2(item, target)
            copied += 1
        except Exception:
            skipped += 1  # locked file (Chrome open) — non-fatal
    log.info(f"Copied real Chrome profile ({copied} items, {skipped} locked/skipped)")
    return True

# Stealth patches injected before any page script runs. They strip the most
# common automation fingerprints DistroKid checks (navigator.webdriver, the
# missing window.chrome object, empty plugins/languages).
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = window.chrome || { runtime: {} };
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
"""

# Launch args that remove the "controlled by automation" banner and the
# webdriver flag at the browser level.
_STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-default-browser-check",
    "--no-first-run",
    "--disable-infobars",
]


def _launch_persistent(p, headless, refresh_profile=False):
    """Open the working DistroKid Chrome profile with stealth patches.

    When DISTROKID_CHROME_PROFILE is set and the working copy is missing (or
    refresh_profile=True), the real logged-in profile is copied in first.
    """
    if DISTROKID_CHROME_PROFILE:
        if refresh_profile or not (PROFILE_DIR / "Default").exists():
            _copy_real_profile()
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=headless,
        channel="chrome",
        args=_STEALTH_ARGS,
        viewport={"width": 1920, "height": 1080},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
    )
    context.add_init_script(_STEALTH_JS)
    return context


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
    """Open the persistent Chrome profile for manual DistroKid login.

    The session lives inside the profile dir itself, so there's nothing to
    export — logging in once here keeps you logged in for every later upload.
    """
    log.info("Opening Chrome (persistent profile) for DistroKid login...")
    log.info("Log in with your account, then come back and press ENTER.")
    with sync_playwright() as p:
        context = _launch_persistent(p, headless=False)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://distrokid.com/signin", wait_until="domcontentloaded", timeout=60_000)
        log.info("=" * 60)
        log.info("Browser is open. Please:")
        log.info("  1. Log into your DistroKid account (email/password or Google)")
        log.info("  2. Wait until you see your dashboard / My Music")
        log.info("  3. Come back here and press ENTER")
        log.info("=" * 60)
        input("\n>>> Press ENTER here after you've logged in... ")
        # Persist a storage_state snapshot too, for tooling that expects it.
        try:
            context.storage_state(path=str(DISTROKID_STATE_FILE))
        except Exception:
            pass
        log.info(f"DistroKid profile saved to: {PROFILE_DIR}")
        context.close()


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

    if not DISTROKID_CHROME_PROFILE and not (PROFILE_DIR / "Default").exists():
        log.error(
            "DistroKid profile not set up.\n"
            "Either run 'python main.py distrokid-login' or set "
            "DISTROKID_CHROME_PROFILE in .env to your real Chrome 'User Data' folder."
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
        # Refresh the profile copy each upload so the latest login cookies win.
        context = _launch_persistent(p, headless=HEADLESS, refresh_profile=True)
        page = context.pages[0] if context.pages else context.new_page()
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
            context.close()


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
