# -*- mode: python ; coding: utf-8 -*-
"""
LUTH — PyInstaller spec file
Builds a standalone Windows application (one-directory mode).
Includes all Python dependencies, Playwright driver, and FFmpeg.
"""

import os
import shutil
from PyInstaller.utils.hooks import copy_metadata

block_cipher = None
ROOT = os.path.abspath('.')

# Collect package metadata so importlib.metadata can find them at runtime
_extra_datas = []
for _pkg in ['openai', 'packaging']:
    try:
        _extra_datas += copy_metadata(_pkg)
    except Exception:
        pass

# Bundle Playwright's driver so frozen app can install/run Chromium
import playwright
_pw_driver_dir = os.path.join(os.path.dirname(playwright.__file__), 'driver')

# Bundle FFmpeg if found in bin/ or PATH
_extra_binaries = []
_ffmpeg = shutil.which('ffmpeg') or os.path.join(ROOT, 'bin', 'ffmpeg.exe')
_ffprobe = shutil.which('ffprobe') or os.path.join(ROOT, 'bin', 'ffprobe.exe')
if os.path.isfile(_ffmpeg):
    _extra_binaries.append((_ffmpeg, 'bin'))
if os.path.isfile(_ffprobe):
    _extra_binaries.append((_ffprobe, 'bin'))

a = Analysis(
    ['app.py'],
    pathex=[ROOT],
    binaries=_extra_binaries,
    datas=[
        ('assets/luth.ico', 'assets'),
        ('assets/luth_64.png', 'assets'),
        ('assets/luth_logo.png', 'assets'),
        ('.env.example', '.'),
        (_pw_driver_dir, 'playwright/driver'),
    ] + _extra_datas,
    hiddenimports=[
        # App modules
        'modules',
        'modules.concept_generator',
        'modules.music_generator',
        'modules.suno_generator',
        'modules.udio_generator',
        'modules.thumbnail_generator',
        'modules.video_creator',
        'modules.youtube_uploader',
        'modules.tiktok_uploader',
        'modules.audio_merger',
        'modules.os_scheduler',
        'modules.updater',
        'utils',
        'utils.logger',
        'utils.browser',
        'utils.auto_setup',
        'config',
        'pipeline',
        # Playwright
        'playwright',
        'playwright.sync_api',
        'playwright._impl._driver',
        # OpenAI
        'openai',
        # Pillow
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'PIL.ImageFont',
        # Google API (YouTube upload)
        'google.oauth2.credentials',
        'google_auth_oauthlib.flow',
        'google.auth.transport.requests',
        'googleapiclient.discovery',
        'googleapiclient.http',
        # Other
        'requests',
        'dotenv',
        'packaging',
        'packaging.version',
        'apscheduler',
        'apscheduler.schedulers.background',
        # Tkinter
        'tkinter',
        'tkinter.ttk',
        'tkinter.scrolledtext',
        'tkinter.messagebox',
        'tkinter.filedialog',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='LUTH',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # No console window (GUI app)
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon='assets/luth.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='LUTH',
)
