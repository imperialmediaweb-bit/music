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


def _dump_page_state(page, step_label: str):
    """Log all visible interactive elements on the page for debugging.

    Dumps buttons, links, inputs, file inputs, and upload-related elements
    so we can see exactly what TuneCore is showing at each step.
    """
    log.info(f"  ── PAGE STATE at {step_label} ──")
    log.info(f"  URL: {page.url}")

    try:
        state = page.evaluate("""() => {
            const result = { buttons: [], links: [], inputs: [], fileInputs: [], uploadZones: [], headings: [] };

            // Visible buttons
            document.querySelectorAll('button, [role="button"], input[type="submit"], input[type="button"]').forEach(el => {
                const rect = el.getBoundingClientRect();
                const visible = rect.width > 0 && rect.height > 0 && getComputedStyle(el).display !== 'none';
                const text = (el.textContent || el.value || '').trim().substring(0, 80);
                if (text) result.buttons.push({ text, visible, tag: el.tagName, disabled: el.disabled || false });
            });

            // Links
            document.querySelectorAll('a[href]').forEach(el => {
                const rect = el.getBoundingClientRect();
                const visible = rect.width > 0 && rect.height > 0;
                const text = (el.textContent || '').trim().substring(0, 80);
                if (text && visible) result.links.push({ text, href: el.href.substring(0, 120) });
            });

            // All inputs (visible and hidden)
            document.querySelectorAll('input, select, textarea').forEach(el => {
                const rect = el.getBoundingClientRect();
                const visible = rect.width > 0 && rect.height > 0 && getComputedStyle(el).display !== 'none';
                result.inputs.push({
                    tag: el.tagName, type: el.type || '', name: el.name || '',
                    id: el.id || '', placeholder: (el.placeholder || '').substring(0, 50),
                    visible, value: (el.value || '').substring(0, 50)
                });
            });

            // File inputs specifically (including hidden)
            document.querySelectorAll('input[type="file"]').forEach(el => {
                const rect = el.getBoundingClientRect();
                const visible = rect.width > 0 && rect.height > 0;
                const styles = getComputedStyle(el);
                result.fileInputs.push({
                    name: el.name || '', id: el.id || '', accept: el.accept || '',
                    visible, display: styles.display, opacity: styles.opacity,
                    parent: el.parentElement ? el.parentElement.className.substring(0, 60) : ''
                });
            });

            // Upload-related elements (divs, spans with upload/drop/drag in class or text)
            document.querySelectorAll('[class*="upload" i], [class*="drop" i], [class*="drag" i], [class*="file" i], [data-testid*="upload" i]').forEach(el => {
                const rect = el.getBoundingClientRect();
                const visible = rect.width > 0 && rect.height > 0;
                const text = (el.textContent || '').trim().substring(0, 80);
                if (visible) result.uploadZones.push({
                    tag: el.tagName, class: el.className.substring(0, 80), text
                });
            });

            // Headings for page context
            document.querySelectorAll('h1, h2, h3').forEach(el => {
                const text = (el.textContent || '').trim().substring(0, 100);
                if (text) result.headings.push({ tag: el.tagName, text });
            });

            return result;
        }""")

        # Log headings (page context)
        if state.get("headings"):
            log.info(f"  HEADINGS:")
            for h in state["headings"][:10]:
                log.info(f"    <{h['tag']}> {h['text']}")

        # Log buttons
        if state.get("buttons"):
            log.info(f"  BUTTONS ({len(state['buttons'])}):")
            for b in state["buttons"][:20]:
                vis = "VISIBLE" if b["visible"] else "hidden"
                dis = " DISABLED" if b.get("disabled") else ""
                log.info(f"    [{vis}{dis}] <{b['tag']}> \"{b['text']}\"")

        # Log links
        if state.get("links"):
            log.info(f"  LINKS ({len(state['links'])}):")
            for lnk in state["links"][:15]:
                log.info(f"    \"{lnk['text']}\" -> {lnk['href']}")

        # Log inputs
        if state.get("inputs"):
            visible_inputs = [i for i in state["inputs"] if i["visible"]]
            hidden_inputs = [i for i in state["inputs"] if not i["visible"]]
            log.info(f"  INPUTS ({len(visible_inputs)} visible, {len(hidden_inputs)} hidden):")
            for inp in visible_inputs[:20]:
                log.info(f"    [VISIBLE] <{inp['tag']}> type={inp['type']} name=\"{inp['name']}\" id=\"{inp['id']}\" placeholder=\"{inp['placeholder']}\" value=\"{inp['value']}\"")
            for inp in hidden_inputs[:10]:
                log.info(f"    [hidden] <{inp['tag']}> type={inp['type']} name=\"{inp['name']}\" id=\"{inp['id']}\"")

        # Log file inputs (critical for upload debugging)
        if state.get("fileInputs"):
            log.info(f"  FILE INPUTS ({len(state['fileInputs'])}):")
            for fi in state["fileInputs"]:
                vis = "VISIBLE" if fi["visible"] else "HIDDEN"
                log.info(f"    [{vis}] name=\"{fi['name']}\" id=\"{fi['id']}\" accept=\"{fi['accept']}\" display={fi['display']} opacity={fi['opacity']} parent_class=\"{fi['parent']}\"")
        else:
            log.info("  FILE INPUTS: *** NONE FOUND ***")

        # Log upload zones
        if state.get("uploadZones"):
            log.info(f"  UPLOAD ZONES ({len(state['uploadZones'])}):")
            for uz in state["uploadZones"][:10]:
                log.info(f"    <{uz['tag']}> class=\"{uz['class']}\" text=\"{uz['text'][:60]}\"")

    except Exception as e:
        log.warning(f"  Could not dump page state: {e}")

    log.info(f"  ── END PAGE STATE ──")


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


