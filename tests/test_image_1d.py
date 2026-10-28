"""Model store (download/verify/cancel) and background removal.

Inference tests need the real models. Point MEDIAKIT_MODEL_DIR at a
folder that has them; otherwise those tests are skipped, not failed.
"""

import dataclasses
import hashlib
import os
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from mediakit.core.batch import CancelToken, run_batch
from mediakit.core.credits import Credit
from mediakit.core.models import DownloadCancelled, ModelDownloadError, ModelSpec, ModelStore
from mediakit.modules.image.background import (
    MODELS,
    Background,
    apply_mask,
    make_background_job,
    output_extension,
)

TEST_CREDIT = Credit("Fake", "Tests", "MIT", "https://example.invalid", ())

# ----------------------------------------------------------- model store


def _fake_model(tmp_path: Path, size: int = 3_000_000) -> tuple[Path, ModelSpec]:
    blob = os.urandom(size)
    source = tmp_path / "remote" / "model.onnx"
    source.parent.mkdir()
    source.write_bytes(blob)
    spec = ModelSpec(
        "fake", "model.onnx", source.as_uri(), hashlib.sha256(blob).hexdigest(), size, TEST_CREDIT
    )
    return source, spec


def test_download_verifies_and_installs(tmp_path):
    _, spec = _fake_model(tmp_path)
    store = ModelStore(tmp_path / "cache")
    seen = []
    path = store.download(spec, on_progress=lambda d, t: seen.append((d, t)))
    assert path.exists() and store.is_installed(spec)
    assert seen[-1][0] == spec.size
    assert not list((tmp_path / "cache").glob("*.part"))


def test_download_rejects_bad_checksum(tmp_path):
    _, spec = _fake_model(tmp_path)
    bad = dataclasses.replace(spec, sha256="0" * 64)
    store = ModelStore(tmp_path / "cache")
    with pytest.raises(ModelDownloadError, match="Checksum"):
        store.download(bad)
    assert not store.is_installed(bad)
    assert not list((tmp_path / "cache").iterdir())  # no partial left behind


def test_download_cancel_leaves_nothing(tmp_path):
    _, spec = _fake_model(tmp_path)
    store = ModelStore(tmp_path / "cache")
    token = CancelToken()
    with pytest.raises(DownloadCancelled):
        store.download(spec, on_progress=lambda d, t: token.cancel(), cancel=token)
    assert not list((tmp_path / "cache").iterdir())


def test_download_network_error_is_wrapped(tmp_path):
    spec = ModelSpec("x", "x.onnx", (tmp_path / "missing.onnx").as_uri(), "0" * 64, 1, TEST_CREDIT)
    with pytest.raises(ModelDownloadError):
        ModelStore(tmp_path / "cache").download(spec)


def test_installed_check_is_size_based(tmp_path):
    _, spec = _fake_model(tmp_path)
    store = ModelStore(tmp_path / "cache")
    store.root.mkdir()
    store.path(spec).write_bytes(b"truncated")
    assert not store.is_installed(spec)


# ------------------------------------------------------ mask compositing


def _subject_and_mask():
    image = Image.new("RGB", (200, 100), (200, 30, 30))
    mask = Image.new("L", (200, 100), 0)
    ImageDraw.Draw(mask).rectangle((60, 20, 139, 79), fill=255)
    return image, mask


def test_apply_mask_transparent():
    image, mask = _subject_and_mask()
    out = apply_mask(image, mask)
    assert out.mode == "RGBA"
    assert out.getpixel((5, 5))[3] == 0 and out.getpixel((100, 50))[3] == 255


def test_apply_mask_white_background():
    image, mask = _subject_and_mask()
    out = apply_mask(image, mask, Background.WHITE)
    assert out.mode == "RGB" and out.getpixel((5, 5)) == (255, 255, 255)


def test_apply_mask_custom_color_and_crop():
    image, mask = _subject_and_mask()
    out = apply_mask(image, mask, Background.COLOR, (0, 0, 255), crop_to_subject=True)
    w, h = out.size
    assert 80 <= w <= 86 and 60 <= h <= 66  # subject box + ~1% padding


def test_output_extension():
    assert output_extension(Background.TRANSPARENT) == "png"
    assert output_extension(Background.WHITE) == "jpg"


# ------------------------------------------------------- real inference

STORE = ModelStore()
needs_model = pytest.mark.skipif(
    not STORE.is_installed(MODELS["fast"].spec),
    reason="model not downloaded (set MEDIAKIT_MODEL_DIR)",
)


def _scene(path: Path) -> Path:
    """A bright 'subject' on a busy dark background."""
    image = Image.new("RGB", (480, 320), (20, 60, 30))
    draw = ImageDraw.Draw(image)
    for i in range(0, 480, 24):
        draw.line((i, 0, i + 120, 320), fill=(40, 90, 50), width=6)
    draw.ellipse((170, 70, 310, 280), fill=(235, 220, 200))
    draw.ellipse((205, 30, 275, 100), fill=(235, 220, 200))
    image.save(path)
    return path


@needs_model
def test_fast_model_separates_subject(tmp_path):
    src = _scene(tmp_path / "scene.jpg")
    work = make_background_job(tmp_path / "out", "rename", "fast", STORE)
    report = run_batch([src], work)
    assert len(report.succeeded) == 1, report.failed
    with Image.open(report.succeeded[0].output) as out:
        assert out.mode == "RGBA" and out.size == (480, 320)
        alpha = out.getchannel("A")
        assert alpha.getpixel((240, 180)) > 128  # body kept
        assert alpha.getpixel((15, 15)) < 64  # corner removed
