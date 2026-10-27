"""Remove metadata tool: shows what a file leaks, then strips it."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QLabel, QVBoxLayout, QWidget

from mediakit.core.batch import WorkFn
from mediakit.core.paths import ConflictPolicy
from mediakit.modules.image.metadata import inspect_metadata, make_strip_job
from mediakit.modules.image.tools import ImageToolBase


class MetadataTool(ImageToolBase):
    def build_options(self, layout: QVBoxLayout) -> None:
        self.inspect_label = QLabel()
        self.inspect_label.setObjectName("SectionLabel")
        layout.addWidget(self.inspect_label)

        self.report = QLabel()
        self.report.setObjectName("InspectorBox")
        self.report.setWordWrap(True)
        self.report.setMinimumHeight(88)
        layout.addWidget(self.report)

        self.keep_icc = QCheckBox()
        self.keep_icc.setChecked(True)
        layout.addWidget(self.keep_icc)

        self.hint = QLabel()
        self.hint.setObjectName("Muted")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        self.file_list.currentItemChanged.connect(lambda *_: self._inspect())

    def retranslate_options(self) -> None:
        self.inspect_label.setText(self.tr("Found in the selected file"))
        self.keep_icc.setText(self.tr("Keep colour profile (ICC)"))
        self.keep_icc.setToolTip(
            self.tr("A colour profile holds no personal data; removing it can shift colours.")
        )
        self.hint.setText(
            self.tr(
                "JPEG, PNG and WebP are cleaned without re-encoding: no quality loss. "
                "Photo orientation is kept so images don't turn sideways."
            )
        )
        self._inspect()

    def run_text(self) -> str:
        return self.tr("Remove metadata")

    def option_widgets(self) -> list[QWidget]:
        return [self.keep_icc]

    def _inspect(self) -> None:
        path = self.current_file()
        if path is None:
            self.report.setText(self.tr("Click an image to see what it contains."))
            return
        try:
            report = inspect_metadata(path)
        except Exception as exc:  # noqa: BLE001 - unreadable file: say so, don't crash
            self.report.setText(self.tr("Could not read: %1").replace("%1", str(exc)))
            return

        lines: list[str] = []
        if report.has_gps:
            lines.append(self.tr("\u26a0 GPS location: where the photo was taken"))
        if report.camera:
            lines.append(self.tr("Camera: %1").replace("%1", report.camera))
        if report.taken:
            lines.append(self.tr("Date taken: %1").replace("%1", report.taken))
        if report.software:
            lines.append(self.tr("Software: %1").replace("%1", report.software))
        if report.has_xmp:
            lines.append(self.tr("XMP data (editing history, author)"))
        if report.has_iptc:
            lines.append(self.tr("IPTC data (captions, copyright, keywords)"))
        if report.has_comment:
            lines.append(self.tr("Embedded comment"))
        if report.other:
            lines.append(self.tr("Other fields: %1").replace("%1", ", ".join(report.other)))
        if not lines:
            lines.append(self.tr("No personal metadata found."))
        if report.has_icc:
            lines.append(self.tr("Colour profile (ICC)"))
        self.report.setText(f"{path.name}\n" + "\n".join(lines))

    def make_work(self, out_dir: Path | None, policy: ConflictPolicy) -> WorkFn:
        return make_strip_job(out_dir, policy, keep_icc=self.keep_icc.isChecked())
