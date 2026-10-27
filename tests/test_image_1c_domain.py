import io

import pytest
from PIL import Image, ImageCms, PngImagePlugin

from mediakit.modules.image.convert import convert_image
from mediakit.modules.image.metadata import inspect_metadata, strip_metadata
from mediakit.modules.image.watermark import (
    Position,
    make_logo_watermark,
    make_text_watermark,
)

GPS_IFD = 0x8825


def _exif_with_gps_and_camera(orientation: int = 1) -> Image.Exif:
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"
    exif[0x0110] = "Model X"
    exif[0x0132] = "2026:10:01 12:00:00"
    exif[0x0112] = orientation
    exif.get_ifd(GPS_IFD)[2] = (39.0, 55.0, 0.0)  # GPSLatitude
    exif.get_ifd(GPS_IFD)[1] = "N"
    return exif


def _jpeg_with_metadata(path, orientation=1, icc=True):
    image = Image.new("RGB", (64, 32), (200, 50, 50))
    args = {"exif": _exif_with_gps_and_camera(orientation).tobytes(), "comment": b"secret"}
    if icc:
        args["icc_profile"] = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    image.save(path, "JPEG", quality=90, **args)
    return path


def _scan_data(data: bytes) -> bytes:
    """Bytes from Start-of-Scan to the end: the compressed pixels."""
    return data[data.index(b"\xff\xda") :]


# ---------------------------------------------------------------- inspect


def test_inspect_finds_gps_camera_comment_icc(tmp_path):
    report = inspect_metadata(_jpeg_with_metadata(tmp_path / "a.jpg"))
    assert report.has_gps
    assert "PhoneMaker" in report.camera
    assert report.taken.startswith("2026")
    assert report.has_comment
    assert report.has_icc
    assert not report.is_clean


# ------------------------------------------------------------------ JPEG


def test_jpeg_strip_removes_gps_and_camera(tmp_path):
    src = _jpeg_with_metadata(tmp_path / "a.jpg")
    dst = strip_metadata(src, tmp_path / "out.jpg")
    report = inspect_metadata(dst)
    assert not report.has_gps
    assert report.camera == ""
    assert not report.has_comment
    assert report.is_clean


def test_jpeg_strip_is_lossless(tmp_path):
    """The compressed image data must be byte-identical: no re-encode."""
    src = _jpeg_with_metadata(tmp_path / "a.jpg")
    dst = strip_metadata(src, tmp_path / "out.jpg")
    assert _scan_data(dst.read_bytes()) == _scan_data(src.read_bytes())
    assert dst.stat().st_size < src.stat().st_size


def test_jpeg_strip_keeps_orientation(tmp_path):
    src = _jpeg_with_metadata(tmp_path / "a.jpg", orientation=6)
    dst = strip_metadata(src, tmp_path / "out.jpg")
    with Image.open(dst) as image:
        exif = image.getexif()
        assert exif.get(0x0112) == 6
        assert not exif.get_ifd(GPS_IFD)
        assert 0x010F not in exif


def test_jpeg_icc_kept_or_dropped(tmp_path):
    src = _jpeg_with_metadata(tmp_path / "a.jpg")
    kept = strip_metadata(src, tmp_path / "kept.jpg", keep_icc=True)
    dropped = strip_metadata(src, tmp_path / "dropped.jpg", keep_icc=False)
    assert inspect_metadata(kept).has_icc
    assert not inspect_metadata(dropped).has_icc


# ------------------------------------------------------------------- PNG


def test_png_strip_removes_text_and_keeps_pixels(tmp_path):
    src = tmp_path / "a.png"
    info = PngImagePlugin.PngInfo()
    info.add_text("Author", "Someone")
    info.add_text("Location", "Ankara")
    image = Image.new("RGBA", (16, 16), (10, 20, 30, 128))
    image.save(src, pnginfo=info, exif=_exif_with_gps_and_camera().tobytes())

    dst = strip_metadata(src, tmp_path / "out.png")
    with Image.open(dst) as out:
        assert "Author" not in out.info and "Location" not in out.info
        assert not out.getexif()
        assert out.tobytes() == image.tobytes()


