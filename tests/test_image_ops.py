from PIL import Image

from mediakit.core.batch import run_batch
from mediakit.modules.image.convert import convert_image, make_convert_job
from mediakit.modules.image.ops import (
    ResizeMode,
    Rotation,
    apply_all,
    make_resize,
    make_rotate,
)


def img(w, h, mode="RGB"):
    return Image.new(mode, (w, h), (255, 0, 0))


# --------------------------------------------------------------- resize


def test_resize_max_width_keeps_aspect():
    out = make_resize(ResizeMode.MAX_WIDTH, width=100)(img(400, 200))
    assert out.size == (100, 50)


def test_resize_max_height_keeps_aspect():
    out = make_resize(ResizeMode.MAX_HEIGHT, height=50)(img(400, 200))
    assert out.size == (100, 50)


def test_resize_percent():
    out = make_resize(ResizeMode.PERCENT, percent=25)(img(400, 200))
    assert out.size == (100, 50)


def test_resize_fit_box_uses_tighter_constraint():
    # 400x200 into a 100x100 box: width is the binding constraint
    out = make_resize(ResizeMode.FIT_BOX, width=100, height=100)(img(400, 200))
    assert out.size == (100, 50)


def test_resize_does_not_upscale_by_default():
    out = make_resize(ResizeMode.MAX_WIDTH, width=800)(img(400, 200))
    assert out.size == (400, 200)


def test_resize_upscales_when_allowed():
    out = make_resize(ResizeMode.MAX_WIDTH, width=800, allow_upscale=True)(img(400, 200))
    assert out.size == (800, 400)


def test_resize_none_is_identity():
    out = make_resize(ResizeMode.NONE)(img(400, 200))
    assert out.size == (400, 200)


def test_resize_missing_param_is_identity():
    out = make_resize(ResizeMode.MAX_WIDTH, width=None)(img(400, 200))
    assert out.size == (400, 200)


def test_resize_never_produces_zero_dimension():
    out = make_resize(ResizeMode.PERCENT, percent=1)(img(10, 10))
    assert out.size[0] >= 1 and out.size[1] >= 1


# --------------------------------------------------------------- rotate


def test_rotate_90_swaps_dimensions():
    out = make_rotate(Rotation.CW_90)(img(400, 200))
    assert out.size == (200, 400)


def test_rotate_180_keeps_dimensions():
    out = make_rotate(Rotation.ROT_180)(img(400, 200))
    assert out.size == (400, 200)


def test_rotate_none_is_identity():
    out = make_rotate(Rotation.NONE)(img(400, 200))
    assert out.size == (400, 200)


def test_rotate_cw_and_ccw_are_opposite():
    source = img(400, 200)
    there = make_rotate(Rotation.CW_90)(source)
    back = make_rotate(Rotation.CCW_90)(there)
    assert back.size == source.size
    assert back.tobytes() == source.tobytes()


# ------------------------------------------------------------- pipeline


def test_apply_all_runs_in_order():
    transforms = [
        make_resize(ResizeMode.MAX_WIDTH, width=100),  # 400x200 -> 100x50
        make_rotate(Rotation.CW_90),  # 100x50 -> 50x100
    ]
    out = apply_all(img(400, 200), transforms)
    assert out.size == (50, 100)


def test_convert_image_applies_transforms(tmp_path):
    src = tmp_path / "a.png"
    img(400, 200).save(src)
    dst = tmp_path / "a.jpg"
    convert_image(src, dst, transforms=[make_resize(ResizeMode.PERCENT, percent=50)])
    with Image.open(dst) as out:
        assert out.size == (200, 100)


def test_transforms_preserved_through_batch(tmp_path):
    src_dir, out_dir = tmp_path / "in", tmp_path / "out"
    src_dir.mkdir()
    srcs = []
    for i in range(3):
        p = src_dir / f"{i}.png"
        img(400, 200).save(p)
        srcs.append(p)

    work = make_convert_job(
        out_dir,
        "jpg",
        transforms=[make_resize(ResizeMode.MAX_WIDTH, width=100)],
    )
    report = run_batch(srcs, work)
    assert len(report.succeeded) == 3
    for result in report.succeeded:
        with Image.open(result.output) as out:
            assert out.size == (100, 50)


def test_transform_runs_before_alpha_flatten(tmp_path):
    """Resize must see the original RGBA, not a flattened RGB."""
    src = tmp_path / "a.png"
    Image.new("RGBA", (400, 200), (255, 0, 0, 0)).save(src)
    dst = tmp_path / "a.jpg"
    convert_image(src, dst, transforms=[make_resize(ResizeMode.PERCENT, percent=50)])
    with Image.open(dst) as out:
        assert out.size == (200, 100)
        assert out.mode == "RGB"
        assert out.getpixel((0, 0)) == (255, 255, 255)
