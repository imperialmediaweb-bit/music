"""
LUTH Auto-Updater
Checks GitHub for new versions in two ways:
  1. GitHub Releases (formal versioned releases + latest pre-release)
  2. Latest commit on branch (any push triggers lightweight source update)

For frozen (EXE) apps:
  - Full update: downloads pre-built ZIP and applies via restart batch script.
  - Lightweight update: downloads source zipball and patches .py files in _internal/.
For source installs:
  - Downloads source zipball and overwrites .py files.
"""

import io
import os
import re
import sys
import shutil
import zipfile
import tempfile
import subprocess
import logging
import requests
from pathlib import Path
from packaging import version as pkg_version

log = logging.getLogger("updater")

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
      2. Latest commit on branch — lightweight source update (works for both
         frozen and source installs)

    Returns:
        (has_update, latest_info, download_url) or (False, current_version, None)
    """
    headers = {"Accept": "application/vnd.github+json"}
    is_frozen = getattr(sys, "frozen", False)

    # --- Method 1: Check releases (including pre-releases for EXE builds) ---
    try:
        resp = requests.get(GITHUB_API_RELEASES, timeout=10, headers=headers,
                            params={"per_page": 5})
        log.debug(f"Releases API: HTTP {resp.status_code}")
        if resp.status_code == 200:
            releases = resp.json()
            for data in releases:
                tag = data.get("tag_name", "")

                # For frozen apps, also accept "latest" pre-release
                if is_frozen and tag == "latest":
                    for asset in data.get("assets", []):
                        name = asset.get("name", "").lower()
                        if name.endswith(".zip"):
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

                    if is_frozen:
                        for asset in data.get("assets", []):
                            name = asset.get("name", "").lower()
                            if name.endswith(".zip"):
                                download_url = asset.get("browser_download_url")
                                break

                    if not download_url:
                        if is_frozen:
                            continue
                        download_url = data.get("zipball_url", "")

                    return True, f"v{latest}", download_url
        elif resp.status_code in (403, 404):
            log.warning(f"Releases API returned {resp.status_code} — repo may be private")
    except Exception as e:
        log.warning(f"Release check failed: {e}")

    # --- Method 2: Check latest commit (lightweight source update) ---
    # Works for BOTH frozen and source installs
    try:
        resp = requests.get(GITHUB_API_COMMITS, timeout=10, headers=headers)
        log.debug(f"Commits API: HTTP {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            remote_sha = data.get("sha", "")[:12]
            local_sha = _get_current_commit()

            if remote_sha and remote_sha != local_sha:
                commit_msg = data.get("commit", {}).get("message", "").split("\n")[0][:60]
                return True, f"new: {commit_msg}", GITHUB_ZIPBALL
        elif resp.status_code in (403, 404):
            log.warning(f"Commits API returned {resp.status_code} — repo may be private")
    except Exception as e:
        log.warning(f"Commit check failed: {e}")

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


def _download_to_file(url: str, progress_callback=None) -> Path | None:
    """Download URL to a temp file on disk (avoids loading into memory)."""
    def _log(msg):
        if progress_callback:
            progress_callback(msg)

    try:
        resp = requests.get(url, timeout=600, stream=True,
                            headers={"Accept": "application/octet-stream"})
        if resp.status_code != 200:
            _log(f"Download failed (HTTP {resp.status_code})")
            return None

        total = int(resp.headers.get("content-length", 0))
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip", prefix="luth_update_")
        downloaded = 0

        for chunk in resp.iter_content(chunk_size=1024 * 256):
            if chunk:
                tmp.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = int(downloaded * 100 / total)
                    mb = downloaded / (1024 * 1024)
                    _log(f"Downloading... {mb:.1f}MB ({pct}%)")

        tmp.close()
        return Path(tmp.name)

    except Exception as e:
        _log(f"Download error: {e}")
        return None


def download_and_apply_update(download_url: str, progress_callback=None):
    """Download the update and apply it.

    For frozen (EXE) apps:
        If the URL is a release asset (.zip build), uses full replacement via batch script.
        If the URL is a source zipball, patches .py files in _internal/.

    For source installs:
        Downloads source zipball, overwrites .py files in-place.

    Args:
        download_url: GitHub release asset or zipball URL.
        progress_callback: Optional callable(text) for status updates.

    Returns:
        True on success, False on failure.
    """

    def _log(msg):
        if progress_callback:
            progress_callback(msg)

    is_frozen = getattr(sys, "frozen", False)
    is_source_zipball = "/zipball/" in download_url

    try:
        # Download to disk instead of memory
        tmp_file = _download_to_file(download_url, progress_callback)
        if not tmp_file:
            return False

        _log("Extracting update...")

        try:
            if is_frozen and not is_source_zipball:
                # Full EXE replacement from release asset
                with open(tmp_file, "rb") as f:
                    data = io.BytesIO(f.read())
                return _apply_frozen_update(data, download_url, _log)
            elif is_frozen and is_source_zipball:
                # Lightweight: patch .py files in _internal/
                with open(tmp_file, "rb") as f:
                    data = io.BytesIO(f.read())
                return _apply_frozen_source_update(data, _log)
            else:
                # Source install
                with open(tmp_file, "rb") as f:
                    data = io.BytesIO(f.read())
                return _apply_source_update(data, _log)
        finally:
            try:
                tmp_file.unlink()
            except Exception:
                pass

    except Exception as e:
        _log(f"Update failed: {e}")
        log.exception("Update failed")
        return False


def _apply_frozen_source_update(data, log_fn):
    """Lightweight update for frozen apps: patch .py files in _internal/.

    Downloads the source zipball and copies .py files into the _internal/
    directory structure so they override the bundled bytecode.
    """
    with zipfile.ZipFile(data) as zf:
        members = zf.namelist()
        if not members:
            log_fn("Empty archive — update aborted.")
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

            internal_dir = BASE_DIR / "_internal"
            if not internal_dir.is_dir():
                # Fallback: if no _internal, treat like regular source update
                log_fn("No _internal directory found, updating root...")
                internal_dir = BASE_DIR

            # Copy .py files to the right places in _internal/
            updated = 0
            for src_path in extracted_root.rglob("*.py"):
                rel = src_path.relative_to(extracted_root)

                top_level = str(rel).split(os.sep)[0]
                if top_level in PRESERVE:
                    continue

                dest = internal_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_path, dest)
                updated += 1

            # Also copy non-.py config files that matter
            for config_file in ["requirements.txt", ".env.example", "LUTH.spec"]:
                src = extracted_root / config_file
                if src.is_file():
                    shutil.copy2(src, BASE_DIR / config_file)

            # Clear __pycache__ so Python uses the new .py files
            for cache_dir in internal_dir.rglob("__pycache__"):
                shutil.rmtree(cache_dir, ignore_errors=True)

            log_fn(f"Updated {updated} files successfully!")

            if commit_sha:
                _save_commit(commit_sha)

            return True

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _apply_frozen_update(data, download_url, log_fn):
    """Apply update to a frozen (PyInstaller) app via restart batch script."""
    # Extract ZIP to a persistent temp directory
    update_dir = BASE_DIR / "_update_staging"
    if update_dir.exists():
        shutil.rmtree(update_dir, ignore_errors=True)
    update_dir.mkdir(exist_ok=True)

    try:
        with zipfile.ZipFile(data) as zf:
            # Check if ZIP has a single top-level folder or files at root
            members = zf.namelist()
            if not members:
                log_fn("Empty archive — update aborted.")
                return False

            zf.extractall(update_dir)

            # If all files are under a single folder, move them up
            top_items = set()
            for m in members:
                top = m.split("/")[0]
                if top:
                    top_items.add(top)

            if len(top_items) == 1:
                subfolder = update_dir / top_items.pop()
                if subfolder.is_dir():
                    # Move contents up one level
                    for item in subfolder.iterdir():
                        dest = update_dir / item.name
                        if dest.exists():
                            if dest.is_dir():
                                shutil.rmtree(dest, ignore_errors=True)
                            else:
                                dest.unlink()
                        shutil.move(str(item), str(dest))
                    subfolder.rmdir()

        log_fn("Update downloaded! Preparing restart...")
    except Exception as e:
        log_fn(f"Extract failed: {e}")
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
        log_fn(f"Could not create update script: {e}")
        shutil.rmtree(update_dir, ignore_errors=True)
        return False

    # Launch the batch script (passing current PID so it waits for us)
    try:
        subprocess.Popen(
            ["cmd", "/c", str(bat_path), str(os.getpid())],
            creationflags=0x00000008,  # DETACHED_PROCESS
        )
    except Exception as e:
        log_fn(f"Could not launch update script: {e}")
        shutil.rmtree(update_dir, ignore_errors=True)
        bat_path.unlink(missing_ok=True)
        return False

    log_fn("Restarting to apply update...")
    return True  # Caller should exit the app


def _apply_source_update(data, log_fn):
    """Apply update to a source (non-frozen) install by overwriting .py files."""
    with zipfile.ZipFile(data) as zf:
        # GitHub zipball has a top-level folder like "user-repo-abc1234/"
        members = zf.namelist()
        if not members:
            log_fn("Empty archive — update aborted.")
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

            log_fn(f"Updated {updated} files successfully!")

            if commit_sha:
                _save_commit(commit_sha)

            # Install any new dependencies
            req_file = BASE_DIR / "requirements.txt"
            if req_file.exists():
                log_fn("Installing updated dependencies...")
                try:
                    subprocess.run(
                        [sys.executable, "-m", "pip", "install", "-r", str(req_file)],
                        capture_output=True, text=True, timeout=300,
                    )
                    log_fn("Dependencies updated!")
                except Exception:
                    log_fn("Could not auto-install dependencies — run install.bat")

            return True

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
