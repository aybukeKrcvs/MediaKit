"""Audio tools. Phase 2a: Convert."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import av
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from mediakit.core.batch import WorkFn
from mediakit.core.paths import ConflictPolicy
from mediakit.modules.audio.convert import (
    FORMATS,
    INPUT_EXTENSIONS,
    SAMPLE_RATES,
    AudioInfo,
    make_audio_convert_job,
    probe,
)
from mediakit.ui.batch_tool import BatchToolScreen
from mediakit.ui.tiles import ChoiceTile, text_drawing

FORMAT_KEYS: tuple[str, ...] = tuple(FORMATS)


class AudioToolBase(BatchToolScreen):
    input_extensions: ClassVar[frozenset[str]] = INPUT_EXTENSIONS


def _clock(seconds: float) -> str:
    seconds = round(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _size(num_bytes: float) -> str:
    return f"{num_bytes / 1e6:.1f} MB" if num_bytes >= 1e6 else f"{num_bytes / 1e3:.0f} kB"


class AudioConvertTool(AudioToolBase):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.current_file_changed.connect(lambda _p: self._refresh_info())
        self.file_list.model().rowsInserted.connect(lambda *_: self._refresh_info())
        self.file_list.model().rowsRemoved.connect(lambda *_: self._refresh_info())

    # ============================================================== build

    def build_options(self, layout: QVBoxLayout) -> None:
        self.format_label = QLabel()
        self.format_label.setObjectName("SectionLabel")
        layout.addWidget(self.format_label)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.format_group = QButtonGroup(self)
        self.format_tiles = []
        for index, key in enumerate(FORMAT_KEYS):
            tile = ChoiceTile(text_drawing(key.upper()), size=QSize(96, 92))
            self.format_group.addButton(tile, index)
            self.format_tiles.append(tile)
            row.addWidget(tile)
        row.addStretch(1)
        layout.addLayout(row)
        self.format_tiles[FORMAT_KEYS.index("mp3")].setChecked(True)

        settings = QHBoxLayout()
        settings.setSpacing(12)
        self.bitrate_label = QLabel()
        self.bitrate_combo = QComboBox()
        self.rate_label = QLabel()
        self.rate_combo = QComboBox()
        self.channels_label = QLabel()
        self.channels_combo = QComboBox()
        for widget in (
            self.bitrate_label,
            self.bitrate_combo,
            self.rate_label,
            self.rate_combo,
            self.channels_label,
            self.channels_combo,
        ):
            settings.addWidget(widget)
        settings.addStretch(1)
        layout.addLayout(settings)

        self.info_label = QLabel()
        self.info_label.setObjectName("Muted")
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        self.format_group.idToggled.connect(lambda _i, on: on and self._on_format_changed())
        self.bitrate_combo.currentIndexChanged.connect(lambda _i: self._refresh_info())
        self._on_format_changed()

    # =============================================================== i18n

    def retranslate_options(self) -> None:
        self.format_label.setText(self.tr("Convert to"))
        captions = {
            "mp3": (self.tr("Everywhere"), self.tr("Plays on every device. Lossy.")),
            "m4a": (self.tr("Phones"), self.tr("AAC in an MP4 container. Lossy.")),
            "opus": (
                self.tr("Smallest"),
                self.tr("Best quality per kbit/s, great for speech. Lossy."),
            ),
            "flac": (self.tr("Lossless"), self.tr("Exact copy of the sound, compressed.")),
            "wav": (self.tr("Uncompressed"), self.tr("Raw PCM. Largest files, for editing.")),
        }
        for key, tile in zip(FORMAT_KEYS, self.format_tiles, strict=True):
            caption, tooltip = captions[key]
            tile.set_texts(key.upper(), caption, tooltip)

        self.bitrate_label.setText(self.tr("Bitrate"))
        self.rate_label.setText(self.tr("Sample rate"))
        self.channels_label.setText(self.tr("Channels"))

        rate = self.rate_combo.currentData()
        self.rate_combo.blockSignals(True)
        self.rate_combo.clear()
        self.rate_combo.addItem(self.tr("Keep original"), None)
        for value in SAMPLE_RATES:
            self.rate_combo.addItem(f"{value / 1000:g} kHz", value)
        self.rate_combo.setCurrentIndex(max(0, self.rate_combo.findData(rate)))
        self.rate_combo.blockSignals(False)

        channels = self.channels_combo.currentData()
        self.channels_combo.blockSignals(True)
        self.channels_combo.clear()
        self.channels_combo.addItem(self.tr("Keep original"), None)
        self.channels_combo.addItem(self.tr("Mono"), 1)
        self.channels_combo.addItem(self.tr("Stereo"), 2)
        self.channels_combo.setCurrentIndex(max(0, self.channels_combo.findData(channels)))
        self.channels_combo.blockSignals(False)
        self._refresh_info()

    def run_text(self) -> str:
        return self.tr("Convert")

    def option_widgets(self) -> list[QWidget]:
        return [*self.format_tiles, self.bitrate_combo, self.rate_combo, self.channels_combo]

    # ============================================================== state

    def _format_key(self) -> str:
        return FORMAT_KEYS[max(0, self.format_group.checkedId())]

    def _on_format_changed(self) -> None:
        fmt = FORMATS[self._format_key()]
        # Lossless formats have no bitrate to choose: hide, don't disable.
        lossy = not fmt.lossless
        self.bitrate_label.setVisible(lossy)
        self.bitrate_combo.setVisible(lossy)
        self.bitrate_combo.blockSignals(True)
        self.bitrate_combo.clear()
        for kbps in fmt.bitrates:
            self.bitrate_combo.addItem(f"{kbps} kbit/s", kbps)
        if lossy:
            self.bitrate_combo.setCurrentIndex(fmt.bitrates.index(fmt.default_bitrate))
        self.bitrate_combo.blockSignals(False)
        self._refresh_info()

    def _info_path(self) -> Path | None:
        path = self.current_file()
        if path is None and self.file_list.count():
            path = self.file_list.item(0).data(Qt.ItemDataRole.UserRole)
        return path

    def _refresh_info(self) -> None:
        if not hasattr(self, "info_label"):
            return
        path = self._info_path()
        if path is None:
            self.info_label.setText("")
            return
        try:
            info = probe(path)
        except (OSError, ValueError, av.FFmpegError) as error:
            self.info_label.setText(f"{path.name}: {error}")
            return
        self.info_label.setText(self._describe(path, info))

    def _describe(self, path: Path, info: AudioInfo) -> str:
        layout = {1: self.tr("mono"), 2: self.tr("stereo")}.get(
            info.channels, self.tr("%1 channels").replace("%1", str(info.channels))
        )
        parts = [info.codec.upper(), f"{info.sample_rate / 1000:g} kHz", layout]
        if info.duration:
            parts.append(_clock(info.duration))
        if info.bitrate:
            parts.append(f"{round(info.bitrate / 1000)} kbit/s")
        text = f"{path.name}: " + " \u00b7 ".join(parts)
        kbps = self.bitrate_combo.currentData()
        if kbps and info.duration:
            # Lossy encoders aim for the bitrate, so size ~ bitrate x time.
            estimate = _size(kbps * 1000 / 8 * info.duration)
            text += "\n" + self.tr("Output about %1 per file like this.").replace("%1", estimate)
        return text

    # ================================================================ run

    def make_work(self, out_dir: Path | None, policy: ConflictPolicy) -> WorkFn:
        return make_audio_convert_job(
            out_dir,
            policy,
            self._format_key(),
            bitrate=self.bitrate_combo.currentData() or 0,
            sample_rate=self.rate_combo.currentData(),
            channels=self.channels_combo.currentData(),
            on_progress=self.item_progress.emit,
            cancel=self.cancel_token(),
        )
