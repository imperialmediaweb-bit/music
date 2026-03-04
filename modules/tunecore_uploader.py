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

import re
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


def continue_tunecore_draft(
    track_name: str,
    artist: str = DEFAULT_ARTIST,
) -> str | None:
    """Continue filling out an existing TuneCore draft.

    Opens TuneCore dashboard, finds the draft by name, fills track details.
    Generates 1600x1600 cover art if none exists locally.
    Uses local WAV if found in output/.

    Args:
        track_name: Name of the draft release on TuneCore.
        artist: Artist / songwriter name.

    Returns:
        URL or status string, or None on failure.
    """
    from config import OUTPUT_DIR

    log.info(f"Continuing TuneCore draft: {track_name}")

    if not TUNECORE_STATE_FILE.exists():
        log.error(
            f"TuneCore session not found: {TUNECORE_STATE_FILE}\n"
            "Run: python main.py tunecore-login"
        )
        return None

    concept = MusicConcept(
        track_name=track_name,
        genre="Afro House",
        mood="energetic",
        description=f"A track called {track_name}",
        music_prompt="instrumental afro house",
        hashtags=["afrohouse", "music"],
        thumbnail_prompt="abstract African mask art, vibrant colors, dark background",
        youtube_title=track_name,
        youtube_description=track_name,
        youtube_tags=["afrohouse"],
        tiktok_caption=track_name,
    )

    safe = track_name.replace(" ", "_")
    name_variants = [track_name, safe]

    # Look for existing cover art (1600x1600)
    cover_path = None
    for name in name_variants:
        for suffix in ["_cover.jpg", "_cover.png", "_thumbnail.jpg", "_thumbnail.png"]:
            candidate = OUTPUT_DIR / f"{name}{suffix}"
            if candidate.exists():
                cover_path = candidate
                log.info(f"Found existing cover: {cover_path}")
                break
        if cover_path:
            break

    if not cover_path:
        try:
            from modules.thumbnail_generator import generate_cover_art
            log.info("No cover art found — generating 1600x1600...")
            cover_path = generate_cover_art(concept.thumbnail_prompt, track_name, artist)
            log.info(f"Cover art generated: {cover_path}")
        except Exception as e:
            log.warning(f"Could not generate cover art: {e}")

    # Look for local WAV
    wav_path = None
    for name in name_variants:
        for ext in [".wav", ".WAV"]:
            candidate = OUTPUT_DIR / f"{name}{ext}"
            if candidate.exists():
                wav_path = candidate
                log.info(f"Found existing WAV: {wav_path}")
                break
        if wav_path:
            break

    return _do_upload(
        wav_path=wav_path or Path("/dev/null"),
        cover_path=cover_path or Path("/dev/null"),
        concept=concept,
        artist=artist,
    )


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
    info["fieldName"] = field_name  # pass field_name for fiber lookup
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


def _react_fiber_set(page, selector: str, value: str, label: str) -> bool:
    """Set a React-controlled value by accessing React fiber internals.

    Instead of clicking dropdown + picking option (fragile), we:
    1. Find the DOM element via selector
    2. Walk the React fiber tree to find the onChange handler
    3. Call onChange directly with the desired value

    Works with react-select, MUI Select, MUI Autocomplete, and any
    React-controlled component.
    """
    result = page.evaluate("""(args) => {
        const { selector, value } = args;
        const el = document.querySelector(selector);
        if (!el) return { ok: false, error: 'element not found: ' + selector };

        // Find React fiber key on the element
        const fiberKey = Object.keys(el).find(
            k => k.startsWith('__reactFiber$') || k.startsWith('__reactInternalInstance$')
        );
        if (!fiberKey) return { ok: false, error: 'no React fiber on element' };

        let fiber = el[fiberKey];

        // Walk UP the fiber tree looking for onChange / onInputChange / props.onChange
        // We look for select-like components (react-select, MUI Select, etc.)
        const MAX_DEPTH = 30;
        for (let i = 0; i < MAX_DEPTH && fiber; i++) {
            const props = fiber.memoizedProps || fiber.pendingProps || {};

            // react-select: has onChange that accepts { value, label }
            if (props.onChange && (props.options || props.isSearchable !== undefined)) {
                // Find matching option
                const options = props.options || [];
                let match = options.find(o =>
                    (o.label || '').toLowerCase().includes(value.toLowerCase())
                );
                if (!match) {
                    // Flatten grouped options
                    for (const group of options) {
                        if (group.options) {
                            match = group.options.find(o =>
                                (o.label || '').toLowerCase().includes(value.toLowerCase())
                            );
                            if (match) break;
                        }
                    }
                }
                if (match) {
                    props.onChange(match, { action: 'select-option', option: match });
                    return { ok: true, method: 'react-select', selected: match.label };
                }
                // If no match found, list available options for debugging
                const available = options.slice(0, 10).map(o => o.label || o.value || JSON.stringify(o));
                return { ok: false, error: 'no matching option', available, value };
            }

            // MUI Select: has onChange that accepts a synthetic event
            if (props.onChange && props.value !== undefined && props.children) {
                // Try to find the option value from children
                const findValue = (children) => {
                    if (!children) return null;
                    const arr = Array.isArray(children) ? children : [children];
                    for (const child of arr) {
                        if (!child || !child.props) continue;
                        const childText = child.props.children || '';
                        if (typeof childText === 'string' &&
                            childText.toLowerCase().includes(value.toLowerCase())) {
                            return child.props.value;
                        }
                    }
                    return null;
                };
                const optValue = findValue(props.children);
                if (optValue !== null) {
                    props.onChange({ target: { value: optValue } });
                    return { ok: true, method: 'mui-select', selected: optValue };
                }
            }

            fiber = fiber.return;
        }

        return { ok: false, error: 'no onChange handler found after ' + MAX_DEPTH + ' levels' };
    }""", {"selector": selector, "value": value})

    if result.get("ok"):
        log.info(f"  {label}: '{result.get('selected')}' ({result.get('method')})")
        page.wait_for_timeout(500)
        return True

    log.info(f"  {label}: fiber approach failed: {result.get('error', '?')}")
    if result.get("available"):
        log.info(f"  {label}: available options: {result['available']}")
    return False


