"""Image tools that are a single setting away from running:
Convert, Resize, Compress. Crop & Rotate lives in crop_tool.py.

Each tool is one task. Every tool auto-orients (EXIF) because every
tool re-encodes, and a re-encode without it silently turns phone
photos sideways.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from mediakit.core.batch import WorkFn
from mediakit.core.paths import ConflictPolicy
from mediakit.modules.image.convert import (
    INPUT_EXTENSIONS,
    OUTPUT_FORMATS,
    make_image_job,
)
from mediakit.modules.image.ops import ResizeMode, auto_orient, make_resize
from mediakit.ui.batch_tool import BatchToolScreen, image_thumbnail
from mediakit.ui.tiles import ChoiceTile, DrawFn, text_drawing


class ImageToolBase(BatchToolScreen):
    input_extensions: ClassVar[frozenset[str]] = frozenset(INPUT_EXTENSIONS)

    def thumbnail(self, path: Path) -> QIcon:
        icon = image_thumbnail(path)
        return icon if not icon.isNull() else super().thumbnail(path)


def _tile_row(tiles: list[ChoiceTile]) -> tuple[QHBoxLayout, QButtonGroup]:
    row = QHBoxLayout()
    row.setSpacing(10)
    group = QButtonGroup(row)
    group.setExclusive(True)
    for index, tile in enumerate(tiles):
        group.addButton(tile, index)
        row.addWidget(tile)
    row.addStretch(1)
    return row, group


def _section_label() -> QLabel:
    label = QLabel()
    label.setObjectName("SectionLabel")
    return label


# ================================================================ convert


class ConvertTool(ImageToolBase):
    """Change file format. Quality only where the format is lossy."""

    def build_options(self, layout: QVBoxLayout) -> None:
        self.format_label = _section_label()
        layout.addWidget(self.format_label)

        self.format_tiles = [
            ChoiceTile(text_drawing(fmt.upper()), size=QSize(104, 96)) for fmt in OUTPUT_FORMATS
        ]
        row, self.format_group = _tile_row(self.format_tiles)
        layout.addLayout(row)
        self.format_tiles[OUTPUT_FORMATS.index("jpg")].setChecked(True)

        quality_row = QHBoxLayout()
        self.quality_label = QLabel()
        self.quality_slider = QSlider(Qt.Orientation.Horizontal)
        self.quality_slider.setRange(10, 100)
        self.quality_slider.setValue(90)
        self.quality_slider.setFixedWidth(200)
        self.quality_value = QLabel("90")
        quality_row.addWidget(self.quality_label)
        quality_row.addWidget(self.quality_slider)
        quality_row.addWidget(self.quality_value)
        quality_row.addStretch(1)
        self.quality_host = QWidget()
        self.quality_host.setLayout(quality_row)
        layout.addWidget(self.quality_host)

        self.quality_slider.valueChanged.connect(lambda v: self.quality_value.setText(str(v)))
        self.format_group.idToggled.connect(lambda *_: self._on_format_changed())
        self._on_format_changed()

    def retranslate_options(self) -> None:
        self.format_label.setText(self.tr("Convert to"))
        captions = {
            "png": (self.tr("Lossless"), self.tr("Lossless, keeps transparency. Larger files.")),
            "jpg": (self.tr("Photos"), self.tr("Small files for photos. No transparency.")),
            "webp": (
                self.tr("Smallest"),
                self.tr("Modern format, smallest files, keeps transparency."),
            ),
        }
        for fmt, tile in zip(OUTPUT_FORMATS, self.format_tiles, strict=True):
            caption, tooltip = captions[fmt]
            tile.set_texts(fmt.upper(), caption, tooltip)
        self.quality_label.setText(self.tr("Quality"))

    def run_text(self) -> str:
        return self.tr("Convert")

    def option_widgets(self) -> list[QWidget]:
        return [*self.format_tiles, self.quality_slider]

    def _target_format(self) -> str:
        return OUTPUT_FORMATS[max(0, self.format_group.checkedId())]

    def _on_format_changed(self) -> None:
        # PNG is lossless: a quality slider there would do nothing.
        self.quality_host.setVisible(self._target_format() != "png")

    def make_work(self, out_dir: Path | None, policy: ConflictPolicy) -> WorkFn:
        return make_image_job(
            out_dir,
            policy=policy,
            transforms=[auto_orient],
            target_format=self._target_format(),
            quality=self.quality_slider.value(),
        )


# ================================================================= resize


def _resize_drawing(mode: ResizeMode) -> DrawFn:
    def draw(p: QPainter, rect: QRectF, ink: QColor, accent: QColor) -> None:
        side = min(rect.width(), rect.height())
        box = QRectF(
            rect.center().x() - side / 2, rect.center().y() - side * 0.35, side, side * 0.7
        )
        p.setPen(QPen(ink, 1.6))
        p.drawRect(box)
        pen = QPen(accent, 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        cx, cy = box.center().x(), box.center().y()
        if mode == ResizeMode.MAX_WIDTH:
            p.drawLine(QPointF(box.left() + 4, cy), QPointF(box.right() - 4, cy))
            for x, d in ((box.left() + 4, 1), (box.right() - 4, -1)):
                p.drawLine(QPointF(x, cy), QPointF(x + 5 * d, cy - 4))
                p.drawLine(QPointF(x, cy), QPointF(x + 5 * d, cy + 4))
        elif mode == ResizeMode.MAX_HEIGHT:
            p.drawLine(QPointF(cx, box.top() + 3), QPointF(cx, box.bottom() - 3))
            for y, d in ((box.top() + 3, 1), (box.bottom() - 3, -1)):
                p.drawLine(QPointF(cx, y), QPointF(cx - 4, y + 5 * d))
                p.drawLine(QPointF(cx, y), QPointF(cx + 4, y + 5 * d))
        elif mode == ResizeMode.FIT_BOX:
            inner = box.adjusted(side * 0.18, side * 0.12, -side * 0.18, -side * 0.12)
            p.drawRect(inner)
        else:  # PERCENT
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, "%")

    return draw


RESIZE_MODES: tuple[ResizeMode, ...] = (
    ResizeMode.MAX_WIDTH,
    ResizeMode.MAX_HEIGHT,
    ResizeMode.FIT_BOX,
    ResizeMode.PERCENT,
)


class ResizeTool(ImageToolBase):
    """Change pixel dimensions. Format is kept; aspect ratio always kept."""

    def build_options(self, layout: QVBoxLayout) -> None:
        self.mode_label = _section_label()
        layout.addWidget(self.mode_label)

        self.mode_tiles = [
            ChoiceTile(_resize_drawing(m), size=QSize(104, 100)) for m in RESIZE_MODES
        ]
        row, self.mode_group = _tile_row(self.mode_tiles)
        layout.addLayout(row)
        self.mode_tiles[0].setChecked(True)

        fields = QHBoxLayout()
        self.width_label = QLabel()
        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 20000)
        self.width_spin.setValue(1920)
        self.width_spin.setSuffix(" px")
        self.height_label = QLabel()
        self.height_spin = QSpinBox()
        self.height_spin.setRange(1, 20000)
        self.height_spin.setValue(1080)
        self.height_spin.setSuffix(" px")
        self.percent_label = QLabel()
        self.percent_spin = QSpinBox()
        self.percent_spin.setRange(1, 400)
        self.percent_spin.setValue(50)
        self.percent_spin.setSuffix(" %")
        self.upscale_check = QCheckBox()
        for widget in (
            self.width_label,
            self.width_spin,
            self.height_label,
            self.height_spin,
            self.percent_label,
            self.percent_spin,
            self.upscale_check,
        ):
            fields.addWidget(widget)
        fields.addStretch(1)
        layout.addLayout(fields)

        self.mode_group.idToggled.connect(lambda *_: self._update_fields())
        self._update_fields()

    def retranslate_options(self) -> None:
        self.mode_label.setText(self.tr("Resize by"))
        texts = {
            ResizeMode.MAX_WIDTH: (
                self.tr("Width"),
                self.tr("Max width"),
                self.tr("Limit the width. Height follows the aspect ratio."),
            ),
            ResizeMode.MAX_HEIGHT: (
                self.tr("Height"),
                self.tr("Max height"),
                self.tr("Limit the height. Width follows the aspect ratio."),
            ),
            ResizeMode.FIT_BOX: (
                self.tr("Fit"),
                self.tr("Inside a box"),
                self.tr("Shrink until the image fits inside width x height."),
            ),
            ResizeMode.PERCENT: (
                self.tr("Percent"),
                self.tr("Scale"),
                self.tr("Scale both sides by a percentage."),
            ),
        }
        for mode, tile in zip(RESIZE_MODES, self.mode_tiles, strict=True):
            tile.set_texts(*texts[mode])
        self.width_label.setText(self.tr("Width"))
        self.height_label.setText(self.tr("Height"))
        self.percent_label.setText(self.tr("Scale"))
        self.upscale_check.setText(self.tr("Allow enlarging small images"))

    def run_text(self) -> str:
        return self.tr("Resize")

    def option_widgets(self) -> list[QWidget]:
        return [
            *self.mode_tiles,
            self.width_spin,
            self.height_spin,
            self.percent_spin,
            self.upscale_check,
        ]

    def _mode(self) -> ResizeMode:
        return RESIZE_MODES[max(0, self.mode_group.checkedId())]

    def _update_fields(self) -> None:
        mode = self._mode()
        show_w = mode in (ResizeMode.MAX_WIDTH, ResizeMode.FIT_BOX)
        show_h = mode in (ResizeMode.MAX_HEIGHT, ResizeMode.FIT_BOX)
        show_p = mode == ResizeMode.PERCENT
        self.width_label.setVisible(show_w)
        self.width_spin.setVisible(show_w)
        self.height_label.setVisible(show_h)
        self.height_spin.setVisible(show_h)
        self.percent_label.setVisible(show_p)
        self.percent_spin.setVisible(show_p)
        # Percent already enlarges above 100; the checkbox is for caps.
        self.upscale_check.setVisible(not show_p)

    def make_work(self, out_dir: Path | None, policy: ConflictPolicy) -> WorkFn:
        resize = make_resize(
            self._mode(),
            width=self.width_spin.value(),
            height=self.height_spin.value(),
            percent=self.percent_spin.value(),
            allow_upscale=self.upscale_check.isChecked(),
        )
        return make_image_job(
            out_dir,
            policy=policy,
            transforms=[auto_orient, resize],
            suffix="_resized",
        )


# =============================================================== compress

COMPRESS_PRESETS: tuple[int, ...] = (85, 70, 50)


class CompressTool(ImageToolBase):
    """Smaller files, same format, same dimensions."""

    def build_options(self, layout: QVBoxLayout) -> None:
        self.level_label = _section_label()
        layout.addWidget(self.level_label)

        self.level_tiles = [
            ChoiceTile(text_drawing(str(q)), size=QSize(104, 96)) for q in COMPRESS_PRESETS
        ]
        row, self.level_group = _tile_row(self.level_tiles)
        layout.addLayout(row)
        self.level_tiles[1].setChecked(True)

        quality_row = QHBoxLayout()
        self.quality_label = QLabel()
        self.quality_slider = QSlider(Qt.Orientation.Horizontal)
        self.quality_slider.setRange(10, 100)
        self.quality_slider.setValue(COMPRESS_PRESETS[1])
        self.quality_slider.setFixedWidth(200)
        self.quality_value = QLabel(str(COMPRESS_PRESETS[1]))
        quality_row.addWidget(self.quality_label)
        quality_row.addWidget(self.quality_slider)
        quality_row.addWidget(self.quality_value)
        quality_row.addStretch(1)
        layout.addLayout(quality_row)

        self.png_hint = QLabel()
        self.png_hint.setObjectName("Muted")
        self.png_hint.setWordWrap(True)
        layout.addWidget(self.png_hint)

        self.level_group.idToggled.connect(self._on_preset)
        self.quality_slider.valueChanged.connect(self._on_slider)

    def retranslate_options(self) -> None:
        self.level_label.setText(self.tr("Compression level"))
        texts = (
            (self.tr("Light"), self.tr("Barely visible change.")),
            (self.tr("Balanced"), self.tr("Good size/quality trade-off.")),
            (self.tr("Strong"), self.tr("Smallest files, visible artefacts.")),
        )
        for tile, (label, tooltip) in zip(self.level_tiles, texts, strict=True):
            tile.set_texts(label, "", tooltip)
        self.quality_label.setText(self.tr("Quality"))
        self.png_hint.setText(
            self.tr(
                "PNG is lossless: PNG files are only re-optimised, so savings are small. "
                "Convert them to WebP for real size reductions."
            )
        )

    def run_text(self) -> str:
        return self.tr("Compress")

    def option_widgets(self) -> list[QWidget]:
        return [*self.level_tiles, self.quality_slider]

    def _on_preset(self, index: int, checked: bool) -> None:
        if checked:
            self.quality_slider.blockSignals(True)
            self.quality_slider.setValue(COMPRESS_PRESETS[index])
            self.quality_slider.blockSignals(False)
            self.quality_value.setText(str(COMPRESS_PRESETS[index]))

    def _on_slider(self, value: int) -> None:
        self.quality_value.setText(str(value))
        # A manual value that matches no preset un-highlights the tiles.
        self.level_group.setExclusive(False)
        for tile, preset in zip(self.level_tiles, COMPRESS_PRESETS, strict=True):
            tile.setChecked(value == preset)
        self.level_group.setExclusive(True)

    def make_work(self, out_dir: Path | None, policy: ConflictPolicy) -> WorkFn:
        return make_image_job(
            out_dir,
            policy=policy,
            transforms=[auto_orient],
            quality=self.quality_slider.value(),
            suffix="_compressed",
        )
