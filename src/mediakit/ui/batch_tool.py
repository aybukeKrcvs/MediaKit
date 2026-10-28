"""Base screen shared by every file-processing tool.

A tool subclass only answers three questions:
  - what options does it show?        build_options / retranslate_options
  - can it run with these settings?   can_run
  - what happens to one file?         make_work

Everything else (file grid, output folder, conflict policy, threading,
progress, status) lives here once.

i18n note: QCoreApplication.translate with an explicit "BatchTool"
context, because `self.tr()` would use the subclass name at runtime and
miss the translations lupdate filed under this class.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from PySide6.QtCore import QCoreApplication, QFileInfo, QMimeData, QSize, Qt, Signal
from PySide6.QtGui import (
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QIcon,
    QImageReader,
    QPixmap,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFileIconProvider,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mediakit.core.batch import BatchReport, CancelToken, WorkFn
from mediakit.core.paths import ConflictPolicy, collect_files
from mediakit.ui.worker import BatchJob

CONFLICT_POLICIES: tuple[ConflictPolicy, ...] = (
    ConflictPolicy.RENAME,
    ConflictPolicy.OVERWRITE,
    ConflictPolicy.SKIP,
)

THUMBNAIL_SIZE = 96
COMPACT_THUMBNAIL = 56
_PATH_ROLE = Qt.ItemDataRole.UserRole


class BatchToolScreen(QWidget):
    """Override the hooks below; do not override _build or the run loop."""

    # Lowercase, dotless. Subclasses set this.
    input_extensions: ClassVar[frozenset[str]] = frozenset()

    # Emitted with the clicked/current file (single-file tools use it).
    current_file_changed = Signal(object)
    # (done, total) inside the current file, for tools whose single item
    # takes long (upscale tiles). Safe to emit from the worker thread:
    # the receiver lives in the GUI thread, so Qt queues the call.
    item_progress = Signal(int, int)

    PROGRESS_STEPS = 100  # progress bar units per file

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._files: list[Path] = []
        self._out_dir: Path | None = None
        self._job: BatchJob | None = None
        self._cancel_token = CancelToken()
        self._files_done = 0
        self._single = False
        self._icon_provider = QFileIconProvider()
        # build_options() runs in the middle of _build(), before the run
        # button exists. Subclasses may call refresh_state() from their
        # signal handlers during that time; this flag makes it a no-op.
        self._built = False

        self._build()
        self._built = True
        # Drag & drop: files or folders dropped anywhere on the tool page
        # go through add_paths, the same door as the Add buttons.
        self.setAcceptDrops(True)
        self.retranslate()
        self._update_enabled()

    # ================================================================ hooks

    def build_options(self, layout: QVBoxLayout) -> None:
        """Add the tool's own controls to `layout`."""

    def retranslate_options(self) -> None:
        """Set texts on the tool's own controls."""

    def option_widgets(self) -> list[QWidget]:
        """Controls to disable while a batch is running."""
        return []

    def can_run(self) -> bool:
        """Extra precondition beyond 'at least one file'."""
        return True

    def make_work(self, out_dir: Path | None, policy: ConflictPolicy) -> WorkFn:
        """Return work(path) -> output path | None. Required."""
        raise NotImplementedError

    def run_text(self) -> str:
        return QCoreApplication.translate("BatchTool", "Start")

    def thumbnail(self, path: Path) -> QIcon:
        """Grid icon for a file. Default: the OS file-type icon."""
        return self._icon_provider.icon(QFileInfo(str(path)))

    # ============================================================ public API

    def set_single_mode(self, single: bool) -> None:
        """Single: pick one file by clicking it, no checkboxes.
        Batch: every file has a checkbox, all checked by default."""
        if single == self._single:
            return
        self._single = single
        self.file_list.blockSignals(True)
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if single:
                # Removing the check-state data removes the indicator.
                item.setData(Qt.ItemDataRole.CheckStateRole, None)
            else:
                item.setCheckState(Qt.CheckState.Checked)
        self.file_list.blockSignals(False)

        mode = (
            QListWidget.SelectionMode.SingleSelection
            if single
            else QListWidget.SelectionMode.ExtendedSelection
        )
        self.file_list.setSelectionMode(mode)
        self.select_all_btn.setVisible(not single)
        self.select_none_btn.setVisible(not single)

        # Single mode: the grid becomes a one-row filmstrip and the tool's
        # editor gets the vertical space instead.
        thumb = COMPACT_THUMBNAIL if single else THUMBNAIL_SIZE
        self.file_list.setIconSize(QSize(thumb, thumb))
        self.file_list.setGridSize(QSize(thumb + 24, thumb + 36))
        self.file_list.setWrapping(not single)
        strip_height = thumb + 56
        self.file_list.setMinimumHeight(strip_height)
        self.file_list.setMaximumHeight(strip_height if single else 16777215)
        self._root.setStretchFactor(self.file_list, 0 if single else 1)
        self._root.setStretchFactor(self._options_host, 1 if single else 0)

        if single and self.file_list.count() and self.file_list.currentRow() < 0:
            self.file_list.setCurrentRow(0)
        self._emit_current()
        self.refresh_state()

    def current_file(self) -> Path | None:
        item = self.file_list.currentItem()
        return item.data(_PATH_ROLE) if item is not None else None

    def items_to_process(self) -> list[Path]:
        if self._single:
            current = self.current_file()
            return [current] if current is not None else []
        paths: list[Path] = []
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                paths.append(item.data(_PATH_ROLE))
        return paths

    def cancel_token(self) -> CancelToken:
        """Token of the batch being started; valid inside make_work."""
        return self._cancel_token

    def is_running(self) -> bool:
        return self._job is not None

    def refresh_state(self) -> None:
        """Call after any option change that affects can_run()."""
        if not self._built:
            return
        self._update_enabled()
        self._refresh_status_idle()

    # ================================================================ build

    def _build(self) -> None:
        root = QVBoxLayout(self)
        self._root = root
        root.setContentsMargins(0, 12, 0, 20)
        root.setSpacing(10)

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
        self.file_list.setMinimumHeight(THUMBNAIL_SIZE + 48)
        root.addWidget(self.file_list, 1)

        self._options_host = QWidget()
        self._options_host.setObjectName("ToolOptions")
        options_layout = QVBoxLayout(self._options_host)
        options_layout.setContentsMargins(0, 4, 0, 4)
        options_layout.setSpacing(10)
        self.build_options(options_layout)
        root.addWidget(self._options_host, 0)

        out_row = QHBoxLayout()
        self.out_dir_btn = QPushButton()
        self.out_dir_label = QLabel()
        self.out_dir_label.setObjectName("Muted")
        self.conflict_label = QLabel()
        self.conflict_combo = QComboBox()
        for policy in CONFLICT_POLICIES:
            self.conflict_combo.addItem("", userData=policy)
        out_row.addWidget(self.out_dir_btn)
        out_row.addWidget(self.out_dir_label, 1)
        out_row.addWidget(self.conflict_label)
        out_row.addWidget(self.conflict_combo)
        root.addLayout(out_row)

        run_row = QHBoxLayout()
        self.run_btn = QPushButton()
        self.run_btn.setObjectName("PrimaryButton")
        self.cancel_btn = QPushButton()
        self.cancel_btn.setVisible(False)
        run_row.addWidget(self.run_btn)
        run_row.addWidget(self.cancel_btn)
        run_row.addStretch(1)
        root.addLayout(run_row)

        self.progress = QProgressBar()
        self.progress.setObjectName("Progress")
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        self.status = QLabel()
        self.status.setObjectName("Status")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.add_files_btn.clicked.connect(self._pick_files)
        self.add_folder_btn.clicked.connect(self._pick_folder)
        self.select_all_btn.clicked.connect(lambda: self._set_all_checked(True))
        self.select_none_btn.clicked.connect(lambda: self._set_all_checked(False))
        self.clear_btn.clicked.connect(self._clear_files)
        self.out_dir_btn.clicked.connect(self._pick_out_dir)
        self.run_btn.clicked.connect(self._start)
        self.cancel_btn.clicked.connect(self._cancel)
        self.item_progress.connect(self._on_item_progress)
        self.file_list.itemChanged.connect(lambda _item: self.refresh_state())
        self.file_list.currentItemChanged.connect(lambda *_: self._on_current_changed())

    # ================================================================= i18n

    def retranslate(self) -> None:
        self.add_files_btn.setText(QCoreApplication.translate("BatchTool", "Add files"))
        self.add_folder_btn.setText(QCoreApplication.translate("BatchTool", "Add folder"))
        self.select_all_btn.setText(QCoreApplication.translate("BatchTool", "Select all"))
        self.select_none_btn.setText(QCoreApplication.translate("BatchTool", "Select none"))
        self.clear_btn.setText(QCoreApplication.translate("BatchTool", "Clear list"))
        self.out_dir_btn.setText(QCoreApplication.translate("BatchTool", "Output folder..."))
        self.conflict_label.setText(QCoreApplication.translate("BatchTool", "If file exists"))
        self.cancel_btn.setText(QCoreApplication.translate("BatchTool", "Cancel"))
        labels = {
            ConflictPolicy.RENAME: QCoreApplication.translate("BatchTool", "Keep both"),
            ConflictPolicy.OVERWRITE: QCoreApplication.translate("BatchTool", "Overwrite"),
            ConflictPolicy.SKIP: QCoreApplication.translate("BatchTool", "Skip"),
        }
        for i, policy in enumerate(CONFLICT_POLICIES):
            self.conflict_combo.setItemText(i, labels[policy])
        self.run_btn.setText(self.run_text())
        self.retranslate_options()
        self._refresh_out_dir_label()
        self._refresh_status_idle()

    def _refresh_out_dir_label(self) -> None:
        if self._out_dir is None:
            self.out_dir_label.setText(
                QCoreApplication.translate("BatchTool", "Same folder as each source file")
            )
        else:
            self.out_dir_label.setText(str(self._out_dir))

    def _refresh_status_idle(self) -> None:
        if self._job is not None:
            return
        if not self._files:
            self.status.setText(
                QCoreApplication.translate("BatchTool", "Add files or drag them here to begin.")
            )
            return
        if self._single:
            current = self.current_file()
            if current is None:
                self.status.setText(
                    QCoreApplication.translate("BatchTool", "Click an image to edit it.")
                )
            else:
                self.status.setText(current.name)
            return
        count = len(self.items_to_process())
        if count == 0:
            self.status.setText(QCoreApplication.translate("BatchTool", "All files excluded."))
        else:
            self.status.setText(
                QCoreApplication.translate("BatchTool", "%n file(s) ready.", "", count)
            )

    # ========================================================= file picking

    def _pick_files(self) -> None:
        patterns = " ".join(f"*.{e}" for e in sorted(self.input_extensions))
        label = QCoreApplication.translate("BatchTool", "Supported files")
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            QCoreApplication.translate("BatchTool", "Select files"),
            "",
            f"{label} ({patterns})",
        )
        self.add_paths([Path(p) for p in paths])

    def _pick_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, QCoreApplication.translate("BatchTool", "Select folder")
        )
        if folder:
            self.add_paths([Path(folder)])

    def add_paths(self, paths: list[Path]) -> None:
        if not paths:
            return
        found = collect_files(paths, self.input_extensions)
        known = set(self._files)
        self.file_list.blockSignals(True)
        for path in found:
            if path in known:
                continue
            self._files.append(path)
            item = QListWidgetItem(self.thumbnail(path), path.stem)
            item.setData(_PATH_ROLE, path)
            item.setToolTip(path.name)
            if not self._single:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked)
            self.file_list.addItem(item)
        self.file_list.blockSignals(False)

        if self._single and self.file_list.currentRow() < 0 and self.file_list.count():
            self.file_list.setCurrentRow(0)
        self.refresh_state()

    # ========================================================== drag & drop
    #
    # Qt delivers a drag in three steps: dragEnterEvent (may I accept
    # this?), dragMoveEvent while the cursor moves, dropEvent on release.
    # Rejecting in dragEnterEvent is what shows the "not allowed" cursor,
    # so the user knows before letting go. The file list itself does not
    # accept drops, so events over it bubble up to this page.

    def dropped_paths(self, mime: QMimeData) -> list[Path]:
        """Local files and folders in a drag; web links etc. are ignored."""
        if not mime.hasUrls():
            return []
        return [Path(url.toLocalFile()) for url in mime.urls() if url.isLocalFile()]

    def _usable(self, paths: list[Path]) -> bool:
        return any(
            path.is_dir() or path.suffix.lower().lstrip(".") in self.input_extensions
            for path in paths
        )

    def _set_drop_highlight(self, on: bool) -> None:
        # A dynamic property the QSS can match: #FileList[dropTarget="true"].
        # Qt only re-reads styles on polish, hence unpolish/polish.
        self.file_list.setProperty("dropTarget", on)
        self.file_list.style().unpolish(self.file_list)
        self.file_list.style().polish(self.file_list)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if not self.is_running() and self._usable(self.dropped_paths(event.mimeData())):
            event.acceptProposedAction()
            self._set_drop_highlight(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._set_drop_highlight(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_drop_highlight(False)
        paths = self.dropped_paths(event.mimeData())
        before = len(self._files)
        event.acceptProposedAction()
        self.add_paths(paths)
        if len(self._files) == before:
            self.status.setText(
                QCoreApplication.translate("BatchTool", "Nothing new to add from what was dropped.")
            )

    def _clear_files(self) -> None:
        self._files.clear()
        self.file_list.clear()
        self._emit_current()
        self.refresh_state()

    def _pick_out_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, QCoreApplication.translate("BatchTool", "Select output folder")
        )
        if folder:
            self._out_dir = Path(folder)
            self._refresh_out_dir_label()

    # =========================================================== checkboxes

    def _set_all_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.file_list.blockSignals(True)
        for i in range(self.file_list.count()):
            self.file_list.item(i).setCheckState(state)
        self.file_list.blockSignals(False)
        self.refresh_state()

    def _lock_items(self, locked: bool) -> None:
        """Freeze inclusion while a batch runs (it already snapshotted
        its file list). setFlags fires itemChanged, hence blockSignals:
        without it this re-enters _update_enabled and recurses."""
        if self._single:
            self.file_list.setEnabled(not locked)
            return
        self.file_list.blockSignals(True)
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if locked:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            else:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        self.file_list.blockSignals(False)

    def _on_current_changed(self) -> None:
        self._emit_current()
        if self._single:
            self.refresh_state()

    def _emit_current(self) -> None:
        self.current_file_changed.emit(self.current_file() if self._single else None)

    # ================================================================== run

    def _update_enabled(self) -> None:
        running = self._job is not None
        ready = bool(self.items_to_process()) and self.can_run()
        self.run_btn.setEnabled(ready and not running)
        for widget in (
            self.add_files_btn,
            self.add_folder_btn,
            self.select_all_btn,
            self.select_none_btn,
            self.clear_btn,
            self.out_dir_btn,
            self.conflict_combo,
            *self.option_widgets(),
        ):
            widget.setEnabled(not running)
        self._lock_items(running)

    def _start(self) -> None:
        items = self.items_to_process()
        if not items or self._job is not None or not self.can_run():
            return

        self._cancel_token = CancelToken()
        self._files_done = 0
        work = self.make_work(self._out_dir, self.conflict_combo.currentData())
        self._job = BatchJob(items, work, parent=self, cancel=self._cancel_token)
        self._job.progress.connect(self._on_progress)
        self._job.finished.connect(self._on_finished)
        self._job.failed.connect(self._on_failed)

        self.progress.setRange(0, len(items) * self.PROGRESS_STEPS)
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
            self.status.setText(QCoreApplication.translate("BatchTool", "Cancelling..."))

    def _on_progress(self, done: int, _total: int, name: str) -> None:
        self._files_done = done
        self.progress.setValue(done * self.PROGRESS_STEPS)
        self.status.setText(
            QCoreApplication.translate("BatchTool", "Processing: %1").replace("%1", name)
        )

    def _on_item_progress(self, done: int, total: int) -> None:
        if self._job is None or not total:
            return
        within = round(self.PROGRESS_STEPS * done / total)
        self.progress.setValue(self._files_done * self.PROGRESS_STEPS + within)

    def _teardown_job(self) -> None:
        self._job = None
        self.progress.setVisible(False)
        self.cancel_btn.setVisible(False)
        self._update_enabled()

    def _on_finished(self, report: BatchReport) -> None:
        self._teardown_job()
        parts = [QCoreApplication.translate("BatchTool", "%n done", "", len(report.succeeded))]
        if report.skipped:
            parts.append(
                QCoreApplication.translate("BatchTool", "%n skipped", "", len(report.skipped))
            )
        if report.failed:
            parts.append(
                QCoreApplication.translate("BatchTool", "%n failed", "", len(report.failed))
            )
        if report.cancelled:
            parts.append(QCoreApplication.translate("BatchTool", "cancelled"))
        text = ", ".join(parts) + "."
        if report.failed:
            first = report.failed[0]
            text += f"\n{first.source.name}: {first.error}"
        self.status.setText(text)

    def _on_failed(self, message: str) -> None:
        self._teardown_job()
        self.status.setText(
            QCoreApplication.translate("BatchTool", "Error: %1").replace("%1", message)
        )


def image_thumbnail(path: Path, size: int = THUMBNAIL_SIZE) -> QIcon:
    """Fast, EXIF-correct thumbnail for image tools.

    QImageReader.setScaledSize lets the JPEG decoder skip most of the
    work for big photos (decodes at reduced resolution), much faster
    than loading full-size and scaling. setAutoTransform applies the
    EXIF orientation so phone photos are not shown sideways.
    """
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    original = reader.size()
    if original.isValid() and original.width() > 0 and original.height() > 0:
        scaled = original.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio)
        reader.setScaledSize(scaled)
    image = reader.read()
    if image.isNull():
        return QIcon()
    return QIcon(QPixmap.fromImage(image))
