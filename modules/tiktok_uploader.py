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


def _do_upload(video_path: Path, concept: MusicConcept) -> str | None:
    """Single attempt to upload a video to TikTok."""
    debug_dir = Path("output")

    with sync_playwright() as p:
        browser, context = get_browser_context(p, TIKTOK_COOKIE_FILE)
        page = context.new_page()

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

            # Wait longer for video processing
            log.info("Waiting for TikTok to process video (20s)...")
            page.wait_for_timeout(20_000)
            page.screenshot(path=str(debug_dir / "debug_tiktok_03_after_processing.png"))

            # Fill in the caption
            log.info(f"Filling caption: {concept.tiktok_caption[:50]}...")
            caption_selectors = [
                '[contenteditable="true"]',
                'div[data-text="true"]',
                '.public-DraftEditor-content',
                '#caption-editor',
                'div[role="textbox"]',
            ]

            filled = False
            for selector in caption_selectors:
                try:
                    caption_el = page.wait_for_selector(selector, timeout=5_000)
                    if caption_el and caption_el.is_visible():
                        caption_el.click()
                        # Clear existing text
                        page.keyboard.select_all()
                        page.keyboard.press("Backspace")
                        page.keyboard.type(concept.tiktok_caption)
                        filled = True
                        log.info(f"Caption filled using: {selector}")
                        break
                except PlaywrightTimeout:
                    continue

            if not filled:
                log.warning("Could not find caption input, continuing without caption")

            page.wait_for_timeout(2000)
            page.screenshot(path=str(debug_dir / "debug_tiktok_04_caption_filled.png"))

            # Click the Post button
            log.info("Looking for Post/Publish button...")
            post_selectors = [
                'button:has-text("Post")',
                'div[class*="btn-post"]',
                'button[data-e2e="post-button"]',
                'button:has-text("Publish")',
                'button:has-text("Upload")',
            ]

            posted = False
            for selector in post_selectors:
                try:
                    post_btn = page.wait_for_selector(selector, timeout=5_000)
                    if post_btn and post_btn.is_visible():
                        is_enabled = post_btn.is_enabled()
                        log.info(f"Found button '{selector}' — enabled={is_enabled}")
                        if is_enabled:
                            post_btn.click()
                            posted = True
                            log.info(f"Post button clicked: {selector}")
                            break
                        else:
                            log.warning(f"Button '{selector}' found but disabled, trying next...")
                except PlaywrightTimeout:
                    continue

            if not posted:
                page.screenshot(path=str(debug_dir / "debug_tiktok_no_post.png"))
                # Log all visible buttons for debugging
                buttons = page.evaluate("""() => {
                    return [...document.querySelectorAll('button')]
                        .filter(b => b.offsetParent !== null)
                        .map(b => b.textContent.trim().substring(0, 50))
                        .slice(0, 20);
                }""")
                log.error(f"Visible buttons on page: {buttons}")
                raise RuntimeError("Could not find Post button on TikTok")

            page.screenshot(path=str(debug_dir / "debug_tiktok_05_post_clicked.png"))

            # Wait for upload completion
            log.info("Waiting for upload to complete (30s)...")
            page.wait_for_timeout(30_000)
            page.screenshot(path=str(debug_dir / "debug_tiktok_06_after_upload.png"))

            # Try to detect success
            video_url = None
            try:
                success_selectors = [
                    'a[href*="/@"]',
                    ':text("uploaded")',
                    ':text("Your video")',
                    ':text("successfully")',
                ]
                for sel in success_selectors:
                    try:
                        el = page.wait_for_selector(sel, timeout=10_000)
                        if el:
                            href = el.get_attribute("href")
                            if href and "/@" in href:
                                video_url = f"https://www.tiktok.com{href}" if href.startswith("/") else href
                                break
                    except PlaywrightTimeout:
                        continue
            except Exception:
                pass

            page.screenshot(path=str(debug_dir / "debug_tiktok_07_final.png"))

            if video_url:
                log.info(f"TikTok video URL: {video_url}")
            else:
                log.info("TikTok upload completed (URL not captured)")

            # Save updated cookies
            save_cookies(context, TIKTOK_COOKIE_FILE)

            return video_url

        except Exception as e:
            log.error(f"TikTok upload failed: {e}")
            try:
                page.screenshot(path=str(debug_dir / "debug_tiktok_error.png"))
            except Exception:
                pass
            raise
        finally:
            browser.close()
