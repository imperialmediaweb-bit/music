import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from modules.concept_generator import MusicConcept
from config import TIKTOK_COOKIE_FILE, HEADLESS
from utils.browser import get_browser_context, save_cookies
from utils.logger import log

# TikTok migrated to TikTok Studio — /upload redirects there anyway,
# but going directly avoids an extra redirect and potential issues.
TIKTOK_UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload"
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
    """Dismiss cookie consent banner, TUXModal overlays, and any popups."""
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

    # Dismiss TUXModal overlays (TikTok's modal system — blocks all interactions)
    tux_dismissed = page.evaluate("""() => {
        const results = [];
        // Find all open TUXModal portals and click any dismiss buttons inside
        const portal = document.querySelector('#tux-portal-container');
        if (!portal) return results;
        const backdrop = portal.querySelector('._TUXModal-backdrop--entered, [class*="TUXModal-backdrop"]');
        if (!backdrop) return results;
        // Try clicking buttons inside the modal (close, got it, ok, etc.)
        const modalBtns = [...portal.querySelectorAll('button')];
        for (const btn of modalBtns) {
            const text = btn.textContent.trim().toLowerCase();
            if (['got it', 'ok', 'close', 'dismiss', 'maybe later', 'not now', 'confirm', 'done'].includes(text)) {
                btn.click();
                results.push('btn:' + text);
            }
        }
        // If no dismiss button found, try clicking the close icon (X)
        if (results.length === 0) {
            const closeIcon = portal.querySelector('[class*="close"], [aria-label="Close"], [class*="CloseButton"]');
            if (closeIcon) {
                closeIcon.click();
                results.push('close-icon');
            }
        }
        // Last resort: remove the backdrop entirely so it stops blocking clicks
        if (results.length === 0) {
            backdrop.remove();
            results.push('backdrop-removed');
        }
        return results;
    }""")
    if tux_dismissed and len(tux_dismissed) > 0:
        log.info(f"TUXModal dismissed: {tux_dismissed}")
        page.wait_for_timeout(1000)

    # Also try Escape key to close any modal
    try:
        backdrop = page.query_selector('[class*="TUXModal-backdrop"]')
        if backdrop:
            page.keyboard.press("Escape")
            log.info("Pressed Escape to dismiss modal")
            page.wait_for_timeout(500)
    except Exception:
        pass

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


