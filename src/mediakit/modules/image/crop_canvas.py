"""Interactive crop rectangle over an image preview. Qt only.

Coordinates: the crop rect is stored in *preview image pixels* (after
EXIF orientation and the user's rotation). The tool converts it to
fractions (0..1) for the domain layer, so the downscaled preview and
the full-resolution file agree.

Interaction:
  - drag on empty area  -> draw a new rectangle
  - drag inside         -> move it
  - drag a corner       -> resize, opposite corner stays put
  - ratio lock          -> width/height forced to the chosen ratio
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Property, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QImage,
    QImageReader,
    QMouseEvent,
    QPainter,
    QPen,
    QTransform,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

PREVIEW_MAX = 2048  # longest side of the in-memory preview
HANDLE = 9  # corner handle half-size in screen pixels
MIN_SIZE = 8.0  # smallest crop, in image pixels


class CropCanvas(QWidget):
    crop_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._source: QImage = QImage()  # oriented, unrotated preview
        self._image: QImage = QImage()  # what is displayed (rotated)
        self._steps = 0  # clockwise quarter turns
        self._ratio: float | None = None  # width / height, None = free
        self._crop = QRectF()

        self._drag_mode: str | None = None  # "new" | "move" | "corner"
        self._anchor = QPointF()  # fixed point while resizing
        self._drag_origin = QPointF()
        self._crop_origin = QRectF()

        self._accent = QColor("#FFB000")
        self._shade = QColor(0, 0, 0, 140)

        # Custom QWidgets ignore QSS backgrounds unless asked to paint them.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setMouseTracking(True)
        self.setMinimumSize(QSize(320, 220))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    # ---------------------------------------------------- QSS properties
    def _get_accent(self) -> QColor:
        return self._accent

    def _set_accent(self, c: QColor) -> None:
        self._accent = QColor(c)
        self.update()

    def _get_shade(self) -> QColor:
        return self._shade

    def _set_shade(self, c: QColor) -> None:
        self._shade = QColor(c)
        self.update()

    accent = Property(QColor, _get_accent, _set_accent)
    shade = Property(QColor, _get_shade, _set_shade)

    # ------------------------------------------------------------ public
    def load(self, path: Path | None) -> bool:
        """Load a preview. Returns False if the file can't be decoded."""
        self._source = QImage()
        if path is not None:
            reader = QImageReader(str(path))
            # Same orientation the export pipeline applies (auto_orient).
            reader.setAutoTransform(True)
            size = reader.size()
            if size.isValid() and max(size.width(), size.height()) > PREVIEW_MAX:
                reader.setScaledSize(
                    size.scaled(PREVIEW_MAX, PREVIEW_MAX, Qt.AspectRatioMode.KeepAspectRatio)
                )
            self._source = reader.read()
        self._apply_rotation()
        return not self._source.isNull()

    def has_image(self) -> bool:
        return not self._image.isNull()

    def set_rotation_steps(self, steps: int) -> None:
        self._steps = steps % 4
        self._apply_rotation()

    def set_ratio(self, ratio: float | None) -> None:
        self._ratio = ratio
        self.reset_crop()

    def reset_crop(self) -> None:
        """Largest centred rect (respecting the ratio lock)."""
        if self._image.isNull():
            self._crop = QRectF()
        else:
            w, h = float(self._image.width()), float(self._image.height())
            if self._ratio is None:
                self._crop = QRectF(0, 0, w, h)
            elif w / h > self._ratio:
                cw = h * self._ratio
                self._crop = QRectF((w - cw) / 2, 0, cw, h)
            else:
                ch = w / self._ratio
                self._crop = QRectF(0, (h - ch) / 2, w, ch)
        self.update()
        self.crop_changed.emit()

    def crop_fractions(self) -> tuple[float, float, float, float] | None:
        """(left, top, right, bottom) as fractions of the rotated image."""
        if self._image.isNull() or self._crop.isEmpty():
            return None
        w, h = self._image.width(), self._image.height()
        r = self._crop
        return (r.left() / w, r.top() / h, r.right() / w, r.bottom() / h)

    def crop_pixel_size(self) -> tuple[int, int] | None:
        """Crop size in *preview* pixels, for display only."""
        if self._crop.isEmpty():
            return None
        return (round(self._crop.width()), round(self._crop.height()))

    # ---------------------------------------------------------- geometry
    def _apply_rotation(self) -> None:
        if self._source.isNull():
            self._image = QImage()
        elif self._steps == 0:
            self._image = self._source
        else:
            self._image = self._source.transformed(QTransform().rotate(90 * self._steps))
        self.reset_crop()

    def _view(self) -> tuple[float, QPointF]:
        """Scale and top-left offset that fit the image in the widget."""
        if self._image.isNull():
            return 1.0, QPointF()
        margin = 12
        avail_w = max(1, self.width() - 2 * margin)
        avail_h = max(1, self.height() - 2 * margin)
        scale = min(avail_w / self._image.width(), avail_h / self._image.height())
        draw_w = self._image.width() * scale
        draw_h = self._image.height() * scale
        offset = QPointF((self.width() - draw_w) / 2, (self.height() - draw_h) / 2)
        return scale, offset

    def _to_screen(self, rect: QRectF) -> QRectF:
        scale, off = self._view()
        return QRectF(
            off.x() + rect.x() * scale,
            off.y() + rect.y() * scale,
            rect.width() * scale,
            rect.height() * scale,
        )

    def _to_image(self, pos: QPointF) -> QPointF:
        scale, off = self._view()
        x = (pos.x() - off.x()) / scale
        y = (pos.y() - off.y()) / scale
        return QPointF(
            min(max(x, 0.0), float(self._image.width())),
            min(max(y, 0.0), float(self._image.height())),
        )

    def _covers_image(self) -> bool:
        """True while the crop is still (almost) the whole image.

        Then a press inside it starts a new rectangle: a full-size rect
        can't be moved anyway, so "move" would make drawing impossible.
        """
        if self._image.isNull():
            return False
        return (
            self._crop.width() >= self._image.width() * 0.99
            and self._crop.height() >= self._image.height() * 0.99
        )

    def _corners(self) -> list[QPointF]:
        r = self._crop
        return [r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft()]

    def _corner_at(self, screen_pos: QPointF) -> int | None:
        scale, off = self._view()
        for index, corner in enumerate(self._corners()):
            sx = off.x() + corner.x() * scale
            sy = off.y() + corner.y() * scale
            if abs(screen_pos.x() - sx) <= HANDLE + 3 and abs(screen_pos.y() - sy) <= HANDLE + 3:
                return index
        return None

    def _rect_from_anchor(self, anchor: QPointF, point: QPointF) -> QRectF:
        """Rect spanned by anchor and point, ratio-locked and clamped."""
        dx = point.x() - anchor.x()
        dy = point.y() - anchor.y()
        sign_x = 1.0 if dx >= 0 else -1.0
        sign_y = 1.0 if dy >= 0 else -1.0

        # Room available from the anchor towards the drag direction.
        max_w = (self._image.width() - anchor.x()) if sign_x > 0 else anchor.x()
        max_h = (self._image.height() - anchor.y()) if sign_y > 0 else anchor.y()

        w = min(abs(dx), max_w)
        h = min(abs(dy), max_h)

        if self._ratio is not None:
            # Grow along whichever side the user dragged further, then
            # shrink both if the other side would leave the image.
            if h == 0 or w / max(h, 1e-6) > self._ratio:
                h = w / self._ratio
            else:
                w = h * self._ratio
            if w > max_w:
                w = max_w
                h = w / self._ratio
            if h > max_h:
                h = max_h
                w = h * self._ratio

        x = anchor.x() if sign_x > 0 else anchor.x() - w
        y = anchor.y() if sign_y > 0 else anchor.y() - h
        return QRectF(x, y, w, h)

    # -------------------------------------------------------------- mouse
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._image.isNull() or event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position()
        corner = self._corner_at(pos)
        point = self._to_image(pos)
        if corner is not None:
            self._drag_mode = "corner"
            # Opposite corner stays fixed.
            self._anchor = self._corners()[(corner + 2) % 4]
        elif self._crop.contains(point) and not self._covers_image():
            self._drag_mode = "move"
            self._drag_origin = point
            self._crop_origin = QRectF(self._crop)
        else:
            self._drag_mode = "new"
            self._anchor = point
            self._crop = QRectF(point, point)
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position()
        if self._drag_mode is None:
            self._update_cursor(pos)
            return
        point = self._to_image(pos)
        if self._drag_mode in ("new", "corner"):
            self._crop = self._rect_from_anchor(self._anchor, point)
        elif self._drag_mode == "move":
            delta = point - self._drag_origin
            moved = self._crop_origin.translated(delta)
            # Keep the whole rect inside the image.
            dx = min(0.0, self._image.width() - moved.right()) + max(0.0, -moved.left())
            dy = min(0.0, self._image.height() - moved.bottom()) + max(0.0, -moved.top())
            self._crop = moved.translated(dx, dy)
        self.update()
        self.crop_changed.emit()

    def mouseReleaseEvent(self, _event: QMouseEvent) -> None:
        if self._drag_mode is None:
            return
        self._drag_mode = None
        # A click without a drag would leave a zero-size rect: undo it.
        if self._crop.width() < MIN_SIZE or self._crop.height() < MIN_SIZE:
            self.reset_crop()
        self.update()
        self.crop_changed.emit()

    def _update_cursor(self, pos: QPointF) -> None:
        if self._image.isNull():
            self.unsetCursor()
            return
        corner = self._corner_at(pos)
        if corner in (0, 2):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif corner in (1, 3):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif self._crop.contains(self._to_image(pos)) and not self._covers_image():
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)

    # ----------------------------------------------------------- painting
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self._image.isNull():
            p.end()
            return

        image_rect = self._to_screen(QRectF(0, 0, self._image.width(), self._image.height()))
        p.drawImage(image_rect, self._image)

        if not self._crop.isEmpty():
            crop = self._to_screen(self._crop)
            # Darken everything outside the crop (four bands).
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self._shade)
            p.drawRect(
                QRectF(
                    image_rect.left(),
                    image_rect.top(),
                    image_rect.width(),
                    crop.top() - image_rect.top(),
                )
            )
            p.drawRect(
                QRectF(
                    image_rect.left(),
                    crop.bottom(),
                    image_rect.width(),
                    image_rect.bottom() - crop.bottom(),
                )
            )
            p.drawRect(
                QRectF(
                    image_rect.left(), crop.top(), crop.left() - image_rect.left(), crop.height()
                )
            )
            p.drawRect(
                QRectF(crop.right(), crop.top(), image_rect.right() - crop.right(), crop.height())
            )

            # Rule-of-thirds guides.
            guide = QPen(QColor(255, 255, 255, 90), 1)
            p.setPen(guide)
            for i in (1, 2):
                x = crop.left() + crop.width() * i / 3
                y = crop.top() + crop.height() * i / 3
                p.drawLine(QPointF(x, crop.top()), QPointF(x, crop.bottom()))
                p.drawLine(QPointF(crop.left(), y), QPointF(crop.right(), y))

            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(self._accent, 2))
            p.drawRect(crop)

            p.setBrush(self._accent)
            p.setPen(Qt.PenStyle.NoPen)
            for corner in (crop.topLeft(), crop.topRight(), crop.bottomRight(), crop.bottomLeft()):
                p.drawRect(QRectF(corner.x() - HANDLE / 2, corner.y() - HANDLE / 2, HANDLE, HANDLE))
        p.end()
