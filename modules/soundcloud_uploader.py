import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from modules.concept_generator import MusicConcept
from config import SOUNDCLOUD_STATE_FILE, HEADLESS
from utils.logger import log

SOUNDCLOUD_UPLOAD_URL = "https://soundcloud.com/upload"
MAX_RETRIES = 2


def upload_to_soundcloud(
    audio_path: Path,
    concept: MusicConcept,
    thumbnail_path: Path | None = None,
) -> str | None:
    """Upload a track to SoundCloud via browser automation.

    Args:
        audio_path: Path to MP3 or WAV file.
        concept: MusicConcept with track metadata.
        thumbnail_path: Optional cover art image to set as track artwork.

    Returns:
        SoundCloud track URL if successful, None otherwise.
    """
    log.info(f"Uploading to SoundCloud: {concept.track_name}")

    if not SOUNDCLOUD_STATE_FILE.exists():
        log.error(
            f"SoundCloud session not found: {SOUNDCLOUD_STATE_FILE}\n"
            "Run: python main.py soundcloud-login"
        )
        return None

    if SOUNDCLOUD_STATE_FILE.stat().st_size < 10:
        log.error(
            f"SoundCloud session file is empty: {SOUNDCLOUD_STATE_FILE}\n"
            "Run: python main.py soundcloud-login"
        )
        return None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = _do_upload(audio_path, concept, thumbnail_path)
            return result
        except Exception as e:
            if attempt < MAX_RETRIES:
                wait = 2 ** attempt
                log.warning(f"SoundCloud upload attempt {attempt}/{MAX_RETRIES} failed: {e}")
                log.info(f"Retrying in {wait}s...")
                time.sleep(wait)
            else:
                log.error(f"SoundCloud upload failed after {MAX_RETRIES} attempts: {e}")
                raise


