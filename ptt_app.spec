# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Mic → Push-To-Talk (Multi-Mode)
Build with: pyinstaller ptt_app.spec
"""
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# Set up paths
spec_root = Path(os.getcwd())
icon_path = spec_root / "app" / "assets" / "icon.ico"
dist_path = str(spec_root / "dist")
build_path = str(spec_root / "build")

block_cipher = None

# Collect all submodules from the app package
hiddenimports = [
    'app.config',
    'app.ui.main_window',
    'app.ui.overlay',
    'app.ui.widgets',
    'app.audio.mic_monitor',
    'app.audio.sounds',
    'app.input.hotkeys',
    'app.core.controller',
    'app.core.profiles',
    'app.utils.helpers',
]

# Additional hidden imports for dependencies
hiddenimports.extend([
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'sounddevice',
    'numpy',
    'pynput',
    'pynput.keyboard',
])

a = Analysis(
    ['app/main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludedimports=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ptt_app',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Set to True if you want a console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path),
    distpath=dist_path,
    buildpath=build_path,
)
