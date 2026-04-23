"""Upload a single track to TuneCore for distribution (Playwright automation).

TuneCore requires:
  - WAV file (stereo, 16-bit, 44.1kHz+)
  - Cover art: 1600x1600 minimum (JPEG or PNG)
  - Metadata: title, artist, genre, songwriter, etc.

Flow (web.tunecore.com):
  1. Dashboard -> navigate to /singles/new (creates a new Single directly)
  2. Click "Start" (if shown)
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


def _strip_emojis(text: str) -> str:
    """Remove emoji characters from text (TuneCore rejects them)."""
    return re.sub(
        r'[\U00010000-\U0010ffff\u2600-\u27BF\u2300-\u23FF'
        r'\u2B50\u2B55\u25AA-\u25FE\u2934-\u2935\u3030\u303D'
        r'\uFE0F\u200D]+', '', text
    ).strip()


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

    # Look for local WAV — by track name first, then latest in output/
    wav_path = None
    for name in name_variants:
        for ext in [".wav", ".WAV"]:
            candidate = OUTPUT_DIR / f"{name}{ext}"
            if candidate.exists():
                wav_path = candidate
                log.info(f"Found WAV by name: {wav_path}")
                break
        if wav_path:
            break

    # Fallback: pick the most recently modified WAV in output/
    if not wav_path:
        all_wavs = sorted(OUTPUT_DIR.glob("*.wav"), key=lambda f: f.stat().st_mtime, reverse=True)
        all_wavs += sorted(OUTPUT_DIR.glob("*.WAV"), key=lambda f: f.stat().st_mtime, reverse=True)
        if all_wavs:
            wav_path = all_wavs[0]
            log.info(f"WAV not found by name — using latest: {wav_path}")

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


def _fill_new_ui_autocomplete(page, section_label: str, value: str) -> bool:
    """Fill a MUI Autocomplete in the 2026 UI by finding the section heading."""
    found = page.evaluate("""(args) => {
        const { label, value } = args;
        const headings = document.querySelectorAll(
            'h1,h2,h3,h4,h5,h6,legend,label,span,div,p,strong');
        for (const h of headings) {
            const t = h.textContent.trim();
            if (h.offsetWidth === 0 || t.length > 50) continue;
            let match = false;
            if (/songwriter/i.test(label) && /^Songwriter/i.test(t)) match = true;
            if (/artist/i.test(label) && /Artist.*Contributor|Artist.*Creative|^Artist.*Name/i.test(t)) match = true;
            if (!match) continue;
            const section = h.closest(
                'fieldset, section, .MuiFormControl-root, .MuiGrid-root, .MuiBox-root'
            ) || h.parentElement?.parentElement || h.parentElement;
            if (!section) continue;
            const inputs = section.querySelectorAll(
                'input[type="text"], input:not([type]), input[role="combobox"]');
            for (const inp of inputs) {
                if (inp.offsetWidth === 0 || inp.type === 'hidden') continue;
                if (inp.value.trim()) return { status: 'filled', value: inp.value.trim() };
                inp.setAttribute('data-tc-auto-fill', 'true');
                return { status: 'empty' };
            }
        }
        // Fallback: direct placeholder match
        if (/songwriter/i.test(label)) {
            const inp = document.querySelector(
                'input[placeholder*="Legal First"], input[placeholder*="Last Name"]');
            if (inp && inp.offsetWidth > 0) {
                if (inp.value.trim()) return { status: 'filled', value: inp.value.trim() };
                inp.setAttribute('data-tc-auto-fill', 'true');
                return { status: 'empty' };
            }
        }
        if (/artist/i.test(label)) {
            const inp = document.querySelector(
                'input[placeholder*="Artist/Contributor"], '
              + 'input[placeholder*="Add Artist"], '
              + 'input[name*="artistContributor" i]');
            if (inp && inp.offsetWidth > 0) {
                if (inp.value.trim()) return { status: 'filled', value: inp.value.trim() };
                inp.setAttribute('data-tc-auto-fill', 'true');
                return { status: 'empty' };
            }
        }
        // Fallback: MUI Autocomplete roots
        const autos = document.querySelectorAll('.MuiAutocomplete-root');
        for (const ac of autos) {
            const lbl = (ac.querySelector('label') || ac.previousElementSibling);
            const lt = (lbl?.textContent || '').trim().toLowerCase();
            if (/songwriter/i.test(label) && lt.includes('songwriter')) {
                const inp = ac.querySelector('input');
                if (inp && inp.offsetWidth > 0) {
                    if (inp.value.trim()) return { status: 'filled', value: inp.value.trim() };
                    inp.setAttribute('data-tc-auto-fill', 'true');
                    return { status: 'empty' };
                }
            }
            if (/artist/i.test(label) && (lt.includes('artist') || lt.includes('creative'))) {
                const inp = ac.querySelector('input');
                if (inp && inp.offsetWidth > 0) {
                    if (inp.value.trim()) return { status: 'filled', value: inp.value.trim() };
                    inp.setAttribute('data-tc-auto-fill', 'true');
                    return { status: 'empty' };
                }
            }
        }
        return { status: 'not_found' };
    }""", {"label": section_label, "value": value})

    if not found or found.get('status') == 'not_found':
        log.warning(f"  {section_label}: input not found")
        return False
    if found.get('status') == 'filled':
        log.info(f"  {section_label}: already '{found.get('value')}'")
        return True

    try:
        inp = page.locator('[data-tc-auto-fill="true"]').first
        inp.scroll_into_view_if_needed(timeout=2000)
        inp.click()
        page.wait_for_timeout(500)
        inp.fill("")
        page.wait_for_timeout(200)
        inp.type(value, delay=80)
        page.wait_for_timeout(2500)

        picked = False
        try:
            opt = page.locator("[role='option']").filter(has_text=value).first
            if opt.is_visible(timeout=3000):
                opt.click()
                picked = True
                log.info(f"  {section_label}: '{value}' (autocomplete)")
        except Exception:
            pass

        if not picked:
            page.keyboard.press("ArrowDown")
            page.wait_for_timeout(300)
            page.keyboard.press("Enter")
            page.wait_for_timeout(500)
            log.info(f"  {section_label}: '{value}' (keyboard)")

        page.wait_for_timeout(1000)
        return True
    except Exception as e:
        log.warning(f"  {section_label}: fill failed: {e}")
        return False
    finally:
        try:
            page.evaluate(
                "document.querySelectorAll('[data-tc-auto-fill]')"
                ".forEach(el => el.removeAttribute('data-tc-auto-fill'))")
        except Exception:
            pass


def _fill_new_ui_track(page, concept, artist, wav_path):
    """Handle the TuneCore 2026 track details page (#tracks-form-root).

    The 2026 redesign uses a Vite-bundled React app mounted on #tracks-form-root
    with MUI components. Flow:
      1. Fill songwriter + artist/creative via MUI Autocomplete
      2. Select performer roles, producer roles, more options (multi-select)
      3. Set radio buttons: release history=No, cover=No, lyrics=instrumental
      4. Click "Save Track Info" → enables WAV upload (uploadable: false → true)
      5. Upload WAV if area becomes available
      6. Click "Save & Continue" to advance
    """
    log.info("  === NEW UI (#tracks-form-root) ===")
    clean_name = _strip_emojis(concept.track_name)

    app_state = page.evaluate("""() => {
        const root = document.querySelector('#tracks-form-root');
        if (!root) return null;
        try {
            const props = JSON.parse(root.getAttribute('data-props') || '{}');
            const song = (props.songs || [])[0] || {};
            return {
                songId: song.id,
                songName: song.name || '',
                hasSongwriters: (song.songwriters || []).length > 0,
                hasCreatives: (song.creatives || []).length > 0,
                instrumental: song.instrumental,
                coverSong: song.cover_song,
                previouslyReleased: song.previously_released,
                uploadable: song.uploadable || false,
                hasAsset: !!song.asset,
            };
        } catch(e) { return { error: e.message }; }
    }""")

    if app_state:
        log.info(f"  React state: id={app_state.get('songId')} "
                 f"name='{app_state.get('songName')}' "
                 f"sw={app_state.get('hasSongwriters')} "
                 f"cr={app_state.get('hasCreatives')} "
                 f"upload={app_state.get('uploadable')} "
                 f"asset={app_state.get('hasAsset')}")

    # ── 1. Song Name (usually pre-filled from step 1) ──
    for sel in ["input[name*='name' i]", "input[name*='title' i]",
                "input[name*='trackName' i]", "input[name*='song_name' i]"]:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=1500):
                current = el.input_value().strip()
                if current:
                    log.info(f"  Song Name: already '{current}'")
                else:
                    el.fill(clean_name)
                    log.info(f"  Song Name: '{clean_name}'")
                break
        except Exception:
            continue

    # ── 2. Songwriter (MUI Autocomplete with account_songwriters) ──
    if not app_state or not app_state.get('hasSongwriters'):
        _fill_new_ui_autocomplete(page, "Songwriter", artist)
    else:
        log.info("  Songwriter: already has entries (from React state)")
    page.wait_for_timeout(1000)

    # ── 3. Artist/Creative (MUI Autocomplete with active_creatives) ──
    if not app_state or not app_state.get('hasCreatives'):
        _fill_new_ui_autocomplete(page, "Artist", artist)
    else:
        log.info("  Artist/Creative: already has entries (from React state)")
    page.wait_for_timeout(1000)

    # ── 4. Performer Roles, Producer/Engineer, More Options, Radio buttons ──
    _fill_new_track_fields(page)
    page.wait_for_timeout(1000)

    # ── 5. Click "SAVE" (not "SAVE & CONTINUE") ──
    save_clicked = page.evaluate("""() => {
        const btns = document.querySelectorAll('button, input[type="submit"]');
        for (const b of btns) {
            const t = (b.textContent || b.value || '').trim();
            if (b.offsetWidth === 0 || b.disabled) continue;
            if (b.getAttribute('aria-disabled') === 'true') continue;
            // Match "Save Track Info" or plain "SAVE" but NOT "SAVE & CONTINUE"
            if (/^Save\\s*Track\\s*Info$/i.test(t)) { b.click(); return 'Save Track Info'; }
            if (/^Save$/i.test(t)) { b.click(); return 'Save'; }
        }
        return null;
    }""")
    if save_clicked:
        log.info(f"  Clicked '{save_clicked}'")
        page.wait_for_timeout(5000)
    else:
        log.warning("  SAVE button not found or disabled")
        # Playwright fallback
        for btn_text in ['Save Track Info', 'Save']:
            try:
                btn = page.get_by_role("button", name=btn_text, exact=True).first
                if btn.is_visible(timeout=2000):
                    btn.scroll_into_view_if_needed(timeout=2000)
                    btn.click()
                    log.info(f"  Clicked '{btn_text}' (Playwright)")
                    save_clicked = btn_text
                    page.wait_for_timeout(5000)
                    break
            except Exception:
                continue

    # ── 6. Upload WAV (if file exists and upload area becomes available) ──
    if wav_path and wav_path.exists() and str(wav_path) != '/dev/null':
        page.wait_for_timeout(3000)
        upload_available = page.evaluate("""() => {
            const fi = document.querySelector('input[type="file"]');
            if (fi) return 'file_input';
            const els = document.querySelectorAll(
                'button, label, div, [class*="upload" i], [class*="dropzone" i]');
            for (const el of els) {
                const t = (el.textContent || '').trim().toLowerCase();
                if ((t.includes('upload') && t.includes('stereo'))
                    || t.includes('add audio')) {
                    if (el.offsetWidth > 0) return 'upload_btn';
                }
            }
            return null;
        }""")

        if upload_available:
            log.info(f"  Upload area available ({upload_available}), uploading WAV...")
            wav_ok = _upload_file(page, wav_path)
            if wav_ok:
                log.info("  WAV uploaded, waiting for processing...")
                _wait_for_upload(page, timeout=360, file_was_set=True)
            else:
                log.warning("  WAV upload failed on new UI page")
        else:
            log.info("  Upload area not available yet (uploadable still false)")

    # ── 7. Click "Save & Continue" ──
    page.wait_for_timeout(2000)
    for btn_text in ['Save & Continue', 'Save and Continue', 'Continue']:
        try:
            btn = page.locator(f"button:has-text('{btn_text}')").first
            if btn.is_visible(timeout=2000):
                disabled = btn.evaluate(
                    "el => el.disabled || el.getAttribute('aria-disabled') === 'true'"
                    " || el.classList.contains('Mui-disabled')")
                if not disabled:
                    btn.scroll_into_view_if_needed(timeout=2000)
                    btn.click()
                    log.info(f"  Clicked '{btn_text}'")
                    page.wait_for_timeout(5000)
                    break
                else:
                    log.info(f"  '{btn_text}' is disabled — may need upload first")
        except Exception:
            continue


def _fill_new_track_fields(page):
    """Fill TuneCore 2026 UI fields: Performer Roles, Producer/Engineer Roles,
    Release History, Copyright Ownership, and Lyrics radio buttons.

    The April-2026 TuneCore redesign moved these into step 3/4 as
    separate MUI sections with dropdowns and radio groups.

    DOM structure (from HTML source):
      Performer Roles: MUI Select → <ul role="listbox" aria-labelledby="songRoles.performer">
        <li role="option" data-value="100">synthesizer</li> ...
      Producer/Engineer: aria-labelledby="songRoles.production_and_engineering"
        <li role="option" data-value="146">producer</li> ...
      More Options: aria-labelledby="songRoles.other"
        <li role="option" data-value="1">performer</li> ...
      Radio sections: MUI RadioGroup with <input type="radio"> inside <label>
    """

    # ── Unified MUI multi-select role picker ──
    def _pick_role(label_id: str, role_name: str, data_value: str, display: str):
        """Open MUI multi-select by aria-labelledby, click option by TEXT, verify."""
        # 1. Find trigger and check if already selected
        check = page.evaluate("""(args) => {
            const { labelId, roleName } = args;
            const trigger = document.querySelector(
                '[aria-labelledby="' + labelId + '"][role="combobox"]')
                || document.querySelector('[aria-labelledby*="' + labelId + '"]');
            if (!trigger) return { status: 'no_trigger' };
            const txt = trigger.textContent.trim().toLowerCase();
            // Known placeholder texts that mean "empty"
            const placeholders = [
                'performer roles', 'producer / engineer roles',
                'producer/engineer roles', 'more options',
            ];
            if (placeholders.includes(txt)) return { status: 'needs_open', txt };
            if (txt === roleName.toLowerCase()) return { status: 'already', txt };
            if (txt.split(',').map(s => s.trim()).includes(roleName.toLowerCase()))
                return { status: 'already', txt };
            return { status: 'needs_open', txt };
        }""", {"labelId": label_id, "roleName": role_name})

        if check.get('status') == 'no_trigger':
            log.warning(f"  {display}: trigger not found")
            return False
        if check.get('status') == 'already':
            log.info(f"  {display}: already has '{check.get('txt')}'")
            return True

        log.info(f"  {display}: opening (current='{check.get('txt')}')...")

        # 2. Open the dropdown
        try:
            trigger_loc = page.locator(
                f'[aria-labelledby="{label_id}"][role="combobox"]').first
            trigger_loc.scroll_into_view_if_needed(timeout=2000)
            trigger_loc.click()
            page.wait_for_timeout(1500)
        except Exception as e:
            log.warning(f"  {display}: could not click trigger: {e}")
            return False

        # 3. Log all available options for debugging
        all_opts = page.evaluate("""() => {
            const opts = document.querySelectorAll('[role="option"]');
            return [...opts].map(o => ({
                text: o.textContent.trim(),
                dv: o.getAttribute('data-value'),
                checked: o.getAttribute('aria-selected') === 'true'
            }));
        }""")
        if all_opts:
            log.info(f"  {display}: {len(all_opts)} options available")
            for o in all_opts[:5]:
                log.info(f"    - '{o.get('text')}' dv={o.get('dv')} sel={o.get('checked')}")
            if len(all_opts) > 5:
                log.info(f"    ... and {len(all_opts) - 5} more")

        # 4. Click option with multi-strategy fuzzy matching in JS
        picked = False
        try:
            pick_result = page.evaluate("""(args) => {
                const { roleName, dataValue } = args;
                const opts = [...document.querySelectorAll('[role="option"]')];
                if (!opts.length) return { picked: false, reason: 'no_options' };
                const target = roleName.toLowerCase().trim();

                const click = (opt, how) => {
                    opt.scrollIntoView({block: 'nearest'});
                    opt.click();
                    return {
                        picked: true,
                        how,
                        text: opt.textContent.trim(),
                        dv: opt.getAttribute('data-value'),
                    };
                };

                // Normalize option text: strip checkbox icons, lowercase, trim
                const normText = (el) => el.textContent
                    .replace(/[☐-☑✓-✔✅❌]/g, '')
                    .trim().toLowerCase();

                // Strategy 1: EXACT match
                for (const opt of opts) {
                    if (normText(opt) === target) return click(opt, 'exact');
                }

                // Only skip qualified variants if the target is unqualified.
                // E.g. target "producer" should skip "co-producer", but target
                // "co-producer" should match "co-producer" (exact via strategy 1).
                const qualifiedPrefixes = ['co-', 'co ', 'assistant ', 'vocal ',
                    'executive ', 'associate '];
                const targetIsQualified = qualifiedPrefixes.some(p => target.startsWith(p));

                // Strategy 2: option's main word is target (e.g. "music producer" → producer)
                for (const opt of opts) {
                    const txt = normText(opt);
                    if (!targetIsQualified
                        && qualifiedPrefixes.some(p => txt.startsWith(p))) continue;
                    const words = txt.split(/[\s-]+/);
                    if (words[words.length - 1] === target) return click(opt, 'last-word');
                }

                // Strategy 3: data-value match (legacy)
                if (dataValue) {
                    const dv = opts.find(o => o.getAttribute('data-value') === dataValue);
                    if (dv) return click(dv, 'data-value');
                }

                // Strategy 4: option contains target as whole word (loose fallback)
                for (const opt of opts) {
                    const txt = normText(opt);
                    if (!targetIsQualified
                        && qualifiedPrefixes.some(p => txt.startsWith(p))) continue;
                    const words = txt.split(/[\s-]+/);
                    if (words.includes(target)) return click(opt, 'whole-word');
                }

                // Not found — return list of all options for debugging
                return {
                    picked: false,
                    reason: 'no_match',
                    available: opts.map(o => ({
                        text: o.textContent.trim(),
                        dv: o.getAttribute('data-value')
                    }))
                };
            }""", {"roleName": role_name, "dataValue": data_value})

            if pick_result and pick_result.get('picked'):
                picked = True
                log.info(f"  {display}: clicked '{pick_result.get('text')}' "
                         f"(data-value={pick_result.get('dv')}) via {pick_result.get('how')}")
            else:
                log.warning(f"  {display}: no match found; reason={pick_result.get('reason')}")
                avail = pick_result.get('available', []) if pick_result else []
                for o in avail[:15]:
                    log.warning(f"    opt: '{o.get('text')}' dv={o.get('dv')}")
        except Exception as e:
            log.info(f"  {display}: JS multi-strategy failed: {e}")

        # FALLBACK: Playwright locator by text
        if not picked:
            try:
                opt = page.locator('[role="option"]').filter(
                    has_text=re.compile(f"^{re.escape(role_name)}$", re.IGNORECASE)).first
                opt.wait_for(state='visible', timeout=2000)
                opt.scroll_into_view_if_needed(timeout=2000)
                opt.click()
                page.wait_for_timeout(500)
                picked = True
                log.info(f"  {display}: clicked '{role_name}' (Playwright text filter)")
            except Exception as e:
                log.info(f"  {display}: Playwright text filter failed: {e}")

        # 5. Close the dropdown by clicking outside (Escape can un-save in MUI)
        page.wait_for_timeout(500)
        try:
            page.locator('body').click(position={"x": 5, "y": 5}, force=True)
        except Exception:
            page.keyboard.press("Escape")
        page.wait_for_timeout(800)

        # 6. Verify the selection stuck (exclude placeholder text)
        verified = page.evaluate("""(args) => {
            const { labelId, roleName } = args;
            const trigger = document.querySelector(
                '[aria-labelledby="' + labelId + '"][role="combobox"]')
                || document.querySelector('[aria-labelledby*="' + labelId + '"]');
            if (!trigger) return false;
            const txt = trigger.textContent.trim().toLowerCase();
            const placeholders = [
                'performer roles', 'producer / engineer roles',
                'producer/engineer roles', 'more options',
            ];
            if (placeholders.includes(txt)) return false;
            return txt.includes(roleName.toLowerCase());
        }""", {"labelId": label_id, "roleName": role_name})

        if verified:
            log.info(f"  {display}: VERIFIED '{role_name}' is selected")
        else:
            log.warning(f"  {display}: selection NOT verified — '{role_name}' not in trigger text")
            # Retry once: reopen and try again
            log.info(f"  {display}: RETRYING...")
            try:
                trigger_loc = page.locator(
                    f'[aria-labelledby="{label_id}"][role="combobox"]').first
                trigger_loc.click()
                page.wait_for_timeout(1500)
                pick2 = page.evaluate("""(roleName) => {
                    const opts = document.querySelectorAll('[role="option"]');
                    const target = roleName.toLowerCase().trim();
                    for (const opt of opts) {
                        const txt = opt.textContent.trim().toLowerCase();
                        if (txt === target) {
                            opt.scrollIntoView({block: 'nearest'});
                            opt.click();
                            return true;
                        }
                    }
                    return false;
                }""", role_name)
                page.wait_for_timeout(500)
                page.locator('body').click(position={"x": 5, "y": 5}, force=True)
                page.wait_for_timeout(800)
                if pick2:
                    log.info(f"  {display}: RETRY picked '{role_name}'")
                    verified = True
            except Exception as e2:
                log.warning(f"  {display}: retry failed: {e2}")
        return verified

    # ── Performer Roles (synthesizer=100) ──
    _pick_role("songRoles.performer", "synthesizer", "100", "Performer Roles")

    # ── Producer / Engineer Roles (co-producer) ──
    _pick_role("songRoles.production_and_engineering", "co-producer", "",
               "Producer/Engineer Roles")

    # ── More Options (performer=1) ──
    _pick_role("songRoles.other", "performer", "1", "More Options")

    # ── Radio sections: Release History, Copyright, Lyrics ──
    # Broad approach: find ALL radio inputs, check their label context,
    # and click the right "No" options.
    try:
        radio_results = page.evaluate("""() => {
            const results = {};
            const radios = document.querySelectorAll('input[type="radio"]');
            for (const r of radios) {
                const label = r.closest('label')
                           || r.closest('.MuiFormControlLabel-root')
                           || r.parentElement;
                const labelText = (label?.textContent || '').trim();

                // Walk up to find the section heading
                let node = r.parentElement;
                let sectionText = '';
                for (let i = 0; i < 10 && node; i++) {
                    const t = node.textContent || '';
                    if (/Release History/i.test(t)) { sectionText = 'release_history'; break; }
                    if (/Copyright Ownership|cover of another/i.test(t)) { sectionText = 'copyright'; break; }
                    if (/Lyrics.*\\*|Does this track have lyrics/i.test(t)) { sectionText = 'lyrics'; break; }
                    node = node.parentElement;
                }
                if (!sectionText) continue;

                // Click "No" or "No, it's instrumental"
                if (sectionText === 'lyrics' && /instrumental|^No/i.test(labelText)) {
                    if (!r.checked) { r.click(); results[sectionText] = 'clicked:' + labelText; }
                    else { results[sectionText] = 'already:' + labelText; }
                } else if (sectionText !== 'lyrics' && /^No$/i.test(labelText)) {
                    if (!r.checked) { r.click(); results[sectionText] = 'clicked:' + labelText; }
                    else { results[sectionText] = 'already:' + labelText; }
                }
            }
            return results;
        }""")
        for section, result in radio_results.items():
            log.info(f"  {section}: {result}")
        for expected in ['release_history', 'copyright', 'lyrics']:
            if expected not in radio_results:
                log.warning(f"  {expected}: radio not found — trying Playwright fallback")
                if expected == 'lyrics':
                    try:
                        lbl = page.locator("label, .MuiFormControlLabel-root").filter(
                            has_text=re.compile(r"instrumental", re.IGNORECASE)).first
                        if lbl.is_visible(timeout=2000):
                            lbl.click()
                            log.info(f"  {expected}: Playwright click")
                    except Exception:
                        pass
                else:
                    try:
                        # Find "No" labels that are near the expected heading
                        no_labels = page.locator("label, .MuiFormControlLabel-root").filter(
                            has_text=re.compile(r"^No$", re.IGNORECASE))
                        for i in range(no_labels.count()):
                            lbl = no_labels.nth(i)
                            if lbl.is_visible(timeout=500):
                                lbl.click()
                                page.wait_for_timeout(300)
                    except Exception:
                        pass
    except Exception as e:
        log.warning(f"  Radio sections failed: {e}")

    page.wait_for_timeout(1000)


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
        try:
            upload_state = page.evaluate("""() => {
                const body = document.body?.innerText || '';

                // "X / Y Completed"
                const m = body.match(/(\\d+)\\s*\\/\\s*(\\d+)\\s*Completed/i);
                if (m && parseInt(m[1]) >= parseInt(m[2]) && parseInt(m[2]) > 0)
                    return 'completed';

                // Success keywords
                if (/upload\\s*complete|successfully\\s*uploaded/i.test(body))
                    return 'completed';

                // Enabled Continue/Save button = upload done
                const btns = document.querySelectorAll('button, a, [role="button"]');
                for (const b of btns) {
                    const t = (b.innerText || b.textContent || '').trim().toLowerCase();
                    if (!t.includes('continue') && !t.includes('save')) continue;
                    if (b.offsetWidth === 0) continue;
                    const cls = b.className || '';
                    const disabled = b.disabled
                        || b.getAttribute('disabled') !== null
                        || b.getAttribute('aria-disabled') === 'true'
                        || /Mui-disabled|disabled/i.test(cls);
                    if (!disabled) return 'button_enabled';
                }

                // MUI LinearProgress / progress bar visible?
                const prog = document.querySelector(
                    '[class*="progress" i], [class*="Progress" i], '
                  + '[role="progressbar"], .MuiLinearProgress-root');
                if (prog && prog.offsetWidth > 0) return 'in_progress';

                return 'waiting';
            }""")

            if upload_state == 'completed' or upload_state == 'button_enabled':
                log.info(f"  Upload done: {upload_state}")
                return
            if upload_state == 'in_progress':
                seen_progress = True
        except Exception:
            pass

        # Progress bar was visible before but now gone
        if seen_progress:
            try:
                still = page.evaluate("""() => {
                    const p = document.querySelector(
                        '[class*="progress" i], [role="progressbar"], .MuiLinearProgress-root');
                    return p && p.offsetWidth > 0;
                }""")
                if not still:
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

    Returns one of: dashboard, choose_type, create_wizard, start, release_details,
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
            hasAddSingleBtn: visibleBtn('add single'),
            hasAddReleaseBtn: visibleBtn('add release'),
            hasTypeChoice: visibleBtn('single') && (visibleBtn('album') || visibleBtn('ep') || visibleBtn('ringtone')),
            hasStartBtn: visibleBtn('start') || visibleBtn('begin'),
            // "Create Single" wizard page with step sections (Progress 0/4)
            isCreateWizard: (body.includes('create single') || body.includes('create album'))
                && body.includes('progress'),
            hasLangField: has('input[name="languageCode"]'),
            hasGenreField: has('input[name="primaryGenreId"]'),
            hasAddTrackBtn: visibleBtn('add track'),
            hasUnuploadedFile: body.includes("hasn't been uploaded") || body.includes('file hasn'),
            // Real TuneCore React app detection
            hasSongsApp: has('#songs_app'),
            hasTracksFormRoot: has('#tracks-form-root'),
            isTracksUrl: url.includes('/tracks'),
            hasWriterField: anyVisible('input[name*="songwriter" i]', 'input[name*="writer" i]'),
            hasRoleField: has('input[name="role"]') || has('select[name="role"]')
                || has('input[name="creativeRole"]') || has('select[name="creativeRole"]'),
            // 2026 UI: new sections on track-details page
            hasPerformerRoles: body.includes('performer roles'),
            hasReleaseHistory: body.includes('release history')
                || body.includes('previously released'),
            hasLyricsSection: body.includes('does this track have lyrics'),
            hasFileInput: has('input[type="file"]'),
            // UPLOAD STEREO button (label.song-file-upload-button > div.stereo-asset-upload-btn)
            hasStereoUploadBtn: visible('div.stereo-asset-upload-btn')
                || has('input.song-file-upload-input')
                || visible('label.song-file-upload-button'),
            hasArtworkBtn: visibleBtn('add artwork') || visibleBtn('upload artwork')
                || visibleBtn('cover art') || visibleBtn('add image'),
            hasReviewBtn: visibleBtn('continue and review') || visibleBtn('continue & review') || visibleBtn('continue to review'),
            reviewBtnDisabled: [...document.querySelectorAll('button, [role="button"]')]
                .some(el => el.offsetWidth > 0
                    && (el.textContent.toLowerCase().includes('continue to review')
                        || el.textContent.toLowerCase().includes('continue and review')
                        || el.textContent.toLowerCase().includes('continue & review'))
                    && (el.disabled || el.getAttribute('aria-disabled') === 'true'
                        || el.classList.contains('Mui-disabled'))),
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
    # ③ Overview page can show "Add Track", "Add Artwork", AND "Continue to Review".
    # The review button is DISABLED until artwork is uploaded.
    # Priority: upload artwork first, then review.
    if state.get('hasReviewBtn') and state.get('hasAddTrackBtn'):
        if not state.get('hasUnuploadedFile') and not state.get('reviewBtnDisabled'):
            return 'review'  # all files uploaded + artwork done → Continue to Review
        # else: fall through — need to upload WAV or artwork first
    # Artwork — also match on overview page where hasAddTrackBtn is present
    if state.get('hasArtworkBtn') and (not state.get('hasAddTrackBtn') or state.get('reviewBtnDisabled')):
        return 'artwork'
    if state.get('hasReviewBtn') and not state.get('hasAddTrackBtn'):
        return 'review'
    # UPLOAD STEREO page: has the stereo upload button (even inside #songs_app)
    # BUT NOT if we also see track-form fields (Performer Roles, Lyrics, etc.)
    is_track_form = (state.get('hasTracksFormRoot') or state.get('hasPerformerRoles')
                     or state.get('hasLyricsSection'))
    if state.get('hasStereoUploadBtn') and not state.get('hasWriterField') and not is_track_form:
        return 'upload_wav'
    if (state.get('hasFileInput') and not state.get('hasWriterField')
            and not state.get('hasSongsApp') and not is_track_form):
        return 'upload_wav'
    # TuneCore React songs app on /singles/{id}/tracks or /albums/{id}/tracks
    if state.get('hasSongsApp') or state.get('hasTracksFormRoot') or (state.get('isTracksUrl') and not state.get('isDashboard')):
        return 'track_details'
    if state.get('hasWriterField') or state.get('hasRoleField'):
        return 'track_details'
    if state.get('hasAddTrackBtn'):
        return 'add_track'
    if state.get('hasLangField') or state.get('hasGenreField'):
        return 'release_details'
    # 2026 UI: Performer Roles / Lyrics sections → track details
    # (checked AFTER release_details to avoid false match on "previously released")
    if state.get('hasPerformerRoles') or state.get('hasLyricsSection'):
        return 'track_details'
    if state.get('hasStartBtn') and not state.get('hasTypeChoice'):
        return 'start'
    if state.get('hasTypeChoice'):
        return 'choose_type'
    # "Create Single" wizard page — shows 4 steps with Progress counter
    if state.get('isCreateWizard'):
        return 'create_wizard'
    return 'unknown'


def _dismiss_overlays(page):
    """Hide the sticky TuneCore navbar and dismiss cookie banners.

    The nav overlay (div.nav-nav85, #v2-nav-mountpoint) intercepts pointer
    events on dashboard buttons.  Hide it via CSS so Playwright clicks land
    on the actual elements underneath.
    """
    try:
        page.evaluate("""() => {
            // Completely hide sticky navbar that intercepts clicks
            for (const sel of ['#v2-nav-mountpoint', '.nav-nav85', '[class*="nav-nav"]']) {
                for (const el of document.querySelectorAll(sel)) {
                    el.style.display = 'none';
                }
            }
            // Click "Reject All" cookie banner if present
            for (const btn of document.querySelectorAll('button')) {
                if (btn.textContent.trim() === 'Reject All' && btn.offsetWidth > 0) {
                    btn.click();
                    break;
                }
            }
        }""")
        log.info("  Dismissed overlays (navbar hidden + cookies)")
    except Exception as e:
        log.info(f"  Overlay dismiss failed (non-fatal): {e}")


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

            # Dismiss cookie banner & hide sticky navbar that blocks clicks
            _dismiss_overlays(page)

            # ── Adaptive loop: detect → act → repeat ──
            while step < MAX_STEPS:
                step += 1
                try:
                    page.screenshot(path=f"output/tunecore_{step:02d}.png")
                except Exception:
                    pass
                _dismiss_overlays(page)

                # ── Beatport: check the checkbox or click the button ──
                try:
                    bp_checked = page.evaluate("""() => {
                        // Strategy 1: checkbox near "Beatport" text
                        const labels = document.querySelectorAll(
                            'label, .MuiFormControlLabel-root, div, span');
                        for (const lbl of labels) {
                            const t = (lbl.textContent || '').trim();
                            if (!/beatport/i.test(t) || lbl.offsetWidth === 0) continue;
                            const cb = lbl.querySelector('input[type="checkbox"]')
                                     || lbl.closest('label')?.querySelector('input[type="checkbox"]');
                            if (cb && !cb.checked) { cb.click(); return 'checkbox'; }
                            if (cb && cb.checked) return 'already';
                            // MUI Checkbox: look for Mui-checked class
                            const muiCb = lbl.querySelector('[class*="Checkbox"], [class*="checkbox"]');
                            if (muiCb && !/checked/i.test(muiCb.className)) {
                                muiCb.click(); return 'mui-checkbox';
                            }
                            if (muiCb) return 'already';
                        }
                        // Strategy 2: checkbox input with beatport in name/id/value
                        const cbs = document.querySelectorAll('input[type="checkbox"]');
                        for (const cb of cbs) {
                            const id = (cb.id || cb.name || cb.value || '').toLowerCase();
                            if (id.includes('beatport') && !cb.checked) {
                                cb.click(); return 'checkbox-by-id';
                            }
                            if (id.includes('beatport') && cb.checked) return 'already';
                        }
                        return null;
                    }""")
                    if bp_checked:
                        log.info(f"  Beatport: {bp_checked}")
                    else:
                        # Fallback: try Playwright label click
                        try:
                            bp_label = page.locator("label, .MuiFormControlLabel-root").filter(
                                has_text=re.compile(r"beatport", re.IGNORECASE)).first
                            if bp_label.is_visible(timeout=2000):
                                bp_label.click()
                                page.wait_for_timeout(500)
                                log.info("  Beatport: clicked label (Playwright)")
                                bp_checked = True
                        except Exception:
                            pass
                    if not bp_checked:
                        # Old UI fallback: "DISTRIBUTE TO BEATPORT" button
                        bp_btn = _find_clickable(page, [
                            "button:has-text('Distribute to Beatport')",
                            "a:has-text('Distribute to Beatport')",
                            "[role='button']:has-text('Distribute to Beatport')",
                            "text=DISTRIBUTE TO BEATPORT",
                        ])
                        if bp_btn:
                            bp_btn.scroll_into_view_if_needed()
                            page.wait_for_timeout(500)
                            bp_btn.click()
                            page.wait_for_timeout(3000)
                            log.info("  Beatport: clicked button (old UI)")
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
                    # If stuck on dashboard, restore nav and try clicking Add Release
                    if state == 'dashboard':
                        log.info("  Stuck on dashboard — restoring nav & trying 'Add Release'")
                        # Restore navbar so Add Release button is visible
                        page.evaluate("""() => {
                            for (const sel of ['#v2-nav-mountpoint', '.nav-nav85', '[class*="nav-nav"]']) {
                                for (const el of document.querySelectorAll(sel)) {
                                    el.style.display = '';
                                }
                            }
                        }""")
                        page.wait_for_timeout(1000)
                        add_rel = _find_clickable(page, [
                            "button:has-text('Add Release')",
                            "a:has-text('Add Release')",
                            "[role='button']:has-text('Add Release')",
                            "div:has-text('Add Release')",
                            "span:has-text('Add Release')",
                            "[data-testid='add-release']",
                        ])
                        if not add_rel:
                            add_rel = page.locator("text=Add Release").first
                            try:
                                if not add_rel.is_visible(timeout=3000):
                                    add_rel = None
                            except Exception:
                                add_rel = None
                        if add_rel:
                            add_rel.scroll_into_view_if_needed()
                            page.wait_for_timeout(500)
                            add_rel.click()
                            log.info("  Clicked 'Add Release'")
                            page.wait_for_timeout(3000)
                            # Select Single from modal
                            single_btn = _find_clickable(page, [
                                "button:has-text('Single')",
                                "a:has-text('Single')",
                                "[role='menuitem']:has-text('Single')",
                                "[role='option']:has-text('Single')",
                                "li:has-text('Single')",
                            ])
                            if single_btn:
                                single_btn.click()
                                log.info("  Selected 'Single' from modal")
                            else:
                                page.evaluate("""() => {
                                    const els = [...document.querySelectorAll('button, a, [role="menuitem"], [role="option"], li, div, span')];
                                    for (const el of els) {
                                        const txt = (el.textContent || '').trim();
                                        if (/^single$/i.test(txt) && el.offsetWidth > 0) { el.click(); return; }
                                    }
                                }""")
                                log.info("  Selected 'Single' via JS fallback")
                            page.wait_for_timeout(3000)
                            _dismiss_overlays(page)
                        else:
                            log.info("  Fallback — navigating directly to /singles/new")
                            page.goto(f"{TUNECORE_BASE}/singles/new",
                                      wait_until="domcontentloaded", timeout=30_000)
                            page.wait_for_timeout(3000)
                            _dismiss_overlays(page)
                        continue
                    # Try to click Continue/Next to force-advance
                    # (exclude SET UP PAYOUT and other unrelated .secondary-btn links)
                    skip_btn = _find_clickable(page, [
                        "a:has-text('Continue')",
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
                        log.info("  Creating new release...")

                        # Restore navbar first — "Add Release" button lives inside it
                        page.evaluate("""() => {
                            for (const sel of ['#v2-nav-mountpoint', '.nav-nav85', '[class*="nav-nav"]']) {
                                for (const el of document.querySelectorAll(sel)) {
                                    el.style.display = '';
                                }
                            }
                        }""")
                        page.wait_for_timeout(1000)

                        # Click "Add Release" — try broad selectors (any element type)
                        add_rel = _find_clickable(page, [
                            "button:has-text('Add Release')",
                            "a:has-text('Add Release')",
                            "[role='button']:has-text('Add Release')",
                            "div:has-text('Add Release')",
                            "span:has-text('Add Release')",
                            "[data-testid='add-release']",
                        ])
                        if not add_rel:
                            # Last resort: find ANY element with "Add Release" text via JS
                            add_rel = page.locator("text=Add Release").first
                            try:
                                if not add_rel.is_visible(timeout=3000):
                                    add_rel = None
                            except Exception:
                                add_rel = None
                        if not add_rel:
                            # JS click fallback — click even if overlapped
                            clicked_js = page.evaluate("""() => {
                                const els = [...document.querySelectorAll('button, a, [role="button"], div, span')];
                                for (const el of els) {
                                    const txt = (el.textContent || '').trim();
                                    if (/^add\\s+release$/i.test(txt) && el.offsetWidth > 0) {
                                        el.click();
                                        return true;
                                    }
                                }
                                return false;
                            }""")
                            if clicked_js:
                                log.info("  Clicked 'Add Release' via JS fallback")
                                add_rel = True  # flag so we enter the modal handler below
                        if add_rel:
                            if add_rel is not True:
                                add_rel.scroll_into_view_if_needed()
                                page.wait_for_timeout(500)
                                add_rel.click()
                            log.info("  Clicked 'Add Release'")
                            page.wait_for_timeout(3000)

                            # A modal/popup appears with Single / Album — select Single
                            single_btn = _find_clickable(page, [
                                "button:has-text('Single')",
                                "a:has-text('Single')",
                                "[role='menuitem']:has-text('Single')",
                                "[role='option']:has-text('Single')",
                                "li:has-text('Single')",
                            ])
                            if not single_btn:
                                # JS fallback for Single in modal
                                page.evaluate("""() => {
                                    const els = [...document.querySelectorAll('button, a, [role="menuitem"], [role="option"], li, div, span')];
                                    for (const el of els) {
                                        const txt = (el.textContent || '').trim();
                                        if (/^single$/i.test(txt) && el.offsetWidth > 0) {
                                            el.click();
                                            return;
                                        }
                                    }
                                }""")
                                log.info("  Selected 'Single' via JS fallback")
                            else:
                                single_btn.click()
                                log.info("  Selected 'Single' from modal")
                            page.wait_for_timeout(3000)
                            _dismiss_overlays(page)
                        else:
                            # Fallback: navigate directly
                            log.warning("  'Add Release' button not found — navigating to /singles/new")
                            _dismiss_overlays(page)
                            page.goto(f"{TUNECORE_BASE}/singles/new",
                                      wait_until="domcontentloaded", timeout=30_000)
                            page.wait_for_timeout(3000)
                            _dismiss_overlays(page)

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

                    # ── CREATE WIZARD / START ──
                    elif state in ('create_wizard', 'start'):
                        log.info(f"  [{state}] Clicking Start button...")
                        _dismiss_overlays(page)
                        clicked = page.evaluate("""() => {
                            // Strategy 1: aria-label selector
                            var btn = document.querySelector('button[aria-label="Link to Release Details"]');
                            if (btn) { btn.click(); return 'aria-label'; }
                            // Strategy 2: any link/button pointing to release details
                            var links = document.querySelectorAll('a[href*="release"], a[href*="details"], a[href*="step"]');
                            for (var i = 0; i < links.length; i++) {
                                if (links[i].offsetWidth > 0) { links[i].click(); return 'link:' + links[i].href; }
                            }
                            // Strategy 3: button with "start" text
                            var all = document.querySelectorAll('button, a, [role="button"]');
                            for (var i = 0; i < all.length; i++) {
                                var txt = (all[i].textContent || '').trim().toLowerCase();
                                if (txt.startsWith('start') || txt === 'begin') {
                                    all[i].click(); return txt;
                                }
                            }
                            // Strategy 4: clickable element inside the first step/section header
                            var sections = document.querySelectorAll('[class*="step"], [class*="section"], [class*="accordion"], [class*="panel"]');
                            for (var i = 0; i < sections.length; i++) {
                                var s = sections[i];
                                var clickable = s.querySelector('button, a, [role="button"], [class*="edit"], [class*="start"]');
                                if (clickable && clickable.offsetWidth > 0) {
                                    clickable.click(); return 'section-btn:' + (clickable.textContent || '').trim();
                                }
                            }
                            // Strategy 5: click the first section header itself (accordion expand)
                            for (var i = 0; i < sections.length; i++) {
                                if (sections[i].offsetWidth > 0) {
                                    sections[i].click(); return 'section-click:' + i;
                                }
                            }
                            // Strategy 6: any small icon-button in the top-right area of the page
                            var btns = document.querySelectorAll('button, [role="button"], a');
                            for (var i = 0; i < btns.length; i++) {
                                var rect = btns[i].getBoundingClientRect();
                                if (rect.right > window.innerWidth * 0.6 && rect.top < 200 && rect.width > 0 && rect.width < 200) {
                                    btns[i].click(); return 'top-right-btn:' + (btns[i].textContent || btns[i].className || '').trim().substring(0, 50);
                                }
                            }
                            return null;
                        }""")
                        if clicked:
                            log.info(f"  Clicked Start: {clicked}")
                        else:
                            log.warning("  Could not find Start button — trying direct navigation")
                            _dump_page_state(page, state)
                            # Fallback: navigate directly to the release details page
                            current_url = page.url
                            if '/singles/' in current_url:
                                # Extract the release ID and go directly to details
                                import re as _re
                                m = _re.search(r'/singles/(\d+)', current_url)
                                if m:
                                    page.goto(f"{TUNECORE_BASE}/singles/{m.group(1)}/details",
                                              wait_until="domcontentloaded", timeout=30_000)
                                    log.info(f"  Navigated directly to release details")
                                    page.wait_for_timeout(3000)
                                    _dismiss_overlays(page)
                                    continue
                            # Last resort: go to /singles/new
                            page.goto(f"{TUNECORE_BASE}/singles/new",
                                      wait_until="domcontentloaded", timeout=30_000)
                            _dismiss_overlays(page)
                        page.wait_for_timeout(3000)

                    # ── RELEASE DETAILS (title, language, genre) ──
                    elif state == 'release_details':
                        log.info("  Filling release details...")
                        for sel in ["input[name*='title' i]", "input[name*='name' i]"]:
                            try:
                                el = page.locator(sel).first
                                if el.is_visible(timeout=1500):
                                    clean_name = _strip_emojis(concept.track_name)
                                    el.fill(clean_name)
                                    log.info(f"  Title: {clean_name}")
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
                                    "a.secondary-btn:not([href*='payout'])", "a:has-text('Continue')",
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
                    # Old UI: jQuery + React (data-songs JSON).
                    # 2026 UI: MUI-based step 3/4 with Songwriters, Artists &
                    #   Contributors (Performer Roles, Producer/Engineer Roles,
                    #   More Options), Release History, Copyright Ownership, Lyrics.
                    elif state == 'track_details':
                        log.info("  Filling track details (AGGRESSIVE — fill everything)...")
                        _dump_page_state(page, "Track Details — before fill")

                        # Wait for page content to render (old UI: #songs_app, new: MUI form)
                        try:
                            page.wait_for_selector(
                                '#songs_app, #tracks-form-root, .MuiFormControl-root, '
                                'input[placeholder*="Legal First"], '
                                'input[name*="artistContributor" i]',
                                timeout=15_000)
                            page.wait_for_timeout(3000)
                        except Exception:
                            page.wait_for_timeout(5000)

                        # ── NEW 2026 UI: #tracks-form-root ──
                        is_new_ui = page.evaluate(
                            "!!document.querySelector('#tracks-form-root')")
                        if is_new_ui:
                            log.info("  Detected #tracks-form-root — using new UI handler")
                            _fill_new_ui_track(page, concept, artist, wav_path)
                            page.wait_for_timeout(3000)
                            continue

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
                                        clean_name = _strip_emojis(concept.track_name)
                                        el.fill(clean_name)
                                        log.info(f"  Song Title: '{clean_name}'")
                                    break
                            except Exception:
                                continue

                        # ── 2. Songwriter ──
                        # Old UI: input with placeholder "Legal First..."
                        # New 2026 UI: plain text input near "Songwriters" heading
                        try:
                            sw_el = None
                            # Try old selector first
                            try:
                                cand = page.locator('input[placeholder*="Legal First"]').first
                                if cand.is_visible(timeout=2000):
                                    sw_el = cand
                            except Exception:
                                pass

                            # Fallback: find input near "Songwriters" heading (2026 UI)
                            if not sw_el:
                                sw_state = page.evaluate("""() => {
                                    const headings = document.querySelectorAll(
                                        'h1,h2,h3,h4,h5,h6,legend,label,span,div,p,strong');
                                    for (const h of headings) {
                                        if (!/^Songwriters?\\s*\\*?$/i.test(h.textContent.trim())) continue;
                                        if (h.offsetWidth === 0) continue;
                                        const section = h.closest(
                                            'fieldset, section, [class*="section"], .MuiFormControl-root'
                                        ) || h.parentElement?.parentElement || h.parentElement;
                                        if (!section) continue;
                                        const inputs = section.querySelectorAll(
                                            'input[type="text"], input:not([type])');
                                        for (const inp of inputs) {
                                            if (inp.offsetWidth > 0) {
                                                if (inp.value.trim()) return 'filled:' + inp.value.trim();
                                                inp.setAttribute('data-sw-fill', 'true');
                                                return 'empty';
                                            }
                                        }
                                    }
                                    return null;
                                }""")
                                if sw_state == 'empty':
                                    sw_el = page.locator('[data-sw-fill="true"]').first
                                elif sw_state and str(sw_state).startswith('filled:'):
                                    log.info(f"  Songwriter: already '{sw_state[7:]}'")

                            if sw_el:
                                sw_val = sw_el.input_value()
                                if sw_val.strip():
                                    log.info(f"  Songwriter: already '{sw_val}'")
                                else:
                                    sw_el.scroll_into_view_if_needed(timeout=2000)
                                    sw_el.click()
                                    page.wait_for_timeout(500)
                                    sw_el.fill(artist)
                                    page.wait_for_timeout(500)
                                    page.keyboard.press("Tab")
                                    page.wait_for_timeout(800)

                                    sw_check = sw_el.input_value()
                                    if sw_check.strip():
                                        log.info(f"  Songwriter: '{sw_check}' (fill)")
                                    else:
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
                                            page.evaluate("""(args) => {
                                                const inp = document.querySelector(
                                                    '[data-sw-fill="true"]')
                                                    || document.querySelector('input[placeholder*="Legal First"]');
                                                if (!inp) return;
                                                const setter = Object.getOwnPropertyDescriptor(
                                                    HTMLInputElement.prototype, 'value').set;
                                                setter.call(inp, args);
                                                inp.dispatchEvent(new Event('input', {bubbles: true}));
                                                inp.dispatchEvent(new Event('change', {bubbles: true}));
                                                inp.dispatchEvent(new Event('blur', {bubbles: true}));
                                            }""", artist)
                                            page.wait_for_timeout(500)
                                            log.info(f"  Songwriter: native setter '{artist}'")
                            elif not (sw_state and str(sw_state).startswith('filled:')):
                                log.warning("  Songwriter: input not found")
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
                                    'input[placeholder*="Add Artist"], '
                                    'input[name*="artistContributor" i], '
                                    'input[name*="artist_contributor" i]'
                                )
                                art_count = empty_arts.count()
                                # Fallback: find inputs near "Artist" headings (2026 UI)
                                if art_count == 0:
                                    page.evaluate("""() => {
                                        const headings = document.querySelectorAll(
                                            'label, legend, span, div, p, h4, h5');
                                        for (const h of headings) {
                                            const t = h.textContent.trim();
                                            if (!/Artist.*Contributor.*Name/i.test(t)) continue;
                                            if (h.offsetWidth === 0) continue;
                                            const ctrl = h.closest('.MuiFormControl-root')
                                                       || h.parentElement;
                                            if (!ctrl) continue;
                                            const inp = ctrl.querySelector('input');
                                            if (inp && inp.offsetWidth > 0 && !inp.value.trim()) {
                                                inp.setAttribute('data-art-fill', 'true');
                                            }
                                        }
                                    }""")
                                    empty_arts = page.locator('[data-art-fill="true"]')
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

                        # ── 4b. New 2026 UI fields ──
                        # Performer Roles, Producer/Engineer, Release History,
                        # Copyright, Lyrics radio buttons.
                        _fill_new_track_fields(page)
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
                            "a.secondary-btn:not([href*='payout'])",
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
                                    "a.secondary-btn:not([href*='payout'])", "a:has-text('Continue')",
                                    "button:has-text('Continue')", "button:has-text('Next')",
                                ])
                                if cont:
                                    cont.click()
                                    page.wait_for_timeout(5000)
                                continue
                            log.info(f"  Uploading WAV: {wav_path.name}")
                            _dump_page_state(page, "Before WAV Upload")

                            # Strategy 1: Set file directly on input.song-file-upload-input
                            wav_ok = False
                            try:
                                file_input = page.locator("input.song-file-upload-input")
                                if file_input.count() > 0:
                                    file_input.first.set_input_files(str(wav_path), timeout=5000)
                                    log.info(f"  WAV set directly on input.song-file-upload-input: {wav_path.name}")
                                    wav_ok = True
                            except Exception as e:
                                log.info(f"  Direct input.song-file-upload-input failed: {e}")

                            # Strategy 2: Click the label.song-file-upload-button to open file chooser
                            if not wav_ok:
                                try:
                                    stereo_label = page.locator("label.song-file-upload-button").first
                                    if stereo_label.is_visible(timeout=3000):
                                        log.info("  Clicking label.song-file-upload-button...")
                                        with page.expect_file_chooser(timeout=10000) as fc_info:
                                            stereo_label.click()
                                        file_chooser = fc_info.value
                                        file_chooser.set_files(str(wav_path))
                                        log.info(f"  WAV selected via song-file-upload-button: {wav_path.name}")
                                        wav_ok = True
                                except Exception as e:
                                    log.info(f"  label.song-file-upload-button failed: {e}")

                            # Strategy 3: Click div.stereo-asset-upload-btn
                            if not wav_ok:
                                try:
                                    stereo_div = page.locator("div.stereo-asset-upload-btn").first
                                    if stereo_div.is_visible(timeout=3000):
                                        log.info("  Clicking div.stereo-asset-upload-btn...")
                                        with page.expect_file_chooser(timeout=10000) as fc_info:
                                            stereo_div.click()
                                        file_chooser = fc_info.value
                                        file_chooser.set_files(str(wav_path))
                                        log.info(f"  WAV selected via stereo-asset-upload-btn: {wav_path.name}")
                                        wav_ok = True
                                except Exception as e:
                                    log.info(f"  div.stereo-asset-upload-btn failed: {e}")

                            # Strategy 4: Fallback to generic _upload_file
                            if not wav_ok:
                                log.info("  TuneCore-specific selectors failed — trying generic _upload_file")
                                wav_ok = _upload_file(page, wav_path)

                            if not wav_ok:
                                # Hard fail — don't silently advance with Audio ❌
                                try:
                                    page.screenshot(
                                        path=str(OUTPUT_DIR / "debug_tunecore_wav_no_input.png"),
                                        full_page=True,
                                    )
                                except Exception:
                                    pass
                                raise RuntimeError(
                                    f"WAV upload failed — no file input accepted '{wav_path.name}'. "
                                    f"See output/debug_tunecore_wav_no_input.png"
                                )

                            log.info("  Waiting for WAV upload (~6 min)...")
                            _wait_for_upload(page, timeout=360, file_was_set=wav_ok)

                            # TuneCore disables Continue until server-side
                            # processing finishes. Poll for the button to
                            # become enabled — clicking it while disabled
                            # just throws a 30s timeout (Audio ❌ on dashboard).
                            log.info("  Waiting for Continue button to become enabled...")
                            enabled_deadline = time.time() + 420  # up to 7 min
                            continue_enabled = False
                            while time.time() < enabled_deadline:
                                try:
                                    continue_enabled = page.evaluate("""() => {
                                        const btns = Array.from(document.querySelectorAll(
                                            'button, a, [role="button"]'));
                                        for (const b of btns) {
                                            const t = (b.innerText || b.textContent || '').trim().toLowerCase();
                                            if (!t.includes('continue') && !t.includes('next')
                                                && !t.includes('save')) continue;
                                            if (b.offsetWidth === 0) continue;
                                            const cls = b.className || '';
                                            const disabled = b.disabled
                                                || b.getAttribute('disabled') !== null
                                                || b.getAttribute('aria-disabled') === 'true'
                                                || /Mui-disabled|disabled/i.test(cls);
                                            if (!disabled) return true;
                                        }
                                        // Also check for "X / Y Completed" pattern
                                        const body = document.body?.innerText || '';
                                        const m = body.match(/(\\d+)\\s*\\/\\s*(\\d+)\\s*Completed/i);
                                        if (m && parseInt(m[1]) >= parseInt(m[2]) && parseInt(m[2]) > 0)
                                            return true;
                                        return false;
                                    }""")
                                except Exception:
                                    pass
                                if continue_enabled:
                                    log.info("  Continue button is now enabled — WAV processing complete")
                                    break
                                page.wait_for_timeout(5000)
                                log.info(f"  Still waiting for Continue to enable ({int(time.time() - (enabled_deadline - 420))}s)...")
                            if not continue_enabled:
                                try:
                                    page.screenshot(
                                        path=str(OUTPUT_DIR / "debug_tunecore_wav_continue_disabled.png"),
                                        full_page=True,
                                    )
                                except Exception:
                                    pass
                                raise RuntimeError(
                                    "Continue button never enabled — TuneCore is still "
                                    "processing or rejected the WAV. "
                                    "See output/debug_tunecore_wav_continue_disabled.png"
                                )

                            # After upload, capture any TuneCore error banner (silence,
                            # duration, format) so we know WHY audio is rejected instead
                            # of silently clicking Continue over a broken file.
                            wav_error = None
                            try:
                                wav_error = page.evaluate("""() => {
                                    const selectors = [
                                        '.error', '.alert-danger', '[class*="error" i]',
                                        '[class*="invalid" i]', '[role="alert"]',
                                    ];
                                    for (const sel of selectors) {
                                        for (const el of document.querySelectorAll(sel)) {
                                            const t = (el.innerText || '').trim();
                                            if (t && t.length < 500 &&
                                                /silen|duration|second|format|fail|invalid|reject/i.test(t)) {
                                                return t.slice(0, 300);
                                            }
                                        }
                                    }
                                    return null;
                                }""")
                            except Exception:
                                pass
                            if wav_error:
                                try:
                                    page.screenshot(
                                        path=str(OUTPUT_DIR / "debug_tunecore_wav_error.png"),
                                        full_page=True,
                                    )
                                except Exception:
                                    pass
                                raise RuntimeError(
                                    f"TuneCore rejected WAV: {wav_error} — "
                                    f"see output/debug_tunecore_wav_error.png"
                                )

                            cont = _find_clickable(page, [
                                "button:has-text('Continue')", "button:has-text('Next')",
                                "a:has-text('Continue')",
                            ])
                            if not cont:
                                try:
                                    page.screenshot(
                                        path=str(OUTPUT_DIR / "debug_tunecore_wav_no_continue.png"),
                                        full_page=True,
                                    )
                                except Exception:
                                    pass
                                raise RuntimeError(
                                    "WAV uploaded but Continue button not found — "
                                    "draft would show Audio ❌. "
                                    "See output/debug_tunecore_wav_no_continue.png"
                                )
                            cont.click()
                            page.wait_for_timeout(5000)
                            log.info("  Clicked Continue after WAV")

                            # Verify we actually advanced past upload_wav. If we're
                            # still on this state, the click didn't save.
                            page.wait_for_timeout(3000)
                            still_on_upload = _detect_page(page) == 'upload_wav'
                            if still_on_upload:
                                try:
                                    page.screenshot(
                                        path=str(OUTPUT_DIR / "debug_tunecore_wav_stuck.png"),
                                        full_page=True,
                                    )
                                except Exception:
                                    pass
                                raise RuntimeError(
                                    "Still on upload_wav state after clicking Continue — "
                                    "WAV did not save. See output/debug_tunecore_wav_stuck.png"
                                )
                        except Exception as e:
                            log.error(f"  Upload WAV step failed: {e}")
                            # Break the state loop — don't pretend the upload worked.
                            # The outer retry loop can try again (Strategy 2 handles
                            # transient failures). Audio ❌ is better surfaced than hidden.
                            raise

                    # ── ARTWORK ──
                    elif state == 'artwork':
                        try:
                            if not cover_path.exists() or str(cover_path) == '/dev/null':
                                log.info("  Artwork step — no file provided, skipping (draft mode)")
                                cont = _find_clickable(page, [
                                    "a.secondary-btn:not([href*='payout'])", "a:has-text('Continue')",
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
                            "a:has-text('Continue and Review')",
                            "a:has-text('Continue & Review')",
                            "a:has-text('Continue to Review')",
                            "[role='button']:has-text('Continue')",
                            "button:has-text('Review')",
                            "a:has-text('Review')",
                            "button:has-text('Continue')",
                            "a.secondary-btn",
                        ])
                        if btn:
                            btn.scroll_into_view_if_needed()
                            page.wait_for_timeout(500)
                            btn.click()
                            page.wait_for_timeout(8000)
                            log.info("  Clicked Continue and Review")
                        else:
                            log.warning("  Review button not found — dumping page state...")
                            _dump_page_state(page, "review step — no button found")
                            try:
                                cont = page.locator("text=Continue").first
                                if cont.is_visible(timeout=3000):
                                    cont.scroll_into_view_if_needed()
                                    page.wait_for_timeout(500)
                                    cont.click()
                                    page.wait_for_timeout(8000)
                                    log.info("  Clicked fallback 'Continue' text")
                            except Exception:
                                pass

                    # ── RELEASE ──
                    elif state == 'release':
                        btn = _find_clickable(page, [
                            "button:has-text('Release Music')",
                            "a:has-text('Release Music')",
                            "[role='button']:has-text('Release Music')",
                            "button:has-text('Release')",
                            "a:has-text('Release')",
                            "button:has-text('Submit')",
                            "a:has-text('Submit')",
                            "button:has-text('Distribute')",
                            "a:has-text('Distribute')",
                        ])
                        if btn:
                            btn.scroll_into_view_if_needed()
                            page.wait_for_timeout(500)
                            btn.click()
                            log.info("  Clicked Release Music")
                            page.wait_for_timeout(5000)

                            # Handle confirmation dialog/modal if one appears
                            confirm = _find_clickable(page, [
                                "button:has-text('Confirm')",
                                "button:has-text('Yes')",
                                "button:has-text('OK')",
                                "button:has-text('Submit')",
                                "button:has-text('Release')",
                                "a:has-text('Confirm')",
                            ])
                            if confirm:
                                confirm.click()
                                page.wait_for_timeout(5000)
                                log.info("  Confirmed release dialog")

                            # Check if release succeeded or failed
                            post_release = _detect_page(page)
                            if post_release == 'done':
                                log.info("  Release succeeded!")
                            else:
                                log.warning(f"  Release may have failed (page={post_release})")
                                log.info("  Attempting to save as draft instead...")
                                try:
                                    page.screenshot(path="output/tunecore_release_fail.png")
                                except Exception:
                                    pass
                                # Try to save as draft
                                draft_btn = _find_clickable(page, [
                                    "button:has-text('Save as Draft')",
                                    "button:has-text('Save Draft')",
                                    "button:has-text('Save')",
                                    "a:has-text('Save as Draft')",
                                    "a:has-text('Save Draft')",
                                ])
                                if draft_btn:
                                    draft_btn.click()
                                    page.wait_for_timeout(3000)
                                    log.info("  Saved as draft (fallback)")
                        else:
                            log.warning("  Release button not found — dumping page state...")
                            _dump_page_state(page, "release step — no button found")
                            draft_btn = _find_clickable(page, [
                                "button:has-text('Save as Draft')",
                                "button:has-text('Save Draft')",
                                "button:has-text('Save')",
                                "a:has-text('Save as Draft')",
                                "a:has-text('Save Draft')",
                            ])
                            if draft_btn:
                                draft_btn.click()
                                page.wait_for_timeout(3000)
                                log.info("  Saved as draft (no release button)")

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
