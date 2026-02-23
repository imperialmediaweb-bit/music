"""Generate music on aimusicfactory.ai using Playwright.

Pipeline approach:
1. Submit all generations back-to-back (wait ~4 min each for server to finish)
2. Wait until 12 min have passed since the first generation (downloads need time)
3. Go to My Music, download all new tracks at once
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

GENERATION_COMPLETE_SEC = 240  # 4 min — wait after clicking Generate for songs to appear
DOWNLOAD_READY_SEC = 720       # 12 min — minimum time from generation before downloads work


def generate_music_batch(concept: MusicConcept, count: int = 4) -> list[Path]:
    """Generate music on aimusicfactory.ai — pipeline approach.

    Submits all generations first, then waits for downloads, then downloads all.
    Much faster than generating and downloading one-by-one.

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
        chrome_args = [
            "--disable-blink-features=AutomationControlled",
            "--window-position=-2400,-2400",  # Move window off-screen
        ]

        # Visible browser required — SPA won't render in headless mode
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

        # ── Phase 1: Submit all generations back-to-back ──
        generation_start_times = []

        for batch_num in range(1, count + 1):
            log.info(f"\n--- Generation {batch_num}/{count} ---")
            try:
                _submit_generation(page, concept, safe_name, batch_num)
                generation_start_times.append(time.time())
                log.info(f"Generation {batch_num} submitted successfully")
            except Exception as e:
                log.warning(f"Generation {batch_num} failed: {e}")
                page.screenshot(path=str(OUTPUT_DIR / f"debug_gen_{batch_num}.png"))

        if not generation_start_times:
            browser.close()
            raise RuntimeError(f"All {count} generations failed")

        # ── Phase 2: Wait for downloads to be ready ──
        first_gen = generation_start_times[0]
        elapsed = time.time() - first_gen
        remaining = DOWNLOAD_READY_SEC - elapsed

        if remaining > 0:
            log.info(f"Waiting {remaining / 60:.1f} more minutes for downloads to become available...")
            _wait_with_progress(page, remaining)
        else:
            log.info("Enough time has passed — downloads should be ready")

        # ── Phase 3: Download all tracks from My Music ──
        log.info("Going to My Music to download all tracks...")
        all_mp3s = _download_all_from_mymusic(
            page, concept, safe_name, len(generation_start_times),
        )

        browser.close()

    if not all_mp3s:
        raise RuntimeError(f"No MP3s downloaded after {count} generations")

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


