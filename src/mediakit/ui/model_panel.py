"""Model picker with one-time download, shared by every AI tool.

Shows one tile per model, the install state, a download button with
progress and cancel, and the device inference will run on. Knows
nothing about what the models do: a tool passes in its keys and a
function that returns the ModelSpec for a key.

`spec_for` is looked up on every use rather than copied once, so a
tool's MODELS dict stays the single source of truth (tests patch it).

i18n: QCoreApplication.translate("ModelPanel", "<literal>") written out
in full at every call: pyside6-lupdate only finds literal strings, so a
helper like _t(text) would hide them from it.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QSize, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mediakit.core.models import ModelSpec, ModelStore
from mediakit.core.onnx import available_device
from mediakit.ui.tiles import ChoiceTile, glyph_drawing
from mediakit.ui.worker import TaskJob

TILE = QSize(104, 100)


class ModelPanel(QWidget):
    # Selection, install state or download state changed: re-check can_run.
    changed = Signal()
    # One-line outcome for the tool's status label ("Model ready." ...).
    message = Signal(str)

    def __init__(
        self,
        keys: tuple[str, ...],
        spec_for: Callable[[str], ModelSpec],
        default: str,
        glyph: str,
        store: ModelStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._keys = keys
        self._spec_for = spec_for
        self._store = store
        self._download: TaskJob | None = None
        self._texts: dict[str, tuple[str, str]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.title = QLabel()
        self.title.setObjectName("SectionLabel")
        layout.addWidget(self.title)

        row = QHBoxLayout()
        self.group = QButtonGroup(self)
        self.tiles: list[ChoiceTile] = []
        for index in range(len(keys)):
            tile = ChoiceTile(glyph_drawing(glyph), size=TILE)
            self.group.addButton(tile, index)
            self.tiles.append(tile)
            row.addWidget(tile)
        row.addStretch(1)
        layout.addLayout(row)
        self.tiles[keys.index(default)].setChecked(True)

        status_row = QHBoxLayout()
        self.status = QLabel()
        self.status.setObjectName("Muted")
        self.bar = QProgressBar()
        self.bar.setObjectName("Progress")
        self.bar.setFixedWidth(180)
        self.download_btn = QPushButton()
        self.download_btn.setObjectName("PrimaryButton")
        self.cancel_btn = QPushButton()
        for widget in (self.status, self.bar, self.download_btn, self.cancel_btn):
            status_row.addWidget(widget)
        status_row.addStretch(1)
        layout.addLayout(status_row)

        self.device = QLabel()
        self.device.setObjectName("Muted")
        layout.addWidget(self.device)
        # Who made the model, always visible next to it.
        self.credit = QLabel()
        self.credit.setObjectName("Muted")
        self.credit.setWordWrap(True)
        layout.addWidget(self.credit)

        self.group.idToggled.connect(lambda _i, on: on and self.refresh())
        self.download_btn.clicked.connect(self.start_download)
        self.cancel_btn.clicked.connect(self.cancel_download)
        self.refresh()

    # ============================================================== state

    def current_key(self) -> str:
        return self._keys[max(0, self.group.checkedId())]

    def current_spec(self) -> ModelSpec:
        return self._spec_for(self.current_key())

    def model_path(self) -> Path:
        return self._store.path(self.current_spec())

    def is_ready(self) -> bool:
        return self._store.is_installed(self.current_spec())

    def is_downloading(self) -> bool:
        return self._download is not None

    def set_locked(self, locked: bool) -> None:
        """Disable model switching (a batch or preview is using it)."""
        for tile in self.tiles:
            tile.setEnabled(not locked and not self.is_downloading())
        self.download_btn.setEnabled(not locked and not self.is_downloading())

    # =============================================================== i18n

    def set_choice_texts(self, texts: dict[str, tuple[str, str]]) -> None:
        """key -> (label, tooltip). Call from the tool's retranslate."""
        self._texts = texts
        for key, tile in zip(self._keys, self.tiles, strict=True):
            label, tooltip = texts.get(key, (key, ""))
            tile.set_texts(label, f"{self._spec_for(key).size_mb} MB", tooltip)

    def retranslate(self) -> None:
        self.title.setText(QCoreApplication.translate("ModelPanel", "Model"))
        self.cancel_btn.setText(QCoreApplication.translate("ModelPanel", "Cancel"))
        self.device.setText(
            QCoreApplication.translate("ModelPanel", "Runs on: %1").replace(
                "%1", available_device()
            )
        )
        if self._texts:
            self.set_choice_texts(self._texts)
        self.refresh()

    def refresh(self) -> None:
        credit = self.current_spec().credit
        self.credit.setText(credit.short())
        tip = QCoreApplication.translate(
            "ModelPanel", "Full license: sidebar \u2192 About & licenses"
        )
        self.credit.setToolTip(f"{credit.note}\n{credit.url}\n\n{tip}".strip())
        downloading = self.is_downloading()
        ready = self.is_ready()
        self.bar.setVisible(downloading)
        self.cancel_btn.setVisible(downloading)
        self.download_btn.setVisible(not ready and not downloading)
        self.download_btn.setText(
            QCoreApplication.translate("ModelPanel", "Download (%1 MB)").replace(
                "%1", str(self.current_spec().size_mb)
            )
        )
        if downloading:
            self.status.setText(QCoreApplication.translate("ModelPanel", "Downloading..."))
        elif ready:
            self.status.setText(
                QCoreApplication.translate("ModelPanel", "\u2713 Model installed, works offline")
            )
        else:
            self.status.setText(
                QCoreApplication.translate("ModelPanel", "Needs a one-time download.")
            )
        self.changed.emit()

    # ========================================================== download

    def start_download(self) -> None:
        if self._download is not None:
            return
        spec, store = self.current_spec(), self._store
        self._download = TaskJob(
            lambda progress, cancel: store.download(spec, progress, cancel), self
        )
        self._download.progress.connect(self._on_progress)
        self._download.finished.connect(lambda _path: self._done(None))
        self._download.failed.connect(self._done)
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        for tile in self.tiles:
            tile.setEnabled(False)
        self._download.start()
        self.refresh()

    def _on_progress(self, done: int, total: int) -> None:
        if total:
            self.bar.setValue(round(1000 * done / total))
            self.bar.setFormat(f"{done / 1e6:.0f} / {total / 1e6:.0f} MB")

    def cancel_download(self) -> None:
        if self._download is not None:
            self._download.cancel()

    def _done(self, error: str | None) -> None:
        cancelled = self._download is not None and self._download.cancel_token.cancelled
        self._download = None
        for tile in self.tiles:
            tile.setEnabled(True)
        self.refresh()
        if cancelled:
            self.message.emit(QCoreApplication.translate("ModelPanel", "Download cancelled."))
        elif error:
            self.message.emit(
                QCoreApplication.translate("ModelPanel", "Download failed: %1").replace("%1", error)
            )
        else:
            self.message.emit(QCoreApplication.translate("ModelPanel", "Model ready."))
