"""Generate the earmark logo assets from static/logo-source.png.

Run with the pillow/numpy/scipy deps fetched on the fly (nothing is added to
the project venv):

    uv run --with pillow --with numpy --with scipy \
        src/frontend/scripts/process_logo.py

Produces, in src/frontend/static/:
  favicon.png            32x32   dog mark
  apple-touch-icon.png   180x180 dog mark
  logo-mark.png          96x96   dog mark (navbar)
  logo-light.png         full logo, original colors (light themes)
  logo-dark.png          full logo, dark wordmark recolored light (dark themes)

The source has a solid white background. We remove only the white that is
connected to the image border so the dog's enclosed white body is preserved.
"""

from __future__ import annotations

import os

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.normpath(os.path.join(HERE, "..", "static"))
SOURCE = os.path.join(STATIC, "logo-source.png")
PREVIEW_DIR = os.environ.get("CLAUDE_JOB_DIR")
PREVIEW_DIR = os.path.join(PREVIEW_DIR, "tmp") if PREVIEW_DIR else None


def load_rgba_with_transparent_bg(path: str) -> Image.Image:
    """Load the source and knock out the border-connected white background."""
    rgb = np.asarray(Image.open(path).convert("RGB")).astype(np.int16)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]

    # Near-white: bright in every channel and nearly grey (low saturation).
    maxc = rgb.max(axis=2)
    minc = rgb.min(axis=2)
    near_white = (minc > 240) & ((maxc - minc) < 12)

    # Keep only near-white blobs that touch the image border (the outer bg);
    # enclosed white (the dog's body) is a separate component and survives.
    labels, n = ndimage.label(near_white)
    border = set(labels[0, :]) | set(labels[-1, :]) | set(labels[:, 0]) | set(labels[:, -1])
    border.discard(0)
    bg = np.isin(labels, list(border))

    alpha = np.where(bg, 0, 255).astype(np.uint8)
    out = np.dstack([rgb.astype(np.uint8), alpha])
    img = Image.fromarray(out, "RGBA")

    # Soften the cut edge by 1px so it isn't aliased.
    a = img.getchannel("A").filter(ImageFilter.GaussianBlur(0.6))
    img.putalpha(a)
    return img


def trim(img: Image.Image, pad: int = 8) -> Image.Image:
    bbox = img.getchannel("A").getbbox()
    if not bbox:
        return img
    left, top, right, bottom = bbox
    left = max(0, left - pad)
    top = max(0, top - pad)
    right = min(img.width, right + pad)
    bottom = min(img.height, bottom + pad)
    return img.crop((left, top, right, bottom))


