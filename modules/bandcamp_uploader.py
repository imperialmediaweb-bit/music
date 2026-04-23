"""Bandcamp uploader — publish a single track with cover art and price.

Bandcamp's "tools → Add a new album" page is used for single-track releases:
we create a 1-track album (name = track name), set the price, upload WAV and
cover art, then publish. The storage state is reused from a prior
`bandcamp-login` run.
"""

import re
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from modules.concept_generator import MusicConcept
from config import (
    BANDCAMP_STATE_FILE, BANDCAMP_USER_DATA_DIR, BANDCAMP_TRACK_PRICE, HEADLESS,
)
from utils.logger import log

BANDCAMP_HOME = "https://bandcamp.com"
# Bandcamp's artist tools live under the artist subdomain
# (e.g. https://groovegenix.bandcamp.com/tools). The generic /tools URL on
# bandcamp.com redirects and often lands on login. We detect the subdomain
# at runtime from cookies + navigation.
BANDCAMP_TOOLS_URL = "https://bandcamp.com/tools"
MAX_RETRIES = 2


def upload_to_bandcamp(
    audio_path: Path,
    concept: MusicConcept,
    cover_path: Path | None = None,
    price: str | None = None,
) -> str | None:
    """Upload a single track to Bandcamp as a 1-track album.

    Args:
        audio_path: Path to WAV (preferred) or MP3 file.
        concept: MusicConcept for title, genre, description, tags.
        cover_path: Cover art image (1:1, ≥1400x1400 recommended).
        price: Track price in USD (e.g. "1.50"). Falls back to BANDCAMP_TRACK_PRICE.

    Returns:
        Bandcamp album/track URL if successful, None otherwise.
    """
    log.info(f"Uploading to Bandcamp: {concept.track_name}")

    if not BANDCAMP_USER_DATA_DIR.exists() or not any(BANDCAMP_USER_DATA_DIR.iterdir()):
        log.error(
            f"Bandcamp profile not found: {BANDCAMP_USER_DATA_DIR}\n"
            "Run: python main.py bandcamp-login"
        )
        return None

    resolved_price = price if price is not None else BANDCAMP_TRACK_PRICE

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return _do_upload(audio_path, concept, cover_path, resolved_price)
        except Exception as e:
            if attempt < MAX_RETRIES:
                wait = 2 ** attempt
                log.warning(f"Bandcamp attempt {attempt}/{MAX_RETRIES} failed: {e}")
                log.info(f"Retrying in {wait}s...")
                time.sleep(wait)
            else:
                log.error(f"Bandcamp upload failed after {MAX_RETRIES} attempts: {e}")
                raise


