"""Generate music on aimusicfactory.ai using Playwright.

Pipeline approach:
1. Submit all generations on the Generate page (wait ~4 min each)
2. Wait until 5 min have passed since the first generation
3. Go to My Music, click on each track card by name
4. On each track detail page, click the Download buttons to get MP3s
"""

import re
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from modules.concept_generator import MusicConcept
from config import OUTPUT_DIR, INPUT_DIR, HEADLESS, AIMUSICFACTORY_STATE_FILE
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
DOWNLOAD_READY_SEC = 300       # 5 min — minimum time from generation before downloads work

# JS to block File System Access API "Save As" dialogs
_BLOCK_SAVE_PICKER_JS = """
window.showSaveFilePicker = undefined;
window.showOpenFilePicker = undefined;
"""


def _send_cdp_download_behavior(cdp, download_dir: Path):
    """(Re-)send CDP command to auto-save downloads without 'Save As' dialog."""
    cdp.send("Browser.setDownloadBehavior", {
        "behavior": "allowAndName",
        "downloadPath": str(download_dir.resolve()),
        "eventsEnabled": True,
    })


def _validate_mp3(path: Path) -> bool:
    """Check if a file is a valid MP3 by inspecting header bytes and size.

    Returns True if the file looks like a real MP3, False otherwise.
    """
    if not path.exists():
        log.warning(f"Validation: file does not exist: {path}")
        return False

    size = path.stat().st_size
    if size < 50_000:  # Less than 50KB is suspicious for a music track
        log.warning(f"Validation: file too small ({size} bytes): {path.name}")
        return False

    header = path.read_bytes()[:16]
    log.info(f"Validation: {path.name} — {size} bytes, header: {header[:8].hex()}")

    # Valid MP3 starts with ID3 tag or MPEG audio frame sync (0xFF 0xFB/0xF3/0xF2/0xFA/0xE0-0xFF)
    if header[:3] == b'ID3':
        return True
    if len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0:
        return True

    # Check if it's HTML (downloaded error page instead of audio)
    text_preview = header[:16].decode("utf-8", errors="replace")
    log.warning(f"Validation FAILED: not an MP3 file. Preview: {text_preview!r}")
    return False


