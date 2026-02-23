import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from modules.concept_generator import MusicConcept
from config import YOUTUBE_COOKIE_FILE, HEADLESS
from utils.browser import get_browser_context, save_cookies
from utils.logger import log

YOUTUBE_STUDIO_URL = "https://studio.youtube.com"
UPLOAD_TIMEOUT_MS = 300_000  # 5 minutes for upload processing


def upload_to_youtube(
    video_path: Path,
    thumbnail_path: Path,
    concept: MusicConcept,
) -> str | None:
    log.info(f"Uploading to YouTube: {concept.youtube_title}")

    with sync_playwright() as p:
        browser, context = get_browser_context(p, YOUTUBE_COOKIE_FILE)
        page = context.new_page()

        try:
            # Navigate to YouTube Studio
            page.goto(YOUTUBE_STUDIO_URL, wait_until="networkidle", timeout=30_000)
            page.wait_for_timeout(3000)

            # Check if logged in — look for upload button or channel icon
            if "accounts.google.com" in page.url:
                log.error("Not logged in to YouTube. Please export cookies first.")
                browser.close()
                return None

            # Click the Create/Upload button
            log.info("Looking for upload button...")
            upload_btn = page.wait_for_selector(
                '#upload-icon, #create-icon, button:has-text("Create"), '
                'ytcp-button#create-icon',
                timeout=10_000,
            )
            upload_btn.click()
            page.wait_for_timeout(1000)

            # Click "Upload videos" from dropdown
            upload_videos = page.wait_for_selector(
                '#text-item-0, tp-yt-paper-item:has-text("Upload videos"), '
                'a:has-text("Upload videos")',
                timeout=5_000,
            )
            upload_videos.click()
            page.wait_for_timeout(2000)

            # Upload the video file via file chooser
            log.info("Selecting video file...")
            file_input = page.wait_for_selector(
                'input[type="file"]',
                timeout=10_000,
            )
            file_input.set_input_files(str(video_path))
            log.info("Video file selected, waiting for processing...")

            # Wait for the details form to appear
            page.wait_for_timeout(5000)

            # Fill in title
            log.info("Filling in video details...")
            title_input = page.wait_for_selector(
                '#textbox[aria-label*="title"], #title-textarea #textbox, '
                'div#textbox.ytcp-social-suggestions-textbox',
                timeout=15_000,
            )
            title_input.click()
            page.keyboard.select_all()
            page.keyboard.type(concept.youtube_title)

            # Fill in description
            desc_input = page.wait_for_selector(
                '#textbox[aria-label*="description"], #description-textarea #textbox',
                timeout=5_000,
            )
            desc_input.click()
            tags_line = " ".join("#" + h.replace(" ", "") for h in concept.hashtags)
            desc_text = (
                f"{concept.youtube_description}\n\n"
                f"{tags_line}"
            )
            page.keyboard.type(desc_text)

            # Add YouTube tags if the tags section is available
            try:
                # Click "Show more" to reveal tags input
                show_more = page.wait_for_selector(
                    'ytcp-button#toggle-button, button:has-text("Show more")',
                    timeout=3_000,
                )
                show_more.click()
                page.wait_for_timeout(1000)

                tags_input = page.wait_for_selector(
                    'input[aria-label*="Tags"], #tags-container input, '
                    'input[placeholder*="Add tag"]',
                    timeout=3_000,
                )
                tags_input.click()
                tags_text = ",".join(concept.youtube_tags)
                page.keyboard.type(tags_text)
                log.info(f"Added {len(concept.youtube_tags)} YouTube tags")
            except PlaywrightTimeout:
                log.warning("Could not find tags input, skipping tags")

            # Upload custom thumbnail
            log.info("Uploading custom thumbnail...")
            try:
                thumb_input = page.wait_for_selector(
                    '#file-loader input[type="file"], '
                    'input[accept="image/jpeg,image/png"]',
                    timeout=5_000,
                )
                thumb_input.set_input_files(str(thumbnail_path))
                page.wait_for_timeout(3000)
            except PlaywrightTimeout:
                log.warning("Could not find thumbnail upload input, skipping")

            # Click through the steps: "Next" buttons
            for step in range(3):
                try:
                    next_btn = page.wait_for_selector(
                        '#next-button, ytcp-button#next-button',
                        timeout=5_000,
                    )
                    next_btn.click()
                    page.wait_for_timeout(2000)
                except PlaywrightTimeout:
                    break

            # Set visibility to Public
            log.info("Setting visibility to Public...")
            try:
                public_radio = page.wait_for_selector(
                    '#offRadio, tp-yt-paper-radio-button[name="PUBLIC"], '
                    'tp-yt-paper-radio-button:has-text("Public")',
                    timeout=5_000,
                )
                public_radio.click()
                page.wait_for_timeout(1000)
            except PlaywrightTimeout:
                log.warning("Could not find Public visibility option")

            # Click Publish/Done
            log.info("Publishing video...")
            done_btn = page.wait_for_selector(
                '#done-button, ytcp-button#done-button',
                timeout=5_000,
            )
            done_btn.click()

            # Wait for upload to complete
            page.wait_for_timeout(10_000)

            # Try to get the video URL from the success dialog
            video_url = None
            try:
                link = page.wait_for_selector(
                    'a.ytcp-video-info, a[href*="youtu.be"], '
                    'span.video-url-fadeable a',
                    timeout=30_000,
                )
                video_url = link.get_attribute("href")
                log.info(f"YouTube video URL: {video_url}")
            except PlaywrightTimeout:
                log.warning("Could not capture YouTube video URL")

            # Save updated cookies
            save_cookies(context, YOUTUBE_COOKIE_FILE)

            return video_url

        except Exception as e:
            log.error(f"YouTube upload failed: {e}")
            page.screenshot(path=str(Path("output") / "debug_youtube_error.png"))
            raise
        finally:
            browser.close()