def _do_upload(
    audio_path: Path,
    concept: MusicConcept,
    cover_path: Path | None,
    price: str,
) -> str | None:
    debug_dir = Path("output")

    with sync_playwright() as p:
        # Reuse the persistent Chrome profile from `bandcamp-login` so
        # Bandcamp's reCAPTCHA scores the browser as trusted.
        persistent_kwargs = dict(
            user_data_dir=str(BANDCAMP_USER_DATA_DIR),
            headless=HEADLESS,
            viewport={"width": 1920, "height": 1080},
            accept_downloads=False,
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )
        try:
            context = p.chromium.launch_persistent_context(
                channel="chrome", **persistent_kwargs
            )
        except Exception:
            log.info("Chrome channel not available — falling back to bundled Chromium")
            context = p.chromium.launch_persistent_context(**persistent_kwargs)
        # Hide navigator.webdriver so Bandcamp's reCAPTCHA doesn't trip.
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        page = context.pages[0] if context.pages else context.new_page()
        browser = None  # persistent context has no separate browser handle

        try:
            # Start at the Bandcamp home feed — after login, Bandcamp shows
            # the user's dashboard here with a link to the artist's tools.
            log.info(f"Navigating to {BANDCAMP_HOME}...")
            page.goto(BANDCAMP_HOME + "/", wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(3_000)
            page.screenshot(path=str(debug_dir / "debug_bandcamp_01_home.png"))

            if _is_logged_out(page):
                log.error("Bandcamp session expired. Run: python main.py bandcamp-login")
                page.screenshot(path=str(debug_dir / "debug_bandcamp_login_fail.png"))
                return None

            _dismiss_banners(page)

            # Resolve the artist subdomain (e.g. https://groovegenix.bandcamp.com)
            # from the dashboard, then navigate to <subdomain>/tools.
            artist_tools_url = _resolve_artist_tools_url(page)
            if artist_tools_url:
                log.info(f"Artist tools URL: {artist_tools_url}")
                page.goto(artist_tools_url, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(3_000)
                page.screenshot(path=str(debug_dir / "debug_bandcamp_02_tools.png"))
                if _is_logged_out(page):
                    log.error("Bandcamp redirected to login despite saved session.")
                    page.screenshot(path=str(debug_dir / "debug_bandcamp_login_redirect.png"))
                    return None

            # Open the "add new album" form. Bandcamp exposes this from the
            # artist tools page; the link varies a bit by account type, so we
            # try several entry points.
            add_url = _find_add_album_url(page)
            if add_url:
                log.info(f"Opening album form: {add_url}")
                page.goto(add_url, wait_until="domcontentloaded", timeout=60_000)
            else:
                # Fallback: click a button/link matching "new album"
                log.info("Falling back to clicking 'add new album' link...")
                clicked = _click_new_album_link(page)
                if not clicked:
                    page.screenshot(path=str(debug_dir / "debug_bandcamp_no_add_link.png"))
                    raise RuntimeError(
                        "Could not find the 'add new album' entry point on Bandcamp"
                    )
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(4_000)
            page.screenshot(path=str(debug_dir / "debug_bandcamp_03_album_form.png"))

            _dismiss_banners(page)

            # ── Title ──
            _set_album_title(page, concept.track_name)

            # ── Artwork ──
            if cover_path and cover_path.exists():
                _upload_artwork(page, cover_path, debug_dir)
            else:
                log.warning("No cover art provided — Bandcamp will use a default placeholder")

            # ── Audio file (creates track 1 automatically) ──
            _upload_audio(page, audio_path, debug_dir)

            # ── Track title (often auto-filled from filename) ──
            _set_first_track_title(page, concept.track_name)

            # ── Price ──
            _set_price(page, price)

            # ── Description & tags ──
            _set_description(page, concept)
            _set_tags(page, concept)

            page.wait_for_timeout(1_500)
            page.screenshot(path=str(debug_dir / "debug_bandcamp_03_filled.png"))

            # Wait for the audio upload to finish processing before publishing
            _wait_for_audio_ready(page)

            # ── Publish ──
            album_url = _publish(page, concept.track_name, debug_dir)

            # Persist storage_state snapshot (profile dir handles the rest)
            try:
                context.storage_state(path=str(BANDCAMP_STATE_FILE))
            except Exception:
                pass
            page.screenshot(path=str(debug_dir / "debug_bandcamp_04_done.png"))

            if album_url:
                log.info(f"Bandcamp URL: {album_url}")
            else:
                log.info("Bandcamp upload completed (URL not captured)")
            return album_url or "uploaded (URL not available)"

        except Exception as e:
            log.error(f"Bandcamp upload failed: {e}")
            try:
                page.screenshot(path=str(debug_dir / "debug_bandcamp_error.png"))
            except Exception:
                pass
            raise
        finally:
            context.close()


# ── Helpers ───────────────────────────────────────────────────────────────


def _is_logged_out(page) -> bool:
    return bool(page.evaluate("""() => {
        const url = location.href.toLowerCase();
        if (url.includes('/login') || url.includes('/signup')) return true;
        // Logged-in Bandcamp always has the user menu / logout link somewhere.
        if (document.querySelector('a[href*="/logout"]')
            || document.querySelector('a[href*="/profile/"]')) {
            return false;
        }
        const bodyText = document.body?.innerText || '';
        if (/log in to bandcamp|sign up for bandcamp/i.test(bodyText)) {
            return true;
        }
        return false;
    }"""))


def _resolve_artist_tools_url(page) -> str | None:
    """Find the artist's `<subdomain>.bandcamp.com/tools` URL from the dashboard.

    Bandcamp's logged-in home has a user-menu link to the artist profile
    (e.g. https://groovegenix.bandcamp.com). We pick the first artist-like
    subdomain we find and append /tools.
    """
    url = page.evaluate("""() => {
        const links = [...document.querySelectorAll('a[href]')];
        // 1) An explicit "tools" link.
        const toolsLink = links.find(a => {
            const href = (a.getAttribute('href') || '').toLowerCase();
            return /^https?:\\/\\/[^/]+\\.bandcamp\\.com\\/tools(\\/|$)/.test(href);
        });
        if (toolsLink) return toolsLink.getAttribute('href');
        // 2) Any link to an artist subdomain (not www, not bandcamp.com).
        const artistLink = links.find(a => {
            const href = (a.getAttribute('href') || '');
            const m = href.match(/^https?:\\/\\/([^/]+)\\.bandcamp\\.com(\\/|$)/i);
            return m && m[1] !== 'www' && m[1] !== 'blog' && m[1] !== 'daily';
        });
        if (artistLink) {
            const href = artistLink.getAttribute('href');
            const m = href.match(/^(https?:\\/\\/[^/]+\\.bandcamp\\.com)/i);
            if (m) return m[1] + '/tools';
        }
        return null;
    }""")
    return url


def _dismiss_banners(page) -> None:
    """Dismiss Bandcamp cookie / marketing banners if present."""
    try:
        page.evaluate("""() => {
            const buttons = [...document.querySelectorAll('button, a')];
            for (const b of buttons) {
                const t = (b.textContent || '').trim().toLowerCase();
                if (t === 'accept' || t === 'accept all' || t === 'ok'
                    || t === 'got it' || t === 'close' || t === 'dismiss'
                    || t === 'i understand') {
                    b.click();
                }
            }
        }""")
    except Exception:
        pass


def _find_add_album_url(page) -> str | None:
    """Locate the artist's 'add a new album' URL from the tools dashboard."""
    href = page.evaluate("""() => {
        const links = [...document.querySelectorAll('a[href]')];
        const candidate = links.find(a => {
            const href = (a.getAttribute('href') || '').toLowerCase();
            const text = (a.textContent || '').trim().toLowerCase();
            return (text.includes('add') && (text.includes('album') || text.includes('track')))
                || href.includes('/album/new') || href.includes('/tools/new_album')
                || href.includes('add_album') || href.includes('album_create');
        });
        if (!candidate) return null;
        const href = candidate.getAttribute('href');
        return href.startsWith('http') ? href : ('https://bandcamp.com' + href);
    }""")
    return href


def _click_new_album_link(page) -> bool:
    for text in ["add a new album", "add new album", "new album",
                 "add a new track", "add new track", "new track"]:
        try:
            loc = page.get_by_role("link", name=re.compile(text, re.I))
            if loc.count() > 0:
                loc.first.click()
                return True
        except Exception:
            continue
        try:
            loc = page.get_by_role("button", name=re.compile(text, re.I))
            if loc.count() > 0:
                loc.first.click()
                return True
        except Exception:
            continue
    return False


def _set_album_title(page, title: str) -> None:
    log.info(f"Setting album title: {title}")
    for selector in [
        'input[name="title"]',
        'input[name="album_title"]',
        'input[id*="album-title" i]',
        'input[placeholder*="album title" i]',
        'input[placeholder="Album title"]',
        'input[aria-label*="album title" i]',
    ]:
        el = page.query_selector(selector)
        if el and el.is_visible():
            try:
                el.click()
                page.keyboard.press("Control+a")
                page.keyboard.type(title, delay=15)
                return
            except Exception as e:
                log.warning(f"Could not set title via {selector}: {e}")
    log.warning("Album title field not found — continuing anyway")


def _upload_artwork(page, cover_path: Path, debug_dir: Path) -> None:
    log.info(f"Uploading cover art: {cover_path.name}")
    # Look for the image file input among all file inputs
    inputs = page.query_selector_all('input[type="file"]')
    for inp in inputs:
        accept = (inp.get_attribute("accept") or "").lower()
        name = (inp.get_attribute("name") or "").lower()
        ident = (inp.get_attribute("id") or "").lower()
        if ("image" in accept or "jpg" in accept or "png" in accept
                or "art" in name or "art" in ident or "cover" in name or "cover" in ident):
            try:
                inp.set_input_files(str(cover_path))
                page.wait_for_timeout(2_000)
                log.info("Cover art uploaded")
                page.screenshot(path=str(debug_dir / "debug_bandcamp_artwork.png"))
                return
            except Exception as e:
                log.warning(f"Artwork set_input_files failed: {e}")

    # Fallback: click an artwork placeholder then use the file chooser
    artwork_el = page.query_selector(
        'div[class*="art" i][role="button"], div[class*="cover" i], '
        'button:has-text("art"), button:has-text("cover")'
    )
    if artwork_el:
        try:
            with page.expect_file_chooser(timeout=5_000) as fc_info:
                artwork_el.click(force=True)
            fc_info.value.set_files(str(cover_path))
            page.wait_for_timeout(2_000)
            log.info("Cover art uploaded (via file chooser)")
            return
        except Exception as e:
            log.warning(f"Artwork file-chooser fallback failed: {e}")
    log.warning("Could not upload cover art — continuing with default placeholder")


def _upload_audio(page, audio_path: Path, debug_dir: Path) -> None:
    log.info(f"Uploading audio: {audio_path.name}")
    inputs = page.query_selector_all('input[type="file"]')
    for inp in inputs:
        accept = (inp.get_attribute("accept") or "").lower()
        name = (inp.get_attribute("name") or "").lower()
        ident = (inp.get_attribute("id") or "").lower()
        if ("audio" in accept or "mp3" in accept or "wav" in accept
                or "audio" in name or "track" in name or "audio" in ident or "track" in ident):
            try:
                inp.set_input_files(str(audio_path))
                page.wait_for_timeout(3_000)
                log.info("Audio file accepted")
                page.screenshot(path=str(debug_dir / "debug_bandcamp_audio.png"))
                return
            except Exception as e:
                log.warning(f"Audio set_input_files failed: {e}")

    # Fallback: any file input that's not the artwork one (artwork already used above)
    for inp in inputs:
        try:
            inp.set_input_files(str(audio_path))
            page.wait_for_timeout(3_000)
            log.info("Audio file accepted (generic file input)")
            return
        except Exception:
            continue

    # Last fallback: file chooser on a button that mentions upload/audio/track
    for selector in [
        'button:has-text("upload")',
        'button:has-text("add a track")',
        'button:has-text("add track")',
        'a:has-text("upload")',
    ]:
        btn = page.query_selector(selector)
        if btn and btn.is_visible():
            try:
                with page.expect_file_chooser(timeout=5_000) as fc_info:
                    btn.click(force=True)
                fc_info.value.set_files(str(audio_path))
                page.wait_for_timeout(3_000)
                log.info(f"Audio selected via file chooser ({selector})")
                return
            except Exception:
                continue

    raise RuntimeError("Could not find audio file input on Bandcamp album form")


def _set_first_track_title(page, title: str) -> None:
    """Bandcamp usually auto-names the first track from the filename.
    Overwrite it with the real title for consistency."""
    selectors = [
        'input[name="track_title"]',
        'input[name="tracks[0][title]"]',
        'input[placeholder*="track title" i]',
        'input[id*="track-title" i]',
    ]
    for selector in selectors:
        el = page.query_selector(selector)
        if el and el.is_visible():
            try:
                el.click()
                page.keyboard.press("Control+a")
                page.keyboard.type(title, delay=15)
                log.info(f"Track title set: {title}")
                return
            except Exception as e:
                log.warning(f"Could not set track title via {selector}: {e}")


def _set_price(page, price: str) -> None:
    """Set the minimum price for the album/track (e.g. '1.50')."""
    log.info(f"Setting price: ${price}")
    clean_price = str(price).lstrip("$").strip()

    # Bandcamp typically offers "name your price" / "free" / "paid" radios.
    # Try to select a "set price" / "paid" option if the form defaults to free.
    try:
        page.evaluate("""() => {
            const labels = [...document.querySelectorAll('label, button, input')];
            for (const el of labels) {
                const t = (el.textContent || el.value || '').trim().toLowerCase();
                if (t === 'paid' || t === 'set price' || t.includes('minimum price')
                    || t === 'pay what you want' || t === 'name your price') {
                    try { el.click(); } catch(e) {}
                }
            }
        }""")
    except Exception:
        pass

    page.wait_for_timeout(500)

    for selector in [
        'input[name="price"]',
        'input[name="minimum_price"]',
        'input[name*="price" i]',
        'input[placeholder*="price" i]',
        'input[aria-label*="price" i]',
        'input[id*="price" i]',
    ]:
        els = page.query_selector_all(selector)
        for el in els:
            try:
                if not el.is_visible():
                    continue
                el.click()
                page.keyboard.press("Control+a")
                page.keyboard.type(clean_price, delay=20)
                page.keyboard.press("Tab")
                log.info(f"Price set via {selector}: {clean_price}")
                return
            except Exception as e:
                log.warning(f"Price input {selector} failed: {e}")

    log.warning(f"Price field not found — track may default to free/pay-what-you-want")


def _set_description(page, concept: MusicConcept) -> None:
    desc = (concept.description or "").strip()
    if not desc:
        return
    for selector in [
        'textarea[name="about"]',
        'textarea[name="description"]',
        'textarea[name*="about" i]',
        'textarea[name*="description" i]',
        'textarea[placeholder*="about" i]',
        'textarea[placeholder*="description" i]',
    ]:
        el = page.query_selector(selector)
        if el and el.is_visible():
            try:
                el.click()
                page.keyboard.press("Control+a")
                page.keyboard.type(desc, delay=5)
                log.info("Description set")
                return
            except Exception as e:
                log.warning(f"Description {selector} failed: {e}")


def _set_tags(page, concept: MusicConcept) -> None:
    tags = [t.lstrip("#") for t in (concept.hashtags or []) if t][:10]
    if concept.genre:
        tags = [concept.genre] + tags
    if not tags:
        return
    tag_string = ", ".join(tags)
    for selector in [
        'input[name="tags"]',
        'input[name*="tag" i]',
        'input[placeholder*="tag" i]',
        'input[aria-label*="tag" i]',
        'textarea[name*="tag" i]',
    ]:
        el = page.query_selector(selector)
        if el and el.is_visible():
            try:
                el.click()
                page.keyboard.type(tag_string, delay=10)
                log.info(f"Tags set: {tag_string[:60]}")
                return
            except Exception as e:
                log.warning(f"Tags {selector} failed: {e}")


def _wait_for_audio_ready(page) -> None:
    """Wait up to 5 min for Bandcamp to finish transcoding the uploaded audio."""
    log.info("Waiting for Bandcamp to finish processing audio...")
    for wait in range(60):  # 60 × 5s = 5 min
        state = page.evaluate("""() => {
            const text = document.body.innerText.toLowerCase();
            if (text.includes('uploading') || text.includes('processing')
                || text.includes('transcoding') || text.includes('please wait')) {
                return 'processing';
            }
            // Progress bars still showing?
            const bars = [...document.querySelectorAll('[class*="progress" i]')]
                .filter(e => e.offsetParent !== null);
            if (bars.length) return 'progress';
            return 'idle';
        }""")
        if state == "idle":
            log.info("Audio processing appears complete")
            return
        if wait % 6 == 0:
            log.info(f"Still processing... ({wait * 5}s)")
        page.wait_for_timeout(5_000)
    log.warning("Audio processing not confirmed after 5 min, continuing anyway")


def _publish(page, track_name: str, debug_dir: Path) -> str | None:
    log.info("Looking for Publish / Save button...")
    btn_handle = page.evaluate_handle("""() => {
        const btns = [...document.querySelectorAll('button, input[type="submit"], a')];
        const publish = btns.find(b => {
            if (b.disabled) return false;
            if (b.offsetParent === null) return false;
            const t = (b.textContent || b.value || '').trim().toLowerCase();
            return t === 'publish' || t === 'publish album' || t === 'save & publish'
                || t === 'save' || t === 'done' || t === 'release';
        });
        return publish || null;
    }""")
    btn = btn_handle.as_element()
    if not btn:
        page.screenshot(path=str(debug_dir / "debug_bandcamp_no_publish.png"))
        raise RuntimeError("Publish button not found on Bandcamp album form")

    label = (btn.text_content() or "").strip()
    log.info(f"Clicking: '{label}'")
    pre_url = page.url
    btn.click(timeout=10_000)
    page.wait_for_timeout(3_000)
    page.screenshot(path=str(debug_dir / "debug_bandcamp_publish_clicked.png"))

    # Confirm any follow-up dialog (e.g. "Yes, publish")
    try:
        confirm = page.evaluate_handle("""() => {
            const btns = [...document.querySelectorAll('button, a[role="button"]')];
            const conf = btns.find(b => {
                if (b.disabled) return false;
                if (b.offsetParent === null) return false;
                const t = (b.textContent || '').trim().toLowerCase();
                return t === 'yes, publish' || t === 'confirm' || t === 'publish now'
                    || t === 'yes' || t === 'ok';
            });
            return conf || null;
        }""")
        conf_el = confirm.as_element()
        if conf_el:
            conf_el.click()
            log.info("Confirmation dialog accepted")
            page.wait_for_timeout(3_000)
    except Exception:
        pass

    # Wait for redirect / album URL
    for wait in range(24):  # 24 × 5s = 2 min
        current = page.url
        if current != pre_url and "/album/" in current:
            log.info(f"Album page: {current}")
            return current
        # Link to the newly-created album somewhere on the page
        link = page.evaluate("""(name) => {
            const links = [...document.querySelectorAll('a[href*="/album/"]')];
            const match = links.find(l => {
                const t = (l.textContent || '').trim().toLowerCase();
                return t.includes(name.toLowerCase());
            }) || links[0];
            if (!match) return null;
            const href = match.getAttribute('href');
            return href.startsWith('http') ? href : ('https://bandcamp.com' + href);
        }""", track_name)
        if link:
            return link
        page.wait_for_timeout(5_000)
    return None
