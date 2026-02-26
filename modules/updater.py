"""
LUTH Auto-Updater
Checks GitHub for new versions in two ways:
  1. GitHub Releases (formal versioned releases)
  2. Latest commit on main branch (any push triggers update)

Downloads the source zipball and applies the update in-place.
"""

import io
import os
import re
import sys
import shutil
import zipfile
import tempfile
import subprocess
import requests
from pathlib import Path
from packaging import version as pkg_version

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
GITHUB_REPO = "imperialmediaweb-bit/music"
GITHUB_API_RELEASES = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_DEFAULT_BRANCH = "claude/luth-software-sS5KD"
GITHUB_API_COMMITS = f"https://api.github.com/repos/{GITHUB_REPO}/commits/{GITHUB_DEFAULT_BRANCH}"
GITHUB_ZIPBALL = f"https://api.github.com/repos/{GITHUB_REPO}/zipball/{GITHUB_DEFAULT_BRANCH}"

# Files and folders that must NEVER be overwritten during an update
PRESERVE = {
    ".env",
    "cookies",
    "output",
    "input",
    "venv",
    ".venv",
    "bin",
    "__pycache__",
    "client_secrets.json",
    "youtube_token.pickle",
    "pipeline.log",
    ".git",
}

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent

# File that stores the last applied commit SHA (for commit-based updates)
_COMMIT_FILE = BASE_DIR / ".last_commit"


def _get_current_commit() -> str | None:
    """Get the current git commit SHA (from git or saved file)."""
    # Try git first
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=str(BASE_DIR),
        )
        if result.returncode == 0:
            return result.stdout.strip()[:12]
    except Exception:
        pass

    # Fall back to saved commit file
    if _COMMIT_FILE.exists():
        return _COMMIT_FILE.read_text().strip()[:12]

    return None


def _save_commit(sha: str):
    """Save the applied commit SHA."""
    try:
        _COMMIT_FILE.write_text(sha[:12])
    except Exception:
        pass


def check_for_update(current_version: str):
    """Check GitHub for a newer version.

    Checks in two ways:
      1. GitHub Releases — formal versioned releases (v2.1.0, etc.)
      2. Latest commit on main — any code push (if no release found)

    Returns:
        (has_update, latest_info, download_url) or (False, current_version, None)
    """
    headers = {"Accept": "application/vnd.github+json"}

    # --- Method 1: Check formal releases ---
    try:
        resp = requests.get(GITHUB_API_RELEASES, timeout=10, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            tag = data.get("tag_name", "")
            latest = re.sub(r"^v", "", tag)

            if latest and pkg_version.parse(latest) > pkg_version.parse(current_version):
                download_url = None

                # For frozen apps, prefer a pre-built release asset (.zip)
                if getattr(sys, "frozen", False):
                    for asset in data.get("assets", []):
                        name = asset.get("name", "").lower()
                        if name.endswith(".zip"):
                            download_url = asset.get("browser_download_url")
                            break

                # Fallback to source zipball
                if not download_url:
                    download_url = data.get("zipball_url", "")

                return True, f"v{latest}", download_url
    except Exception:
        pass

    # --- Method 2: Check latest commit on main branch ---
    try:
        resp = requests.get(GITHUB_API_COMMITS, timeout=10, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            remote_sha = data.get("sha", "")[:12]
            local_sha = _get_current_commit()

            if remote_sha and remote_sha != local_sha:
                # There are new commits — offer update
                commit_msg = data.get("commit", {}).get("message", "").split("\n")[0][:60]
                return True, f"new: {commit_msg}", GITHUB_ZIPBALL

    except Exception:
        pass

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

            # Extract the commit SHA from the folder name (user-repo-SHA/)
            folder_name = prefix.rstrip("/")
            parts = folder_name.rsplit("-", 1)
            commit_sha = parts[-1] if len(parts) > 1 else ""

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

                # Save the commit SHA so we know what version we're at
                if commit_sha:
                    _save_commit(commit_sha)

                # Install any new dependencies from updated requirements.txt
                req_file = BASE_DIR / "requirements.txt"
                if req_file.exists() and not getattr(sys, "frozen", False):
                    log("Installing updated dependencies...")
                    try:
                        subprocess.run(
                            [sys.executable, "-m", "pip", "install", "-r", str(req_file)],
                            capture_output=True, text=True, timeout=300,
                        )
                        log("Dependencies updated!")
                    except Exception:
                        log("Could not auto-install dependencies — run install.bat")

                return True

            finally:
                # Clean up temp directory
                shutil.rmtree(tmp_dir, ignore_errors=True)

    except Exception as e:
        log(f"Update failed: {e}")
        return False
