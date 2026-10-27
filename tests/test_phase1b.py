from pathlib import Path

import pytest
from PIL import Image

from mediakit.core.batch import CancelToken, run_batch
from mediakit.core.paths import ConflictPolicy, collect_files, resolve_output_path
from mediakit.modules.image.convert import convert_image, make_convert_job


def make_png(path: Path, size=(8, 8), alpha=False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "RGBA" if alpha else "RGB"
    color = (255, 0, 0, 0) if alpha else (255, 0, 0)
    Image.new(mode, size, color).save(path)
    return path


# ---------------------------------------------------------------- paths

def test_resolve_rename(tmp_path):
    src = tmp_path / "a.png"
    (tmp_path / "a.jpg").write_bytes(b"x")
    out = resolve_output_path(src, tmp_path, "jpg", ConflictPolicy.RENAME)
    assert out.name == "a (1).jpg"


def test_resolve_skip(tmp_path):
    src = tmp_path / "a.png"
    (tmp_path / "a.jpg").write_bytes(b"x")
    assert resolve_output_path(src, tmp_path, "jpg", ConflictPolicy.SKIP) is None


def test_resolve_overwrite(tmp_path):
    src = tmp_path / "a.png"
    (tmp_path / "a.jpg").write_bytes(b"x")
    out = resolve_output_path(src, tmp_path, "jpg", ConflictPolicy.OVERWRITE)
    assert out.name == "a.jpg"


def test_collect_files_recursive(tmp_path):
    make_png(tmp_path / "one.png")
    make_png(tmp_path / "sub" / "two.png")
    (tmp_path / "note.txt").write_text("x")
    found = collect_files([tmp_path], {"png"})
    assert {p.name for p in found} == {"one.png", "two.png"}


def test_collect_files_dedupes(tmp_path):
    p = make_png(tmp_path / "one.png")
    found = collect_files([p, tmp_path], {"png"})
    assert len(found) == 1


# --------------------------------------------------------------- batch

def test_run_batch_isolates_failures(tmp_path):
    items = [tmp_path / f"{i}.png" for i in range(3)]

    def work(p: Path):
        if p.name == "1.png":
            raise ValueError("boom")
        return p

    report = run_batch(items, work)
    assert len(report.succeeded) == 2
    assert len(report.failed) == 1
    assert "boom" in report.failed[0].error


def test_run_batch_reports_skips(tmp_path):
    items = [tmp_path / "a.png"]
    report = run_batch(items, lambda p: None)
    assert len(report.skipped) == 1


def test_run_batch_cancel(tmp_path):
    items = [tmp_path / f"{i}.png" for i in range(5)]
    token = CancelToken()

    def work(p: Path):
        token.cancel()
        return p

    report = run_batch(items, work, cancel=token)
    assert report.cancelled
    assert len(report.results) == 1


def test_run_batch_progress_sequence(tmp_path):
    items = [tmp_path / f"{i}.png" for i in range(2)]
    seen = []
    run_batch(items, lambda p: p, on_progress=lambda d, t, n: seen.append((d, t)))
    assert seen == [(0, 2), (1, 2), (1, 2), (2, 2)]


# ------------------------------------------------------------- convert

def test_png_to_jpg_flattens_alpha(tmp_path):
    src = make_png(tmp_path / "t.png", alpha=True)
    dst = tmp_path / "t.jpg"
    convert_image(src, dst)
    with Image.open(dst) as im:
        assert im.mode == "RGB"
        assert im.getpixel((0, 0)) == (255, 255, 255)


def test_png_to_webp_keeps_alpha(tmp_path):
    src = make_png(tmp_path / "t.png", alpha=True)
    dst = tmp_path / "t.webp"
    convert_image(src, dst)
    with Image.open(dst) as im:
        assert im.mode in ("RGBA", "RGB")


def test_unsupported_output_raises(tmp_path):
    src = make_png(tmp_path / "t.png")
    with pytest.raises(ValueError):
        convert_image(src, tmp_path / "t.tga")


def test_convert_job_end_to_end(tmp_path):
    srcs = [make_png(tmp_path / "in" / f"{i}.png") for i in range(3)]
    out = tmp_path / "out"
    work = make_convert_job(out, "jpg", quality=80)
    report = run_batch(srcs, work)
    assert len(report.succeeded) == 3
    assert sorted(p.name for p in out.iterdir()) == ["0.jpg", "1.jpg", "2.jpg"]


def test_convert_job_skip_policy(tmp_path):
    src = make_png(tmp_path / "a.png")
    out = tmp_path / "out"
    out.mkdir()
    (out / "a.jpg").write_bytes(b"x")
    work = make_convert_job(out, "jpg", policy=ConflictPolicy.SKIP)
    report = run_batch([src], work)
    assert len(report.skipped) == 1


def test_resolve_overwrite_accepts_plain_string(tmp_path):
    """Regression: QComboBox.currentData() can hand back a plain str
    instead of the ConflictPolicy member. `is` comparison silently
    treats that as "no match" and falls through to rename - this
    pins `==` as the required comparison."""
    src = tmp_path / "a.png"
    (tmp_path / "a.jpg").write_bytes(b"x")
    out = resolve_output_path(src, tmp_path, "jpg", "overwrite")
    assert out.name == "a.jpg"


def test_resolve_skip_accepts_plain_string(tmp_path):
    src = tmp_path / "a.png"
    (tmp_path / "a.jpg").write_bytes(b"x")
    assert resolve_output_path(src, tmp_path, "jpg", "skip") is None