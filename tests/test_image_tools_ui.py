"""UI-level tests: real widgets, real worker thread, offscreen Qt.

They drive the tools the way a user would (click tiles, drag on the
crop canvas, press Save) and check the files that come out.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PySide6.QtCore import QEvent, QEventLoop, QPointF, Qt, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from mediakit.core.credits import Credit
from mediakit.modules.image.hub import build_image_hub

L, N = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
TEST_CREDIT = Credit("Fake", "Tests", "MIT", "https://example.invalid", ())


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def images(tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    Image.new("RGB", (1600, 900), (200, 80, 40)).save(src / "wide.jpg")
    Image.new("RGBA", (900, 1600), (40, 120, 200, 255)).save(src / "tall.png")
    return src


@pytest.fixture
def hub(app):
    widget = build_image_hub()
    widget.resize(1100, 760)
    widget.show()
    yield widget
    widget.close()


def run(app, tool):
    loop = QEventLoop()
    timer = QTimer()
    timer.timeout.connect(lambda: loop.quit() if not tool.is_running() else None)
    tool.run_btn.click()
    timer.start(20)
    QTimer.singleShot(15000, loop.quit)
    loop.exec()


def drag(canvas, a, b):
    scale, off = canvas._view()
    steps = (
        (QEvent.Type.MouseButtonPress, a, L, L),
        (QEvent.Type.MouseMove, b, N, L),
        (QEvent.Type.MouseButtonRelease, b, L, N),
    )
    for kind, (x, y), button, buttons in steps:
        pos = QPointF(off.x() + x * scale, off.y() + y * scale)
        event = QMouseEvent(
            kind, pos, canvas.mapToGlobal(pos), button, buttons, Qt.KeyboardModifier.NoModifier
        )
        QApplication.sendEvent(canvas, event)


def size_of(path):
    with Image.open(path) as im:
        return im.size


def test_coming_soon_tool_does_not_open(app):
    # Every image tool is built now, so use a hub with an unbuilt card.
    from mediakit.ui.tool_hub import ToolHub, ToolSpec

    spec = ToolSpec("later", "upscale", lambda: "Later", lambda: "Not built yet.")
    hub = ToolHub(lambda: "T", lambda: "S", [spec])
    hub.open_tool("later")
    assert hub.current_tool() is None


def test_tool_page_is_created_once(hub):
    hub.open_tool("crop")
    first = hub.current_tool()
    hub.show_home()
    hub.open_tool("crop")
    assert hub.current_tool() is first


def test_single_crop_by_drag(app, hub, images, tmp_path):
    hub.open_tool("crop")
    tool = hub.current_tool()
    tool.add_paths([images])
    tool.file_list.setCurrentRow(1)  # wide.jpg (list is sorted)
    app.processEvents()
    drag(tool.canvas, (400, 200), (1200, 700))
    tool._out_dir = tmp_path / "out"
    run(app, tool)
    outputs = list((tmp_path / "out").iterdir())
    assert [o.name for o in outputs] == ["wide_cropped.jpg"]
    w, h = size_of(outputs[0])
    assert abs(w - 800) <= 6 and abs(h - 500) <= 6


def test_crop_canvas_ratio_lock(app, hub, images):
    hub.open_tool("crop")
    tool = hub.current_tool()
    tool.add_paths([images])
    tool.single_ratio_tiles[1].click()  # 1:1
    app.processEvents()
    w, h = tool.canvas.crop_pixel_size()
    assert w == h


def test_batch_crop_16_9_after_rotation(app, hub, images, tmp_path):
    hub.open_tool("crop")
    tool = hub.current_tool()
    tool.add_paths([images])
    tool.batch_btn.click()
    tool.batch_ratio_tiles[4].click()  # 16:9 (index 0 is "Original")
    tool.rotate_cw.click()
    tool._out_dir = tmp_path / "out"
    run(app, tool)
    sizes = [size_of(p) for p in (tmp_path / "out").iterdir()]
    assert len(sizes) == 2
    assert all(abs(w / h - 16 / 9) < 0.01 for w, h in sizes)


def test_batch_original_without_rotation_cannot_run(app, hub, images):
    hub.open_tool("crop")
    tool = hub.current_tool()
    tool.add_paths([images])
    tool.batch_btn.click()
    tool.batch_ratio_tiles[0].click()
    app.processEvents()
    assert not tool.run_btn.isEnabled()


def test_resize_tool(app, hub, images, tmp_path):
    hub.open_tool("resize")
    tool = hub.current_tool()
    tool.add_paths([images])
    tool.width_spin.setValue(800)
    tool._out_dir = tmp_path / "out"
    run(app, tool)
    assert size_of(tmp_path / "out" / "wide_resized.jpg") == (800, 450)
    assert (tmp_path / "out" / "tall_resized.png").exists()


def test_convert_tool(app, hub, images, tmp_path):
    hub.open_tool("convert")
    tool = hub.current_tool()
    tool.add_paths([images])
    tool.format_tiles[2].click()  # webp
    tool._out_dir = tmp_path / "out"
    run(app, tool)
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["tall.webp", "wide.webp"]


def test_compress_preset_moves_slider(hub):
    hub.open_tool("compress")
    tool = hub.current_tool()
    tool.level_tiles[2].click()
    assert tool.quality_slider.value() == 50


# ------------------------------------------------------------------ 1c


def _jpeg_with_gps(path):
    exif = Image.Exif()
    exif[0x010F] = "Apple"
    exif[0x0112] = 6
    exif.get_ifd(0x8825)[2] = (39.0, 55.0, 12.0)
    Image.new("RGB", (320, 200), (90, 140, 60)).save(path, exif=exif.tobytes())
    return path


def test_metadata_tool_inspects_and_strips(app, hub, tmp_path):
    src = _jpeg_with_gps(tmp_path / "trip.jpg")
    hub.open_tool("metadata")
    tool = hub.current_tool()
    tool.add_paths([src])
    tool.file_list.setCurrentRow(0)
    app.processEvents()
    assert "GPS" in tool.report.text()

    tool._out_dir = tmp_path / "out"
    run(app, tool)
    out = tmp_path / "out" / "trip_clean.jpg"
    with Image.open(out) as image:
        exif = image.getexif()
        assert not exif.get_ifd(0x8825)  # GPS gone
        assert 0x010F not in exif  # camera gone
        assert exif.get(0x0112) == 6  # orientation kept


def test_watermark_tool_needs_text_then_runs(app, hub, images, tmp_path):
    hub.open_tool("watermark")
    tool = hub.current_tool()
    tool.add_paths([images / "wide.jpg"])
    app.processEvents()
    assert not tool.run_btn.isEnabled()  # empty text: nothing to stamp

    tool.text_edit.setText("\u00a9 test")
    app.processEvents()
    assert tool.run_btn.isEnabled()

    tool._render_preview()
    assert not tool.preview.pixmap().isNull()

    tool._out_dir = tmp_path / "out"
    run(app, tool)
    out = tmp_path / "out" / "wide_watermarked.jpg"
    with Image.open(out) as stamped, Image.open(images / "wide.jpg") as original:
        assert stamped.size == original.size
        assert stamped.tobytes() != original.tobytes()


def test_watermark_logo_mode_requires_logo(app, hub, images):
    hub.open_tool("watermark")
    tool = hub.current_tool()
    tool.add_paths([images])
    tool.logo_btn.click()
    app.processEvents()
    assert tool.logo_row.isVisibleTo(tool) and not tool.text_row.isVisibleTo(tool)
    assert not tool.run_btn.isEnabled()


# ------------------------------------------------------------------ 1d


def _wait(app, predicate, timeout_ms=60000):
    loop = QEventLoop()
    timer = QTimer()
    timer.timeout.connect(lambda: loop.quit() if predicate() else None)
    timer.start(20)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()


def test_background_tool_without_model_cannot_run(app, images, tmp_path):
    from mediakit.core.models import ModelStore
    from mediakit.modules.image.background_tool import BackgroundTool

    tool = BackgroundTool(store=ModelStore(tmp_path / "empty"))
    tool.show()
    tool.add_paths([images])
    app.processEvents()
    assert not tool.run_btn.isEnabled()
    assert tool.download_btn.isVisibleTo(tool)
    assert not tool.preview_btn.isEnabled()


def test_background_tool_download_flow(app, images, tmp_path, monkeypatch):
    import dataclasses
    import hashlib

    from mediakit.core.models import ModelSpec, ModelStore
    from mediakit.modules.image import background
    from mediakit.modules.image.background_tool import BackgroundTool

    blob = b"x" * 2_500_000
    remote = tmp_path / "remote.onnx"
    remote.write_bytes(blob)
    fake = ModelSpec(
        "fake",
        "fake.onnx",
        remote.as_uri(),
        hashlib.sha256(blob).hexdigest(),
        len(blob),
        TEST_CREDIT,
    )
    monkeypatch.setitem(
        background.MODELS,
        "standard",
        dataclasses.replace(background.MODELS["standard"], spec=fake),
    )

    tool = BackgroundTool(store=ModelStore(tmp_path / "cache"))
    tool.show()
    tool.add_paths([images])
    tool.download_btn.click()
    _wait(app, lambda: tool._download is None)
    assert (tmp_path / "cache" / "fake.onnx").exists()
    assert not tool.download_btn.isVisibleTo(tool)
    assert tool.run_btn.isEnabled()


_REAL = None


def _real_store():
    from mediakit.core.models import ModelStore
    from mediakit.modules.image.background import MODELS

    store = ModelStore()
    return store if store.is_installed(MODELS["fast"].spec) else None


@pytest.mark.skipif(_real_store() is None, reason="model not downloaded")
def test_background_tool_preview_and_batch(app, images, tmp_path):
    from mediakit.modules.image.background_tool import MODEL_KEYS, BackgroundTool

    tool = BackgroundTool(store=_real_store())
    tool.show()
    tool.model_tiles[MODEL_KEYS.index("fast")].click()
    tool.add_paths([images / "wide.jpg"])
    tool.file_list.setCurrentRow(0)
    app.processEvents()

    tool.preview_btn.click()
    _wait(app, lambda: tool._preview_job is None)
    assert tool.preview.pixmap() is not None and not tool.preview.pixmap().isNull()

    tool._out_dir = tmp_path / "out"
    run(app, tool)
    out = tmp_path / "out" / "wide_nobg.png"
    with Image.open(out) as image:
        assert image.mode == "RGBA" and image.size == (1600, 900)


# ------------------------------------------------------------------ 1e


@pytest.fixture
def fake_upscaler(tmp_path, monkeypatch):
    """Installed-looking model + nearest-neighbour stand-in for ONNX."""
    import dataclasses
    import hashlib

    import numpy as np

    from mediakit.core.models import ModelSpec, ModelStore
    from mediakit.modules.image import upscale, upscale_tool

    blob = b"m" * 1000
    spec = ModelSpec(
        "fake", "fake.onnx", "", hashlib.sha256(blob).hexdigest(), len(blob), TEST_CREDIT
    )
    for key in ("fast", "quality"):
        monkeypatch.setitem(
            upscale.MODELS, key, dataclasses.replace(upscale.MODELS[key], spec=spec, tile=32)
        )
    store = ModelStore(tmp_path / "models")
    store.root.mkdir()
    store.path(spec).write_bytes(blob)

    def runner(_path):
        return lambda t: t.repeat(4, axis=2).repeat(4, axis=3).astype(np.float32)

    monkeypatch.setattr(upscale, "TileRunner", runner)
    monkeypatch.setattr(upscale_tool, "TileRunner", runner)
    return store


def test_upscale_tool_without_model_cannot_run(app, images, tmp_path):
    from mediakit.core.models import ModelStore
    from mediakit.modules.image.upscale_tool import UpscaleTool

    tool = UpscaleTool(store=ModelStore(tmp_path / "empty"))
    tool.show()
    tool.add_paths([images])
    app.processEvents()
    assert not tool.run_btn.isEnabled()
    assert tool.model_panel.download_btn.isVisibleTo(tool)
    assert not tool.preview_btn.isEnabled()


def test_upscale_tool_preview_size_and_batch(app, images, tmp_path, fake_upscaler):
    from mediakit.modules.image.upscale_tool import UpscaleTool

    tool = UpscaleTool(store=fake_upscaler)
    tool.show()
    tool.add_paths([images / "wide.jpg"])
    app.processEvents()
    assert "3200" in tool.size_label.text()  # 1600 px wide, 2x default
    tool.scale_tiles[1].click()
    assert "6400" in tool.size_label.text()

    tool.preview_btn.click()
    _wait(app, lambda: tool._preview_job is None)
    assert not tool.after.pixmap().isNull()
    assert tool.after.pixmap().width() == tool.before.pixmap().width()

    tool.scale_tiles[0].click()
    tool._out_dir = tmp_path / "out"
    run(app, tool)
    with Image.open(tmp_path / "out" / "wide_x2.jpg") as image:
        assert image.size == (3200, 1800)


def test_upscale_card_opens_from_hub(hub):
    hub.open_tool("upscale")
    assert type(hub.current_tool()).__name__ == "UpscaleTool"


# --------------------------------------------------------- drag & drop


def _mime(*paths):
    from PySide6.QtCore import QMimeData, QUrl

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return mime


def _drag_enter(tool, mime):
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QDragEnterEvent

    args = (
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    try:  # QPointF overload is newer; QPoint one is deprecated in 6.12
        event = QDragEnterEvent(QPointF(10, 10), *args)
    except TypeError:
        event = QDragEnterEvent(QPoint(10, 10), *args)
    tool.dragEnterEvent(event)
    return event.isAccepted()


def _drop(tool, mime):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QDropEvent

    event = QDropEvent(
        QPointF(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    tool.dropEvent(event)


def test_drop_files_and_folders(hub, images, tmp_path):
    hub.open_tool("convert")
    tool = hub.current_tool()
    assert tool.acceptDrops()

    mime = _mime(images / "wide.jpg")
    assert _drag_enter(tool, mime)
    assert tool.file_list.property("dropTarget") is True
    _drop(tool, mime)
    assert tool.file_list.property("dropTarget") is False
    assert tool.file_list.count() == 1

    _drop(tool, _mime(images))  # a folder adds what is inside
    assert tool.file_list.count() == 2


def test_drop_rejects_unsupported_and_reports_duplicates(hub, images, tmp_path):
    hub.open_tool("convert")
    tool = hub.current_tool()
    note = tmp_path / "notes.txt"
    note.write_text("x")
    assert not _drag_enter(tool, _mime(note))  # "not allowed" cursor

    _drop(tool, _mime(images / "wide.jpg"))
    _drop(tool, _mime(images / "wide.jpg"))
    assert tool.file_list.count() == 1
    assert "Nothing new" in tool.status.text()
