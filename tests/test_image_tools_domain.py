from PIL import Image

from mediakit.core.batch import run_batch
from mediakit.core.paths import ConflictPolicy, resolve_output_path
from mediakit.modules.image.convert import keep_format_extension, make_image_job
from mediakit.modules.image.ops import (
    ASPECT_PRESETS,
    AspectRatio,
    Rotation,
    center_crop_box,
    make_center_crop,
    make_crop_fraction,
    rotation_from_steps,
)


def img(w, h):
    return Image.new("RGB", (w, h), (0, 128, 255))


# ------------------------------------------------------------ center crop


def test_center_crop_wide_image_to_square():
    assert center_crop_box((400, 200), AspectRatio(1, 1)) == (100, 0, 300, 200)


def test_center_crop_tall_image_to_square():
    assert center_crop_box((200, 400), AspectRatio(1, 1)) == (0, 100, 200, 300)


def test_center_crop_to_16_9():
    out = make_center_crop(AspectRatio(16, 9))(img(1600, 1600))
    assert out.size == (1600, 900)


def test_center_crop_to_portrait_9_16():
    out = make_center_crop(AspectRatio(9, 16))(img(1600, 900))
    w, h = out.size
    assert h == 900 and abs(w / h - 9 / 16) < 0.01


def test_center_crop_exact_ratio_is_identity():
    source = img(1600, 900)
    assert make_center_crop(AspectRatio(16, 9))(source) is source


def test_presets_include_portrait_variants():
    keys = {p.key for p in ASPECT_PRESETS}
    for landscape, portrait in (("4:3", "3:4"), ("16:9", "9:16"), ("21:9", "9:21")):
        assert landscape in keys and portrait in keys


# ---------------------------------------------------------- manual crop


def test_crop_fraction_maps_to_pixels():
    out = make_crop_fraction(0.25, 0.0, 0.75, 0.5)(img(400, 200))
    assert out.size == (200, 100)


def test_crop_fraction_normalises_reversed_box():
    out = make_crop_fraction(0.75, 0.5, 0.25, 0.0)(img(400, 200))
    assert out.size == (200, 100)


def test_crop_fraction_clamps_outside_values():
    out = make_crop_fraction(-1, -1, 2, 2)(img(400, 200))
    assert out.size == (400, 200)


def test_crop_fraction_never_empty():
    out = make_crop_fraction(0.5, 0.5, 0.5, 0.5)(img(400, 200))
    assert out.size[0] >= 1 and out.size[1] >= 1


def test_rotation_from_steps_wraps():
    assert rotation_from_steps(0) == Rotation.NONE
    assert rotation_from_steps(1) == Rotation.CW_90
    assert rotation_from_steps(-1) == Rotation.CCW_90
    assert rotation_from_steps(6) == Rotation.ROT_180


# ---------------------------------------------------------- job plumbing


def test_keep_format_extension():
    from pathlib import Path

    assert keep_format_extension(Path("a.JPEG")) == "jpg"
    assert keep_format_extension(Path("a.webp")) == "webp"
    assert keep_format_extension(Path("a.bmp")) == "png"


def test_suffix_added_to_stem(tmp_path):
    src = tmp_path / "a.jpg"
    out = resolve_output_path(src, tmp_path, "jpg", suffix="_resized")
    assert out.name == "a_resized.jpg"


def test_never_overwrites_source_even_with_overwrite_policy(tmp_path):
    src = tmp_path / "a.png"
    img(10, 10).save(src)
    out = resolve_output_path(src, tmp_path, "png", ConflictPolicy.OVERWRITE)
    assert out != src
    assert out.name == "a (1).png"


def test_image_job_keeps_format_and_writes_next_to_source(tmp_path):
    a = tmp_path / "one" / "a.webp"
    b = tmp_path / "two" / "b.png"
    a.parent.mkdir()
    b.parent.mkdir()
    img(100, 50).save(a)
    img(100, 50).save(b)

    work = make_image_job(None, transforms=[make_center_crop(AspectRatio(1, 1))], suffix="_cropped")
    report = run_batch([a, b], work)

    assert len(report.succeeded) == 2
    assert (tmp_path / "one" / "a_cropped.webp").exists()
    assert (tmp_path / "two" / "b_cropped.png").exists()
    with Image.open(tmp_path / "two" / "b_cropped.png") as out:
        assert out.size == (50, 50)
