"""Image format conversion. Pure domain logic: Pillow only, no Qt."""

from __future__ import annotations

from functools import partial
from pathlib import Path

from PIL import Image

from mediakit.core.batch import WorkFn
from mediakit.core.paths import ConflictPolicy, resolve_output_path
from mediakit.modules.image.ops import Transform, apply_all

# What we can read vs. what we can write. Not symmetric on purpose:
# reading a format is cheap, writing it well is not.
INPUT_EXTENSIONS: set[str] = {"jpg", "jpeg", "png", "webp", "bmp", "tif", "tiff", "gif"}
OUTPUT_FORMATS: tuple[str, ...] = ("png", "jpg", "webp")

# Pillow's format identifiers differ from file extensions.
_PIL_FORMAT = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}

# Formats with no alpha channel: transparency must be flattened first,
# otherwise the alpha area is written as black.
_NO_ALPHA = {"JPEG"}

DEFAULT_BACKGROUND = (255, 255, 255)


def flatten_alpha(image: Image.Image, background: tuple[int, int, int]) -> Image.Image:
    """Composite a transparent image onto a solid background."""
    rgba = image.convert("RGBA")
    canvas = Image.new("RGB", rgba.size, background)
    # The alpha channel is used as the paste mask.
    canvas.paste(rgba, mask=rgba.split()[-1])
    return canvas


def convert_image(
    source: Path,
    destination: Path,
    quality: int = 90,
    background: tuple[int, int, int] = DEFAULT_BACKGROUND,
    transforms: list[Transform] | None = None,
) -> Path:
    """Decode `source`, re-encode it to `destination`'s format."""
    ext = destination.suffix.lower().lstrip(".")
    pil_format = _PIL_FORMAT.get(ext)
    if pil_format is None:
        raise ValueError(f"Unsupported output format: {ext}")

    destination.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(source) as image:
        image.load()

        if transforms:
            image = apply_all(image, transforms)

        if pil_format in _NO_ALPHA and (image.mode in ("RGBA", "LA", "P")):
            image = flatten_alpha(image, background)
        elif image.mode == "P":
            image = image.convert("RGBA")
        elif image.mode not in ("RGB", "RGBA", "L"):
            image = image.convert("RGB")

        save_args: dict[str, object] = {}
        if pil_format == "JPEG":
            save_args.update(quality=quality, optimize=True, progressive=True)
        elif pil_format == "WEBP":
            save_args.update(quality=quality, method=4)
        elif pil_format == "PNG":
            save_args.update(optimize=True)

        image.save(destination, format=pil_format, **save_args)

    return destination


def make_convert_job(
    out_dir: Path,
    target_format: str,
    quality: int = 90,
    policy: ConflictPolicy = ConflictPolicy.RENAME,
    background: tuple[int, int, int] = DEFAULT_BACKGROUND,
    transforms: list[Transform] | None = None,
) -> WorkFn:
    """Build a one-argument callable for `core.batch.run_batch`.

    This is the seam between the generic batch runner and this module:
    the runner only ever sees `work(path) -> path | None`.
    """

    def work(source: Path) -> Path | None:
        destination = resolve_output_path(source, out_dir, target_format, policy)
        if destination is None:
            return None  # skipped by policy
        return convert_image(
            source,
            destination,
            quality=quality,
            background=background,
            transforms=transforms,
        )

    return work


# Convenience for single-file use (Phase 1a behaviour kept alive).
convert_one = partial(convert_image)