def split_dog_and_wordmark(img: Image.Image) -> int:
    """Return the y row of the gap between the dog and the 'earmark' wordmark.

    Scans the lower half for the widest run of fully-transparent rows and
    returns its midpoint.
    """
    alpha = np.asarray(img.getchannel("A"))
    row_has_ink = (alpha > 16).any(axis=1)
    h = img.height
    best = (0, 0, h)  # (length, start, mid)
    run_start = None
    for y in range(h // 2, h):
        if not row_has_ink[y]:
            if run_start is None:
                run_start = y
        else:
            if run_start is not None:
                length = y - run_start
                if length > best[0]:
                    best = (length, run_start, run_start + length // 2)
                run_start = None
    return best[2]


def recolor_dark_wordmark(img: Image.Image, gap_y: int, light=(236, 236, 236)) -> Image.Image:
    """In the wordmark region (below gap_y), turn dark grey/black ink light.

    Red ink (the 'ear' letters) is left untouched.
    """
    arr = np.asarray(img).copy()
    region = arr[gap_y:, :, :]
    r = region[..., 0].astype(np.int16)
    g = region[..., 1].astype(np.int16)
    b = region[..., 2].astype(np.int16)
    a = region[..., 3]
    maxc = np.maximum(np.maximum(r, g), b)
    minc = np.minimum(np.minimum(r, g), b)
    is_dark = (maxc < 110) & ((maxc - minc) < 40) & (a > 16)
    # blend toward light proportionally to opacity so anti-aliased edges stay smooth
    for i, val in enumerate(light):
        region[..., i] = np.where(is_dark, val, region[..., i])
    arr[gap_y:, :, :] = region
    return Image.fromarray(arr, "RGBA")


def clear_wordmark_counters(img: Image.Image, gap_y: int) -> Image.Image:
    """Make enclosed white letter counters in the wordmark transparent.

    The border flood-fill in load_rgba_with_transparent_bg can't reach white
    that is enclosed by letter strokes (the eye of the 'e', the bowls of the
    'a's), so those stay opaque. The wordmark region (below gap_y) has no
    intended white fill, so any near-white grey here is background: fade its
    alpha out, linearly across a small band so edges stay smooth. Must run
    before recolor_dark_wordmark so it applies to both variants.
    """
    arr = np.asarray(img).copy().astype(np.int16)
    region = arr[gap_y:, :, :]
    r, g, b = region[..., 0], region[..., 1], region[..., 2]
    minc = np.minimum(np.minimum(r, g), b)
    maxc = np.maximum(np.maximum(r, g), b)
    greyish = (maxc - minc) < 30
    # minc>=245 -> fully transparent, <=200 -> opaque, linear between.
    factor = np.clip((245 - minc) / 45.0, 0.0, 1.0)
    factor = np.where(greyish, factor, 1.0)
    region[..., 3] = np.minimum(region[..., 3], (factor * 255).astype(np.int16))
    arr[gap_y:, :, :] = region
    return Image.fromarray(arr.astype(np.uint8), "RGBA")


def square_pad(img: Image.Image) -> Image.Image:
    side = max(img.width, img.height)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.alpha_composite(img, ((side - img.width) // 2, (side - img.height) // 2))
    return canvas


def save(img: Image.Image, name: str) -> None:
    path = os.path.join(STATIC, name)
    img.save(path)
    print(f"wrote {path} ({img.width}x{img.height})")


def write_previews(assets: dict[str, Image.Image]) -> None:
    if not PREVIEW_DIR:
        return
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    for bg_name, bg in (("light", (245, 245, 245)), ("dark", (21, 21, 26))):
        for name, img in assets.items():
            canvas = Image.new("RGB", img.size, bg)
            canvas.paste(img, (0, 0), img)
            out = os.path.join(PREVIEW_DIR, f"preview_{name.replace('.png','')}_{bg_name}.png")
            canvas.save(out)
            print(f"wrote {out}")


def main() -> None:
    full = trim(load_rgba_with_transparent_bg(SOURCE))
    gap_y = split_dog_and_wordmark(full)
    full = clear_wordmark_counters(full, gap_y)

    # Full logo variants
    logo_light = full
    logo_dark = recolor_dark_wordmark(full, gap_y)

    target_w = 600
    scale = target_w / logo_light.width
    size = (target_w, round(logo_light.height * scale))
    logo_light = logo_light.resize(size, Image.LANCZOS)
    logo_dark = logo_dark.resize(size, Image.LANCZOS)
    save(logo_light, "logo-light.png")
    save(logo_dark, "logo-dark.png")

    # Dog mark (navbar): full dog cropped above the gap, square-padded.
    dog = trim(square_pad(full.crop((0, 0, full.width, gap_y))))
    dog = square_pad(dog)
    save(dog.resize((96, 96), Image.LANCZOS), "logo-mark.png")

    # Favicon / touch icon: a tight crop of the dog's head reads far better at
    # tab size than the busy full-body dog. Fractions of the trimmed full-dog.
    dw, dh = dog.size
    head = trim(dog.crop((int(dw * 0.20), int(dh * 0.04), int(dw * 0.82), int(dh * 0.66))))
    head = square_pad(head)
    save(head.resize((180, 180), Image.LANCZOS), "apple-touch-icon.png")
    fav32 = head.resize((32, 32), Image.LANCZOS)
    save(fav32, "favicon.png")
    # Multi-size .ico so browsers that auto-request /favicon.ico get a real icon.
    head.resize((48, 48), Image.LANCZOS).save(
        os.path.join(STATIC, "favicon.ico"), sizes=[(16, 16), (32, 32), (48, 48)]
    )
    print(f"wrote {os.path.join(STATIC, 'favicon.ico')} (16/32/48)")

    write_previews(
        {
            "logo-light.png": logo_light,
            "logo-dark.png": logo_dark,
            "logo-mark.png": dog.resize((96, 96), Image.LANCZOS),
            "favicon.png": fav32,
        }
    )


if __name__ == "__main__":
    main()
