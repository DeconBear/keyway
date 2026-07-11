# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

import glob as _glob

# Collect web files from the keyway source package
_keyway_src = Path(SPECPATH).resolve().parent / "src" / "keyway"
_web_dir = _keyway_src / "web"

_web_files = []
for _f in _glob.glob(str(_web_dir / "**" / "*"), recursive=True):
    if Path(_f).is_file():
        # dest is the destination DIRECTORY (PyInstaller keeps the source basename);
        # using the full file path would create a spurious nested directory.
        _rel_parent = Path(_f).relative_to(_web_dir).parent
        _dest_dir = "keyway/web" if str(_rel_parent) == "." else str(Path("keyway/web") / _rel_parent)
        _web_files.append((_f, _dest_dir))

# Build the datas list: bundled icon + web assets
_datas = [
    (str(Path(SPECPATH) / "keyway.ico"), "."),  # (src, dest) tuple for Analysis
]
_datas.extend(_web_files)

_a = Analysis(
    [str(Path(SPECPATH) / "main.py")],
    pathex=[str(Path(SPECPATH).resolve().parent / "src")],
    binaries=[],
    datas=_datas,
    hiddenimports=[
        "keyway",
        "keyway.app",
        "keyway.config",
        "keyway.crypto",
        "keyway.llm_keys",
        "keyway.llm_router",
        "keyway.llm_store",
        "keyway.llm_tools",
        "keyway.models",
        "keyway.modality",
        "keyway.adapters",
        "keyway.fusion",
        "paths",
        "server",
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
    icon=str(Path(SPECPATH) / "keyway.ico"),
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
