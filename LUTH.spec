# -*- mode: python ; coding: utf-8 -*-
"""
LUTH — PyInstaller spec file
Builds a standalone Windows application (one-directory mode).
"""

import os

block_cipher = None
ROOT = os.path.abspath('.')

a = Analysis(
    ['app.py'],
    pathex=[ROOT],
    binaries=[],
    datas=[
        ('assets/luth.ico', 'assets'),
        ('assets/luth_64.png', 'assets'),
        ('assets/luth_logo.png', 'assets'),
        ('.env.example', '.'),
    ],
    hiddenimports=[
        'modules',
        'modules.concept_generator',
        'modules.music_generator',
        'modules.thumbnail_generator',
        'modules.video_creator',
        'modules.youtube_uploader',
        'modules.tiktok_uploader',
        'modules.audio_merger',
        'modules.os_scheduler',
        'utils',
        'utils.logger',
        'utils.browser',
        'utils.auto_setup',
        'config',
        'pipeline',
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
