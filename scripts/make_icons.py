"""Draw the Sage Study app icon (a cream leaf on a sage rounded square) and write the
.png / .ico / .icns files the shortcuts need, plus the favicon used by the frontend.

    python scripts/make_icons.py
"""
from __future__ import annotations

import math
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "icon"
SIZE = 1024
SS = 4  # supersampling factor for smooth edges

BG_TOP = (125, 160, 131)     # lighter sage
BG_BOTTOM = (79, 111, 85)    # #4F6F55
LEAF = (244, 246, 241)       # #F4F6F1
VEIN = (107, 143, 113)       # #6B8F71


def lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def leaf_outline(base, tip, width, n=200):
    """Points of a leaf from base to tip: a lens shape whose half-width follows sin(pi*t)^0.8,
    skewed toward the base so it looks like a real leaf rather than a symmetric ellipse."""
    (bx, by), (tx, ty) = base, tip
    dx, dy = tx - bx, ty - by
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length
    px, py = -uy, ux  # perpendicular
    left, right = [], []
    for i in range(n + 1):
        t = i / n
        w = width * (math.sin(math.pi * t) ** 0.8) * (1 - 0.25 * t)
        cx, cy = bx + dx * t, by + dy * t
        left.append((cx + px * w, cy + py * w))
        right.append((cx - px * w, cy - py * w))
    return left + right[::-1]


def draw_icon() -> Image.Image:
    s = SIZE * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    # Rounded-square background with a vertical gradient.
    grad = Image.new("RGBA", (s, s))
    gd = ImageDraw.Draw(grad)
    for y in range(s):
        gd.line([(0, y), (s, y)], fill=lerp(BG_TOP, BG_BOTTOM, y / s) + (255,))
    mask = Image.new("L", (s, s), 0)
    margin = int(s * 0.06)
    ImageDraw.Draw(mask).rounded_rectangle([margin, margin, s - margin, s - margin], radius=int(s * 0.22), fill=255)
    img.paste(grad, (0, 0), mask)

    # Soft shadow under the leaf.
    base = (s * 0.27, s * 0.76)
    tip = (s * 0.76, s * 0.25)
    shadow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    off = s * 0.012
    sd.polygon([(x + off, y + off * 1.5) for x, y in leaf_outline(base, tip, s * 0.2)], fill=(30, 45, 33, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(s * 0.012))
    img = Image.alpha_composite(img, shadow)

    d = ImageDraw.Draw(img)
    d.polygon(leaf_outline(base, tip, s * 0.2), fill=LEAF + (255,))

    # Stem and midrib.
    stem_start = (s * 0.21, s * 0.82)
    d.line([stem_start, base], fill=LEAF + (255,), width=int(s * 0.03), joint="curve")
    d.ellipse([stem_start[0] - s * 0.015, stem_start[1] - s * 0.015, stem_start[0] + s * 0.015, stem_start[1] + s * 0.015], fill=LEAF + (255,))
    mid_end = (base[0] + (tip[0] - base[0]) * 0.88, base[1] + (tip[1] - base[1]) * 0.88)
    d.line([base, mid_end], fill=VEIN + (255,), width=int(s * 0.016))

    # Side veins.
    dx, dy = tip[0] - base[0], tip[1] - base[1]
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    for t, reach in ((0.28, 0.13), (0.48, 0.13), (0.66, 0.1)):
        cx, cy = base[0] + dx * t, base[1] + dy * t
        for side in (1, -1):
            ex = cx + (px * side * 0.85 + ux * 0.55) * s * reach
            ey = cy + (py * side * 0.85 + uy * 0.55) * s * reach
            d.line([(cx, cy), (ex, ey)], fill=VEIN + (255,), width=int(s * 0.011))

    return img.resize((SIZE, SIZE), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    icon = draw_icon()
    icon.save(OUT / "icon.png")
    icon.resize((256, 256), Image.LANCZOS).save(OUT / "icon-256.png")
    icon.save(OUT / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    icon.save(OUT / "icon.icns")
    public = ROOT / "frontend" / "public"
    public.mkdir(parents=True, exist_ok=True)
    icon.resize((128, 128), Image.LANCZOS).save(public / "icon.png")
    dist = ROOT / "frontend" / "dist"
    if dist.exists():
        shutil.copy(public / "icon.png", dist / "icon.png")
    print(f"Icons written to {OUT}")


if __name__ == "__main__":
    main()
