"""Small vector icons painted with QPainter.

Why painted instead of icon fonts or PNG files:
- no font-coverage risk on Windows (missing glyphs render as boxes),
- no binary assets to bundle,
- colours come from QSS (`color` and `qproperty-accent`), so icons
  follow the dark/light theme switch automatically.

Every painter draws into a unit box (0..1) scaled to the widget, which
keeps the drawing code independent of icon size.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Property, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QWidget

Painter = Callable[[QPainter, QColor, QColor], None]


def _pen(color: QColor, width: float = 0.07) -> QPen:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _arrow(p: QPainter, x1: float, y1: float, x2: float, y2: float, head: float = 0.14) -> None:
    """Line from (x1,y1) to (x2,y2) with an arrow head at the end."""
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    dx, dy = x2 - x1, y2 - y1
    length = (dx * dx + dy * dy) ** 0.5 or 1.0
    ux, uy = dx / length, dy / length
    # Two short strokes at +-45 degrees from the shaft.
    for sx, sy in ((-ux - uy, -uy + ux), (-ux + uy, -uy - ux)):
        p.drawLine(QPointF(x2, y2), QPointF(x2 + sx * head * 0.7, y2 + sy * head * 0.7))


def _doc(p: QPainter, x: float, y: float, w: float, h: float) -> None:
    """A page with a folded corner."""
    fold = min(w, h) * 0.28
    path = QPainterPath()
    path.moveTo(x, y)
    path.lineTo(x + w - fold, y)
    path.lineTo(x + w, y + fold)
    path.lineTo(x + w, y + h)
    path.lineTo(x, y + h)
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(QPointF(x + w - fold, y), QPointF(x + w - fold, y + fold))
    p.drawLine(QPointF(x + w - fold, y + fold), QPointF(x + w, y + fold))


def _wave(p: QPainter, x: float, y: float, w: float, h: float, bars: int = 7) -> None:
    heights = (0.35, 0.7, 1.0, 0.55, 0.85, 0.4, 0.6, 0.3, 0.75)
    step = w / (bars - 1)
    for i in range(bars):
        bh = h * heights[i % len(heights)]
        cx = x + i * step
        p.drawLine(QPointF(cx, y - bh / 2), QPointF(cx, y + bh / 2))


# --------------------------------------------------------------- image


def _convert(p: QPainter, ink: QColor, accent: QColor) -> None:
    p.setPen(_pen(ink))
    _arrow(p, 0.15, 0.36, 0.85, 0.36)
    p.setPen(_pen(accent))
    _arrow(p, 0.85, 0.64, 0.15, 0.64)


def _resize(p: QPainter, ink: QColor, accent: QColor) -> None:
    p.setPen(_pen(ink))
    p.drawRect(QRectF(0.12, 0.12, 0.76, 0.76))
    p.setPen(_pen(accent))
    _arrow(p, 0.32, 0.68, 0.70, 0.30)
    _arrow(p, 0.68, 0.32, 0.30, 0.70)


def _crop(p: QPainter, ink: QColor, accent: QColor) -> None:
    p.setPen(_pen(ink, 0.08))
    p.drawPolyline([QPointF(0.28, 0.08), QPointF(0.28, 0.72), QPointF(0.92, 0.72)])
    p.drawPolyline([QPointF(0.08, 0.28), QPointF(0.72, 0.28), QPointF(0.72, 0.92)])
    p.setPen(_pen(accent, 0.06))
    p.drawLine(QPointF(0.18, 0.82), QPointF(0.82, 0.18))


def _compress(p: QPainter, ink: QColor, accent: QColor) -> None:
    p.setPen(_pen(accent))
    _arrow(p, 0.10, 0.10, 0.38, 0.38, 0.12)
    _arrow(p, 0.90, 0.10, 0.62, 0.38, 0.12)
    _arrow(p, 0.10, 0.90, 0.38, 0.62, 0.12)
    _arrow(p, 0.90, 0.90, 0.62, 0.62, 0.12)
    p.setPen(_pen(ink, 0.05))
    p.drawRect(QRectF(0.44, 0.44, 0.12, 0.12))


def _metadata(p: QPainter, ink: QColor, accent: QColor) -> None:
    p.setPen(_pen(ink))
    path = QPainterPath()
    path.moveTo(0.12, 0.30)
    path.lineTo(0.55, 0.30)
    path.lineTo(0.85, 0.55)
    path.lineTo(0.55, 0.80)
    path.lineTo(0.12, 0.80)
    path.closeSubpath()
    p.drawPath(path)
    p.setPen(_pen(accent))
    p.drawLine(QPointF(0.10, 0.10), QPointF(0.90, 0.92))


def _watermark(p: QPainter, ink: QColor, accent: QColor) -> None:
    p.setPen(_pen(ink))
    p.drawRect(QRectF(0.10, 0.14, 0.80, 0.72))
    p.setPen(_pen(accent))
    p.drawPolyline(
        [
            QPointF(0.26, 0.38),
            QPointF(0.36, 0.64),
            QPointF(0.50, 0.44),
            QPointF(0.64, 0.64),
            QPointF(0.74, 0.38),
        ]
    )


def _background(p: QPainter, ink: QColor, accent: QColor) -> None:
    dashed = _pen(ink, 0.05)
    dashed.setStyle(Qt.PenStyle.DashLine)
    p.setPen(dashed)
    p.drawRect(QRectF(0.08, 0.08, 0.84, 0.84))
    p.setPen(_pen(accent))
    p.drawEllipse(QRectF(0.38, 0.22, 0.24, 0.24))
    p.drawArc(QRectF(0.24, 0.52, 0.52, 0.50), 0, 180 * 16)


def _upscale(p: QPainter, ink: QColor, accent: QColor) -> None:
    p.setPen(_pen(ink))
    p.drawRect(QRectF(0.08, 0.58, 0.30, 0.30))
    p.drawRect(QRectF(0.40, 0.10, 0.50, 0.50))
    p.setPen(_pen(accent))
    _arrow(p, 0.28, 0.66, 0.56, 0.38, 0.12)


# --------------------------------------------------------------- audio


def _audio_convert(p: QPainter, ink: QColor, accent: QColor) -> None:
    p.setPen(_pen(ink, 0.06))
    _wave(p, 0.12, 0.34, 0.76, 0.32)
    p.setPen(_pen(accent))
    _arrow(p, 0.15, 0.76, 0.85, 0.76)


def _transcribe(p: QPainter, ink: QColor, accent: QColor) -> None:
    p.setPen(_pen(accent, 0.06))
    _wave(p, 0.10, 0.30, 0.36, 0.40, 5)
    p.setPen(_pen(ink, 0.06))
    for y in (0.62, 0.76, 0.90):
        p.drawLine(QPointF(0.10, y), QPointF(0.90 if y < 0.9 else 0.62, y))
    p.drawLine(QPointF(0.58, 0.22), QPointF(0.90, 0.22))
    p.drawLine(QPointF(0.58, 0.38), QPointF(0.82, 0.38))


def _denoise(p: QPainter, ink: QColor, accent: QColor) -> None:
    p.setPen(_pen(ink, 0.06))
    _wave(p, 0.12, 0.5, 0.76, 0.6, 9)
    p.setPen(_pen(accent))
    p.drawLine(QPointF(0.08, 0.90), QPointF(0.92, 0.10))


def _tts(p: QPainter, ink: QColor, accent: QColor) -> None:
    p.setPen(_pen(ink, 0.06))
    for y in (0.30, 0.50, 0.70):
        p.drawLine(QPointF(0.08, y), QPointF(0.38, y))
    p.setPen(_pen(accent))
    _arrow(p, 0.44, 0.50, 0.58, 0.50, 0.08)
    p.setPen(_pen(ink, 0.06))
    _wave(p, 0.66, 0.50, 0.26, 0.6, 4)


def _record(p: QPainter, ink: QColor, accent: QColor) -> None:
    p.setPen(_pen(ink))
    p.drawEllipse(QRectF(0.12, 0.12, 0.76, 0.76))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(accent)
    p.drawEllipse(QRectF(0.32, 0.32, 0.36, 0.36))
    p.setBrush(Qt.BrushStyle.NoBrush)


# ----------------------------------------------------------------- pdf


def _pdf_merge(p: QPainter, ink: QColor, accent: QColor) -> None:
    p.setPen(_pen(ink, 0.06))
    _doc(p, 0.06, 0.08, 0.30, 0.40)
    _doc(p, 0.06, 0.54, 0.30, 0.40)
    p.setPen(_pen(accent, 0.06))
    _doc(p, 0.62, 0.28, 0.32, 0.44)
    _arrow(p, 0.40, 0.30, 0.56, 0.44, 0.08)
    _arrow(p, 0.40, 0.72, 0.56, 0.58, 0.08)


def _pdf_split(p: QPainter, ink: QColor, accent: QColor) -> None:
    p.setPen(_pen(ink, 0.06))
    _doc(p, 0.06, 0.28, 0.32, 0.44)
    p.setPen(_pen(accent, 0.06))
    _doc(p, 0.64, 0.08, 0.30, 0.40)
    _doc(p, 0.64, 0.54, 0.30, 0.40)
    _arrow(p, 0.42, 0.44, 0.58, 0.30, 0.08)
    _arrow(p, 0.42, 0.58, 0.58, 0.72, 0.08)


def _pdf_pages(p: QPainter, ink: QColor, accent: QColor) -> None:
    p.setPen(_pen(ink, 0.06))
    _doc(p, 0.08, 0.10, 0.36, 0.48)
    _doc(p, 0.56, 0.10, 0.36, 0.48)
    p.setPen(_pen(accent))
    p.drawArc(QRectF(0.22, 0.52, 0.56, 0.40), 200 * 16, 140 * 16)
    _arrow(p, 0.70, 0.86, 0.76, 0.70, 0.08)


def _pdf_compress(p: QPainter, ink: QColor, accent: QColor) -> None:
    p.setPen(_pen(ink, 0.06))
    _doc(p, 0.30, 0.22, 0.40, 0.56)
    p.setPen(_pen(accent, 0.06))
    _arrow(p, 0.50, 0.02, 0.50, 0.18, 0.08)
    _arrow(p, 0.50, 0.98, 0.50, 0.82, 0.08)


def _pdf_from(p: QPainter, ink: QColor, accent: QColor) -> None:
    p.setPen(_pen(ink, 0.06))
    _doc(p, 0.06, 0.18, 0.36, 0.64)
    p.setPen(_pen(accent))
    _arrow(p, 0.48, 0.50, 0.70, 0.50, 0.08)
    p.setPen(_pen(ink, 0.06))
    p.drawRect(QRectF(0.74, 0.30, 0.20, 0.40))


def _pdf_to(p: QPainter, ink: QColor, accent: QColor) -> None:
    p.setPen(_pen(ink, 0.06))
    p.drawRect(QRectF(0.06, 0.30, 0.20, 0.40))
    p.setPen(_pen(accent))
    _arrow(p, 0.30, 0.50, 0.52, 0.50, 0.08)
    p.setPen(_pen(ink, 0.06))
    _doc(p, 0.58, 0.18, 0.36, 0.64)


def _pdf_stamp(p: QPainter, ink: QColor, accent: QColor) -> None:
    p.setPen(_pen(ink, 0.06))
    _doc(p, 0.18, 0.08, 0.64, 0.84)
    p.setPen(_pen(accent, 0.06))
    p.drawLine(QPointF(0.32, 0.40), QPointF(0.68, 0.40))
    p.drawLine(QPointF(0.32, 0.54), QPointF(0.60, 0.54))
    p.drawLine(QPointF(0.44, 0.78), QPointF(0.56, 0.78))


def _lock(p: QPainter, ink: QColor, accent: QColor) -> None:
    p.setPen(_pen(ink))
    p.drawArc(QRectF(0.30, 0.10, 0.40, 0.46), 0, 180 * 16)
    p.drawLine(QPointF(0.30, 0.33), QPointF(0.30, 0.44))
    p.drawLine(QPointF(0.70, 0.33), QPointF(0.70, 0.44))
    p.drawRect(QRectF(0.20, 0.44, 0.60, 0.46))
    p.setPen(_pen(accent, 0.09))
    p.drawLine(QPointF(0.50, 0.60), QPointF(0.50, 0.74))


def _rotate_ccw(p: QPainter, ink: QColor, accent: QColor) -> None:
    # Qt arc angles are counter-clockwise-positive: this open circle
    # has its gap at the top and the arrow head points left (CCW).
    p.setPen(_pen(ink, 0.08))
    p.drawArc(QRectF(0.16, 0.18, 0.66, 0.66), 100 * 16, -280 * 16)
    p.drawLine(QPointF(0.44, 0.19), QPointF(0.58, 0.08))
    p.drawLine(QPointF(0.44, 0.19), QPointF(0.58, 0.31))


def _rotate_cw(p: QPainter, ink: QColor, accent: QColor) -> None:
    # Mirror image of the CCW arrow.
    p.save()
    p.translate(1.0, 0.0)
    p.scale(-1.0, 1.0)
    _rotate_ccw(p, ink, accent)
    p.restore()


def _generic(p: QPainter, ink: QColor, accent: QColor) -> None:
    p.setPen(_pen(ink))
    p.drawRect(QRectF(0.18, 0.18, 0.64, 0.64))


ICON_PAINTERS: dict[str, Painter] = {
    "convert": _convert,
    "resize": _resize,
    "crop": _crop,
    "compress": _compress,
    "metadata": _metadata,
    "watermark": _watermark,
    "background": _background,
    "upscale": _upscale,
    "audio_convert": _audio_convert,
    "transcribe": _transcribe,
    "denoise": _denoise,
    "tts": _tts,
    "record": _record,
    "pdf_merge": _pdf_merge,
    "pdf_split": _pdf_split,
    "pdf_pages": _pdf_pages,
    "pdf_compress": _pdf_compress,
    "pdf_from": _pdf_from,
    "pdf_to": _pdf_to,
    "pdf_stamp": _pdf_stamp,
    "lock": _lock,
    "rotate_cw": _rotate_cw,
    "rotate_ccw": _rotate_ccw,
}


class GlyphIcon(QWidget):
    """A widget that paints one named icon.

    QSS hooks:  GlyphIcon { color: <ink>; qproperty-accent: <accent>; }
    """

    def __init__(self, kind: str, size: int = 32, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._kind = kind
        self._accent = QColor("#FFB000")
        self.setFixedSize(QSize(size, size))
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def _get_accent(self) -> QColor:
        return self._accent

    def _set_accent(self, color: QColor) -> None:
        self._accent = QColor(color)
        self.update()

    accent = Property(QColor, _get_accent, _set_accent)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height())
        painter.scale(side, side)
        ink = self.palette().color(QPalette.ColorRole.WindowText)
        accent = self._accent
        if not self.isEnabled():
            ink.setAlphaF(0.45)
            accent = QColor(ink)
        ICON_PAINTERS.get(self._kind, _generic)(painter, ink, accent)
        painter.end()
