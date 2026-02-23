from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from modules.concept_generator import MusicConcept
from config import TIKTOK_COOKIE_FILE, HEADLESS
from utils.browser import get_browser_context, save_cookies
from utils.logger import log

TIKTOK_UPLOAD_URL = "https://www.tiktok.com/upload"


def upload_to_tiktok(
    video_path: Path,
    concept: MusicConcept,
) -> str | None:
    log.info(f"Uploading to TikTok: {concept.track_name}")

    with sync_playwright() as p:
        browser, context = get_browser_context(p, TIKTOK_COOKIE_FILE)
        page = context.new_page()

        try:
            # Navigate to TikTok upload page
            page.goto(TIKTOK_UPLOAD_URL, wait_until="networkidle", timeout=30_000)
            page.wait_for_timeout(3000)

            # Check if logged in
            if "login" in page.url.lower():
                log.error("Not logged in to TikTok. Please export cookies first.")
                browser.close()
                return None

            # Upload video file
            log.info("Selecting video file...")
            file_input = page.wait_for_selector(
                'input[type="file"][accept*="video"]',
                timeout=15_000,
            )
            file_input.set_input_files(str(video_path))
            log.info("Video file selected, waiting for processing...")
            page.wait_for_timeout(10_000)

            # Fill in the caption
            log.info("Filling in caption...")
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
                        log.info(f"Caption filled using selector: {selector}")
                        break
                except PlaywrightTimeout:
                    continue

            if not filled:
                log.warning("Could not find caption input, continuing without caption")

            page.wait_for_timeout(2000)

            # Click the Post button
            log.info("Clicking Post button...")
            post_selectors = [
                'button:has-text("Post")',
                'div[class*="btn-post"]',
                'button[data-e2e="post-button"]',
                'button:has-text("Publish")',
            ]

            posted = False
            for selector in post_selectors:
                try:
                    post_btn = page.wait_for_selector(selector, timeout=5_000)
                    if post_btn and post_btn.is_visible() and post_btn.is_enabled():
                        post_btn.click()
                        posted = True
                        log.info(f"Post button clicked: {selector}")
                        break
                except PlaywrightTimeout:
                    continue

            if not posted:
                page.screenshot(path=str(Path("output") / "debug_tiktok_no_post.png"))
                raise RuntimeError("Could not find Post button on TikTok")

            # Wait for upload completion
            page.wait_for_timeout(15_000)

            # Try to detect success
            video_url = None
            try:
                success_selectors = [
                    'a[href*="/@"]',
                    ':text("uploaded")',
                    ':text("Your video")',
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

            if video_url:
                log.info(f"TikTok video URL: {video_url}")
            else:
                log.info("TikTok upload completed (URL not captured)")

            # Save updated cookies
            save_cookies(context, TIKTOK_COOKIE_FILE)

            return video_url

        except Exception as e:
            log.error(f"TikTok upload failed: {e}")
            page.screenshot(path=str(Path("output") / "debug_tiktok_error.png"))
            raise
        finally:
            browser.close()
