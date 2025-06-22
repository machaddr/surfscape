# -*- mode: python ; coding: utf-8 -*-
import sys
from PyInstaller.utils.hooks import collect_data_files

# Collect data files for various packages
datas = []
datas += collect_data_files('PyQt6')

# Add any additional data files if needed
# datas += [('path/to/data', 'destination')]

a = Analysis(
    ['surfscape.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PyQt6.QtWebEngineWidgets',
        'PyQt6.QtWebEngineCore',
        'PyQt6.QtNetwork',
        'PyQt6.QtPrintSupport',
        'anthropic',
        'aiohttp',
        'speech_recognition',
        'pyaudio',
        'markdown',
        'adblockparser',
        'json',
        'asyncio',
        're',
        'os',
        'sys'
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='surfscape',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None  # Add icon path here if you have one: icon='icon.ico'
)

# For Linux/macOS app bundle (optional)
if sys.platform == 'darwin':
    app = BUNDLE(
        exe,
        name='Surfscape.app',
        icon=None,  # Add icon path here if you have one
        bundle_identifier='com.surfscape.browser',
        info_plist={
            'NSHighResolutionCapable': 'True',
            'NSRequiresAquaSystemAppearance': 'False'
        }
    )