def _smart_fill(page, field_name: str, value: str, label: str) -> bool:
    """Intelligently fill ANY form field — auto-detects component type via DOM analysis.

    Uses JavaScript to inspect the element and its surrounding DOM to determine
    the exact component type, then interacts accordingly:
      - MUI Select (hidden input + combobox div): click combobox, pick from listbox
      - MUI Autocomplete (visible input in Autocomplete wrapper): type to filter, pick option
      - Native <select>: use select_option()
      - Radio buttons: click the matching value
      - Plain text input: fill directly
    """
    # ── Step 1: Analyse the DOM to detect component type ──
    info = page.evaluate("""(fieldName) => {
        const el = document.querySelector(
            `input[name="${fieldName}"], select[name="${fieldName}"], textarea[name="${fieldName}"]`
        );
        if (!el) return { found: false };

        const r = {
            found: true,
            tag: el.tagName.toLowerCase(),
            type: el.type || '',
            ariaHidden: el.getAttribute('aria-hidden'),
            tabIndex: el.tabIndex,
            isMuiSelectNative: el.classList.contains('MuiSelect-nativeInput'),
        };

        // MUI Select: hidden native input, sibling <div role=combobox>
        if (r.isMuiSelectNative || (r.ariaHidden === 'true' && r.tabIndex === -1)) {
            r.kind = 'mui-select';
            const cb = el.parentElement?.querySelector('[role="combobox"]');
            if (cb) {
                r.comboboxId = cb.id || '';
            }
            return r;
        }
        // Native <select>
        if (r.tag === 'select') { r.kind = 'native-select'; return r; }
        // Radio
        if (r.type === 'radio') { r.kind = 'radio'; return r; }
        // MUI Autocomplete: input inside an Autocomplete root
        const ac = el.closest('.MuiAutocomplete-root, [class*="Autocomplete"]');
        if (ac) { r.kind = 'mui-autocomplete'; return r; }
        // Plain text input
        r.kind = 'text';
        return r;
    }""", field_name)

    if not info or not info.get("found"):
        log.info(f"  '{label}': field '{field_name}' not found in DOM")
        return False

    kind = info.get("kind", "text")
    log.info(f"  '{label}': detected {kind} (field={field_name})")

    # ── Step 2: Interact based on component type ──
    try:
        if kind == "mui-select":
            return _interact_mui_select(page, info, value, label)
        elif kind == "mui-autocomplete":
            return _interact_mui_autocomplete(page, field_name, value, label)
        elif kind == "native-select":
            sel = page.locator(f"select[name='{field_name}']").first
            sel.select_option(label=value)
            log.info(f"  {label}: {value} (native select)")
            return True
        elif kind == "radio":
            radio = page.locator(f"input[name='{field_name}'][value='{value}']").first
            radio.click(force=True)
            log.info(f"  {label}: {value} (radio)")
            return True
        else:
            inp = page.locator(f"input[name='{field_name}']").first
            inp.fill(value)
            log.info(f"  {label}: {value} (text input)")
            return True
    except Exception as e:
        log.warning(f"  '{label}' interaction failed: {e}")
        return False


