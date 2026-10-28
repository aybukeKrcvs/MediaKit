"""AI upscaling (super-resolution) with Real-ESRGAN. Domain logic, no Qt.

Both models enlarge 4x. 2x is made from the 4x result with a Lanczos
downscale, so no separate x2 model has to be downloaded.

Tiling: the whole image never goes through the network at once (a 4x
output of a 12 MP photo would need many GB of GPU memory). It is cut
into tiles; each tile is run with a `pad` px margin of real neighbouring
pixels around it, and only the centre of the result is kept. Every
output pixel therefore sees the same context it would see untiled, so
there are no visible seams and no blending is needed.

The ONNX files are built from the official BSD-3 checkpoints by
tools/export_upscalers.py (no PyTorch) and hosted on this project's
GitHub release.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

import numpy as np
from PIL import Image

from mediakit.core.batch import Cancelled, CancelToken, WorkFn
from mediakit.core.credits import Credit
from mediakit.core.models import ModelSpec, ModelStore
from mediakit.core.onnx import load_model
from mediakit.core.paths import ConflictPolicy, resolve_output_path
from mediakit.modules.image.ops import auto_orient

_RELEASE = "https://github.com/aybukeKrcvs/MediaKit/releases/download/models-v1/"
_ESRGAN_AUTHORS = "Xintao Wang et al."
_ESRGAN_NOTE = (
    "Official BSD-3 weights, rebuilt as ONNX by MediaKit (tools/export_upscalers.py); "
    "the network and its weights are unchanged."
)
NATIVE_SCALE = 4
# 80 MP output = 240 MB as raw RGB. Beyond that saving alone gets slow
# and memory hungry; the user is asked to pick 2x or a smaller source.
MAX_OUTPUT_PIXELS = 80_000_000

# on_tile(done, total)
TileProgress = Callable[[int, int], None]
# tensor [1, 3, h, w] in 0..1 -> tensor [1, 3, 4h, 4w] in 0..1
InferFn = Callable[[np.ndarray], np.ndarray]


@dataclass(frozen=True)
class UpscaleModel:
    spec: ModelSpec
    tile: int  # input pixels per tile side; sized for a 4 GB GPU
    pad: int  # context margin around each tile, input pixels


MODELS: dict[str, UpscaleModel] = {
    "fast": UpscaleModel(
        ModelSpec(
            "realesr-general-x4v3",
            "realesr-general-x4v3.onnx",
            _RELEASE + "realesr-general-x4v3.onnx",
            "beeb6c1d0bc76b5b704a184dbef4a519665e2454e244f8978a8c2bc00414979a",
            4861752,
            Credit(
                "Real-ESRGAN general-x4v3",
                _ESRGAN_AUTHORS,
                "BSD-3-Clause",
                "https://github.com/xinntao/Real-ESRGAN",
                ("models/realesrgan/LICENSE",),
                _ESRGAN_NOTE,
            ),
        ),
        tile=512,
        pad=16,
    ),
    "quality": UpscaleModel(
        ModelSpec(
            "realesrgan-x4plus",
            "realesrgan-x4plus.onnx",
            _RELEASE + "realesrgan-x4plus.onnx",
            "8695e1b10e548274dd96ebe4697a28ad8ea2e20261c63ddf1ea05c7337dcd7ec",
            66920546,
            Credit(
                "Real-ESRGAN x4plus",
                _ESRGAN_AUTHORS,
                "BSD-3-Clause",
                "https://github.com/xinntao/Real-ESRGAN",
                ("models/realesrgan/LICENSE",),
                _ESRGAN_NOTE,
            ),
        ),
        # Measured on a GTX 1650 (4 GB, DirectML), 800x450 input at 4x:
        #   tile 128 -> 14.8 s   192 -> 13.8 s   256 -> 11.5 s   320 -> 12.4 s
        # Below 256 the fixed per-tile cost dominates; above it the
        # activations of this 23-block network stop fitting in 4 GB and
        # DirectML starts spilling into system memory.
        tile=256,
        # RRDBNet sees far: measured against an untiled run, pad 16 left
        # seams up to 47/255, pad 32 stays under 8/255 (invisible).
        pad=32,
    ),
}


class Scale(IntEnum):
    X2 = 2
    X4 = 4


# ================================================================ tiling


def tile_grid(width: int, height: int, tile: int) -> list[tuple[int, int, int, int]]:
    """Boxes (left, top, right, bottom) covering the image, row by row."""
    return [
        (x, y, min(x + tile, width), min(y + tile, height))
        for y in range(0, height, tile)
        for x in range(0, width, tile)
    ]


def _resize_rgb(array: np.ndarray, width: int, height: int) -> np.ndarray:
    image = Image.fromarray(array).resize((width, height), Image.Resampling.LANCZOS)
    return np.asarray(image)


def upscale_rgb(
    rgb: np.ndarray,
    infer: InferFn,
    scale: int,
    tile: int,
    pad: int,
    on_tile: TileProgress | None = None,
    cancel: CancelToken | None = None,
) -> np.ndarray:
    """uint8 HxWx3 -> uint8 (H*scale)x(W*scale)x3, tile by tile.

    Every tile is run on a canvas of exactly (tile + 2*pad) px, edge
    tiles included: the shorter ones are filled out by repeating their
    border pixels and that filler is thrown away afterwards. The model
    therefore always sees one and the same input shape. With a dynamic
    shape, DirectML recompiles and re-allocates the whole graph for
    every new tile size, which is what makes the GPU idle between tiles
    and the memory keep growing.
    """
    height, width = rgb.shape[:2]
    # One canvas size for the whole image (and for every image of the
    # same size in a batch). Capped by the image itself so a picture
    # smaller than one tile does not pay for empty filler.
    canvas_w = min(tile, width) + 2 * pad
    canvas_h = min(tile, height) + 2 * pad
    out = np.empty((height * scale, width * scale, 3), dtype=np.uint8)
    boxes = tile_grid(width, height, tile)
    for index, (left, top, right, bottom) in enumerate(boxes, start=1):
        if cancel is not None and cancel.cancelled:
            raise Cancelled
        # Window = the tile with `pad` px of context on every side. It
        # starts at (left - pad, top - pad) whatever the tile, so the
        # tile always sits at offset `pad` inside the canvas.
        wl, wt = left - pad, top - pad
        wr, wb = wl + canvas_w, wt + canvas_h
        pl, pt = max(0, wl), max(0, wt)
        pr, pb = min(width, wr), min(height, wb)
        patch = rgb[pt:pb, pl:pr]
        canvas = np.pad(
            patch,
            ((pt - wt, wb - pb), (pl - wl, wr - pr), (0, 0)),
            mode="edge",
        ).astype(np.float32)
        canvas /= 255.0
        result = infer(canvas.transpose(2, 0, 1)[np.newaxis])[0].transpose(1, 2, 0)
        result = (result * 255.0).round().clip(0, 255).astype(np.uint8)
        if scale != NATIVE_SCALE:
            # Downscale before cropping, so Lanczos also has context at
            # the tile edges.
            result = _resize_rgb(result, canvas_w * scale, canvas_h * scale)
        # Keep only the tile; the context and any filler are discarded.
        y0, x0 = pad * scale, pad * scale
        h, w = (bottom - top) * scale, (right - left) * scale
        out[top * scale : bottom * scale, left * scale : right * scale] = result[
            y0 : y0 + h, x0 : x0 + w
        ]
        if on_tile is not None:
            on_tile(index, len(boxes))
    return out


# ============================================================= inference


class TileRunner:
    """Runs tiles on the GPU; after the first GPU failure (typically out
    of memory on a big tile) it stays on the CPU for the rest of the job
    instead of failing again on every tile."""

    def __init__(self, model_path: Path) -> None:
        self._path = model_path
        self._loaded = load_model(model_path)

    @property
    def device(self) -> str:
        return self._loaded.device

    def __call__(self, tensor: np.ndarray) -> np.ndarray:
        session = self._loaded.session
        feed = {session.get_inputs()[0].name: tensor}
        try:
            return session.run(None, feed)[0]
        except Exception:
            if self._loaded.device == "CPU":
                raise
            self._loaded = load_model(self._path, prefer_gpu=False)
            session = self._loaded.session
            return session.run(None, {session.get_inputs()[0].name: tensor})[0]


def output_size(size: tuple[int, int], scale: int) -> tuple[int, int]:
    return size[0] * scale, size[1] * scale


def check_output_size(size: tuple[int, int], scale: int) -> None:
    width, height = output_size(size, scale)
    if width * height > MAX_OUTPUT_PIXELS:
        raise ValueError(
            f"Output would be {width} x {height} px, too large. Choose 2x or a smaller image."
        )


def upscale_image(
    image: Image.Image,
    model: UpscaleModel,
    infer: InferFn,
    scale: int,
    on_tile: TileProgress | None = None,
    cancel: CancelToken | None = None,
) -> Image.Image:
    """Any mode in, RGB or RGBA out. Alpha is enlarged with Lanczos:
    the model only knows colour, and edges of a mask need no detail."""
    check_output_size(image.size, scale)
    has_alpha = image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info)
    rgb = np.asarray(image.convert("RGB"))
    big = Image.fromarray(upscale_rgb(rgb, infer, scale, model.tile, model.pad, on_tile, cancel))
    if has_alpha:
        alpha = image.convert("RGBA").getchannel("A")
        big.putalpha(alpha.resize(big.size, Image.Resampling.LANCZOS))
    return big


# ================================================================== save


def output_extension(source: Path) -> str:
    """Keep the format when it is one we write well, else PNG."""
    ext = source.suffix.lower().lstrip(".")
    return {"jpg": "jpg", "jpeg": "jpg", "png": "png", "webp": "webp"}.get(ext, "png")


def save(image: Image.Image, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    ext = destination.suffix.lower()
    if ext in (".jpg", ".jpeg"):
        image.convert("RGB").save(destination, "JPEG", quality=95, optimize=True)
    elif ext == ".webp":
        image.save(destination, "WEBP", quality=95, method=4)
    else:
        image.save(destination, "PNG", optimize=False)  # optimize is very slow on big images
    return destination


def make_upscale_job(
    out_dir: Path | None,
    policy: ConflictPolicy,
    model_key: str,
    store: ModelStore,
    scale: int,
    on_tile: TileProgress | None = None,
    cancel: CancelToken | None = None,
) -> WorkFn:
    model = MODELS[model_key]
    model_path = store.path(model.spec)
    runner: TileRunner | None = None  # created on first use, inside the worker thread

    def work(source: Path) -> Path | None:
        nonlocal runner
        directory = out_dir if out_dir is not None else source.parent
        destination = resolve_output_path(
            source, directory, output_extension(source), policy, f"_x{scale}"
        )
        if destination is None:
            return None
        with Image.open(source) as opened:
            image = auto_orient(opened)
            image.load()
        if runner is None:
            runner = TileRunner(model_path)
        big = upscale_image(image, model, runner, scale, on_tile, cancel)
        return save(big, destination)

    return work
