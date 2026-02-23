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

from modules.concept_generator import MusicConcept
from config import BASE_DIR, OUTPUT_DIR
from utils.logger import log

# OAuth2 scopes needed for YouTube upload
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

# Paths for OAuth credentials
CLIENT_SECRETS_FILE = BASE_DIR / "client_secrets.json"
TOKEN_FILE = BASE_DIR / "youtube_token.pickle"


def _get_authenticated_service():
    """Get an authenticated YouTube API service using OAuth2."""
    credentials = None

    # Load saved token if it exists
    if TOKEN_FILE.exists():
        with open(TOKEN_FILE, "rb") as f:
            credentials = pickle.load(f)

    # If no valid credentials, do the OAuth flow
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            log.info("Refreshing expired YouTube token...")
            credentials.refresh(Request())
        else:
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


def upload_to_youtube(
    video_path: Path,
    thumbnail_path: Path,
    concept: MusicConcept,
) -> str | None:
    """Upload video to YouTube using the official API.

    Returns the YouTube video URL or None on failure.
    """
    log.info(f"Uploading to YouTube via API: {concept.youtube_title}")

    try:
        youtube = _get_authenticated_service()
    except FileNotFoundError as e:
        log.error(str(e))
        return None

    # Build tags string
    tags = concept.youtube_tags[:30]  # YouTube allows max 30 tags
    hashtags_line = " ".join("#" + h.replace(" ", "") for h in concept.hashtags)

    # Full description with hashtags
    description = f"{concept.youtube_description}\n\n{hashtags_line}"

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
        },
    }

    log.info("Uploading video file...")
    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=10 * 1024 * 1024,  # 10MB chunks
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    # Execute upload with progress
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            progress = int(status.progress() * 100)
            log.info(f"Upload progress: {progress}%")

    video_id = response["id"]
    video_url = f"https://youtu.be/{video_id}"
    log.info(f"Video uploaded: {video_url}")

    # Upload custom thumbnail
    try:
        log.info("Uploading custom thumbnail...")
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(str(thumbnail_path), mimetype="image/png"),
        ).execute()
        log.info("Thumbnail uploaded successfully")
    except Exception as e:
        log.warning(f"Thumbnail upload failed (may need verified account): {e}")

    return video_url