def _interact_mui_select(page, info: dict, text: str, label: str) -> bool:
    """Click the MUI Select combobox div, then pick an option from the popup."""
    # Find the combobox div — prefer by ID, fallback to role
    combobox_id = info.get("comboboxId", "")
    if combobox_id:
        combobox = page.locator(f"#{combobox_id}").first
    else:
        field_input = page.locator(f".MuiSelect-nativeInput").first
        combobox = field_input.locator("xpath=..").locator("[role='combobox']").first

    if not combobox.is_visible(timeout=3000):
        log.warning(f"  '{label}': MUI Select combobox not visible")
        return False

    combobox.click()
    page.wait_for_timeout(1000)

    # Pick the matching option from the popup listbox
    option = page.locator("[role='listbox'] [role='option']").filter(has_text=text).first
    try:
        if option.is_visible(timeout=3000):
            option.click()
            page.wait_for_timeout(500)
            log.info(f"  {label}: {text} (MUI Select)")
            return True
    except Exception:
        pass

    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    log.warning(f"  '{label}': option '{text}' not found in MUI Select")
    return False


def _interact_mui_autocomplete(page, field_name: str, text: str, label: str) -> bool:
    """Type into MUI Autocomplete input, then pick from the filtered dropdown."""
    el = page.locator(f"input[name='{field_name}']").first
    if not el.is_visible(timeout=2000):
        log.warning(f"  '{label}': Autocomplete input not visible")
        return False

    el.click()
    page.wait_for_timeout(500)
    el.fill("")
    page.wait_for_timeout(300)
    el.type(text, delay=80)
    page.wait_for_timeout(1500)

    # Pick the matching option
    option = page.locator("[role='option']").filter(has_text=text).first
    try:
        if option.is_visible(timeout=2000):
            option.click()
            page.wait_for_timeout(500)
            log.info(f"  {label}: {text} (Autocomplete)")
            return True
    except Exception:
        pass

    # Fallback: keyboard — ArrowDown + Enter to pick first suggestion
    el.press("ArrowDown")
    page.wait_for_timeout(300)
    el.press("Enter")
    page.wait_for_timeout(500)
    val = el.input_value()
    if val.strip():
        log.info(f"  {label}: {val} (keyboard fallback)")
        return True

    log.warning(f"  '{label}': could not select '{text}'")
    return False


def _fill_autocomplete(page, input_sel: str, value: str, label: str) -> bool:
    """Type into a TuneCore autocomplete field and pick the matching option.

    TuneCore autocompletes: type text → dropdown appears → click matching option.
    If no dropdown, falls back to typing + Enter.
    """
    try:
        el = page.locator(input_sel).first
        if not el.is_visible(timeout=2000):
            log.info(f"  {label}: input not visible ({input_sel})")
            return False

        el.click()
        page.wait_for_timeout(300)
        el.fill("")
        page.wait_for_timeout(200)
        el.type(value, delay=60)
        page.wait_for_timeout(1500)

        # Try to pick from dropdown
        option = page.locator("[role='option'], [role='listbox'] li, .MuiAutocomplete-option").filter(has_text=value).first
        try:
            if option.is_visible(timeout=2000):
                option.click()
                page.wait_for_timeout(500)
                log.info(f"  {label}: '{value}' (autocomplete dropdown)")
                return True
        except Exception:
            pass

        # Fallback: ArrowDown + Enter
        el.press("ArrowDown")
        page.wait_for_timeout(300)
        el.press("Enter")
        page.wait_for_timeout(500)
        log.info(f"  {label}: '{value}' (keyboard fallback)")
        return True
    except Exception as e:
        log.warning(f"  {label}: autocomplete failed: {e}")
        return False


