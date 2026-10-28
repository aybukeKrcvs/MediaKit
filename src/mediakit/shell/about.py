"""About / Licenses dialog.

Left: every model and bundled library. Right: who made it, its license,
and the full license text(s). Everything comes from data that tests
check (ModelSpec.credit and assets/licenses/libraries.json), so this
page cannot drift from what the app actually ships.

License texts are legal documents and stay in their original language;
only the dialog chrome is translated.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from importlib.resources import files

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from mediakit import __version__
from mediakit.modules.models import all_model_specs

KEY_ROLE = Qt.ItemDataRole.UserRole


@dataclass(frozen=True)
class Entry:
    key: str
    name: str
    authors: str
    license: str
    url: str
    version: str
    note: str
    license_files: tuple[str, ...]


def _licenses_root():
    return files("mediakit").joinpath("assets", "licenses")


def model_entries() -> list[Entry]:
    return [
        Entry(
            f"model:{spec.key}",
            spec.credit.name,
            spec.credit.authors,
            spec.credit.license,
            spec.credit.url,
            "",
            spec.credit.note,
            spec.credit.license_files,
        )
        for spec in all_model_specs()
    ]


def library_entries() -> list[Entry]:
    raw = _licenses_root().joinpath("libraries.json").read_text(encoding="utf-8")
    return [
        Entry(
            f"lib:{item['name']}",
            item["name"],
            "",
            item["license"],
            item.get("url") or "",
            item["version"],
            "",
            tuple(item["files"]),
        )
        for item in json.loads(raw)
    ]


def _read(relative: str) -> str:
    try:
        return (
            _licenses_root()
            .joinpath(*relative.split("/"))
            .read_text(encoding="utf-8", errors="replace")
        )
    except OSError:
        return f"[missing: {relative}]"


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, focus: str | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("AboutDialog")
        self.setWindowTitle(self.tr("About MediaKit"))
        self.resize(940, 620)
        self._entries: dict[str, Entry] = {}

        layout = QVBoxLayout(self)
        title = QLabel(f"MediaKit {__version__}")
        title.setObjectName("ToolTitle")
        layout.addWidget(title)
        intro = QLabel(
            self.tr(
                "An offline media toolkit. It is built on the open-source work below; "
                "thank you to everyone who made it."
            )
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        body = QHBoxLayout()
        self.list = QListWidget()
        self.list.setFixedWidth(280)
        self.text = QTextBrowser()
        self.text.setOpenExternalLinks(True)
        body.addWidget(self.list)
        body.addWidget(self.text, 1)
        layout.addLayout(body, 1)

        note = QLabel(
            self.tr("License texts are legal documents and are shown in their original language.")
        )
        note.setObjectName("Muted")
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        # Standard buttons are translated by Qt's own catalogue, which we
        # do not ship; set the text ourselves.
        buttons.button(QDialogButtonBox.StandardButton.Close).setText(self.tr("Close"))
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._add_section(self.tr("MODELS"), model_entries())
        self._add_section(self.tr("LIBRARIES"), library_entries())
        self.list.currentItemChanged.connect(self._show)
        self.select(focus)

    def _add_section(self, title: str, entries: list[Entry]) -> None:
        header = QListWidgetItem(title)
        header.setFlags(Qt.ItemFlag.NoItemFlags)  # a label, not selectable
        font = header.font()
        font.setBold(True)
        header.setFont(font)
        self.list.addItem(header)
        for entry in entries:
            self._entries[entry.key] = entry
            label = f"{entry.name}  {entry.version}".rstrip()
            item = QListWidgetItem(label)
            item.setData(KEY_ROLE, entry.key)
            self.list.addItem(item)

    def select(self, key: str | None) -> None:
        """Open on one entry (e.g. "model:silueta"); first entry otherwise."""
        for row in range(self.list.count()):
            item = self.list.item(row)
            item_key = item.data(KEY_ROLE)
            if item_key and (key is None or item_key == key):
                self.list.setCurrentItem(item)
                return

    def current_key(self) -> str | None:
        item = self.list.currentItem()
        return item.data(KEY_ROLE) if item else None

    def _show(self, item: QListWidgetItem | None) -> None:
        entry = self._entries.get(item.data(KEY_ROLE)) if item else None
        if entry is None:
            return
        parts = [f"<h3>{html.escape(entry.name)}</h3>"]
        facts = [entry.authors, entry.license, entry.version]
        parts.append("<p>" + " \u00b7 ".join(html.escape(f) for f in facts if f) + "</p>")
        if entry.url:
            url = html.escape(entry.url, quote=True)
            parts.append(f'<p><a href="{url}">{url}</a></p>')
        if entry.note:
            parts.append(f"<p><i>{html.escape(entry.note)}</i></p>")
        for name in entry.license_files:
            parts.append(f"<hr><p><b>{html.escape(name.rsplit('/', 1)[-1])}</b></p>")
            parts.append(f"<pre>{html.escape(_read(name))}</pre>")
        self.text.setHtml("".join(parts))
        self.text.verticalScrollBar().setValue(0)
