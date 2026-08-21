"""Upload videos to YouTube using the official YouTube Data API v3.

Uses OAuth2 for authentication (first time requires browser login,
then token is saved for future uploads).
"""

import json
import pickle
from pathlib import Path

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from modules.concept_generator import MusicConcept
from config import (
    BASE_DIR, OUTPUT_DIR, YOUTUBE_COOKIE_FILE, YOUTUBE_TOKEN_FILE, HEADLESS,
    SPOTIFY_ARTIST_URL, BEATPORT_ARTIST_URL,
)
from utils.browser import get_browser_context, save_cookies
from utils.logger import log

# OAuth2 scopes — full youtube scope for upload + playlist management
SCOPES = ["https://www.googleapis.com/auth/youtube",
          "https://www.googleapis.com/auth/youtube.force-ssl"]

# Paths for OAuth credentials
CLIENT_SECRETS_FILE = BASE_DIR / "client_secrets.json"
# TOKEN_FILE is profile-aware via config.YOUTUBE_TOKEN_FILE so each YouTube
# channel (Afro House / Dark House / ...) uploads with its own OAuth token.
TOKEN_FILE = YOUTUBE_TOKEN_FILE


def _get_authenticated_service():
    """Get an authenticated YouTube API service using OAuth2."""
    credentials = None

    # Load saved token if it exists
    if TOKEN_FILE.exists():
        with open(TOKEN_FILE, "rb") as f:
            credentials = pickle.load(f)
        log.info(f"YouTube token loaded from {TOKEN_FILE}")

        # Check scopes BEFORE anything else — if wrong, delete and re-auth
        saved_scopes = getattr(credentials, "scopes", None) or set()
        if not set(SCOPES).issubset(saved_scopes):
            log.warning(f"Token scopes mismatch. Have: {saved_scopes}, need: {SCOPES}")
            log.info("Deleting old token — will re-authenticate with correct scopes")
            TOKEN_FILE.unlink(missing_ok=True)
            credentials = None

    # If no valid credentials, try to refresh or re-authenticate
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            log.info("Refreshing expired YouTube token...")
            try:
                credentials.refresh(Request())
                log.info("YouTube token refreshed successfully")
            except Exception as e:
                log.warning(f"Token refresh failed: {e} — will re-authenticate")
                credentials = None

        if not credentials or not credentials.valid:
            if not CLIENT_SECRETS_FILE.exists():
                raise FileNotFoundError(
                    f"OAuth client secrets not found: {CLIENT_SECRETS_FILE}\n"
                    "To set up YouTube uploads:\n"
                    "1. Go to https://console.cloud.google.com/apis/credentials\n"
                    "2. Create OAuth 2.0 Client ID (Desktop application)\n"
                    "3. Download the JSON and save as: client_secrets.json\n"
                    "4. Run the pipeline again - a browser will open for login"
                )
            log.info("Starting YouTube OAuth login (browser will open)...")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CLIENT_SECRETS_FILE), SCOPES
            )
            credentials = flow.run_local_server(port=0)

        # Save token for future use
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(credentials, f)
        log.info("YouTube token saved")

    return build("youtube", "v3", credentials=credentials)


def _find_or_create_playlist(youtube, playlist_title="Afro House") -> str:
    """Find existing playlist by title, or create a new one.

    Returns the playlist ID.
    """
    # Search existing playlists
    request = youtube.playlists().list(part="snippet", mine=True, maxResults=50)
    response = request.execute()
    for item in response.get("items", []):
        if item["snippet"]["title"].lower() == playlist_title.lower():
            log.info(f"Found existing playlist '{playlist_title}' (id={item['id']})")
            return item["id"]

    # Create new playlist
    log.info(f"Creating new playlist '{playlist_title}'...")
    body = {
        "snippet": {
            "title": playlist_title,
            "description": "Afro House Music Collection — Deep Tribal Drums & Underground Grooves",
        },
        "status": {"privacyStatus": "public"},
    }
    result = youtube.playlists().insert(part="snippet,status", body=body).execute()
    log.info(f"Created playlist '{playlist_title}' (id={result['id']})")
    return result["id"]


def _add_to_playlist(youtube, playlist_id: str, video_id: str):
    """Add a video to a YouTube playlist."""
    youtube.playlistItems().insert(
        part="snippet",
        body={
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {
                    "kind": "youtube#video",
                    "videoId": video_id,
                },
            }
        },
    ).execute()
    log.info(f"Video {video_id} added to playlist {playlist_id}")


def post_comment(video_id: str, text: str) -> str | None:
    """Post a comment on a YouTube video. Returns comment ID or None."""
    try:
        youtube = _get_authenticated_service()
        response = youtube.commentThreads().insert(
            part="snippet",
            body={
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {
                        "snippet": {
                            "textOriginal": text,
                        }
                    },
                }
            },
        ).execute()
        comment_id = response["id"]
        log.info(f"Comment posted on {video_id}: {comment_id}")
        return comment_id
    except Exception as e:
        log.warning(f"Failed to post comment on {video_id}: {e}")
        return None


