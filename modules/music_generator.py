"""Generate music on aimusicfactory.ai using Playwright.

Flow:
1. Go to #Generate page
2. Ensure Custom Mode ON + Instrumental ON
3. Fill "Style of Music" textarea (if empty) with Afro House prompt
4. Fill "Title" input with the track name (e.g. "Zanu")
5. Click Generate
6. Wait ~6 minutes for generation
7. Go to My Music, find the new track, open its page
8. Download the MP3s from the track page
"""

import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from modules.concept_generator import MusicConcept
from config import OUTPUT_DIR, HEADLESS, AIMUSICFACTORY_STATE_FILE
from utils.logger import log

# The fixed Afro House style prompt (goes into "Style of Music" field)
STYLE_OF_MUSIC_PROMPT = (
    "Create a progressive Afro House track infused with heavy car bass and deep, "
    "psychedelic tribal energy. The tempo is 122 BPM, blending organic percussion "
    "(congas, shakers, djembe, bongos) with massive analog low-end — the kind of "
    "bass that moves both air and soul. Layer psychedelic textures, evolving "
    "atmospheric pads, and subtle vocal tribal chants that echo through wide stereo "
    "space. Introduce dark, evolving synth arps and progressive transitions that "
    "rise gradually toward a cinematic, festival-style drop. The groove should feel "
    "spiritual yet raw, balancing Afro rhythms with deep car bass resonance, perfect "
    "for big sound systems and open-air sets. The overall sound is deep, hypnotic, "
    "and cinematic, mastered for warmth, clarity, and sub-bass impact. "
    "Mood: Ritualistic, primal, powerful, transcendent."
)

GENERATION_WAIT_SEC = 360  # 6 minutes wait for generation


def generate_music_batch(concept: MusicConcept, count: int = 4) -> list[Path]:
    """Generate music on aimusicfactory.ai multiple times.

    Args:
        concept: The music concept with the prompt.
        count: Number of times to hit Generate (each gives 2 MP3s).

    Returns:
        List of downloaded MP3 file paths.
    """
    log.info(f"Generating {count} batches on aimusicfactory.ai for: {concept.track_name}")

    safe_name = "".join(c if c.isalnum() or c in "-_ " else "" for c in concept.track_name)
    safe_name = safe_name.strip().replace(" ", "_")[:50]

    all_mp3s = []

    with sync_playwright() as p:
        chrome_args = ["--disable-blink-features=AutomationControlled"]

        # Always use visible browser — site is a SPA that won't render in headless
        context_opts = {"viewport": {"width": 1920, "height": 1080}}
        if AIMUSICFACTORY_STATE_FILE.exists():
            context_opts["storage_state"] = str(AIMUSICFACTORY_STATE_FILE)
            log.info("Loading saved cookies")

        browser = p.chromium.launch(
            headless=False, channel="chrome", args=chrome_args,
        )
        context = browser.new_context(**context_opts)
        context.set_default_timeout(60_000)
        page = context.new_page()

        # Check if logged in, prompt if not
        logged_in = _check_logged_in(page)
        if logged_in:
            log.info("Already logged in!")
            context.storage_state(path=str(AIMUSICFACTORY_STATE_FILE))
        else:
            log.info("Not logged in — please log in with Google in the browser.")
            input("\n>>> Press ENTER after you've logged in... ")
            AIMUSICFACTORY_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            context.storage_state(path=str(AIMUSICFACTORY_STATE_FILE))
            log.info(f"Session saved to: {AIMUSICFACTORY_STATE_FILE}")

        for batch_num in range(1, count + 1):
            log.info(f"\n--- Generation {batch_num}/{count} ---")

            try:
                mp3s = _single_generation(page, concept, safe_name, batch_num)
                all_mp3s.extend(mp3s)
                log.info(f"Generation {batch_num} done: {len(mp3s)} MP3(s) downloaded")
            except Exception as e:
                log.warning(f"Generation {batch_num} failed: {e}")
                page.screenshot(path=str(OUTPUT_DIR / f"debug_gen_{batch_num}.png"))

        browser.close()

    if not all_mp3s:
        raise RuntimeError(f"No MP3s generated after {count} attempts")

    log.info(f"Total MP3s downloaded: {len(all_mp3s)}")
    return all_mp3s