def _interact_mui_select(page, info: dict, text: str, label: str) -> bool:
    """Set MUI Select value — tries React fiber first, then DOM click fallback."""
    field_name = info.get("fieldName", "")

    # ── Strategy 1: React fiber (most reliable) ──
    for selector in [
        f"input[name='{field_name}']" if field_name else None,
        ".MuiSelect-nativeInput",
        f"#{info.get('comboboxId', '')}" if info.get("comboboxId") else None,
    ]:
        if selector and _react_fiber_set(page, selector, text, label):
            return True

    # ── Strategy 2: DOM click fallback ──
    combobox_id = info.get("comboboxId", "")
    if combobox_id:
        combobox = page.locator(f"#{combobox_id}").first
    else:
        field_input = page.locator(f".MuiSelect-nativeInput").first
        combobox = field_input.locator("xpath=..").locator("[role='combobox']").first

    if not combobox.is_visible(timeout=3000):
        log.warning(f"  '{label}': MUI Select combobox not visible")
        return False

    # Try click, then mousedown, then keyboard to open
    for open_method in ["click", "mousedown", "keyboard"]:
        try:
            if open_method == "click":
                combobox.click()
            elif open_method == "mousedown":
                combobox.dispatch_event("mousedown")
            else:
                combobox.focus()
                page.keyboard.press("Space")
            page.wait_for_timeout(1000)

            option = page.locator("[role='listbox'] [role='option']").filter(has_text=text).first
            if option.is_visible(timeout=2000):
                option.click()
                page.wait_for_timeout(500)
                log.info(f"  {label}: {text} (MUI Select via {open_method})")
                return True
        except Exception:
            continue

    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    log.warning(f"  '{label}': option '{text}' not found in MUI Select")
    return False


def _interact_mui_autocomplete(page, field_name: str, text: str, label: str) -> bool:
    """Set MUI Autocomplete — tries React fiber first, then type+pick fallback."""
    # ── Strategy 1: React fiber ──
    if _react_fiber_set(page, f"input[name='{field_name}']", text, label):
        return True

    # ── Strategy 2: Type + pick from dropdown ──
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
            log.info(f"  {label}: {text} (Autocomplete click)")
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


def _click_dropdown_option(page, name: str, label: str, prefer: list = None):
    """After a dropdown is already open, find and click the right option.

    Tags the option with data-pick-me, then uses Playwright .click()
    so React events fire properly.
    """
    tagged = page.evaluate("""(args) => {
        const { name, prefer } = args;
        const vis = el => el.offsetWidth > 0 && el.offsetHeight > 0;
        const selectors = [
            '[role=option]', '[role=listbox] li',
            '[class*=option]', '[class*=Option]',
            '[id*=option]',
            '[class*=menu] div', '[class*=Menu] div',
            '[class*=listbox] div',
            '[class*=dropdown] li', '[class*=Dropdown] li',
            '[class*=dropdown] div', '[class*=Dropdown] div',
            'ul li', '.list-group li',
        ];

        let opts = [];
        for (const sel of selectors) {
            const found = [...document.querySelectorAll(sel)].filter(el =>
                vis(el) && el.textContent.trim().length > 0 &&
                el.textContent.trim().length < 60 &&
                el.textContent.trim().toUpperCase() !== 'CHOOSE' &&
                el.textContent.trim().toLowerCase() !== 'select...');
            opts.push(...found);
        }
        opts = [...new Set(opts)];

        // Remove any old tags
        document.querySelectorAll('[data-pick-me]').forEach(el =>
            el.removeAttribute('data-pick-me'));

        // If we have preferred keywords (role selection), try those first
        if (prefer && prefer.length > 0) {
            for (const pref of prefer) {
                for (const el of opts) {
                    if (el.textContent.trim().toLowerCase().includes(pref)) {
                        el.setAttribute('data-pick-me', 'true');
                        return { found: true, text: el.textContent.trim() };
                    }
                }
            }
        }

        // Exact match by name
        for (const el of opts) {
            if (el.textContent.trim() === name) {
                el.setAttribute('data-pick-me', 'true');
                return { found: true, text: el.textContent.trim() };
            }
        }
        // Case-insensitive
        for (const el of opts) {
            if (el.textContent.trim().toLowerCase() === name.toLowerCase()) {
                el.setAttribute('data-pick-me', 'true');
                return { found: true, text: el.textContent.trim() };
            }
        }
        // Contains
        for (const el of opts) {
            const t = el.textContent.trim();
            if (t.toLowerCase().includes(name.toLowerCase()) &&
                t.length < name.length + 30) {
                el.setAttribute('data-pick-me', 'true');
                return { found: true, text: t };
            }
        }
        // Do NOT pick first random option — return not found instead
        const available = opts.map(el => el.textContent.trim()).slice(0, 15);
        return { found: false, total: opts.length, available };
    }""", {"name": name, "prefer": prefer or []})

    if tagged.get('found'):
        try:
            pick = page.locator("[data-pick-me='true']").first
            if pick.is_visible(timeout=2000):
                pick.click()
                page.wait_for_timeout(500)
                log.info(f"  {label}: selected '{tagged.get('text')}'")
                return True
        except Exception as e:
            log.warning(f"  {label}: Playwright click failed: {e}")
    # Log available options instead of blindly selecting
    if tagged.get('available'):
        log.warning(f"  {label}: could not find '{name}' — available options: {tagged['available']}")
    else:
        log.warning(f"  {label}: no matching option found for '{name}'")
    return False