def _submit_generation(page, concept: MusicConcept, safe_name: str, batch_num: int):
    """Fill form and click Generate, then wait for generation to complete.

    Does NOT download — that happens later in the pipeline.
    """
    # Step 1: Navigate to Generate page
    log.info("Navigating to Generate page...")
    page.goto("https://aimusicfactory.ai/#Generate", wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(5000)
    page.screenshot(path=str(OUTPUT_DIR / f"debug_before_gen_{batch_num}.png"))

    # Step 2: Enable Custom Mode + Instrumental toggles
    _ensure_toggle_on(page, "Custom Mode")
    page.wait_for_timeout(500)
    _ensure_toggle_on(page, "Instrumental")
    page.wait_for_timeout(500)

    # Verify Instrumental is ON: if lyrics textarea is visible, toggle failed
    lyrics_el = page.query_selector('textarea[name="prompt"]')
    if lyrics_el and lyrics_el.is_visible():
        log.warning("Instrumental toggle didn't work — lyrics field still visible. Clicking again...")
        page.click('text="Instrumental"', timeout=5000)
        page.wait_for_timeout(1000)

    # Step 3: Debug — log all visible form fields
    _debug_form_fields(page)

    # Step 4: Fill form fields
    _fill_form_fields(page, concept, batch_num)
    page.screenshot(path=str(OUTPUT_DIR / f"debug_fields_filled_{batch_num}.png"))

    # Step 5: Click Generate button
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

    # Step 6: Wait for this generation to complete on the server (~4 min)
    log.info(f"Waiting {GENERATION_COMPLETE_SEC // 60} min for generation to complete...")
    _wait_with_progress(page, GENERATION_COMPLETE_SEC)


def _wait_with_progress(page, seconds: float):
    """Wait with progress logging every 30 seconds."""
    total = int(seconds)
    for elapsed in range(0, total, 30):
        page.wait_for_timeout(30_000)
        remaining = total - elapsed - 30
        if remaining > 0:
            log.info(f"  {remaining // 60}m {remaining % 60}s remaining...")


def _download_all_from_mymusic(page, concept: MusicConcept, safe_name: str, track_count: int) -> list[Path]:
    """Go to My Music page and download MP3s from the newest tracks.

    Args:
        track_count: Number of recent tracks to download from.

    Returns:
        List of downloaded MP3 paths.
    """
    page.goto("https://aimusicfactory.ai/myMusic", wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(5000)
    page.screenshot(path=str(OUTPUT_DIR / "debug_mymusic.png"))

    # Find track links
    track_links = []
    seen_hrefs = set()
    for selector in ['a[href*="/myMusic/"]', '[href*="/myMusic/"]',
                      '.track-card a', '.music-card a',
                      f'a:has-text("{concept.track_name}")']:
        try:
            links = page.query_selector_all(selector)
            for link in links:
                if not link.is_visible():
                    continue
                href = link.get_attribute("href") or ""
                if href and href not in seen_hrefs:
                    seen_hrefs.add(href)
                    track_links.append(link)
        except Exception:
            continue

    if not track_links:
        log.warning("No track links found in My Music!")
        page.screenshot(path=str(OUTPUT_DIR / "debug_no_tracks.png"))
        return []

    log.info(f"Found {len(track_links)} track(s) in My Music, downloading from newest {track_count}")
    tracks_to_download = track_links[:track_count]

    all_mp3s = []
    for i, link in enumerate(tracks_to_download):
        batch_num = i + 1
        href = link.get_attribute("href") or ""
        log.info(f"Opening track {batch_num}/{len(tracks_to_download)}: {href}")
        link.click()
        page.wait_for_timeout(3000)
        page.screenshot(path=str(OUTPUT_DIR / f"debug_track_page_{batch_num}.png"))

        downloaded = _download_mp3s(page, safe_name, batch_num)
        all_mp3s.extend(downloaded)
        log.info(f"Track {batch_num}: downloaded {len(downloaded)} MP3(s)")

        # Go back to My Music for next track
        if i < len(tracks_to_download) - 1:
            page.goto("https://aimusicfactory.ai/myMusic", wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(3000)

    return all_mp3s


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
    """Fill the aimusicfactory.ai form fields.

    Known form structure (Custom Mode):
      textarea[name='prompt'] = Lyrics (leave empty for Instrumental)
      textarea[name='tags']   = Style of Music (our STYLE_OF_MUSIC_PROMPT)
      textarea[name='title']  = Title (track name)
    """
    style_filled = False
    title_filled = False

    # Fill by exact name attribute (most reliable)
    tags_el = page.query_selector('textarea[name="tags"]')
    if tags_el and tags_el.is_visible():
        tags_el.click()
        tags_el.fill(STYLE_OF_MUSIC_PROMPT)
        style_filled = True
        log.info(f"Filled Style of Music (name='tags', {len(STYLE_OF_MUSIC_PROMPT)} chars)")

    title_el = page.query_selector('textarea[name="title"]')
    if title_el and title_el.is_visible():
        title_el.click()
        title_el.fill(concept.track_name)
        title_filled = True
        log.info(f"Filled Title (name='title'): {concept.track_name}")

    # If lyrics field is still visible (Instrumental toggle failed), clear it
    lyrics_el = page.query_selector('textarea[name="prompt"]')
    if lyrics_el and lyrics_el.is_visible():
        lyrics_el.click()
        lyrics_el.fill("")
        log.info("Cleared Lyrics field (Instrumental toggle may have failed)")
    else:
        log.info("Lyrics field hidden (Instrumental mode active)")

    if not style_filled:
        log.warning("Could not find Style of Music field (name='tags')!")
    if not title_filled:
        page.screenshot(path=str(OUTPUT_DIR / f"debug_no_title_{batch_num}.png"))
        raise RuntimeError("Could not find Title field (name='title')")


def _ensure_toggle_on(page, label_text: str):
    """Ensure a HeadlessUI toggle (Custom Mode / Instrumental) is ON.

    The toggles are HeadlessUI switches: <button role="switch" aria-checked="true/false">
    near a text label. We find the label text, then search siblings/parent for the switch.
    """
    try:
        result = page.evaluate("""(labelText) => {
            // Strategy 1: Find text node, walk up parents to find sibling switch
            const walker = document.createTreeWalker(
                document.body, NodeFilter.SHOW_TEXT, null);
            while (walker.nextNode()) {
                const text = walker.currentNode.textContent.trim();
                if (text === labelText || text.includes(labelText)) {
                    let el = walker.currentNode.parentElement;
                    // Walk up to find a container that has a button[role="switch"]
                    for (let i = 0; i < 8; i++) {
                        if (!el) break;
                        const sw = el.querySelector('button[role="switch"]');
                        if (sw) {
                            const isOn = sw.getAttribute('aria-checked') === 'true'
                                || sw.hasAttribute('data-checked');
                            if (!isOn) { sw.click(); return 'turned_on'; }
                            return 'already_on';
                        }
                        el = el.parentElement;
                    }
                }
            }

            // Strategy 2: Find all switches and match by nearby text
            const switches = document.querySelectorAll('button[role="switch"]');
            for (const sw of switches) {
                const container = sw.closest('div')?.parentElement
                    || sw.parentElement?.parentElement;
                if (container && container.textContent.includes(labelText)) {
                    const isOn = sw.getAttribute('aria-checked') === 'true'
                        || sw.hasAttribute('data-checked');
                    if (!isOn) { sw.click(); return 'turned_on'; }
                    return 'already_on';
                }
            }
            return 'not_found';
        }""", label_text)

        if result == "already_on":
            log.info(f"{label_text}: already ON")
        elif result == "turned_on":
            log.info(f"{label_text}: turned ON")
            page.wait_for_timeout(500)
        else:
            log.info(f"{label_text}: toggle not found")
    except Exception as e:
        log.info(f"{label_text} toggle: {e}")


def _download_mp3s(page, safe_name: str, batch_num: int) -> list[Path]:
    """Find and click download buttons on the current page.

    The site uses <span class="ml-[2rem] mr-[1rem]">Download</span> inside
    clickable containers. We use JS to find these spans and click them or
    their parent elements.
    """
    # Save page HTML for debugging
    try:
        html = page.content()
        html_path = OUTPUT_DIR / f"debug_download_page_{batch_num}.html"
        html_path.write_text(html, encoding="utf-8")
        log.info(f"Download page HTML saved: {html_path}")
    except Exception:
        pass

    # Strategy 1: Use JavaScript to find all elements containing "Download" text
    download_info = page.evaluate("""() => {
        const results = [];
        // Find all spans/elements with exact "Download" text
        const allEls = document.querySelectorAll('span, a, button, div');
        for (const el of allEls) {
            if (el.textContent.trim() === 'Download' && el.offsetParent !== null) {
                const tag = el.tagName.toLowerCase();
                const cls = el.className || '';
                const parentTag = el.parentElement?.tagName.toLowerCase() || '';
                const parentCls = el.parentElement?.className || '';
                const href = el.closest('a')?.href || el.parentElement?.closest('a')?.href || '';
                results.push({
                    tag, cls, parentTag, parentCls, href,
                    rect: el.getBoundingClientRect()
                });
            }
        }
        return results;
    }""")
    log.info(f"Found {len(download_info)} 'Download' elements via JS:")
    for i, info in enumerate(download_info):
        log.info(f"  [{i}] <{info['tag']}> class='{info['cls'][:60]}' "
                 f"parent=<{info['parentTag']}> href='{info['href'][:80]}'")

    downloaded = []

    # Strategy 2: Click Download spans via JS (click the span's closest clickable parent)
    if download_info:
        count_to_dl = min(len(download_info), 2)
        for i in range(count_to_dl):
            try:
                ts = int(time.time())
                output_path = OUTPUT_DIR / f"{safe_name}_gen{batch_num}_{i + 1}_{ts}.mp3"

                # Try to get a direct download URL from an <a> tag
                href = page.evaluate("""(idx) => {
                    const spans = [...document.querySelectorAll('span, a, button, div')]
                        .filter(el => el.textContent.trim() === 'Download' && el.offsetParent !== null);
                    if (idx >= spans.length) return null;
                    const el = spans[idx];
                    const link = el.closest('a') || el.parentElement?.closest('a');
                    return link?.href || null;
                }""", i)

                if href and ('.mp3' in href or 'download' in href.lower()):
                    # Direct download via URL
                    log.info(f"Downloading via URL: {href[:100]}")
                    response = page.request.get(href)
                    output_path.write_bytes(response.body())
                    downloaded.append(output_path)
                    log.info(f"Downloaded: {output_path.name}")
                    continue

                # Click the element and catch the download event
                try:
                    with page.expect_download(timeout=30_000) as dl_info:
                        page.evaluate("""(idx) => {
                            const spans = [...document.querySelectorAll('span, a, button, div')]
                                .filter(el => el.textContent.trim() === 'Download' && el.offsetParent !== null);
                            if (idx >= spans.length) return;
                            const el = spans[idx];
                            // Try clicking parent chain until we find a clickable
                            const clickable = el.closest('a') || el.closest('button')
                                || el.parentElement?.closest('a') || el.parentElement?.closest('button')
                                || el.parentElement || el;
                            clickable.click();
                        }""", i)
                    download = dl_info.value
                    download.save_as(str(output_path))
                    downloaded.append(output_path)
                    log.info(f"Downloaded: {output_path.name}")
                except PlaywrightTimeout:
                    # Download event didn't fire — maybe it opened a new tab or uses fetch
                    log.warning(f"Download event timeout for button {i+1}, trying direct click...")
                    page.evaluate("""(idx) => {
                        const spans = [...document.querySelectorAll('span, a, button, div')]
                            .filter(el => el.textContent.trim() === 'Download' && el.offsetParent !== null);
                        if (idx >= spans.length) return;
                        spans[idx].click();
                    }""", i)
                    page.wait_for_timeout(5000)

                page.wait_for_timeout(2000)
            except Exception as e:
                log.warning(f"Download {i + 1} failed: {e}")

        if downloaded:
            return downloaded

    # Strategy 3: Fallback — standard Playwright selectors
    for selector in ['a:has-text("Download")', 'button:has-text("Download")',
                      'span:has-text("Download")', 'a[download]',
                      '[href*=".mp3"]', '[href*="download"]']:
        try:
            elements = page.query_selector_all(selector)
            visible = [el for el in elements if el.is_visible()]
            if visible:
                log.info(f"Fallback: found {len(visible)} elements: {selector}")
                for i, btn in enumerate(visible[:2]):
                    try:
                        ts = int(time.time())
                        output_path = OUTPUT_DIR / f"{safe_name}_gen{batch_num}_{i + 1}_{ts}.mp3"
                        with page.expect_download(timeout=60_000) as dl_info:
                            btn.click()
                        download = dl_info.value
                        download.save_as(str(output_path))
                        downloaded.append(output_path)
                        log.info(f"Downloaded: {output_path.name}")
                        page.wait_for_timeout(2000)
                    except Exception as e:
                        log.warning(f"Fallback download {i + 1} failed: {e}")
                if downloaded:
                    return downloaded
        except Exception:
            continue

    return downloaded


def generate_music(concept: MusicConcept) -> Path:
    """Generate a single music track (backward compatibility)."""
    mp3s = generate_music_batch(concept, count=1)
    return mp3s[0]
