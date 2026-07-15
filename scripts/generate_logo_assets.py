"""Generate Keyway logo ICO/PNG assets from a crisp geometric mark."""

from __future__ import annotations

import math
import shutil
import struct
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SRC = Path(
    r"C:\Users\qzx\.cursor\projects\e-BaiduSyncdisk-research-Programming-Development-prodev-klynx-dev-Keyway"
    r"\assets\keyway-logo-source.png"
)
WEB = ROOT / "src" / "keyway" / "web" / "assets"
DESK = ROOT / "keyway-desktop"
DESK_ASSETS = DESK / "assets"


def draw_logo(size: int, *, with_bg: bool = True) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if with_bg:
        radius = max(2, int(size * 0.22))
        draw.rounded_rectangle(
            (0, 0, size - 1, size - 1),
            radius=radius,
            fill=(247, 245, 242, 255),
        )
    ink = (17, 17, 17, 255)
    s = size / 100.0
    stroke = max(2, int(9.5 * s))
    cx, cy, r = 50 * s, 32 * s, 14 * s
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=ink, width=stroke)
    x = 50 * s
    y1, y2 = 46 * s, 62 * s
    draw.line([(x, y1), (x, y2)], fill=ink, width=stroke)
    left = (28 * s, 84 * s)
    right = (72 * s, 84 * s)
    mid = (x, y2)
    draw.line([mid, left], fill=ink, width=stroke)
    draw.line([mid, right], fill=ink, width=stroke)
    ah = max(3, int(7 * s))

    def arrow(tip: tuple[float, float], back_dir: tuple[float, float]) -> None:
        tx, ty = tip
        dx, dy = back_dir
        length = math.hypot(dx, dy) or 1.0
        dx, dy = dx / length, dy / length
        bx, by = tx - dx * ah * 1.4, ty - dy * ah * 1.4
        px, py = -dy * ah * 0.85, dx * ah * 0.85
        draw.polygon([(tx, ty), (bx + px, by + py), (bx - px, by - py)], fill=ink)

    arrow(left, (50 * s - left[0], 62 * s - left[1]))
    arrow(right, (50 * s - right[0], 62 * s - right[1]))
    return img


def write_ico(path: Path, sizes: list[int], *, with_bg: bool = True) -> None:
    """Write a multi-resolution ICO with embedded PNG images (Vista+)."""
    import io

    png_blobs: list[tuple[int, bytes]] = []
    for size in sizes:
        buf = io.BytesIO()
        draw_logo(size, with_bg=with_bg).save(buf, format="PNG")
        png_blobs.append((size, buf.getvalue()))

    # ICONDIR + ICONDIRENTRY * n + image data
    count = len(png_blobs)
    header = struct.pack("<HHH", 0, 1, count)
    offset = 6 + 16 * count
    entries = b""
    data = b""
    for size, blob in png_blobs:
        w = 0 if size >= 256 else size
        h = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(blob), offset)
        data += blob
        offset += len(blob)
    path.write_bytes(header + entries + data)


def main() -> None:
    WEB.mkdir(parents=True, exist_ok=True)
    DESK_ASSETS.mkdir(parents=True, exist_ok=True)

    draw_logo(512, with_bg=True).save(WEB / "logo.png")
    draw_logo(192, with_bg=True).save(WEB / "logo-192.png")
    draw_logo(64, with_bg=False).save(WEB / "logo-mark.png")

    draw_logo(512, with_bg=True).save(DESK_ASSETS / "logo.png")
    draw_logo(256, with_bg=False).save(DESK_ASSETS / "logo-mark.png")
    if SRC.exists():
        shutil.copy2(SRC, DESK_ASSETS / "logo-source.png")

    write_ico(DESK / "keyway.ico", [16, 24, 32, 48, 64, 128, 256], with_bg=True)
    write_ico(WEB / "favicon.ico", [16, 32, 48], with_bg=True)

    # cleanup temp
    test = DESK / "_test.png"
    if test.exists():
        test.unlink()

    print("OK ico", (DESK / "keyway.ico").stat().st_size, "bytes")
    print("OK web", WEB / "favicon.ico", WEB / "logo.png", WEB / "logo.svg")


if __name__ == "__main__":
    main()
