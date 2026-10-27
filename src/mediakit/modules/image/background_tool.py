"""Remove background tool.

First use downloads the chosen model (with progress and cancel); after
that everything is offline. Preview runs the real model on a small copy
of the selected image in a worker thread, so the UI never freezes.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from mediakit.core.batch import WorkFn
from mediakit.core.models import ModelStore
from mediakit.core.paths import ConflictPolicy
from mediakit.modules.image.background import (
    MODELS,
    Background,
    apply_mask,
    make_background_job,
    predict_mask,
)
from mediakit.modules.image.ops import auto_orient
from mediakit.modules.image.tools import ImageToolBase
from mediakit.ui.model_panel import ModelPanel
from mediakit.ui.qimage import pil_to_qimage
from mediakit.ui.tiles import ChoiceTile, DrawFn
from mediakit.ui.worker import TaskJob

MODEL_KEYS: tuple[str, ...] = tuple(MODELS)
BACKGROUNDS: tuple[Background, ...] = (Background.TRANSPARENT, Background.WHITE, Background.COLOR)
PREVIEW_SIZE = QSize(380, 250)
PREVIEW_MAX = 640  # px, longest side of the image the preview runs on


def _checker(p: QPainter, rect: QRectF, cell: float = 6.0) -> None:
    light, dark = QColor(235, 235, 235), QColor(190, 190, 190)
    y = rect.top()
    row = 0
    while y < rect.bottom():
        x = rect.left()
        col = 0
        while x < rect.right():
            p.fillRect(
                QRectF(x, y, min(cell, rect.right() - x), min(cell, rect.bottom() - y)),
                dark if (row + col) % 2 else light,
            )
            x += cell
            col += 1
        y += cell
        row += 1


def _swatch_drawing(color_fn) -> DrawFn:
    def draw(p: QPainter, rect: QRectF, ink: QColor, _accent: QColor) -> None:
        side = min(rect.width(), rect.height()) * 0.7
        box = QRectF(rect.center().x() - side / 2, rect.center().y() - side / 2, side, side)
        color = color_fn()
        if color is None:
            _checker(p, box)
        else:
            p.fillRect(box, color)
        p.setPen(QPen(ink, 1.5))
        p.drawRect(box)

    return draw


def _checker_pixmap(image: QImage) -> QPixmap:
    pixmap = QPixmap(image.size())
    painter = QPainter(pixmap)
    _checker(painter, QRectF(0, 0, image.width(), image.height()), 10)
    painter.drawImage(0, 0, image)
    painter.end()
    return pixmap


class BackgroundTool(ImageToolBase):
    def __init__(self, parent: QWidget | None = None, store: ModelStore | None = None) -> None:
        self._store = store or ModelStore()
        self._color = QColor(40, 40, 40)
        self._preview_job: TaskJob | None = None
        super().__init__(parent)

    # ============================================================== build

    def build_options(self, layout: QVBoxLayout) -> None:
        body = QHBoxLayout()
        body.setSpacing(18)
        controls = QVBoxLayout()
        controls.setSpacing(10)
        body.addLayout(controls, 1)

        # --- model (picker + one-time download) ---
        self.model_panel = ModelPanel(
            MODEL_KEYS, lambda key: MODELS[key].spec, "standard", "background", self._store
        )
        controls.addWidget(self.model_panel)

        # --- background ---
        self.bg_label = QLabel()
        self.bg_label.setObjectName("SectionLabel")
        controls.addWidget(self.bg_label)
        bg_row = QHBoxLayout()
        self.bg_group = QButtonGroup(self)
        swatches = (lambda: None, lambda: QColor(255, 255, 255), lambda: self._color)
        self.bg_tiles = [ChoiceTile(_swatch_drawing(fn), size=QSize(88, 92)) for fn in swatches]
        for index, tile in enumerate(self.bg_tiles):
            self.bg_group.addButton(tile, index)
            bg_row.addWidget(tile)
        self.bg_tiles[0].setChecked(True)
        self.color_btn = QPushButton()
        bg_row.addWidget(self.color_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        bg_row.addStretch(1)
        controls.addLayout(bg_row)

        self.crop_check = QCheckBox()
        controls.addWidget(self.crop_check)
        controls.addStretch(1)

        # --- preview ---
        preview_col = QVBoxLayout()
        self.preview = QLabel()
        self.preview.setObjectName("PreviewBox")
        self.preview.setFixedSize(PREVIEW_SIZE)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.preview_btn = QPushButton()
        preview_col.addWidget(self.preview)
        preview_col.addWidget(self.preview_btn, 0, Qt.AlignmentFlag.AlignLeft)
        preview_col.addStretch(1)
        body.addLayout(preview_col)
        layout.addLayout(body)

        # --- signals ---
        self.model_panel.changed.connect(self.refresh_state)
        # self.status is created by the base after build_options returns.
        self.model_panel.message.connect(lambda text: self.status.setText(text))
        self.bg_group.idToggled.connect(lambda _i, on: on and self._on_background())
        self.color_btn.clicked.connect(self._pick_color)
        self.preview_btn.clicked.connect(self._start_preview)

        self._on_background()

    # =============================================================== i18n

    def retranslate_options(self) -> None:
        self.bg_label.setText(self.tr("New background"))
        texts = {
            "fast": (self.tr("Fast"), self.tr("Quick, softer edges.")),
            "standard": (self.tr("Standard"), self.tr("Cleaner edges, a few seconds per image.")),
        }
        self.model_panel.set_choice_texts(texts)
        self.model_panel.retranslate()
        bg_texts = (
            (self.tr("None"), self.tr("Transparent PNG")),
            (self.tr("White"), self.tr("White background, saved as JPG")),
            (self.tr("Colour"), self.tr("Any colour, saved as JPG")),
        )
        for tile, (label, tooltip) in zip(self.bg_tiles, bg_texts, strict=True):
            tile.set_texts(label, "", tooltip)
        self.color_btn.setText(self.tr("Pick colour..."))
        self.crop_check.setText(self.tr("Crop to the subject"))
        self.preview_btn.setText(self.tr("Preview selected image"))
        if self.preview.pixmap() is None or self.preview.pixmap().isNull():
            self.preview.setText(self.tr("Preview"))

    def run_text(self) -> str:
        return self.tr("Remove background")

    def option_widgets(self) -> list[QWidget]:
        return [
            *self.bg_tiles,
            self.color_btn,
            self.crop_check,
        ]

    def _update_enabled(self) -> None:
        # Base handles the common widgets; these two also depend on the
        # model being installed and on no download/preview in flight.
        super()._update_enabled()
        busy = self.is_running() or self.model_panel.is_downloading()
        self.model_panel.set_locked(self.is_running() or self._preview_job is not None)
        self.preview_btn.setEnabled(self._model_ready() and not busy and self._preview_job is None)

    # ============================================================== model

    # Kept as attributes of the tool so callers and tests need not know
    # the picker is a separate widget.
    @property
    def model_tiles(self) -> list[ChoiceTile]:
        return self.model_panel.tiles

    @property
    def download_btn(self) -> QPushButton:
        return self.model_panel.download_btn

    @property
    def _download(self):
        return self.model_panel._download

    def _model_key(self) -> str:
        return self.model_panel.current_key()

    def _model_ready(self) -> bool:
        return self.model_panel.is_ready()

    # ========================================================= background

    def _background(self) -> Background:
        return BACKGROUNDS[max(0, self.bg_group.checkedId())]

    def _on_background(self) -> None:
        self.color_btn.setVisible(self._background() == Background.COLOR)

    def _pick_color(self) -> None:
        color = QColorDialog.getColor(self._color, self, self.tr("Background colour"))
        if color.isValid():
            self._color = color
            self.bg_tiles[2].update()
            swatch = QPixmap(14, 14)
            swatch.fill(color)
            self.color_btn.setIcon(QIcon(swatch))

    def _rgb(self) -> tuple[int, int, int]:
        return (self._color.red(), self._color.green(), self._color.blue())

    # ============================================================ preview

    def _start_preview(self) -> None:
        path = self.current_file()
        if path is None and self.file_list.count():
            path = self.file_list.item(0).data(Qt.ItemDataRole.UserRole)
        if path is None or self._preview_job is not None or not self._model_ready():
            return
        model = MODELS[self._model_key()]
        model_path = self._store.path(model.spec)
        background, color, crop = self._background(), self._rgb(), self.crop_check.isChecked()

        def task(_progress, _cancel):
            with Image.open(path) as opened:
                image = auto_orient(opened)
                image.thumbnail((PREVIEW_MAX, PREVIEW_MAX))
                image = image.copy()
            mask = predict_mask(image, model, model_path)
            return apply_mask(image, mask, background, color, crop)

        self._preview_job = TaskJob(task, self)
        self._preview_job.finished.connect(self._show_preview)
        self._preview_job.failed.connect(self._preview_failed)
        self.preview.setText(self.tr("Working..."))
        self.preview_btn.setEnabled(False)
        self._update_enabled()
        self._preview_job.start()

    def _show_preview(self, image: Image.Image) -> None:
        self._preview_job = None
        qimage = pil_to_qimage(image).scaled(
            PREVIEW_SIZE - QSize(4, 4),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview.setPixmap(_checker_pixmap(qimage))
        self.refresh_state()

    def _preview_failed(self, message: str) -> None:
        self._preview_job = None
        self.preview.setText(self.tr("Preview failed: %1").replace("%1", message))
        self.refresh_state()

    # ================================================================ run

    def can_run(self) -> bool:
        return self._model_ready() and not self.model_panel.is_downloading()

    def make_work(self, out_dir: Path | None, policy: ConflictPolicy) -> WorkFn:
        return make_background_job(
            out_dir,
            policy,
            self._model_key(),
            self._store,
            self._background(),
            self._rgb(),
            self.crop_check.isChecked(),
        )
