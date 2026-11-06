# -*- mode: python ; coding: utf-8 -*-

import os

datas = [('app.ico', '.'), ('app.png', '.'), ('trace.png', '.')]

extra_binaries = []
hiddenimports = []

a = Analysis(
    ['main.py'],
    pathex=[os.environ['STARTRACE_VENDOR']] if os.environ.get('STARTRACE_VENDOR') else [],
    binaries=extra_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['stanza', 'spacy', 'torch', 'matplotlib', 'scipy', 'pandas', 'tensorflow', 'IPython',
              'argostranslate', 'ctranslate2', 'sentencepiece', 'onnxruntime'],
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
    name='StarTrace',
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
    version='version_info.txt',
    icon=['app.ico'],
)
