"""Auto-download FFmpeg and Playwright Chromium on first run."""

import os
import sys
import shutil
import subprocess
import zipfile
import tempfile
from pathlib import Path
from urllib.request import urlretrieve

from utils.logger import log

# FFmpeg static build for Windows (BtbN/FFmpeg-Builds on GitHub)
_FFMPEG_WIN_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    "ffmpeg-master-latest-win64-gpl.zip"
)


def _app_root() -> Path:
    """Get the application root directory (works for both normal and frozen)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


def _bin_dir() -> Path:
    """Local bin/ directory next to the app for bundled tools."""
    d = _app_root() / "bin"
    d.mkdir(exist_ok=True)
    return d


def ensure_path():
    """Add local bin/ to PATH so ffmpeg/ffprobe are found."""
    bin_path = str(_bin_dir())
    if bin_path not in os.environ.get("PATH", ""):
        os.environ["PATH"] = bin_path + os.pathsep + os.environ.get("PATH", "")


def is_ffmpeg_installed() -> bool:
    """Check if ffmpeg is available (PATH or local bin/)."""
    ensure_path()
    return shutil.which("ffmpeg") is not None


def is_chromium_installed() -> bool:
    """Check if Playwright Chromium browser is downloaded."""
    env_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env_path:
        bp = Path(env_path)
    elif sys.platform == "win32":
        bp = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    else:
        bp = Path.home() / ".cache" / "ms-playwright"

    if not bp.exists():
        return False
    return any(d.name.startswith("chromium-") for d in bp.iterdir() if d.is_dir())


def download_ffmpeg(progress_callback=None):
    """Download FFmpeg static build for Windows and extract to bin/.

    Args:
        progress_callback: Optional callable(status_text) for UI updates.
    """
    if sys.platform != "win32":
        log.info("FFmpeg auto-download is Windows-only. Install via your package manager.")
        return False

    bin_path = _bin_dir()
    ffmpeg_exe = bin_path / "ffmpeg.exe"
    if ffmpeg_exe.exists():
        log.info("FFmpeg already in bin/")
        ensure_path()
        return True

    log.info("Downloading FFmpeg...")
    if progress_callback:
        progress_callback("Downloading FFmpeg (~100 MB)...")

    try:
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / "ffmpeg.zip"

            def _report(block_num, block_size, total_size):
                if total_size > 0 and progress_callback:
                    pct = min(100, block_num * block_size * 100 // total_size)
                    progress_callback(f"Downloading FFmpeg... {pct}%")

            urlretrieve(_FFMPEG_WIN_URL, str(zip_path), reporthook=_report)

            if progress_callback:
                progress_callback("Extracting FFmpeg...")
            log.info("Extracting FFmpeg...")

            with zipfile.ZipFile(zip_path) as zf:
                # Find ffmpeg.exe and ffprobe.exe inside the ZIP
                for name in zf.namelist():
                    basename = Path(name).name.lower()
                    if basename in ("ffmpeg.exe", "ffprobe.exe"):
                        data = zf.read(name)
                        dest = bin_path / basename
                        dest.write_bytes(data)
                        log.info(f"  Extracted {basename}")

        ensure_path()
        if ffmpeg_exe.exists():
            log.info("FFmpeg installed successfully.")
            if progress_callback:
                progress_callback("FFmpeg OK")
            return True
        else:
            log.error("FFmpeg extraction failed — ffmpeg.exe not found in ZIP.")
            return False

    except Exception as e:
        log.error(f"FFmpeg download failed: {e}")
        if progress_callback:
            progress_callback(f"FFmpeg download failed: {e}")
        return False


def install_playwright_chromium(progress_callback=None):
    """Install Playwright Chromium browser."""
    if is_chromium_installed():
        log.info("Playwright Chromium already installed.")
        return True

    log.info("Installing Playwright Chromium browser...")
    if progress_callback:
        progress_callback("Installing Playwright Chromium (~280 MB)...")

    try:
        if getattr(sys, "frozen", False):
            # PyInstaller frozen app — use playwright driver directly
            from playwright._impl._driver import compute_driver_executable
            driver = str(compute_driver_executable())
            result = subprocess.run(
                [driver, "install", "chromium"],
                capture_output=True, text=True, timeout=600,
            )
        else:
            result = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                capture_output=True, text=True, timeout=600,
            )

        if result.returncode == 0:
            log.info("Playwright Chromium installed successfully.")
            if progress_callback:
                progress_callback("Playwright Chromium OK")
            return True
        else:
            log.error(f"Playwright install failed: {result.stderr}")
            if progress_callback:
                progress_callback(f"Playwright install failed")
            return False

    except Exception as e:
        log.error(f"Playwright install error: {e}")
        if progress_callback:
            progress_callback(f"Playwright install error: {e}")
        return False


def auto_setup(progress_callback=None):
    """Run all first-time setup checks. Returns True if everything is OK."""
    ensure_path()
    all_ok = True

    if not is_ffmpeg_installed():
        if not download_ffmpeg(progress_callback):
            all_ok = False

    if not is_chromium_installed():
        if not install_playwright_chromium(progress_callback):
            all_ok = False

    return all_ok
