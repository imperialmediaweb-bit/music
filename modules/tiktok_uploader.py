import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from modules.concept_generator import MusicConcept
from config import TIKTOK_COOKIE_FILE, HEADLESS
from utils.browser import get_browser_context, save_cookies
from utils.logger import log

TIKTOK_UPLOAD_URL = "https://www.tiktok.com/upload"
MAX_RETRIES = 2


def upload_to_tiktok(
    video_path: Path,
    concept: MusicConcept,
) -> str | None:
    log.info(f"Uploading to TikTok: {concept.track_name}")

    # Pre-flight: validate cookies exist and are non-empty
    if not TIKTOK_COOKIE_FILE.exists():
        log.error(
            f"TikTok cookies not found: {TIKTOK_COOKIE_FILE}\n"
            "Run: python main.py tiktok-login"
        )
        return None

    if TIKTOK_COOKIE_FILE.stat().st_size < 10:
        log.error(
            f"TikTok cookie file is empty: {TIKTOK_COOKIE_FILE}\n"
            "Run: python main.py tiktok-login"
        )
        return None

    # Retry loop
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = _do_upload(video_path, concept)
            return result
        except Exception as e:
            if attempt < MAX_RETRIES:
                wait = 2 ** attempt
                log.warning(f"TikTok upload attempt {attempt}/{MAX_RETRIES} failed: {e}")
                log.info(f"Retrying in {wait}s...")
                time.sleep(wait)
            else:
                log.error(f"TikTok upload failed after {MAX_RETRIES} attempts: {e}")
                raise


def _dismiss_tiktok_popups(page) -> None:
    """Dismiss cookie consent banner and any popups on TikTok Studio."""
    # Cookie banner — use JavaScript to find and click (most reliable)
    dismissed = page.evaluate("""() => {
        // Find banner buttons by text content
        const buttons = [...document.querySelectorAll('button')];
        for (const btn of buttons) {
            const text = btn.textContent.trim().toLowerCase();
            if (text === 'allow all' || text === 'allow all cookies'
                || text === 'accept all' || text === 'accept all cookies') {
                btn.click();
                return 'cookie:' + text;
            }
        }
        // Also try removing the entire banner overlay via common selectors
        for (const sel of ['[class*="cookie"]', '[id*="cookie"]', 'tiktok-cookie-banner']) {
            const el = document.querySelector(sel);
            if (el && el.offsetHeight > 50) {
                el.remove();
                return 'removed:' + sel;
            }
        }
        return null;
    }""")
    if dismissed:
        log.info(f"Cookie banner dismissed: {dismissed}")
        page.wait_for_timeout(1000)

    # Dismiss popups ("Got it", "New editing features", etc.)
    for popup_text in ["Got it", "OK", "Close", "Maybe later", "Not now"]:
        try:
            popup_btn = page.query_selector(f'button:has-text("{popup_text}")')
            if popup_btn and popup_btn.is_visible():
                popup_btn.click(force=True)
                log.info(f"Dismissed popup: '{popup_text}'")
                page.wait_for_timeout(500)
        except Exception:
            continue


