"""Generate music on aimusicfactory.ai using Playwright.

Pipeline approach:
1. Submit all generations on the Generate page (wait ~4 min each)
2. Wait until 18 min have passed since the first generation
3. Go to My Music, click on each track card by name
4. On each track detail page, click the Download buttons to get MP3s
"""

import re
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
DOWNLOAD_READY_SEC = 1080      # 18 min — minimum time from generation before downloads work


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

    # Click Generate button
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


# ── Phase 3: My Music → click cards → download from detail pages ──

def _download_from_mymusic(page, concept: MusicConcept, safe_name: str, expected_cards: int) -> list[Path]:
    """Navigate to My Music, find track cards by name, open each, download MP3s.

    Flow (matches site structure from screenshots):
    1. Go to /myMusic
    2. Scroll page to load all cards
    3. Find all cards with the track name (multiple strategies)
    4. Click each card to open its detail page
    5. On the detail page, click each green "Download" button
    6. Go back to My Music for the next card
    """
    page.goto("https://aimusicfactory.ai/myMusic", wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(10_000)

    # Scroll down to load all cards (lazy loading / infinite scroll)
    _scroll_page(page)
    page.screenshot(path=str(OUTPUT_DIR / "debug_mymusic.png"))

    # Save HTML for debugging
    html = page.content()
    (OUTPUT_DIR / "debug_mymusic.html").write_text(html, encoding="utf-8")
    log.info(f"My Music page loaded ({len(html)} chars)")

    # Log all visible card names for debugging
    all_card_names = _get_all_card_names(page)
    log.info(f"All visible card names on My Music ({len(all_card_names)}):")
    for name_info in all_card_names[:20]:
        log.info(f"  card: '{name_info['name']}' → {name_info['href']}")

    # Log DOM structure diagnostics if no <a>-based cards found
    if not all_card_names:
        _log_page_structure(page)

    # Strategy 1: Find cards matching our track name
    track_name = concept.track_name
    card_hrefs = _find_track_cards(page, track_name)

    # Strategy 2: Try search box
    if not card_hrefs:
        log.warning(f"No cards found for '{track_name}' — trying search box...")
        _search_mymusic(page, track_name)
        page.wait_for_timeout(5000)
        _scroll_page(page)
        page.screenshot(path=str(OUTPUT_DIR / "debug_mymusic_search.png"))
        card_hrefs = _find_track_cards(page, track_name)

    # Strategy 3: Reload page and try again
    if not card_hrefs:
        log.warning(f"Still no cards — reloading My Music page...")
        page.goto("https://aimusicfactory.ai/myMusic", wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(15_000)
        _scroll_page(page)
        card_hrefs = _find_track_cards(page, track_name)

    # Strategy 4: Fallback — get the latest N cards regardless of name
    if not card_hrefs:
        log.warning(f"Name match failed — falling back to latest {expected_cards} card(s)...")
        card_hrefs = _get_latest_card_hrefs(page, expected_cards)
        if card_hrefs:
            log.info(f"Fallback: found {len(card_hrefs)} latest card(s)")

    # ── Strategy 5: Click-based approach using DOM structure ──
    # If href-based strategies all failed, the site probably uses divs with click handlers
    if not card_hrefs:
        log.info("All href-based strategies failed — trying click-based card detection...")
        struct_cards = _find_music_cards_by_structure(page, track_name)

        if struct_cards:
            log.info(f"Found {len(struct_cards)} card(s) by DOM structure — using click approach")
            # Filter: prefer name matches, then top-scored, limit to expected count
            name_matches = [c for c in struct_cards if c.get("nameMatch")]
            cards_to_use = name_matches if name_matches else struct_cards[:expected_cards]

            all_mp3s = []
            for i, card_info in enumerate(cards_to_use):
                card_num = i + 1
                log.info(f"\n--- Click-Card {card_num}/{len(cards_to_use)}: "
                         f"'{card_info.get('text', '')[:50]}' ---")

                try:
                    # Navigate back to My Music before each click
                    if i > 0:
                        page.goto("https://aimusicfactory.ai/myMusic",
                                  wait_until="domcontentloaded", timeout=60_000)
                        page.wait_for_timeout(8_000)
                        _scroll_page(page)

                    old_url = page.url
                    clicked = _click_card_by_index(page, cards_to_use, i)
                    if not clicked:
                        log.warning(f"Click-Card {card_num}: click failed, skipping")
                        continue

                    page.wait_for_timeout(3_000)
                    new_url = page.url
                    log.info(f"Click-Card {card_num}: URL changed: {old_url} → {new_url}")
                    page.screenshot(path=str(OUTPUT_DIR / f"debug_click_card_{card_num}.png"))

                    # Save detail page HTML
                    detail_html = page.content()
                    (OUTPUT_DIR / f"debug_click_detail_{card_num}.html").write_text(
                        detail_html, encoding="utf-8")

                    song_id = str(int(time.time()))
                    song_id_match = re.search(r'/(\d+)', new_url)
                    if song_id_match:
                        song_id = song_id_match.group(1)

                    _wait_for_download_button(page, card_num)
                    downloaded = _download_mp3s_from_detail(page, safe_name, card_num, song_id)
                    all_mp3s.extend(downloaded)
                    log.info(f"Click-Card {card_num}: downloaded {len(downloaded)} MP3(s)")

                except Exception as e:
                    log.warning(f"Click-Card {card_num} failed: {e}")
                    page.screenshot(path=str(OUTPUT_DIR / f"debug_click_fail_{card_num}.png"))

            return all_mp3s

    if not card_hrefs:
        log.error(f"No track cards found on My Music at all!")
        page.screenshot(path=str(OUTPUT_DIR / "debug_no_cards.png"))
        return []

    log.info(f"Found {len(card_hrefs)} card(s) to download from")

    all_mp3s = []
    for i, href in enumerate(card_hrefs):
        card_num = i + 1
        log.info(f"\n--- Card {card_num}/{len(card_hrefs)}: {href} ---")

        # Extract song ID from href (e.g. /myMusic/12345 → 12345)
        song_id_match = re.search(r'/(\d+)', href)
        song_id = song_id_match.group(1) if song_id_match else str(int(time.time()))

        try:
            # Navigate to the track detail page
            if href.startswith("/"):
                full_url = f"https://aimusicfactory.ai{href}"
            elif href.startswith("http"):
                full_url = href
            else:
                full_url = f"https://aimusicfactory.ai/{href}"

            page.goto(full_url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(8_000)
            page.screenshot(path=str(OUTPUT_DIR / f"debug_track_detail_{card_num}.png"))

            # Save detail page HTML
            detail_html = page.content()
            (OUTPUT_DIR / f"debug_track_detail_{card_num}.html").write_text(detail_html, encoding="utf-8")

            # Wait for Download buttons to appear (React hydration)
            _wait_for_download_button(page, card_num)

            # Download all MP3s from this detail page (named: TrackName_SongID.mp3)
            downloaded = _download_mp3s_from_detail(page, safe_name, card_num, song_id)
            all_mp3s.extend(downloaded)
            log.info(f"Card {card_num}: downloaded {len(downloaded)} MP3(s)")

        except Exception as e:
            log.warning(f"Card {card_num} failed: {e}")
            page.screenshot(path=str(OUTPUT_DIR / f"debug_card_fail_{card_num}.png"))

    return all_mp3s


def _find_track_cards(page, track_name: str) -> list[str]:
    """Find all card hrefs on My Music page matching the track name.

    Uses multiple strategies: exact match, case-insensitive, partial match.
    Returns list of hrefs (URLs) for matching cards.
    """
    hrefs = page.evaluate("""(trackName) => {
        const results = [];
        const seen = new Set();
        const lowerName = trackName.toLowerCase();

        function addHref(href) {
            if (!href || seen.has(href) || href === '/' || href === '#') return;
            // Only add music-related hrefs (track detail pages)
            if (href.includes('/song/') || href.includes('/track/') ||
                href.includes('/music/') || href.match(/\\/\\d+/) ||
                href.includes('/myMusic/')) {
                seen.add(href);
                results.push(href);
            }
        }

        // Strategy 1: Find <a> tags with case-insensitive text match
        const allLinks = document.querySelectorAll('a');
        for (const link of allLinks) {
            const text = link.textContent.trim().toLowerCase();
            const href = link.getAttribute('href') || '';
            if (text.includes(lowerName)) {
                addHref(href);
            }
        }

        // Strategy 2: Walk up from text nodes containing track name
        if (results.length === 0) {
            const walker = document.createTreeWalker(
                document.body, NodeFilter.SHOW_TEXT, null);
            while (walker.nextNode()) {
                const text = walker.currentNode.textContent.trim().toLowerCase();
                if (!text.includes(lowerName)) continue;

                let el = walker.currentNode.parentElement;
                for (let i = 0; i < 15; i++) {
                    if (!el) break;
                    if (el.tagName === 'A') {
                        addHref(el.getAttribute('href') || '');
                        break;
                    }
                    // Also check for onClick or data-href
                    const href = el.getAttribute('href') || el.dataset?.href || '';
                    if (href) { addHref(href); break; }
                    el = el.parentElement;
                }
            }
        }

        // Strategy 3: If href filter was too strict, try without it
        if (results.length === 0) {
            for (const link of allLinks) {
                const text = link.textContent.trim().toLowerCase();
                const href = link.getAttribute('href') || '';
                if (!href || seen.has(href) || href === '/' || href === '#') continue;
                if (text.includes(lowerName)) {
                    seen.add(href);
                    results.push(href);
                }
            }
        }

        return results;
    }""", track_name)

    log.info(f"_find_track_cards('{track_name}'): found {len(hrefs)} card(s)")
    for h in hrefs:
        log.info(f"  card href: {h}")

    return hrefs


def _find_music_cards_by_structure(page, track_name: str = "") -> list[dict]:
    """Find music cards by DOM structure, not just <a> tags.

    The site may use <div> elements with click handlers instead of <a> links.
    Looks for card-like containers: elements with images + text that appear to be
    track listings (contain duration patterns, play buttons, etc.).

    Returns list of dicts: [{index, text, tag, has_image, has_duration}, ...]
    """
    cards = page.evaluate("""(trackName) => {
        const lowerName = trackName ? trackName.toLowerCase() : '';
        const results = [];

        // Strategy A: Find elements that look like music cards
        // (contain an <img> + text, not in nav/header/footer)
        const candidates = document.querySelectorAll(
            '[class*="card"], [class*="Card"], [class*="track"], [class*="Track"], ' +
            '[class*="song"], [class*="Song"], [class*="item"], [class*="Item"], ' +
            '[class*="music"], [class*="Music"], [class*="list-"] , [class*="grid-"]'
        );

        for (const el of candidates) {
            if (el.closest('nav') || el.closest('footer') || el.closest('header')) continue;
            if (el.offsetParent === null) continue;
            // Must have some text content
            const text = el.textContent.trim().substring(0, 200);
            if (text.length < 2) continue;
            // Skip if it's a huge container (likely page wrapper, not individual card)
            const rect = el.getBoundingClientRect();
            if (rect.width > window.innerWidth * 0.9 && rect.height > window.innerHeight * 0.5) continue;

            const hasImage = el.querySelector('img') !== null;
            const hasDuration = /\\d+:\\d{2}/.test(text);
            const hasPlayBtn = el.querySelector('[class*="play"], [class*="Play"], svg') !== null;

            // Score: more card-like features = higher score
            let score = 0;
            if (hasImage) score += 2;
            if (hasDuration) score += 3;
            if (hasPlayBtn) score += 1;
            if (rect.width > 100 && rect.width < 800 && rect.height > 50 && rect.height < 400) score += 2;

            if (score >= 2) {
                results.push({
                    index: results.length,
                    text: text.substring(0, 100),
                    tag: el.tagName,
                    className: (el.className || '').toString().substring(0, 100),
                    hasImage: hasImage,
                    hasDuration: hasDuration,
                    hasPlayBtn: hasPlayBtn,
                    score: score,
                    nameMatch: lowerName ? text.toLowerCase().includes(lowerName) : false,
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                });
            }
        }

        // Strategy B: Look for repeated sibling elements (typical card pattern)
        if (results.length === 0) {
            // Find containers with multiple similar children
            const containers = document.querySelectorAll('div, section, main, ul');
            for (const container of containers) {
                if (container.closest('nav') || container.closest('footer') || container.closest('header')) continue;
                const children = container.children;
                if (children.length < 2 || children.length > 50) continue;

                // Check if children have same tag and similar structure
                const firstTag = children[0].tagName;
                let sameTag = 0;
                for (const child of children) {
                    if (child.tagName === firstTag && child.offsetParent !== null) sameTag++;
                }
                if (sameTag < 2) continue;

                // These repeated children might be cards
                for (let i = 0; i < children.length; i++) {
                    const child = children[i];
                    if (child.tagName !== firstTag || child.offsetParent === null) continue;
                    const text = child.textContent.trim();
                    if (text.length < 2 || text.length > 500) continue;
                    const rect = child.getBoundingClientRect();
                    if (rect.width < 50 || rect.height < 30) continue;

                    results.push({
                        index: results.length,
                        text: text.substring(0, 100),
                        tag: child.tagName,
                        className: (child.className || '').toString().substring(0, 100),
                        hasImage: child.querySelector('img') !== null,
                        hasDuration: /\\d+:\\d{2}/.test(text),
                        hasPlayBtn: child.querySelector('[class*="play"], svg') !== null,
                        score: 1,
                        nameMatch: lowerName ? text.toLowerCase().includes(lowerName) : false,
                        width: Math.round(rect.width),
                        height: Math.round(rect.height),
                        parentTag: container.tagName,
                        siblingCount: sameTag,
                    });
                }
                if (results.length > 0) break;  // Use first matching container
            }
        }

        // Sort by name match first, then by score
        results.sort((a, b) => {
            if (a.nameMatch !== b.nameMatch) return b.nameMatch ? 1 : -1;
            return b.score - a.score;
        });

        return results;
    }""", track_name)

    log.info(f"_find_music_cards_by_structure('{track_name}'): found {len(cards)} candidate(s)")
    for c in cards[:10]:
        log.info(f"  card: [{c.get('tag')}] score={c.get('score')} match={c.get('nameMatch')} "
                 f"size={c.get('width')}x{c.get('height')} "
                 f"img={c.get('hasImage')} dur={c.get('hasDuration')} "
                 f"text='{c.get('text', '')[:60]}' class='{c.get('className', '')[:40]}'")

    return cards


def _click_card_by_index(page, cards: list[dict], idx: int) -> bool:
    """Click on a music card found by _find_music_cards_by_structure.

    Returns True if a navigation happened (new page content loaded).
    """
    card = cards[idx]
    class_name = card.get("className", "")
    text_snippet = card.get("text", "")[:30]

    log.info(f"Clicking card {idx}: '{text_snippet}...' (class: {class_name[:40]})")

    # Click the element matching this card's properties
    navigated = page.evaluate("""(args) => {
        const {idx, className, text} = args;
        const lowerText = text.toLowerCase();

        // Re-find the element by matching class + text
        const candidates = document.querySelectorAll(
            '[class*="card"], [class*="Card"], [class*="track"], [class*="Track"], ' +
            '[class*="song"], [class*="Song"], [class*="item"], [class*="Item"], ' +
            '[class*="music"], [class*="Music"], [class*="list-"], [class*="grid-"], ' +
            'div, li, article'
        );

        let matchIdx = 0;
        for (const el of candidates) {
            if (el.closest('nav') || el.closest('footer') || el.closest('header')) continue;
            if (el.offsetParent === null) continue;
            const elText = el.textContent.trim().substring(0, 100).toLowerCase();
            if (!elText.includes(lowerText.substring(0, 20))) continue;

            if (matchIdx === idx) {
                // Try clicking the most specific clickable child first
                const clickable = el.querySelector('a') || el.querySelector('button') || el;
                clickable.click();
                return 'clicked';
            }
            matchIdx++;
        }
        return 'not_found';
    }""", {"idx": idx, "className": class_name, "text": text_snippet})

    if navigated == "not_found":
        log.warning(f"Card {idx} not found on re-click attempt")
        return False

    # Wait for potential navigation
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


def _get_all_card_names(page) -> list[dict]:
    """Get all visible card names and hrefs on My Music page for debugging."""
    return page.evaluate("""() => {
        const cards = [];
        const seen = new Set();
        const allLinks = document.querySelectorAll('a');

        for (const link of allLinks) {
            const href = link.getAttribute('href') || '';
            if (!href || href === '/' || href === '#' || seen.has(href)) continue;
            // Skip navigation/footer links
            if (link.closest('nav') || link.closest('footer') || link.closest('header')) continue;
            if (link.offsetParent === null) continue;  // hidden

            const text = link.textContent.trim().replace(/\\s+/g, ' ');
            if (text.length > 0 && text.length < 200) {
                seen.add(href);
                cards.push({name: text.substring(0, 80), href: href});
            }
        }
        return cards;
    }""")


def _get_latest_card_hrefs(page, count: int) -> list[str]:
    """Get hrefs of the latest N cards on My Music page (regardless of name).

    Fallback when name matching fails — assumes latest cards are at the top.
    """
    # Known site navigation paths to NEVER treat as music cards
    NAV_BLACKLIST = [
        '/#Generate', '/#', '/audio-tool', '/persona', '/pricing',
        '/myMusic', '/ai-image', '/song-mv', '/about', '/contact',
        '/terms', '/privacy', '/faq', '/blog',
    ]

    hrefs = page.evaluate("""(args) => {
        const {count, blacklist} = args;
        const blackSet = new Set(blacklist.map(b => b.toLowerCase()));
        const results = [];
        const seen = new Set();
        const allLinks = document.querySelectorAll('a');

        function isBlacklisted(href) {
            const lower = href.toLowerCase();
            for (const b of blackSet) {
                if (lower === b || lower.startsWith(b + '/') || lower.startsWith(b + '?')) return true;
            }
            // Skip fragment-only links and short paths that look like nav
            if (lower.startsWith('/#') || (lower.startsWith('/') && lower.split('/').length <= 2 && !lower.match(/\\/\\d+/))) return true;
            return false;
        }

        for (const link of allLinks) {
            const href = link.getAttribute('href') || '';
            if (!href || href === '/' || href === '#' || seen.has(href)) continue;
            if (link.closest('nav') || link.closest('footer') || link.closest('header')) continue;
            if (link.offsetParent === null) continue;
            if (isBlacklisted(href)) continue;

            // Heuristic: card links typically have numeric IDs or specific paths
            if (href.includes('/song/') || href.includes('/track/') ||
                href.includes('/music/') || href.includes('/myMusic/') ||
                href.match(/\\/\\d{4,}/)) {
                seen.add(href);
                results.push(href);
                if (results.length >= count) break;
            }
        }

        // Second pass: content links not in blacklist, with longer paths
        if (results.length === 0) {
            for (const link of allLinks) {
                const href = link.getAttribute('href') || '';
                if (!href || href === '/' || href === '#' || seen.has(href)) continue;
                if (link.closest('nav') || link.closest('footer') || link.closest('header')) continue;
                if (link.offsetParent === null) continue;
                if (isBlacklisted(href)) continue;

                const text = link.textContent.trim();
                // Must have text and href must be a deep path (3+ segments)
                if (text.length >= 2 && text.length <= 100 && href.split('/').length >= 3) {
                    seen.add(href);
                    results.push(href);
                    if (results.length >= count) break;
                }
            }
        }

        return results;
    }""", {"count": count, "blacklist": NAV_BLACKLIST})

    log.info(f"_get_latest_card_hrefs(count={count}): found {len(hrefs)}")
    for h in hrefs:
        log.info(f"  latest card href: {h}")

    return hrefs


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


def _download_mp3s_from_detail(page, safe_name: str, card_num: int, song_id: str = "") -> list[Path]:
    """Click all Download buttons on a track detail page and save MP3s.

    From screenshots: each track has a green gradient "Download" button.
    Clicking it opens a popover with "Audio" option.
    Files are saved as: TrackName_SongID.mp3
    """
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
            # Name file as: TrackName_SongID_N.mp3 (or TrackName_SongID.mp3 if only one)
            id_part = f"_{song_id}" if song_id else f"_{int(time.time())}"
            suffix = f"_{i + 1}" if btn_count > 1 else ""
            output_path = OUTPUT_DIR / f"{safe_name}{id_part}{suffix}.mp3"

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
    """
    # Click the popover button
    page.evaluate("""(idx) => {
        const popovers = [...document.querySelectorAll('[id^="headlessui-popover-button"]')]
            .filter(p => p.textContent.includes('Download') && p.offsetParent !== null);
        if (idx < popovers.length) popovers[idx].click();
    }""", idx)

    page.wait_for_timeout(1500)
    page.screenshot(path=str(OUTPUT_DIR / f"debug_popover_{card_num}_{idx + 1}.png"))

    # Log panel content
    panel_html = page.evaluate("""() => {
        const panels = document.querySelectorAll('[id^="headlessui-popover-panel"]');
        if (panels.length === 0) return 'NO_PANEL';
        return panels[panels.length - 1].innerHTML;
    }""")
    log.info(f"Popover panel ({len(panel_html)} chars): {panel_html[:300]}")

    try:
        with page.expect_download(timeout=30_000) as dl_info:
            page.evaluate("""() => {
                const panels = document.querySelectorAll('[id^="headlessui-popover-panel"]');
                for (const panel of panels) {
                    const links = panel.querySelectorAll('a, button, div, span, [class*="cursor"]');
                    for (const link of links) {
                        const text = link.textContent.trim().toLowerCase();
                        // Match 'Audio', 'MP3', or 'audio' options
                        if (text.includes('audio') || text.includes('mp3')) {
                            link.click();
                            return 'clicked_audio';
                        }
                    }
                    // Click first clickable option as fallback
                    const first = panel.querySelector('a, button, div[class*="cursor"], [role="button"]');
                    if (first) { first.click(); return 'clicked_first'; }
                }
                return 'nothing';
            }""")

        download = dl_info.value
        download.save_as(str(output_path))

        # Close popover
        page.evaluate("document.body.click()")
        page.wait_for_timeout(1000)
        return output_path

    except PlaywrightTimeout:
        log.warning(f"Popover download timeout (card {card_num}, btn {idx + 1})")
        page.screenshot(path=str(OUTPUT_DIR / f"debug_popover_timeout_{card_num}_{idx + 1}.png"))
        page.evaluate("document.body.click()")
        page.wait_for_timeout(1000)
        return None


def _download_via_button(page, idx: int, output_path: Path, card_num: int) -> Path | None:
    """Download MP3 by clicking Download then Audio in the dropdown."""
    try:
        # Click the Download button first
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

        # Wait for dropdown to appear, then click "Audio"
        page.wait_for_timeout(1500)

        with page.expect_download(timeout=30_000) as dl_info:
            page.evaluate("""() => {
                // Look for "Audio" option in any visible dropdown/popover/panel
                const allEls = document.querySelectorAll('a, button, div, span, [role="menuitem"]');
                for (const el of allEls) {
                    if (el.offsetParent === null) continue;
                    const text = el.textContent.trim().toLowerCase();
                    if (text === 'audio' || text.includes('audio') || text.includes('mp3')) {
                        el.click();
                        return 'clicked_audio';
                    }
                }
                return 'not_found';
            }""")

        download = dl_info.value
        download.save_as(str(output_path))
        page.wait_for_timeout(2000)
        return output_path

    except PlaywrightTimeout:
        log.warning(f"Direct download timeout (card {card_num}, btn {idx + 1})")
        page.screenshot(path=str(OUTPUT_DIR / f"debug_btn_timeout_{card_num}_{idx + 1}.png"))

        # Maybe the button opened a popover instead — check and try
        panel_exists = page.evaluate("""() => {
            return document.querySelectorAll('[id^="headlessui-popover-panel"]').length > 0;
        }""")

        if panel_exists:
            log.info("A popover opened — trying to download MP3 from it...")
            return _download_via_popover(page, 0, output_path, card_num)

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


def generate_music(concept: MusicConcept) -> Path:
    """Generate a single music track (backward compatibility)."""
    mp3s = generate_music_batch(concept, count=1)
    return mp3s[0]
