"""Qt adapter for image conversion. No conversion logic lives here."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from mediakit.core.batch import BatchReport
from mediakit.core.paths import ConflictPolicy, collect_files
from mediakit.modules.image.convert import (
    INPUT_EXTENSIONS,
    OUTPUT_FORMATS,
    make_convert_job,
)
from mediakit.modules.image.ops import (
    ResizeMode,
    Rotation,
    auto_orient,
    make_resize,
    make_rotate,
)
from mediakit.shell.worker import BatchJob

CONFLICT_POLICIES: tuple[ConflictPolicy, ...] = (
    ConflictPolicy.RENAME,
    ConflictPolicy.OVERWRITE,
    ConflictPolicy.SKIP,
)

RESIZE_MODES: tuple[ResizeMode, ...] = (
    ResizeMode.NONE,
    ResizeMode.MAX_WIDTH,
    ResizeMode.MAX_HEIGHT,
    ResizeMode.FIT_BOX,
    ResizeMode.PERCENT,
)

ROTATIONS: tuple[Rotation, ...] = (
    Rotation.NONE,
    Rotation.CW_90,
    Rotation.ROT_180,
    Rotation.CCW_90,
)

THUMBNAIL_SIZE = 96
_PATH_ROLE = Qt.ItemDataRole.UserRole


def _build_thumbnail(path: Path) -> QIcon:
    """Load an actual preview of the image; a gray placeholder if that fails.

    Loading can fail for formats Qt's bundled image plugins don't cover
    (e.g. some WebP builds) - a placeholder keeps the grid usable rather
    than crashing or leaving a blank cell.
    """
    pixmap = QPixmap(str(path))
    if not pixmap.isNull():
        return QIcon(
            pixmap.scaled(
                THUMBNAIL_SIZE,
                THUMBNAIL_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    placeholder = QPixmap(THUMBNAIL_SIZE, THUMBNAIL_SIZE)
    placeholder.fill(Qt.GlobalColor.transparent)
    painter = QPainter(placeholder)
    painter.setPen(Qt.GlobalColor.gray)
    painter.drawRect(2, 2, THUMBNAIL_SIZE - 4, THUMBNAIL_SIZE - 4)
    painter.drawText(placeholder.rect(), Qt.AlignmentFlag.AlignCenter, "?")
    painter.end()
    return QIcon(placeholder)


class ImageConvertScreen(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._files: list[Path] = []
        self._out_dir: Path | None = None
        self._job: BatchJob | None = None

        self._build_ui()
        self.retranslate()
        self._update_enabled()

    # ---------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)

        self.title = QLabel()
        self.title.setObjectName("ScreenTitle")
        root.addWidget(self.title)

        self.subtitle = QLabel()
        self.subtitle.setObjectName("Muted")
        self.subtitle.setWordWrap(True)
        root.addWidget(self.subtitle)

        # --- source files ---
        source_row = QHBoxLayout()
        self.add_files_btn = QPushButton()
        self.add_folder_btn = QPushButton()
        self.select_all_btn = QPushButton()
        self.select_none_btn = QPushButton()
        self.clear_btn = QPushButton()
        for btn in (
            self.add_files_btn,
            self.add_folder_btn,
            self.select_all_btn,
            self.select_none_btn,
            self.clear_btn,
        ):
            source_row.addWidget(btn)
        source_row.addStretch(1)
        root.addLayout(source_row)

        # Thumbnail grid. Checkboxes make inclusion in the batch optional
        # per file; selection highlight (click) is separate from the
        # checkbox and only used for things like future multi-delete.
        self.file_list = QListWidget()
        self.file_list.setObjectName("FileList")
        self.file_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.file_list.setIconSize(QSize(THUMBNAIL_SIZE, THUMBNAIL_SIZE))
        self.file_list.setGridSize(QSize(THUMBNAIL_SIZE + 24, THUMBNAIL_SIZE + 40))
        self.file_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.file_list.setMovement(QListWidget.Movement.Static)
        self.file_list.setSpacing(6)
        self.file_list.setWordWrap(True)
        self.file_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        root.addWidget(self.file_list, 1)

        # --- output settings ---
        options_row = QHBoxLayout()

        self.format_label = QLabel()
        self.format_combo = QComboBox()
        for fmt in OUTPUT_FORMATS:
            self.format_combo.addItem(fmt.upper(), userData=fmt)
        options_row.addWidget(self.format_label)
        options_row.addWidget(self.format_combo)

        self.quality_label = QLabel()
        self.quality_slider = QSlider(Qt.Orientation.Horizontal)
        self.quality_slider.setRange(10, 100)
        self.quality_slider.setValue(90)
        self.quality_slider.setFixedWidth(140)
        self.quality_value = QLabel("90")
        options_row.addWidget(self.quality_label)
        options_row.addWidget(self.quality_slider)
        options_row.addWidget(self.quality_value)

        self.conflict_label = QLabel()
        self.conflict_combo = QComboBox()
        for policy in CONFLICT_POLICIES:
            self.conflict_combo.addItem("", userData=policy)
        options_row.addWidget(self.conflict_label)
        options_row.addWidget(self.conflict_combo)

        options_row.addStretch(1)
        root.addLayout(options_row)

        # --- transform settings ---
        transform_row = QHBoxLayout()

        self.resize_label = QLabel()
        self.resize_combo = QComboBox()
        for mode in RESIZE_MODES:
            self.resize_combo.addItem("", userData=mode)
        transform_row.addWidget(self.resize_label)
        transform_row.addWidget(self.resize_combo)

        # Width / height / percent share this row; visibility depends on
        # the chosen mode so the user only sees fields that apply.
        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 20000)
        self.width_spin.setValue(1920)
        self.width_spin.setSuffix(" px")
        self.height_spin = QSpinBox()
        self.height_spin.setRange(1, 20000)
        self.height_spin.setValue(1080)
        self.height_spin.setSuffix(" px")
        self.percent_spin = QSpinBox()
        self.percent_spin.setRange(1, 400)
        self.percent_spin.setValue(50)
        self.percent_spin.setSuffix(" %")
        transform_row.addWidget(self.width_spin)
        transform_row.addWidget(self.height_spin)
        transform_row.addWidget(self.percent_spin)

        self.upscale_check = QCheckBox()
        transform_row.addWidget(self.upscale_check)

        self.rotate_label = QLabel()
        self.rotate_combo = QComboBox()
        for rotation in ROTATIONS:
            self.rotate_combo.addItem("", userData=rotation)
        transform_row.addWidget(self.rotate_label)
        transform_row.addWidget(self.rotate_combo)

        self.auto_orient_check = QCheckBox()
        self.auto_orient_check.setChecked(True)
        transform_row.addWidget(self.auto_orient_check)

        transform_row.addStretch(1)
        root.addLayout(transform_row)

        out_row = QHBoxLayout()
        self.out_dir_btn = QPushButton()
        self.out_dir_label = QLabel()
        self.out_dir_label.setObjectName("Muted")
        out_row.addWidget(self.out_dir_btn)
        out_row.addWidget(self.out_dir_label, 1)
        root.addLayout(out_row)

        # --- run ---
        run_row = QHBoxLayout()
        self.convert_btn = QPushButton()
        self.convert_btn.setObjectName("PrimaryButton")
        self.cancel_btn = QPushButton()
        self.cancel_btn.setVisible(False)
        run_row.addWidget(self.convert_btn)
        run_row.addWidget(self.cancel_btn)
        run_row.addStretch(1)
        root.addLayout(run_row)

        self.progress = QProgressBar()
        self.progress.setObjectName("Progress")
        self.progress.setVisible(False)
        self.progress.setTextVisible(True)
        root.addWidget(self.progress)

        self.status = QLabel()
        self.status.setObjectName("Status")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        # --- signals ---
        self.add_files_btn.clicked.connect(self._pick_files)
        self.add_folder_btn.clicked.connect(self._pick_folder)
        self.select_all_btn.clicked.connect(lambda: self._set_all_checked(True))
        self.select_none_btn.clicked.connect(lambda: self._set_all_checked(False))
        self.clear_btn.clicked.connect(self._clear_files)
        self.out_dir_btn.clicked.connect(self._pick_out_dir)
        self.convert_btn.clicked.connect(self._start)
        self.cancel_btn.clicked.connect(self._cancel)
        self.quality_slider.valueChanged.connect(
            lambda v: self.quality_value.setText(str(v))
        )
        self.format_combo.currentIndexChanged.connect(self._update_enabled)
        self.file_list.itemChanged.connect(self._on_item_checked_changed)
        self.resize_combo.currentIndexChanged.connect(self._update_resize_fields)

        self._update_resize_fields()

    # ------------------------------------------------------------- i18n

    def retranslate(self) -> None:
        self.title.setText(self.tr("Image Converter"))
        self.subtitle.setText(
            self.tr("Convert one or many images between PNG, JPG and WebP.")
        )
        self.add_files_btn.setText(self.tr("Add files"))
        self.add_folder_btn.setText(self.tr("Add folder"))
        self.select_all_btn.setText(self.tr("Select all"))
        self.select_none_btn.setText(self.tr("Select none"))
        self.clear_btn.setText(self.tr("Clear list"))
        self.format_label.setText(self.tr("Output format"))
        self.quality_label.setText(self.tr("Quality"))
        self.conflict_label.setText(self.tr("If file exists"))
        self.resize_label.setText(self.tr("Resize"))
        self.rotate_label.setText(self.tr("Rotate"))
        self.upscale_check.setText(self.tr("Allow upscale"))
        self.auto_orient_check.setText(self.tr("Auto-orient (EXIF)"))
        self.out_dir_btn.setText(self.tr("Output folder..."))
        self.convert_btn.setText(self.tr("Convert"))
        self.cancel_btn.setText(self.tr("Cancel"))

        labels = {
            ConflictPolicy.RENAME: self.tr("Rename"),
            ConflictPolicy.OVERWRITE: self.tr("Overwrite"),
            ConflictPolicy.SKIP: self.tr("Skip"),
        }
        for i, policy in enumerate(CONFLICT_POLICIES):
            self.conflict_combo.setItemText(i, labels[policy])

        resize_labels = {
            ResizeMode.NONE: self.tr("No resize"),
            ResizeMode.MAX_WIDTH: self.tr("Max width"),
            ResizeMode.MAX_HEIGHT: self.tr("Max height"),
            ResizeMode.FIT_BOX: self.tr("Fit in box"),
            ResizeMode.PERCENT: self.tr("Percentage"),
        }
        for i, mode in enumerate(RESIZE_MODES):
            self.resize_combo.setItemText(i, resize_labels[mode])

        rotate_labels = {
            Rotation.NONE: self.tr("No rotation"),
            Rotation.CW_90: self.tr("90° right"),
            Rotation.ROT_180: self.tr("180°"),
            Rotation.CCW_90: self.tr("90° left"),
        }
        for i, rotation in enumerate(ROTATIONS):
            self.rotate_combo.setItemText(i, rotate_labels[rotation])

        self._refresh_out_dir_label()
        self._refresh_status_idle()

    def _update_resize_fields(self) -> None:
        """Show only the spinboxes that the chosen resize mode uses."""
        mode = self.resize_combo.currentData()
        self.width_spin.setVisible(mode in (ResizeMode.MAX_WIDTH, ResizeMode.FIT_BOX))
        self.height_spin.setVisible(mode in (ResizeMode.MAX_HEIGHT, ResizeMode.FIT_BOX))
        self.percent_spin.setVisible(mode == ResizeMode.PERCENT)
        # Upscaling is only meaningful for the capping modes; percentage
        # already scales up when you ask for more than 100%.
        self.upscale_check.setVisible(
            mode in (ResizeMode.MAX_WIDTH, ResizeMode.MAX_HEIGHT, ResizeMode.FIT_BOX)
        )

    def _refresh_out_dir_label(self) -> None:
        if self._out_dir is None:
            self.out_dir_label.setText(self.tr("Not selected (same folder as source)"))
        else:
            self.out_dir_label.setText(str(self._out_dir))

    def _refresh_status_idle(self) -> None:
        if self._job is not None:
            return
        total = len(self._files)
        checked = len(self._checked_paths())
        if total == 0:
            self.status.setText(self.tr("No files selected."))
        elif checked == 0:
            self.status.setText(self.tr("All files excluded."))
        else:
            self.status.setText(self.tr("%n file(s) ready.", "", checked))

    # ------------------------------------------------------- file picking

    def _pick_files(self) -> None:
        patterns = " ".join(f"*.{e}" for e in sorted(INPUT_EXTENSIONS))
        paths, _ = QFileDialog.getOpenFileNames(
            self, self.tr("Select images"), "", f"{self.tr('Images')} ({patterns})"
        )
        self._add_paths([Path(p) for p in paths])

    def _pick_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, self.tr("Select folder"))
        if folder:
            self._add_paths([Path(folder)])

    def _add_paths(self, paths: list[Path]) -> None:
        if not paths:
            return
        found = collect_files(paths, INPUT_EXTENSIONS)
        known = set(self._files)
        for path in found:
            if path in known:
                continue
            self._files.append(path)

            item = QListWidgetItem(_build_thumbnail(path), path.stem)
            item.setData(_PATH_ROLE, path)
            item.setToolTip(path.name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            # Set before adding to the list: avoids firing itemChanged
            # (and a redundant status refresh) for every item on a big
            # folder import.
            item.setCheckState(Qt.CheckState.Checked)
            self.file_list.addItem(item)

        self._update_enabled()
        self._refresh_status_idle()

    def _clear_files(self) -> None:
        self._files.clear()
        self.file_list.clear()
        self._update_enabled()
        self._refresh_status_idle()

    def _pick_out_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, self.tr("Select output folder"))
        if folder:
            self._out_dir = Path(folder)
            self._refresh_out_dir_label()
            self._update_enabled()

    # --------------------------------------------------------- checkboxes

    def _checked_paths(self) -> list[Path]:
        paths: list[Path] = []
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                paths.append(item.data(_PATH_ROLE))
        return paths

    def _set_all_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.file_list.blockSignals(True)
        for i in range(self.file_list.count()):
            self.file_list.item(i).setCheckState(state)
        self.file_list.blockSignals(False)
        self._update_enabled()
        self._refresh_status_idle()

    def _on_item_checked_changed(self, _item: QListWidgetItem) -> None:
        self._update_enabled()
        self._refresh_status_idle()

    def _lock_checkboxes(self, locked: bool) -> None:
        """Freeze inclusion once a batch has started.

        The running batch already snapshotted which paths it's working
        on (`_start` reads `_checked_paths()` once), so toggling a
        checkbox mid-run would silently do nothing - worse than just
        disabling it. Flag changes don't fire `itemChanged`, so this
        doesn't trigger a spurious status refresh.

        `setFlags` itself fires `itemChanged` in Qt (not just check-state
        changes), so this must block signals - otherwise it re-enters
        `_update_enabled` -> `_lock_checkboxes` and recurses forever.
        """
        self.file_list.blockSignals(True)
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if locked:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            else:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        self.file_list.blockSignals(False)

    # ------------------------------------------------------------- run

    def _update_enabled(self) -> None:
        running = self._job is not None
        has_checked = bool(self._checked_paths())
        self.convert_btn.setEnabled(has_checked and not running)
        for widget in (
            self.add_files_btn,
            self.add_folder_btn,
            self.select_all_btn,
            self.select_none_btn,
            self.clear_btn,
            self.out_dir_btn,
            self.format_combo,
            self.quality_slider,
            self.conflict_combo,
            self.resize_combo,
            self.width_spin,
            self.height_spin,
            self.percent_spin,
            self.upscale_check,
            self.rotate_combo,
            self.auto_orient_check,
        ):
            widget.setEnabled(not running)
        self._lock_checkboxes(running)

    def _build_transforms(self) -> list:
        """Assemble the transform chain in the order it must run.

        Auto-orient first: it normalises the image to how a viewer would
        show it, so a later rotate means what the user expects rather
        than compounding an unapplied EXIF tag. Resize before rotate is
        cheaper (fewer pixels to reorder) and gives the same result for
        90-degree steps.
        """
        transforms = []

        if self.auto_orient_check.isChecked():
            transforms.append(auto_orient)

        mode = self.resize_combo.currentData()
        if mode != ResizeMode.NONE:
            transforms.append(
                make_resize(
                    mode,
                    width=self.width_spin.value(),
                    height=self.height_spin.value(),
                    percent=self.percent_spin.value(),
                    allow_upscale=self.upscale_check.isChecked(),
                )
            )

        rotation = self.rotate_combo.currentData()
        if rotation != Rotation.NONE:
            transforms.append(make_rotate(rotation))

        return transforms

    def _start(self) -> None:
        items = self._checked_paths()
        if not items or self._job is not None:
            return

        target_format = self.format_combo.currentData()
        policy = self.conflict_combo.currentData()
        quality = self.quality_slider.value()
        out_dir = self._out_dir or items[0].parent

        work = make_convert_job(
            out_dir=out_dir,
            target_format=target_format,
            quality=quality,
            policy=policy,
            transforms=self._build_transforms(),
        )

        self._job = BatchJob(items, work, parent=self)
        self._job.progress.connect(self._on_progress)
        self._job.finished.connect(self._on_finished)
        self._job.failed.connect(self._on_failed)

        self.progress.setRange(0, len(items))
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.cancel_btn.setVisible(True)
        self.cancel_btn.setEnabled(True)
        self._update_enabled()

        self._job.start()

    def _cancel(self) -> None:
        if self._job is not None:
            self._job.cancel()
            self.cancel_btn.setEnabled(False)
            self.status.setText(self.tr("Cancelling..."))

    def _on_progress(self, done: int, total: int, name: str) -> None:
        self.progress.setValue(done)
        self.status.setText(self.tr("Converting: %1").replace("%1", name))

    def _teardown_job(self) -> None:
        self._job = None
        self.progress.setVisible(False)
        self.cancel_btn.setVisible(False)
        self._update_enabled()

    def _on_finished(self, report: BatchReport) -> None:
        self._teardown_job()
        ok = len(report.succeeded)
        failed = len(report.failed)
        skipped = len(report.skipped)

        parts = [self.tr("%n converted", "", ok)]
        if skipped:
            parts.append(self.tr("%n skipped", "", skipped))
        if failed:
            parts.append(self.tr("%n failed", "", failed))
        if report.cancelled:
            parts.append(self.tr("cancelled"))

        self.status.setText(", ".join(parts) + ".")

        if failed:
            first = report.failed[0]
            self.status.setText(
                self.status.text()
                + f"\n{first.source.name}: {first.error}"
            )

    def _on_failed(self, message: str) -> None:
        self._teardown_job()
        self.status.setText(self.tr("Error: %1").replace("%1", message))