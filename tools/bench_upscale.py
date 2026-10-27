"""Find the fastest tile size for this machine.

Tile size is the one number that decides how the GPU is used: too small
and the card finishes each tile before the CPU has the next one ready
(the dips in the usage graph), too large and the activations no longer
fit in VRAM and spill into system memory, which is far slower.

Usage (project root):

    uv run python tools/bench_upscale.py <image> [--model quality] [--scale 4]

Each tile size gets a fresh ONNX session, so the model file is read
from disk once per size: the heavy disk activity during a run is this
tool, not the app.

Prints seconds per run for a few tile sizes. The first run of each size
includes the one-time graph build for that input shape, so every size is
timed twice and only the second run counts.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
from PIL import Image

from mediakit.core.models import ModelStore
from mediakit.core.onnx import available_device, unload_all
from mediakit.modules.image.ops import auto_orient
from mediakit.modules.image.upscale import MODELS, TileRunner, upscale_rgb

TILES = (128, 192, 256, 320)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    parser.add_argument("--model", default="quality", choices=list(MODELS))
    parser.add_argument("--scale", type=int, default=4)
    parser.add_argument("--max-side", type=int, default=800, help="shrink the input first")
    args = parser.parse_args()

    model = MODELS[args.model]
    store = ModelStore()
    if not store.is_installed(model.spec):
        raise SystemExit(f"{model.spec.filename} is not downloaded yet")

    if not args.image.is_file():
        raise SystemExit(f"No such image: {args.image}")
    with Image.open(args.image) as opened:
        image = auto_orient(opened)
        image.load()
    image.thumbnail((args.max_side, args.max_side))
    rgb = np.asarray(image.convert("RGB"))

    print(f"device {available_device()} | model {args.model} | input {rgb.shape[1]}x{rgb.shape[0]}")
    for tile in TILES:
        unload_all()  # fresh session, so one size cannot warm up the next
        runner = TileRunner(store.path(model.spec))
        timings = []
        for _ in range(2):
            start = time.perf_counter()
            upscale_rgb(rgb, runner, args.scale, tile, model.pad)
            timings.append(time.perf_counter() - start)
        tiles_across = -(-rgb.shape[1] // tile) * -(-rgb.shape[0] // tile)
        print(
            f"tile {tile:>4} (canvas {tile + 2 * model.pad:>4}, {tiles_across:>3} tiles): "
            f"{timings[1]:6.2f} s   first run {timings[0]:6.2f} s"
        )
    unload_all()


if __name__ == "__main__":
    main()
