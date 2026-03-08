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


def _find_playwright_cli():
    """Locate the Playwright CLI executable.

    Returns the path string, or None if not found.
    Works in both frozen (PyInstaller) and normal (source) mode.
    """
    candidates = []

    if getattr(sys, "frozen", False):
        # 1) Playwright's own driver locator
        try:
            from playwright._impl._driver import compute_driver_executable
            candidates.append(str(compute_driver_executable()))
        except Exception:
            pass

        # 2) sys._MEIPASS (PyInstaller internal data directory)
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            driver_dir = Path(meipass) / "playwright" / "driver"
            cli = "playwright.cmd" if sys.platform == "win32" else "playwright.sh"
            candidates.append(str(driver_dir / cli))

        # 3) Next to the exe (one-dir mode, various PyInstaller layouts)
        exe_dir = Path(sys.executable).parent
        for sub in ("_internal", "."):
            driver_dir = exe_dir / sub / "playwright" / "driver"
            cli = "playwright.cmd" if sys.platform == "win32" else "playwright.sh"
            candidates.append(str(driver_dir / cli))

    # 4) Search PATH (works for both frozen and non-frozen)
    search = ("playwright.cmd", "playwright") if sys.platform == "win32" else ("playwright",)
    for name in search:
        found = shutil.which(name)
        if found:
            candidates.append(found)

    # Return first candidate that actually exists on disk
    for c in candidates:
        if c and Path(c).exists():
            return c
    return None


def _python_executables():
    """Yield Python executable paths to try, in order of preference."""
    if sys.executable and Path(sys.executable).exists():
        yield sys.executable
    for name in ("python", "python3", "py"):
        found = shutil.which(name)
        if found:
            yield found


def install_playwright_chromium(progress_callback=None):
    """Install Playwright Chromium browser."""
    if is_chromium_installed():
        log.info("Playwright Chromium already installed.")
        return True

    log.info("Installing Playwright Chromium browser...")
    if progress_callback:
        progress_callback("Installing Playwright Chromium (~280 MB)...")

    try:
        result = None

        if getattr(sys, "frozen", False):
            # PyInstaller frozen app — find the playwright driver executable
            driver = _find_playwright_cli()
            if driver:
                log.info(f"Using Playwright CLI: {driver}")
                result = subprocess.run(
                    [driver, "install", "chromium"],
                    capture_output=True, text=True, timeout=600,
                )
            else:
                log.error(
                    "Cannot find Playwright driver in frozen app. "
                    "Install Chromium manually: playwright install chromium"
                )
                if progress_callback:
                    progress_callback("Playwright driver not found — install manually")
                return False
        else:
            # Non-frozen: try Python -m playwright, with fallbacks
            for exe in _python_executables():
                try:
                    log.info(f"Trying: {exe} -m playwright install chromium")
                    result = subprocess.run(
                        [exe, "-m", "playwright", "install", "chromium"],
                        capture_output=True, text=True, timeout=600,
                    )
                    break
                except FileNotFoundError:
                    log.warning(f"Python executable not found: {exe}")
                    continue

            if result is None:
                # Fallback: try playwright CLI directly from PATH
                driver = _find_playwright_cli()
                if driver:
                    log.info(f"Using Playwright CLI fallback: {driver}")
                    result = subprocess.run(
                        [driver, "install", "chromium"],
                        capture_output=True, text=True, timeout=600,
                    )
                else:
                    log.error(
                        f"Cannot find Python ({sys.executable}) or Playwright CLI. "
                        "Install Chromium manually: python -m playwright install chromium"
                    )
                    if progress_callback:
                        progress_callback("Python/Playwright not found — install manually")
                    return False

        if result.returncode == 0:
            log.info("Playwright Chromium installed successfully.")
            if progress_callback:
                progress_callback("Playwright Chromium OK")
            return True
        else:
            log.error(f"Playwright install failed (exit {result.returncode}): {result.stderr}")
            if progress_callback:
                progress_callback(f"Playwright install failed")
            return False

    except Exception as e:
        log.error(f"Playwright install error: {e}")
        if progress_callback:
            progress_callback(f"Playwright install error: {e}")
        return False


def _check_missing_packages():
    """Check which required packages are not importable."""
    # Map pip package names to their Python import names
    package_import_map = {
        "Pillow": "PIL",
        "openai": "openai",
        "playwright": "playwright",
        "python-dotenv": "dotenv",
        "apscheduler": "apscheduler",
        "requests": "requests",
        "google-api-python-client": "googleapiclient",
        "google-auth-oauthlib": "google_auth_oauthlib",
        "google-auth-httplib2": "google_auth_httplib2",
        "packaging": "packaging",
        "librosa": "librosa",
        "numpy": "numpy",
        "soundfile": "soundfile",
    }
    missing = []
    for pip_name, import_name in package_import_map.items():
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pip_name)
    return missing


def install_missing_packages(progress_callback=None):
    """Auto-install any missing Python packages from requirements.txt."""
    missing = _check_missing_packages()
    if not missing:
        return True

    log.info(f"Missing packages detected: {', '.join(missing)}")
    if progress_callback:
        progress_callback(f"Installing missing packages: {', '.join(missing)}...")

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install"] + missing,
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0:
            log.info(f"Successfully installed: {', '.join(missing)}")
            if progress_callback:
                progress_callback("Packages installed OK")
            return True
        else:
            log.error(f"pip install failed: {result.stderr[-300:]}")
            if progress_callback:
                progress_callback(f"Package install failed — run install.bat")
            return False
    except Exception as e:
        log.error(f"Package install error: {e}")
        if progress_callback:
            progress_callback(f"Package install error: {e}")
        return False


def auto_setup(progress_callback=None):
    """Run all first-time setup checks. Returns True if everything is OK."""
    ensure_path()
    all_ok = True

    # Check and install missing Python packages
    if not install_missing_packages(progress_callback):
        all_ok = False

    if not is_ffmpeg_installed():
        if not download_ffmpeg(progress_callback):
            all_ok = False

    if not is_chromium_installed():
        if not install_playwright_chromium(progress_callback):
            all_ok = False

    return all_ok
