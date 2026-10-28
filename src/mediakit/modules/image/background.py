"""AI background removal. Domain logic: Pillow + numpy + onnxruntime.

Each model predicts a soft mask (0..1 per pixel: how much of it is the
subject). The mask becomes the alpha channel of the output.

Pre/post-processing per model follows the reference implementations
(the same values rembg uses), without pulling rembg's heavy extras.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import numpy as np
from PIL import Image

from mediakit.core.batch import WorkFn
from mediakit.core.credits import Credit
from mediakit.core.models import ModelSpec, ModelStore
from mediakit.core.onnx import load_model
from mediakit.core.paths import ConflictPolicy, resolve_output_path
from mediakit.modules.image.ops import auto_orient

_RELEASE = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/"
_IMAGENET_MEAN = (0.485, 0.456, 0.406)
_IMAGENET_STD = (0.229, 0.224, 0.225)


@dataclass(frozen=True)
class SegmentationModel:
    spec: ModelSpec
    input_size: int
    mean: tuple[float, float, float]
    std: tuple[float, float, float]
    sigmoid: bool  # True for models that output logits instead of 0..1


# BiRefNet (higher quality) was evaluated and left out for now: at its
# fixed 1024px input it needs >3.7 GB RAM on CPU and will not fit a 4 GB
# GPU. Re-add it here once measured on target hardware.


MODELS: dict[str, SegmentationModel] = {
    "fast": SegmentationModel(
        ModelSpec(
            "silueta",
            "silueta.onnx",
            _RELEASE + "silueta.onnx",
            "75da6c8d2f8096ec743d071951be73b4a8bc7b3e51d9a6625d63644f90ffeedb",
            44173029,
            Credit(
                "silueta (U\u00b2-Net)",
                "Xuebin Qin et al., Daniel Gatis",
                "Apache-2.0",
                "https://github.com/xuebinqin/U-2-Net",
                ("models/u2net/LICENSE", "models/rembg/LICENSE"),
                "A smaller U\u00b2-Net distributed by rembg. Downloaded unchanged "
                "from the rembg GitHub release.",
            ),
        ),
        320,
        _IMAGENET_MEAN,
        _IMAGENET_STD,
        sigmoid=False,
    ),
    "standard": SegmentationModel(
        ModelSpec(
            "isnet-general-use",
            "isnet-general-use.onnx",
            _RELEASE + "isnet-general-use.onnx",
            "60920e99c45464f2ba57bee2ad08c919a52bbf852739e96947fbb4358c0d964a",
            178648008,
            Credit(
                "IS-Net (DIS)",
                "Xuebin Qin et al.",
                "Apache-2.0",
                "https://github.com/xuebinqin/DIS",
                ("models/dis/LICENSE", "models/rembg/LICENSE"),
                "General-use weights distributed by rembg. Downloaded unchanged "
                "from the rembg GitHub release.",
            ),
        ),
        1024,
        _IMAGENET_MEAN,
        (1.0, 1.0, 1.0),
        sigmoid=False,
    ),
}


class Background(StrEnum):
    TRANSPARENT = "transparent"
    WHITE = "white"
    COLOR = "color"


def _preprocess(image: Image.Image, model: SegmentationModel) -> np.ndarray:
    """RGB image -> float32 NCHW tensor in the model's expected range."""
    size = (model.input_size, model.input_size)
    rgb = image.convert("RGB").resize(size, Image.Resampling.BILINEAR)
    array = np.asarray(rgb, dtype=np.float32)
    array /= max(float(array.max()), 1e-6)
    array = (array - np.array(model.mean, dtype=np.float32)) / np.array(model.std, dtype=np.float32)
    return array.transpose(2, 0, 1)[np.newaxis].astype(np.float32)


def _run(session, tensor: np.ndarray) -> np.ndarray:
    return session.run(None, {session.get_inputs()[0].name: tensor})[0]