# ------------------------------------------------------------------ WebP


def test_webp_strip_removes_exif_and_stays_valid(tmp_path):
    src = tmp_path / "a.webp"
    Image.new("RGB", (32, 32), (0, 128, 255)).save(
        src, "WEBP", exif=_exif_with_gps_and_camera().tobytes()
    )
    assert inspect_metadata(src).has_gps
    dst = strip_metadata(src, tmp_path / "out.webp")
    with Image.open(dst) as out:
        out.load()  # decodes: proves the RIFF structure is still valid
        assert out.size == (32, 32)
    assert not inspect_metadata(dst).has_gps


def test_strip_rejects_unsupported(tmp_path):
    src = tmp_path / "a.bmp"
    Image.new("RGB", (4, 4)).save(src)
    with pytest.raises(ValueError):
        strip_metadata(src, tmp_path / "out.bmp")


# ------------------------------------------------------------- watermark


def _changed_region(before: Image.Image, after: Image.Image):
    from PIL import ImageChops

    return ImageChops.difference(before.convert("RGB"), after.convert("RGB")).getbbox()


def test_text_watermark_bottom_right(tmp_path):
    base = Image.new("RGB", (400, 200), (30, 30, 30))
    out = make_text_watermark("© Aybüke", Position.BOTTOM_RIGHT, size=0.06)(base)
    box = _changed_region(base, out)
    assert box is not None
    assert box[0] > 200 and box[1] > 100  # lower-right quadrant


def test_text_watermark_top_left(tmp_path):
    base = Image.new("RGB", (400, 200), (30, 30, 30))
    box = _changed_region(base, make_text_watermark("x", Position.TOP_LEFT, size=0.08)(base))
    assert box[2] < 200 and box[3] < 100


def test_text_watermark_tiled_covers_image():
    base = Image.new("RGB", (600, 400), (30, 30, 30))
    box = _changed_region(base, make_text_watermark("DRAFT", Position.TILED)(base))
    assert box[0] < 60 and box[2] > 540 and box[1] < 60 and box[3] > 340


def test_text_watermark_scales_with_image():
    small = Image.new("RGB", (400, 200), (30, 30, 30))
    big = Image.new("RGB", (1600, 800), (30, 30, 30))
    wm = make_text_watermark("Stamp", Position.CENTER, size=0.05)
    s = _changed_region(small, wm(small))
    b = _changed_region(big, wm(big))
    ratio = (b[2] - b[0]) / (s[2] - s[0])
    assert 3.5 < ratio < 4.5


def test_empty_text_is_identity():
    base = Image.new("RGB", (100, 50))
    assert make_text_watermark("   ")(base) is base


def test_watermark_keeps_alpha_and_mode():
    rgba = Image.new("RGBA", (200, 100), (0, 0, 0, 0))
    assert make_text_watermark("hi")(rgba).mode == "RGBA"
    rgb = Image.new("RGB", (200, 100))
    assert make_text_watermark("hi")(rgb).mode == "RGB"


def test_logo_watermark_size_and_opacity(tmp_path):
    logo = tmp_path / "logo.png"
    Image.new("RGBA", (100, 50), (255, 0, 0, 255)).save(logo)
    base = Image.new("RGB", (1000, 500), (0, 0, 0))
    out = make_logo_watermark(logo, Position.TOP_LEFT, size=0.2, opacity=0.5, margin=0)(base)
    box = _changed_region(base, out)
    assert box == (0, 0, 200, 100)  # 20% of width, aspect kept
    r, g, b = out.getpixel((50, 50))
    assert 110 < r < 145 and g == 0  # ~50% red over black


def test_convert_keeps_icc_profile(tmp_path):
    src = _jpeg_with_metadata(tmp_path / "a.jpg")
    dst = convert_image(src, tmp_path / "a.webp")
    with Image.open(dst) as out:
        assert out.info.get("icc_profile")
    buffer = io.BytesIO(dst.read_bytes())
    assert buffer.getbuffer().nbytes > 0
