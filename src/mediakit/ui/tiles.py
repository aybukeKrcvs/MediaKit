"""Selectable tiles: a small drawing plus a label and caption.

Used for aspect-ratio pickers, rotate buttons and similar "pick one of
these" controls. Painted rather than icon+text QToolButtons so the
shape inside (e.g. a 16:9 rectangle) can be drawn to exact proportions
and recoloured by the theme.

QSS hooks:
  ChoiceTile { color: <ink>; background: <panel>; qproperty-accent: <accent>;
               qproperty-line: <line>; qproperty-muted: <muted>; }
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Property, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPalette, QPen
from PySide6.QtWidgets import QAbstractButton, QSizePolicy, QWidget

from mediakit.ui.icons import ICON_PAINTERS

# draw(painter, rect, ink, accent) - rect is where the drawing goes.
DrawFn = Callable[[QPainter, QRectF, QColor, QColor], None]


def ratio_drawing(w: int, h: int) -> DrawFn:
    """Draw a rectangle with the given proportions, centred."""

    def draw(p: QPainter, rect: QRectF, ink: QColor, _accent: QColor) -> None:
        scale = min(rect.width() / w, rect.height() / h) * 0.8
        rw, rh = w * scale, h * scale
        box = QRectF(rect.center().x() - rw / 2, rect.center().y() - rh / 2, rw, rh)
        pen = QPen(ink, 2)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawRoundedRect(box, 2, 2)

    return draw


def free_drawing() -> DrawFn:
    """Dashed square: 'no fixed ratio'."""

    def draw(p: QPainter, rect: QRectF, ink: QColor, _accent: QColor) -> None:
        side = min(rect.width(), rect.height()) * 0.7
        box = QRectF(rect.center().x() - side / 2, rect.center().y() - side / 2, side, side)
        pen = QPen(ink, 2, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawRect(box)

    return draw


def picture_drawing() -> DrawFn:
    """Frame with a little mountain and sun: 'the image as it is'."""

    def draw(p: QPainter, rect: QRectF, ink: QColor, accent: QColor) -> None:
        side = min(rect.width(), rect.height()) * 0.8
        box = QRectF(
            rect.center().x() - side / 2, rect.center().y() - side * 0.38, side, side * 0.76
        )
        pen = QPen(ink, 2)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawRoundedRect(box, 2, 2)
        p.drawPolyline(
            [
                QPointF(box.left() + 3, box.bottom() - 3),
                QPointF(box.left() + side * 0.35, box.top() + side * 0.38),
                QPointF(box.left() + side * 0.55, box.top() + side * 0.55),
                QPointF(box.left() + side * 0.7, box.top() + side * 0.45),
                QPointF(box.right() - 3, box.bottom() - 3),
            ]
        )
        p.setPen(QPen(accent, 2))
        p.drawEllipse(
            QPointF(box.right() - side * 0.2, box.top() + side * 0.2), side * 0.07, side * 0.07
        )

    return draw


def text_drawing(text: str) -> DrawFn:
    """Big monospace text, e.g. a file format name."""

    def draw(p: QPainter, rect: QRectF, ink: QColor, _accent: QColor) -> None:
        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setBold(True)
        font.setPixelSize(max(10, int(rect.height() * 0.42)))
        p.setFont(font)
        p.setPen(ink)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    return draw


def glyph_drawing(kind: str) -> DrawFn:
    """Reuse an icons.py painter inside a tile."""
    painter_fn = ICON_PAINTERS[kind]

    def draw(p: QPainter, rect: QRectF, ink: QColor, accent: QColor) -> None:
        side = min(rect.width(), rect.height()) * 0.8
        p.save()
        p.translate(rect.center().x() - side / 2, rect.center().y() - side / 2)
        p.scale(side, side)
        painter_fn(p, ink, accent)
        p.restore()

    return draw


class ChoiceTile(QAbstractButton):
    """Checkable tile: drawing on top, bold label, small caption."""

    def __init__(
        self,
        drawing: DrawFn,
        label: str = "",
        caption: str = "",
        size: QSize | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._drawing = drawing
        self._label = label
        self._caption = caption
        self._accent = QColor("#FFB000")
        self._line = QColor("#33302A")
        self._muted = QColor("#8A8477")
        self._panel = QColor("#15110B")
        self.setCheckable(True)
        self.setFixedSize(size if size is not None else QSize(96, 104))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    # --- QSS-settable colours -------------------------------------------
    def _get_accent(self) -> QColor:
        return self._accent

    def _set_accent(self, c: QColor) -> None:
        self._accent = QColor(c)
        self.update()

    def _get_line(self) -> QColor:
        return self._line

    def _set_line(self, c: QColor) -> None:
        self._line = QColor(c)
        self.update()

    def _get_muted(self) -> QColor:
        return self._muted

    def _set_muted(self, c: QColor) -> None:
        self._muted = QColor(c)
        self.update()

    def _get_panel(self) -> QColor:
        return self._panel

    def _set_panel(self, c: QColor) -> None:
        self._panel = QColor(c)
        self.update()

    accent = Property(QColor, _get_accent, _set_accent)
    line = Property(QColor, _get_line, _set_line)
    muted = Property(QColor, _get_muted, _set_muted)
    panel = Property(QColor, _get_panel, _set_panel)

    # --- text -------------------------------------------------------------
    def set_texts(self, label: str, caption: str = "", tooltip: str = "") -> None:
        self._label = label
        self._caption = caption
        self.setToolTip(tooltip or (f"{label}: {caption}" if caption else label))
        self.setAccessibleName(label)
        self.update()

    def sizeHint(self) -> QSize:
        return self.size()

    # --- painting ---------------------------------------------------------
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        ink = self.palette().color(QPalette.ColorRole.WindowText)
        enabled = self.isEnabled()
        checked = self.isChecked()
        hovered = self.underMouse() and enabled

        has_text = bool(self._label)
        text_h = 0
        if has_text:
            text_h = 34 if self._caption else 20
        tile = QRectF(1, 1, self.width() - 2, self.height() - 2 - text_h)

        border = self._accent if (checked or hovered or self.hasFocus()) else self._line
        if not enabled:
            border = self._line
            ink = QColor(self._muted)
        p.setPen(QPen(border, 2 if checked else 1))
        p.setBrush(self._panel)
        p.drawRoundedRect(tile.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)

        drawing_color = self._accent if checked else ink
        # Padding scales with the tile so small icon-only tiles stay legible.
        pad = max(5.0, min(12.0, tile.height() * 0.16))
        self._drawing(p, tile.adjusted(pad, pad, -pad, -pad), drawing_color, self._accent)

        if has_text:
            font = QFont(self.font())
            font.setBold(True)
            p.setFont(font)
            p.setPen(self._accent if checked else ink)
            label_rect = QRectF(0, tile.bottom() + 4, self.width(), 16)
            p.drawText(
                label_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self._label
            )
            if self._caption:
                small = QFont(self.font())
                small.setPointSizeF(max(6.5, self.font().pointSizeF() - 1.5))
                p.setFont(small)
                p.setPen(self._muted)
                cap_rect = QRectF(0, tile.bottom() + 20, self.width(), 14)
                elided = p.fontMetrics().elidedText(
                    self._caption, Qt.TextElideMode.ElideRight, self.width() - 4
                )
                p.drawText(
                    cap_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, elided
                )
        p.end()
