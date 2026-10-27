"""Text and logo watermarks. Pure domain logic: Pillow only, no Qt.

Sizes are fractions of the image width, not pixels, so one setting
gives the same look on a 800px thumbnail and a 6000px photo, and the
downscaled UI preview matches the exported file.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from mediakit.modules.image.ops import Transform


class Position(StrEnum):
    TOP_LEFT = "tl"
    TOP = "t"
    TOP_RIGHT = "tr"
    LEFT = "l"
    CENTER = "c"
    RIGHT = "r"
    BOTTOM_LEFT = "bl"
    BOTTOM = "b"
    BOTTOM_RIGHT = "br"
    TILED = "tiled"


# Row-major 3x3 order, used by the UI grid.
GRID_POSITIONS: tuple[Position, ...] = (
    Position.TOP_LEFT, Position.TOP, Position.TOP_RIGHT,
    Position.LEFT, Position.CENTER, Position.RIGHT,
    Position.BOTTOM_LEFT, Position.BOTTOM, Position.BOTTOM_RIGHT,
)  # fmt: skip

# Fonts tried in order. Pillow searches the OS font folder for bare
# names on Windows. All of these cover Turkish characters.
_FONT_CANDIDATES = ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf", "Arial.ttf")


@lru_cache(maxsize=32)
def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    # Bundled scalable font (Pillow >= 10.1); last resort.
    return ImageFont.load_default(size=size)


def _anchor_xy(
    position: Position, canvas: tuple[int, int], item: tuple[int, int], margin: int
) -> tuple[int, int]:
    cw, ch = canvas
    iw, ih = item
    col = {"l": 0, "c": 1, "r": 2}
    row = {"t": 0, "c": 1, "b": 2}
    key = position.value
    r = row["t"] if key.startswith("t") else row["b"] if key.startswith("b") else row["c"]
    c = col["l"] if key.endswith("l") else col["r"] if key.endswith("r") else col["c"]
    x = (margin, (cw - iw) // 2, cw - iw - margin)[c]
    y = (margin, (ch - ih) // 2, ch - ih - margin)[r]
    return x, y


def _with_opacity(rgba: Image.Image, opacity: float) -> Image.Image:
    if opacity >= 1:
        return rgba
    alpha = rgba.getchannel("A").point(lambda a: round(a * opacity))
    out = rgba.copy()
    out.putalpha(alpha)
    return out


def _tile(base: Image.Image, stamp: Image.Image, angle: float = 30.0) -> Image.Image:
    """Repeat `stamp` diagonally over the whole image.

    Tiles are laid on a canvas one stamp larger on every side, then
    cropped back: stamps hanging off the edges are cut cleanly, with no
    negative-coordinate bookkeeping.
    """
    rotated = stamp.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
    sw, sh = rotated.size
    step_x, step_y = max(1, int(sw * 1.35)), max(1, int(sh * 1.5))
    width, height = base.width + 2 * sw, base.height + 2 * sh
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for row, y in enumerate(range(sh // 2, height - sh, step_y)):
        offset = step_x // 2 if row % 2 else 0
        for x in range(sw // 2 + offset, width - sw, step_x):
            canvas.alpha_composite(rotated, (x, y))
    return canvas.crop((sw, sh, sw + base.width, sh + base.height))


def _composite(image: Image.Image, overlay: Image.Image) -> Image.Image:
    """Blend an RGBA overlay, keeping the original mode family."""
    had_alpha = image.mode in ("RGBA", "LA", "P")
    base = image.convert("RGBA")
    base.alpha_composite(overlay)
    return base if had_alpha else base.convert("RGB")


def render_text_stamp(
    text: str, font_px: int, color: tuple[int, int, int], opacity: float
) -> Image.Image:
    """The text as an RGBA image with a soft outline for legibility."""
    font = _font(max(6, font_px))
    stroke = max(1, font_px // 18)
    # Outline in the opposite tone keeps text readable on any background.
    luminance = 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]
    outline = (0, 0, 0) if luminance > 128 else (255, 255, 255)

    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    left, top, right, bottom = probe.textbbox((0, 0), text, font=font, stroke_width=stroke)
    stamp = Image.new("RGBA", (right - left + 2, bottom - top + 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(stamp)
    draw.text(
        (-left + 1, -top + 1),
        text,
        font=font,
        fill=(*color, 255),
        stroke_width=stroke,
        stroke_fill=(*outline, 110),
    )
    return _with_opacity(stamp, opacity)


def make_text_watermark(
    text: str,
    position: Position = Position.BOTTOM_RIGHT,
    size: float = 0.05,
    opacity: float = 0.6,
    color: tuple[int, int, int] = (255, 255, 255),
    margin: float = 0.03,
) -> Transform:
    """`size` = font height as a fraction of image width."""
    text = text.strip()

    def apply(image: Image.Image) -> Image.Image:
        if not text:
            return image
        font_px = max(6, round(image.width * size))
        stamp = render_text_stamp(text, font_px, color, opacity)
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        if position == Position.TILED:
            overlay = _tile(image, stamp)
        else:
            gap = round(min(image.size) * margin)
            overlay.alpha_composite(stamp, _anchor_xy(position, image.size, stamp.size, gap))
        return _composite(image, overlay)

    return apply


def make_logo_watermark(
    logo_path: Path,
    position: Position = Position.BOTTOM_RIGHT,
    size: float = 0.2,
    opacity: float = 0.8,
    margin: float = 0.03,
) -> Transform:
    """`size` = logo width as a fraction of image width."""
    with Image.open(logo_path) as source:
        logo = source.convert("RGBA")

    def apply(image: Image.Image) -> Image.Image:
        target_w = max(1, round(image.width * size))
        target_h = max(1, round(logo.height * target_w / logo.width))
        stamp = _with_opacity(logo.resize((target_w, target_h), Image.Resampling.LANCZOS), opacity)
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        if position == Position.TILED:
            overlay = _tile(image, stamp, angle=0.0)
        else:
            gap = round(min(image.size) * margin)
            overlay.alpha_composite(stamp, _anchor_xy(position, image.size, stamp.size, gap))
        return _composite(image, overlay)

    return apply
