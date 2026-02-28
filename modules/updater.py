"""
LUTH Auto-Updater
Checks GitHub for new versions in two ways:
  1. GitHub Releases (formal versioned releases + latest pre-release)
  2. Latest commit on main branch (any push triggers update)

For frozen (EXE) apps: downloads pre-built ZIP and applies via restart.
For source installs: downloads source zipball and overwrites .py files.
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
GITHUB_API_RELEASES = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
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
      1. GitHub Releases — formal releases + "latest" pre-release builds
      2. Latest commit on branch — any code push (source installs only)

    Returns:
        (has_update, latest_info, download_url) or (False, current_version, None)
    """
    headers = {"Accept": "application/vnd.github+json"}
    is_frozen = getattr(sys, "frozen", False)

    # --- Method 1: Check releases (including pre-releases for EXE builds) ---
    try:
        # Get all releases (including pre-releases)
        resp = requests.get(GITHUB_API_RELEASES, timeout=10, headers=headers,
                            params={"per_page": 5})
        if resp.status_code == 200:
            releases = resp.json()
            for data in releases:
                tag = data.get("tag_name", "")

                # For frozen apps, also accept "latest" pre-release
                if is_frozen and tag == "latest":
                    # Check if we already have this build
                    for asset in data.get("assets", []):
                        name = asset.get("name", "").lower()
                        if name.endswith(".zip"):
                            # Compare the published_at date or asset updated_at
                            asset_updated = asset.get("updated_at", "")
                            last_update = _get_last_release_date()
                            if asset_updated and asset_updated != last_update:
                                download_url = asset.get("browser_download_url")
                                return True, "new build available", download_url
                    continue

                # Formal versioned release
                latest = re.sub(r"^v", "", tag)
                if latest and pkg_version.parse(latest) > pkg_version.parse(current_version):
                    download_url = None

                    # For frozen apps, prefer a pre-built release asset (.zip)
                    if is_frozen:
                        for asset in data.get("assets", []):
                            name = asset.get("name", "").lower()
                            if name.endswith(".zip"):
                                download_url = asset.get("browser_download_url")
                                break

                    # Fallback to source zipball (only useful for non-frozen)
                    if not download_url:
                        if is_frozen:
                            continue  # Skip — no usable asset for EXE
                        download_url = data.get("zipball_url", "")

                    return True, f"v{latest}", download_url
    except Exception:
        pass

    # --- Method 2: Check latest commit (source installs only) ---
    if not is_frozen:
        try:
            resp = requests.get(GITHUB_API_COMMITS, timeout=10, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                remote_sha = data.get("sha", "")[:12]
                local_sha = _get_current_commit()

                if remote_sha and remote_sha != local_sha:
                    commit_msg = data.get("commit", {}).get("message", "").split("\n")[0][:60]
                    return True, f"new: {commit_msg}", GITHUB_ZIPBALL
        except Exception:
            pass

    return False, current_version, None


def _get_last_release_date() -> str:
    """Get the timestamp of the last applied pre-release update."""
    marker = BASE_DIR / ".last_release_date"
    if marker.exists():
        return marker.read_text().strip()
    return ""


def _save_last_release_date(date_str: str):
    """Save the timestamp of the applied pre-release update."""
    try:
        (BASE_DIR / ".last_release_date").write_text(date_str)
    except Exception:
        pass


def download_and_apply_update(download_url: str, progress_callback=None):
    """Download the update and apply it.

    For frozen (EXE) apps:
        Downloads pre-built ZIP, extracts to temp, creates a batch script
        that replaces files after the app exits, then signals restart.

    For source installs:
        Downloads source zipball, overwrites .py files in-place.

    Args:
        download_url: GitHub release asset or zipball URL.
        progress_callback: Optional callable(text) for status updates.

    Returns:
        True on success, False on failure.
    """

    def log(msg):
        if progress_callback:
            progress_callback(msg)

    is_frozen = getattr(sys, "frozen", False)

    try:
        log("Downloading update...")
        resp = requests.get(download_url, timeout=300, stream=True,
                            headers={"Accept": "application/octet-stream"})
        if resp.status_code != 200:
            log(f"Download failed (HTTP {resp.status_code})")
            return False

        data = io.BytesIO(resp.content)
        log("Extracting update...")

        if is_frozen:
            return _apply_frozen_update(data, download_url, log)
        else:
            return _apply_source_update(data, log)

    except Exception as e:
        log(f"Update failed: {e}")
        return False


def _apply_frozen_update(data, download_url, log):
    """Apply update to a frozen (PyInstaller) app via restart batch script."""
    # Extract ZIP to a persistent temp directory
    update_dir = BASE_DIR / "_update_staging"
    if update_dir.exists():
        shutil.rmtree(update_dir, ignore_errors=True)
    update_dir.mkdir(exist_ok=True)

    try:
        with zipfile.ZipFile(data) as zf:
            zf.extractall(update_dir)
        log("Update downloaded! Preparing restart...")
    except Exception as e:
        log(f"Extract failed: {e}")
        shutil.rmtree(update_dir, ignore_errors=True)
        return False

    # Save the release date for future comparison
    try:
        resp_info = requests.get(download_url.rsplit("/", 1)[0],
                                 timeout=10,
                                 headers={"Accept": "application/vnd.github+json"})
        if resp_info.status_code == 200:
            for asset in resp_info.json().get("assets", []):
                if asset.get("browser_download_url") == download_url:
                    _save_last_release_date(asset.get("updated_at", ""))
                    break
    except Exception:
        pass

    # Create batch script that waits for app to exit, copies files, relaunches
    app_exe = Path(sys.executable).resolve()
    app_dir = app_exe.parent
    bat_path = app_dir / "_update.bat"

    bat_content = f'''@echo off
title LUTH Update
echo Waiting for LUTH to close...
:wait
timeout /t 1 /nobreak > nul
tasklist /FI "PID eq %1" 2>NUL | find /I "LUTH" >NUL
if not errorlevel 1 goto wait
echo Applying update...
xcopy /s /y /q "{update_dir}\\*" "{app_dir}\\"
echo Cleaning up...
rmdir /s /q "{update_dir}"
echo Starting LUTH...
start "" "{app_exe}"
del "%~f0"
'''
    try:
        bat_path.write_text(bat_content, encoding="utf-8")
    except Exception as e:
        log(f"Could not create update script: {e}")
        shutil.rmtree(update_dir, ignore_errors=True)
        return False

    # Launch the batch script (passing current PID so it waits for us)
    try:
        subprocess.Popen(
            ["cmd", "/c", str(bat_path), str(os.getpid())],
            creationflags=0x00000008,  # DETACHED_PROCESS
        )
    except Exception as e:
        log(f"Could not launch update script: {e}")
        shutil.rmtree(update_dir, ignore_errors=True)
        bat_path.unlink(missing_ok=True)
        return False

    log("Restarting to apply update...")
    return True  # Caller should exit the app


def _apply_source_update(data, log):
    """Apply update to a source (non-frozen) install by overwriting .py files."""
    with zipfile.ZipFile(data) as zf:
        # GitHub zipball has a top-level folder like "user-repo-abc1234/"
        members = zf.namelist()
        if not members:
            log("Empty archive — update aborted.")
            return False

        prefix = members[0].split("/")[0] + "/"

        # Extract commit SHA from folder name
        folder_name = prefix.rstrip("/")
        parts = folder_name.rsplit("-", 1)
        commit_sha = parts[-1] if len(parts) > 1 else ""

        tmp_dir = Path(tempfile.mkdtemp(prefix="luth_update_"))

        try:
            zf.extractall(tmp_dir)
            extracted_root = tmp_dir / prefix.rstrip("/")

            if not extracted_root.is_dir():
                extracted_root = tmp_dir

            # Copy new files over existing ones, skipping preserved paths
            updated = 0
            for src_path in extracted_root.rglob("*"):
                rel = src_path.relative_to(extracted_root)

                top_level = str(rel).split(os.sep)[0]
                if top_level in PRESERVE:
                    continue

                dest = BASE_DIR / rel
                if src_path.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy(src_path, dest)
                    updated += 1

            # Clear __pycache__ so Python uses the new .py files
            for cache_dir in BASE_DIR.rglob("__pycache__"):
                shutil.rmtree(cache_dir, ignore_errors=True)

            log(f"Updated {updated} files successfully!")

            if commit_sha:
                _save_commit(commit_sha)

            # Install any new dependencies
            req_file = BASE_DIR / "requirements.txt"
            if req_file.exists():
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
            shutil.rmtree(tmp_dir, ignore_errors=True)
