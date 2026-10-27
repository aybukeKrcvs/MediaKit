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
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from mediakit.core.batch import WorkFn
from mediakit.core.models import ModelStore
from mediakit.core.onnx import available_device
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
from mediakit.ui.tiles import ChoiceTile, DrawFn, glyph_drawing
from mediakit.ui.worker import TaskJob

MODEL_KEYS: tuple[str, ...] = tuple(MODELS)
BACKGROUNDS: tuple[Background, ...] = (Background.TRANSPARENT, Background.WHITE, Background.COLOR)
PREVIEW_SIZE = QSize(380, 250)
PREVIEW_MAX = 640  # px, longest side of the image the preview runs on
TILE = QSize(104, 100)


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


def _to_qimage(image: Image.Image) -> QImage:
    rgba = image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    return QImage(
        data, rgba.width, rgba.height, rgba.width * 4, QImage.Format.Format_RGBA8888
    ).copy()


class BackgroundTool(ImageToolBase):
    def __init__(self, parent: QWidget | None = None, store: ModelStore | None = None) -> None:
        self._store = store or ModelStore()
        self._color = QColor(40, 40, 40)
        self._download: TaskJob | None = None
        self._preview_job: TaskJob | None = None
        super().__init__(parent)

    # ============================================================== build

    def build_options(self, layout: QVBoxLayout) -> None:
        body = QHBoxLayout()
        body.setSpacing(18)
        controls = QVBoxLayout()
        controls.setSpacing(10)
        body.addLayout(controls, 1)

        # --- model ---
        self.model_label = QLabel()
        self.model_label.setObjectName("SectionLabel")
        controls.addWidget(self.model_label)
        model_row = QHBoxLayout()
        self.model_group = QButtonGroup(self)
        self.model_tiles: list[ChoiceTile] = []
        for index in range(len(MODEL_KEYS)):
            tile = ChoiceTile(glyph_drawing("background"), size=TILE)
            self.model_group.addButton(tile, index)
            self.model_tiles.append(tile)
            model_row.addWidget(tile)
        model_row.addStretch(1)
        controls.addLayout(model_row)
        self.model_tiles[MODEL_KEYS.index("standard")].setChecked(True)

        # --- download / status ---
        status_row = QHBoxLayout()
        self.model_status = QLabel()
        self.model_status.setObjectName("Muted")
        self.download_btn = QPushButton()
        self.download_btn.setObjectName("PrimaryButton")
        self.download_cancel = QPushButton()
        self.download_bar = QProgressBar()
        self.download_bar.setObjectName("Progress")
        self.download_bar.setFixedWidth(180)
        status_row.addWidget(self.model_status)
        status_row.addWidget(self.download_bar)
        status_row.addWidget(self.download_btn)
        status_row.addWidget(self.download_cancel)
        status_row.addStretch(1)
        controls.addLayout(status_row)

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
        self.device_label = QLabel()
        self.device_label.setObjectName("Muted")
        controls.addWidget(self.device_label)
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
        self.model_group.idToggled.connect(lambda _i, on: on and self._refresh_model())
        self.download_btn.clicked.connect(self._start_download)
        self.download_cancel.clicked.connect(self._cancel_download)
        self.bg_group.idToggled.connect(lambda _i, on: on and self._on_background())
        self.color_btn.clicked.connect(self._pick_color)
        self.preview_btn.clicked.connect(self._start_preview)

        self._on_background()
        self._refresh_model()

    # =============================================================== i18n

    def retranslate_options(self) -> None:
        self.model_label.setText(self.tr("Model"))
        self.bg_label.setText(self.tr("New background"))
        texts = {
            "fast": (self.tr("Fast"), self.tr("Quick, softer edges.")),
            "standard": (self.tr("Standard"), self.tr("Cleaner edges, a few seconds per image.")),
        }
        for key, tile in zip(MODEL_KEYS, self.model_tiles, strict=True):
            label, tooltip = texts[key]
            tile.set_texts(label, f"{MODELS[key].spec.size_mb} MB", tooltip)
        bg_texts = (
            (self.tr("None"), self.tr("Transparent PNG")),
            (self.tr("White"), self.tr("White background, saved as JPG")),
            (self.tr("Colour"), self.tr("Any colour, saved as JPG")),
        )
        for tile, (label, tooltip) in zip(self.bg_tiles, bg_texts, strict=True):
            tile.set_texts(label, "", tooltip)
        self.color_btn.setText(self.tr("Pick colour..."))
        self.crop_check.setText(self.tr("Crop to the subject"))
        self.download_cancel.setText(self.tr("Cancel"))
        self.preview_btn.setText(self.tr("Preview selected image"))
        if self.preview.pixmap() is None or self.preview.pixmap().isNull():
            self.preview.setText(self.tr("Preview"))
        self.device_label.setText(self.tr("Runs on: %1").replace("%1", available_device()))
        self._refresh_model()

    def run_text(self) -> str:
        return self.tr("Remove background")

    def option_widgets(self) -> list[QWidget]:
        return [
            *self.model_tiles,
            *self.bg_tiles,
            self.color_btn,
            self.crop_check,
        ]

    def _update_enabled(self) -> None:
        # Base handles the common widgets; these two also depend on the
        # model being installed and on no download/preview in flight.
        super()._update_enabled()
        busy = self.is_running() or self._download is not None
        self.download_btn.setEnabled(not busy)
        self.preview_btn.setEnabled(self._model_ready() and not busy and self._preview_job is None)

    # ============================================================== model

    def _model_key(self) -> str:
        return MODEL_KEYS[max(0, self.model_group.checkedId())]

    def _model_ready(self) -> bool:
        return self._store.is_installed(MODELS[self._model_key()].spec)

    def _refresh_model(self) -> None:
        if not hasattr(self, "download_btn"):
            return
        downloading = self._download is not None
        ready = self._model_ready()
        spec = MODELS[self._model_key()].spec
        self.download_bar.setVisible(downloading)
        self.download_cancel.setVisible(downloading)
        self.download_btn.setVisible(not ready and not downloading)
        self.download_btn.setText(self.tr("Download (%1 MB)").replace("%1", str(spec.size_mb)))
        if downloading:
            self.model_status.setText(self.tr("Downloading..."))
        elif ready:
            self.model_status.setText(self.tr("\u2713 Model installed, works offline"))
        else:
            self.model_status.setText(self.tr("Needs a one-time download."))
        self.refresh_state()

    def _start_download(self) -> None:
        if self._download is not None:
            return
        spec = MODELS[self._model_key()].spec
        store = self._store
        self._download = TaskJob(
            lambda progress, cancel: store.download(spec, progress, cancel), self
        )
        self._download.progress.connect(self._on_download_progress)
        self._download.finished.connect(lambda _path: self._download_done(None))
        self._download.failed.connect(self._download_done)
        self.download_bar.setRange(0, 1000)
        self.download_bar.setValue(0)
        for tile in self.model_tiles:
            tile.setEnabled(False)
        self._download.start()
        self._refresh_model()

    def _on_download_progress(self, done: int, total: int) -> None:
        if total:
            self.download_bar.setValue(round(1000 * done / total))
            self.download_bar.setFormat(f"{done / 1e6:.0f} / {total / 1e6:.0f} MB")

    def _cancel_download(self) -> None:
        if self._download is not None:
            self._download.cancel()

    def _download_done(self, error: str | None) -> None:
        cancelled = self._download is not None and self._download.cancel_token.cancelled
        self._download = None
        for tile in self.model_tiles:
            tile.setEnabled(True)
        self._refresh_model()
        if cancelled:
            self.status.setText(self.tr("Download cancelled."))
        elif error:
            self.status.setText(self.tr("Download failed: %1").replace("%1", error))
        else:
            self.status.setText(self.tr("Model ready."))

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
        self._preview_job.start()

    def _show_preview(self, image: Image.Image) -> None:
        self._preview_job = None
        qimage = _to_qimage(image).scaled(
            PREVIEW_SIZE - QSize(4, 4),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview.setPixmap(_checker_pixmap(qimage))
        self._refresh_model()

    def _preview_failed(self, message: str) -> None:
        self._preview_job = None
        self.preview.setText(self.tr("Preview failed: %1").replace("%1", message))
        self._refresh_model()

    # ================================================================ run

    def can_run(self) -> bool:
        return self._model_ready() and self._download is None

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
