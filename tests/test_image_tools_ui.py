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

from mediakit.modules.image.hub import build_image_hub

L, N = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton


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


def test_coming_soon_tool_does_not_open(hub):
    hub.open_tool("metadata")
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