def _click_post_button(page, post_btn, selector: str, debug_dir: Path) -> None:
    """Try multiple click strategies on the Post button, retrying if the page
    doesn't change. TikTok sometimes ignores the first click silently."""
    pre_click_url = page.url

    for click_attempt in range(3):
        if click_attempt > 0:
            log.info(f"Post click retry #{click_attempt + 1}...")
            # Re-query the button — DOM may have changed
            post_btn = page.query_selector(selector)
            if not post_btn or not post_btn.is_visible():
                log.info("Post button gone after previous click — assuming success")
                return
            _dismiss_tiktok_popups(page)
            page.wait_for_timeout(1_000)
            post_btn.scroll_into_view_if_needed()
            page.wait_for_timeout(500)

        # Strategy 1: normal Playwright click (respects actionability)
        try:
            post_btn.click(timeout=5_000)
            log.info(f"Post button clicked (normal) on attempt {click_attempt + 1}")
        except (PlaywrightTimeout, Exception) as click_err:
            log.warning(f"Normal click failed: {click_err}")
            # Strategy 2: JS click (bypasses overlay issues)
            try:
                page.evaluate("(el) => el.click()", post_btn)
                log.info(f"Post button clicked (JS) on attempt {click_attempt + 1}")
            except Exception as js_err:
                log.warning(f"JS click also failed: {js_err}")
                # Strategy 3: click by coordinates
                box = post_btn.bounding_box()
                if box:
                    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                    log.info(f"Post button clicked (mouse coords) on attempt {click_attempt + 1}")

        page.screenshot(path=str(debug_dir / f"debug_tiktok_05_post_clicked_{click_attempt}.png"))

        # Wait and check if the click had any effect
        page.wait_for_timeout(5_000)
        current_url = page.url
        btn_after = page.query_selector(selector)
        btn_still_visible = btn_after and btn_after.is_visible()
        log.info(
            f"After click attempt {click_attempt + 1} — "
            f"URL changed: {current_url != pre_click_url}, "
            f"Post button still visible: {btn_still_visible}"
        )
        page.screenshot(path=str(debug_dir / f"debug_tiktok_05b_after_click_{click_attempt}.png"))

        # If URL changed or Post button disappeared, click worked
        if current_url != pre_click_url or not btn_still_visible:
            return

        # Check for error messages that might have appeared
        errors = page.evaluate("""() => {
            const els = [...document.querySelectorAll('[class*="error"], [class*="alert"], [role="alert"]')];
            return els.filter(e => e.offsetParent !== null).map(e => e.textContent.trim().substring(0, 100));
        }""")
        if errors:
            log.warning(f"Error messages on page after click: {errors}")

    log.warning("Post button click may not have worked after 3 attempts")


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
            # IMPORTANT: use :text-is() for EXACT text match.
            # :has-text("Post") matches "Posts" sidebar nav — WRONG button!
            post_selectors = [
                'button:text-is("Post")',
                'button[data-e2e="post-button"]',
                'div[class*="btn-post"] button',
                'button:text-is("Publish")',
            ]

            posted = False
            # Poll for up to 5 minutes, checking every 10 seconds
            for attempt in range(30):
                for selector in post_selectors:
                    try:
                        post_btn = page.query_selector(selector)
                        if post_btn and post_btn.is_visible() and post_btn.is_enabled():
                            # Log button details before clicking
                            btn_text = post_btn.text_content().strip()
                            btn_box = post_btn.bounding_box()
                            log.info(f"Post button found: '{btn_text}' at {btn_box} via {selector}")
                            posted = True

                            # Dismiss any overlays that may intercept the click
                            _dismiss_tiktok_popups(page)
                            page.wait_for_timeout(500)

                            # Scroll button into view and re-query (DOM may have changed)
                            post_btn.scroll_into_view_if_needed()
                            page.wait_for_timeout(500)

                            # Try clicking — multiple strategies
                            _click_post_button(page, post_btn, selector, debug_dir)
                            break
                    except Exception as e:
                        log.info(f"Post selector '{selector}' failed: {e}")
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
                        .map(b => ({text: b.textContent.trim().substring(0, 50), enabled: !b.disabled, box: b.getBoundingClientRect()}))
                        .slice(0, 20);
                }""")
                log.error(f"Visible buttons on page: {buttons}")
                raise RuntimeError("Post button not enabled after 5 minutes")

            # Wait for TikTok to finish publishing.
            # Strategy: detect that the upload page has actually changed — either
            # the URL navigated away from /upload, or the upload form disappeared,
            # or a post-publish modal/page appeared. We must NOT match text that
            # was already on the upload page (e.g. "Your video", "Uploaded").
            log.info("Waiting for TikTok to finish publishing (up to 5 min)...")
            pre_post_url = page.url
            video_url = None

            for wait_attempt in range(60):  # 60 × 5s = 5 minutes
                page.wait_for_timeout(5_000)
                current_url = page.url

                # 1. URL changed away from upload page — strong signal
                if current_url != pre_post_url:
                    log.info(f"Page navigated: {pre_post_url} -> {current_url}")
                    # Try to extract video URL from the new page
                    link = page.query_selector('a[href*="/video/"]')
                    if link:
                        href = link.get_attribute("href")
                        if href:
                            video_url = f"https://www.tiktok.com{href}" if href.startswith("/") else href
                    break

                # 2. Upload form disappeared (Post button gone = page transitioned)
                post_btn = page.query_selector('button:text-is("Post")')
                if not post_btn or not post_btn.is_visible():
                    log.info("Post button disappeared — page transitioned")
                    link = page.query_selector('a[href*="/video/"]')
                    if link:
                        href = link.get_attribute("href")
                        if href:
                            video_url = f"https://www.tiktok.com{href}" if href.startswith("/") else href
                    break

                # 3. Check for "Manage your posts" link — only appears after publish
                manage = page.query_selector(':text("Manage your posts")')
                if manage:
                    log.info("'Manage your posts' found — publish confirmed")
                    link = page.query_selector('a[href*="/video/"]')
                    if link:
                        href = link.get_attribute("href")
                        if href:
                            video_url = f"https://www.tiktok.com{href}" if href.startswith("/") else href
                    break

                if wait_attempt % 6 == 0:
                    page.screenshot(path=str(debug_dir / f"debug_tiktok_publishing_{wait_attempt}.png"))
                    log.info(f"Still on upload page... ({(wait_attempt + 1) * 5}s / 300s)")
                    # Dump page state for debugging
                    page_text = page.evaluate("() => document.body.innerText.substring(0, 500)")
                    log.info(f"Page text preview: {page_text[:200]}")
            else:
                log.warning("No publish confirmation after 5 min")
                page.screenshot(path=str(debug_dir / "debug_tiktok_publish_timeout.png"))
                page_text = page.evaluate("() => document.body.innerText.substring(0, 1000)")
                log.error(f"Page text at timeout: {page_text[:500]}")

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