def pin_comment(video_id: str, comment_id: str) -> bool:
    """Pin our comment via the watch page (the Data API cannot pin).

    Opens watch?v=ID&lc=COMMENT_ID — the `lc` param renders that comment as
    the first "highlighted" thread — then clicks its ⋮ menu → Pin → confirm.
    Menu text is matched case-insensitively in English and Romanian ("Pin" /
    "Fixează") so a localized UI still works. Non-fatal: returns False on any
    failure and leaves the comment simply unpinned.
    """
    url = f"https://www.youtube.com/watch?v={video_id}&lc={comment_id}"
    log.info(f"Pinning comment: {url}")

    with sync_playwright() as p:
        browser, context = get_browser_context(p, YOUTUBE_COOKIE_FILE)
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(5000)

            # Comments lazy-load — scroll until the highlighted thread renders.
            thread = None
            for _ in range(10):
                thread = page.query_selector("ytd-comment-thread-renderer")
                if thread:
                    break
                page.evaluate("window.scrollBy(0, 900)")
                page.wait_for_timeout(1200)
            if not thread:
                log.warning("pin_comment: comment thread never rendered")
                return False

            # Open the thread's ⋮ action menu.
            menu_btn = (thread.query_selector("#action-menu button")
                        or thread.query_selector("#action-menu yt-icon-button"))
            if not menu_btn:
                log.warning("pin_comment: action menu button not found")
                return False
            menu_btn.click(force=True)
            page.wait_for_timeout(1500)

            # Click the "Pin" item (language-tolerant).
            clicked = False
            for item in page.query_selector_all(
                "ytd-menu-service-item-renderer, tp-yt-paper-item"
            ):
                try:
                    txt = (item.inner_text() or "").strip().lower()
                    if txt.startswith("pin") or "fixeaz" in txt:
                        item.click(force=True)
                        clicked = True
                        break
                except Exception:
                    continue
            if not clicked:
                log.warning("pin_comment: 'Pin' menu item not found")
                return False
            page.wait_for_timeout(1500)

            # Confirm dialog ("Pin"/"Fixează" — #confirm-button is stable).
            for sel in ("yt-confirm-dialog-renderer #confirm-button",
                        "#confirm-button"):
                try:
                    btn = page.query_selector(sel)
                    if btn and btn.is_visible():
                        btn.click(force=True)
                        break
                except Exception:
                    continue
            page.wait_for_timeout(2000)
            log.info(f"Pinned comment {comment_id} on {video_id}")
            return True
        except Exception as e:
            log.warning(f"pin_comment failed: {e}")
            return False
        finally:
            browser.close()


