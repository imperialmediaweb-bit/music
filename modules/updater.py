"""
LUTH Auto-Updater
Checks GitHub Releases for a new version, downloads only the changed source
files, and applies the update in-place — no full reinstall needed.
"""

import io
import os
import re
import sys
import shutil
import zipfile
import tempfile
import requests
from pathlib import Path
from packaging import version as pkg_version

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
GITHUB_REPO = "imperialmediaweb-bit/music"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

# Files and folders that must NEVER be overwritten during an update
PRESERVE = {
    ".env",
    "cookies",
    "output",
    "input",
    "venv",
    ".venv",
    "__pycache__",
    "client_secrets.json",
    "pipeline.log",
    ".git",
}

BASE_DIR = Path(__file__).resolve().parent.parent


def check_for_update(current_version: str):
    """Check GitHub for a newer release.

    Returns:
        (has_update, latest_version, download_url) or (False, current_version, None)
    """
    try:
        resp = requests.get(GITHUB_API, timeout=10, headers={"Accept": "application/vnd.github+json"})
        if resp.status_code != 200:
            return False, current_version, None

        data = resp.json()
        tag = data.get("tag_name", "")
        # Strip leading 'v' from tag (e.g. "v1.1.0" -> "1.1.0")
        latest = re.sub(r"^v", "", tag)
        if not latest:
            return False, current_version, None

        if pkg_version.parse(latest) > pkg_version.parse(current_version):
            # Prefer the zipball URL (source archive)
            download_url = data.get("zipball_url", "")
            return True, latest, download_url

        return False, current_version, None

    except Exception:
        return False, current_version, None


def download_and_apply_update(download_url: str, progress_callback=None):
    """Download the release zip and overwrite source files in-place.

    Preserves user data (.env, cookies, output, input, venv, etc.).

    Args:
        download_url: GitHub zipball URL.
        progress_callback: Optional callable(text) for status updates.

    Returns:
        True on success, False on failure.
    """

    def log(msg):
        if progress_callback:
            progress_callback(msg)

    try:
        log("Downloading update...")
        resp = requests.get(download_url, timeout=120, stream=True)
        if resp.status_code != 200:
            log(f"Download failed (HTTP {resp.status_code})")
            return False

        data = io.BytesIO(resp.content)
        log("Extracting update...")

        with zipfile.ZipFile(data) as zf:
            # GitHub zipball has a top-level folder like "user-repo-abc1234/"
            # We need to strip that prefix.
            members = zf.namelist()
            if not members:
                log("Empty archive — update aborted.")
                return False

            # Find the common prefix (top-level folder)
            prefix = members[0].split("/")[0] + "/"

            # Create a temporary directory for extraction
            tmp_dir = Path(tempfile.mkdtemp(prefix="luth_update_"))

            try:
                zf.extractall(tmp_dir)
                extracted_root = tmp_dir / prefix.rstrip("/")

                if not extracted_root.is_dir():
                    # Fallback: use tmp_dir directly
                    extracted_root = tmp_dir

                # Copy new files over existing ones, skipping preserved paths
                updated = 0
                for src_path in extracted_root.rglob("*"):
                    rel = src_path.relative_to(extracted_root)

                    # Skip preserved files/folders
                    top_level = str(rel).split(os.sep)[0]
                    if top_level in PRESERVE:
                        continue

                    dest = BASE_DIR / rel
                    if src_path.is_dir():
                        dest.mkdir(parents=True, exist_ok=True)
                    else:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src_path, dest)
                        updated += 1

                log(f"Updated {updated} files successfully!")
                return True

            finally:
                # Clean up temp directory
                shutil.rmtree(tmp_dir, ignore_errors=True)

    except Exception as e:
        log(f"Update failed: {e}")
        return False
