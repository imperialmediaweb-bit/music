#!/usr/bin/env python3
"""
LUTH — Desktop GUI Application
Full automation: generate music → thumbnail → video → upload to YouTube & TikTok
"""

import os
import sys
import json
import threading
import queue
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
from pathlib import Path
from datetime import datetime

# Ensure we run from the script directory
os.chdir(Path(__file__).parent)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
APP_TITLE = "LUTH"
APP_VERSION = "2.0.0"
ENV_FILE = Path(__file__).parent / ".env"
BG_COLOR = "#1a1a2e"
CARD_COLOR = "#16213e"
ACCENT_COLOR = "#e94560"
ACCENT2_COLOR = "#0f3460"
TEXT_COLOR = "#eee"
TEXT_DIM = "#999"
SUCCESS_COLOR = "#00c853"
WARNING_COLOR = "#ffc107"
ERROR_COLOR = "#ff5252"
FONT_FAMILY = "Segoe UI"
FONT = (FONT_FAMILY, 10)
FONT_BOLD = (FONT_FAMILY, 10, "bold")
FONT_TITLE = (FONT_FAMILY, 14, "bold")
FONT_HEADER = (FONT_FAMILY, 18, "bold")
FONT_MONO = ("Consolas", 9)


# ---------------------------------------------------------------------------
# Ensure Playwright finds installed browsers (frozen PyInstaller builds look
# in .local-browsers by default which may be empty — redirect to standard path)
# ---------------------------------------------------------------------------
if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
    if sys.platform == "win32":
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(
            Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
        )
    else:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(
            Path.home() / ".cache" / "ms-playwright"
        )

# ---------------------------------------------------------------------------
# Clear stale __pycache__ so Python uses updated .py files after an update
# ---------------------------------------------------------------------------
import shutil as _shutil
for _cache_dir in Path(__file__).parent.rglob("__pycache__"):
    _shutil.rmtree(_cache_dir, ignore_errors=True)

# ---------------------------------------------------------------------------
# One-time cleanup: remove moviepy/imageio (replaced by FFmpeg)
# These cause "No package metadata found for imageio" on Windows
# ---------------------------------------------------------------------------
def _cleanup_obsolete_packages():
    # Skip in frozen apps — pip doesn't work on bundled packages
    if getattr(sys, "frozen", False):
        return
    try:
        __import__("moviepy")
    except ImportError:
        return  # not installed, nothing to do
    except Exception:
        pass  # installed but broken — still need to remove it
    import subprocess
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "uninstall", "-y",
             "moviepy", "imageio", "imageio-ffmpeg"],
            capture_output=True, text=True, timeout=120,
        )
    except Exception:
        pass

_cleanup_obsolete_packages()


# ---------------------------------------------------------------------------
# Log queue — captures pipeline logs and sends them to the GUI
# ---------------------------------------------------------------------------
_log_queue: queue.Queue = queue.Queue()


class GUILogHandler:
    """Intercepts pipeline log output and routes it to the GUI log panel."""

    def __init__(self, q: queue.Queue):
        self.q = q

    def write(self, msg: str):
        if msg.strip():
            self.q.put(msg.rstrip("\n"))

    def flush(self):
        pass


# ---------------------------------------------------------------------------
# Helper: read/write .env
# ---------------------------------------------------------------------------
ENV_EXAMPLE = Path(__file__).parent / ".env.example"


def _ensure_env_file():
    """Create .env from .env.example on first run so settings persist."""
    if not ENV_FILE.exists() and ENV_EXAMPLE.exists():
        import shutil
        shutil.copy2(ENV_EXAMPLE, ENV_FILE)


def read_env() -> dict:
    _ensure_env_file()
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                env[key.strip()] = val.strip()
    return env


