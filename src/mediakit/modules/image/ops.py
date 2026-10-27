"""Image transform operations. Pure domain logic: Pillow only, no Qt.

Each operation is a `Transform`: a callable taking an Image and
returning an Image. `convert.py` composes a list of them into the
decode -> transform -> encode pipeline.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from PIL import Image, ImageOps

Transform = Callable[[Image.Image], Image.Image]


class ResizeMode(StrEnum):
    NONE = "none"
    MAX_WIDTH = "max_width"  # cap width, height follows aspect ratio
    MAX_HEIGHT = "max_height"  # cap height, width follows aspect ratio
    FIT_BOX = "fit_box"  # fit inside width x height, keep aspect
    PERCENT = "percent"  # scale both dimensions by a percentage


class Rotation(StrEnum):
    NONE = "none"
    CW_90 = "cw_90"
    ROT_180 = "rot_180"
    CCW_90 = "ccw_90"


# Pillow resampling filter. LANCZOS is the quality choice for
# downscaling (most common case here); BILINEAR/NEAREST are faster but
# visibly softer or aliased.
_RESAMPLE = Image.Resampling.LANCZOS


def auto_orient(image: Image.Image) -> Image.Image:
    """Apply the EXIF orientation tag and drop it.

    Phone cameras often store the image rotated with an orientation tag
    rather than rotating the pixels. Viewers honour the tag; a naive
    re-encode does not, so photos silently come out sideways. This bakes
    the rotation into the pixels.
    """
    return ImageOps.exif_transpose(image)


def make_resize(
    mode: ResizeMode,
    width: int | None = None,
    height: int | None = None,
    percent: int | None = None,
    allow_upscale: bool = False,
) -> Transform:
    """Build a resize transform. Aspect ratio is always preserved."""

    def resize(image: Image.Image) -> Image.Image:
        w, h = image.size
        if w == 0 or h == 0:
            return image

        if mode == ResizeMode.NONE:
            return image

        if mode == ResizeMode.PERCENT:
            if not percent or percent <= 0:
                return image
            target_w = max(1, round(w * percent / 100))
            target_h = max(1, round(h * percent / 100))

        elif mode == ResizeMode.MAX_WIDTH:
            if not width or width <= 0:
                return image
            if w <= width and not allow_upscale:
                return image
            target_w = width
            target_h = max(1, round(h * width / w))

        elif mode == ResizeMode.MAX_HEIGHT:
            if not height or height <= 0:
                return image
            if h <= height and not allow_upscale:
                return image
            target_h = height
            target_w = max(1, round(w * height / h))

        elif mode == ResizeMode.FIT_BOX:
            if not width or not height or width <= 0 or height <= 0:
                return image
            # Scale by whichever dimension is the tighter constraint.
            scale = min(width / w, height / h)
            if scale >= 1 and not allow_upscale:
                return image
            target_w = max(1, round(w * scale))
            target_h = max(1, round(h * scale))

        else:
            return image

        if (target_w, target_h) == (w, h):
            return image
        return image.resize((target_w, target_h), _RESAMPLE)

    return resize


def make_rotate(rotation: Rotation) -> Transform:
    """Build a rotation transform.

    Uses `transpose` with fixed 90-degree steps rather than `rotate`:
    it is lossless pixel reordering, no resampling, no new edge pixels.
    """
    ops = {
        Rotation.CW_90: Image.Transpose.ROTATE_270,  # PIL rotates CCW
        Rotation.ROT_180: Image.Transpose.ROTATE_180,
        Rotation.CCW_90: Image.Transpose.ROTATE_90,
    }

    def rotate(image: Image.Image) -> Image.Image:
        op = ops.get(rotation)
        if op is None:
            return image
        return image.transpose(op)

    return rotate


def rotation_from_steps(steps: int) -> Rotation:
    """Map a count of clockwise quarter turns to a Rotation."""
    return {
        0: Rotation.NONE,
        1: Rotation.CW_90,
        2: Rotation.ROT_180,
        3: Rotation.CCW_90,
    }[steps % 4]


# ------------------------------------------------------------------ crop


@dataclass(frozen=True)
class AspectRatio:
    """A target width:height ratio, e.g. AspectRatio(16, 9)."""

    w: int
    h: int

    @property
    def key(self) -> str:
        return f"{self.w}:{self.h}"

    @property
    def value(self) -> float:
        return self.w / self.h


# Landscape presets followed by their portrait counterparts.
ASPECT_PRESETS: tuple[AspectRatio, ...] = (
    AspectRatio(1, 1),
    AspectRatio(4, 3),
    AspectRatio(3, 4),
    AspectRatio(16, 9),
    AspectRatio(9, 16),
    AspectRatio(21, 9),
    AspectRatio(9, 21),
)


def center_crop_box(size: tuple[int, int], ratio: AspectRatio) -> tuple[int, int, int, int]:
    """Largest box of `ratio` that fits in `size`, centred. (l, t, r, b)."""
    w, h = size
    target = ratio.value
    if w / h > target:
        # Too wide: keep full height, trim the sides.
        new_w = max(1, round(h * target))
        left = (w - new_w) // 2
        return (left, 0, left + new_w, h)
    # Too tall (or exact): keep full width, trim top and bottom.
    new_h = max(1, round(w / target))
    top = (h - new_h) // 2
    return (0, top, w, top + new_h)


def make_center_crop(ratio: AspectRatio) -> Transform:
    """Batch-friendly crop: same ratio for every image, centred."""

    def crop(image: Image.Image) -> Image.Image:
        box = center_crop_box(image.size, ratio)
        if box == (0, 0, *image.size):
            return image
        return image.crop(box)

    return crop


def make_crop_fraction(left: float, top: float, right: float, bottom: float) -> Transform:
    """Crop by a box given as fractions (0..1) of the image size.

    Fractions rather than pixels: the UI shows a downscaled preview, and
    fractions mean the same thing on the preview and the full image.
    """
    x0, y0 = max(0.0, min(left, right)), max(0.0, min(top, bottom))
    x1, y1 = min(1.0, max(left, right)), min(1.0, max(top, bottom))

    def crop(image: Image.Image) -> Image.Image:
        w, h = image.size
        box = (round(x0 * w), round(y0 * h), round(x1 * w), round(y1 * h))
        # Guarantee at least a 1x1 result.
        box = (box[0], box[1], max(box[0] + 1, box[2]), max(box[1] + 1, box[3]))
        if box == (0, 0, w, h):
            return image
        return image.crop(box)

    return crop


def apply_all(image: Image.Image, transforms: list[Transform]) -> Image.Image:
    """Run transforms left to right."""
    for transform in transforms:
        image = transform(image)
    return image