def predict_mask(image: Image.Image, model: SegmentationModel, model_path: Path) -> Image.Image:
    """Soft mask ('L' mode, 0..255) at the original image size."""
    tensor = _preprocess(image, model)
    loaded = load_model(model_path)
    try:
        output = _run(loaded.session, tensor)
    except Exception:
        if loaded.device == "CPU":
            raise
        # GPU ran out of memory or hit an unsupported op mid-run: the
        # session loaded fine, so this only shows up here. Retry on CPU.
        output = _run(load_model(model_path, prefer_gpu=False).session, tensor)
    pred = output[0, 0].astype(np.float32)
    if model.sigmoid:
        pred = 1.0 / (1.0 + np.exp(-pred))
    # Min-max stretch: the raw range differs per image and per model.
    low, high = float(pred.min()), float(pred.max())
    pred = (pred - low) / (high - low) if high > low else np.zeros_like(pred)
    mask = Image.fromarray((pred * 255).clip(0, 255).astype(np.uint8), mode="L")
    return mask.resize(image.size, Image.Resampling.LANCZOS)


def apply_mask(
    image: Image.Image,
    mask: Image.Image,
    background: Background = Background.TRANSPARENT,
    color: tuple[int, int, int] = (255, 255, 255),
    crop_to_subject: bool = False,
) -> Image.Image:
    cutout = image.convert("RGBA")
    cutout.putalpha(mask)

    if crop_to_subject:
        # Ignore faint haze in the mask when finding the subject's box.
        box = mask.point(lambda v: 255 if v > 16 else 0).getbbox()
        if box:
            pad = round(max(image.size) * 0.01)
            box = (
                max(0, box[0] - pad),
                max(0, box[1] - pad),
                min(image.width, box[2] + pad),
                min(image.height, box[3] + pad),
            )
            cutout = cutout.crop(box)

    if background == Background.TRANSPARENT:
        return cutout
    fill = (255, 255, 255) if background == Background.WHITE else color
    canvas = Image.new("RGBA", cutout.size, (*fill, 255))
    canvas.alpha_composite(cutout)
    return canvas.convert("RGB")


def remove_background(
    source: Path,
    destination: Path,
    model: SegmentationModel,
    model_path: Path,
    background: Background = Background.TRANSPARENT,
    color: tuple[int, int, int] = (255, 255, 255),
    crop_to_subject: bool = False,
) -> Path:
    with Image.open(source) as opened:
        image = auto_orient(opened)
        image.load()
    mask = predict_mask(image, model, model_path)
    result = apply_mask(image, mask, background, color, crop_to_subject)

    destination.parent.mkdir(parents=True, exist_ok=True)
    ext = destination.suffix.lower()
    if ext in (".jpg", ".jpeg"):
        result.convert("RGB").save(destination, "JPEG", quality=92, optimize=True)
    elif ext == ".webp":
        result.save(destination, "WEBP", quality=92, method=4)
    else:
        result.save(destination, "PNG", optimize=True)
    return destination


def output_extension(background: Background) -> str:
    """Transparency needs PNG; a solid background is fine as JPG."""
    return "png" if background == Background.TRANSPARENT else "jpg"


def make_background_job(
    out_dir: Path | None,
    policy: ConflictPolicy,
    model_key: str,
    store: ModelStore,
    background: Background = Background.TRANSPARENT,
    color: tuple[int, int, int] = (255, 255, 255),
    crop_to_subject: bool = False,
) -> WorkFn:
    model = MODELS[model_key]
    model_path = store.path(model.spec)
    ext = output_extension(background)

    def work(source: Path) -> Path | None:
        directory = out_dir if out_dir is not None else source.parent
        destination = resolve_output_path(source, directory, ext, policy, "_nobg")
        if destination is None:
            return None
        return remove_background(
            source, destination, model, model_path, background, color, crop_to_subject
        )

    return work