def reply_to_new_comments(max_videos: int = 5, max_replies_per_video: int = 3) -> int:
    """Auto-reply to unanswered comments on recent videos.

    Finds comment threads on the channel's latest videos where the channel
    has not replied yet, and posts an engagement reply. Returns total replies sent.
    """
    import random

    try:
        youtube = _get_authenticated_service()
    except FileNotFoundError as e:
        log.error(str(e))
        return 0

    try:
        channels = youtube.channels().list(part="contentDetails", mine=True).execute()
        uploads_playlist = channels["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    except Exception as e:
        log.warning(f"Could not get channel uploads: {e}")
        return 0

    try:
        playlist_items = youtube.playlistItems().list(
            part="snippet", playlistId=uploads_playlist, maxResults=max(max_videos, 5)
        ).execute()
        all_items = playlist_items.get("items", [])
        video_ids = [item["snippet"]["resourceId"]["videoId"] for item in all_items]
    except Exception as e:
        log.warning(f"Could not list recent videos: {e}")
        return 0

    try:
        channels_resp = youtube.channels().list(part="id", mine=True).execute()
        my_channel_id = channels_resp["items"][0]["id"]
    except Exception:
        my_channel_id = None

    # Build latest video link for cross-promotion in replies
    latest_url = ""
    if len(video_ids) >= 2:
        latest_url = f"https://youtu.be/{video_ids[0]}"

    REPLY_TEMPLATES = [
        "Thank you so much for listening! 🔥 Which part was your favorite? Share with a friend who needs this vibe! 🎧",
        "Glad you're here! 🙌 Hit Subscribe + 🔔 so you never miss a new mix! 🔥",
        "This means a lot! 🎶 Drop a ❤️ and share this track with someone who'd love it! 🙏",
        "Love that you're vibing with this! 🔥 Subscribe for daily mixes and share with your crew! 💪",
        "You're amazing for listening! 🎧 New tracks every day — Subscribe + 🔔! 🙌",
    ]
    if latest_url:
        REPLY_TEMPLATES = [
            f"Thank you! 🔥 Check out our latest drop too 👉 {latest_url} — share with a friend! 🎧",
            f"Glad you're here! 🙌 New mix just dropped 👉 {latest_url} — Subscribe + 🔔! 🔥",
            f"This means a lot! 🎶 Also check this one 👉 {latest_url} — share the vibes! 🙏",
            f"Love it! 🔥 Our newest track is fire too 👉 {latest_url} — Subscribe + share! 💪",
            f"You're amazing! 🎧 Latest mix here 👉 {latest_url} — Subscribe + 🔔! 🙌",
        ]

    total_replies = 0
    for vid_id in video_ids[:max_videos]:
        if total_replies >= max_replies_per_video * max_videos:
            break

        if vid_id == video_ids[0] and latest_url:
            pass

        try:
            threads = youtube.commentThreads().list(
                part="snippet,replies", videoId=vid_id, maxResults=20,
                order="time",
            ).execute()
        except Exception as e:
            log.warning(f"Could not get comments for {vid_id}: {e}")
            continue

        replies_this_video = 0
        for thread in threads.get("items", []):
            if replies_this_video >= max_replies_per_video:
                break

            snippet = thread["snippet"]
            top_comment = snippet["topLevelComment"]["snippet"]

            if my_channel_id and top_comment.get("authorChannelId", {}).get("value") == my_channel_id:
                continue

            if snippet.get("totalReplyCount", 0) > 0:
                replies = thread.get("replies", {}).get("comments", [])
                already_replied = any(
                    r["snippet"].get("authorChannelId", {}).get("value") == my_channel_id
                    for r in replies
                ) if my_channel_id else False
                if already_replied:
                    continue

            try:
                reply_text = random.choice(REPLY_TEMPLATES)
                youtube.comments().insert(
                    part="snippet",
                    body={
                        "snippet": {
                            "parentId": thread["id"],
                            "textOriginal": reply_text,
                        }
                    },
                ).execute()
                commenter = top_comment.get("authorDisplayName", "someone")
                log.info(f"Replied to {commenter} on {vid_id}")
                total_replies += 1
                replies_this_video += 1
            except Exception as e:
                log.warning(f"Reply failed: {e}")

    log.info(f"Auto-replied to {total_replies} comments across {len(video_ids)} videos")
    return total_replies


def _complete_self_certification(video_id: str) -> bool:
    """Complete YouTube Studio self-certification for monetization.

    Opens YouTube Studio via Playwright, navigates to the video's
    monetization page, turns monetization ON, selects 'None of the above'
    for ALL categories, and clicks Submit.
    Returns True on success, False on failure.
    """
    studio_url = f"https://studio.youtube.com/video/{video_id}/monetization"
    debug_dir = OUTPUT_DIR

    log.info(f"Opening YouTube Studio for self-certification: {studio_url}")

    with sync_playwright() as p:
        browser, context = get_browser_context(p, YOUTUBE_COOKIE_FILE)
        page = context.new_page()

        try:
            page.goto(studio_url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(8000)

            actual_url = page.url
            log.info(f"YouTube Studio loaded. URL: {actual_url}")
            page.screenshot(path=str(debug_dir / "debug_yt_monetization_01.png"))

            # Check if we're redirected to login
            if "accounts.google.com" in actual_url:
                log.error("Not logged into YouTube Studio. Cookies may be expired.")
                log.error("Run: python main.py youtube-login")
                return False

            # Log page state for debugging
            page_text = (page.text_content("body") or "")[:500]
            log.info(f"Page text preview: {page_text[:200]}")

            # Step 1 (CURRENT Studio UI): the monetization page shows a
            # "Watch page ads and YouTube Premium" card with On/Off radio
            # buttons, a Done button, then a Save button top-right. Click the
            # exact "On" radio (NOT substring matching — "None of the above"
            # also contains "on").
            ads_on_done = False
            try:
                radios = page.query_selector_all(
                    'tp-yt-paper-radio-button, ytcp-radio-button, [role="radio"]'
                )
                for r in radios:
                    try:
                        if not r.is_visible():
                            continue
                        txt = (r.inner_text() or "").strip().lower()
                        if txt == "on":
                            checked = (r.get_attribute("aria-checked") or
                                       r.get_attribute("checked") or "")
                            if checked == "true":
                                log.info("Ads radio already ON")
                                ads_on_done = True
                            else:
                                r.click(force=True)
                                page.wait_for_timeout(1500)
                                log.info("Clicked ads radio 'On'")
                                ads_on_done = True
                            break
                    except Exception:
                        continue
                if ads_on_done:
                    # Confirm the card with its Done button (if present)
                    for done_sel in ('ytcp-button:has-text("Done")',
                                     'button:has-text("Done")'):
                        try:
                            btn = page.query_selector(done_sel)
                            if btn and btn.is_visible() and btn.is_enabled():
                                btn.click(force=True)
                                page.wait_for_timeout(1500)
                                log.info("Clicked 'Done' on ads card")
                                break
                        except Exception:
                            continue
            except Exception as e:
                log.info(f"New-UI ads radio flow failed: {e}")

            # Step 1b (LEGACY UI): old toggle-based monetization switch.
            if not ads_on_done:
                toggle_selectors = [
                    '#monetize-with-ads',
                    'tp-yt-paper-toggle-button',
                    'div[id*="monetize"]',
                    '#onoff-toggle',
                    'ytcp-toggle-button',
                ]
                for sel in toggle_selectors:
                    try:
                        toggle = page.query_selector(sel)
                        if toggle and toggle.is_visible():
                            # Check if it's already ON
                            aria = toggle.get_attribute("aria-pressed") or toggle.get_attribute("checked") or ""
                            classes = toggle.get_attribute("class") or ""
                            if aria == "true" or "checked" in classes or "selected" in classes:
                                log.info(f"Monetization toggle already ON ({sel})")
                            else:
                                toggle.click(force=True)
                                log.info(f"Turned ON monetization toggle: {sel}")
                                page.wait_for_timeout(2000)
                            break
                    except Exception as e:
                        log.info(f"Toggle selector {sel} failed: {e}")

            page.screenshot(path=str(debug_dir / "debug_yt_monetization_02_toggle.png"))

            # Step 2: Click ALL "None of the above" options (one per category)
            # YouTube self-certification has multiple sections (drugs, violence, etc.)
            none_selectors = [
                'tp-yt-paper-radio-button:has-text("None of the above")',
                'label:has-text("None of the above")',
                'div[role="radio"]:has-text("None of the above")',
                ':text("None of the above")',
            ]

            total_clicked = 0
            for selector in none_selectors:
                try:
                    elements = page.query_selector_all(selector)
                    for el in elements:
                        if el.is_visible():
                            el.click(force=True)
                            total_clicked += 1
                            page.wait_for_timeout(300)
                except Exception:
                    continue

            log.info(f"Clicked 'None of the above' {total_clicked} time(s)")

            if total_clicked == 0 and not ads_on_done:
                page.screenshot(path=str(debug_dir / "debug_yt_monetization_no_none.png"))
                # Dump all radio buttons / checkboxes for debugging
                radios = page.evaluate("""() => {
                    return [...document.querySelectorAll('[role="radio"], [role="checkbox"], tp-yt-paper-radio-button, label')]
                        .filter(e => e.offsetParent !== null)
                        .map(e => e.textContent.trim().substring(0, 60))
                        .slice(0, 30);
                }""")
                log.warning(f"No 'None of the above' found. Visible radios/labels: {radios}")
                # Check if already certified
                if "self-certification" not in page_text.lower():
                    log.info("Self-certification section not visible — may already be done")
                    return True
                return False

            page.wait_for_timeout(1000)
            page.screenshot(path=str(debug_dir / "debug_yt_monetization_03_selected.png"))

            # Step 3: Click Submit / Save button
            submit_selectors = [
                'ytcp-button:has-text("Submit rating")',
                'button:has-text("Submit rating")',
                'ytcp-button:has-text("Submit")',
                'button:has-text("Submit")',
                '#submit-button',
                'ytcp-button:has-text("Save")',
                'button:has-text("Save")',
            ]

            submitted = False
            for selector in submit_selectors:
                try:
                    btn = page.wait_for_selector(selector, timeout=5_000)
                    if btn and btn.is_visible() and btn.is_enabled():
                        btn.click(force=True)
                        submitted = True
                        log.info(f"Clicked Submit using: {selector}")
                        break
                except PlaywrightTimeout:
                    continue

            if not submitted:
                page.screenshot(path=str(debug_dir / "debug_yt_monetization_no_submit.png"))
                buttons = page.evaluate("""() => {
                    return [...document.querySelectorAll('button, ytcp-button, tp-yt-paper-button')]
                        .filter(b => b.offsetParent !== null)
                        .map(b => b.textContent.trim().substring(0, 50))
                        .slice(0, 20);
                }""")
                log.warning(f"Could not find Submit button. Visible buttons: {buttons}")
                # In the new UI, a disabled/absent Save just means nothing
                # changed (ads were already ON) — that's success, not failure.
                if ads_on_done:
                    log.info("Ads ON confirmed; Save not needed (no pending changes)")
                    return True
                return False

            # Wait for save to complete
            page.wait_for_timeout(5000)
            page.screenshot(path=str(debug_dir / "debug_yt_monetization_04_done.png"))

            # VERIFY — reload the monetization page and confirm the "On" radio
            # is actually checked. Videos were silently left "Ads off" when the
            # click flow reported success without taking effect; never trust
            # the clicks, only the resulting state.
            verified = None
            try:
                page.goto(studio_url, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(6000)
                for r in page.query_selector_all(
                    'tp-yt-paper-radio-button, ytcp-radio-button, [role="radio"]'
                ):
                    try:
                        if (r.inner_text() or "").strip().lower() == "on":
                            verified = (r.get_attribute("aria-checked") == "true"
                                        or r.get_attribute("checked") == "true")
                            break
                    except Exception:
                        continue
            except Exception as e:
                log.warning(f"Monetization verify step errored: {e}")
            page.screenshot(path=str(debug_dir / "debug_yt_monetization_05_verify.png"))

            # Save updated cookies
            save_cookies(context, YOUTUBE_COOKIE_FILE)

            if verified is False:
                log.error("Monetization VERIFY FAILED — ads are still OFF for this "
                          "video. See output/debug_yt_monetization_*.png")
                return False
            if verified is None:
                log.warning("Monetization state could not be verified (no On radio "
                            "found on reload) — check Studio manually")
            else:
                log.info("Monetization VERIFIED: ads are ON")
            return True

        except Exception as e:
            log.error(f"YouTube self-certification failed: {e}")
            try:
                page.screenshot(path=str(debug_dir / "debug_yt_monetization_error.png"))
            except Exception:
                pass
            return False
        finally:
            browser.close()


def _apply_end_screen(video_id: str) -> bool:
    """Apply a Subscribe + Best-for-viewer end-screen template via YouTube Studio.

    The YouTube Data API does not support end-screen elements, so this drives
    the Studio web UI with Playwright. Tries the new editor first, then the
    legacy end-screen page. Best-effort — returns False on UI mismatch and
    logs a screenshot so we can adjust selectors when Studio changes.
    """
    editor_urls = [
        f"https://studio.youtube.com/video/{video_id}/edit/endscreen",
        f"https://studio.youtube.com/video/{video_id}/endscreen",
        f"https://studio.youtube.com/video/{video_id}/end-screen",
    ]
    debug_dir = OUTPUT_DIR

    log.info(f"Opening YouTube Studio end-screen editor for {video_id}...")

    with sync_playwright() as p:
        browser, context = get_browser_context(p, YOUTUBE_COOKIE_FILE)
        page = context.new_page()
        try:
            loaded = False
            for url in editor_urls:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                    page.wait_for_timeout(6000)
                    if "accounts.google.com" not in page.url and "endscreen" in page.url.lower().replace("-", ""):
                        loaded = True
                        log.info(f"End-screen editor loaded at {page.url}")
                        break
                except Exception as e:
                    log.info(f"Endscreen URL '{url}' failed: {e}")
                    continue

            if not loaded:
                log.warning("Could not open end-screen editor")
                try:
                    page.screenshot(path=str(debug_dir / "debug_yt_endscreen_no_load.png"))
                except Exception:
                    pass
                return False

            if "accounts.google.com" in page.url:
                log.warning("End-screen: not logged into Studio (cookies expired)")
                return False

            page.screenshot(path=str(debug_dir / "debug_yt_endscreen_01_loaded.png"))

            # Strategy 1: "Apply template" — pick the template that adds
            # Subscribe + Best-for-viewer. The Studio UI shows several
            # template thumbnails; pick the one with 2 elements.
            template_clicked = False
            for sel in [
                "button:has-text('Apply template')",
                "ytcp-button:has-text('Apply template')",
                "tp-yt-paper-button:has-text('Apply template')",
                "button[aria-label*='template' i]",
            ]:
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=2000):
                        el.click()
                        log.info(f"Clicked Apply template via: {sel}")
                        template_clicked = True
                        page.wait_for_timeout(2500)
                        break
                except Exception:
                    continue

            if template_clicked:
                # Pick the first template that mentions "subscribe" and "video"
                # or just the 2nd thumbnail (which is usually 1 video + subscribe).
                for sel in [
                    "div[role='option']:has-text('1 video, 1 subscribe')",
                    "div[role='option']:has-text('Video + subscribe')",
                    "[role='option']:nth-of-type(2)",
                    "ytcp-end-screen-template-picker [role='option']:nth-of-type(2)",
                ]:
                    try:
                        el = page.locator(sel).first
                        if el.is_visible(timeout=2000):
                            el.click()
                            log.info(f"Selected end-screen template via: {sel}")
                            page.wait_for_timeout(2000)
                            break
                    except Exception:
                        continue

            # Strategy 2: add elements manually if no template flow.
            if not template_clicked:
                log.info("No 'Apply template' button found — adding elements manually")
                for label in ["Subscribe", "Video"]:
                    add_clicked = False
                    for sel in [
                        f"button:has-text('Add element')",
                        f"ytcp-button:has-text('Add element')",
                    ]:
                        try:
                            el = page.locator(sel).first
                            if el.is_visible(timeout=2000):
                                el.click()
                                page.wait_for_timeout(1500)
                                add_clicked = True
                                break
                        except Exception:
                            continue
                    if not add_clicked:
                        log.warning("'Add element' button not visible")
                        break
                    for sel in [
                        f"[role='menuitem']:has-text('{label}')",
                        f"div:has-text('{label}'):not(:has(*))",
                    ]:
                        try:
                            el = page.locator(sel).first
                            if el.is_visible(timeout=2000):
                                el.click()
                                log.info(f"Added end-screen element: {label}")
                                page.wait_for_timeout(2000)
                                break
                        except Exception:
                            continue
                    # For the Video element, pick "Best for viewer"
                    if label == "Video":
                        for sel in [
                            "div:has-text('Best for viewer')",
                            "[role='option']:has-text('Best for viewer')",
                        ]:
                            try:
                                el = page.locator(sel).first
                                if el.is_visible(timeout=2000):
                                    el.click()
                                    page.wait_for_timeout(1500)
                                    break
                            except Exception:
                                continue

            page.screenshot(path=str(debug_dir / "debug_yt_endscreen_02_elements.png"))

            # Click Save
            saved = False
            for sel in [
                "button:has-text('Save')",
                "ytcp-button:has-text('Save')",
                "tp-yt-paper-button:has-text('Save')",
                "button[aria-label*='Save' i]",
            ]:
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=3000):
                        el.click()
                        log.info(f"Clicked Save via: {sel}")
                        saved = True
                        page.wait_for_timeout(4000)
                        break
                except Exception:
                    continue

            page.screenshot(path=str(debug_dir / "debug_yt_endscreen_03_saved.png"))

            if saved:
                log.info("End-screen elements saved")
                return True
            log.warning("End-screen Save button not clicked — elements may not persist")
            return False
        except Exception as e:
            log.warning(f"End-screen application failed: {e}")
            try:
                page.screenshot(path=str(debug_dir / "debug_yt_endscreen_error.png"))
            except Exception:
                pass
            return False
        finally:
            try:
                browser.close()
            except Exception:
                pass


LOCALIZATION_TEMPLATES = {
    "es": {
        "title_prefix": "",
        "title_suffix": " | Música",
        "desc": "Mezcla profunda de {genre} con ritmos tribales y energía ritual. "
                "Perfecta para entrenamientos, conducir, estudiar o relajarse. "
                "¡Suscríbete para más mezclas diarias! 🔥",
    },
    "pt": {
        "title_prefix": "",
        "title_suffix": " | Música",
        "desc": "Mix profundo de {genre} com batidas tribais e energia ritual. "
                "Perfeito para treinos, dirigir, estudar ou relaxar. "
                "Inscreva-se para mais mixes diários! 🔥",
    },
    "fr": {
        "title_prefix": "",
        "title_suffix": " | Musique",
        "desc": "Mix profond de {genre} avec des rythmes tribaux et une énergie rituelle. "
                "Parfait pour l'entraînement, la conduite, les études ou la détente. "
                "Abonnez-vous pour des mix quotidiens ! 🔥",
    },
    "de": {
        "title_prefix": "",
        "title_suffix": " | Musik",
        "desc": "Tiefer {genre} Mix mit Tribal-Beats und ritueller Energie. "
                "Perfekt für Training, Autofahren, Lernen oder Entspannung. "
                "Abonnieren für tägliche Mixes! 🔥",
    },
    "hi": {
        "title_prefix": "",
        "title_suffix": " | संगीत",
        "desc": "गहरे {genre} मिक्स जनजातीय ताल और अनुष्ठान ऊर्जा के साथ। "
                "वर्कआउट, ड्राइविंग, पढ़ाई या आराम के लिए बिल्कुल सही। "
                "रोज़ाना मिक्स के लिए सब्सक्राइब करें! 🔥",
    },
    "ja": {
        "title_prefix": "",
        "title_suffix": " | 音楽",
        "desc": "トライバルビートとリチュアルエネルギーのディープ{genre}ミックス。"
                "ワークアウト、ドライブ、勉強、リラックスに最適。"
                "毎日のミックスをお届け！チャンネル登録してね！🔥",
    },
    "ko": {
        "title_prefix": "",
        "title_suffix": " | 음악",
        "desc": "트라이벌 비트와 의식 에너지가 담긴 딥 {genre} 믹스. "
                "운동, 드라이브, 공부, 휴식에 완벽합니다. "
                "매일 새로운 믹스를 구독하세요! 🔥",
    },
    "ar": {
        "title_prefix": "",
        "title_suffix": " | موسيقى",
        "desc": "مزيج عميق من {genre} مع إيقاعات قبلية وطاقة روحانية. "
                "مثالي للتمارين والقيادة والدراسة أو الاسترخاء. "
                "اشترك للحصول على مزيج يومي! 🔥",
    },
}


def _set_localizations(youtube, video_id: str, title: str, description: str, concept):
    """Add multi-language titles and descriptions to a video.

    YouTube shows the localized version to users based on their language settings.
    Massive reach expansion with zero extra effort.
    """
    genre = concept.genre or "Afro House"
    localizations = {}
    for lang, tmpl in LOCALIZATION_TEMPLATES.items():
        loc_title = f"{title}{tmpl['title_suffix']}"[:100]
        loc_desc = tmpl["desc"].format(genre=genre)
        loc_desc = f"{loc_desc}\n\n{description}"[:5000]
        localizations[lang] = {
            "title": loc_title,
            "description": loc_desc,
        }

    try:
        youtube.videos().update(
            part="localizations",
            body={
                "id": video_id,
                "localizations": localizations,
            },
        ).execute()
        log.info(f"Set localizations for {len(localizations)} languages: {', '.join(localizations.keys())}")
    except Exception as e:
        log.warning(f"Localization failed (non-fatal): {e}")


def upload_to_youtube(
    video_path: Path,
    thumbnail_path: Path,
    concept: MusicConcept,
    extra_playlists: list[str] | None = None,
    profile_data: dict | None = None,
) -> str | None:
    """Upload video to YouTube using the official API.

    Args:
        extra_playlists: Additional playlist names to add the video to
            (besides the genre-based main playlist).
        profile_data: Playlist profile dict with extra_tags, description_intro,
            title_suffixes for enriching the upload metadata.

    Returns the YouTube video URL or None on failure.
    """
    log.info(f"Uploading to YouTube via API: {concept.youtube_title}")

    try:
        youtube = _get_authenticated_service()
    except FileNotFoundError as e:
        log.error(str(e))
        return None

    import re

    # Build tags for video metadata
    # YouTube API rules: only letters, digits, spaces, hyphens allowed;
    # no < > # or special chars; individual tag max 100 chars; total ≤ 500 chars
    # Merge profile extra_tags with AI-generated tags
    profile = profile_data or {}
    all_raw_tags = list(concept.youtube_tags[:30])
    for pt in profile.get("extra_tags", []):
        if pt not in all_raw_tags:
            all_raw_tags.append(pt)

    log.info(f"Raw tags before sanitization ({len(all_raw_tags)}): {all_raw_tags}")
    tags = []
    total_chars = 0
    for t in all_raw_tags:
        if not isinstance(t, str):
            continue
        # Strip everything except letters, digits, spaces, hyphens, and apostrophes
        t = re.sub(r'[^a-zA-Z0-9\s\-\']', '', t).strip()
        if not t or len(t) > 100:
            continue
        # YouTube counts commas between tags; each tag costs len(tag)+1 (except last)
        cost = len(t) + (1 if tags else 0)
        if total_chars + cost > 500:
            break
        tags.append(t)
        total_chars += cost
    log.info(f"Sanitized tags ({len(tags)}, {total_chars} chars): {tags}")

    # Add profile title suffix (e.g. "| Gym Workout Mix", "| Night Drive Mix")
    title = concept.youtube_title
    suffixes = profile.get("title_suffixes", [])
    if suffixes:
        import random
        suffix = random.choice(suffixes)
        if len(title) + len(suffix) + 1 <= 100:
            title = f"{title} {suffix}"

    # Clean any existing hashtags from end of AI description to avoid duplication
    clean_desc = re.sub(r'(\s*#\w+)+\s*$', '', concept.youtube_description).rstrip()

    # Prepend profile description_intro if available
    desc_intro = profile.get("description_intro", "")
    if desc_intro:
        clean_desc = f"{desc_intro}\n\n{clean_desc}"

    # The description body starts with the HOOK line, not hashtags — YouTube
    # surfaces the first 3 hashtags above the title no matter where they sit
    # in the description, so they go at the very END (appended below).
    description = clean_desc

    # Playlist autoplay trap — link to playlist instead of single video
    # Viewers click → playlist starts → autoplay → massive watch time
    genre_playlist = concept.genre or "Afro House"
    try:
        pl_id = _find_or_create_playlist(youtube, genre_playlist)
        playlist_url = f"https://www.youtube.com/playlist?list={pl_id}"
        description += f"\n\n🎧 Full Playlist (Autoplay): {playlist_url}"
    except Exception:
        pass

    # Extra playlist link if available
    extra_pl_names = profile.get("youtube_playlists", [])[1:]
    for pl_name in extra_pl_names[:1]:
        try:
            epl_id = _find_or_create_playlist(youtube, pl_name)
            epl_url = f"https://www.youtube.com/playlist?list={epl_id}"
            description += f"\n🔥 {pl_name} Playlist: {epl_url}"
        except Exception:
            pass

    # Append artist links (Spotify + Beatport) so viewers can find the paid releases.
    artist_links = []
    if SPOTIFY_ARTIST_URL:
        artist_links.append(f"Spotify: {SPOTIFY_ARTIST_URL}")
    if BEATPORT_ARTIST_URL:
        artist_links.append(f"Beatport: {BEATPORT_ARTIST_URL}")
    if artist_links:
        description = description.rstrip() + "\n\n" + "\n".join(artist_links)

    # NO raw keyword list here — that's keyword stuffing (against YouTube's
    # spam policy) and the keywords already live in the video tags. The
    # description ends with exactly 3 hashtags: YouTube lifts the first 3
    # hashtags from anywhere in the description and shows them above the
    # title, so the hook keeps the first line and the tags close the text.
    genre_tag = (concept.genre or "Afro House").lower().replace(" ", "")
    description = description.rstrip() + f"\n\n#{genre_tag} #deephouse #tribalhouse"

    # Premiere mode: upload as private with publishAt 30 min from now.
    # YouTube shows countdown + sends subscriber notifications + live chat.
    # After publishAt time, video auto-switches to public.
    from datetime import datetime, timezone, timedelta
    premiere_time = datetime.now(timezone.utc) + timedelta(minutes=30)
    publish_at = premiere_time.strftime("%Y-%m-%dT%H:%M:%S.0Z")

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags,
            "categoryId": "10",
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": publish_at,
            "selfDeclaredMadeForKids": False,
            "embeddable": True,
            "license": "youtube",
            "publicStatsViewable": True,
        },
    }

    log.info("Uploading video file...")

    def _execute_upload(upload_body):
        media = MediaFileUpload(
            str(video_path),
            mimetype="video/mp4",
            resumable=True,
            chunksize=10 * 1024 * 1024,  # 10MB chunks
        )
        req = youtube.videos().insert(
            part="snippet,status",
            body=upload_body,
            media_body=media,
        )
        resp = None
        while resp is None:
            st, resp = req.next_chunk()
            if st:
                progress = int(st.progress() * 100)
                log.info(f"Upload progress: {progress}%")
        return resp

    try:
        response = _execute_upload(body)
    except Exception as e:
        if "invalidTags" in str(e):
            original_tags = body["snippet"].get("tags", [])
            log.warning(f"YouTube rejected {len(original_tags)} tags: {e}")
            # Try with only the first 5 most important tags
            if len(original_tags) > 5:
                body["snippet"]["tags"] = original_tags[:5]
                log.info(f"Retrying with {len(body['snippet']['tags'])} tags: {body['snippet']['tags']}")
                try:
                    response = _execute_upload(body)
                except Exception as e2:
                    if "invalidTags" in str(e2):
                        log.warning(f"Still rejected, uploading without any tags")
                        body["snippet"].pop("tags", None)
                        response = _execute_upload(body)
                    else:
                        raise
            else:
                log.warning("Uploading without any tags")
                body["snippet"].pop("tags", None)
                response = _execute_upload(body)
        else:
            raise

    video_id = response["id"]
    video_url = f"https://youtu.be/{video_id}"
    log.info(f"Video uploaded: {video_url}")

    # Multi-language titles + descriptions for global reach
    # YouTube shows the localized version to users in those countries
    _set_localizations(youtube, video_id, title, description, concept)

    # Upload custom thumbnail
    try:
        log.info("Uploading custom thumbnail...")
        # Detect mimetype from file extension
        suffix = thumbnail_path.suffix.lower()
        mimetype = "image/jpeg" if suffix in (".jpg", ".jpeg") else "image/png"
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(str(thumbnail_path), mimetype=mimetype),
        ).execute()
        log.info("Thumbnail uploaded successfully")
    except Exception as e:
        log.warning(f"Thumbnail upload failed (may need verified account): {e}")

    # Add to genre playlist (e.g. "Afro House")
    try:
        genre_playlist = concept.genre or "Afro House"
        playlist_id = _find_or_create_playlist(youtube, genre_playlist)
        _add_to_playlist(youtube, playlist_id, video_id)
        log.info(f"Added to '{genre_playlist}' playlist")
    except Exception as e:
        log.warning(f"Playlist add failed: {e}")

    # Add to extra playlists (e.g. "Gym Workout Mix", "Driving Music")
    for pl_name in (extra_playlists or []):
        try:
            pl_id = _find_or_create_playlist(youtube, pl_name)
            _add_to_playlist(youtube, pl_id, video_id)
            log.info(f"Added to '{pl_name}' playlist")
        except Exception as e:
            log.warning(f"Extra playlist '{pl_name}' add failed: {e}")

    # Apply end-screen (Subscribe + Best for viewer) — boosts session time
    try:
        _apply_end_screen(video_id)
    except Exception as e:
        log.warning(f"End-screen apply failed: {e}")

    # Complete self-certification for monetization
    try:
        certified = _complete_self_certification(video_id)
        if not certified:
            log.warning("Self-certification incomplete — check YouTube Studio manually")
    except Exception as e:
        log.warning(f"Self-certification failed (non-fatal): {e}")

    log.info(f"Premiere scheduled at {publish_at} — YouTube will notify subscribers")

    return video_url