def _do_upload(
    audio_path: Path,
    concept: MusicConcept,
    thumbnail_path: Path | None,
) -> str | None:
    """Single attempt to upload a track to SoundCloud."""
    debug_dir = Path("output")

    with sync_playwright() as p:
        # Use storage_state for SoundCloud (keeps cookies + localStorage)
        browser = p.chromium.launch(
            headless=HEADLESS,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            storage_state=str(SOUNDCLOUD_STATE_FILE),
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/134.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        try:
            # Navigate to SoundCloud upload page
            log.info(f"Navigating to {SOUNDCLOUD_UPLOAD_URL}...")
            page.goto(SOUNDCLOUD_UPLOAD_URL, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(5_000)

            actual_url = page.url
            log.info(f"SoundCloud page loaded. URL: {actual_url}")
            page.screenshot(path=str(debug_dir / "debug_soundcloud_01_loaded.png"))

            # Check if logged in
            if "signin" in actual_url.lower() or "sign-in" in actual_url.lower():
                log.error(f"Not logged in to SoundCloud (redirected to: {actual_url})")
                log.error("Session expired. Run: python main.py soundcloud-login")
                page.screenshot(path=str(debug_dir / "debug_soundcloud_login_fail.png"))
                browser.close()
                return None

            # Dismiss cookie consent banner if present
            _dismiss_soundcloud_popups(page)

            # Upload audio file — look for the file input or the upload button area
            log.info("Looking for audio file input...")

            # SoundCloud is a SPA — wait for dynamic content to fully render
            page.wait_for_load_state("networkidle", timeout=15_000)
            page.wait_for_timeout(3_000)

            # Extra wait: poll for any file input or upload-related element to appear
            for _poll in range(6):  # up to 30s total
                has_upload_el = page.evaluate("""() => {
                    return !!(document.querySelector('input[type="file"]')
                        || document.querySelector('[class*="dropzone" i]')
                        || document.querySelector('[class*="upload" i] button')
                        || document.querySelector('button[class*="upload" i]')
                        || document.querySelector('[data-testid*="upload"]'));
                }""")
                if has_upload_el:
                    break
                log.info(f"Waiting for upload elements to appear... ({(_poll + 1) * 5}s)")
                page.wait_for_timeout(5_000)

            file_uploaded = False

            # Strategy 1: Find file input directly (attached to DOM, may be hidden)
            file_input = page.query_selector('input[type="file"]')
            if file_input:
                try:
                    file_input.set_input_files(str(audio_path))
                    log.info(f"Audio file selected via input[type=file]: {audio_path.name}")
                    page.screenshot(path=str(debug_dir / "debug_soundcloud_02_file_selected.png"))
                    file_uploaded = True
                except Exception as e:
                    log.warning(f"set_input_files failed on file input: {e}")

            # Strategy 2: Use FileChooser event — click the upload button/area
            if not file_uploaded:
                log.info("No file input found directly, trying file chooser strategy...")
                # SoundCloud upload page has a button like "or choose files to upload"
                # or a large dropzone area — try multiple known selectors
                upload_clickables = [
                    'button:has-text("choose file")',
                    'a:has-text("choose file")',
                    'button:has-text("Upload")',
                    'button:has-text("Upload a track")',
                    'a:has-text("Upload a track")',
                    'button:has-text("Select a file")',
                    'button:has-text("Browse")',
                    '[class*="dropzone"]',
                    '[class*="Dropzone"]',
                    '[class*="chooser"]',
                    '[class*="uploadButton"]',
                    '[class*="uploadTarget"]',
                    '[class*="upload"] button',
                    '[data-testid*="upload"]',
                    '[data-testid*="file"]',
                    'label[for*="file"]',
                    'label[for*="upload"]',
                    # React/modern UI patterns
                    '[role="button"][class*="upload" i]',
                    'div[class*="upload" i][role="presentation"]',
                ]
                for selector in upload_clickables:
                    el = page.query_selector(selector)
                    if el:
                        log.info(f"Found clickable: {selector}, trying file chooser...")
                        try:
                            with page.expect_file_chooser(timeout=5_000) as fc_info:
                                el.click(force=True)
                            file_chooser = fc_info.value
                            file_chooser.set_files(str(audio_path))
                            log.info(f"Audio file selected via file chooser: {audio_path.name}")
                            page.screenshot(path=str(debug_dir / "debug_soundcloud_02_file_selected.png"))
                            file_uploaded = True
                            break
                        except PlaywrightTimeout:
                            log.info(f"File chooser did not appear for {selector}")
                        except Exception as e:
                            log.warning(f"File chooser error for {selector}: {e}")

            # Strategy 3: Use JavaScript to find ANY file input (even deeply nested/shadow DOM)
            if not file_uploaded:
                log.info("Trying JavaScript-based file input discovery...")
                found_input = page.evaluate_handle("""() => {
                    // Check regular DOM
                    let input = document.querySelector('input[type="file"]');
                    if (input) return input;
                    // Check all inputs regardless of type attribute
                    const inputs = document.querySelectorAll('input');
                    for (const i of inputs) {
                        if (i.accept && (i.accept.includes('audio') || i.accept.includes('*')))
                            return i;
                    }
                    // Search inside shadow DOMs
                    const allElements = document.querySelectorAll('*');
                    for (const el of allElements) {
                        if (el.shadowRoot) {
                            const shadowInput = el.shadowRoot.querySelector('input[type="file"]');
                            if (shadowInput) return shadowInput;
                        }
                    }
                    return null;
                }""")
                el = found_input.as_element()
                if el:
                    try:
                        el.set_input_files(str(audio_path))
                        log.info(f"Audio file selected via JS discovery: {audio_path.name}")
                        page.screenshot(path=str(debug_dir / "debug_soundcloud_02_file_selected.png"))
                        file_uploaded = True
                    except Exception as e:
                        log.warning(f"JS file input set_input_files failed: {e}")

            # Strategy 4: Click anywhere in the dropzone area and intercept file chooser
            if not file_uploaded:
                log.info("Trying click-on-dropzone strategy...")
                # Try clicking the center of the main upload area
                dropzone = page.query_selector(
                    '[class*="drop"], [class*="upload"]:not(nav *):not(header *), '
                    'main [role="button"], [class*="Dropzone"], [class*="drag"]'
                )
                if dropzone:
                    try:
                        with page.expect_file_chooser(timeout=5_000) as fc_info:
                            dropzone.click(force=True)
                        file_chooser = fc_info.value
                        file_chooser.set_files(str(audio_path))
                        log.info(f"Audio file selected via dropzone click: {audio_path.name}")
                        file_uploaded = True
                    except Exception as e:
                        log.warning(f"Dropzone file chooser failed: {e}")

            # Strategy 5: Inject a file input via JS and simulate drag-and-drop
            if not file_uploaded:
                log.info("Trying drag-and-drop simulation strategy...")
                # Create a hidden file input, set its files, and dispatch
                # a drop event on the upload area
                drop_target = page.query_selector(
                    '[class*="drop" i], [class*="upload" i]:not(nav *):not(header *), '
                    'main, [class*="Dropzone"]'
                )
                if drop_target:
                    try:
                        with page.expect_file_chooser(timeout=5_000) as fc_info:
                            # Click center of the target area
                            box = drop_target.bounding_box()
                            if box:
                                page.mouse.click(
                                    box["x"] + box["width"] / 2,
                                    box["y"] + box["height"] / 2,
                                )
                        file_chooser = fc_info.value
                        file_chooser.set_files(str(audio_path))
                        log.info(f"Audio file selected via drop-target click: {audio_path.name}")
                        file_uploaded = True
                    except Exception as e:
                        log.warning(f"Drop-target click strategy failed: {e}")

            # Strategy 6: Force-create a file input via JS as last resort
            if not file_uploaded:
                log.info("Trying forced file input creation via JS...")
                page.evaluate("""() => {
                    const input = document.createElement('input');
                    input.type = 'file';
                    input.id = '__sc_forced_file_input';
                    input.style.position = 'fixed';
                    input.style.top = '0';
                    input.style.left = '0';
                    input.style.opacity = '0.01';
                    input.style.zIndex = '999999';
                    document.body.appendChild(input);
                }""")
                page.wait_for_timeout(500)
                forced_input = page.query_selector('#__sc_forced_file_input')
                if forced_input:
                    try:
                        forced_input.set_input_files(str(audio_path))
                        # Dispatch change event to trigger SoundCloud handlers
                        page.evaluate("""() => {
                            const input = document.querySelector('#__sc_forced_file_input');
                            if (input && input.files.length > 0) {
                                // Find the real drop zone and dispatch a synthetic drop event
                                const dropZone = document.querySelector(
                                    '[class*="drop" i], [class*="upload" i]:not(nav *):not(header *)'
                                );
                                if (dropZone) {
                                    const dt = new DataTransfer();
                                    dt.items.add(input.files[0]);
                                    const dropEvent = new DragEvent('drop', {
                                        dataTransfer: dt, bubbles: true, cancelable: true
                                    });
                                    dropZone.dispatchEvent(dropEvent);
                                    return 'drop_dispatched';
                                }
                                // Fallback: dispatch change on any existing file input
                                input.dispatchEvent(new Event('change', {bubbles: true}));
                                return 'change_dispatched';
                            }
                            return 'no_files';
                        }""")
                        page.wait_for_timeout(3_000)
                        # Check if SoundCloud picked up the file (title form appears)
                        title_check = page.query_selector(
                            'input[name="title"], input[placeholder*="Title"], '
                            'input[aria-label*="Title"]'
                        )
                        if title_check:
                            log.info("Audio file accepted via forced drag-and-drop simulation")
                            file_uploaded = True
                        else:
                            log.warning("Forced file input created but SoundCloud did not accept the file")
                    except Exception as e:
                        log.warning(f"Forced file input strategy failed: {e}")
                    finally:
                        page.evaluate("""() => {
                            const el = document.querySelector('#__sc_forced_file_input');
                            if (el) el.remove();
                        }""")

            if not file_uploaded:
                page.screenshot(path=str(debug_dir / "debug_soundcloud_no_file_input.png"))
                # Log all inputs and clickable elements for debugging
                debug_info = page.evaluate("""() => {
                    const inputs = [...document.querySelectorAll('input')]
                        .map(i => ({type: i.type, accept: i.accept, name: i.name, id: i.id,
                                    visible: i.offsetParent !== null}));
                    const buttons = [...document.querySelectorAll('button, a[role="button"]')]
                        .filter(b => b.offsetParent !== null)
                        .map(b => ({text: b.textContent.trim().substring(0, 60),
                                    class: b.className.substring(0, 80)}))
                        .slice(0, 15);
                    // Also log all elements with upload-related classes
                    const uploadEls = [...document.querySelectorAll('[class*="upload" i], [class*="drop" i]')]
                        .map(e => ({tag: e.tagName, class: e.className.substring(0, 80),
                                    id: e.id, visible: e.offsetParent !== null}))
                        .slice(0, 15);
                    return {inputs, buttons, uploadEls};
                }""")
                log.error(f"No file input found. Inputs: {debug_info.get('inputs', [])}")
                log.error(f"Visible buttons: {debug_info.get('buttons', [])}")
                log.error(f"Upload-related elements: {debug_info.get('uploadEls', [])}")
                raise RuntimeError("Could not find file input on SoundCloud upload page")

            # Wait for SoundCloud to process the file and show the edit form
            log.info("Waiting for SoundCloud to process the upload (up to 5 min)...")
            page.wait_for_timeout(5_000)

            # Wait for the track edit form to appear (title input, etc.)
            title_input = None
            for wait in range(60):  # 60 × 5s = 5 min
                # SoundCloud shows a form with title, genre, tags after file is selected
                title_input = page.query_selector(
                    'input[name="title"], input[placeholder*="Title"], '
                    'input[id*="title"], input[aria-label*="Title"]'
                )
                if title_input:
                    log.info("Track edit form appeared")
                    break

                # Also check for a textarea or contenteditable for title
                title_input = page.query_selector(
                    'textarea[name="title"], [contenteditable="true"][data-field="title"]'
                )
                if title_input:
                    log.info("Track edit form appeared (textarea)")
                    break

                if wait % 6 == 0 and wait > 0:
                    page.screenshot(path=str(debug_dir / f"debug_soundcloud_waiting_form_{wait}.png"))
                    log.info(f"Still waiting for edit form... ({wait * 5}s)")
                page.wait_for_timeout(5_000)

            if not title_input:
                page.screenshot(path=str(debug_dir / "debug_soundcloud_no_form.png"))
                # Dump visible form elements for debugging
                form_els = page.evaluate("""() => {
                    return [...document.querySelectorAll('input, textarea, select')]
                        .filter(e => e.offsetParent !== null)
                        .map(e => ({tag: e.tagName, type: e.type, name: e.name, id: e.id,
                                    placeholder: e.placeholder, classes: e.className.substring(0, 60)}))
                        .slice(0, 30);
                }""")
                log.error(f"Edit form not found. Visible form elements: {form_els}")
                raise RuntimeError("Track edit form did not appear after upload")

            page.screenshot(path=str(debug_dir / "debug_soundcloud_03_form_loaded.png"))

            # Fill in the title
            log.info(f"Setting title: {concept.track_name}")
            title_input.click()
            page.keyboard.press("Control+a")
            page.wait_for_timeout(200)
            page.keyboard.type(concept.track_name, delay=20)
            page.wait_for_timeout(500)

            # Fill in genre — SoundCloud has a genre dropdown/select
            _set_genre(page, concept.genre)

            # Fill in tags/hashtags
            _set_tags(page, concept.hashtags)

            # Fill in description
            _set_description(page, concept)

            # Upload artwork/thumbnail if provided
            if thumbnail_path and thumbnail_path.exists():
                _upload_artwork(page, thumbnail_path, debug_dir)

            page.wait_for_timeout(2_000)
            page.screenshot(path=str(debug_dir / "debug_soundcloud_04_form_filled.png"))

            # Wait for the upload to finish processing before saving
            _wait_for_upload_complete(page)

            # Click Save / Publish
            log.info("Looking for Save button...")
            save_btn = _find_save_button(page)

            if not save_btn:
                page.screenshot(path=str(debug_dir / "debug_soundcloud_no_save.png"))
                buttons = page.evaluate("""() => {
                    return [...document.querySelectorAll('button')]
                        .filter(b => b.offsetParent !== null)
                        .map(b => ({text: b.textContent.trim().substring(0, 50),
                                    enabled: !b.disabled}))
                        .slice(0, 20);
                }""")
                log.error(f"Save button not found. Visible buttons: {buttons}")
                raise RuntimeError("Save button not found on SoundCloud upload page")

            log.info(f"Clicking Save: '{save_btn.text_content().strip()}'")
            save_btn.click(timeout=10_000)
            page.wait_for_timeout(3_000)
            page.screenshot(path=str(debug_dir / "debug_soundcloud_05_save_clicked.png"))

            # Wait for save/publish to complete
            track_url = _wait_for_publish(page, concept.track_name, debug_dir)

            # Save updated session state
            context.storage_state(path=str(SOUNDCLOUD_STATE_FILE))

            page.screenshot(path=str(debug_dir / "debug_soundcloud_06_final.png"))

            if track_url:
                log.info(f"SoundCloud track URL: {track_url}")
            else:
                log.info("SoundCloud upload completed (URL not captured)")

            return track_url or "uploaded (URL not available)"

        except Exception as e:
            log.error(f"SoundCloud upload failed: {e}")
            try:
                page.screenshot(path=str(debug_dir / "debug_soundcloud_error.png"))
            except Exception:
                pass
            raise
        finally:
            browser.close()


def _dismiss_soundcloud_popups(page) -> None:
    """Dismiss cookie consent and other popups on SoundCloud."""
    # Wait for OneTrust banner to appear (SoundCloud uses OneTrust)
    try:
        onetrust_btn = page.wait_for_selector(
            '#onetrust-accept-btn-handler',
            state="visible",
            timeout=8_000,
        )
        if onetrust_btn:
            onetrust_btn.click(force=True)
            log.info("Popup dismissed: onetrust accept button")
            page.wait_for_timeout(2_000)
            # Wait for the banner to disappear
            try:
                page.wait_for_selector('#onetrust-banner-sdk', state='hidden', timeout=5_000)
                log.info("OneTrust banner hidden")
            except PlaywrightTimeout:
                # Force-remove the banner via JS
                page.evaluate("""() => {
                    const banner = document.querySelector('#onetrust-banner-sdk');
                    if (banner) banner.remove();
                    const overlay = document.querySelector('.onetrust-pc-dark-filter');
                    if (overlay) overlay.remove();
                }""")
                log.info("OneTrust banner force-removed")
            return
    except PlaywrightTimeout:
        log.info("No OneTrust banner found, trying other dismiss methods...")

    # Fallback: try generic cookie consent buttons via JS
    dismissed = page.evaluate("""() => {
        const buttons = [...document.querySelectorAll('button')];
        for (const btn of buttons) {
            const text = btn.textContent.trim().toLowerCase();
            if (text === 'accept all' || text === 'accept cookies'
                || text === 'accept all cookies' || text === 'accept & continue'
                || text === 'i accept' || text === 'ok' || text === 'agree') {
                btn.click();
                return 'cookie:' + text;
            }
        }
        return null;
    }""")
    if dismissed:
        log.info(f"Popup dismissed: {dismissed}")
        page.wait_for_timeout(1_000)

    # Try clicking any "Got it" or dismiss button
    for text in ["Got it", "Close", "Dismiss", "Not now"]:
        try:
            btn = page.query_selector(f'button:has-text("{text}")')
            if btn and btn.is_visible():
                btn.click(force=True)
                log.info(f"Dismissed: '{text}'")
                page.wait_for_timeout(500)
        except Exception:
            continue


def _set_genre(page, genre: str) -> None:
    """Set the genre on SoundCloud upload form."""
    try:
        # SoundCloud uses a select dropdown or a custom genre picker
        genre_select = page.query_selector(
            'select[name="genre"], select[id*="genre"], '
            '[data-testid*="genre"] select'
        )
        if genre_select:
            # Try to select by text match
            options = genre_select.query_selector_all("option")
            for opt in options:
                opt_text = opt.text_content().strip().lower()
                if genre.lower() in opt_text or opt_text in genre.lower():
                    genre_select.select_option(label=opt.text_content().strip())
                    log.info(f"Genre set to: {opt.text_content().strip()}")
                    return

            # If no exact match, try common mappings
            genre_map = {
                "afro house": "Electronic",
                "house": "Electronic",
                "edm": "Electronic",
                "lo-fi": "Electronic",
                "hip-hop": "Hip-hop & Rap",
                "hip hop": "Hip-hop & Rap",
                "trap": "Hip-hop & Rap",
                "jazz": "Jazz & Blues",
                "ambient": "Ambient",
                "r&b": "R&B & Soul",
            }
            mapped = genre_map.get(genre.lower())
            if mapped:
                try:
                    genre_select.select_option(label=mapped)
                    log.info(f"Genre mapped: {genre} -> {mapped}")
                    return
                except Exception:
                    pass

            # Fallback: select "Electronic" for music genres
            try:
                genre_select.select_option(label="Electronic")
                log.info("Genre fallback: Electronic")
            except Exception:
                log.warning(f"Could not set genre to '{genre}' — leaving default")
        else:
            # Try clicking a genre button/input
            genre_input = page.query_selector(
                'input[name="genre"], input[placeholder*="genre" i], '
                'input[aria-label*="genre" i]'
            )
            if genre_input:
                genre_input.click()
                page.keyboard.press("Control+a")
                page.keyboard.type(genre, delay=20)
                log.info(f"Genre typed: {genre}")
            else:
                log.info("No genre selector found — skipping")
    except Exception as e:
        log.warning(f"Could not set genre: {e}")


def _set_tags(page, hashtags: list[str]) -> None:
    """Set tags on SoundCloud upload form."""
    try:
        # SoundCloud has a tags input field
        tags_input = page.query_selector(
            'input[name="tag_list"], input[placeholder*="tag" i], '
            'input[aria-label*="tag" i], input[id*="tag"]'
        )
        if tags_input:
            # Clean hashtags — remove # prefix, join with spaces
            clean_tags = " ".join(
                tag.lstrip("#") for tag in hashtags[:10]  # SoundCloud limit
            )
            tags_input.click()
            page.keyboard.type(clean_tags, delay=10)
            # Press Enter to confirm tags on SoundCloud
            page.keyboard.press("Enter")
            log.info(f"Tags set: {clean_tags[:60]}...")
        else:
            # Try textarea for tags
            tags_area = page.query_selector(
                'textarea[name="tag_list"], textarea[placeholder*="tag" i]'
            )
            if tags_area:
                clean_tags = " ".join(tag.lstrip("#") for tag in hashtags[:10])
                tags_area.click()
                page.keyboard.type(clean_tags, delay=10)
                log.info(f"Tags set (textarea): {clean_tags[:60]}...")
            else:
                log.info("No tags input found — skipping")
    except Exception as e:
        log.warning(f"Could not set tags: {e}")


def _set_description(page, concept: MusicConcept) -> None:
    """Set description on SoundCloud upload form."""
    try:
        desc_input = page.query_selector(
            'textarea[name="description"], textarea[placeholder*="description" i], '
            'textarea[aria-label*="description" i], textarea[id*="description"]'
        )
        if desc_input:
            # Build a description from concept data
            desc = (
                f"{concept.description}\n\n"
                f"Genre: {concept.genre} | Mood: {concept.mood}\n\n"
                f"{' '.join('#' + h.lstrip('#') for h in concept.hashtags[:8])}"
            )
            desc_input.click()
            page.keyboard.press("Control+a")
            page.keyboard.type(desc, delay=5)
            log.info("Description set")
        else:
            # Try contenteditable
            desc_el = page.query_selector(
                '[contenteditable="true"][data-field="description"], '
                '[contenteditable="true"][aria-label*="description" i]'
            )
            if desc_el:
                desc = (
                    f"{concept.description}\n\n"
                    f"Genre: {concept.genre} | Mood: {concept.mood}"
                )
                desc_el.click()
                page.keyboard.press("Control+a")
                page.keyboard.type(desc, delay=5)
                log.info("Description set (contenteditable)")
            else:
                log.info("No description field found — skipping")
    except Exception as e:
        log.warning(f"Could not set description: {e}")


def _upload_artwork(page, thumbnail_path: Path, debug_dir: Path) -> None:
    """Upload artwork/cover image on SoundCloud."""
    try:
        # SoundCloud has an image upload area — look for image file input
        img_input = page.query_selector(
            'input[type="file"][accept*="image"]'
        )
        if not img_input:
            # Try any secondary file input (first one was for audio)
            inputs = page.query_selector_all('input[type="file"]')
            for inp in inputs:
                accept = inp.get_attribute("accept") or ""
                if "image" in accept or "png" in accept or "jpg" in accept:
                    img_input = inp
                    break
            # If still not found, check for a clickable artwork area
            if not img_input and len(inputs) > 1:
                img_input = inputs[1]  # Second file input is likely artwork

        if img_input:
            img_input.set_input_files(str(thumbnail_path))
            log.info(f"Artwork uploaded: {thumbnail_path.name}")
            page.wait_for_timeout(3_000)
            page.screenshot(path=str(debug_dir / "debug_soundcloud_artwork_uploaded.png"))
        else:
            # Try clicking on the artwork placeholder
            artwork_area = page.query_selector(
                '[class*="artwork"] button, [class*="coverArt"], '
                '[class*="image-upload"], [data-testid*="artwork"]'
            )
            if artwork_area:
                artwork_area.click()
                page.wait_for_timeout(1_000)
                # After clicking, a file input should appear
                img_input = page.query_selector('input[type="file"][accept*="image"]')
                if img_input:
                    img_input.set_input_files(str(thumbnail_path))
                    log.info(f"Artwork uploaded (via click): {thumbnail_path.name}")
                    page.wait_for_timeout(3_000)
                else:
                    log.warning("Artwork upload area found but no file input appeared")
            else:
                log.info("No artwork upload area found — track will use default artwork")
    except Exception as e:
        log.warning(f"Could not upload artwork: {e}")


def _wait_for_upload_complete(page) -> None:
    """Wait for SoundCloud to finish processing the uploaded audio file."""
    log.info("Waiting for upload to complete...")

    for wait in range(60):  # 60 × 5s = 5 minutes
        # Check for progress indicators
        progress = page.evaluate("""() => {
            // Look for progress bar or percentage text
            const progressBar = document.querySelector(
                '[class*="progress"], [role="progressbar"], [class*="upload"]'
            );
            if (progressBar) {
                const width = progressBar.style.width || progressBar.getAttribute('aria-valuenow');
                if (width) return 'progress:' + width;
            }
            // Check for "Uploading" text
            const uploading = document.querySelector(':scope *');
            const allText = document.body.innerText;
            if (allText.includes('Uploading')) return 'uploading';
            if (allText.includes('Processing')) return 'processing';
            if (allText.includes('Ready to publish') || allText.includes('Save')
                || allText.includes('ready')) return 'ready';
            return 'unknown';
        }""")

        if progress == "ready":
            log.info("Upload processing complete — ready to save")
            break
        elif progress in ("uploading", "processing") or progress.startswith("progress:"):
            if wait % 6 == 0:
                log.info(f"Upload in progress: {progress} ({wait * 5}s)")
        else:
            # Check if Save button is enabled — that means upload is done
            save_btn = _find_save_button(page)
            if save_btn:
                is_disabled = save_btn.get_attribute("disabled")
                if not is_disabled:
                    log.info("Save button is enabled — upload complete")
                    break

        page.wait_for_timeout(5_000)
    else:
        log.warning("Upload processing not confirmed after 5 min, continuing anyway")


def _find_save_button(page):
    """Find the Save/Publish button on SoundCloud upload form."""
    handle = page.evaluate_handle("""() => {
        const btns = [...document.querySelectorAll('button, input[type="submit"]')];
        const save = btns.find(b => {
            const text = b.textContent.trim().toLowerCase();
            return (text === 'save' || text === 'publish' || text === 'upload'
                    || text === 'save & publish' || text.includes('save'))
                && !b.disabled
                && b.offsetParent !== null;
        });
        return save || null;
    }""")
    return handle.as_element()


def _wait_for_publish(page, track_name: str, debug_dir: Path) -> str | None:
    """Wait for SoundCloud to finish saving/publishing the track."""
    log.info("Waiting for SoundCloud to finish publishing (up to 3 min)...")
    pre_url = page.url
    track_url = None

    for wait in range(36):  # 36 × 5s = 3 minutes
        page.wait_for_timeout(5_000)
        current_url = page.url

        # URL changed — might be redirected to the track page
        if current_url != pre_url:
            log.info(f"Page navigated: {pre_url} -> {current_url}")
            if "/upload" not in current_url.lower():
                track_url = current_url
                break

        # Look for a link to the published track
        track_link = page.evaluate("""(trackName) => {
            const links = [...document.querySelectorAll('a[href]')];
            for (const link of links) {
                const href = link.getAttribute('href');
                if (href && href.includes('/') && !href.includes('/upload')
                    && !href.includes('/discover') && !href.includes('/stream')
                    && link.textContent.trim().length > 0) {
                    // Check if link text matches track name
                    if (link.textContent.trim().toLowerCase().includes(trackName.toLowerCase())) {
                        return href.startsWith('http') ? href : 'https://soundcloud.com' + href;
                    }
                }
            }
            return null;
        }""", track_name)

        if track_link:
            track_url = track_link
            log.info(f"Track link found: {track_url}")
            break

        # Check for success message
        success = page.evaluate("""() => {
            const text = document.body.innerText.toLowerCase();
            return text.includes('has been uploaded') || text.includes('successfully')
                || text.includes('your track is live') || text.includes('go to track');
        }""")
        if success:
            log.info("Success message detected")
            # Try to find the track URL in the page
            track_link = page.evaluate("""() => {
                const links = [...document.querySelectorAll('a[href]')];
                const trackLink = links.find(l => {
                    const href = l.getAttribute('href');
                    return href && !href.includes('/upload') && !href.includes('/discover')
                        && !href.includes('/stream') && !href.includes('/settings')
                        && href.split('/').length >= 3;
                });
                if (trackLink) {
                    const href = trackLink.getAttribute('href');
                    return href.startsWith('http') ? href : 'https://soundcloud.com' + href;
                }
                return null;
            }""")
            if track_link:
                track_url = track_link
            break

        if wait % 6 == 0 and wait > 0:
            page.screenshot(path=str(debug_dir / f"debug_soundcloud_publishing_{wait}.png"))
            log.info(f"Still waiting for publish... ({wait * 5}s)")

    return track_url
