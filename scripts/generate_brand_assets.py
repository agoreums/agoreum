#!/usr/bin/env python3
"""
Generate Agoreum's production branding asset set from the official logo.

Source of truth: brand/logo.png (transparent-background mark).
This script is idempotent and safe to re-run; it never modifies the sources.

Outputs (apps/web/public/):
  favicon.ico                 (16/32/48 multi-size)
  icons/favicon-16x16.png
  icons/favicon-32x32.png
  icons/apple-touch-icon.png  (180x180)
  icons/android-chrome-192x192.png
  icons/android-chrome-512x512.png
  icons/maskable-512x512.png  (Android maskable, safe-zone padded)
  icons/mark.png              (trimmed transparent mark master, 1024)
  icons/og-image.png          (1200x630 social / Open Graph)
  icons/twitter-image.png     (1200x600 X / Twitter card)
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "brand" / "logo.png"
PUBLIC = ROOT / "apps" / "web" / "public"
ICONS = PUBLIC / "icons"
ICONS.mkdir(parents=True, exist_ok=True)

# Brand palette (derived from the official mark)
INDIGO = (91, 99, 241)          # peak mark blue
BG_DARK = (10, 10, 18)          # near-black icon/background field
BG_DARK2 = (20, 22, 48)         # gradient partner

def load_mark() -> Image.Image:
    """Return the mark trimmed to its opaque bounding box, on transparency."""
    im = Image.open(SRC).convert("RGBA")
    alpha = im.getchannel("A")
    bbox = alpha.point(lambda a: 255 if a > 40 else 0).getbbox()
    return im.crop(bbox)

def square_canvas(mark: Image.Image, size: int, bg, pad_ratio: float) -> Image.Image:
    """Center the mark on a solid square background with given padding."""
    canvas = Image.new("RGBA", (size, size), bg + (255,))
    inner = int(size * (1 - 2 * pad_ratio))
    m = mark.copy()
    m.thumbnail((inner, inner), Image.LANCZOS)
    x = (size - m.width) // 2
    y = (size - m.height) // 2
    canvas.alpha_composite(m, (x, y))
    return canvas

def transparent_square(mark: Image.Image, size: int, pad_ratio: float) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    inner = int(size * (1 - 2 * pad_ratio))
    m = mark.copy()
    m.thumbnail((inner, inner), Image.LANCZOS)
    canvas.alpha_composite(m, ((size - m.width) // 2, (size - m.height) // 2))
    return canvas

def vertical_gradient(size, top, bottom):
    w, h = size
    base = Image.new("RGB", (w, h), top)
    top_img = Image.new("RGB", (w, h), bottom)
    mask = Image.new("L", (w, h))
    md = mask.load()
    for y in range(h):
        v = int(255 * (y / max(1, h - 1)))
        for x in range(w):
            md[x, y] = v
    base.paste(top_img, (0, 0), mask)
    return base

def load_font(size):
    candidates = [
        "C:/Windows/Fonts/segoeuisb.ttf",  # Segoe UI Semibold
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for c in candidates:
        if Path(c).exists():
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                continue
    return ImageFont.load_default()

def social_image(mark, out, w, h):
    """Compose a premium social card: gradient field, glow, mark, wordmark."""
    card = vertical_gradient((w, h), BG_DARK2, BG_DARK).convert("RGBA")

    # subtle radial indigo glow behind the mark
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    cx = int(w * 0.30)
    cy = int(h * 0.5)
    R = int(h * 0.42)
    gd.ellipse([cx - R, cy - R, cx + R, cy + R], fill=INDIGO + (90,))
    glow = glow.filter(ImageFilter.GaussianBlur(80))
    card.alpha_composite(glow)

    # mark on the left
    m = mark.copy()
    target = int(h * 0.52)
    m.thumbnail((target, target), Image.LANCZOS)
    mx = int(w * 0.30) - m.width // 2
    my = (h - m.height) // 2
    card.alpha_composite(m, (mx, my))

    # wordmark + tagline on the right
    d = ImageDraw.Draw(card)
    title_font = load_font(int(h * 0.16))
    sub_font = load_font(int(h * 0.052))
    tx = int(w * 0.50)
    d.text((tx, int(h * 0.34)), "Agoreum", font=title_font, fill=(245, 245, 255, 255))
    d.text((tx, int(h * 0.56)), "The Autonomous Agent Commerce Hub",
           font=sub_font, fill=(170, 176, 210, 255))
    card.convert("RGB").save(out, "PNG")

def main():
    mark = load_mark()
    print(f"Loaded mark: {mark.size}")

    # Master transparent mark
    transparent_square(mark, 1024, 0.06).save(ICONS / "mark.png")

    # Favicons (transparent, tight padding for legibility at small sizes)
    transparent_square(mark, 16, 0.04).save(ICONS / "favicon-16x16.png")
    transparent_square(mark, 32, 0.04).save(ICONS / "favicon-32x32.png")

    # Apple touch icon, Apple ignores transparency, needs solid bg
    square_canvas(mark, 180, BG_DARK, 0.14).save(ICONS / "apple-touch-icon.png")

    # Android chrome (transparent-friendly PWA icons)
    square_canvas(mark, 192, BG_DARK, 0.12).save(ICONS / "android-chrome-192x192.png")
    square_canvas(mark, 512, BG_DARK, 0.12).save(ICONS / "android-chrome-512x512.png")

    # Maskable icon, extra safe-zone padding (mark within center ~60%)
    square_canvas(mark, 512, BG_DARK, 0.22).save(ICONS / "maskable-512x512.png")

    # Multi-size ICO
    ico_src = square_canvas(mark, 256, BG_DARK, 0.10)
    ico_src.save(PUBLIC / "favicon.ico",
                 sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])

    # Social preview images
    social_image(mark, ICONS / "og-image.png", 1200, 630)
    social_image(mark, ICONS / "twitter-image.png", 1200, 600)

    print("All brand assets generated.")

if __name__ == "__main__":
    main()
