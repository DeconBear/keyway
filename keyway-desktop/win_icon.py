"""Windows window / taskbar icon helpers for Keyway Desktop."""

from __future__ import annotations

import ctypes
import os
import sys
import time
from ctypes import POINTER, byref, c_long, c_void_p, sizeof, windll
from ctypes.wintypes import DWORD, HWND, LPCWSTR, WORD

HRESULT = c_long


APP_ID = "keyway.desktop.v1"

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
WM_SETICON = 0x0080
ICON_SMALL = 0
ICON_BIG = 1
GCLP_HICON = -14
GCLP_HICONSM = -34

user32 = windll.user32
shell32 = windll.shell32
ole32 = windll.ole32
LPVOID = c_void_p


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", DWORD),
        ("Data2", WORD),
        ("Data3", WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", DWORD)]


class PROPVARIANT(ctypes.Structure):
    """Enough of PROPVARIANT for string values (vt + reserved + pointer)."""

    _fields_ = [
        ("vt", WORD),
        ("wReserved1", WORD),
        ("wReserved2", WORD),
        ("wReserved3", WORD),
        ("data", c_void_p),
    ]


def _guid(data1: int, data2: int, data3: int, data4: bytes) -> GUID:
    g = GUID()
    g.Data1 = data1
    g.Data2 = data2
    g.Data3 = data3
    for i, b in enumerate(data4):
        g.Data4[i] = b
    return g


# {9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}
_FMTID_APPUSERMODEL = _guid(
    0x9F4C2855, 0x9F79, 0x4B39, bytes([0xA8, 0xD0, 0xE1, 0xD4, 0x2D, 0xE1, 0xD5, 0xF3])
)
PKEY_AppUserModel_ID = PROPERTYKEY(_FMTID_APPUSERMODEL, 5)
PKEY_AppUserModel_RelaunchCommand = PROPERTYKEY(_FMTID_APPUSERMODEL, 2)
PKEY_AppUserModel_RelaunchIconResource = PROPERTYKEY(_FMTID_APPUSERMODEL, 3)
PKEY_AppUserModel_RelaunchDisplayNameResource = PROPERTYKEY(_FMTID_APPUSERMODEL, 4)

IID_IPropertyStore = _guid(
    0x886D8EEB, 0x8CF2, 0x4446, bytes([0x8D, 0x02, 0xCD, 0xBA, 0x1D, 0xBD, 0xCF, 0x99])
)


def set_app_id(app_id: str = APP_ID) -> None:
    if sys.platform != "win32":
        return
    try:
        shell32.SetCurrentProcessExplicitAppUserModelID(ctypes.c_wchar_p(app_id))
    except Exception:
        pass


def _load_icon(path: str, size: int) -> int:
    user32.LoadImageW.argtypes = [LPVOID, LPCWSTR, DWORD, ctypes.c_int, ctypes.c_int, DWORD]
    user32.LoadImageW.restype = LPVOID
    handle = user32.LoadImageW(None, path, IMAGE_ICON, size, size, LR_LOADFROMFILE)
    return int(handle) if handle else 0


def _hicon_from_png(png_path: str, size: int) -> int:
    """Build an HICON from a PNG via Pillow (reliable for tray-quality marks)."""
    try:
        import io
        from PIL import Image
    except ImportError:
        return 0
    try:
        im = Image.open(png_path).convert("RGBA")
        im = im.resize((size, size), Image.Resampling.LANCZOS)
        # AND mask + XOR bitmap for CreateIconIndirect is painful;
        # use PNG compressed icon resource via CreateIconFromResourceEx.
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        data = buf.getvalue()
        CreateIconFromResourceEx = user32.CreateIconFromResourceEx
        CreateIconFromResourceEx.argtypes = [
            ctypes.c_void_p,
            DWORD,
            ctypes.c_bool,
            DWORD,
            ctypes.c_int,
            ctypes.c_int,
            DWORD,
        ]
        CreateIconFromResourceEx.restype = LPVOID
        ptr = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        h = CreateIconFromResourceEx(ptr, len(data), True, 0x00030000, size, size, 0)
        return int(h) if h else 0
    except Exception:
        return 0


def _window_title(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 511)
    return buf.value or ""


def _find_hwnds(pid: int | None = None) -> list[int]:
    pid = pid or os.getpid()
    found: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, HWND, LPVOID)
    def _enum(hwnd: int, _lparam: LPVOID) -> bool:
        proc = DWORD()
        user32.GetWindowThreadProcessId(hwnd, byref(proc))
        if proc.value != pid:
            return True
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetParent(hwnd):
            return True
        found.append(int(hwnd))
        return True

    user32.EnumWindows(_enum, None)
    keyed = [h for h in found if "Keyway" in _window_title(h)]
    return keyed or found