def _fill_choose_sections(page, artist: str):
    """Fill artist names + roles. PURE Playwright — zero JS evaluate."""
    log.info(f"  _fill_choose_sections: artist='{artist}'")

    # ── Phase 1: Fill empty "Add Artist/Creative" inputs, one at a time ──
    for attempt in range(5):
        all_inputs = page.locator('input')
        count = all_inputs.count()
        filled = False
        for i in range(count):
            try:
                inp = all_inputs.nth(i)
                if not inp.is_visible(timeout=300):
                    continue
                ph = (inp.get_attribute('placeholder') or '').lower()
                val = inp.input_value()
                if not val.strip() and ('artist' in ph or 'creative' in ph):
                    log.info(f"  [{attempt}] Empty input #{i} ph='{ph}', filling...")
                    inp.click()
                    page.wait_for_timeout(500)
                    inp.type(artist, delay=80)
                    page.wait_for_timeout(2000)
                    # Select from autocomplete dropdown
                    try:
                        opt = page.locator(
                            "[role='option'], [id*='option'], [class*='option']"
                        ).filter(has_text=artist).first
                        if opt.is_visible(timeout=2000):
                            opt.click()
                            log.info(f"  [{attempt}] Name: '{artist}' (dropdown)")
                        else:
                            inp.press("ArrowDown")
                            page.wait_for_timeout(300)
                            inp.press("Enter")
                            log.info(f"  [{attempt}] Name: '{artist}' (keyboard)")
                    except Exception:
                        inp.press("ArrowDown")
                        page.wait_for_timeout(300)
                        inp.press("Enter")
                        log.info(f"  [{attempt}] Name: keyboard fallback")
                    page.wait_for_timeout(1500)
                    filled = True
                    break
            except Exception as e:
                log.warning(f"  [{attempt}] Input #{i}: {e}")
                continue
        if not filled:
            log.info(f"  No more empty name inputs (after {attempt})")
            break

    # ── Phase 2: Fill Role dropdowns per section (multi-select) ──
    # Click the box → dropdown opens → click option(s) → done.
    # Legend text: "Performing Artists*", "Song Artists & Creatives", "Producers & Engineers*"
    SECTION_ROLES = {
        'song artists':          ['main artist', 'performer'],
        'artists & creatives':   ['main artist', 'performer'],
        'performing artists':    ['accordion', 'background vocals', 'banjo'],
        'performing artist':     ['accordion', 'background vocals', 'banjo'],
        'producers & engineers': ['producer'],
        'producers':             ['producer'],
        'engineers':             ['producer'],
    }

    def _get_section_roles(legend_text):
        s = legend_text.lower().replace('*', '').strip()
        for key, roles in SECTION_ROLES.items():
            if key in s:
                return roles
        return ['producer']

    for attempt in range(8):
        try:
            choose = page.get_by_text('CHOOSE', exact=True).first
            if not choose.is_visible(timeout=1500):
                log.info(f"  No more CHOOSE dropdowns (after {attempt})")
                break

            # Find which section this belongs to via <fieldset> → <legend>
            section_text = page.evaluate("""(el) => {
                const fs = el.closest('fieldset.artists_creatives_fieldset');
                if (fs) {
                    const lg = fs.querySelector('legend.artists_creatives_legend');
                    if (lg) return lg.textContent.trim().toLowerCase();
                }
                return 'unknown';
            }""", choose.element_handle())

            desired_roles = _get_section_roles(section_text)
            log.info(f"  [{attempt}] Section: '{section_text}' → roles: {desired_roles}")

            # Click the dropdown CONTAINER (parent of "CHOOSE" text), not the
            # text node itself.  Walk up to the nearest react-select control,
            # combobox role, or any wrapper that acts as the click target.
            dropdown_opened = False
            choose.scroll_into_view_if_needed(timeout=2000)

            # Try clicking the parent control first (react-select / MUI wrapper)
            try:
                parent = page.evaluate("""(el) => {
                    // Walk up to the nearest clickable dropdown wrapper
                    let cur = el;
                    for (let i = 0; i < 6; i++) {
                        cur = cur.parentElement;
                        if (!cur) break;
                        const role = cur.getAttribute('role') || '';
                        const cls = cur.className || '';
                        if (role === 'combobox' || role === 'listbox'
                            || /control|select|dropdown|indicator/i.test(cls)) {
                            cur.setAttribute('data-choose-click', 'true');
                            return true;
                        }
                    }
                    return false;
                }""", choose.element_handle())

                if parent:
                    wrapper = page.locator("[data-choose-click='true']").first
                    if wrapper.is_visible(timeout=1000):
                        wrapper.click()
                        page.wait_for_timeout(1000)
                        # Check if dropdown actually opened
                        if page.locator("[role='option'], [role='listbox'] [role='option']").first.is_visible(timeout=1500):
                            dropdown_opened = True
                            log.info(f"  [{attempt}] Dropdown opened via parent container")
                    # Clean up marker
                    page.evaluate("document.querySelectorAll('[data-choose-click]').forEach(el => el.removeAttribute('data-choose-click'))")
            except Exception as e:
                log.info(f"  [{attempt}] Parent click attempt: {e}")

            # Fallback: click the CHOOSE text directly + dispatch mousedown
            if not dropdown_opened:
                try:
                    choose.click()
                    page.wait_for_timeout(800)
                    if page.locator("[role='option']").first.is_visible(timeout=1500):
                        dropdown_opened = True
                        log.info(f"  [{attempt}] Dropdown opened via CHOOSE text click")
                except Exception:
                    pass

            if not dropdown_opened:
                try:
                    choose.dispatch_event("mousedown")
                    page.wait_for_timeout(800)
                    if page.locator("[role='option']").first.is_visible(timeout=1500):
                        dropdown_opened = True
                        log.info(f"  [{attempt}] Dropdown opened via mousedown dispatch")
                except Exception:
                    pass

            if not dropdown_opened:
                log.warning(f"  [{attempt}] Could not open CHOOSE dropdown")
                page.wait_for_timeout(500)
                continue

            page.wait_for_timeout(500)

            # Click each desired role option (dropdown stays open for multi-select)
            for role_name in desired_roles:
                selected = False
                try:
                    # Strategy 1: flexible text match (contains, case-insensitive)
                    opt = page.locator("[role='option']").filter(
                        has_text=re.compile(re.escape(role_name), re.IGNORECASE))
                    if opt.first.is_visible(timeout=2000):
                        opt.first.click(timeout=3000)
                        log.info(f"  [{attempt}] Role: '{role_name}' clicked")
                        page.wait_for_timeout(800)
                        selected = True
                except Exception as e:
                    log.info(f"  [{attempt}] Role '{role_name}' click attempt 1: {e}")

                if not selected:
                    # Strategy 2: broader selector (listbox li, menu div)
                    try:
                        broader = page.locator(
                            "[role='option'], [role='listbox'] li, "
                            "[class*='option'], [class*='Option']"
                        ).filter(has_text=re.compile(re.escape(role_name), re.IGNORECASE))
                        if broader.first.is_visible(timeout=1500):
                            broader.first.click(timeout=3000)
                            log.info(f"  [{attempt}] Role: '{role_name}' clicked (broader)")
                            page.wait_for_timeout(800)
                            selected = True
                    except Exception as e:
                        log.info(f"  [{attempt}] Role '{role_name}' click attempt 2: {e}")

                if not selected:
                    # Strategy 3: keyboard navigation — ArrowDown through
                    # options and Enter on match
                    try:
                        log.info(f"  [{attempt}] Role '{role_name}': trying keyboard nav")
                        # Find how many options exist
                        option_count = page.locator("[role='option']").count()
                        for idx in range(min(option_count, 15)):
                            focused = page.locator(
                                "[role='option'][aria-selected='true'], "
                                "[role='option'][data-focused='true'], "
                                "[role='option'].is-focused, "
                                "[role='option']:focus"
                            )
                            # Check current highlighted option text
                            try:
                                focused_text = focused.first.inner_text(timeout=500)
                            except Exception:
                                focused_text = ""
                            if role_name.lower() in focused_text.lower():
                                page.keyboard.press("Enter")
                                log.info(f"  [{attempt}] Role: '{role_name}' selected via Enter")
                                page.wait_for_timeout(800)
                                selected = True
                                break
                            page.keyboard.press("ArrowDown")
                            page.wait_for_timeout(300)

                        if not selected and option_count > 0:
                            # Last resort: press Enter on whatever is highlighted
                            page.keyboard.press("Enter")
                            page.wait_for_timeout(500)
                            log.info(f"  [{attempt}] Role '{role_name}': Enter pressed (keyboard last resort)")
                    except Exception as e:
                        log.warning(f"  [{attempt}] Role '{role_name}' keyboard nav: {e}")

                if not selected:
                    log.warning(f"  [{attempt}] Role '{role_name}' click failed — all strategies exhausted")

            # Click outside to close dropdown
            page.wait_for_timeout(500)
            try:
                page.locator("body").click(position={"x": 10, "y": 10})
            except Exception:
                pass
            page.wait_for_timeout(1000)
        except Exception as e:
            log.warning(f"  [{attempt}] CHOOSE: {e}")
            break


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
        "text=UPLOAD STEREO", "text=Upload Stereo",
        "button:has-text('UPLOAD STEREO')", "button:has-text('Upload Stereo')",
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
            // Real TuneCore React app detection
            hasSongsApp: has('#songs_app'),
            isTracksUrl: url.includes('/tracks'),
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
            // Overview page (after songs, shows Continue link)
            hasSecondaryBtn: visible('a.secondary-btn'),
            bodyClass: document.body.className || '',
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
    if state.get('hasFileInput') and not state.get('hasWriterField') and not state.get('hasSongsApp'):
        return 'upload_wav'
    # TuneCore React songs app on /singles/{id}/tracks or /albums/{id}/tracks
    if state.get('hasSongsApp') or (state.get('isTracksUrl') and not state.get('isDashboard')):
        return 'track_details'
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
        # Track repeated visits to same page to detect stuck loops
        page_visit_counts = {}

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
                try:
                    page.screenshot(path=f"output/tunecore_{step:02d}.png")
                except Exception:
                    pass
                state = _detect_page(page)
                page_visit_counts[state] = page_visit_counts.get(state, 0) + 1
                log.info(f"{'='*50}")
                log.info(f"[{step}] Page state: {state} (visit #{page_visit_counts[state]})")
                log.info(f"{'='*50}")

                # Detect stuck loop — if we visit the same page 4+ times, force skip
                if page_visit_counts[state] >= 4 and state not in ('done', 'unknown'):
                    log.error(f"  STUCK on '{state}' after {page_visit_counts[state]} visits!")
                    log.error("  Taking debug screenshot and forcing Continue...")
                    try:
                        page.screenshot(path=f"output/tunecore_stuck_{state}.png")
                        _dump_page_state(page, f"STUCK on {state}")
                    except Exception:
                        pass
                    # Try to click Continue/Next to force-advance
                    skip_btn = _find_clickable(page, [
                        "a.secondary-btn", "a:has-text('Continue')",
                        "button:has-text('Continue')", "button:has-text('Next')",
                        "button:has-text('Skip')",
                    ])
                    if skip_btn:
                        skip_btn.click()
                        log.info("  Forced Continue click to break stuck loop")
                        page.wait_for_timeout(5000)
                    continue

                try:
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
                    elif state == 'add_track':
                        try:
                            _dump_page_state(page, "Add Track — before")

                            # If no WAV file, skip and try to continue
                            if not wav_path.exists() or str(wav_path) == '/dev/null':
                                log.info("  Add Track step — no WAV file, skipping...")
                                cont = _find_clickable(page, [
                                    "a.secondary-btn", "a:has-text('Continue')",
                                    "button:has-text('Continue')",
                                ])
                                if cont:
                                    cont.click()
                                    page.wait_for_timeout(5000)
                                continue

                            log.info(f"  Uploading WAV via Add Track: {wav_path.name}")
                            btn = _find_clickable(page, [
                                "text=Add Track", "button:has-text('Add Track')",
                                "a:has-text('Add Track')", "text=Add track",
                                "text=ADD TRACK",
                            ])
                            if btn:
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
                                    try:
                                        btn.click()
                                        page.wait_for_timeout(2000)
                                        uploaded = _upload_file(page, wav_path)
                                    except Exception:
                                        pass

                                if not uploaded:
                                    log.warning("  WAV upload failed — skipping...")
                                else:
                                    log.info("  WAV uploading — waiting 1 min for processing...")
                                    page.wait_for_timeout(60_000)
                                    _dump_page_state(page, "Add Track — after 1 min wait")
                        except Exception as e:
                            log.warning(f"  Add Track step failed: {e} — skipping...")

                    # ── TRACK DETAILS (smart fill) ──
                    # TuneCore React app #songs_app on /singles/{id}/tracks
                    # Real DOM (from HTML source): jQuery + React, NOT Material UI.
                    # data-songs JSON has current state: explicit, instrumental, etc.
                    # Sections: Song Title, Songwriter*, Song Artists & Creatives,
                    #   Performing Artists*, Producers & Engineers*, Copyright Ownership*,
                    #   Instrumental, Explicit, ISRC, Language, Lyrics, TikTok
                    # Smart: reads data-songs + DOM to detect what's filled.
                    elif state == 'track_details':
                        log.info("  Filling track details (AGGRESSIVE — fill everything)...")
                        _dump_page_state(page, "Track Details — before fill")

                        # Wait for React #songs_app to render
                        try:
                            page.wait_for_selector('#songs_app', timeout=15_000)
                            page.wait_for_timeout(3000)
                        except Exception:
                            page.wait_for_timeout(5000)

                        # ── 1. Song Title — skip if already filled ──
                        for sel in [
                            "input[name*='title' i]", "input[name*='trackName' i]",
                            "input[name*='song_name' i]", "input[name*='songName' i]",
                        ]:
                            try:
                                el = page.locator(sel).first
                                if el.is_visible(timeout=1500):
                                    current = el.input_value().strip()
                                    if current:
                                        log.info(f"  Song Title: already '{current}', skipping")
                                    else:
                                        el.fill(concept.track_name)
                                        log.info(f"  Song Title: '{concept.track_name}'")
                                    break
                            except Exception:
                                continue

                        # ── 2. Songwriter — Playwright locator fill (NOT JS focus) ──
                        try:
                            sw_el = page.locator('input[placeholder*="Legal First"]').first
                            if sw_el.is_visible(timeout=3000):
                                sw_val = sw_el.input_value()
                                if sw_val.strip():
                                    log.info(f"  Songwriter: already '{sw_val}'")
                                else:
                                    sw_el.scroll_into_view_if_needed(timeout=2000)

                                    # Method 1: Playwright click + fill (best React compat)
                                    sw_el.click()
                                    page.wait_for_timeout(500)
                                    sw_el.fill(artist)
                                    page.wait_for_timeout(500)
                                    page.keyboard.press("Tab")
                                    page.wait_for_timeout(800)

                                    sw_check = sw_el.input_value()
                                    if sw_check.strip():
                                        log.info(f"  Songwriter: '{sw_check}' (Playwright fill)")
                                    else:
                                        # Method 2: press_sequentially — char by char, fires all events
                                        log.info("  Songwriter fill didn't stick, trying press_sequentially...")
                                        sw_el.click()
                                        page.wait_for_timeout(300)
                                        sw_el.press_sequentially(artist, delay=60)
                                        page.wait_for_timeout(500)
                                        page.keyboard.press("Tab")
                                        page.wait_for_timeout(800)

                                        sw_check = sw_el.input_value()
                                        if sw_check.strip():
                                            log.info(f"  Songwriter: '{sw_check}' (press_sequentially)")
                                        else:
                                            # Method 3: React native value setter as last resort
                                            log.info("  Songwriter press_sequentially didn't stick, trying native setter...")
                                            page.evaluate("""(name) => {
                                                const inp = document.querySelector('input[placeholder*="Legal First"]');
                                                if (!inp) return;
                                                const setter = Object.getOwnPropertyDescriptor(
                                                    HTMLInputElement.prototype, 'value').set;
                                                setter.call(inp, name);
                                                inp.dispatchEvent(new Event('input', {bubbles: true}));
                                                inp.dispatchEvent(new Event('change', {bubbles: true}));
                                                inp.dispatchEvent(new Event('blur', {bubbles: true}));
                                            }""", artist)
                                            page.wait_for_timeout(500)
                                            log.info(f"  Songwriter: native setter applied '{artist}'")
                            else:
                                log.warning("  Songwriter: input not visible")
                        except Exception as e:
                            log.warning(f"  Songwriter failed: {e}")
                        page.wait_for_timeout(1000)

                        # ── 3. Fill ALL empty "Add Artist/Creative" inputs ──
                        # Direct approach: find empty inputs by placeholder, fill one at a time
                        # and re-scan (DOM changes after each autocomplete pick)
                        for fill_round in range(6):
                            filled_any = False
                            try:
                                empty_arts = page.locator(
                                    'input[placeholder*="Artist/Creative"], '
                                    'input[placeholder*="Add Artist"]'
                                )
                                art_count = empty_arts.count()
                                log.info(f"  Artist round {fill_round}: {art_count} inputs found")

                                for i in range(art_count):
                                    try:
                                        inp = empty_arts.nth(i)
                                        if not inp.is_visible(timeout=500):
                                            continue
                                        val = inp.input_value()
                                        if val.strip():
                                            continue

                                        log.info(f"  Artist [{i}]: empty, filling '{artist}'...")
                                        inp.scroll_into_view_if_needed(timeout=2000)
                                        inp.click()
                                        page.wait_for_timeout(500)
                                        inp.fill("")
                                        page.wait_for_timeout(200)
                                        inp.press_sequentially(artist, delay=80)
                                        page.wait_for_timeout(2500)

                                        # Pick from autocomplete dropdown
                                        picked = False
                                        try:
                                            opt = page.locator(
                                                "[role='option'], [id*='option'], [class*='option']"
                                            ).filter(has_text=artist).first
                                            if opt.is_visible(timeout=2500):
                                                opt.click()
                                                log.info(f"  Artist [{i}]: '{artist}' from dropdown")
                                                picked = True
                                        except Exception:
                                            pass
                                        if not picked:
                                            page.keyboard.press("ArrowDown")
                                            page.wait_for_timeout(300)
                                            page.keyboard.press("Enter")
                                            log.info(f"  Artist [{i}]: keyboard fallback")

                                        page.wait_for_timeout(1500)
                                        filled_any = True
                                        break  # Re-scan after each fill (DOM changes)
                                    except Exception as e:
                                        log.warning(f"  Artist [{i}] failed: {e}")
                                        continue
                            except Exception as e:
                                log.warning(f"  Artist round {fill_round} error: {e}")

                            if not filled_any:
                                log.info(f"  No more empty artist inputs (round {fill_round})")
                                break
                        page.wait_for_timeout(1000)

                        # ── 4. Fill ALL role dropdowns showing CHOOSE ──
                        # Simple approach: find CHOOSE text, click to open, pick option
                        _fill_choose_sections(page, artist)
                        page.wait_for_timeout(500)

                        # ── 5. Copyright → No ──
                        copyright_done = False

                        # Method 1: Direct ID selector
                        try:
                            radio = page.locator("#song-cover-song-metadata-cover-song-no")
                            radio.scroll_into_view_if_needed(timeout=3000)
                            radio.check(timeout=3000)
                            log.info("  Copyright No: checked by exact ID")
                            copyright_done = True
                        except Exception as e:
                            log.info(f"  Copyright No ID fail: {e}")

                        # Method 2: By name + value
                        if not copyright_done:
                            try:
                                radio = page.locator("input[name='cover_song'][value='No']")
                                radio.check(timeout=2000)
                                log.info("  Copyright No: checked by name+value")
                                copyright_done = True
                            except Exception as e:
                                log.info(f"  Copyright No name+val fail: {e}")

                        # Method 3: JS direct
                        if not copyright_done:
                            cr = page.evaluate("""() => {
                                let el = document.getElementById(
                                    'song-cover-song-metadata-cover-song-no');
                                if (!el) el = document.querySelector(
                                    'input[name="cover_song"][value="No"]');
                                if (!el) {
                                    const radios = document.querySelectorAll('input[type="radio"]');
                                    for (const r of radios) {
                                        if (r.value === 'No' || r.value === 'no') { el = r; break; }
                                    }
                                }
                                if (el) {
                                    el.checked = true;
                                    el.click();
                                    el.dispatchEvent(new Event('change', {bubbles:true}));
                                    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                                        window.HTMLInputElement.prototype, 'checked').set;
                                    nativeInputValueSetter.call(el, true);
                                    el.dispatchEvent(new Event('change', {bubbles:true}));
                                    return 'CLICKED:' + el.id;
                                }
                                return 'NOT_FOUND';
                            }""")
                            log.info(f"  Copyright No JS: {cr}")
                            if cr and cr.startswith("CLICKED:"):
                                copyright_done = True

                        # Method 4: Click the <label> element
                        if not copyright_done:
                            try:
                                lbl = page.locator(
                                    "label.song-cover-song-metadata-cover-song"
                                ).filter(has_text="No").first
                                lbl.click(timeout=2000)
                                log.info("  Copyright No: label click")
                            except Exception as e:
                                log.info(f"  Copyright No label fail: {e}")

                        page.wait_for_timeout(500)

                        # ── 6. Instrumental checkbox ──
                        try:
                            instr_label = page.locator('label').filter(has_text='Instrumental').first
                            if instr_label.is_visible(timeout=2000):
                                instr_label.scroll_into_view_if_needed(timeout=2000)
                                cb = instr_label.locator('input[type="checkbox"]').first
                                try:
                                    if not cb.is_checked(timeout=1000):
                                        instr_label.click()
                                        page.wait_for_timeout(500)
                                        log.info("  Instrumental: CHECKED via Playwright")
                                    else:
                                        log.info("  Instrumental: already checked")
                                except Exception:
                                    instr_label.click()
                                    page.wait_for_timeout(500)
                                    log.info("  Instrumental: clicked label (fallback)")
                            else:
                                # JS fallback
                                instr = page.evaluate("""() => {
                                    for (const cb of document.querySelectorAll('input[type=checkbox]')) {
                                        const lbl = cb.closest('label') || cb.parentElement;
                                        if (lbl && lbl.textContent.toLowerCase().includes('instrumental')) {
                                            if (!cb.checked) { cb.click(); return 'CHECKED_JS'; }
                                            return 'ALREADY';
                                        }
                                    }
                                    return 'NOT_FOUND';
                                }""")
                                log.info(f"  Instrumental: {instr}")
                        except Exception as e:
                            log.warning(f"  Instrumental failed: {e}")
                        page.wait_for_timeout(500)

                        # ── 7. Explicit lyrics → No ──
                        try:
                            # Playwright: find "No" button near "explicit" text
                            no_buttons = page.locator('button').filter(has_text='No')
                            no_count = no_buttons.count()
                            explicit_clicked = False
                            for i in range(no_count):
                                try:
                                    btn = no_buttons.nth(i)
                                    if not btn.is_visible(timeout=500):
                                        continue
                                    # Check parent/grandparent contains "explicit"
                                    parent_text = btn.locator('xpath=../..').inner_text(timeout=1000)
                                    if 'explicit' in parent_text.lower():
                                        btn.click()
                                        page.wait_for_timeout(500)
                                        log.info("  Explicit: clicked No (Playwright)")
                                        explicit_clicked = True
                                        break
                                except Exception:
                                    continue
                            if not explicit_clicked:
                                # JS fallback: click "No" button near "explicit" context
                                result = page.evaluate("""() => {
                                    const btns = [...document.querySelectorAll('button')];
                                    for (const btn of btns) {
                                        if (btn.textContent.trim().toLowerCase() !== 'no') continue;
                                        if (btn.offsetWidth === 0) continue;
                                        let node = btn.parentElement;
                                        for (let i = 0; i < 6 && node; i++) {
                                            if (node.textContent.toLowerCase().includes('explicit')) {
                                                btn.click();
                                                return 'CLICKED_NO_JS';
                                            }
                                            node = node.parentElement;
                                        }
                                    }
                                    return 'NOT_FOUND';
                                }""")
                                log.info(f"  Explicit: {result}")
                        except Exception as e:
                            log.warning(f"  Explicit failed: {e}")

                        page.wait_for_timeout(2000)

                        # ── 8. FINAL SCAN — check ALL empty required fields before Save ──
                        empty_scan = page.evaluate("""(artist) => {
                            const problems = [];
                            // Check songwriter
                            const sw = document.querySelector('input[placeholder*="Legal First"]');
                            if (sw && !sw.value.trim()) problems.push('songwriter');
                            // Check all inputs with placeholder containing Artist/Creative
                            const artInputs = document.querySelectorAll(
                                'input[placeholder*="Artist" i], input[placeholder*="Creative" i]'
                            );
                            let emptyArtist = 0;
                            for (const inp of artInputs) {
                                if (inp.offsetWidth > 0 && !inp.value.trim()) emptyArtist++;
                            }
                            if (emptyArtist > 0) problems.push('artist_inputs:' + emptyArtist);
                            // Check role dropdowns showing CHOOSE (multiple selectors)
                            const roleSels = [
                                '.artist-song-role-select',
                                '[class*="role-select"]',
                                '[class*="roleSelect"]',
                                '[data-tc-role-select]',
                            ];
                            let emptyRoles = 0;
                            const checkedRoles = new Set();
                            for (const sel of roleSels) {
                                for (const r of document.querySelectorAll(sel)) {
                                    if (checkedRoles.has(r)) continue;
                                    checkedRoles.add(r);
                                    // Multi-select: check for chips (multiValue) — if present, role is filled
                                    const mv = r.querySelector('[class*="multiValue"], [class*="multi-value"]');
                                    if (mv) continue;  // has selected chip(s), not empty
                                    const ph = r.querySelector('[class*="placeholder"]');
                                    const sv = r.querySelector('[class*="singleValue"], [class*="single-value"]');
                                    const text = (sv ? sv.textContent : r.textContent).trim();
                                    if (ph || /choose/i.test(text) || !text) emptyRoles++;
                                }
                            }
                            if (emptyRoles > 0) problems.push('roles:' + emptyRoles);
                            // Check validation message
                            const body = document.body.innerText.toLowerCase();
                            if (body.includes('required before saving')) problems.push('validation_msg');
                            return problems;
                        }""", artist)
                        log.info(f"  Pre-save scan: {empty_scan if empty_scan else 'ALL FIELDS OK'}")

                        # ── Retry empty fields up to 2 more times ──
                        for retry in range(2):
                            if not empty_scan:
                                break
                            log.info(f"  --- RETRY {retry + 1}: fixing {empty_scan} ---")

                            # Retry songwriter
                            if any('songwriter' in p for p in empty_scan):
                                log.info("  Songwriter STILL empty — retrying...")
                                try:
                                    sw_el = page.locator('input[placeholder*="Legal First"]').first
                                    sw_el.scroll_into_view_if_needed(timeout=2000)
                                    sw_el.click(timeout=2000)
                                    page.wait_for_timeout(300)
                                    sw_el.fill(artist)
                                    page.wait_for_timeout(500)
                                    page.keyboard.press("Tab")
                                    page.wait_for_timeout(500)
                                    # Verify
                                    val = sw_el.input_value()
                                    if not val.strip():
                                        sw_el.click()
                                        page.wait_for_timeout(200)
                                        sw_el.press_sequentially(artist, delay=50)
                                        page.keyboard.press("Tab")
                                    log.info(f"  Songwriter retry: '{sw_el.input_value()}'")
                                except Exception as e:
                                    log.warning(f"  Songwriter retry failed: {e}")
                                page.wait_for_timeout(1000)

                            # Retry empty artist inputs
                            if any('artist_inputs' in p for p in empty_scan):
                                log.info("  Artist inputs STILL empty — retrying...")
                                try:
                                    empty_arts = page.locator(
                                        'input[placeholder*="Artist/Creative"], '
                                        'input[placeholder*="Add Artist"]'
                                    )
                                    for i in range(empty_arts.count()):
                                        inp = empty_arts.nth(i)
                                        if not inp.is_visible(timeout=500):
                                            continue
                                        if inp.input_value().strip():
                                            continue
                                        inp.scroll_into_view_if_needed(timeout=2000)
                                        inp.click()
                                        page.wait_for_timeout(500)
                                        inp.press_sequentially(artist, delay=80)
                                        page.wait_for_timeout(2000)
                                        # Pick from autocomplete
                                        try:
                                            opt = page.locator("[role='option']").filter(
                                                has_text=artist).first
                                            if opt.is_visible(timeout=2000):
                                                opt.click()
                                            else:
                                                page.keyboard.press("ArrowDown")
                                                page.wait_for_timeout(200)
                                                page.keyboard.press("Enter")
                                        except Exception:
                                            page.keyboard.press("ArrowDown")
                                            page.wait_for_timeout(200)
                                            page.keyboard.press("Enter")
                                        page.wait_for_timeout(1500)
                                        break
                                except Exception as e:
                                    log.warning(f"  Artist retry failed: {e}")

                            # Retry empty roles using simple CHOOSE-click approach
                            if any('roles' in p for p in empty_scan):
                                log.info("  Roles STILL showing CHOOSE — retrying...")
                                _fill_choose_sections(page, artist)

                            page.wait_for_timeout(2000)

                            # Re-scan
                            empty_scan = page.evaluate("""(artist) => {
                                const problems = [];
                                const sw = document.querySelector('input[placeholder*="Legal First"]');
                                if (sw && !sw.value.trim()) problems.push('songwriter');
                                const artInputs = document.querySelectorAll(
                                    'input[placeholder*="Artist" i], input[placeholder*="Creative" i]'
                                );
                                let emptyArtist = 0;
                                for (const inp of artInputs) {
                                    if (inp.offsetWidth > 0 && !inp.value.trim()) emptyArtist++;
                                }
                                if (emptyArtist > 0) problems.push('artist_inputs:' + emptyArtist);
                                // Check role dropdowns with multiple selectors
                                const roleSels = [
                                    '.artist-song-role-select',
                                    '[class*="role-select"]',
                                    '[class*="roleSelect"]',
                                    '[data-tc-role-select]',
                                    '[data-tc-role-retry]',
                                ];
                                let emptyRoles = 0;
                                let checkedRoles = new Set();
                                for (const sel of roleSels) {
                                    for (const r of document.querySelectorAll(sel)) {
                                        if (checkedRoles.has(r)) continue;
                                        checkedRoles.add(r);
                                        // Multi-select: check for chips (multiValue) — if present, role is filled
                                        const mv = r.querySelector('[class*="multiValue"], [class*="multi-value"]');
                                        if (mv) continue;
                                        const ph = r.querySelector('[class*="placeholder"]');
                                        const sv = r.querySelector('[class*="singleValue"], [class*="single-value"]');
                                        const text = (sv ? sv.textContent : r.textContent).trim();
                                        if (ph || /choose/i.test(text) || !text) emptyRoles++;
                                    }
                                }
                                if (emptyRoles > 0) problems.push('roles:' + emptyRoles);
                                return problems;
                            }""", artist)
                            log.info(f"  Re-scan after retry {retry + 1}: {empty_scan if empty_scan else 'ALL OK'}")

                        _dump_page_state(page, "Track Details — after fill")

                        # ── SAVE (within the React form) ──
                        save = _find_clickable(page, [
                            "button:has-text('Save')", "button[type='submit']:has-text('Save')",
                            "#songs_app button:has-text('Save')",
                        ])
                        if save:
                            save.click()
                            log.info("  Clicked Save — waiting for response...")
                            page.wait_for_timeout(5000)

                            # Check if save succeeded or validation errors appeared
                            save_ok = page.evaluate("""() => {
                                const body = document.body.innerText.toLowerCase();
                                if (body.includes('required before saving')) return 'VALIDATION_ERROR';
                                if (body.includes('error')) return 'ERROR';
                                return 'OK';
                            }""")
                            log.info(f"  Save result: {save_ok}")

                            if save_ok == 'VALIDATION_ERROR':
                                log.warning("  Save failed — validation errors still present!")
                                log.info("  Taking screenshot of validation failure...")
                                try:
                                    page.screenshot(path="output/tunecore_validation_fail.png")
                                except Exception:
                                    pass
                                # Wait a bit and continue — the adaptive loop will retry
                                page.wait_for_timeout(3000)
                            else:
                                log.info("  Save appears successful — waiting 5s more...")
                                page.wait_for_timeout(5000)

                        # ── CONTINUE (a.secondary-btn link at bottom of page) ──
                        cont = _find_clickable(page, [
                            "a.secondary-btn",
                            "a:has-text('Continue')",
                            "button:has-text('Continue')",
                        ])
                        if cont:
                            cont.click()
                            log.info("  Clicked Continue after track details")
                            page.wait_for_timeout(5000)

                    # ── UPLOAD WAV ──
                    elif state == 'upload_wav':
                        try:
                            if not wav_path.exists() or str(wav_path) == '/dev/null':
                                log.info("  WAV upload step — no file provided, skipping (draft mode)")
                                cont = _find_clickable(page, [
                                    "a.secondary-btn", "a:has-text('Continue')",
                                    "button:has-text('Continue')", "button:has-text('Next')",
                                ])
                                if cont:
                                    cont.click()
                                    page.wait_for_timeout(5000)
                                continue
                            log.info(f"  Uploading WAV: {wav_path.name}")
                            _dump_page_state(page, "Before WAV Upload")

                            # Click "UPLOAD STEREO" button first to open file chooser
                            stereo_btn = _find_clickable(page, [
                                "text=UPLOAD STEREO",
                                "text=Upload Stereo",
                                "button:has-text('UPLOAD STEREO')",
                                "button:has-text('Upload Stereo')",
                                "a:has-text('UPLOAD STEREO')",
                                "[class*='upload' i]:has-text('Stereo')",
                            ])
                            if stereo_btn:
                                log.info("  Found 'UPLOAD STEREO' button — clicking...")
                                try:
                                    with page.expect_file_chooser(timeout=10000) as fc_info:
                                        stereo_btn.click()
                                    file_chooser = fc_info.value
                                    file_chooser.set_files(str(wav_path))
                                    log.info(f"  WAV selected via UPLOAD STEREO file chooser: {wav_path.name}")
                                    wav_ok = True
                                except Exception as e:
                                    log.warning(f"  UPLOAD STEREO file chooser failed: {e} — falling back to _upload_file")
                                    wav_ok = _upload_file(page, wav_path)
                            else:
                                log.info("  'UPLOAD STEREO' button not found — using generic _upload_file")
                                wav_ok = _upload_file(page, wav_path)
                            if not wav_ok:
                                log.warning(f"  WAV upload failed for '{wav_path.name}' — skipping...")
                                continue
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
                        except Exception as e:
                            log.warning(f"  Upload WAV step failed: {e} — skipping...")

                    # ── ARTWORK ──
                    elif state == 'artwork':
                        try:
                            if not cover_path.exists() or str(cover_path) == '/dev/null':
                                log.info("  Artwork step — no file provided, skipping (draft mode)")
                                cont = _find_clickable(page, [
                                    "a.secondary-btn", "a:has-text('Continue')",
                                    "button:has-text('Continue')", "button:has-text('Next')",
                                ])
                                if cont:
                                    cont.click()
                                    page.wait_for_timeout(5000)
                                continue
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
                                log.warning(f"  Cover upload failed for '{cover_path.name}' — skipping...")
                                continue
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
                        except Exception as e:
                            log.warning(f"  Artwork step failed: {e} — skipping...")

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

                except Exception as _step_err:
                    log.warning(f"  Step {step} ({state}) failed: {_step_err}")
                    log.warning("  Skipping this step, moving on...")
                    page.wait_for_timeout(3000)

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
