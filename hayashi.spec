# -*- mode: python ; coding: utf-8 -*-

import sys
import PyQt5
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# Qt plugins (platforms, imageformats) are needed so the GUI starts on Win/macOS.
qt_datas = collect_data_files('PyQt5', include_py_files=False)
hidden = collect_submodules('PyQt5')

block_cipher = None

a = Analysis(
    ['hayashi.py'],
    pathex=[],
    binaries=[],
    datas=qt_datas,         # include Qt plugin data
    hiddenimports=hidden + ['fitz', 'PyQt5.sip'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Hayashi',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # GUI app: no console window
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Hayashi'
)

# On macOS, wrap into a .app bundle so users can double-click it.
if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='Hayashi.app',
        icon=None,          # add an .icns if you want later
        bundle_identifier='org.hanenashi.hayashi',
        info_plist={
          'NSHighResolutionCapable': True
        }
    )
