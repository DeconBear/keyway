# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

_a = Analysis(
    [str(Path(__file__).parent / "main.py")],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        "keyway",
        "keyway.app",
        "keyway.config",
        "keyway.crypto",
        "keyway.llm_keys",
        "keyway.llm_protocol",
        "keyway.llm_router",
        "keyway.llm_store",
        "keyway.llm_tools",
        "keyway.models",
        "keyway.modality",
        "keyway.adapters",
        "keyway.fusion",
        "uvicorn",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "fastapi",
        "pydantic",
        "cryptography",
        "httpx",
        "PIL",
        "pystray",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

_pyz = PYZ(_a.pure)

_exe = EXE(
    _pyz,
    _a.scripts,
    _a.binaries,
    _a.datas,
    [],
    name="Keyway",
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

# Copy the src/keyway/web directory into the bundle
_keyway_src = Path(__file__).resolve().parents[1] / "src" / "keyway"
_web_dir = _keyway_src / "web"

import glob as _glob

_web_files = []
for _f in _glob.glob(str(_web_dir / "**" / "*"), recursive=True):
    if Path(_f).is_file():
        _web_files.append((_f, str(Path("keyway") / "web" / Path(_f).relative_to(_web_dir))))

_coll = COLLECT(
    _exe,
    _a.scripts,
    _a.binaries,
    _a.datas + _web_files,
    _a.pure,
    _a.zipfiles,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Keyway",
)
