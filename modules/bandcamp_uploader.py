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
    BANDCAMP_STATE_FILE, BANDCAMP_TRACK_PRICE, BANDCAMP_ARTIST_SUBDOMAIN, HEADLESS,
)
from utils.logger import log

BANDCAMP_HOME = "https://bandcamp.com"
BANDCAMP_DASHBOARD_URL = f"https://{BANDCAMP_ARTIST_SUBDOMAIN}.bandcamp.com/dashboard"
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

    if not BANDCAMP_STATE_FILE.exists() or BANDCAMP_STATE_FILE.stat().st_size < 10:
        log.error(
            f"Bandcamp session not found: {BANDCAMP_STATE_FILE}\n"
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
        # Same setup as TuneCore: bundled Chromium + storage_state + stealth
        # init script. Real Chrome is NOT required.
        browser = p.chromium.launch(
            headless=HEADLESS,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            storage_state=str(BANDCAMP_STATE_FILE),
            viewport={"width": 1920, "height": 1080},
            accept_downloads=False,
        )
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            window.chrome = { runtime: {} };
        """)
        page = context.new_page()

        try:
            # Go straight to the artist dashboard (e.g. groovegenix.bandcamp.com/dashboard)
            log.info(f"Navigating to {BANDCAMP_DASHBOARD_URL}...")
            page.goto(BANDCAMP_DASHBOARD_URL, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(3_000)
            page.screenshot(path=str(debug_dir / "debug_bandcamp_01_dashboard.png"))

            if _is_logged_out(page):
                log.error("Bandcamp session expired. Run: python main.py bandcamp-login")
                page.screenshot(path=str(debug_dir / "debug_bandcamp_login_fail.png"))
                return None

            _dismiss_banners(page)

            # Click the "+ Add" link in the header to open the album/track form
            log.info("Clicking '+ Add' in the dashboard header...")
            clicked = _click_add_button(page)
            if not clicked:
                page.screenshot(path=str(debug_dir / "debug_bandcamp_no_add_link.png"))
                raise RuntimeError(
                    "Could not find the '+ Add' button on the Bandcamp dashboard"
                )
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(4_000)
            page.screenshot(path=str(debug_dir / "debug_bandcamp_02_add_clicked.png"))

            # "+ Add" often shows a chooser (Album vs Track). Pick "Track" for a
            # single-track release, or fall through if it landed on the form.
            _pick_track_option(page)
            page.wait_for_timeout(2_000)
            page.screenshot(path=str(debug_dir / "debug_bandcamp_03_album_form.png"))

            _dismiss_banners(page)

            # ── Track name ──
            _set_track_name(page, concept.track_name)

            # ── Price (already defaults to 1.50 on the form, but overwrite anyway) ──
            _set_price(page, price)

            # ── Audio file ──
            _upload_audio(page, audio_path, debug_dir)

            # ── Track art ──
            if cover_path and cover_path.exists():
                _upload_artwork(page, cover_path, debug_dir)
            else:
                log.warning("No cover art provided — Bandcamp will use a default placeholder")

            # ── Description & tags ──
            _set_description(page, concept)
            _set_tags(page, concept)

            page.wait_for_timeout(1_500)
            page.screenshot(path=str(debug_dir / "debug_bandcamp_03_filled.png"))

            # Wait for the audio upload to finish processing before publishing
            _wait_for_audio_ready(page)

            # ── Publish ──
            album_url = _publish(page, concept.track_name, debug_dir)

            # Save refreshed session
            context.storage_state(path=str(BANDCAMP_STATE_FILE))
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
            browser.close()


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


def _click_add_button(page) -> bool:
    """Click the '+ Add' nav link on the artist dashboard.

    The dashboard header on the new Bandcamp UI uses a custom div/span as
    the '+ Add' trigger (not <a> or <button>), so role-based lookups miss it.
    Strategy: scan ANY visible clickable element near the top of the page
    whose trimmed text equals 'Add' / '+ Add'.
    """
    # Prefer role-based lookup so Playwright dispatches real events
    for pattern in [r"^\s*\+\s*Add\s*$", r"^\s*Add\s*$"]:
        for role in ("link", "button", "menuitem"):
            try:
                loc = page.get_by_role(role, name=re.compile(pattern, re.I))
                if loc.count() > 0:
                    loc.first.click(timeout=5_000)
                    log.info(f"Clicked '+ Add' via role={role}")
                    return True
            except Exception:
                continue

    # Fallback 1: get_by_text — Playwright filters to visible by default.
    for text in ("+ Add", "Add"):
        try:
            loc = page.get_by_text(text, exact=True).first
            if loc.is_visible(timeout=1500):
                loc.click(timeout=5_000)
                log.info(f"Clicked '+ Add' via get_by_text('{text}')")
                return True
        except Exception:
            continue

    # Fallback 2: JS scan across ANY tag whose trimmed text is "+ Add" / "Add"
    # and that's near the top of the viewport (= header).
    clicked = page.evaluate("""() => {
        const want = ['+ Add', 'Add', '+ add', '+add'];
        const els = [...document.querySelectorAll('*')];
        for (const el of els) {
            const rect = el.getBoundingClientRect();
            if (rect.width <= 0 || rect.height <= 0) continue;
            if (rect.top > 200) continue;  // header area only
            // Only consider elements whose OWN text (not nested) matches.
            const ownText = Array.from(el.childNodes)
                .filter(n => n.nodeType === 3)
                .map(n => n.textContent.trim()).join(' ').trim();
            if (want.includes(ownText)) {
                el.scrollIntoView({block: 'center'});
                el.click();
                return el.tagName + (el.className ? '.' + el.className.toString().split(' ')[0] : '');
            }
        }
        // Last resort: parent-text equality (catches the <div>+icon+text wrapper)
        for (const el of els) {
            const rect = el.getBoundingClientRect();
            if (rect.width <= 0 || rect.height <= 0) continue;
            if (rect.top > 200) continue;
            const txt = (el.textContent || '').trim();
            if (want.includes(txt) && el.children.length <= 3) {
                el.scrollIntoView({block: 'center'});
                el.click();
                return el.tagName + ' (fallback)';
            }
        }
        return null;
    }""")
    if clicked:
        log.info(f"Clicked '+ Add' via JS scan: {clicked}")
        return True
    return False


def _pick_track_option(page) -> None:
    """After '+ Add', Bandcamp opens a dropdown with
    Album / Track / Merch / Subscription / Listening Party / Live Stream
    — pick exactly 'Track'.
    """
    page.wait_for_timeout(800)  # let the dropdown render

    # Strategy 1: pick the dropdown item whose text is EXACTLY "Track"
    clicked = page.evaluate("""() => {
        const all = [...document.querySelectorAll('a, button, li, [role="menuitem"], [role="option"]')];
        const track = all.find(e => {
            if (e.offsetParent === null) return false;
            const t = (e.textContent || '').trim();
            return t === 'Track';
        });
        if (track) { track.click(); return track.tagName; }
        return null;
    }""")
    if clicked:
        log.info(f"Selected 'Track' via <{clicked}>")
        return

    # Strategy 2: role-based lookups
    for role in ("menuitem", "link", "button", "option"):
        try:
            loc = page.get_by_role(role, name=re.compile(r"^\s*Track\s*$"))
            if loc.count() > 0 and loc.first.is_visible():
                loc.first.click(timeout=3_000)
                log.info(f"Selected 'Track' via role={role}")
                return
        except Exception:
            continue

    log.info("Track option not found — assuming form is already open")


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


def _set_track_name(page, title: str) -> None:
    log.info(f"Setting track name: {title}")
    for selector in [
        'input[placeholder="track name"]',
        'input[placeholder*="track name" i]',
        'input[placeholder="album title"]',
        'input[placeholder*="album title" i]',
        'input[name="title"]',
        'input[name="album_title"]',
        'input[id*="title" i]',
        'input[aria-label*="track name" i]',
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
    log.warning("Track name field not found — continuing anyway")


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
    # Bandcamp limit is 10 tags. We keep 8 to leave room for Bandcamp's own
    # auto-suggested ones (House / Electronic / etc.). Dedupe case-insensitive
    # and drop overly generic words so we don't waste slots.
    raw = []
    if concept.genre:
        raw.append(concept.genre)
    raw.extend(t.lstrip("#") for t in (concept.hashtags or []) if t)

    blacklist = {"music", "song", "songs", "track", "tracks", "mix"}
    seen = set()
    tags: list[str] = []
    for t in raw:
        clean = t.strip()
        key = clean.lower().replace(" ", "")
        if not clean or key in seen or key in blacklist:
            continue
        seen.add(key)
        tags.append(clean)
        if len(tags) >= 8:
            break

    if not tags:
        return
    tag_string = ", ".join(tags)
    log.info(f"Tags ({len(tags)}): {tag_string}")
    for selector in [
        'input[placeholder*="comma-separated" i]',
        'input[placeholder*="list of tags" i]',
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
                # Clear field first in case Bandcamp pre-populated it
                page.keyboard.press("Control+A")
                page.keyboard.press("Delete")
                page.keyboard.type(tag_string, delay=10)
                log.info(f"Tags set: {tag_string[:80]}")
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
    log.info("Looking for Publish / Save Draft button...")
    # Prefer a real Publish/Release button; fall back to "Save Draft"
    btn_handle = page.evaluate_handle("""() => {
        const btns = [...document.querySelectorAll('button, input[type="submit"], a')]
            .filter(b => !b.disabled && b.offsetParent !== null);
        const textOf = b => (b.textContent || b.value || '').trim().toLowerCase();
        // Priority 1: real publish actions
        const publish = btns.find(b => {
            const t = textOf(b);
            return t === 'publish' || t === 'publish album' || t === 'publish track'
                || t === 'save & publish' || t === 'release';
        });
        if (publish) return publish;
        // Priority 2: save-draft (first step on the Track form)
        const saveDraft = btns.find(b => {
            const t = textOf(b);
            return t === 'save draft' || t === 'save' || t === 'save & continue' || t === 'done';
        });
        return saveDraft || null;
    }""")
    btn = btn_handle.as_element()
    if not btn:
        page.screenshot(path=str(debug_dir / "debug_bandcamp_no_publish.png"))
        raise RuntimeError("Publish / Save Draft button not found on Bandcamp form")

    label = (btn.text_content() or "").strip()
    log.info(f"Clicking: '{label}'")
    pre_url = page.url
    btn.click(timeout=10_000)
    page.wait_for_timeout(4_000)
    page.screenshot(path=str(debug_dir / "debug_bandcamp_save_clicked.png"))

    # If we clicked Save Draft, look for a Publish button on the result page.
    if "save" in label.lower() and "publish" not in label.lower():
        publish_now = page.evaluate_handle("""() => {
            const btns = [...document.querySelectorAll('button, input[type="submit"], a')]
                .filter(b => !b.disabled && b.offsetParent !== null);
            return btns.find(b => {
                const t = (b.textContent || b.value || '').trim().toLowerCase();
                return t === 'publish' || t === 'publish album' || t === 'publish track'
                    || t === 'release' || t === 'make it live';
            }) || null;
        }""")
        pub_el = publish_now.as_element()
        if pub_el:
            log.info("Clicking Publish after Save Draft...")
            pub_el.click(timeout=10_000)
            page.wait_for_timeout(4_000)
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
