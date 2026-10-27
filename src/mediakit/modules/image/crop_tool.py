"""Crop & Rotate tool.

Two modes, because they are different jobs:
  Single - one image, crop drawn by hand on a preview.
  Batch  - many images, one aspect ratio, centred crop.

Rotation is shared: it applies before cropping in both modes, so the
chosen ratio refers to the final orientation.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from mediakit.core.batch import WorkFn
from mediakit.core.paths import ConflictPolicy
from mediakit.modules.image.convert import make_image_job
from mediakit.modules.image.crop_canvas import CropCanvas
from mediakit.modules.image.ops import (
    ASPECT_PRESETS,
    AspectRatio,
    auto_orient,
    make_center_crop,
    make_crop_fraction,
    make_rotate,
    rotation_from_steps,
)
from mediakit.modules.image.tools import ImageToolBase
from mediakit.ui.tiles import (
    ChoiceTile,
    free_drawing,
    glyph_drawing,
    picture_drawing,
    ratio_drawing,
)

RATIO_TILE = QSize(78, 92)


def _scroll_row(tiles: list[ChoiceTile]) -> tuple[QScrollArea, QButtonGroup]:
    """Horizontally scrollable tile strip (fits narrow windows)."""
    host = QWidget()
    row = QHBoxLayout(host)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    group = QButtonGroup(host)
    group.setExclusive(True)
    for index, tile in enumerate(tiles):
        group.addButton(tile, index)
        row.addWidget(tile)
    row.addStretch(1)

    scroll = QScrollArea()
    scroll.setObjectName("TileStrip")
    scroll.setWidget(host)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setFixedHeight(RATIO_TILE.height() + 18)
    return scroll, group


class CropRotateTool(ImageToolBase):
    def __init__(self, parent: QWidget | None = None) -> None:
        self._steps = 0
        super().__init__(parent)
        self.current_file_changed.connect(self._load_preview)
        self._set_mode(single=True)

    # ============================================================== build

    def build_options(self, layout: QVBoxLayout) -> None:
        # --- mode + rotate, one compact row ---
        top = QHBoxLayout()
        top.setSpacing(8)
        self.single_btn = QPushButton()
        self.batch_btn = QPushButton()
        self.mode_group = QButtonGroup(self)
        for index, btn in enumerate((self.single_btn, self.batch_btn)):
            btn.setObjectName("SegmentButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.mode_group.addButton(btn, index)
            top.addWidget(btn)
        self.single_btn.setChecked(True)
        top.addSpacing(24)

        self.rotate_label = QLabel()
        self.rotate_label.setObjectName("SectionLabel")
        top.addWidget(self.rotate_label)
        self.rotate_ccw = ChoiceTile(glyph_drawing("rotate_ccw"), size=QSize(40, 40))
        self.rotate_cw = ChoiceTile(glyph_drawing("rotate_cw"), size=QSize(40, 40))
        for tile in (self.rotate_ccw, self.rotate_cw):
            tile.setCheckable(False)
            top.addWidget(tile)
        self.angle_label = QLabel("0\u00b0")
        self.angle_label.setObjectName("Muted")
        self.angle_label.setMinimumWidth(36)
        top.addWidget(self.angle_label)
        top.addStretch(1)
        layout.addLayout(top)

        # --- single mode: canvas + ratio lock ---
        self.single_page = QWidget()
        single = QVBoxLayout(self.single_page)
        single.setContentsMargins(0, 0, 0, 0)
        single.setSpacing(8)
        self.canvas = CropCanvas()
        self.canvas.setObjectName("CropCanvas")
        single.addWidget(self.canvas, 1)

        lock_row = QHBoxLayout()
        self.lock_label = QLabel()
        self.lock_label.setObjectName("SectionLabel")
        self.crop_size_label = QLabel()
        self.crop_size_label.setObjectName("Muted")
        self.reset_btn = QPushButton()
        lock_row.addWidget(self.lock_label)
        lock_row.addStretch(1)
        lock_row.addWidget(self.crop_size_label)
        lock_row.addWidget(self.reset_btn)
        single.addLayout(lock_row)

        self.single_ratio_tiles = [ChoiceTile(free_drawing(), size=RATIO_TILE)] + [
            ChoiceTile(ratio_drawing(r.w, r.h), size=RATIO_TILE) for r in ASPECT_PRESETS
        ]
        strip, self.single_ratio_group = _scroll_row(self.single_ratio_tiles)
        self.single_ratio_tiles[0].setChecked(True)
        single.addWidget(strip)
        layout.addWidget(self.single_page, 1)

        # --- batch mode: centred crop to a ratio ---
        self.batch_page = QWidget()
        batch = QVBoxLayout(self.batch_page)
        batch.setContentsMargins(0, 0, 0, 0)
        batch.setSpacing(8)
        self.batch_label = QLabel()
        self.batch_label.setObjectName("SectionLabel")
        batch.addWidget(self.batch_label)
        self.batch_ratio_tiles = [ChoiceTile(picture_drawing(), size=RATIO_TILE)] + [
            ChoiceTile(ratio_drawing(r.w, r.h), size=RATIO_TILE) for r in ASPECT_PRESETS
        ]
        strip, self.batch_ratio_group = _scroll_row(self.batch_ratio_tiles)
        self.batch_ratio_tiles[1].setChecked(True)  # 1:1
        batch.addWidget(strip)
        self.batch_hint = QLabel()
        self.batch_hint.setObjectName("Muted")
        self.batch_hint.setWordWrap(True)
        batch.addWidget(self.batch_hint)
        layout.addWidget(self.batch_page)

        # --- signals ---
        self.mode_group.idToggled.connect(
            lambda index, checked: checked and self._set_mode(single=index == 0)
        )
        self.rotate_cw.clicked.connect(lambda: self._rotate(1))
        self.rotate_ccw.clicked.connect(lambda: self._rotate(-1))
        self.single_ratio_group.idToggled.connect(self._on_single_ratio)
        self.batch_ratio_group.idToggled.connect(lambda *_: self.refresh_state())
        self.reset_btn.clicked.connect(self.canvas.reset_crop)
        self.canvas.crop_changed.connect(self._on_crop_changed)

    # =============================================================== i18n

    def _ratio_texts(self) -> dict[str, tuple[str, str]]:
        return {
            "1:1": (self.tr("Square"), self.tr("Square, e.g. an Instagram post")),
            "4:3": (self.tr("Classic"), self.tr("Classic photo / SD screen")),
            "3:4": (self.tr("Portrait"), self.tr("Classic photo, portrait")),
            "16:9": (self.tr("Wide"), self.tr("Widescreen / HD video")),
            "9:16": (self.tr("Stories"), self.tr("Vertical: Stories & Reels")),
            "21:9": (self.tr("Ultrawide"), self.tr("Ultra-widescreen / cinema")),
            "9:21": (self.tr("Ultra-tall"), self.tr("Ultra-tall vertical")),
        }

    def retranslate_options(self) -> None:
        self.single_btn.setText(self.tr("Single image"))
        self.single_btn.setToolTip(self.tr("Draw the crop by hand on one image."))
        self.batch_btn.setText(self.tr("Batch"))
        self.batch_btn.setToolTip(self.tr("Crop many images to the same ratio, centred."))
        self.rotate_label.setText(self.tr("Rotate"))
        self.rotate_ccw.set_texts("", "", self.tr("Rotate 90\u00b0 left"))
        self.rotate_cw.set_texts("", "", self.tr("Rotate 90\u00b0 right"))
        self.lock_label.setText(self.tr("Aspect ratio"))
        self.reset_btn.setText(self.tr("Reset crop"))
        self.batch_label.setText(self.tr("Crop every image to"))
        self.batch_hint.setText(
            self.tr("Each image keeps its centre; the edges that don't fit the ratio are trimmed.")
        )

        ratio_texts = self._ratio_texts()
        self.single_ratio_tiles[0].set_texts(
            self.tr("Free"), self.tr("Any shape"), self.tr("No fixed ratio")
        )
        self.batch_ratio_tiles[0].set_texts(
            self.tr("Original"), self.tr("No crop"), self.tr("Only rotate, don't crop")
        )
        for ratio, a, b in zip(
            ASPECT_PRESETS, self.single_ratio_tiles[1:], self.batch_ratio_tiles[1:], strict=True
        ):
            caption, tooltip = ratio_texts[ratio.key]
            a.set_texts(ratio.key, caption, tooltip)
            b.set_texts(ratio.key, caption, tooltip)
        self._on_crop_changed()

    def run_text(self) -> str:
        return self.tr("Save")

    def option_widgets(self) -> list[QWidget]:
        return [
            self.single_btn,
            self.batch_btn,
            self.rotate_ccw,
            self.rotate_cw,
            self.reset_btn,
            self.canvas,
            *self.single_ratio_tiles,
            *self.batch_ratio_tiles,
        ]

    # ============================================================== state

    def _is_single(self) -> bool:
        return self.mode_group.checkedId() == 0

    def _set_mode(self, single: bool) -> None:
        self.single_page.setVisible(single)
        self.batch_page.setVisible(not single)
        self.set_single_mode(single)
        if single:
            self._load_preview(self.current_file())

    def _rotate(self, delta: int) -> None:
        self._steps = (self._steps + delta) % 4
        self.angle_label.setText(f"{self._steps * 90}\u00b0")
        self.canvas.set_rotation_steps(self._steps)
        self.refresh_state()

    def _load_preview(self, path: Path | None) -> None:
        if not self._is_single():
            return
        self.canvas.load(path)
        self.canvas.set_rotation_steps(self._steps)
        self.refresh_state()

    def _single_ratio(self) -> AspectRatio | None:
        index = self.single_ratio_group.checkedId()
        return ASPECT_PRESETS[index - 1] if index > 0 else None

    def _batch_ratio(self) -> AspectRatio | None:
        index = self.batch_ratio_group.checkedId()
        return ASPECT_PRESETS[index - 1] if index > 0 else None

    def _on_single_ratio(self, _index: int, checked: bool) -> None:
        if checked:
            ratio = self._single_ratio()
            self.canvas.set_ratio(ratio.value if ratio else None)

    def _on_crop_changed(self) -> None:
        size = self.canvas.crop_pixel_size()
        self.crop_size_label.setText(f"{size[0]} \u00d7 {size[1]}" if size else "")
        self.refresh_state()

    def can_run(self) -> bool:
        if self._is_single():
            return self.canvas.has_image() and self.canvas.crop_fractions() is not None
        # Batch with "Original" and no rotation would be a pointless copy.
        return self._batch_ratio() is not None or self._steps != 0

    # ================================================================ run

    def make_work(self, out_dir: Path | None, policy: ConflictPolicy) -> WorkFn:
        # auto_orient always first: the preview was shown EXIF-oriented,
        # so the crop coordinates only match an oriented image.
        transforms = [auto_orient]
        if self._steps:
            transforms.append(make_rotate(rotation_from_steps(self._steps)))

        cropped = False
        if self._is_single():
            fractions = self.canvas.crop_fractions()
            if fractions is not None and fractions != (0.0, 0.0, 1.0, 1.0):
                transforms.append(make_crop_fraction(*fractions))
                cropped = True
        else:
            ratio = self._batch_ratio()
            if ratio is not None:
                transforms.append(make_center_crop(ratio))
                cropped = True

        return make_image_job(
            out_dir,
            policy=policy,
            transforms=transforms,
            suffix="_cropped" if cropped else "_rotated",
        )