def _upload_file(page, file_path: Path):
    """Upload a file via input[type=file] or file chooser dialog."""
    log.info(f"  _upload_file: looking for file input for {file_path.name}...")

    # Strategy 1: Find ALL file inputs via JS (catches hidden ones too)
    try:
        file_input_count = page.evaluate("document.querySelectorAll('input[type=file]').length")
        log.info(f"  Strategy 1: Found {file_input_count} input[type=file] elements via JS")
        if file_input_count > 0:
            for i in range(file_input_count):
                try:
                    el = page.locator("input[type='file']").nth(i)
                    el.set_input_files(str(file_path), timeout=5000)
                    log.info(f"  File selected via input[type=file] (index {i})")
                    return True
                except Exception as exc:
                    log.info(f"  input[type=file] index {i} failed: {exc}")
                    continue
    except Exception as exc:
        log.info(f"  Strategy 1 failed: {exc}")

    # Strategy 2: Make hidden file inputs visible, then try again
    try:
        page.evaluate("""
            document.querySelectorAll('input[type=file]').forEach(el => {
                el.style.display = 'block';
                el.style.visibility = 'visible';
                el.style.opacity = '1';
                el.style.width = '200px';
                el.style.height = '50px';
                el.style.position = 'relative';
                el.style.zIndex = '99999';
            });
        """)
        page.wait_for_timeout(500)
        inputs = page.locator("input[type='file']")
        count = inputs.count()
        log.info(f"  Strategy 2: After unhiding, found {count} file inputs")
        for i in range(count):
            try:
                el = inputs.nth(i)
                el.set_input_files(str(file_path), timeout=5000)
                log.info(f"  File selected via unhidden input[type=file] (index {i})")
                return True
            except Exception as exc:
                log.info(f"  Unhidden input index {i} failed: {exc}")
                continue
    except Exception as exc:
        log.info(f"  Strategy 2 failed: {exc}")

    # Strategy 3: Click upload area to trigger a file chooser dialog
    log.info("  Strategy 3: Trying file chooser via click...")
    for selector in [
        "[class*='upload' i]", "[class*='drop' i]", "[class*='dropzone' i]",
        "[class*='drag' i]", "[data-testid*='upload' i]",
        "text=Upload", "text=Choose File", "text=Browse",
        "text=Drag", "text=Drop files", "text=Click to upload",
        "text=click to upload", "text=Choose a file",
        "button:has-text('Upload')", "div[class*='Upload']",
        "text=Add Audio", "text=Add File", "text=Select File",
    ]:
        try:
            el = page.locator(selector).first
            if el.is_visible(timeout=1000):
                log.info(f"  Trying file chooser via: {selector}")
                with page.expect_file_chooser(timeout=10000) as fc_info:
                    el.click()
                file_chooser = fc_info.value
                file_chooser.set_files(str(file_path))
                log.info(f"  File uploaded via file chooser: {selector}")
                return True
        except Exception:
            continue

    # Failed — dump page state to understand what's on screen
    log.warning(f"Could not find file input for {file_path.name}")
    _dump_page_state(page, f"UPLOAD FAILED for {file_path.name}")
    return False


def _wait_for_upload(page, timeout: int = 300, file_was_set: bool = True):
    """Wait for file upload to complete.

    Args:
        page: Playwright page.
        timeout: Max seconds to wait.
        file_was_set: If False, skip waiting (upload never started).
    """
    if not file_was_set:
        log.warning("  Skipping upload wait — file was never set")
        return

    start = time.time()
    seen_progress = False

    # Give TuneCore a moment to start processing the file
    page.wait_for_timeout(3000)

    while time.time() - start < timeout:
        # Check for success indicators
        for text in ["Upload complete", "Uploaded", "Success", "100%",
                      "Complete", "Done", "Ready"]:
            try:
                if page.locator(f"text={text}").first.is_visible(timeout=500):
                    log.info(f"  Upload complete: found '{text}'")
                    return
            except Exception:
                continue

        # Check progress bar — only trust "gone" if we saw it appear first
        try:
            progress = page.locator("[class*='progress']").first
            if progress.is_visible(timeout=1000):
                seen_progress = True
                log.info("  Upload progress bar visible...")
            elif seen_progress:
                # Was visible before, now gone => upload finished
                log.info("  Upload progress bar gone — upload complete")
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


