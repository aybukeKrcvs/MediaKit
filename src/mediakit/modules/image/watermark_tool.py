"""Watermark tool: text or logo, nine positions or tiled, live preview.

The preview runs the exact domain transform on a downscaled copy of
the selected image. Because sizes are fractions of the image width,
what you see is what the full-size export gets.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QColorDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from mediakit.core.batch import WorkFn
from mediakit.core.paths import ConflictPolicy
from mediakit.modules.image.convert import make_image_job
from mediakit.modules.image.ops import Transform, auto_orient
from mediakit.modules.image.tools import ImageToolBase
from mediakit.modules.image.watermark import (
    GRID_POSITIONS,
    Position,
    make_logo_watermark,
    make_text_watermark,
)
from mediakit.ui.tiles import ChoiceTile, DrawFn

PREVIEW_SIZE = QSize(380, 250)
POSITION_TILE = QSize(34, 34)
ALL_POSITIONS: tuple[Position, ...] = (*GRID_POSITIONS, Position.TILED)


def _position_drawing(position: Position) -> DrawFn:
    """Frame with a dot where the watermark goes (or a diagonal pattern)."""

    def draw(p: QPainter, rect: QRectF, ink: QColor, _accent: QColor) -> None:
        frame = rect.adjusted(1, 1, -1, -1)
        p.setPen(QPen(ink, 1.2))
        p.drawRect(frame)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ink)
        if position == Position.TILED:
            for i in range(3):
                for j in range(3):
                    cx = frame.left() + frame.width() * (0.2 + 0.3 * i)
                    cy = frame.top() + frame.height() * (0.2 + 0.3 * j)
                    p.drawRect(QRectF(cx - 1.5, cy - 1.5, 3, 3))
        else:
            index = GRID_POSITIONS.index(position)
            col, row = index % 3, index // 3
            cx = frame.left() + frame.width() * (0.22 + 0.28 * col)
            cy = frame.top() + frame.height() * (0.22 + 0.28 * row)
            p.drawRect(QRectF(QPointF(cx - 3, cy - 3), QSize(6, 6)))
        p.setBrush(Qt.BrushStyle.NoBrush)

    return draw


def _pil_to_qimage(image: Image.Image) -> QImage:
    rgba = image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    # .copy(): QImage would otherwise point at Python-owned bytes.
    return QImage(
        data, rgba.width, rgba.height, rgba.width * 4, QImage.Format.Format_RGBA8888
    ).copy()


class WatermarkTool(ImageToolBase):
    def __init__(self, parent: QWidget | None = None) -> None:
        self._color = QColor(255, 255, 255)
        self._logo: Path | None = None
        self._sizes = {"text": 5, "logo": 20}  # % of image width, per mode
        self._preview_cache: tuple[Path, Image.Image] | None = None
        super().__init__(parent)

    # ============================================================== build

    def build_options(self, layout: QVBoxLayout) -> None:
        body = QHBoxLayout()
        body.setSpacing(18)
        controls = QVBoxLayout()
        controls.setSpacing(10)
        body.addLayout(controls, 1)

        # --- mode ---
        mode_row = QHBoxLayout()
        self.text_btn = QPushButton()
        self.logo_btn = QPushButton()
        self.mode_group = QButtonGroup(self)
        for index, btn in enumerate((self.text_btn, self.logo_btn)):
            btn.setObjectName("SegmentButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.mode_group.addButton(btn, index)
            mode_row.addWidget(btn)
        self.text_btn.setChecked(True)
        mode_row.addStretch(1)
        controls.addLayout(mode_row)

        # --- text input + colour ---
        self.text_row = QWidget()
        text_layout = QHBoxLayout(self.text_row)
        text_layout.setContentsMargins(0, 0, 0, 0)
        self.text_edit = QLineEdit()
        self.text_edit.setMaxLength(80)
        self.color_btn = QPushButton()
        text_layout.addWidget(self.text_edit, 1)
        text_layout.addWidget(self.color_btn)
        controls.addWidget(self.text_row)

        # --- logo picker ---
        self.logo_row = QWidget()
        logo_layout = QHBoxLayout(self.logo_row)
        logo_layout.setContentsMargins(0, 0, 0, 0)
        self.logo_btn_pick = QPushButton()
        self.logo_name = QLabel()
        self.logo_name.setObjectName("Muted")
        logo_layout.addWidget(self.logo_btn_pick)
        logo_layout.addWidget(self.logo_name, 1)
        controls.addWidget(self.logo_row)

        # --- position grid ---
        position_row = QHBoxLayout()
        self.position_label = QLabel()
        self.position_label.setObjectName("SectionLabel")
        position_row.addWidget(self.position_label, 0, Qt.AlignmentFlag.AlignTop)
        grid = QGridLayout()
        grid.setSpacing(4)
        self.position_group = QButtonGroup(self)
        self.position_tiles: list[ChoiceTile] = []
        for index, position in enumerate(ALL_POSITIONS):
            tile = ChoiceTile(_position_drawing(position), size=POSITION_TILE)
            self.position_group.addButton(tile, index)
            self.position_tiles.append(tile)
            if position == Position.TILED:
                grid.addWidget(tile, 1, 4)
            else:
                grid.addWidget(tile, index // 3, index % 3)
        grid.setColumnMinimumWidth(3, 10)
        self.position_tiles[ALL_POSITIONS.index(Position.BOTTOM_RIGHT)].setChecked(True)
        position_row.addLayout(grid)
        position_row.addStretch(1)
        controls.addLayout(position_row)

        # --- size + opacity ---
        self.size_label, self.size_slider, self.size_value = self._slider_row(controls, 1, 40, 5)
        self.opacity_label, self.opacity_slider, self.opacity_value = self._slider_row(
            controls, 10, 100, 60
        )
        controls.addStretch(1)

        # --- preview ---
        self.preview = QLabel()
        self.preview.setObjectName("PreviewBox")
        self.preview.setFixedSize(PREVIEW_SIZE)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        body.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(body)

        # Rendering on every keystroke would stutter on big photos; wait
        # until typing/dragging pauses briefly.
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(120)
        self._preview_timer.timeout.connect(self._render_preview)

        # --- signals ---
        self.mode_group.idToggled.connect(lambda _i, on: on and self._on_mode())
        self.text_edit.textChanged.connect(self._settings_changed)
        self.color_btn.clicked.connect(self._pick_color)
        self.logo_btn_pick.clicked.connect(self._pick_logo)
        self.position_group.idToggled.connect(lambda _i, on: on and self._settings_changed())
        self.size_slider.valueChanged.connect(self._on_size)
        self.opacity_slider.valueChanged.connect(self._on_opacity)
        self.file_list.currentItemChanged.connect(lambda *_: self._schedule_preview())

        self._update_color_icon()
        self._on_mode()

    def _slider_row(
        self, parent: QVBoxLayout, low: int, high: int, value: int
    ) -> tuple[QLabel, QSlider, QLabel]:
        row = QHBoxLayout()
        label = QLabel()
        label.setMinimumWidth(70)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(low, high)
        slider.setValue(value)
        slider.setFixedWidth(180)
        shown = QLabel(f"{value} %")
        shown.setMinimumWidth(44)
        row.addWidget(label)
        row.addWidget(slider)
        row.addWidget(shown)
        row.addStretch(1)
        parent.addLayout(row)
        return label, slider, shown

    # =============================================================== i18n

    def retranslate_options(self) -> None:
        self.text_btn.setText(self.tr("Text"))
        self.logo_btn.setText(self.tr("Logo"))
        self.text_edit.setPlaceholderText(self.tr("\u00a9 Your name"))
        self.color_btn.setText(self.tr("Colour"))
        self.logo_btn_pick.setText(self.tr("Choose logo..."))
        self.logo_name.setText(
            self._logo.name if self._logo else self.tr("PNG with transparency works best")
        )
        self.position_label.setText(self.tr("Position"))
        self.size_label.setText(self.tr("Size"))
        self.opacity_label.setText(self.tr("Opacity"))
        names = {
            Position.TOP_LEFT: self.tr("Top left"),
            Position.TOP: self.tr("Top"),
            Position.TOP_RIGHT: self.tr("Top right"),
            Position.LEFT: self.tr("Left"),
            Position.CENTER: self.tr("Centre"),
            Position.RIGHT: self.tr("Right"),
            Position.BOTTOM_LEFT: self.tr("Bottom left"),
            Position.BOTTOM: self.tr("Bottom"),
            Position.BOTTOM_RIGHT: self.tr("Bottom right"),
            Position.TILED: self.tr("Tiled across the image"),
        }
        for position, tile in zip(ALL_POSITIONS, self.position_tiles, strict=True):
            tile.set_texts("", "", names[position])
        self._schedule_preview()

    def run_text(self) -> str:
        return self.tr("Add watermark")

    def option_widgets(self) -> list[QWidget]:
        return [
            self.text_btn,
            self.logo_btn,
            self.text_edit,
            self.color_btn,
            self.logo_btn_pick,
            self.size_slider,
            self.opacity_slider,
            *self.position_tiles,
        ]

    # ============================================================== state

    def _mode(self) -> str:
        return "logo" if self.mode_group.checkedId() == 1 else "text"

    def _position(self) -> Position:
        return ALL_POSITIONS[max(0, self.position_group.checkedId())]

    def _on_mode(self) -> None:
        mode = self._mode()
        self.text_row.setVisible(mode == "text")
        self.logo_row.setVisible(mode == "logo")
        self.size_slider.blockSignals(True)
        self.size_slider.setValue(self._sizes[mode])
        self.size_slider.blockSignals(False)
        self.size_value.setText(f"{self._sizes[mode]} %")
        self._settings_changed()

    def _on_size(self, value: int) -> None:
        self._sizes[self._mode()] = value
        self.size_value.setText(f"{value} %")
        self._settings_changed()

    def _on_opacity(self, value: int) -> None:
        self.opacity_value.setText(f"{value} %")
        self._settings_changed()

    def _settings_changed(self) -> None:
        self.refresh_state()
        self._schedule_preview()

    def _pick_color(self) -> None:
        color = QColorDialog.getColor(self._color, self, self.tr("Watermark colour"))
        if color.isValid():
            self._color = color
            self._update_color_icon()
            self._settings_changed()

    def _update_color_icon(self) -> None:
        swatch = QPixmap(14, 14)
        swatch.fill(self._color)
        self.color_btn.setIcon(QIcon(swatch))

    def _pick_logo(self) -> None:
        images = self.tr("Images")
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Choose logo"), "", f"{images} (*.png *.webp *.jpg *.jpeg)"
        )
        if path:
            self._logo = Path(path)
            self.logo_name.setText(self._logo.name)
            self._settings_changed()

    def can_run(self) -> bool:
        if self._mode() == "text":
            return bool(self.text_edit.text().strip())
        return self._logo is not None

    def _transform(self) -> Transform | None:
        if not self.can_run():
            return None
        size = self.size_slider.value() / 100
        opacity = self.opacity_slider.value() / 100
        if self._mode() == "text":
            color = (self._color.red(), self._color.green(), self._color.blue())
            return make_text_watermark(
                self.text_edit.text(), self._position(), size, opacity, color
            )
        return make_logo_watermark(self._logo, self._position(), size, opacity)

    # ============================================================ preview

    def _schedule_preview(self) -> None:
        if hasattr(self, "_preview_timer"):
            self._preview_timer.start()

    def _preview_base(self, path: Path) -> Image.Image | None:
        if self._preview_cache and self._preview_cache[0] == path:
            return self._preview_cache[1]
        try:
            with Image.open(path) as image:
                image.draft("RGB", (PREVIEW_SIZE.width() * 2, PREVIEW_SIZE.height() * 2))
                base = auto_orient(image)
                base.thumbnail((PREVIEW_SIZE.width(), PREVIEW_SIZE.height()))
                base = base.copy()
        except Exception:  # noqa: BLE001 - preview is best-effort
            return None
        self._preview_cache = (path, base)
        return base

    def _render_preview(self) -> None:
        path = self.current_file()
        if path is None and self.file_list.count():
            path = self.file_list.item(0).data(Qt.ItemDataRole.UserRole)
        if path is None:
            self.preview.setPixmap(QPixmap())
            self.preview.setText(self.tr("Preview"))
            return
        base = self._preview_base(path)
        if base is None:
            self.preview.setText(self.tr("No preview"))
            return
        transform = self._transform()
        try:
            shown = transform(base) if transform else base
        except Exception:  # noqa: BLE001 - e.g. logo file unreadable
            shown = base
        self.preview.setPixmap(QPixmap.fromImage(_pil_to_qimage(shown)))

    def add_paths(self, paths: list[Path]) -> None:
        super().add_paths(paths)
        self._schedule_preview()

    # ================================================================ run

    def make_work(self, out_dir: Path | None, policy: ConflictPolicy) -> WorkFn:
        transform = self._transform()
        transforms = [auto_orient] + ([transform] if transform else [])
        return make_image_job(out_dir, policy=policy, transforms=transforms, suffix="_watermarked")
