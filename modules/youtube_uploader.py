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
SCOPES = ["https://www.googleapis.com/auth/youtube"]

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

        # Check if saved token has the required scopes
        saved_scopes = getattr(credentials, "scopes", None) or set()
        if credentials.valid and not set(SCOPES).issubset(saved_scopes):
            log.warning(f"Token scopes mismatch. Have: {saved_scopes}, need: {SCOPES}")
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

            # Step 1: Turn ON monetization if there's a toggle
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

            if total_clicked == 0:
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
                return False

            # Wait for save to complete
            page.wait_for_timeout(5000)
            page.screenshot(path=str(debug_dir / "debug_yt_monetization_04_done.png"))

            # Save updated cookies
            save_cookies(context, YOUTUBE_COOKIE_FILE)

            log.info("YouTube self-certification completed successfully")
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


def upload_to_youtube(
    video_path: Path,
    thumbnail_path: Path,
    concept: MusicConcept,
    extra_playlists: list[str] | None = None,
) -> str | None:
    """Upload video to YouTube using the official API.

    Args:
        extra_playlists: Additional playlist names to add the video to
            (besides the genre-based main playlist).

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
    raw_tags = concept.youtube_tags[:30]
    log.info(f"Raw tags before sanitization ({len(raw_tags)}): {raw_tags}")
    tags = []
    total_chars = 0
    for t in raw_tags:
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

    # Clean any existing hashtags from end of AI description to avoid duplication
    clean_desc = re.sub(r'(\s*#\w+)+\s*$', '', concept.youtube_description).rstrip()

    # Append exactly 3 hashtags at end (YouTube shows the FIRST 3 hashtags above the title)
    # These are prime real estate — use the most searched, clickable hashtags
    # Place them at the TOP of the description so they display above the video title
    genre_tag = concept.genre.lower().replace(" ", "")
    description = f"#{genre_tag} #deephouse #tribalhouse\n\n{clean_desc}"

    # Append artist links (Spotify + Beatport) so viewers can find the paid releases.
    artist_links = []
    if SPOTIFY_ARTIST_URL:
        artist_links.append(f"Spotify: {SPOTIFY_ARTIST_URL}")
    if BEATPORT_ARTIST_URL:
        artist_links.append(f"Beatport: {BEATPORT_ARTIST_URL}")
    if artist_links:
        description = description.rstrip() + "\n\n" + "\n".join(artist_links)

    # Upload the video
    body = {
        "snippet": {
            "title": concept.youtube_title[:100],  # Max 100 chars
            "description": description[:5000],  # Max 5000 chars
            "tags": tags,
            "categoryId": "10",  # Music category
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus": "public",
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

    # Complete self-certification for monetization
    try:
        certified = _complete_self_certification(video_id)
        if not certified:
            log.warning("Self-certification incomplete — check YouTube Studio manually")
    except Exception as e:
        log.warning(f"Self-certification failed (non-fatal): {e}")

    return video_url
