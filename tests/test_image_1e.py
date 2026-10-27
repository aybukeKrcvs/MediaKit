"""Phase 1e: AI upscale.

Tiling is tested with a fake 'model' (nearest-neighbour enlarge), so the
maths is checked without any download. Tests with the real ONNX models
run only when they are installed (MEDIAKIT_MODEL_DIR or the user cache).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter

from mediakit.core.batch import Cancelled, CancelToken, run_batch
from mediakit.core.models import ModelStore
from mediakit.core.paths import ConflictPolicy
from mediakit.modules.image import upscale
from mediakit.modules.image.upscale import (
    MODELS,
    Scale,
    TileRunner,
    check_output_size,
    make_upscale_job,
    output_extension,
    tile_grid,
    upscale_image,
    upscale_rgb,
)


def nearest4(tensor: np.ndarray) -> np.ndarray:
    """Stand-in for the network: same contract, [1,3,h,w] -> [1,3,4h,4w]."""
    return tensor.repeat(4, axis=2).repeat(4, axis=3)


def blur4(tensor: np.ndarray) -> np.ndarray:
    """Like nearest4 but each output pixel depends on its neighbours, so a
    tile without context would differ at its edges."""
    padded = np.pad(tensor, ((0, 0), (0, 0), (1, 1), (1, 1)), mode="edge")
    smooth = sum(
        padded[:, :, 1 + dy : padded.shape[2] - 1 + dy, 1 + dx : padded.shape[3] - 1 + dx]
        for dy in (-1, 0, 1)
        for dx in (-1, 0, 1)
    )
    return nearest4(smooth / 9.0)


def pattern(width: int, height: int) -> np.ndarray:
    rng = np.random.default_rng(7)
    return rng.integers(0, 256, (height, width, 3), dtype=np.uint8)


# ----------------------------------------------------------------- tiling


def test_tile_grid_covers_every_pixel_once():
    width, height = 130, 70
    cover = np.zeros((height, width), int)
    for left, top, right, bottom in tile_grid(width, height, 32):
        cover[top:bottom, left:right] += 1
    assert (cover == 1).all()


@pytest.mark.parametrize("size", [(64, 64), (97, 53), (300, 17)])
def test_tiled_equals_untiled_for_local_model(size):
    rgb = pattern(*size)
    whole = upscale_rgb(rgb, nearest4, 4, tile=10_000, pad=0)
    tiled = upscale_rgb(rgb, nearest4, 4, tile=24, pad=4)
    assert tiled.shape == (size[1] * 4, size[0] * 4, 3)
    assert np.array_equal(whole, tiled)


def test_padding_removes_seams_for_a_model_with_context():
    rgb = pattern(90, 60)
    whole = upscale_rgb(rgb, blur4, 4, tile=10_000, pad=0)
    no_pad = upscale_rgb(rgb, blur4, 4, tile=30, pad=0)
    padded = upscale_rgb(rgb, blur4, 4, tile=30, pad=2)
    assert not np.array_equal(whole, no_pad)  # seams without context
    assert np.array_equal(whole, padded)  # gone with it


def test_2x_is_close_to_downscaled_4x():
    rgb = pattern(80, 48)
    tiled = upscale_rgb(rgb, nearest4, 2, tile=20, pad=8)
    whole = upscale_rgb(rgb, nearest4, 2, tile=10_000, pad=0)
    assert tiled.shape == (96, 160, 3)
    assert np.abs(tiled.astype(int) - whole.astype(int)).mean() < 1.0


def test_tile_progress_and_cancel():
    seen = []
    upscale_rgb(pattern(50, 50), nearest4, 4, tile=20, pad=2, on_tile=lambda d, t: seen.append(d))
    assert seen == list(range(1, 10))

    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        upscale_rgb(pattern(50, 50), nearest4, 4, tile=20, pad=2, cancel=token)


# ---------------------------------------------------------------- images


def test_alpha_is_kept_and_enlarged():
    image = Image.new("RGBA", (40, 30), (10, 200, 30, 0))
    ImageDraw.Draw(image).rectangle([10, 10, 30, 20], fill=(255, 0, 0, 255))
    big = upscale_image(image, MODELS["fast"], nearest4, Scale.X4)
    assert big.mode == "RGBA" and big.size == (160, 120)
    assert big.getpixel((0, 0))[3] == 0 and big.getpixel((80, 60))[3] == 255


def test_grayscale_and_palette_inputs_work():
    for mode in ("L", "P"):
        big = upscale_image(Image.new(mode, (20, 10)), MODELS["fast"], nearest4, Scale.X2)
        assert big.size == (40, 20)


def test_too_large_output_is_refused():
    check_output_size((2000, 1500), 4)  # 48 MP: fine
    with pytest.raises(ValueError, match="too large"):
        check_output_size((4000, 3000), 4)


def test_output_extension_keeps_format():
    assert output_extension(Path("a.JPEG")) == "jpg"
    assert output_extension(Path("a.webp")) == "webp"
    assert output_extension(Path("a.bmp")) == "png"
    assert output_extension(Path("a.gif")) == "png"


# ---------------------------------------------------------------- the job


def test_job_writes_suffixed_file_and_cancel_leaves_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(upscale, "TileRunner", lambda _path: nearest4)
    src = tmp_path / "photo.jpg"
    Image.new("RGB", (60, 40), (90, 140, 60)).save(src)

    work = make_upscale_job(
        tmp_path / "out", ConflictPolicy.RENAME, "fast", ModelStore(tmp_path), 2
    )
    report = run_batch([src], work)
    out = tmp_path / "out" / "photo_x2.jpg"
    assert report.succeeded and out.exists()
    with Image.open(out) as image:
        assert image.size == (120, 80)

    token = CancelToken()
    token.cancel()
    work = make_upscale_job(
        tmp_path / "out2", ConflictPolicy.RENAME, "fast", ModelStore(tmp_path), 4, cancel=token
    )
    report = run_batch([src], work)
    assert report.cancelled and not report.failed
    assert not (tmp_path / "out2").exists() or not list((tmp_path / "out2").iterdir())


# ------------------------------------------------------------ real models


def _installed(key: str) -> Path | None:
    store = ModelStore()
    spec = MODELS[key].spec
    return store.path(spec) if store.is_installed(spec) else None


@pytest.mark.parametrize("key", ["fast", "quality"])
def test_real_model_tiles_without_visible_seams(key):
    path = _installed(key)
    if path is None:
        pytest.skip("model not downloaded")
    rgb = pattern(96, 72) // 2 + 64  # calmer than pure noise
    image = Image.fromarray(rgb).filter(ImageFilter.SMOOTH_MORE)
    rgb = np.asarray(image)
    runner = TileRunner(path)
    model = MODELS[key]
    # The reference is a single-tile run with the same border padding,
    # so only the seams between tiles are compared. (Replicated border
    # pixels do change the outermost output pixels, the same way they
    # would for an untiled run on a cropped image; that is a border
    # effect, not a seam.)
    whole = upscale_rgb(rgb, runner, 4, tile=10_000, pad=model.pad)
    tiled = upscale_rgb(rgb, runner, 4, tile=48, pad=model.pad)
    diff = np.abs(whole.astype(int) - tiled.astype(int))
    assert np.percentile(diff, 99.9) <= 6
    assert diff.mean() < 0.5