def _set_prop_store(hwnd: int, icon_path: str, app_id: str) -> bool:
    try:
        ole32.CoInitialize(None)
    except Exception:
        pass

    store = LPVOID()
    shell32.SHGetPropertyStoreForWindow.argtypes = [HWND, POINTER(GUID), POINTER(LPVOID)]
    shell32.SHGetPropertyStoreForWindow.restype = HRESULT
    hr = shell32.SHGetPropertyStoreForWindow(hwnd, byref(IID_IPropertyStore), byref(store))
    if hr != 0 or not store:
        return False

    vtbl = ctypes.cast(ctypes.cast(store, POINTER(LPVOID))[0], POINTER(LPVOID))
    SetValue = ctypes.WINFUNCTYPE(HRESULT, LPVOID, POINTER(PROPERTYKEY), POINTER(PROPVARIANT))(vtbl[6])
    Commit = ctypes.WINFUNCTYPE(HRESULT, LPVOID)(vtbl[7])
    Release = ctypes.WINFUNCTYPE(DWORD, LPVOID)(vtbl[2])

    try:
        propsys = windll.propsys
        InitPropVariantFromString = propsys.InitPropVariantFromString
        InitPropVariantFromString.argtypes = [LPCWSTR, POINTER(PROPVARIANT)]
        InitPropVariantFromString.restype = HRESULT
        PropVariantClear = ole32.PropVariantClear
        PropVariantClear.argtypes = [POINTER(PROPVARIANT)]
    except Exception:
        Release(store)
        return False

    abs_icon = os.path.abspath(icon_path)
    # Relaunch command keeps a distinct taskbar identity when running under python.exe
    if getattr(sys, "frozen", False):
        relaunch = f'"{sys.executable}"'
    else:
        main_py = os.path.join(os.path.dirname(abs_icon), "main.py")
        if not os.path.exists(main_py):
            main_py = os.path.abspath(os.path.join(os.path.dirname(__file__), "main.py"))
        relaunch = f'"{sys.executable}" "{main_py}"'

    pairs = [
        (PKEY_AppUserModel_ID, app_id),
        (PKEY_AppUserModel_RelaunchIconResource, f"{abs_icon},0"),
        (PKEY_AppUserModel_RelaunchDisplayNameResource, "Keyway"),
        (PKEY_AppUserModel_RelaunchCommand, relaunch),
    ]
    ok = True
    for key, value in pairs:
        pv = PROPVARIANT()
        if InitPropVariantFromString(value, byref(pv)) != 0:
            ok = False
            continue
        if SetValue(store, byref(key), byref(pv)) != 0:
            ok = False
        PropVariantClear(byref(pv))
    Commit(store)
    Release(store)
    return ok


def apply_window_icons(
    icon_path: str,
    *,
    png_path: str | None = None,
    app_id: str = APP_ID,
) -> int:
    """Apply icon to top-level process windows. Returns HWND count updated."""
    if sys.platform != "win32":
        return 0
    if not icon_path or not os.path.exists(icon_path):
        return 0

    set_app_id(app_id)
    abs_icon = os.path.abspath(icon_path)

    h_big = _load_icon(abs_icon, 32) or _load_icon(abs_icon, 256)
    h_small = _load_icon(abs_icon, 16) or h_big

    if png_path and os.path.exists(png_path):
        h_big = _hicon_from_png(png_path, 32) or h_big
        h_small = _hicon_from_png(png_path, 16) or h_small or h_big

    if not h_big:
        user32.LoadImageW.restype = LPVOID
        h_big = int(user32.LoadImageW(None, abs_icon, IMAGE_ICON, 0, 0, LR_LOADFROMFILE) or 0)
        h_small = h_big
    if not h_big:
        return 0

    hwnds = _find_hwnds()
    if not hwnds:
        return 0

    set_class_long = user32.SetClassLongPtrW if sizeof(c_void_p) == 8 else user32.SetClassLongW
    set_class_long.restype = LPVOID

    updated = 0
    for hwnd in hwnds:
        try:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, h_big)
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, h_small or h_big)
            set_class_long(hwnd, GCLP_HICON, h_big)
            set_class_long(hwnd, GCLP_HICONSM, h_small or h_big)
            _set_prop_store(hwnd, abs_icon, app_id)
            user32.InvalidateRect(hwnd, None, True)
            updated += 1
        except Exception:
            continue
    return updated


def apply_icons_with_retry(
    icon_path: str,
    *,
    png_path: str | None = None,
    attempts: int = 40,
    delay: float = 0.35,
    app_id: str = APP_ID,
) -> None:
    set_app_id(app_id)
    for i in range(attempts):
        n = apply_window_icons(icon_path, png_path=png_path, app_id=app_id)
        if n > 0 and i >= 3:
            # WebView2 sometimes overwrites the icon after first paint
            for wait in (0.6, 1.2, 2.0):
                time.sleep(wait)
                apply_window_icons(icon_path, png_path=png_path, app_id=app_id)
            print(f"[desktop] applied window icon to {n} hwnd(s)", flush=True)
            return
        time.sleep(delay)
    print("[desktop] WARNING: could not apply window icon (no hwnd yet)", flush=True)