def _check_logged_in(page) -> bool:
    """Navigate to the site and return True if already logged in."""
    page.goto("https://aimusicfactory.ai", wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(5000)

    for sel in ['text="Sign In"', 'text="Login"', 'text="Log In"',
                'text="Sign in"', 'text="sign in"', 'a:has-text("Sign")',
                'button:has-text("Sign")', 'button:has-text("Login")']:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                return False
        except Exception:
            continue
    return True



def _single_generation(page, concept: MusicConcept, safe_name: str, batch_num: int) -> list[Path]:
    """Generate one track on aimusicfactory.ai.

    1. Ensure Custom Mode + Instrumental toggles are ON
    2. Fill form fields (Style of Music, Title)
    3. Click Generate, wait, download
    """

    # Step 1: Go to Generate page
    log.info("Navigating to Generate page...")
    page.goto("https://aimusicfactory.ai/#Generate", wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(5000)
    page.screenshot(path=str(OUTPUT_DIR / f"debug_before_gen_{batch_num}.png"))

    # Step 2: Try to enable Custom Mode + Instrumental toggles
    _ensure_toggle_on(page, "Custom Mode")
    page.wait_for_timeout(500)
    _ensure_toggle_on(page, "Instrumental")
    page.wait_for_timeout(500)

    # Step 3: Debug — log all visible form fields
    _debug_form_fields(page)

    # Step 4: Fill form fields by analyzing placeholders
    _fill_form_fields(page, concept, batch_num)

    page.screenshot(path=str(OUTPUT_DIR / f"debug_fields_filled_{batch_num}.png"))

    # Step 6: Click Generate button
    clicked = False
    for selector in ['button:has-text("Generate")', 'button:has-text("Create")',
                      'button:has-text("Make")', '[type="submit"]',
                      ".generate-btn", "#generate"]:
        try:
            btn = page.wait_for_selector(selector, timeout=3000)
            if btn and btn.is_visible():
                btn.click()
                clicked = True
                log.info(f"Clicked: {selector}")
                break
        except PlaywrightTimeout:
            continue

    if not clicked:
        page.screenshot(path=str(OUTPUT_DIR / f"debug_no_button_{batch_num}.png"))
        raise RuntimeError("Could not find Generate button")

    # Step 4: Wait for generation (~6 minutes)
    log.info(f"Generating... waiting {GENERATION_WAIT_SEC // 60} minutes")
    for elapsed in range(0, GENERATION_WAIT_SEC, 30):
        page.wait_for_timeout(30_000)
        remaining = GENERATION_WAIT_SEC - elapsed - 30
        if remaining > 0:
            log.info(f"  {remaining // 60}m {remaining % 60}s remaining...")

    # Step 5: Go to My Music and find the newest track
    log.info("Going to My Music to download...")
    page.goto("https://aimusicfactory.ai/myMusic", wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(5000)
    page.screenshot(path=str(OUTPUT_DIR / f"debug_mymusic_{batch_num}.png"))

    # Step 6: Click on the first/newest track card to open its page
    track_link = None
    for selector in ['a[href*="/myMusic/"]', '[href*="/myMusic/"]',
                      '.track-card a', '.music-card a',
                      'a:has-text("' + concept.track_name + '")']:
        try:
            links = page.query_selector_all(selector)
            visible = [l for l in links if l.is_visible()]
            if visible:
                track_link = visible[0]  # First = newest
                log.info(f"Found track link: {selector}")
                break
        except Exception:
            continue

    if track_link:
        href = track_link.get_attribute("href") or ""
        log.info(f"Opening track page: {href}")
        track_link.click()
        page.wait_for_timeout(3000)
        page.screenshot(path=str(OUTPUT_DIR / f"debug_track_page_{batch_num}.png"))

    # Step 7: Download MP3s from track page
    downloaded = _download_mp3s(page, safe_name, batch_num)

    if not downloaded:
        page.screenshot(path=str(OUTPUT_DIR / f"debug_no_download_{batch_num}.png"))
        raise RuntimeError("Could not download MP3")

    return downloaded


def _debug_form_fields(page):
    """Log all visible form fields and save page HTML for analysis."""
    # Log textareas
    textareas = page.query_selector_all("textarea")
    visible_tas = [t for t in textareas if t.is_visible()]
    log.info(f"Visible textareas: {len(visible_tas)}")
    for i, ta in enumerate(visible_tas):
        ph = ta.get_attribute("placeholder") or ""
        name = ta.get_attribute("name") or ""
        cls = ta.get_attribute("class") or ""
        val = ta.input_value()[:30] if ta.input_value() else ""
        log.info(f"  textarea[{i}]: placeholder='{ph}' name='{name}' class='{cls}' value='{val}...'")

    # Log inputs
    inputs = page.query_selector_all("input")
    visible_inputs = [inp for inp in inputs if inp.is_visible()]
    log.info(f"Visible inputs: {len(visible_inputs)}")
    for i, inp in enumerate(visible_inputs):
        t = inp.get_attribute("type") or ""
        ph = inp.get_attribute("placeholder") or ""
        name = inp.get_attribute("name") or ""
        cls = inp.get_attribute("class") or ""
        val = inp.input_value()[:30] if inp.input_value() else ""
        log.info(f"  input[{i}]: type='{t}' placeholder='{ph}' name='{name}' class='{cls}' value='{val}'")

    # Dump page HTML to file for analysis
    try:
        html = page.content()
        html_path = OUTPUT_DIR / "debug_page.html"
        html_path.write_text(html, encoding="utf-8")
        log.info(f"Page HTML saved to: {html_path} ({len(html)} chars)")
    except Exception as e:
        log.warning(f"Could not save page HTML: {e}")


def _fill_form_fields(page, concept: MusicConcept, batch_num: int):
    """Fill Style of Music and Title fields. Works with textareas and inputs."""
    style_filled = False
    title_filled = False

    # Collect all visible textareas and inputs
    textareas = page.query_selector_all("textarea")
    visible_tas = [t for t in textareas if t.is_visible()]

    inputs = page.query_selector_all("input")
    visible_inputs = [inp for inp in inputs if inp.is_visible()
                      and inp.get_attribute("type") in (None, "", "text", "search")]

    all_fields = []
    for ta in visible_tas:
        ph = (ta.get_attribute("placeholder") or "").lower()
        name = (ta.get_attribute("name") or "").lower()
        all_fields.append({"el": ta, "ph": ph, "name": name, "tag": "textarea"})
    for inp in visible_inputs:
        ph = (inp.get_attribute("placeholder") or "").lower()
        name = (inp.get_attribute("name") or "").lower()
        all_fields.append({"el": inp, "ph": ph, "name": name, "tag": "input"})

    log.info(f"Total visible form fields: {len(all_fields)}")

    # First pass: fill by placeholder/name matching
    for f in all_fields:
        ph, name = f["ph"], f["name"]

        # Match Style of Music
        if not style_filled and ("style" in ph or "music" in ph or "genre" in ph
                                  or "style" in name or "prompt" in name
                                  or "description" in ph or "describe" in ph):
            current = f["el"].input_value()
            if not current.strip():
                f["el"].click()
                f["el"].fill(STYLE_OF_MUSIC_PROMPT)
                log.info(f"Filled Style of Music via placeholder='{f['ph']}'")
            else:
                log.info(f"Style of Music already filled ({len(current)} chars)")
            style_filled = True
            continue

        # Match Title
        if not title_filled and ("title" in ph or "song" in ph or "name" in ph
                                  or "title" in name or "song" in name):
            f["el"].click()
            f["el"].fill("")
            f["el"].fill(concept.track_name)
            title_filled = True
            log.info(f"Filled Title via placeholder='{f['ph']}'")
            continue

    # Second pass: if not matched by placeholder, use position-based logic
    # For Custom Mode + Instrumental on aimusicfactory.ai:
    #   textarea[0] = Style of Music (big prompt area)
    #   textarea[1] = Lyrics (disabled/empty for Instrumental)
    #   textarea[2] or last field = Title
    if not style_filled and len(visible_tas) >= 1:
        ta = visible_tas[0]
        current = ta.input_value()
        if not current.strip():
            ta.click()
            ta.fill(STYLE_OF_MUSIC_PROMPT)
            log.info("Filled Style of Music (first textarea, position-based)")
        else:
            log.info(f"Style of Music (first textarea) already filled ({len(current)} chars)")
        style_filled = True

    if not title_filled:
        # Try the last textarea (often Title is the last short field)
        for ta in reversed(visible_tas):
            ph = (ta.get_attribute("placeholder") or "").lower()
            # Skip if this is the Style of Music textarea we already filled
            current = ta.input_value()
            if current == STYLE_OF_MUSIC_PROMPT:
                continue
            # Skip if it looks like a lyrics field (usually large/multiline)
            if "lyric" in ph or "lyrics" in ph:
                continue
            ta.click()
            ta.fill("")
            ta.fill(concept.track_name)
            title_filled = True
            log.info(f"Filled Title (textarea, position-based, placeholder='{ph}')")
            break

    # Last resort: try any visible input
    if not title_filled and visible_inputs:
        visible_inputs[0].click()
        visible_inputs[0].fill("")
        visible_inputs[0].fill(concept.track_name)
        title_filled = True
        log.info("Filled Title (first visible input, last resort)")

    if not style_filled:
        log.warning("Could not find Style of Music field!")
    if not title_filled:
        page.screenshot(path=str(OUTPUT_DIR / f"debug_no_title_{batch_num}.png"))
        raise RuntimeError("Could not find Title field")


def _ensure_toggle_on(page, label_text: str):
    """Ensure a toggle (Custom Mode / Instrumental) is ON.

    Looks for the label text on the page and checks if the nearby
    toggle/switch is active. If not, clicks it.
    """
    try:
        # Find all text elements matching the label
        elements = page.query_selector_all(f'text="{label_text}"')
        for el in elements:
            if not el.is_visible():
                continue

            # Look for a toggle/switch near this label
            # Common patterns: sibling element, parent container with toggle
            parent = el.evaluate_handle(
                "el => el.closest('label') || el.closest('div') || el.parentElement"
            )
            parent_el = parent.as_element()
            if not parent_el:
                continue

            # Check for toggle input or switch
            toggle = parent_el.query_selector(
                'input[type="checkbox"], [role="switch"], button, .toggle, .switch'
            )
            if toggle:
                # Check if it's already ON
                checked = (
                    toggle.get_attribute("aria-checked")
                    or toggle.get_attribute("data-state")
                    or toggle.get_attribute("checked")
                )
                is_on = checked in ("true", "checked", "on")

                if is_on:
                    log.info(f"{label_text}: already ON")
                else:
                    toggle.click()
                    log.info(f"{label_text}: turned ON")
                return

            # If no toggle found, try clicking the label area itself
            # (some toggles are CSS-only and clicking the label toggles them)
            el.click()
            log.info(f"{label_text}: clicked label (assuming toggle)")
            return

    except Exception as e:
        log.info(f"{label_text} toggle check: {e}")

    log.info(f"{label_text}: could not find toggle (assuming already ON)")


def _download_mp3s(page, safe_name: str, batch_num: int) -> list[Path]:
    """Find and click download buttons on the current page."""
    for selector in ['a:has-text("Download")', 'button:has-text("Download")',
                      'a[download]', '[href*=".mp3"]', '[href*="download"]',
                      '[aria-label*="ownload"]', '[title*="ownload"]',
                      '.download-btn', 'a:has-text("download")',
                      'button:has-text("download")',
                      'svg[data-testid*="download"]']:
        try:
            elements = page.query_selector_all(selector)
            visible = [el for el in elements if el.is_visible()]
            if visible:
                log.info(f"Found {len(visible)} download button(s): {selector}")
                downloaded = []
                for i, btn in enumerate(visible[:2]):
                    try:
                        output_path = OUTPUT_DIR / f"{safe_name}_gen{batch_num}_{i + 1}.mp3"
                        with page.expect_download(timeout=120_000) as dl_info:
                            btn.click()
                        download = dl_info.value
                        download.save_as(str(output_path))
                        downloaded.append(output_path)
                        log.info(f"Downloaded: {output_path.name}")
                        page.wait_for_timeout(2000)
                    except Exception as e:
                        log.warning(f"Download {i + 1} failed: {e}")
                if downloaded:
                    return downloaded
        except Exception:
            continue

    return []


def generate_music(concept: MusicConcept) -> Path:
    """Generate a single music track (backward compatibility)."""
    mp3s = generate_music_batch(concept, count=1)
    return mp3s[0]