def upload_short_to_youtube(
    video_path: Path,
    title: str,
    description: str,
    concept: MusicConcept,
    publish_at: str | None = None,
) -> str | None:
    """Upload a YouTube Short (vertical, under 60s).

    Shorts are regular YouTube uploads — YouTube auto-detects them as Shorts
    based on vertical format (9:16) and duration under 60 seconds.
    When publish_at is set, the Short is uploaded as private and auto-publishes
    at the given ISO 8601 timestamp.
    """
    log.info(f"Uploading YouTube Short: {title}")

    try:
        youtube = _get_authenticated_service()
    except FileNotFoundError as e:
        log.error(str(e))
        return None

    import re
    genre_tag = concept.genre.lower().replace(" ", "")
    tags = [
        f"{genre_tag}", "shorts", "afrohouse", "deephouse",
        "tribalhouse", "music", "newmusic",
    ]

    status = {
        "selfDeclaredMadeForKids": False,
        "embeddable": True,
    }
    if publish_at:
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at
    else:
        status["privacyStatus"] = "public"

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags,
            "categoryId": "10",
            "defaultLanguage": "en",
        },
        "status": status,
    }

    from googleapiclient.http import MediaFileUpload
    media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        _, response = request.next_chunk()

    video_id = response["id"]
    short_url = f"https://youtube.com/shorts/{video_id}"
    log.info(f"Short uploaded: {short_url}")
    return short_url