def _detect_page(page) -> str:
    """Scan the DOM and determine which TuneCore step the current page is on.

    Returns one of: dashboard, choose_type, start, release_details,
    add_track, track_details, upload_wav, artwork, review, release, done, unknown
    """
    state = page.evaluate("""() => {
        const body = document.body?.innerText?.toLowerCase() || '';
        const url = window.location.href.toLowerCase();
        const has = (sel) => !!document.querySelector(sel);
        const visible = (sel) => {
            const el = document.querySelector(sel);
            return el && el.offsetWidth > 0 && el.offsetHeight > 0;
        };
        const anyVisible = (...sels) => sels.some(s => visible(s));
        const visibleBtn = (text) => {
            return [...document.querySelectorAll('button, a, label, [role="button"]')]
                .some(el => el.offsetWidth > 0 && el.textContent.toLowerCase().includes(text));
        };

        return {
            url,
            isDashboard: url.includes('/dashboard'),
            hasTypeChoice: visibleBtn('single') && (visibleBtn('album') || visibleBtn('ep') || visibleBtn('ringtone')),
            hasStartBtn: visibleBtn('start') || visibleBtn('begin'),
            hasLangField: has('input[name="languageCode"]'),
            hasGenreField: has('input[name="primaryGenreId"]'),
            hasAddTrackBtn: visibleBtn('add track'),
            hasUnuploadedFile: body.includes("hasn't been uploaded") || body.includes('file hasn'),
            hasWriterField: anyVisible('input[name*="songwriter" i]', 'input[name*="writer" i]'),
            hasRoleField: has('input[name="role"]') || has('select[name="role"]')
                || has('input[name="creativeRole"]') || has('select[name="creativeRole"]'),
            hasFileInput: has('input[type="file"]'),
            hasArtworkBtn: visibleBtn('add artwork') || visibleBtn('upload artwork')
                || visibleBtn('cover art') || visibleBtn('add image'),
            hasReviewBtn: visibleBtn('continue and review') || visibleBtn('continue & review'),
            hasReleaseBtn: visibleBtn('release music'),
            hasConfirm: body.includes('congrat') || body.includes('submitted your release')
                || body.includes('in review'),
        };
    }""")

    log.info(f"  Page scan: url={state.get('url', '?')}")
    flags = [k for k, v in state.items() if k != 'url' and v]
    if flags:
        log.info(f"    Flags: {', '.join(flags)}")

    if state.get('hasConfirm'):
        return 'done'
    # Dashboard has "Singles/Albums" filter tabs — check URL early to avoid
    # misidentifying those tabs as the release-type chooser page.
    if state.get('isDashboard'):
        return 'dashboard'
    if state.get('hasReleaseBtn') and not state.get('hasTypeChoice'):
        return 'release'
    # ③ Tracks page has BOTH "Add Track" AND "Continue to Review".
    # If tracks still need uploading, stay on add_track.
    # If all tracks uploaded, proceed to review.
    if state.get('hasReviewBtn') and state.get('hasAddTrackBtn'):
        if not state.get('hasUnuploadedFile'):
            return 'review'  # all files uploaded → Continue to Review
        # else: fall through to add_track (need to upload WAV first)
    if state.get('hasReviewBtn') and not state.get('hasAddTrackBtn'):
        return 'review'
    if state.get('hasArtworkBtn') and not state.get('hasAddTrackBtn'):
        return 'artwork'
    if state.get('hasFileInput') and not state.get('hasWriterField'):
        return 'upload_wav'
    if state.get('hasWriterField') or state.get('hasRoleField'):
        return 'track_details'
    if state.get('hasAddTrackBtn'):
        return 'add_track'
    if state.get('hasLangField') or state.get('hasGenreField'):
        return 'release_details'
    if state.get('hasStartBtn') and not state.get('hasTypeChoice'):
        return 'start'
    if state.get('hasTypeChoice'):
        return 'choose_type'
    return 'unknown'


