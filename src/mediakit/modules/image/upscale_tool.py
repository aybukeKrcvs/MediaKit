"""Upscale tool.

Preview is a side-by-side of the same small region of the selected
image: on the left a plain Lanczos enlargement (what any resize does),
on the right the AI result. Both at 1:1 pixels, so the difference is
real and not a scaling artefact of the preview box.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from mediakit.core.batch import WorkFn
from mediakit.core.models import ModelStore
from mediakit.core.onnx import available_device, unload_all
from mediakit.core.paths import ConflictPolicy
from mediakit.modules.image.ops import auto_orient
from mediakit.modules.image.tools import ImageToolBase
from mediakit.modules.image.upscale import (
    MAX_OUTPUT_PIXELS,
    MODELS,
    Scale,
    TileRunner,
    make_upscale_job,
    output_size,
    upscale_image,
)
from mediakit.ui.model_panel import ModelPanel
from mediakit.ui.qimage import pil_to_qimage
from mediakit.ui.tiles import ChoiceTile, text_drawing
from mediakit.ui.worker import TaskJob

MODEL_KEYS: tuple[str, ...] = tuple(MODELS)
SCALES: tuple[Scale, ...] = (Scale.X2, Scale.X4)
PANE = 220  # px, each side of the before/after preview


def _crop_for_preview(path: Path, scale: int) -> Image.Image:
    """Centre region that becomes exactly PANE px after enlarging."""
    side = PANE // scale
    with Image.open(path) as opened:
        image = auto_orient(opened)
        image.load()
    image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
    side = min(side, image.width, image.height)
    left = (image.width - side) // 2
    top = (image.height - side) // 2
    return image.crop((left, top, left + side, top + side))


def _image_size(path: Path) -> tuple[int, int] | None:
    try:
        with Image.open(path) as opened:
            return auto_orient(opened).size
    except OSError:
        return None


class UpscaleTool(ImageToolBase):
    def __init__(self, parent: QWidget | None = None, store: ModelStore | None = None) -> None:
        self._store = store or ModelStore()
        self._preview_job: TaskJob | None = None
        super().__init__(parent)
        self.current_file_changed.connect(lambda _path: self._refresh_size())
        self.file_list.model().rowsInserted.connect(lambda *_: self._refresh_size())
        self.file_list.model().rowsRemoved.connect(lambda *_: self._refresh_size())

    # ============================================================== build

    def build_options(self, layout: QVBoxLayout) -> None:
        body = QHBoxLayout()
        body.setSpacing(18)
        controls = QVBoxLayout()
        controls.setSpacing(10)
        body.addLayout(controls, 1)

        # Adaptive default: the large model only makes sense on a GPU.
        on_gpu = available_device().startswith("GPU")
        self.model_panel = ModelPanel(
            MODEL_KEYS,
            lambda key: MODELS[key].spec,
            "quality" if on_gpu else "fast",
            "upscale",
            self._store,
        )
        controls.addWidget(self.model_panel)

        self.scale_label = QLabel()
        self.scale_label.setObjectName("SectionLabel")
        controls.addWidget(self.scale_label)
        scale_row = QHBoxLayout()
        self.scale_group = QButtonGroup(self)
        self.scale_tiles = [
            ChoiceTile(text_drawing(f"{int(s)}\u00d7"), size=QSize(88, 92)) for s in SCALES
        ]
        for index, tile in enumerate(self.scale_tiles):
            self.scale_group.addButton(tile, index)
            scale_row.addWidget(tile)
        scale_row.addStretch(1)
        controls.addLayout(scale_row)
        self.scale_tiles[0].setChecked(True)

        self.size_label = QLabel()
        self.size_label.setObjectName("Muted")
        self.size_label.setWordWrap(True)
        controls.addWidget(self.size_label)
        self.cpu_hint = QLabel()
        self.cpu_hint.setObjectName("Muted")
        self.cpu_hint.setWordWrap(True)
        self.cpu_hint.setVisible(not on_gpu)
        controls.addWidget(self.cpu_hint)
        controls.addStretch(1)

        # --- before / after preview ---
        preview_col = QVBoxLayout()
        panes = QHBoxLayout()
        panes.setSpacing(8)
        self.before, self.after = QLabel(), QLabel()
        self.before_caption, self.after_caption = QLabel(), QLabel()
        for pane, caption in ((self.before, self.before_caption), (self.after, self.after_caption)):
            column = QVBoxLayout()
            pane.setObjectName("PreviewBox")
            pane.setFixedSize(QSize(PANE + 4, PANE + 4))
            pane.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pane.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            caption.setObjectName("Muted")
            column.addWidget(pane)
            column.addWidget(caption)
            panes.addLayout(column)
        preview_col.addLayout(panes)
        self.preview_btn = QPushButton()
        preview_col.addWidget(self.preview_btn, 0, Qt.AlignmentFlag.AlignLeft)
        preview_col.addStretch(1)
        body.addLayout(preview_col)
        layout.addLayout(body)

        self.model_panel.changed.connect(self.refresh_state)
        # self.status is created by the base after build_options returns.
        self.model_panel.message.connect(lambda text: self.status.setText(text))
        self.scale_group.idToggled.connect(lambda _i, on: on and self._refresh_size())
        self.preview_btn.clicked.connect(self._start_preview)

    # =============================================================== i18n

    def retranslate_options(self) -> None:
        self.model_panel.set_choice_texts(
            {
                "fast": (
                    self.tr("Fast"),
                    self.tr("Small model, seconds per image. Good for most photos."),
                ),
                "quality": (
                    self.tr("Quality"),
                    self.tr("Sharper detail. Much slower, best on a GPU."),
                ),
            }
        )
        self.model_panel.retranslate()
        self.scale_label.setText(self.tr("Enlarge"))
        self.scale_tiles[0].set_texts("", "", self.tr("Twice the width and height"))
        self.scale_tiles[1].set_texts("", "", self.tr("Four times the width and height"))
        self.cpu_hint.setText(
            self.tr("No GPU found: large images can take minutes each on the CPU.")
        )
        self.before_caption.setText(self.tr("Plain resize"))
        self.after_caption.setText(self.tr("AI upscale"))
        self.preview_btn.setText(self.tr("Preview selected image"))
        for pane in (self.before, self.after):
            if pane.pixmap() is None or pane.pixmap().isNull():
                pane.setText(self.tr("Preview"))
        self._refresh_size()

    def run_text(self) -> str:
        return self.tr("Upscale")

    def option_widgets(self) -> list[QWidget]:
        return [*self.scale_tiles]

    def _update_enabled(self) -> None:
        super()._update_enabled()
        busy = self.is_running() or self.model_panel.is_downloading()
        self.model_panel.set_locked(self.is_running() or self._preview_job is not None)
        self.preview_btn.setEnabled(
            self.model_panel.is_ready() and not busy and self._preview_job is None
        )

    # ============================================================== state

    def _scale(self) -> int:
        return int(SCALES[max(0, self.scale_group.checkedId())])

    def _preview_path(self) -> Path | None:
        path = self.current_file()
        if path is None and self.file_list.count():
            path = self.file_list.item(0).data(Qt.ItemDataRole.UserRole)
        return path

    def _refresh_size(self) -> None:
        if not hasattr(self, "size_label"):
            return
        path = self._preview_path()
        size = _image_size(path) if path is not None else None
        if size is None:
            self.size_label.setText("")
            return
        width, height = output_size(size, self._scale())
        text = self.tr("%1: %2 \u00d7 %3 px \u2192 %4 \u00d7 %5 px")
        for key, value in (("%1", path.name), ("%2", size[0]), ("%3", size[1])):
            text = text.replace(key, str(value))
        text = text.replace("%4", str(width)).replace("%5", str(height))
        if width * height > MAX_OUTPUT_PIXELS:
            text += "\n" + self.tr("Too large for this scale, it will be skipped as an error.")
        self.size_label.setText(text)

    # ============================================================ preview

    def _start_preview(self) -> None:
        path = self._preview_path()
        if path is None or self._preview_job is not None or not self.model_panel.is_ready():
            return
        model = MODELS[self.model_panel.current_key()]
        model_path = self.model_panel.model_path()
        scale = self._scale()

        def task(_progress, _cancel):
            crop = _crop_for_preview(path, scale)
            size = (crop.width * scale, crop.height * scale)
            plain = crop.resize(size, Image.Resampling.LANCZOS)
            ai = upscale_image(crop, model, TileRunner(model_path), scale)
            return plain, ai

        self._preview_job = TaskJob(task, self)
        self._preview_job.finished.connect(self._show_preview)
        self._preview_job.failed.connect(self._preview_failed)
        for pane in (self.before, self.after):
            pane.setPixmap(QPixmap())
            pane.setText(self.tr("Working..."))
        self._update_enabled()
        self._preview_job.start()

    def _show_preview(self, result: tuple[Image.Image, Image.Image]) -> None:
        self._preview_job = None
        for pane, image in zip((self.before, self.after), result, strict=True):
            pane.setPixmap(QPixmap.fromImage(pil_to_qimage(image)))
        self.refresh_state()

    def _preview_failed(self, message: str) -> None:
        self._preview_job = None
        self.before.setText("")
        self.after.setText(self.tr("Preview failed: %1").replace("%1", message))
        self.refresh_state()

    # ================================================================ run

    def can_run(self) -> bool:
        return self.model_panel.is_ready() and not self.model_panel.is_downloading()

    def _on_finished(self, report) -> None:
        super()._on_finished(report)
        # Give the GPU memory back. Upscaling is the heaviest thing in
        # the app, and a cached session holds its buffers for as long as
        # the app runs; re-creating it on the next run costs a second.
        unload_all()

    def make_work(self, out_dir: Path | None, policy: ConflictPolicy) -> WorkFn:
        return make_upscale_job(
            out_dir,
            policy,
            self.model_panel.current_key(),
            self._store,
            self._scale(),
            on_tile=self.item_progress.emit,
            cancel=self.cancel_token(),
        )