def generate_music_batch(concept: MusicConcept, count: int = 4) -> list[Path]:
    """Generate music on aimusicfactory.ai.

    Submits all generations, waits for downloads to be ready,
    then goes to My Music and downloads from each track's detail page.

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
        context_opts = {"viewport": {"width": 1920, "height": 1080}, "accept_downloads": True}
        if AIMUSICFACTORY_STATE_FILE.exists():
            context_opts["storage_state"] = str(AIMUSICFACTORY_STATE_FILE)
            log.info("Loading saved cookies")

        browser = p.chromium.launch(
            headless=False, channel="chrome", args=chrome_args,
        )
        context = browser.new_context(**context_opts)
        context.set_default_timeout(60_000)
        page = context.new_page()

        # Block "Save As" dialog from File System Access API
        page.add_init_script(_BLOCK_SAVE_PICKER_JS)

        # Force Chrome to auto-save downloads without "Save As" dialog
        cdp = context.new_cdp_session(page)
        _send_cdp_download_behavior(cdp, OUTPUT_DIR)

        # Check if logged in, prompt if not
        logged_in = _check_logged_in(page)
        if logged_in:
            log.info("Already logged in!")
            context.storage_state(path=str(AIMUSICFACTORY_STATE_FILE))
        else:
            page.evaluate("window.moveTo(100, 100)")
            log.info("Not logged in — browser moved on-screen. Please log in with Google.")
            input("\n>>> Press ENTER after you've logged in... ")
            AIMUSICFACTORY_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            context.storage_state(path=str(AIMUSICFACTORY_STATE_FILE))
            log.info(f"Session saved to: {AIMUSICFACTORY_STATE_FILE}")
            page.evaluate("window.moveTo(-2400, -2400)")

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

        # ── Phase 2: Wait for downloads to be ready (18 min from first gen) ──
        first_gen = generation_start_times[0]
        elapsed = time.time() - first_gen
        remaining = DOWNLOAD_READY_SEC - elapsed

        if remaining > 0:
            log.info(f"Waiting {remaining / 60:.1f} more minutes for downloads to become available...")
            _wait_with_progress(page, remaining)
        else:
            log.info("Enough time has passed — downloads should be ready")

        # ── Phase 3: Go to My Music, find track cards, download from each ──
        log.info(f"\nGoing to My Music to find '{concept.track_name}' cards...")
        all_mp3s = _download_from_mymusic(
            page, concept, safe_name, len(generation_start_times),
            cdp=cdp, download_dir=OUTPUT_DIR,
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
    """Fill form and click Generate, then wait for generation to complete."""
    log.info("Navigating to Generate page...")
    page.goto("https://aimusicfactory.ai/#Generate", wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(5000)
    page.screenshot(path=str(OUTPUT_DIR / f"debug_before_gen_{batch_num}.png"))

    _ensure_toggle_on(page, "Custom Mode")
    page.wait_for_timeout(500)
    _ensure_toggle_on(page, "Instrumental")
    page.wait_for_timeout(500)

    # Verify Instrumental is ON
    lyrics_el = page.query_selector('textarea[name="prompt"]')
    if lyrics_el and lyrics_el.is_visible():
        log.warning("Instrumental toggle didn't work — lyrics field still visible. Clicking again...")
        page.click('text="Instrumental"', timeout=5000)
        page.wait_for_timeout(1000)

    _debug_form_fields(page)
    _fill_form_fields(page, concept, batch_num)
    page.screenshot(path=str(OUTPUT_DIR / f"debug_fields_filled_{batch_num}.png"))

    # Click Generate button — dump all buttons first for debugging
    all_buttons = page.query_selector_all('button, [role="button"], div[onclick], a.btn, a.button')
    log.info(f"Found {len(all_buttons)} button-like elements on page:")
    for i, b in enumerate(all_buttons):
        try:
            txt = (b.text_content() or "").strip()[:80]
            tag = b.evaluate("el => el.tagName")
            cls = b.get_attribute("class") or ""
            visible = b.is_visible()
            log.info(f"  btn[{i}]: <{tag}> text='{txt}' visible={visible} class='{cls[:120]}'")
        except Exception:
            pass

    clicked = False
    for selector in [
        'button:has-text("Generate")', 'button:has-text("Create")',
        'button:has-text("Make")', '[type="submit"]',
        'div:has-text("Generate")', 'span:has-text("Generate")',
        'a:has-text("Generate")', '[role="button"]:has-text("Generate")',
        'button:has-text("generate")', 'div:has-text("generate")',
        ".generate-btn", "#generate",
        # Gradient/colored large buttons (common on this site)
        'button.bg-gradient', 'button[class*="gradient"]',
        'div[class*="gradient"]:has-text("Generate")',
        'button[class*="rounded"][class*="bg-"]',
    ]:
        try:
            btn = page.wait_for_selector(selector, timeout=2000)
            if btn and btn.is_visible():
                btn.click()
                clicked = True
                log.info(f"Clicked: {selector}")
                break
        except PlaywrightTimeout:
            continue

    # Last resort: find any visible button via JS
    if not clicked:
        log.info("Standard selectors failed, trying JS button search...")
        clicked = page.evaluate("""() => {
            const elements = document.querySelectorAll('button, [role="button"], div, span, a');
            for (const el of elements) {
                const text = (el.textContent || '').trim().toLowerCase();
                const rect = el.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0 && rect.width < 500 &&
                    (text === 'generate' || text === 'create' || text === 'create music' || text === 'generate music')) {
                    el.click();
                    return true;
                }
            }
            return false;
        }""")
        if clicked:
            log.info("Clicked Generate button via JS fallback")

    if not clicked:
        page.screenshot(path=str(OUTPUT_DIR / f"debug_no_button_{batch_num}.png"))
        raise RuntimeError("Could not find Generate button")

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


# ── Phase 3: My Music -> click cards -> download from detail pages ──

def _download_from_mymusic(page, concept: MusicConcept, safe_name: str, expected_cards: int,
                           cdp=None, download_dir: Path = None) -> list[Path]:
    """Navigate to My Music, find track cards by name, open each, download MP3s.

    The site renders a CSS grid of square cards on /myMusic. Each card has:
    - Album art image
    - Track name text at bottom
    - v8.0 badge, star icon
    The first card is a "+" button (create new) — skip it.

    Cards are NOT <a> tags — they are div elements with click handlers.
    Clicking a card navigates to a detail page with a green "Download" button
    that opens a popover with "Audio" option to download the MP3.
    """
    if download_dir is None:
        download_dir = OUTPUT_DIR
    page.goto("https://aimusicfactory.ai/myMusic", wait_until="domcontentloaded", timeout=60_000)
    if cdp:
        _send_cdp_download_behavior(cdp, download_dir)
    page.wait_for_timeout(15_000)

    # Scroll down to load all cards (lazy loading / infinite scroll)
    _scroll_page(page)
    page.screenshot(path=str(OUTPUT_DIR / "debug_mymusic.png"))

    # Save HTML for debugging
    html = page.content()
    (OUTPUT_DIR / "debug_mymusic.html").write_text(html, encoding="utf-8")
    log.info(f"My Music page loaded ({len(html)} chars)")

    # Check page has actual content (images = track cards)
    img_count = page.evaluate("() => document.querySelectorAll('img').length")
    log.info(f"Images on page: {img_count}")

    track_name = concept.track_name

    # ── PRIMARY STRATEGY: Find grid cards (divs with images + track names) ──
    grid_cards = _find_grid_cards(page, track_name)

    # If no cards found, try search box
    if not grid_cards:
        log.warning(f"No grid cards found for '{track_name}' — trying search box...")
        _search_mymusic(page, track_name)
        page.wait_for_timeout(5000)
        _scroll_page(page)
        page.screenshot(path=str(OUTPUT_DIR / "debug_mymusic_search.png"))
        grid_cards = _find_grid_cards(page, track_name)

    # If still no cards, reload and retry
    if not grid_cards:
        log.warning(f"Still no cards — reloading My Music page...")
        page.goto("https://aimusicfactory.ai/myMusic", wait_until="domcontentloaded", timeout=60_000)
        if cdp:
            _send_cdp_download_behavior(cdp, download_dir)
        page.wait_for_timeout(15_000)
        _scroll_page(page)
        grid_cards = _find_grid_cards(page, track_name)

    if not grid_cards:
        log.error(f"No track cards found on My Music for '{track_name}'!")
        _log_page_structure(page)
        page.screenshot(path=str(OUTPUT_DIR / "debug_no_cards.png"))
        return []

    # Filter: prefer cards matching our track name, otherwise take latest
    name_matches = [c for c in grid_cards if c.get("nameMatch")]
    if name_matches:
        cards_to_use = name_matches
        log.info(f"Found {len(cards_to_use)} card(s) matching '{track_name}'")
    else:
        cards_to_use = grid_cards[:expected_cards]
        log.info(f"No name match — using latest {len(cards_to_use)} card(s)")

    # ── Click each card -> navigate to detail -> download MP3 ──
    all_mp3s = []
    for i, card_info in enumerate(cards_to_use):
        card_num = i + 1
        card_name = card_info.get("name", "?")
        log.info(f"\n--- Card {card_num}/{len(cards_to_use)}: '{card_name}' ---")

        try:
            # Navigate back to My Music before each click (except the first)
            if i > 0:
                page.goto("https://aimusicfactory.ai/myMusic",
                          wait_until="domcontentloaded", timeout=60_000)
                if cdp:
                    _send_cdp_download_behavior(cdp, download_dir)
                page.wait_for_timeout(10_000)
                _scroll_page(page)

            old_url = page.url
            clicked = _click_grid_card(page, card_info)
            if not clicked:
                log.warning(f"Card {card_num}: click failed, skipping")
                continue

            page.wait_for_timeout(5_000)
            new_url = page.url
            if cdp:
                _send_cdp_download_behavior(cdp, download_dir)
            log.info(f"Card {card_num}: navigated {old_url} -> {new_url}")
            page.screenshot(path=str(OUTPUT_DIR / f"debug_detail_{card_num}.png"))

            # Save detail page HTML
            detail_html = page.content()
            (OUTPUT_DIR / f"debug_detail_{card_num}.html").write_text(
                detail_html, encoding="utf-8")

            # Extract song ID from URL
            song_id = str(int(time.time()))
            song_id_match = re.search(r'/(\d+)', new_url)
            if song_id_match:
                song_id = song_id_match.group(1)

            _wait_for_download_button(page, card_num)
            downloaded = _download_mp3s_from_detail(page, safe_name, card_num, song_id,
                                                    download_dir=download_dir)
            all_mp3s.extend(downloaded)
            log.info(f"Card {card_num}: downloaded {len(downloaded)} MP3(s)")

        except Exception as e:
            log.warning(f"Card {card_num} failed: {e}")
            page.screenshot(path=str(OUTPUT_DIR / f"debug_card_fail_{card_num}.png"))

    return all_mp3s


def _find_grid_cards(page, track_name: str) -> list[dict]:
    """Find track cards in the My Music CSS grid.

    The site renders a grid of square cards. Each card has:
    - Album art <img>
    - Track name text at the bottom
    - v8.0 badge, star icon
    The first card is a "+" button (create new) — skip it.

    Cards are NOT <a> tags — they are div elements with click handlers.

    Returns list of dicts sorted by name match, then newest first:
    [{gridIndex, name, nameMatch, hasImage, width, height}, ...]
    """
    cards = page.evaluate("""(trackName) => {
        const lowerName = trackName ? trackName.toLowerCase() : '';
        const results = [];

        // ── Strategy A: Find the grid container ──
        // Look for a parent element with many children that each have an <img>.
        // This matches the card grid layout seen in screenshots.
        let bestContainer = null;
        let bestImgCount = 0;

        const containers = document.querySelectorAll('div, section, main, ul');
        for (const c of containers) {
            if (c.closest('nav') || c.closest('footer') || c.closest('header')) continue;
            const children = c.children;
            if (children.length < 3 || children.length > 100) continue;

            // Count children that have an <img> AND are visible
            let imgChildren = 0;
            for (const child of children) {
                if (child.offsetParent === null) continue;
                if (child.querySelector('img')) imgChildren++;
            }

            // The grid with the most image-bearing children is likely our card grid
            if (imgChildren > bestImgCount) {
                bestImgCount = imgChildren;
                bestContainer = c;
            }
        }

        if (!bestContainer || bestImgCount < 2) {
            // ── Strategy B: Find all visible elements with images ──
            // Fallback: look for any square-ish elements with images
            const allImgParents = document.querySelectorAll('div, li, article');
            for (const el of allImgParents) {
                if (el.closest('nav') || el.closest('footer') || el.closest('header')) continue;
                if (el.offsetParent === null) continue;
                if (!el.querySelector('img')) continue;

                const rect = el.getBoundingClientRect();
                // Card-like: roughly square, between 100-500px
                if (rect.width < 100 || rect.width > 500) continue;
                if (rect.height < 100 || rect.height > 500) continue;
                const ratio = rect.width / rect.height;
                if (ratio < 0.5 || ratio > 2.0) continue;

                // Get the track name from the card text
                // Track name is usually the last short text in the card
                const textNodes = [];
                const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
                while (walker.nextNode()) {
                    const t = walker.currentNode.textContent.trim();
                    if (t.length >= 2 && t.length <= 60) textNodes.push(t);
                }
                // Skip cards with no text or only version badges
                const name = textNodes.filter(t => !t.match(/^v\\d/) && t !== '+')
                    .pop() || '';
                if (!name) continue;

                results.push({
                    gridIndex: results.length,
                    name: name,
                    nameMatch: lowerName ? name.toLowerCase() === lowerName : false,
                    hasImage: true,
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                });
            }
        } else {
            // We found the grid container — iterate its children
            const children = bestContainer.children;
            for (let i = 0; i < children.length; i++) {
                const child = children[i];
                if (child.offsetParent === null) continue;
                if (!child.querySelector('img')) continue;

                const rect = child.getBoundingClientRect();
                if (rect.width < 80 || rect.height < 80) continue;

                // Get text content to find track name
                const textNodes = [];
                const walker = document.createTreeWalker(child, NodeFilter.SHOW_TEXT);
                while (walker.nextNode()) {
                    const t = walker.currentNode.textContent.trim();
                    if (t.length >= 1 && t.length <= 60) textNodes.push(t);
                }

                // The track name is typically the last meaningful text
                // Filter out badges like "v8.0" and the "+" create button
                const meaningfulTexts = textNodes.filter(
                    t => !t.match(/^v\\d/) && t !== '+' && t.length >= 2
                );
                const name = meaningfulTexts.pop() || '';

                // Skip the "+" create card (has no track name)
                if (!name || name === '+') continue;

                results.push({
                    gridIndex: i,  // Position in the grid container
                    name: name,
                    nameMatch: lowerName ? name.toLowerCase() === lowerName : false,
                    hasImage: true,
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                    containerChildCount: children.length,
                });
            }
        }

        // Sort: name matches first, then by grid position (newest = first)
        results.sort((a, b) => {
            if (a.nameMatch !== b.nameMatch) return b.nameMatch ? 1 : -1;
            return a.gridIndex - b.gridIndex;
        });

        return results;
    }""", track_name)

    log.info(f"_find_grid_cards('{track_name}'): found {len(cards)} card(s)")
    for c in cards[:15]:
        match_str = "MATCH" if c.get("nameMatch") else ""
        log.info(f"  [{c.get('gridIndex')}] '{c.get('name')}' "
                 f"{c.get('width')}x{c.get('height')} {match_str}")

    return cards


def _click_grid_card(page, card_info: dict) -> bool:
    """Click a specific grid card on My Music page to navigate to its detail page.

    Uses the card's grid index and name to re-find and click it.
    Returns True if navigation happened.
    """
    grid_index = card_info.get("gridIndex", -1)
    card_name = card_info.get("name", "")

    log.info(f"Clicking grid card [{grid_index}]: '{card_name}'")

    result = page.evaluate("""(args) => {
        const {gridIndex, cardName} = args;
        const lowerName = cardName.toLowerCase();

        // Re-find the grid container (same logic as _find_grid_cards)
        let bestContainer = null;
        let bestImgCount = 0;

        const containers = document.querySelectorAll('div, section, main, ul');
        for (const c of containers) {
            if (c.closest('nav') || c.closest('footer') || c.closest('header')) continue;
            const children = c.children;
            if (children.length < 3 || children.length > 100) continue;

            let imgChildren = 0;
            for (const child of children) {
                if (child.offsetParent === null) continue;
                if (child.querySelector('img')) imgChildren++;
            }

            if (imgChildren > bestImgCount) {
                bestImgCount = imgChildren;
                bestContainer = c;
            }
        }

        if (!bestContainer) return 'no_grid';

        // Try to click by grid index first
        const children = bestContainer.children;
        if (gridIndex >= 0 && gridIndex < children.length) {
            const target = children[gridIndex];
            // Verify it still has the right name
            const text = target.textContent.toLowerCase();
            if (text.includes(lowerName) || !cardName) {
                target.click();
                return 'clicked_by_index';
            }
        }

        // Fallback: find by name match
        for (const child of children) {
            if (child.offsetParent === null) continue;
            const text = child.textContent.toLowerCase();
            if (text.includes(lowerName)) {
                child.click();
                return 'clicked_by_name';
            }
        }

        return 'not_found';
    }""", {"gridIndex": grid_index, "cardName": card_name})

    log.info(f"Click result: {result}")

    if result == "not_found" or result == "no_grid":
        log.warning(f"Grid card '{card_name}' not found")
        return False

    page.wait_for_timeout(5000)
    return True


def _log_page_structure(page):
    """Log detailed DOM structure of My Music page for debugging.

    Called when <a>-based card detection finds nothing, to help understand
    what the actual card elements look like.
    """
    info = page.evaluate("""() => {
        const result = {url: location.href, title: document.title};

        // Count visible elements by type
        const tagCounts = {};
        const allEls = document.querySelectorAll('*');
        for (const el of allEls) {
            if (el.offsetParent === null) continue;
            const tag = el.tagName;
            tagCounts[tag] = (tagCounts[tag] || 0) + 1;
        }
        result.visibleTags = tagCounts;

        // Find all unique class names that might indicate cards
        const cardClasses = new Set();
        const els = document.querySelectorAll('[class]');
        for (const el of els) {
            if (el.offsetParent === null) continue;
            const cls = el.className.toString().toLowerCase();
            if (cls.match(/card|track|song|item|music|list|grid|row|entry/)) {
                cardClasses.add(el.tagName + '.' + el.className.toString().substring(0, 80));
            }
        }
        result.cardLikeClasses = [...cardClasses].slice(0, 30);

        // Find elements with duration-like text (e.g., "3:45")
        const durationEls = [];
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        while (walker.nextNode()) {
            const text = walker.currentNode.textContent.trim();
            if (/^\\d{1,2}:\\d{2}$/.test(text)) {
                const parent = walker.currentNode.parentElement;
                if (parent) {
                    let card = parent;
                    for (let i = 0; i < 10; i++) {
                        if (!card.parentElement) break;
                        card = card.parentElement;
                        if (card.children.length > 1) break;
                    }
                    durationEls.push({
                        duration: text,
                        parentTag: parent.tagName,
                        parentClass: (parent.className || '').toString().substring(0, 50),
                        cardTag: card.tagName,
                        cardClass: (card.className || '').toString().substring(0, 80),
                        cardText: card.textContent.trim().substring(0, 100),
                    });
                }
            }
        }
        result.durationElements = durationEls.slice(0, 10);

        // Find all images on the page (cards usually have images)
        const images = [];
        for (const img of document.querySelectorAll('img')) {
            if (img.offsetParent === null) continue;
            const rect = img.getBoundingClientRect();
            if (rect.width < 30 || rect.height < 30) continue;
            const parent = img.parentElement;
            images.push({
                src: (img.src || '').substring(0, 80),
                size: Math.round(rect.width) + 'x' + Math.round(rect.height),
                parentTag: parent ? parent.tagName : '?',
                parentClass: parent ? (parent.className || '').toString().substring(0, 50) : '',
            });
        }
        result.significantImages = images.slice(0, 15);

        return result;
    }""")

    log.info(f"=== MY MUSIC PAGE STRUCTURE ===")
    log.info(f"  URL: {info.get('url')}")
    log.info(f"  Title: {info.get('title')}")

    tags = info.get("visibleTags", {})
    top_tags = sorted(tags.items(), key=lambda x: -x[1])[:15]
    log.info(f"  Top visible tags: {', '.join(f'{t}:{c}' for t,c in top_tags)}")

    card_classes = info.get("cardLikeClasses", [])
    if card_classes:
        log.info(f"  Card-like classes ({len(card_classes)}):")
        for cls in card_classes[:15]:
            log.info(f"    {cls}")
    else:
        log.info("  No card-like classes found")

    dur_els = info.get("durationElements", [])
    if dur_els:
        log.info(f"  Duration elements ({len(dur_els)}):")
        for d in dur_els[:5]:
            log.info(f"    {d.get('duration')} in [{d.get('cardTag')}.{d.get('cardClass', '')[:30]}] "
                     f"text='{d.get('cardText', '')[:50]}'")
    else:
        log.info("  No duration elements found")

    images = info.get("significantImages", [])
    if images:
        log.info(f"  Significant images ({len(images)}):")
        for img in images[:8]:
            log.info(f"    {img.get('size')} in [{img.get('parentTag')}.{img.get('parentClass', '')[:30]}] "
                     f"src={img.get('src', '')[:50]}")
    else:
        log.info("  No significant images found")

    log.info(f"=== END PAGE STRUCTURE ===")



def _scroll_page(page):
    """Scroll the page down to trigger lazy loading of cards."""
    page.evaluate("""async () => {
        for (let i = 0; i < 5; i++) {
            window.scrollBy(0, window.innerHeight);
            await new Promise(r => setTimeout(r, 1500));
        }
        window.scrollTo(0, 0);
        await new Promise(r => setTimeout(r, 1000));
    }""")
    page.wait_for_timeout(2000)


def _search_mymusic(page, track_name: str):
    """Use the search box on My Music to filter by track name."""
    try:
        # The search box has placeholder "title/lyric/description/style"
        search_input = page.query_selector('input[placeholder*="title"]')
        if not search_input:
            search_input = page.query_selector('input[type="text"]')
        if not search_input:
            search_input = page.query_selector('input[type="search"]')

        if search_input and search_input.is_visible():
            search_input.click()
            search_input.fill(track_name)
            log.info(f"Filled search box with: {track_name}")

            # Click Search button
            for sel in ['button:has-text("Search")', 'button[type="submit"]']:
                try:
                    btn = page.query_selector(sel)
                    if btn and btn.is_visible():
                        btn.click()
                        log.info(f"Clicked: {sel}")
                        page.wait_for_timeout(3000)
                        return
                except Exception:
                    continue

            # Press Enter as fallback
            search_input.press("Enter")
            log.info("Pressed Enter in search box")
        else:
            log.warning("Search input not found on My Music page")
    except Exception as e:
        log.warning(f"Search failed: {e}")


def _wait_for_download_button(page, card_num: int):
    """Wait for Download button(s) to appear on the track detail page."""
    log.info(f"Card {card_num}: waiting for Download button...")

    for attempt in range(1, 5):
        try:
            page.wait_for_selector('text="Download"', timeout=15_000)
            log.info(f"Card {card_num}: Download button(s) visible!")
            page.wait_for_timeout(2000)
            page.screenshot(path=str(OUTPUT_DIR / f"debug_dl_ready_{card_num}.png"))
            return
        except PlaywrightTimeout:
            log.warning(f"Card {card_num}: Download not found (attempt {attempt}/4)")
            if attempt < 4:
                page.reload(wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(8_000)

    log.warning(f"Card {card_num}: Download button not found after 4 attempts, trying anyway")
    page.screenshot(path=str(OUTPUT_DIR / f"debug_dl_notfound_{card_num}.png"))


def _download_mp3s_from_detail(page, safe_name: str, card_num: int, song_id: str = "",
                               download_dir: Path = None) -> list[Path]:
    """Click all Download buttons on a track detail page and save MP3s.

    From screenshots: each track has a green gradient "Download" button.
    Clicking it opens a popover with "Audio" option.
    Files are saved as: TrackName_1.mp3, TrackName_2.mp3, etc. (sequential).
    """
    if download_dir is None:
        download_dir = OUTPUT_DIR
    # Save page HTML for debugging
    try:
        html = page.content()
        (OUTPUT_DIR / f"debug_detail_page_{card_num}.html").write_text(html, encoding="utf-8")
    except Exception:
        pass

    # Count Download buttons (green buttons with "Download" text, outside footer)
    dl_button_count = page.evaluate("""() => {
        // Find all elements with "Download" text that are visible and not in footer
        const candidates = [];

        // Check HeadlessUI popover buttons
        const popovers = document.querySelectorAll('[id^="headlessui-popover-button"]');
        for (const p of popovers) {
            if (p.textContent.includes('Download') && p.offsetParent !== null) {
                candidates.push(p);
            }
        }
        if (candidates.length > 0) return {type: 'popover', count: candidates.length};

        // Check buttons/divs with Download text (green gradient buttons)
        const allEls = document.querySelectorAll('button, div, a, span');
        for (const el of allEls) {
            if (el.closest('footer')) continue;
            if (el.offsetParent === null) continue;
            // Check own text content
            const ownText = el.textContent.trim();
            if (ownText === 'Download' || ownText === 'Download ❓' || ownText.startsWith('Download')) {
                // Make sure it's a clickable-looking element (not a child span inside another match)
                const tag = el.tagName.toLowerCase();
                if (tag === 'button' || tag === 'a' || el.getAttribute('role') === 'button'
                    || el.classList.toString().includes('cursor')
                    || el.style.cursor === 'pointer') {
                    candidates.push(el);
                }
            }
        }
        if (candidates.length > 0) return {type: 'button', count: candidates.length};

        return {type: 'none', count: 0};
    }""")

    btn_type = dl_button_count.get("type", "none")
    btn_count = dl_button_count.get("count", 0)
    log.info(f"Found {btn_count} Download element(s) (type: {btn_type})")

    if btn_count == 0:
        log.warning("No Download buttons found on detail page!")
        page.screenshot(path=str(OUTPUT_DIR / f"debug_no_dlbtn_{card_num}.png"))

        # Debug: log all visible buttons
        visible_buttons = page.evaluate("""() => {
            const result = [];
            const els = document.querySelectorAll('button, a, [role="button"]');
            els.forEach(el => {
                if (el.offsetParent !== null) {
                    result.push(el.tagName + ': ' + el.textContent.trim().substring(0, 60));
                }
            });
            return result;
        }""")
        for vb in visible_buttons[:20]:
            log.info(f"  visible element: {vb}")

        return []

    downloaded = []

    for i in range(btn_count):
        try:
            # Sequential naming: TrackName_1.mp3, TrackName_2.mp3, ...
            # Find next available number to avoid overwriting existing files
            seq = 1
            while (download_dir / f"{safe_name}_{seq}.mp3").exists():
                seq += 1
            output_path = download_dir / f"{safe_name}_{seq}.mp3"

            log.info(f"Clicking Download button {i + 1}/{btn_count}...")

            if btn_type == "popover":
                # HeadlessUI popover — click to open, then find MP3 in panel
                mp3_path = _download_via_popover(page, i, output_path, card_num)
            else:
                # Direct button — click and expect download event
                mp3_path = _download_via_button(page, i, output_path, card_num)

            if mp3_path:
                downloaded.append(mp3_path)
                log.info(f"Downloaded: {mp3_path.name}")

        except Exception as e:
            log.warning(f"Download {i + 1} failed: {e}")

    return downloaded


def _download_via_popover(page, idx: int, output_path: Path, card_num: int) -> Path | None:
    """Download MP3 via HeadlessUI popover dropdown.

    From screenshots: clicking Download opens a dropdown with 'Audio' option.
    The site uses JS fetch → blob → <a download> pattern, so we set up network
    interception BEFORE clicking to capture the actual audio URL/data.
    """
    import requests as req

    # Click the popover button to open dropdown
    page.evaluate("""(idx) => {
        const popovers = [...document.querySelectorAll('[id^="headlessui-popover-button"]')]
            .filter(p => p.textContent.includes('Download') && p.offsetParent !== null);
        if (idx < popovers.length) popovers[idx].click();
    }""", idx)

    page.wait_for_timeout(2000)
    page.screenshot(path=str(OUTPUT_DIR / f"debug_popover_{card_num}_{idx + 1}.png"))

    # Log panel buttons for debugging (strip SVG noise, check enabled state)
    panel_info = page.evaluate("""() => {
        const panels = document.querySelectorAll('[id^="headlessui-popover-panel"]');
        if (panels.length === 0) return {exists: false, buttons: [], html: 'NO_PANEL'};
        const panel = panels[panels.length - 1];
        const buttons = [];
        const clickables = panel.querySelectorAll('button, a, li, [role="menuitem"]');
        for (const el of clickables) {
            // Get text without SVG content
            let text = '';
            for (const node of el.childNodes) {
                if (node.nodeType === 3) {  // TEXT_NODE
                    text += node.textContent;
                } else if (node.nodeType === 1 && node.tagName !== 'SVG' && node.tagName !== 'svg') {
                    // Skip SVG elements, get text from other children
                    const inner = node.textContent || '';
                    if (!node.querySelector('svg')) text += inner;
                }
            }
            text = text.trim();
            if (!text) {
                // Fallback: use full textContent
                text = el.textContent.trim().substring(0, 50);
            }
            buttons.push({
                tag: el.tagName,
                text: text,
                href: el.getAttribute('href') || '',
                disabled: el.disabled || el.hasAttribute('disabled')
                    || el.getAttribute('aria-disabled') === 'true'
                    || el.classList.contains('opacity-50')
                    || el.classList.contains('cursor-not-allowed')
                    || getComputedStyle(el).pointerEvents === 'none'
                    || getComputedStyle(el).opacity < 0.6,
            });
        }
        return {
            exists: true,
            buttons: buttons,
            html: panel.innerHTML.substring(0, 1000),
            panelId: panel.id || '',
        };
    }""")

    if not panel_info.get("exists"):
        log.warning(f"No popover panel found (card {card_num}, btn {idx + 1})")
        return None

    log.info(f"Popover panel buttons ({len(panel_info.get('buttons', []))}):")
    for btn in panel_info.get("buttons", []):
        disabled_str = " [DISABLED]" if btn.get("disabled") else ""
        log.info(f"  <{btn['tag']}> text='{btn['text']}' href='{btn['href']}'{disabled_str}")

    # Check if Audio button is disabled — skip immediately instead of waiting 30s
    audio_disabled = False
    for btn in panel_info.get("buttons", []):
        if btn.get("text", "").strip().lower() == "audio" and btn.get("tag") == "BUTTON":
            if btn.get("disabled"):
                audio_disabled = True
                break
    if audio_disabled:
        log.warning(f"Audio button is DISABLED (card {card_num}, btn {idx + 1}) — song not ready, skipping")
        page.evaluate("document.body.click()")
        page.wait_for_timeout(500)
        return None

    # Snapshot existing files in download dir before clicking (for fallback detection)
    dl_dir = output_path.parent
    existing_files = set(dl_dir.glob("*"))

    # ── Set up network interception BEFORE clicking Audio ──
    # The site uses JS fetch → blob → <a download>, so the actual audio data
    # travels as a network response BEFORE the download event fires.
    captured_responses = []

    def on_response(response):
        url = response.url
        ct = response.headers.get("content-type", "")
        size = int(response.headers.get("content-length", "0") or "0")
        is_audio = ("audio" in ct or "octet-stream" in ct
                    or ".mp3" in url or ".wav" in url)
        is_api_dl = ("download" in url.lower() and size > 10_000) or is_audio
        if is_audio or is_api_dl:
            log.info(f"  [network] {url[:100]} ct={ct} size={size}")
            captured_responses.append({"url": url, "ct": ct, "size": size})

    page.on("response", on_response)

    # Find the Audio button locator
    panel_sel = '[id^="headlessui-popover-panel"]'
    panel_loc = page.locator(panel_sel).last

    audio_loc = None
    for text_match in ["Audio", "audio", "MP3", "mp3"]:
        loc = panel_loc.locator("button").filter(has_text=text_match)
        if loc.count() > 0:
            audio_loc = loc.first
            log.info(f"Found audio <button> by text: '{text_match}'")
            break

    if not audio_loc:
        for text_match in ["Audio", "audio", "MP3", "mp3"]:
            loc = panel_loc.get_by_text(text_match, exact=False)
            if loc.count() > 0:
                audio_loc = loc.first
                log.info(f"Found audio option by text: '{text_match}'")
                break

    if not audio_loc:
        first_btn = panel_loc.locator("button, a").first
        if first_btn.count() > 0:
            audio_loc = first_btn
            log.info("No 'Audio' text found, clicking first button in panel")
        else:
            log.warning("No clickable elements in popover panel")
            page.remove_listener("response", on_response)
            page.evaluate("document.body.click()")
            return None

    # ── Strategy 1: Playwright click + expect_download ──
    download_ok = False
    try:
        with page.expect_download(timeout=30_000) as dl_info:
            audio_loc.click()

        download = dl_info.value
        # Wait for the download to fully complete
        failure = download.failure()
        if failure:
            log.warning(f"Strategy 1: download failed: {failure}")
        else:
            download.save_as(str(output_path))
            log.info(f"Strategy 1 (Playwright click): downloaded {output_path.name}")
            if _validate_mp3(output_path):
                download_ok = True
            else:
                log.warning(f"Strategy 1: downloaded file is NOT a valid MP3 (0 bytes or bad header)")
                output_path.unlink(missing_ok=True)

    except PlaywrightTimeout:
        log.warning(f"Strategy 1 timeout (card {card_num}, btn {idx + 1})")

    except Exception as e:
        log.warning(f"Strategy 1 error: {e}")

    if download_ok:
        page.remove_listener("response", on_response)
        page.evaluate("document.body.click()")
        page.wait_for_timeout(1000)
        return output_path

    # ── Strategy 2: Check captured network responses (set up BEFORE click) ──
    # Give extra time for async fetch to complete
    page.wait_for_timeout(5_000)
    page.remove_listener("response", on_response)

    if captured_responses:
        # Pick the best captured URL (prefer audio content-type, largest size)
        captured_responses.sort(key=lambda r: (
            1 if "audio" in r["ct"] else 0,
            r["size"],
        ), reverse=True)
        best = captured_responses[0]
        log.info(f"Strategy 2: using captured URL: {best['url'][:100]} (ct={best['ct']}, size={best['size']})")

        try:
            cookies = page.context.cookies()
            cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
            resp = req.get(best["url"], headers={
                "Cookie": cookie_str,
                "Referer": page.url,
                "User-Agent": page.evaluate("() => navigator.userAgent"),
            }, timeout=120, stream=True)

            # Stream to file to handle large responses
            total = 0
            with open(output_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    f.write(chunk)
                    total += len(chunk)

            log.info(f"Strategy 2 (network capture): saved {output_path.name} ({total} bytes)")
            if _validate_mp3(output_path):
                page.evaluate("document.body.click()")
                page.wait_for_timeout(1000)
                return output_path
            else:
                log.warning(f"Strategy 2: file is NOT a valid MP3, deleting")
                output_path.unlink(missing_ok=True)
        except Exception as e:
            log.warning(f"Strategy 2 download error: {e}")
    else:
        log.warning(f"Strategy 2: no audio network responses captured")

    # ── Strategy 3: Check for <a href> with direct download URL in popover ──
    try:
        audio_url = page.evaluate("""() => {
            const panels = document.querySelectorAll('[id^="headlessui-popover-panel"]');
            for (const panel of panels) {
                const links = panel.querySelectorAll('a[href]');
                for (const a of links) {
                    const text = a.textContent.toLowerCase();
                    const href = a.href;
                    if (href && (text.includes('audio') || text.includes('mp3')
                        || href.includes('.mp3') || href.includes('audio'))) {
                        return href;
                    }
                }
                const buttons = panel.querySelectorAll('button[data-url], button[data-href]');
                for (const btn of buttons) {
                    const url = btn.getAttribute('data-url') || btn.getAttribute('data-href');
                    if (url) return url;
                }
                if (links.length > 0) return links[0].href;
            }
            return null;
        }""")

        if audio_url:
            log.info(f"Strategy 3: found direct URL: {audio_url[:100]}")
            cookies = page.context.cookies()
            cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
            resp = req.get(audio_url, headers={
                "Cookie": cookie_str,
                "Referer": page.url,
            }, timeout=120)
            if resp.status_code == 200 and len(resp.content) > 10_000:
                output_path.write_bytes(resp.content)
                log.info(f"Strategy 3 (direct URL): downloaded {output_path.name} ({len(resp.content)} bytes)")
                page.evaluate("document.body.click()")
                page.wait_for_timeout(1000)
                if _validate_mp3(output_path):
                    return output_path
                else:
                    log.warning(f"Strategy 3: file is NOT a valid MP3, deleting")
                    output_path.unlink(missing_ok=True)
            else:
                log.warning(f"Strategy 3: HTTP {resp.status_code}, size {len(resp.content)}")
    except Exception as e:
        log.warning(f"Strategy 3 error: {e}")

    # ── Strategy 4: Check if CDP auto-saved the file to download dir ──
    new_files = set(dl_dir.glob("*")) - existing_files
    audio_files = [f for f in new_files if f.suffix.lower() in (".mp3", ".wav", ".m4a")]
    if audio_files:
        src = max(audio_files, key=lambda f: f.stat().st_mtime)
        if _validate_mp3(src):
            src.rename(output_path)
            log.info(f"Strategy 4 (CDP auto-save): found {src.name} -> {output_path.name}")
            page.evaluate("document.body.click()")
            page.wait_for_timeout(1000)
            return output_path
        else:
            log.warning(f"Strategy 4: {src.name} is not a valid MP3")
            src.unlink(missing_ok=True)

    # ── Strategy 5: Re-open popover, click Audio again with fresh network capture ──
    try:
        log.info("Strategy 5: re-clicking Audio with fresh network capture...")
        captured_retry = []

        def on_response_retry(response):
            url = response.url
            ct = response.headers.get("content-type", "")
            if ("audio" in ct or "octet-stream" in ct
                    or ".mp3" in url or ".wav" in url):
                captured_retry.append(url)

        page.on("response", on_response_retry)

        # Re-open popover
        page.evaluate("""(idx) => {
            document.body.click();  // close any open popover
            setTimeout(() => {
                const popovers = [...document.querySelectorAll('[id^="headlessui-popover-button"]')]
                    .filter(p => p.textContent.includes('Download') && p.offsetParent !== null);
                if (idx < popovers.length) popovers[idx].click();
            }, 500);
        }""", idx)
        page.wait_for_timeout(2000)

        # Click Audio again
        panel_loc = page.locator('[id^="headlessui-popover-panel"]').last
        for text_match in ["Audio", "audio", "MP3", "mp3"]:
            loc = panel_loc.get_by_text(text_match, exact=False)
            if loc.count() > 0:
                loc.first.click()
                break

        # Wait longer for the network response
        page.wait_for_timeout(15_000)
        page.remove_listener("response", on_response_retry)

        if captured_retry:
            log.info(f"Strategy 5: captured URL: {captured_retry[0][:100]}")
            cookies = page.context.cookies()
            cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
            resp = req.get(captured_retry[0], headers={
                "Cookie": cookie_str,
                "Referer": page.url,
            }, timeout=120)
            if resp.status_code == 200 and len(resp.content) > 10_000:
                output_path.write_bytes(resp.content)
                log.info(f"Strategy 5 (retry capture): {output_path.name} ({len(resp.content)} bytes)")
                page.evaluate("document.body.click()")
                page.wait_for_timeout(1000)
                if _validate_mp3(output_path):
                    return output_path
                else:
                    log.warning(f"Strategy 5: file is NOT a valid MP3, deleting")
                    output_path.unlink(missing_ok=True)
            else:
                log.warning(f"Strategy 5: HTTP {resp.status_code}, size {len(resp.content)}")
        else:
            log.warning("Strategy 5: no audio response captured on retry")
    except Exception as e:
        log.warning(f"Strategy 5 error: {e}")

    # Close popover
    page.evaluate("document.body.click()")
    page.wait_for_timeout(1000)
    log.warning(f"All download strategies failed (card {card_num}, btn {idx + 1})")
    page.screenshot(path=str(OUTPUT_DIR / f"debug_popover_allfail_{card_num}_{idx + 1}.png"))
    return None


def _download_via_button(page, idx: int, output_path: Path, card_num: int) -> Path | None:
    """Download MP3 by clicking Download then Audio in the dropdown.

    Uses Playwright locator clicks for proper download event handling.
    """
    try:
        # Click the Download button first (JS click to open dropdown)
        page.evaluate("""(idx) => {
            const candidates = [];
            const allEls = document.querySelectorAll('button, div, a, span');
            for (const el of allEls) {
                if (el.closest('footer')) continue;
                if (el.offsetParent === null) continue;
                const ownText = el.textContent.trim();
                if (ownText === 'Download' || ownText.startsWith('Download')) {
                    const tag = el.tagName.toLowerCase();
                    if (tag === 'button' || tag === 'a' || el.getAttribute('role') === 'button'
                        || el.classList.toString().includes('cursor')
                        || el.style.cursor === 'pointer') {
                        candidates.push(el);
                    }
                }
            }
            if (idx < candidates.length) candidates[idx].click();
        }""", idx)

        page.wait_for_timeout(2000)

        # Check if a popover panel appeared
        panel_exists = page.evaluate("""() => {
            return document.querySelectorAll('[id^="headlessui-popover-panel"]').length > 0;
        }""")

        if panel_exists:
            log.info("Download button opened a popover — using popover download flow")
            return _download_via_popover(page, 0, output_path, card_num)

        # No popover — try Playwright click on "Audio" text anywhere visible
        with page.expect_download(timeout=30_000) as dl_info:
            audio_loc = page.get_by_text("Audio", exact=False)
            if audio_loc.count() > 0:
                audio_loc.first.click()
            else:
                # Click any visible dropdown option
                page.locator('[role="menuitem"], [role="option"]').first.click()

        download = dl_info.value
        download.save_as(str(output_path))
        page.wait_for_timeout(2000)
        if not _validate_mp3(output_path):
            log.warning(f"Direct download: file is NOT a valid MP3, deleting")
            output_path.unlink(missing_ok=True)
            return None
        return output_path

    except PlaywrightTimeout:
        log.warning(f"Direct download timeout (card {card_num}, btn {idx + 1})")
        page.screenshot(path=str(OUTPUT_DIR / f"debug_btn_timeout_{card_num}_{idx + 1}.png"))
        return None
    except Exception as e:
        log.warning(f"Direct download error (card {card_num}, btn {idx + 1}): {e}")
        return None


# ── Form helpers ──

def _debug_form_fields(page):
    """Log all visible form fields and save page HTML for analysis."""
    textareas = page.query_selector_all("textarea")
    visible_tas = [t for t in textareas if t.is_visible()]
    log.info(f"Visible textareas: {len(visible_tas)}")
    for i, ta in enumerate(visible_tas):
        ph = ta.get_attribute("placeholder") or ""
        name = ta.get_attribute("name") or ""
        cls = ta.get_attribute("class") or ""
        val = ta.input_value()[:30] if ta.input_value() else ""
        log.info(f"  textarea[{i}]: placeholder='{ph}' name='{name}' class='{cls}' value='{val}...'")

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

    try:
        html = page.content()
        html_path = OUTPUT_DIR / "debug_page.html"
        html_path.write_text(html, encoding="utf-8")
        log.info(f"Page HTML saved to: {html_path} ({len(html)} chars)")
    except Exception as e:
        log.warning(f"Could not save page HTML: {e}")


def _fill_form_fields(page, concept: MusicConcept, batch_num: int):
    """Fill the aimusicfactory.ai form fields."""
    style_filled = False
    title_filled = False

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
    """Ensure a HeadlessUI toggle (Custom Mode / Instrumental) is ON."""
    try:
        result = page.evaluate("""(labelText) => {
            const walker = document.createTreeWalker(
                document.body, NodeFilter.SHOW_TEXT, null);
            while (walker.nextNode()) {
                const text = walker.currentNode.textContent.trim();
                if (text === labelText || text.includes(labelText)) {
                    let el = walker.currentNode.parentElement;
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


def download_existing_tracks(track_name: str, max_cards: int = 4) -> list[Path]:
    """Go to My Music and download MP3s for tracks already generated.

    Skips generation and waiting — just opens the browser, finds cards, downloads.

    Args:
        track_name: Name to search for (or empty to grab latest cards).
        max_cards: Maximum number of cards to download from.

    Returns:
        List of downloaded MP3 file paths.
    """
    log.info(f"Downloading existing tracks from My Music (name='{track_name}', max={max_cards})")

    safe_name = "".join(c if c.isalnum() or c in "-_ " else "" for c in track_name) if track_name else "track"
    safe_name = safe_name.strip().replace(" ", "_")[:50] or "track"

    # Build a minimal MusicConcept for _download_from_mymusic
    name = track_name or "Afro House Mix"
    concept = MusicConcept(
        track_name=name,
        genre="Afro House",
        mood="ritualistic, primal, powerful, transcendent",
        description=f"A deep, hypnotic Afro House track called {name}",
        music_prompt="",
        hashtags=["afrohouse", "tribalbass", "deephouse", "carbass", "music"],
        thumbnail_prompt="",
        youtube_title=f"{name} - Afro House",
        youtube_description=f"{name} - A deep Afro House track.",
        youtube_tags=["afro house", "deep house", "tribal", "car bass"],
        tiktok_caption=f"{name} #afrohouse #tribal #deepbass",
    )

    with sync_playwright() as p:
        chrome_args = [
            "--disable-blink-features=AutomationControlled",
            "--window-position=-2400,-2400",
        ]

        context_opts = {"viewport": {"width": 1920, "height": 1080}, "accept_downloads": True}
        if AIMUSICFACTORY_STATE_FILE.exists():
            context_opts["storage_state"] = str(AIMUSICFACTORY_STATE_FILE)
            log.info("Loading saved cookies")

        browser = p.chromium.launch(
            headless=False, channel="chrome", args=chrome_args,
        )
        context = browser.new_context(**context_opts)
        context.set_default_timeout(60_000)
        page = context.new_page()

        # Block "Save As" dialog from File System Access API
        page.add_init_script(_BLOCK_SAVE_PICKER_JS)

        cdp = context.new_cdp_session(page)
        _send_cdp_download_behavior(cdp, INPUT_DIR)

        logged_in = _check_logged_in(page)
        if logged_in:
            log.info("Already logged in!")
            context.storage_state(path=str(AIMUSICFACTORY_STATE_FILE))
        else:
            page.evaluate("window.moveTo(100, 100)")
            log.info("Not logged in — please log in with Google.")
            input("\n>>> Press ENTER after you've logged in... ")
            AIMUSICFACTORY_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            context.storage_state(path=str(AIMUSICFACTORY_STATE_FILE))
            page.evaluate("window.moveTo(-2400, -2400)")

        all_mp3s = _download_from_mymusic(page, concept, safe_name, max_cards,
                                          cdp=cdp, download_dir=INPUT_DIR)
        browser.close()

    if not all_mp3s:
        raise RuntimeError("No MP3s downloaded from My Music")

    log.info(f"Total MP3s downloaded: {len(all_mp3s)}")
    return all_mp3s


def generate_music(concept: MusicConcept) -> Path:
    """Generate a single music track (backward compatibility)."""
    mp3s = generate_music_batch(concept, count=1)
    return mp3s[0]
