# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['surfscape.py'],
    pathex=[],
    binaries=[],
    datas=[('icon/icon.png', 'icon')],
    hiddenimports=['multiprocessing.popen_spawn_posix','multiprocessing.popen_spawn_win32','multiprocessing.util'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['pyi_rth_multiprocessing'],
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
)
