"""Image encode pipeline. Pure domain logic: Pillow only, no Qt.

decode -> transforms -> encode. Every image tool (convert, resize,
crop, compress) is this same pipeline with different transforms and
encode settings, so they all go through `make_image_job`.
"""

from __future__ import annotations

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
DEFAULT_QUALITY = 92


def keep_format_extension(source: Path) -> str:
    """Output extension for tools that should not change the format.

    Inputs we can read but not write (bmp, tiff, gif) fall back to png:
    lossless, so nothing is lost by the forced change.
    """
    ext = source.suffix.lower().lstrip(".")
    if ext == "jpeg":
        return "jpg"
    return ext if ext in _PIL_FORMAT else "png"


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
    quality: int = DEFAULT_QUALITY,
    background: tuple[int, int, int] = DEFAULT_BACKGROUND,
    transforms: list[Transform] | None = None,
) -> Path:
    """Decode `source`, apply transforms, re-encode to `destination`.

    Transforms run on the decoded image before any mode conversion, so
    resize/rotate still see the original alpha channel.
    """
    ext = destination.suffix.lower().lstrip(".")
    pil_format = _PIL_FORMAT.get(ext)
    if pil_format is None:
        raise ValueError(f"Unsupported output format: {ext}")

    destination.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(source) as image:
        image.load()
        # Colour profile: kept so wide-gamut photos (e.g. Display P3)
        # don't come out washed out. EXIF is deliberately not carried.
        icc_profile = image.info.get("icc_profile")

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

        if icc_profile:
            save_args["icc_profile"] = icc_profile
        image.save(destination, format=pil_format, **save_args)

    return destination


def make_image_job(
    out_dir: Path | None,
    policy: ConflictPolicy = ConflictPolicy.RENAME,
    transforms: list[Transform] | None = None,
    target_format: str | None = None,
    quality: int = DEFAULT_QUALITY,
    suffix: str = "",
    background: tuple[int, int, int] = DEFAULT_BACKGROUND,
) -> WorkFn:
    """Build a one-argument callable for `core.batch.run_batch`.

    `out_dir=None` writes next to each source file (so a batch spanning
    several folders keeps its structure). `target_format=None` keeps
    each file's own format.
    """

    def work(source: Path) -> Path | None:
        ext = target_format or keep_format_extension(source)
        directory = out_dir if out_dir is not None else source.parent
        destination = resolve_output_path(source, directory, ext, policy, suffix)
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


def make_convert_job(
    out_dir: Path,
    target_format: str,
    quality: int = 90,
    policy: ConflictPolicy = ConflictPolicy.RENAME,
    background: tuple[int, int, int] = DEFAULT_BACKGROUND,
    transforms: list[Transform] | None = None,
) -> WorkFn:
    """Phase 1b entry point, kept as a thin wrapper for existing callers."""
    return make_image_job(
        out_dir,
        policy=policy,
        transforms=transforms,
        target_format=target_format,
        quality=quality,
        background=background,
    )