def _do_upload(
    wav_path: Path,
    cover_path: Path,
    concept: MusicConcept,
    artist: str,
) -> str | None:
    """Upload to TuneCore using adaptive page detection.

    Scans the page after every action to decide what to do next.
    Works for both new releases and resumed drafts — no hardcoded step order.
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
        step = 0
        MAX_STEPS = 20

        try:
            log.info("Navigating to TuneCore dashboard...")
            page.goto(f"{TUNECORE_BASE}/dashboard", wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(3000)

            if not _check_login(page):
                return None
            log.info(f"  Logged in: {page.url}")

            # ── Adaptive loop: detect → act → repeat ──
            while step < MAX_STEPS:
                step += 1
                page.screenshot(path=f"output/tunecore_{step:02d}.png")
                state = _detect_page(page)
                log.info(f"{'='*50}")
                log.info(f"[{step}] Page state: {state}")
                log.info(f"{'='*50}")

                # ── DASHBOARD ──
                if state == 'dashboard':
                    draft = None
                    try:
                        draft = page.locator(f"a:has-text('{concept.track_name}')").first
                        if not draft.is_visible(timeout=2000):
                            draft = None
                    except Exception:
                        draft = None

                    if draft:
                        log.info(f"  Found draft '{concept.track_name}' — clicking...")
                        draft.click()
                        page.wait_for_timeout(5000)
                    else:
                        log.info("  No draft found — creating new release...")
                        btn = _find_clickable(page, [
                            "text=Add Release", "button:has-text('Add Release')",
                            "a:has-text('Add Release')", "text=Create New",
                        ])
                        if btn:
                            btn.click()
                            page.wait_for_timeout(3000)
                        else:
                            page.goto(f"{TUNECORE_BASE}/releases/new",
                                      wait_until="domcontentloaded", timeout=30_000)
                            page.wait_for_timeout(3000)

                # ── CHOOSE TYPE (Single) ──
                elif state == 'choose_type':
                    btn = _find_clickable(page, [
                        "text=Single", "button:has-text('Single')",
                        "[data-type='single']", "label:has-text('Single')",
                    ])
                    if btn:
                        btn.click()
                        log.info("  Selected: Single")
                        page.wait_for_timeout(2000)

                # ── START ──
                elif state == 'start':
                    btn = _find_clickable(page, [
                        "button:has-text('Start')", "a:has-text('Start')",
                        "button:has-text('Begin')", "button:has-text('Continue')",
                    ])
                    if btn:
                        btn.click()
                        log.info("  Clicked Start")
                        page.wait_for_timeout(3000)

                # ── RELEASE DETAILS (title, language, genre) ──
                elif state == 'release_details':
                    log.info("  Filling release details...")
                    for sel in ["input[name*='title' i]", "input[name*='name' i]"]:
                        try:
                            el = page.locator(sel).first
                            if el.is_visible(timeout=1500):
                                el.fill(concept.track_name)
                                log.info(f"  Title: {concept.track_name}")
                                break
                        except Exception:
                            continue

                    _smart_fill(page, "languageCode", "English", "Language")
                    for g in ["Afro house", "Afro House", "Electronic", "Dance"]:
                        if _smart_fill(page, "primaryGenreId", g, "Primary genre"):
                            break
                    for g in ["Afro house", "Afro House", "Electronic", "Dance"]:
                        if _smart_fill(page, "secondaryGenreId", g, "Secondary genre"):
                            break

                    no_btn = _find_clickable(page, [
                        "label:has-text('No')", "input[type='radio'][value='no']",
                        "input[type='radio'][value='false']",
                    ])
                    if no_btn:
                        no_btn.click()
                        log.info("  Previously Released: No")

                    save = _find_clickable(page, [
                        "button:has-text('Save')", "button[type='submit']",
                    ])
                    if save:
                        save.click()
                        log.info("  Saved — waiting for next page (~2 min)...")
                        for i in range(24):
                            page.wait_for_timeout(5000)
                            ns = _detect_page(page)
                            if ns != 'release_details':
                                log.info(f"  Page changed → '{ns}' after ~{(i+1)*5}s")
                                break
                            if i % 4 == 3:
                                log.info(f"  Still loading... ({(i+1)*5}s)")

                # ── ADD TRACK ──
                # Real TuneCore flow on ③ Tracks page:
                #   1. Click "ADD TRACK" → file chooser opens
                #   2. Select WAV file from folder
                #   3. Wait ~1 min for upload/processing
                #   4. Click "Continue to Review"
                elif state == 'add_track':
                    log.info(f"  Uploading WAV via Add Track: {wav_path.name}")
                    _dump_page_state(page, "Add Track — before")

                    btn = _find_clickable(page, [
                        "text=Add Track", "button:has-text('Add Track')",
                        "a:has-text('Add Track')", "text=Add track",
                        "text=ADD TRACK",
                    ])
                    if btn:
                        # ADD TRACK opens file picker — upload WAV through it
                        uploaded = False
                        try:
                            with page.expect_file_chooser(timeout=10_000) as fc_info:
                                btn.click()
                            file_chooser = fc_info.value
                            file_chooser.set_files(str(wav_path))
                            uploaded = True
                            log.info(f"  WAV selected via file chooser: {wav_path.name}")
                        except Exception as e:
                            log.info(f"  File chooser not triggered ({e}), trying input[type=file]...")
                            btn.click()
                            page.wait_for_timeout(2000)
                            uploaded = _upload_file(page, wav_path)

                        if not uploaded:
                            raise RuntimeError(f"Failed to upload WAV '{wav_path.name}' via Add Track")

                        # Wait ~1 min for TuneCore to process the upload
                        log.info("  WAV uploading — waiting 1 min for processing...")
                        page.wait_for_timeout(60_000)
                        _dump_page_state(page, "Add Track — after 1 min wait")

                # ── TRACK DETAILS ──
                # Sections on TuneCore track page (from screenshots):
                #   1. Song Title (text input)
                #   2. Songwriter (autocomplete → "GrooveGenix")
                #   3. Song Artists & Creatives (autocomplete name + role dropdown)
                #   4. Performing Artists (autocomplete name)
                #   5. Producers & Engineers (autocomplete name + role = "producer")
                #   6. Copyright Ownership: Is this a cover? = No
                #   7. Instrumental checkbox
                elif state == 'track_details':
                    log.info("  Filling track details...")
                    _dump_page_state(page, "Track Details — before fill")

                    # 1. Song Title
                    for sel in [
                        "input[name*='track' i][name*='name' i]",
                        "input[name*='song' i][name*='title' i]",
                        "input[name*='title' i]",
                    ]:
                        try:
                            el = page.locator(sel).first
                            if el.is_visible(timeout=1500):
                                if not el.input_value().strip():
                                    el.fill(concept.track_name)
                                log.info(f"  Song Title: {concept.track_name}")
                                break
                        except Exception:
                            continue

                    # 2. Songwriter (autocomplete — type + pick from dropdown)
                    _fill_autocomplete(
                        page,
                        "input[name*='songwriter' i], input[name*='writer' i], "
                        "input[placeholder*='Legal First Name' i], input[placeholder*='songwriter' i]",
                        artist, "Songwriter",
                    )

                    # 3. Song Artists & Creatives — name (autocomplete) + role (dropdown)
                    # The "Artist/Creative Name" field in this section
                    for sel in [
                        "input[name*='artist' i][name*='name' i]",
                        "input[name*='creative' i][name*='name' i]",
                        "input[placeholder*='Artist' i]",
                    ]:
                        try:
                            el = page.locator(sel).first
                            if el.is_visible(timeout=1500):
                                _fill_autocomplete(page, sel, artist, "Song Artist Name")
                                break
                        except Exception:
                            continue

                    # Role = Main Artist (dropdown/select)
                    for rn in ["role", "creativeRole"]:
                        ok = False
                        for rv in ["Main Artist", "main artist", "Primary Artist"]:
                            if _smart_fill(page, rn, rv, "Song Artist Role"):
                                ok = True
                                break
                        if ok:
                            break

                    # 4. Performing Artists (autocomplete name)
                    for sel in [
                        "input[name*='performing' i]",
                        "input[placeholder*='performing' i]",
                    ]:
                        try:
                            el = page.locator(sel).first
                            if el.is_visible(timeout=1500):
                                _fill_autocomplete(page, sel, artist, "Performing Artist")
                                break
                        except Exception:
                            continue

                    # 5. Producers & Engineers — name (autocomplete) + role = producer
                    for sel in [
                        "input[name*='producer' i]",
                        "input[name*='engineer' i]",
                    ]:
                        try:
                            el = page.locator(sel).first
                            if el.is_visible(timeout=1500):
                                _fill_autocomplete(page, sel, artist, "Producer Name")
                                break
                        except Exception:
                            continue

                    # Producer role dropdown
                    for rn in ["producerRole", "engineerRole", "role"]:
                        for rv in ["Producer", "producer"]:
                            if _smart_fill(page, rn, rv, "Producer Role"):
                                break

                    # 6. Copyright: Is this a cover? = No
                    cover_no = _find_clickable(page, [
                        "input[name*='cover' i][value='no']",
                        "input[name*='cover' i][value='false']",
                        "label:has-text('No')",
                    ])
                    if cover_no:
                        cover_no.click()
                        log.info("  Is this a cover: No")

                    # 7. Instrumental checkbox
                    instr = _find_clickable(page, [
                        "label:has-text('Instrumental')", "input[name*='instrumental' i]",
                        "label:has-text('no lyrics')",
                    ])
                    if instr:
                        instr.click()
                        log.info("  Instrumental: checked")

                    _dump_page_state(page, "Track Details — after fill")

                    # Save
                    save = _find_clickable(page, [
                        "button:has-text('Save')", "button[type='submit']",
                    ])
                    if save:
                        save.click()
                        log.info("  Saved track — waiting 1 min...")
                        page.wait_for_timeout(60_000)

                # ── UPLOAD WAV ──
                elif state == 'upload_wav':
                    log.info(f"  Uploading WAV: {wav_path.name}")
                    _dump_page_state(page, "Before WAV Upload")
                    wav_ok = _upload_file(page, wav_path)
                    if not wav_ok:
                        raise RuntimeError(f"Failed to upload WAV '{wav_path.name}'")
                    log.info("  Waiting for WAV upload (~5 min)...")
                    _wait_for_upload(page, timeout=360, file_was_set=wav_ok)

                    cont = _find_clickable(page, [
                        "button:has-text('Continue')", "button:has-text('Next')",
                        "a:has-text('Continue')",
                    ])
                    if cont:
                        cont.click()
                        page.wait_for_timeout(5000)
                        log.info("  Clicked Continue after WAV")

                # ── ARTWORK ──
                elif state == 'artwork':
                    log.info(f"  Uploading cover art: {cover_path.name}")
                    art_btn = _find_clickable(page, [
                        "text=Add Artwork", "button:has-text('Add Artwork')",
                        "text=Upload Artwork", "text=Add Cover Art", "text=Add Image",
                    ])
                    if art_btn:
                        art_btn.click()
                        page.wait_for_timeout(3000)

                    cover_ok = _upload_file(page, cover_path)
                    if not cover_ok:
                        raise RuntimeError(f"Failed to upload cover '{cover_path.name}'")
                    log.info("  Waiting for artwork upload (~1 min)...")
                    _wait_for_upload(page, timeout=120, file_was_set=cover_ok)

                    sc = _find_clickable(page, [
                        "button:has-text('Save and Continue')",
                        "button:has-text('Save & Continue')",
                        "button:has-text('Continue')", "button:has-text('Save')",
                    ])
                    if sc:
                        sc.click()
                        page.wait_for_timeout(5000)
                        log.info("  Clicked Save & Continue after artwork")

                # ── REVIEW ──
                elif state == 'review':
                    btn = _find_clickable(page, [
                        "button:has-text('Continue and Review')",
                        "button:has-text('Continue & Review')",
                        "button:has-text('Review')", "button:has-text('Continue')",
                    ])
                    if btn:
                        btn.click()
                        page.wait_for_timeout(5000)
                        log.info("  Clicked Continue and Review")

                # ── RELEASE ──
                elif state == 'release':
                    btn = _find_clickable(page, [
                        "button:has-text('Release Music')", "button:has-text('Release')",
                        "button:has-text('Submit')", "button:has-text('Distribute')",
                    ])
                    if btn:
                        btn.click()
                        page.wait_for_timeout(5000)
                        log.info("  Clicked Release Music")

                # ── DONE ──
                elif state == 'done':
                    log.info("  Release confirmed!")
                    break

                # ── UNKNOWN ──
                else:
                    _dump_page_state(page, f"Unknown page (step {step})")
                    log.warning("  Unknown page — waiting 10s and retrying...")
                    page.wait_for_timeout(10_000)

            # ── Wrap up ──
            page.screenshot(path="output/tunecore_final.png")
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
