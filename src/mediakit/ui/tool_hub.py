"""Task-first navigation: a grid of tool cards, one page per tool.

Every module (image / audio / pdf) is a ToolHub fed with a list of
ToolSpecs. The hub knows nothing about images or PDFs.

i18n note: strings in this file use QCoreApplication.translate with an
explicit context. `self.tr()` in PySide6 takes its context from the
runtime class, which breaks lookups for shared base classes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QCoreApplication, Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from mediakit.ui.icons import GlyphIcon

TextFn = Callable[[], str]


@dataclass(frozen=True)
class ToolSpec:
    key: str
    icon: str
    title: TextFn
    description: TextFn
    # None = not built yet: the card is shown disabled with a badge.
    factory: Callable[[], QWidget] | None = None

    @property
    def available(self) -> bool:
        return self.factory is not None


class ToolCard(QFrame):
    """Clickable card: icon, title, one-line description."""

    clicked = Signal(str)

    def __init__(self, spec: ToolSpec, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.spec = spec
        self.setObjectName("ToolCard")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setMinimumSize(220, 132)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)

        top = QHBoxLayout()
        self.icon = GlyphIcon(spec.icon, 34)
        top.addWidget(self.icon)
        top.addStretch(1)
        self.badge = QLabel()
        self.badge.setObjectName("SoonBadge")
        top.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)

        self.title = QLabel()
        self.title.setObjectName("ToolCardTitle")
        layout.addWidget(self.title)

        self.description = QLabel()
        self.description.setObjectName("ToolCardDesc")
        self.description.setWordWrap(True)
        layout.addWidget(self.description)
        layout.addStretch(1)

        if spec.available:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.badge.hide()
        else:
            self.setEnabled(False)

    def retranslate(self) -> None:
        self.title.setText(self.spec.title())
        self.description.setText(self.spec.description())
        self.badge.setText(QCoreApplication.translate("ToolHub", "SOON"))
        self.setToolTip(self.spec.description())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.clicked.emit(self.spec.key)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        # Keyboard users can Tab to a card and open it with Enter/Space.
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit(self.spec.key)
            return
        super().keyPressEvent(event)


class _ToolPage(QWidget):
    """Header (back + title + description) wrapped around one tool."""

    back = Signal()

    def __init__(self, spec: ToolSpec, tool: QWidget) -> None:
        super().__init__()
        self.spec = spec
        self.tool = tool

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 0)
        layout.setSpacing(4)

        header = QHBoxLayout()
        self.back_btn = QPushButton()
        self.back_btn.setObjectName("BackButton")
        self.back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_btn.clicked.connect(self.back)
        header.addWidget(self.back_btn)
        header.addSpacing(8)
        self.icon = GlyphIcon(spec.icon, 26)
        header.addWidget(self.icon)
        self.title = QLabel()
        self.title.setObjectName("ScreenTitle")
        header.addWidget(self.title)
        header.addStretch(1)
        layout.addLayout(header)

        self.description = QLabel()
        self.description.setObjectName("Muted")
        self.description.setWordWrap(True)
        layout.addWidget(self.description)

        layout.addWidget(tool, 1)

    def retranslate(self) -> None:
        self.back_btn.setText(QCoreApplication.translate("ToolHub", "\u2190 All tools"))
        self.title.setText(self.spec.title())
        self.description.setText(self.spec.description())
        retranslate = getattr(self.tool, "retranslate", None)
        if callable(retranslate):
            retranslate()


class ToolHub(QWidget):
    """Home page with tool cards; opening a card swaps to its page."""

    CARD_MIN_WIDTH = 240

    def __init__(
        self,
        title: TextFn,
        subtitle: TextFn,
        specs: list[ToolSpec],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._title_fn = title
        self._subtitle_fn = subtitle
        self._specs = {spec.key: spec for spec in specs}
        self._pages: dict[str, _ToolPage] = {}
        self._columns = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._stack = QStackedWidget()
        outer.addWidget(self._stack)

        # --- home page ---
        home = QWidget()
        home_layout = QVBoxLayout(home)
        home_layout.setContentsMargins(24, 24, 24, 24)
        home_layout.setSpacing(6)

        self.title = QLabel()
        self.title.setObjectName("ScreenTitle")
        home_layout.addWidget(self.title)
        self.subtitle = QLabel()
        self.subtitle.setObjectName("Muted")
        home_layout.addWidget(self.subtitle)
        home_layout.addSpacing(12)

        scroll = QScrollArea()
        scroll.setObjectName("HubScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        grid_host = QWidget()
        grid_host.setObjectName("HubGrid")
        self._grid = QGridLayout(grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(14)
        scroll.setWidget(grid_host)
        home_layout.addWidget(scroll, 1)

        self._cards = [ToolCard(spec) for spec in specs]
        for card in self._cards:
            card.clicked.connect(self.open_tool)

        self._stack.addWidget(home)
        self._home = home
        self._relayout(3)
        self.retranslate()

    # ------------------------------------------------------- navigation

    def show_home(self) -> None:
        self._stack.setCurrentWidget(self._home)

    def open_tool(self, key: str) -> None:
        spec = self._specs.get(key)
        if spec is None or spec.factory is None:
            return
        page = self._pages.get(key)
        if page is None:
            # Built on first use: keeps startup fast and avoids loading
            # every module's dependencies before the user needs them.
            page = _ToolPage(spec, spec.factory())
            page.back.connect(self.show_home)
            page.retranslate()
            self._pages[key] = page
            self._stack.addWidget(page)
        self._stack.setCurrentWidget(page)

    def current_tool(self) -> QWidget | None:
        page = self._stack.currentWidget()
        return page.tool if isinstance(page, _ToolPage) else None

    # ----------------------------------------------------------- layout

    def _relayout(self, columns: int) -> None:
        if columns == self._columns:
            return
        self._columns = columns
        for card in self._cards:
            self._grid.removeWidget(card)
        for index, card in enumerate(self._cards):
            self._grid.addWidget(card, index // columns, index % columns)
        for column in range(4):
            self._grid.setColumnStretch(column, 1 if column < columns else 0)
        self._grid.setRowStretch(len(self._cards) // columns + 1, 1)

    def resizeEvent(self, event) -> None:
        usable = max(1, self.width() - 48)
        self._relayout(max(1, min(4, usable // self.CARD_MIN_WIDTH)))
        super().resizeEvent(event)

    # ------------------------------------------------------------- i18n

    def retranslate(self) -> None:
        self.title.setText(self._title_fn())
        self.subtitle.setText(self._subtitle_fn())
        for card in self._cards:
            card.retranslate()
        for page in self._pages.values():
            page.retranslate()