def _do_upload(video_path: Path, concept: MusicConcept) -> str | None:
    """Single attempt to upload a video to TikTok."""
    debug_dir = Path("output")

    with sync_playwright() as p:
        browser, context = get_browser_context(p, TIKTOK_COOKIE_FILE)
        page = context.new_page()
        # Auto-accept any "Leave page?" / beforeunload dialogs
        page.on("dialog", lambda d: d.accept())

        try:
            # Navigate to TikTok upload page
            log.info(f"Navigating to {TIKTOK_UPLOAD_URL}...")
            # Use 'domcontentloaded' — TikTok keeps background requests active
            # forever (analytics, websockets) so 'networkidle' always times out.
            page.goto(TIKTOK_UPLOAD_URL, wait_until="domcontentloaded", timeout=60_000)
            # Give the SPA time to render after DOM is ready
            page.wait_for_timeout(8000)

            actual_url = page.url
            log.info(f"TikTok page loaded. URL: {actual_url}")
            page.screenshot(path=str(debug_dir / "debug_tiktok_01_loaded.png"))

            # Check if logged in — multiple patterns
            if ("login" in actual_url.lower()
                    or page.query_selector('[data-e2e="login-modal"]')
                    or page.query_selector('div[class*="login"]')):
                log.error(f"Not logged in to TikTok (redirected to: {actual_url})")
                log.error("Cookies may be expired. Please re-export TikTok cookies.")
                page.screenshot(path=str(debug_dir / "debug_tiktok_login_fail.png"))
                browser.close()
                return None

            log.info("TikTok login check passed")

            # Dismiss cookie consent banner aggressively (blocks all interactions)
            _dismiss_tiktok_popups(page)

            # Upload video file (input is hidden by design, use state="attached")
            log.info("Looking for video file input...")
            file_input = page.wait_for_selector(
                'input[type="file"][accept*="video"]',
                state="attached",
                timeout=15_000,
            )
            file_input.set_input_files(str(video_path))
            log.info(f"Video file selected: {video_path.name}")
            page.screenshot(path=str(debug_dir / "debug_tiktok_02_file_selected.png"))

            # Wait for video to finish uploading to TikTok servers.
            # IMPORTANT: Don't just check for ':text("Uploaded")' immediately —
            # that text may already exist on the page and cause a false positive.
            # Instead, first detect that upload is in progress, then wait for it
            # to finish, then wait extra time for TikTok to process the video.
            log.info("Waiting for TikTok to finish uploading (up to 5 min)...")

            # Give TikTok a few seconds to register the file and start uploading
            page.wait_for_timeout(5_000)

            # Try to detect active upload progress ("Uploading" text or percentage)
            upload_in_progress = False
            try:
                page.wait_for_selector(':text("Uploading")', timeout=15_000)
                upload_in_progress = True
                log.info("Upload in progress — waiting for completion...")
            except PlaywrightTimeout:
                log.info("No 'Uploading' progress indicator found")

            if upload_in_progress:
                # Wait for "Uploading" text to disappear (= upload finished)
                try:
                    page.wait_for_selector(
                        ':text("Uploading")', state="hidden", timeout=300_000
                    )
                    log.info("Video upload confirmed ('Uploading' indicator gone)")
                except PlaywrightTimeout:
                    log.warning("Upload still showing after 5 min, continuing anyway")
            else:
                # No "Uploading" indicator — poll manually with a minimum 30s wait
                log.info("Polling for upload completion...")
                upload_start = time.time()
                while time.time() - upload_start < 300:
                    uploaded_el = page.query_selector(':text("Uploaded")')
                    uploading_el = page.query_selector(':text("Uploading")')
                    if uploaded_el and not uploading_el:
                        log.info("Video upload confirmed (Uploaded indicator found)")
                        break
                    elapsed = int(time.time() - upload_start)
                    if elapsed % 15 == 0 and elapsed > 0:
                        log.info(f"Still waiting for upload... ({elapsed}s)")
                    page.wait_for_timeout(5_000)
                else:
                    log.warning("Upload not confirmed after 5 min, continuing anyway")

            # Wait 5 minutes for TikTok to process the video on their servers.
            # Without this, the Post button may be enabled but the video won't
            # actually publish correctly.
            log.info("Waiting 5 minutes for TikTok to process the video...")
            for i in range(30):  # 30 × 10s = 5 minutes
                page.wait_for_timeout(10_000)
                if (i + 1) % 6 == 0:  # Log + screenshot every 60 seconds
                    elapsed_min = (i + 1) * 10 / 60
                    log.info(f"Processing wait: {elapsed_min:.0f} min / 5 min")
                    page.screenshot(
                        path=str(debug_dir / f"debug_tiktok_processing_{int(elapsed_min)}m.png")
                    )

            page.screenshot(path=str(debug_dir / "debug_tiktok_03_after_processing.png"))

            # Dismiss cookie banner + popups again (may reappear after upload)
            _dismiss_tiktok_popups(page)

            # Dump all editable elements for debugging
            editables = page.evaluate("""() => {
                return [...document.querySelectorAll('[contenteditable="true"], [role="textbox"], textarea')]
                    .map(e => ({
                        tag: e.tagName,
                        classes: e.className.substring(0, 80),
                        role: e.getAttribute('role'),
                        visible: e.offsetParent !== null,
                        text: e.textContent.substring(0, 30)
                    }));
            }""")
            log.info(f"Editable elements found: {editables}")

            # Fill in the caption / description
            # TikTok Studio shows "Description" field with the filename pre-filled
            log.info(f"Filling caption: {concept.tiktok_caption[:50]}...")
            caption_selectors = [
                'div[role="textbox"][contenteditable="true"]',
                '[contenteditable="true"][data-text="true"]',
                '.public-DraftEditor-content [contenteditable="true"]',
                '[contenteditable="true"]',
                'div[role="textbox"]',
                '.DraftEditor-root',
            ]

            filled = False
            for selector in caption_selectors:
                try:
                    elements = page.query_selector_all(selector)
                    for caption_el in elements:
                        if caption_el and caption_el.is_visible():
                            # Click into the editor
                            caption_el.click(force=True)
                            page.wait_for_timeout(500)
                            # Select all and delete existing text
                            page.keyboard.press("Control+a")
                            page.wait_for_timeout(200)
                            page.keyboard.press("Backspace")
                            page.wait_for_timeout(200)
                            # Type the caption
                            page.keyboard.type(concept.tiktok_caption, delay=20)
                            filled = True
                            log.info(f"Caption filled using: {selector}")
                            break
                    if filled:
                        break
                except Exception as e:
                    log.info(f"Caption selector '{selector}' failed: {e}")
                    continue

            if not filled:
                log.warning("Could not fill caption via selectors, trying JS fallback")
                try:
                    # Use JavaScript to find and fill the description
                    page.evaluate("""(text) => {
                        const el = document.querySelector('[contenteditable="true"]');
                        if (el) { el.focus(); el.textContent = text; }
                    }""", concept.tiktok_caption)
                    filled = True
                    log.info("Caption filled using JS fallback")
                except Exception as e:
                    log.warning(f"JS fallback also failed: {e}")

            page.wait_for_timeout(2000)
            page.screenshot(path=str(debug_dir / "debug_tiktok_04_caption_filled.png"))

            # Scroll down to make sure Post button is visible
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1000)

            # Dismiss popups again before clicking Post
            _dismiss_tiktok_popups(page)

            # Wait for Post button to become enabled (red) — video must finish
            # processing first, which can take several minutes for large files.
            log.info("Waiting for Post button to become enabled (up to 5 min)...")
            post_selectors = [
                'button:has-text("Post")',
                'div[class*="btn-post"]',
                'button[data-e2e="post-button"]',
                'button:has-text("Publish")',
                'button:has-text("Upload")',
            ]

            posted = False
            # Poll for up to 5 minutes, checking every 10 seconds
            for attempt in range(30):
                for selector in post_selectors:
                    try:
                        post_btn = page.query_selector(selector)
                        if post_btn and post_btn.is_visible() and post_btn.is_enabled():
                            log.info(f"Post button enabled: {selector}")
                            try:
                                post_btn.click(force=True, timeout=10_000)
                            except PlaywrightTimeout:
                                log.warning(f"click() timed out for '{selector}', trying dispatch_event")
                                post_btn.dispatch_event("click")
                            posted = True
                            log.info(f"Post button clicked: {selector}")
                            break
                    except Exception:
                        continue
                if posted:
                    break
                if attempt < 29:
                    if attempt % 3 == 0:
                        page.screenshot(path=str(debug_dir / f"debug_tiktok_waiting_post_{attempt}.png"))
                        log.info(f"Post button not ready yet, waiting... ({(attempt + 1) * 10}s / 300s)")
                    page.wait_for_timeout(10_000)

            if not posted:
                page.screenshot(path=str(debug_dir / "debug_tiktok_no_post.png"))
                buttons = page.evaluate("""() => {
                    return [...document.querySelectorAll('button')]
                        .filter(b => b.offsetParent !== null)
                        .map(b => ({text: b.textContent.trim().substring(0, 50), enabled: !b.disabled}))
                        .slice(0, 20);
                }""")
                log.error(f"Visible buttons on page: {buttons}")
                raise RuntimeError("Post button not enabled after 5 minutes")

            page.screenshot(path=str(debug_dir / "debug_tiktok_05_post_clicked.png"))

            # Wait for TikTok to finish publishing — poll for success indicators
            # for up to 5 minutes instead of a blind sleep.
            # IMPORTANT: Wait a few seconds first so the page can transition after
            # clicking Post. Otherwise we may match stale text like "Uploaded" from
            # the file-upload step and get a false positive.
            log.info("Waiting for TikTok to finish publishing (up to 5 min)...")
            page.wait_for_timeout(5_000)
            video_url = None
            # Only use selectors that indicate the POST was published, not file upload.
            # ':text("uploaded")' was removed — it matches the file-upload indicator
            # that is already on the page and causes false positives.
            success_selectors = [
                ':text("Manage your posts")',
                ':text("Your video is being uploaded to TikTok")',
                ':text("Your videos")',
                ':text("successfully")',
                ':text("Your video")',
                'a[href*="/video/"]',
                'a[href*="/@"]',
            ]
            for wait_attempt in range(30):
                for sel in success_selectors:
                    try:
                        el = page.query_selector(sel)
                        if el:
                            href = el.get_attribute("href")
                            if href and ("/@" in href or "/video/" in href):
                                video_url = f"https://www.tiktok.com{href}" if href.startswith("/") else href
                            log.info(f"Success indicator found: {sel}")
                            break
                    except Exception:
                        continue
                else:
                    # No success indicator found yet — keep waiting
                    if wait_attempt % 3 == 0:
                        page.screenshot(path=str(debug_dir / f"debug_tiktok_publishing_{wait_attempt}.png"))
                        log.info(f"Still publishing... ({(wait_attempt + 1) * 10}s / 300s)")
                    page.wait_for_timeout(10_000)
                    continue
                # Success indicator found — break outer loop
                break

            page.screenshot(path=str(debug_dir / "debug_tiktok_06_final.png"))

            if video_url:
                log.info(f"TikTok video URL: {video_url}")
            else:
                log.info("TikTok upload completed (URL not captured)")

            # Save updated cookies
            save_cookies(context, TIKTOK_COOKIE_FILE)

            # Return the URL, or a sentinel indicating success without URL
            return video_url or "uploaded (URL not available)"

        except Exception as e:
            log.error(f"TikTok upload failed: {e}")
            try:
                page.screenshot(path=str(debug_dir / "debug_tiktok_error.png"))
            except Exception:
                pass
            raise
        finally:
            browser.close()