def write_env(env: dict):
    lines = []
    for k, v in env.items():
        lines.append(f"{k}={v}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def check_dependency(name: str) -> bool:
    """Check if a Python package is importable."""
    try:
        __import__(name)
        return True
    except ImportError:
        return False


def check_ffmpeg() -> bool:
    import shutil
    from utils.auto_setup import ensure_path
    ensure_path()
    return shutil.which("ffmpeg") is not None


def check_cookies(path: str) -> bool:
    p = Path(path)
    return p.exists() and p.stat().st_size > 100


# ---------------------------------------------------------------------------
# Main Application
# ---------------------------------------------------------------------------
class MusicFactoryApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title(APP_TITLE)
        self.geometry("960x700")
        self.minsize(800, 600)
        self.configure(bg=BG_COLOR)
        self._set_icon()

        # State
        self.running = False
        self.current_thread = None

        # Style
        self._setup_styles()

        # Layout
        self._build_header()
        self._build_notebook()
        self._build_statusbar()

        # Start log polling
        self._poll_log_queue()

        # Auto-install missing dependencies on first run, then refresh status
        self.after(500, self._auto_setup_check)

        # Auto-check for updates after 3 seconds
        self._pending_update_url = None
        self.after(3000, self._auto_check_update)

        # Auto-save settings when user closes the window
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _set_icon(self):
        try:
            ico_path = Path(__file__).parent / "assets" / "luth.ico"
            if ico_path.exists():
                self.iconbitmap(str(ico_path))
        except Exception:
            pass
        # Also set the title bar icon (for Linux/taskbar)
        try:
            logo_path = Path(__file__).parent / "assets" / "luth_logo.png"
            if logo_path.exists():
                icon_img = tk.PhotoImage(file=str(logo_path))
                self.iconphoto(True, icon_img)
                self._icon_ref = icon_img  # keep reference
        except Exception:
            pass

    def _setup_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure(".", background=BG_COLOR, foreground=TEXT_COLOR, font=FONT)
        style.configure("TFrame", background=BG_COLOR)
        style.configure("Card.TFrame", background=CARD_COLOR)
        style.configure("TLabel", background=BG_COLOR, foreground=TEXT_COLOR, font=FONT)
        style.configure("Card.TLabel", background=CARD_COLOR, foreground=TEXT_COLOR, font=FONT)
        style.configure("Title.TLabel", background=BG_COLOR, foreground=TEXT_COLOR, font=FONT_TITLE)
        style.configure("Header.TLabel", background=BG_COLOR, foreground=TEXT_COLOR, font=FONT_HEADER)
        style.configure("Dim.TLabel", background=BG_COLOR, foreground=TEXT_DIM, font=FONT)
        style.configure("Success.TLabel", background=CARD_COLOR, foreground=SUCCESS_COLOR, font=FONT_BOLD)
        style.configure("Warning.TLabel", background=CARD_COLOR, foreground=WARNING_COLOR, font=FONT_BOLD)
        style.configure("Error.TLabel", background=CARD_COLOR, foreground=ERROR_COLOR, font=FONT_BOLD)

        style.configure("Accent.TButton", background=ACCENT_COLOR, foreground="white",
                         font=FONT_BOLD, padding=(20, 10))
        style.map("Accent.TButton",
                   background=[("active", "#c0392b"), ("disabled", "#555")])

        style.configure("Secondary.TButton", background=ACCENT2_COLOR, foreground="white",
                         font=FONT, padding=(12, 6))
        style.map("Secondary.TButton",
                   background=[("active", "#1a4a80"), ("disabled", "#555")])

        style.configure("TNotebook", background=BG_COLOR, borderwidth=0)
        style.configure("TNotebook.Tab", background=CARD_COLOR, foreground=TEXT_COLOR,
                         font=FONT_BOLD, padding=(16, 8))
        style.map("TNotebook.Tab",
                   background=[("selected", ACCENT2_COLOR)],
                   foreground=[("selected", "white")])

        style.configure("TEntry", fieldbackground="#2a2a4a", foreground=TEXT_COLOR,
                         insertcolor=TEXT_COLOR, font=FONT)
        style.configure("TSpinbox", fieldbackground="#2a2a4a", foreground=TEXT_COLOR, font=FONT)

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------
    def _build_header(self):
        hdr = ttk.Frame(self)
        hdr.pack(fill="x", padx=20, pady=(15, 5))

        # Logo image in header
        try:
            logo_path = Path(__file__).parent / "assets" / "luth_64.png"
            if logo_path.exists():
                self._header_logo = tk.PhotoImage(file=str(logo_path))
                logo_lbl = ttk.Label(hdr, image=self._header_logo, background=BG_COLOR)
                logo_lbl.pack(side="left", padx=(0, 10))
        except Exception:
            pass

        ttk.Label(hdr, text="LUTH", style="Header.TLabel").pack(side="left")
        ttk.Label(hdr, text=f"v{APP_VERSION}", style="Dim.TLabel").pack(side="left", padx=(10, 0))
        # Show last update commit info
        self._version_detail_label = ttk.Label(hdr, text="", style="Dim.TLabel")
        self._version_detail_label.pack(side="left", padx=(6, 0))
        self._load_version_detail()
        ttk.Label(hdr, text="Music Automation Pipeline", style="Dim.TLabel").pack(side="left", padx=(10, 0))

        # Update button (right side of header)
        self.update_frame = ttk.Frame(hdr)
        self.update_frame.pack(side="right")
        self.btn_update = ttk.Button(
            self.update_frame, text="Check for Updates",
            style="Secondary.TButton", command=self._on_check_update,
        )
        self.btn_update.pack(side="right")
        self.update_label = ttk.Label(self.update_frame, text="", style="Dim.TLabel")
        self.update_label.pack(side="right", padx=(0, 8))

    # ------------------------------------------------------------------
    # Notebook (tabs)
    # ------------------------------------------------------------------
    def _build_notebook(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=15, pady=10)

        # Tab 1: Dashboard / Run
        self.tab_run = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_run, text="  Pipeline  ")
        self._build_run_tab()

        # Tab 2: Settings
        self.tab_settings = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_settings, text="  Settings  ")
        self._build_settings_tab()

        # Tab 3: Logins
        self.tab_logins = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_logins, text="  Logins  ")
        self._build_logins_tab()

        # Tab 4: Schedule
        self.tab_schedule = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_schedule, text="  Schedule  ")
        self._build_schedule_tab()

        # Tab 5: Log
        self.tab_log = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_log, text="  Log  ")
        self._build_log_tab()

    # ------------------------------------------------------------------
    # Tab: Pipeline (Run)
    # ------------------------------------------------------------------
    def _build_run_tab(self):
        parent = self.tab_run

        # Status cards row
        status_frame = ttk.Frame(parent)
        status_frame.pack(fill="x", padx=10, pady=10)

        self.status_cards = {}
        cards_data = [
            ("openai", "OpenAI API"),
            ("ffmpeg", "FFmpeg"),
            ("playwright", "Playwright"),
            ("youtube", "YouTube"),
            ("tiktok", "TikTok"),
            ("music_factory", "Music Factory"),
            ("suno", "Suno"),
            ("udio", "Udio"),
        ]
        for i, (key, label) in enumerate(cards_data):
            card = ttk.Frame(status_frame, style="Card.TFrame", padding=10)
            card.grid(row=0, column=i, padx=4, pady=4, sticky="nsew")
            status_frame.columnconfigure(i, weight=1)

            ttk.Label(card, text=label, style="Card.TLabel").pack()
            status_lbl = ttk.Label(card, text="...", style="Warning.TLabel")
            status_lbl.pack(pady=(4, 0))
            self.status_cards[key] = status_lbl

        # Action buttons
        actions = ttk.Frame(parent)
        actions.pack(fill="x", padx=10, pady=10)

        # Platform selector
        platform_frame = ttk.Frame(actions)
        platform_frame.pack(side="left", padx=(0, 15))
        ttk.Label(platform_frame, text="Platform:").pack(side="left")
        self.platform_var = tk.StringVar(value="aimusicfactory")
        platform_combo = ttk.Combobox(platform_frame, textvariable=self.platform_var,
                                       values=["aimusicfactory", "suno", "udio"],
                                       state="readonly", width=14, font=FONT)
        platform_combo.pack(side="left", padx=(6, 0))

        # Songs per clip selector
        songs_frame = ttk.Frame(actions)
        songs_frame.pack(side="left", padx=(0, 15))
        ttk.Label(songs_frame, text="Songs:").pack(side="left")
        self.songs_var = tk.IntVar(value=2)
        songs_combo = ttk.Combobox(songs_frame, textvariable=self.songs_var,
                                    values=[2, 4, 6, 8],
                                    state="readonly", width=4, font=FONT)
        songs_combo.pack(side="left", padx=(6, 0))

        # Clip count
        count_frame = ttk.Frame(actions)
        count_frame.pack(side="left", padx=(0, 15))
        ttk.Label(count_frame, text="Clips:").pack(side="left")
        self.clip_count = tk.IntVar(value=1)
        spin = ttk.Spinbox(count_frame, from_=1, to=8, textvariable=self.clip_count,
                            width=4, font=FONT)
        spin.pack(side="left", padx=(6, 0))

        # Run button
        self.btn_run = ttk.Button(actions, text="RUN PIPELINE", style="Accent.TButton",
                                   command=self._on_run_pipeline)
        self.btn_run.pack(side="left", padx=5)

        # Stop button
        self.btn_stop = ttk.Button(actions, text="STOP", style="Secondary.TButton",
                                    command=self._on_stop, state="disabled")
        self.btn_stop.pack(side="left", padx=5)

        # Quick actions
        quick = ttk.Frame(actions)
        quick.pack(side="right")
        ttk.Button(quick, text="Process MP3s", style="Secondary.TButton",
                    command=self._on_process_mp3s).pack(side="left", padx=3)
        ttk.Button(quick, text="Re-upload", style="Secondary.TButton",
                    command=self._on_reupload).pack(side="left", padx=3)

        # Live log area (mini)
        log_frame = ttk.Frame(parent, style="Card.TFrame")
        log_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        ttk.Label(log_frame, text="Live Output", style="Card.TLabel").pack(anchor="w", padx=10, pady=(8, 2))
        self.mini_log = scrolledtext.ScrolledText(
            log_frame, height=12, bg="#0d1117", fg="#c9d1d9",
            font=FONT_MONO, wrap="word", state="disabled",
            insertbackground=TEXT_COLOR, selectbackground=ACCENT2_COLOR,
            borderwidth=0, highlightthickness=0,
        )
        self.mini_log.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.mini_log.tag_config("error", foreground=ERROR_COLOR)
        self.mini_log.tag_config("success", foreground=SUCCESS_COLOR)
        self.mini_log.tag_config("warning", foreground=WARNING_COLOR)

    # ------------------------------------------------------------------
    # Tab: Settings
    # ------------------------------------------------------------------
    def _build_settings_tab(self):
        parent = self.tab_settings

        canvas = tk.Canvas(parent, bg=BG_COLOR, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)

        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        scrollbar.pack(side="right", fill="y")

        # OpenAI API Key
        card1 = self._make_card(scroll_frame, "OpenAI API Key")
        ttk.Label(card1, text="Required for concept generation (GPT-4) and thumbnails (DALL-E 3)",
                   style="Card.TLabel").pack(anchor="w")
        self.entry_openai = ttk.Entry(card1, width=60, show="*")
        self.entry_openai.pack(fill="x", pady=(6, 0))

        # Headless mode
        card2 = self._make_card(scroll_frame, "Browser Settings")
        self.headless_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(card2, text="Headless mode (hide browser windows during automation)",
                         variable=self.headless_var).pack(anchor="w")

        # Output directory
        card3 = self._make_card(scroll_frame, "Output Directory")
        out_row = ttk.Frame(card3, style="Card.TFrame")
        out_row.pack(fill="x")
        self.entry_output_dir = ttk.Entry(out_row, width=50)
        self.entry_output_dir.pack(side="left", fill="x", expand=True)
        ttk.Button(out_row, text="Browse", style="Secondary.TButton",
                    command=self._browse_output).pack(side="left", padx=(6, 0))

        # Music Genre
        card4 = self._make_card(scroll_frame, "Music Genre")
        ttk.Label(card4, text="Genre used for concept generation (e.g. Afro House, Lo-Fi, Trap, EDM, Jazz)",
                   style="Card.TLabel").pack(anchor="w")
        self.entry_genre = ttk.Entry(card4, width=40)
        self.entry_genre.pack(fill="x", pady=(6, 0))

        # Music Style Prompt
        card5 = self._make_card(scroll_frame, "Music Style Prompt")
        ttk.Label(card5, text="Describes the sound, instruments, tempo, mood for AI music generation.\n"
                   "Leave empty to use default for your genre.",
                   style="Card.TLabel").pack(anchor="w")
        self.text_music_prompt = tk.Text(card5, height=6, wrap="word",
                                          bg="#1e1e3a", fg=TEXT_COLOR, insertbackground=TEXT_COLOR,
                                          font=FONT_MONO, relief="flat", bd=1)
        self.text_music_prompt.pack(fill="x", pady=(6, 0))

        # Thumbnail Style Prompt
        card6 = self._make_card(scroll_frame, "Thumbnail Style Prompt")
        ttk.Label(card6, text="Describes the visual style for DALL-E thumbnail generation.\n"
                   "Leave empty to use default (African tribal mask).",
                   style="Card.TLabel").pack(anchor="w")
        self.text_thumbnail_prompt = tk.Text(card6, height=6, wrap="word",
                                              bg="#1e1e3a", fg=TEXT_COLOR, insertbackground=TEXT_COLOR,
                                              font=FONT_MONO, relief="flat", bd=1)
        self.text_thumbnail_prompt.pack(fill="x", pady=(6, 0))

        # Save button
        btn_frame = ttk.Frame(scroll_frame)
        btn_frame.pack(fill="x", pady=15, padx=10)
        ttk.Button(btn_frame, text="Save Settings", style="Accent.TButton",
                    command=self._save_settings).pack(side="left")
        self.settings_status = ttk.Label(btn_frame, text="", style="Dim.TLabel")
        self.settings_status.pack(side="left", padx=15)

        # Load current settings
        self._load_settings()

    def _make_card(self, parent, title: str) -> ttk.Frame:
        card = ttk.Frame(parent, style="Card.TFrame", padding=15)
        card.pack(fill="x", padx=10, pady=6)
        ttk.Label(card, text=title, font=FONT_BOLD, style="Card.TLabel").pack(anchor="w", pady=(0, 6))
        return card

    def _load_env(self) -> dict:
        """Load .env file settings (wrapper around module-level read_env)."""
        return read_env()

    def _browse_output(self):
        d = filedialog.askdirectory()
        if d:
            self.entry_output_dir.delete(0, "end")
            self.entry_output_dir.insert(0, d)

    def _load_settings(self):
        env = read_env()
        api_key = env.get("OPENAI_API_KEY", "")
        if api_key and api_key != "sk-your-key-here":
            self.entry_openai.insert(0, api_key)
        self.headless_var.set(env.get("HEADLESS", "true").lower() == "true")
        self.entry_output_dir.insert(0, env.get("OUTPUT_DIR", "output"))
        self.entry_genre.insert(0, env.get("MUSIC_GENRE", "Afro House"))
        music_prompt = env.get("MUSIC_STYLE_PROMPT", "")
        if music_prompt:
            self.text_music_prompt.insert("1.0", music_prompt)
        thumb_prompt = env.get("THUMBNAIL_STYLE_PROMPT", "")
        if thumb_prompt:
            self.text_thumbnail_prompt.insert("1.0", thumb_prompt)

    def _save_settings(self):
        env = read_env()
        api_key = self.entry_openai.get().strip()
        if api_key:
            env["OPENAI_API_KEY"] = api_key
        env["HEADLESS"] = "true" if self.headless_var.get() else "false"
        out_dir = self.entry_output_dir.get().strip()
        if out_dir:
            env["OUTPUT_DIR"] = out_dir
        genre = self.entry_genre.get().strip()
        if genre:
            env["MUSIC_GENRE"] = genre
        music_prompt = self.text_music_prompt.get("1.0", "end-1c").strip()
        env["MUSIC_STYLE_PROMPT"] = music_prompt
        thumb_prompt = self.text_thumbnail_prompt.get("1.0", "end-1c").strip()
        env["THUMBNAIL_STYLE_PROMPT"] = thumb_prompt
        write_env(env)
        # Reload dotenv
        try:
            from dotenv import load_dotenv
            load_dotenv(override=True)
        except Exception:
            pass
        self.settings_status.config(text="Saved!", foreground=SUCCESS_COLOR)
        self.after(3000, lambda: self.settings_status.config(text=""))
        self._refresh_status()

    def _on_close(self):
        """Auto-save settings on exit so nothing is lost."""
        try:
            self._save_settings()
        except Exception:
            pass
        self.destroy()

    # ------------------------------------------------------------------
    # Tab: Logins
    # ------------------------------------------------------------------
    def _build_logins_tab(self):
        parent = self.tab_logins

        ttk.Label(parent, text="Service Logins",
                   style="Title.TLabel").pack(anchor="w", padx=15, pady=(15, 5))
        ttk.Label(parent, text="Click each button to open a browser and log into the service.\n"
                   "Your cookies will be saved automatically for future automation.",
                   style="Dim.TLabel").pack(anchor="w", padx=15)

        # Login cards
        logins = [
            ("AI Music Factory", "Login with Google to generate music",
             "music_factory", self._on_login_music),
            ("Suno", "Login to generate music on suno.com",
             "suno", self._on_login_suno),
            ("Udio", "Login to generate music on udio.com",
             "udio", self._on_login_udio),
            ("YouTube Studio", "Login to enable uploads & monetization",
             "youtube", self._on_login_youtube),
            ("TikTok", "Login to enable TikTok uploads",
             "tiktok", self._on_login_tiktok),
        ]

        for name, desc, key, cmd in logins:
            card = ttk.Frame(parent, style="Card.TFrame", padding=15)
            card.pack(fill="x", padx=15, pady=6)

            left = ttk.Frame(card, style="Card.TFrame")
            left.pack(side="left", fill="x", expand=True)
            ttk.Label(left, text=name, font=FONT_BOLD, style="Card.TLabel").pack(anchor="w")
            ttk.Label(left, text=desc, style="Card.TLabel").pack(anchor="w")

            right = ttk.Frame(card, style="Card.TFrame")
            right.pack(side="right")
            ttk.Button(right, text=f"Login", style="Secondary.TButton",
                        command=cmd).pack(padx=5)

        # YouTube OAuth section
        card_oauth = ttk.Frame(parent, style="Card.TFrame", padding=15)
        card_oauth.pack(fill="x", padx=15, pady=6)

        left = ttk.Frame(card_oauth, style="Card.TFrame")
        left.pack(side="left", fill="x", expand=True)
        ttk.Label(left, text="YouTube OAuth (client_secrets.json)", font=FONT_BOLD,
                   style="Card.TLabel").pack(anchor="w")
        ttk.Label(left, text="Required for YouTube API uploads. Get from Google Cloud Console.",
                   style="Card.TLabel").pack(anchor="w")
        self.oauth_status = ttk.Label(left, text="", style="Card.TLabel")
        self.oauth_status.pack(anchor="w", pady=(4, 0))

        right = ttk.Frame(card_oauth, style="Card.TFrame")
        right.pack(side="right")
        ttk.Button(right, text="Import JSON", style="Secondary.TButton",
                    command=self._import_oauth).pack(padx=5)

    def _import_oauth(self):
        f = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if f:
            import shutil
            dest = Path(__file__).parent / "client_secrets.json"
            shutil.copy2(f, dest)
            self.oauth_status.config(text="Imported!", foreground=SUCCESS_COLOR)
            self._refresh_status()

    # ------------------------------------------------------------------
    # Tab: Schedule
    # ------------------------------------------------------------------
    def _build_schedule_tab(self):
        parent = self.tab_schedule

        ttk.Label(parent, text="Automatic Scheduling",
                   style="Title.TLabel").pack(anchor="w", padx=15, pady=(15, 5))
        ttk.Label(parent, text="Set up Windows Task Scheduler to run the pipeline automatically.\n"
                   "No terminal window needs to stay open.",
                   style="Dim.TLabel").pack(anchor="w", padx=15, pady=(0, 10))

        # Schedule slots
        card = self._make_card_in(parent, "Daily Schedule")

        self.schedule_slots = []
        defaults = [("09", "50"), ("14", "00"), ("18", "00"), ("20", "00")]
        for i, (h, m) in enumerate(defaults):
            row = ttk.Frame(card, style="Card.TFrame")
            row.pack(fill="x", pady=2)

            enabled = tk.BooleanVar(value=True)
            ttk.Checkbutton(row, text=f"Slot {i + 1}:", variable=enabled).pack(side="left")

            hour_var = tk.StringVar(value=h)
            ttk.Spinbox(row, from_=0, to=23, textvariable=hour_var, width=3,
                         format="%02.0f", font=FONT).pack(side="left", padx=(6, 0))
            ttk.Label(row, text=":", style="Card.TLabel").pack(side="left")
            min_var = tk.StringVar(value=m)
            ttk.Spinbox(row, from_=0, to=59, textvariable=min_var, width=3,
                         format="%02.0f", font=FONT).pack(side="left")

            self.schedule_slots.append((enabled, hour_var, min_var))

        # Buttons
        btn_row = ttk.Frame(parent)
        btn_row.pack(fill="x", padx=15, pady=15)

        ttk.Button(btn_row, text="Install Schedule", style="Accent.TButton",
                    command=self._on_install_schedule).pack(side="left", padx=5)
        ttk.Button(btn_row, text="Remove Schedule", style="Secondary.TButton",
                    command=self._on_remove_schedule).pack(side="left", padx=5)
        ttk.Button(btn_row, text="View Current", style="Secondary.TButton",
                    command=self._on_list_schedule).pack(side="left", padx=5)

        self.schedule_status = ttk.Label(btn_row, text="", style="Dim.TLabel")
        self.schedule_status.pack(side="left", padx=15)

    def _make_card_in(self, parent, title: str) -> ttk.Frame:
        card = ttk.Frame(parent, style="Card.TFrame", padding=15)
        card.pack(fill="x", padx=15, pady=6)
        ttk.Label(card, text=title, font=FONT_BOLD, style="Card.TLabel").pack(anchor="w", pady=(0, 8))
        return card

    # ------------------------------------------------------------------
    # Tab: Log
    # ------------------------------------------------------------------
    def _build_log_tab(self):
        parent = self.tab_log

        toolbar = ttk.Frame(parent)
        toolbar.pack(fill="x", padx=10, pady=5)
        ttk.Button(toolbar, text="Clear Log", style="Secondary.TButton",
                    command=self._clear_log).pack(side="left")
        ttk.Button(toolbar, text="Open Log File", style="Secondary.TButton",
                    command=self._open_log_file).pack(side="left", padx=5)

        self.full_log = scrolledtext.ScrolledText(
            parent, bg="#0d1117", fg="#c9d1d9",
            font=FONT_MONO, wrap="word", state="disabled",
            insertbackground=TEXT_COLOR, selectbackground=ACCENT2_COLOR,
            borderwidth=0, highlightthickness=0,
        )
        self.full_log.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.full_log.tag_config("error", foreground=ERROR_COLOR)
        self.full_log.tag_config("success", foreground=SUCCESS_COLOR)
        self.full_log.tag_config("warning", foreground=WARNING_COLOR)
        self.full_log.tag_config("timestamp", foreground=TEXT_DIM)

    def _clear_log(self):
        for widget in (self.mini_log, self.full_log):
            widget.config(state="normal")
            widget.delete("1.0", "end")
            widget.config(state="disabled")

    def _open_log_file(self):
        log_path = Path(__file__).parent / "output" / "pipeline.log"
        if log_path.exists():
            os.startfile(str(log_path)) if sys.platform == "win32" else os.system(f"xdg-open '{log_path}'")

    # ------------------------------------------------------------------
    # Statusbar
    # ------------------------------------------------------------------
    def _build_statusbar(self):
        bar = ttk.Frame(self, style="Card.TFrame")
        bar.pack(fill="x", side="bottom")

        self.statusbar_text = ttk.Label(bar, text="Ready", style="Card.TLabel", padding=(10, 4))
        self.statusbar_text.pack(side="left")

        self.statusbar_right = ttk.Label(bar, text="", style="Card.TLabel", padding=(10, 4))
        self.statusbar_right.pack(side="right")

    def _set_status(self, text: str, color: str = TEXT_DIM):
        self.statusbar_text.config(text=text, foreground=color)

    # ------------------------------------------------------------------
    # Auto-setup (first run)
    # ------------------------------------------------------------------
    def _auto_setup_check(self):
        """Check for missing dependencies and auto-install them."""
        from utils.auto_setup import is_ffmpeg_installed, is_chromium_installed, ensure_path
        ensure_path()

        needs_ffmpeg = not is_ffmpeg_installed()
        needs_chromium = not is_chromium_installed()

        if not needs_ffmpeg and not needs_chromium:
            self._refresh_status()
            return

        # Run auto-setup in background thread
        self._set_status("Installing missing dependencies...", WARNING_COLOR)

        def setup_task():
            from utils.auto_setup import auto_setup
            def on_progress(text):
                self.after(0, lambda t=text: self._set_status(t, WARNING_COLOR))
            auto_setup(progress_callback=on_progress)
            self.after(0, self._on_setup_done)

        threading.Thread(target=setup_task, daemon=True).start()

    def _on_setup_done(self):
        self._set_status("Ready", SUCCESS_COLOR)
        self._refresh_status()

    # ------------------------------------------------------------------
    # Status refresh
    # ------------------------------------------------------------------
    def _refresh_status(self):
        env = read_env()

        # OpenAI
        api_key = env.get("OPENAI_API_KEY", "")
        if api_key and api_key != "sk-your-key-here" and api_key.startswith("sk-"):
            self.status_cards["openai"].config(text="OK", style="Success.TLabel")
        else:
            self.status_cards["openai"].config(text="Missing", style="Error.TLabel")

        # FFmpeg
        if check_ffmpeg():
            self.status_cards["ffmpeg"].config(text="OK", style="Success.TLabel")
        else:
            self.status_cards["ffmpeg"].config(text="Missing", style="Error.TLabel")

        # Playwright
        if check_dependency("playwright"):
            self.status_cards["playwright"].config(text="OK", style="Success.TLabel")
        else:
            self.status_cards["playwright"].config(text="Missing", style="Error.TLabel")

        # YouTube cookies
        yt_cookie = env.get("YOUTUBE_COOKIE_FILE", "cookies/youtube_cookies.json")
        if check_cookies(yt_cookie) or Path("client_secrets.json").exists():
            self.status_cards["youtube"].config(text="OK", style="Success.TLabel")
        else:
            self.status_cards["youtube"].config(text="No Login", style="Warning.TLabel")

        # TikTok cookies
        tt_cookie = env.get("TIKTOK_COOKIE_FILE", "cookies/tiktok_cookies.json")
        if check_cookies(tt_cookie):
            self.status_cards["tiktok"].config(text="OK", style="Success.TLabel")
        else:
            self.status_cards["tiktok"].config(text="No Login", style="Warning.TLabel")

        # Music Factory state
        state_file = env.get("AIMUSICFACTORY_STATE_FILE",
                              "cookies/aimusicfactory_state.json")
        if check_cookies(state_file):
            self.status_cards["music_factory"].config(text="OK", style="Success.TLabel")
        else:
            self.status_cards["music_factory"].config(text="No Login", style="Warning.TLabel")

        # Suno state
        suno_state = env.get("SUNO_STATE_FILE", "cookies/suno_state.json")
        if check_cookies(suno_state):
            self.status_cards["suno"].config(text="OK", style="Success.TLabel")
        else:
            self.status_cards["suno"].config(text="No Login", style="Warning.TLabel")

        # Udio state
        udio_state = env.get("UDIO_STATE_FILE", "cookies/udio_state.json")
        if check_cookies(udio_state):
            self.status_cards["udio"].config(text="OK", style="Success.TLabel")
        else:
            self.status_cards["udio"].config(text="No Login", style="Warning.TLabel")

        # OAuth status
        if hasattr(self, "oauth_status"):
            if Path("client_secrets.json").exists():
                self.oauth_status.config(text="client_secrets.json found", foreground=SUCCESS_COLOR)
            else:
                self.oauth_status.config(text="Not found — YouTube uploads will fail",
                                          foreground=WARNING_COLOR)

    # ------------------------------------------------------------------
    # Log polling (from background threads)
    # ------------------------------------------------------------------
    def _poll_log_queue(self):
        try:
            while True:
                msg = _log_queue.get_nowait()
                self._append_log(msg)
        except queue.Empty:
            pass
        self.after(100, self._poll_log_queue)

    def _append_log(self, text: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {text}\n"

        # Determine tag
        tag = None
        lower = text.lower()
        if "error" in lower or "failed" in lower or "exception" in lower:
            tag = "error"
        elif "done" in lower or "success" in lower or "completed" in lower or "url:" in lower:
            tag = "success"
        elif "warning" in lower or "skip" in lower:
            tag = "warning"

        for widget in (self.mini_log, self.full_log):
            widget.config(state="normal")
            if tag:
                widget.insert("end", line, tag)
            else:
                widget.insert("end", line)
            widget.see("end")
            widget.config(state="disabled")

    # ------------------------------------------------------------------
    # Pipeline execution (background thread)
    # ------------------------------------------------------------------
    def _run_in_thread(self, target, description: str = "Running..."):
        if self.running:
            messagebox.showwarning("Busy", "A task is already running. Wait or stop it first.")
            return

        self.running = True
        self.btn_run.config(state="disabled")
        self.btn_stop.config(state="normal")
        self._set_status(description, ACCENT_COLOR)

        # Redirect stdout/stderr to log queue
        gui_handler = GUILogHandler(_log_queue)

        def wrapper():
            # Patch the pipeline logger to also write to our queue
            import logging
            pipeline_logger = logging.getLogger()
            stream_handler = logging.StreamHandler(gui_handler)
            stream_handler.setFormatter(logging.Formatter("%(message)s"))
            pipeline_logger.addHandler(stream_handler)

            old_stdout = sys.stdout
            old_stderr = sys.stderr
            sys.stdout = gui_handler
            sys.stderr = gui_handler

            try:
                target()
                _log_queue.put("Pipeline finished successfully!")
                self.after(0, lambda: self._set_status("Completed!", SUCCESS_COLOR))
            except Exception as e:
                _log_queue.put(f"ERROR: {e}")
                self.after(0, lambda: self._set_status(f"Error: {e}", ERROR_COLOR))
            finally:
                sys.stdout = old_stdout
                sys.stderr = old_stderr
                pipeline_logger.removeHandler(stream_handler)
                self.running = False
                self.after(0, lambda: self.btn_run.config(state="normal"))
                self.after(0, lambda: self.btn_stop.config(state="disabled"))
                self.after(0, self._refresh_status)

        self.current_thread = threading.Thread(target=wrapper, daemon=True)
        self.current_thread.start()

    def _on_stop(self):
        if self.running:
            self._set_status("Stopping... (will finish current step)", WARNING_COLOR)
            # We can't truly kill the thread, but we signal it
            self.running = False
            _log_queue.put("Stop requested — pipeline will stop after current step.")

    # ------------------------------------------------------------------
    # Pipeline actions
    # ------------------------------------------------------------------
    def _on_run_pipeline(self):
        # Save current GUI settings to .env and reload into os.environ
        try:
            self._save_settings()
        except Exception:
            pass
        count = self.clip_count.get()
        platform = self.platform_var.get()
        songs = self.songs_var.get()
        # Read genre/prompt settings
        env = self._load_env()
        genre = env.get("MUSIC_GENRE", "Afro House")
        music_style = env.get("MUSIC_STYLE_PROMPT", "")
        thumbnail_style = env.get("THUMBNAIL_STYLE_PROMPT", "")

        def task():
            from main import _run_full_pipeline
            for i in range(count):
                if not self.running:
                    _log_queue.put("Stopped by user.")
                    break
                _log_queue.put(f"{'#' * 50}")
                _log_queue.put(f"CLIP {i + 1}/{count} | {genre} | {platform} | {songs} songs")
                _log_queue.put(f"{'#' * 50}")
                _run_full_pipeline(platform=platform, songs=songs,
                                   genre=genre, music_style=music_style,
                                   thumbnail_style=thumbnail_style)

        self._run_in_thread(task, f"Running {platform} ({count} clip{'s' if count > 1 else ''}, {songs} songs)...")

    def _on_process_mp3s(self):
        folder = filedialog.askdirectory(title="Select folder with MP3 files",
                                          initialdir=str(Path(__file__).parent / "input"))
        if not folder:
            return

        def task():
            from modules.audio_merger import merge_mp3s
            from pipeline import process_single_track

            mp3s = sorted(Path(folder).glob("*.mp3"))
            if not mp3s:
                _log_queue.put(f"No MP3 files found in {folder}")
                return
            _log_queue.put(f"Found {len(mp3s)} MP3 files")
            merged = merge_mp3s(mp3s)
            process_single_track(merged)

        self._run_in_thread(task, "Processing MP3s...")

    def _on_reupload(self):
        name = tk.simpledialog.askstring("Re-upload", "Enter track name (e.g. Zanu):",
                                          parent=self) if hasattr(tk, 'simpledialog') else None
        if name is None:
            # Fallback: simple dialog
            dialog = tk.Toplevel(self)
            dialog.title("Re-upload Track")
            dialog.geometry("350x120")
            dialog.configure(bg=BG_COLOR)
            dialog.transient(self)
            dialog.grab_set()

            ttk.Label(dialog, text="Track name:").pack(pady=(15, 5))
            entry = ttk.Entry(dialog, width=30)
            entry.pack()
            entry.focus()

            result = {"name": None}

            def submit():
                result["name"] = entry.get().strip()
                dialog.destroy()

            ttk.Button(dialog, text="Re-upload", style="Accent.TButton",
                        command=submit).pack(pady=10)
            dialog.bind("<Return>", lambda e: submit())
            self.wait_window(dialog)
            name = result["name"]

        if not name:
            return

        def task():
            from pipeline import reupload_track
            reupload_track(name)

        self._run_in_thread(task, f"Re-uploading {name}...")

    # ------------------------------------------------------------------
    # Login actions — run Playwright directly (no subprocess needed)
    # ------------------------------------------------------------------
    def _login_with_browser(self, url, save_path, save_mode="state", label=""):
        """Open a Chrome browser for login, save session when user closes it.

        Args:
            url: Website URL to open.
            save_path: Path to save cookies/state to.
            save_mode: "state" for storage_state (cookies+localStorage),
                       "cookies" for just cookies via save_cookies().
            label: Display name for log messages.
        """
        from playwright.sync_api import sync_playwright
        import time

        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)

        _log_queue.put(f"Opening Chrome for {label} login...")
        _log_queue.put(f"Log in, then CLOSE the browser window to save your session.")

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,
                channel="chrome",
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(viewport={"width": 1920, "height": 1080})
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)

            # Periodically save session while browser is open.
            # When the user closes the browser, the last save is kept.
            saved = False
            while browser.is_connected():
                try:
                    if save_mode == "cookies":
                        from utils.browser import save_cookies
                        save_cookies(context, save_path)
                    else:
                        context.storage_state(path=str(save_path))
                    saved = True
                except Exception:
                    pass
                try:
                    page.wait_for_timeout(3000)
                except Exception:
                    break

            if saved:
                _log_queue.put(f"{label} session saved! You can now run the pipeline.")
            else:
                _log_queue.put(f"Warning: Could not save {label} session. Try again.")

            try:
                browser.close()
            except Exception:
                pass

    def _on_login_music(self):
        env = self._load_env()
        state_file = env.get("AIMUSICFACTORY_STATE_FILE",
                             "cookies/aimusicfactory_state.json")

        def task():
            self._login_with_browser(
                "https://aimusicfactory.ai", state_file,
                save_mode="state", label="AI Music Factory")

        self._run_in_thread(task, "Logging into AI Music Factory...")

    def _on_login_suno(self):
        env = self._load_env()
        state_file = env.get("SUNO_STATE_FILE", "cookies/suno_state.json")

        def task():
            self._login_with_browser(
                "https://suno.com", state_file,
                save_mode="state", label="Suno")

        self._run_in_thread(task, "Logging into Suno...")

    def _on_login_udio(self):
        env = self._load_env()
        state_file = env.get("UDIO_STATE_FILE", "cookies/udio_state.json")

        def task():
            self._login_with_browser(
                "https://www.udio.com", state_file,
                save_mode="state", label="Udio")

        self._run_in_thread(task, "Logging into Udio...")

    def _on_login_youtube(self):
        env = self._load_env()
        cookie_file = env.get("YOUTUBE_COOKIE_FILE", "cookies/youtube_cookies.json")

        def task():
            self._login_with_browser(
                "https://studio.youtube.com", cookie_file,
                save_mode="cookies", label="YouTube Studio")

        self._run_in_thread(task, "Logging into YouTube...")

    def _on_login_tiktok(self):
        env = self._load_env()
        cookie_file = env.get("TIKTOK_COOKIE_FILE", "cookies/tiktok_cookies.json")

        def task():
            self._login_with_browser(
                "https://www.tiktok.com/login", cookie_file,
                save_mode="cookies", label="TikTok")

        self._run_in_thread(task, "Logging into TikTok...")

    # ------------------------------------------------------------------
    # Update actions
    # ------------------------------------------------------------------
    def _load_version_detail(self):
        """Show the last applied commit SHA in the header."""
        try:
            from modules.updater import _get_current_commit
            sha = _get_current_commit()
            if sha:
                self._version_detail_label.config(text=f"({sha})")
        except Exception:
            pass

    def _auto_check_update(self):
        """Silently check for updates in the background on startup."""
        def check():
            try:
                from modules.updater import check_for_update
                has_update, latest, url = check_for_update(APP_VERSION)
                if has_update:
                    self._pending_update_url = url
                    self.after(0, lambda: self._show_update_available(latest))
            except Exception as e:
                _log_queue.put(f"[UPDATE] Auto-check failed: {e}")

        threading.Thread(target=check, daemon=True).start()

    def _show_update_available(self, latest_version: str):
        """Show update notification in the header."""
        self.update_label.config(
            text=f"{latest_version} available!",
            foreground=SUCCESS_COLOR,
        )
        self.btn_update.config(text="Update Now", style="Accent.TButton")

    def _on_check_update(self):
        """Manual check for updates / apply update."""
        if self._pending_update_url:
            # We already know there's an update — apply it
            self._apply_update()
            return

        # Check for update
        self.btn_update.config(state="disabled")
        self.update_label.config(text="Checking...", foreground=TEXT_DIM)

        def check():
            try:
                from modules.updater import check_for_update
                has_update, latest, url = check_for_update(APP_VERSION)
                if has_update:
                    self._pending_update_url = url
                    self.after(0, lambda: self._show_update_available(latest))
                else:
                    self.after(0, lambda: self.update_label.config(
                        text="Up to date!", foreground=SUCCESS_COLOR))
                    self.after(5000, lambda: self.update_label.config(text=""))
            except Exception as e:
                err_msg = str(e)[:50]
                _log_queue.put(f"[UPDATE] Check failed: {e}")
                self.after(0, lambda: self.update_label.config(
                    text=f"Check failed: {err_msg}", foreground=ERROR_COLOR))
            finally:
                self.after(0, lambda: self.btn_update.config(state="normal"))

        threading.Thread(target=check, daemon=True).start()

    def _apply_update(self):
        """Download and apply the update, then prompt to restart."""
        if self.running:
            messagebox.showwarning("Busy", "Stop the pipeline before updating.")
            return

        confirm = messagebox.askyesno(
            "Update LUTH",
            "A new version is available.\n\n"
            "This will update the application files.\n"
            "Your settings, cookies, and output files will be preserved.\n\n"
            "Continue?",
        )
        if not confirm:
            return

        self.btn_update.config(state="disabled")
        self.update_label.config(text="Updating...", foreground=WARNING_COLOR)

        def do_update():
            from modules.updater import download_and_apply_update

            def on_progress(msg):
                self.after(0, lambda m=msg: self.update_label.config(text=m))
                _log_queue.put(f"[UPDATE] {msg}")

            success = download_and_apply_update(self._pending_update_url, on_progress)

            if success:
                self.after(0, self._on_update_complete)
            else:
                self.after(0, lambda: self.update_label.config(
                    text="Update failed!", foreground=ERROR_COLOR))
                self.after(0, lambda: self.btn_update.config(state="normal"))

        threading.Thread(target=do_update, daemon=True).start()

    def _on_update_complete(self):
        """Prompt user to restart after successful update."""
        self.update_label.config(text="Updated!", foreground=SUCCESS_COLOR)
        self._pending_update_url = None
        self._load_version_detail()
        _log_queue.put("[UPDATE] Update applied successfully! Restart to use the new version.")

        restart = messagebox.askyesno(
            "Update Complete",
            "LUTH has been updated successfully!\n\n"
            "Restart now to use the new version?",
        )
        if restart:
            self._restart_app()
        else:
            self.btn_update.config(text="Restart to Apply", style="Accent.TButton",
                                    state="normal", command=self._restart_app)

    def _restart_app(self):
        """Restart the application."""
        python = sys.executable
        os.execl(python, python, *sys.argv)

    # ------------------------------------------------------------------
    # Schedule actions
    # ------------------------------------------------------------------
    def _on_install_schedule(self):
        slots = []
        for enabled, h, m in self.schedule_slots:
            if enabled.get():
                slots.append((int(h.get()), int(m.get()), 1))

        if not slots:
            messagebox.showwarning("No Slots", "Enable at least one time slot.")
            return

        def task():
            from modules.os_scheduler import setup_schedule
            _log_queue.put(f"Installing {len(slots)} scheduled tasks...")
            setup_schedule(slots)
            _log_queue.put("Schedule installed successfully!")

        self._run_in_thread(task, "Installing schedule...")

    def _on_remove_schedule(self):
        def task():
            from modules.os_scheduler import setup_schedule
            _log_queue.put("Removing scheduled tasks...")
            setup_schedule([], remove=True)
            _log_queue.put("Schedule removed.")

        self._run_in_thread(task, "Removing schedule...")

    def _on_list_schedule(self):
        def task():
            from modules.os_scheduler import list_schedule
            list_schedule()

        self._run_in_thread(task, "Listing schedule...")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    app = MusicFactoryApp()
    app.mainloop()


if __name__ == "__main__":
    main()
