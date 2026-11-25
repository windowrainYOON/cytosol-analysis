"""Histogram — the brightness range of one channel (design system ``hig-histogram``).

A board 64 high (radius 8) on the card surface: the channel's log
histogram as bars in the channel colour at 50 %, the part outside the LUT
range under a ``label`` 8 % veil, the range lines and two ▲ handles in the
accent colour. With ``editable`` the handles are dragged (and ←/→ move the
focused handle by one step, ⇧ by ten); ``rangeEdited(vmin, vmax)`` carries
the new values to the Min / Max number rows under the histogram, which stay
the source of truth (both ways).

Variants: ``lut`` (LUT tab, editable), ``threshold`` (입자 추적 신호 기준,
editable), ``mini`` (no handles, 40 high).
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

HEIGHT = 64
RADIUS = 8
HANDLE = 7  # half width of a ▲ handle
VARIANTS = ('lut', 'threshold', 'mini')


def qcolor(rgb) -> QColor:
    return QColor.fromRgbF(*[float(c) for c in rgb])


class Histogram(QWidget):
    """Log histogram of a channel with the current LUT range drawn on top."""

    rangeEdited = Signal(float, float)

    def __init__(self, variant: str = 'lut', editable: bool = False):
        super().__init__()
        self.variant = variant if variant in VARIANTS else 'lut'
        self.editable = editable and self.variant != 'mini'
        h = 40 if self.variant == 'mini' else HEIGHT
        self.setMinimumHeight(h + (HANDLE + 2 if self.editable else 0))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(self.minimumHeight())
        self.setProperty('hig_histogram', self.variant)
        self.counts = None
        self.lo = self.hi = 0.0
        self.vmin = self.vmax = 0.0
        self.color = (1, 1, 1)
        self._drag = None  # 'min' / 'max' while dragging
        self._focus = 'min'
        if self.editable:
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            self.setToolTip('▲ 끌기: Min / Max · ←→ 한 단계, ⇧ 열 단계')

    def set_data(self, plane, lo, hi):
        self.lo, self.hi = lo, hi
        if plane.size > 1_000_000:  # a quarter of the pixels draws the same curve
            plane = plane[::2, ::2]
        counts, _ = np.histogram(plane, bins=128, range=(lo, hi))
        self.counts = np.log1p(counts.astype(np.float64))
        self.update()

    def set_lut(self, vmin, vmax, color):
        self.vmin, self.vmax, self.color = vmin, vmax, color
        self.update()

    # -- geometry ------------------------------------------------------------
    def _board(self) -> QRectF:
        return QRectF(0.5, 0.5, self.width() - 1, (40 if self.variant == 'mini' else HEIGHT) - 1)

    def _x(self, v: float) -> float:
        b = self._board()
        span = max(self.hi - self.lo, 1e-12)
        return b.left() + (v - self.lo) / span * b.width()

    def _value(self, x: float) -> float:
        b = self._board()
        f = min(max((x - b.left()) / max(b.width(), 1), 0.0), 1.0)
        return self.lo + f * (self.hi - self.lo)

    # -- drawing -------------------------------------------------------------
    def paintEvent(self, _):
        from .. import theme  # noqa: PLC0415

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        b = self._board()
        board = QPainterPath()
        board.addRoundedRect(b, RADIUS, RADIUS)
        p.fillPath(board, theme.color('fill-quaternary'))
        p.setClipPath(board)
        if self.counts is not None and self.counts.max() > 0:
            c = self.counts / self.counts.max()
            n = len(c)
            bw = b.width() / n
            col = qcolor(self.color)
            col.setAlphaF(0.5)
            bars = QPainterPath()
            for i, v in enumerate(c):
                if v > 0:
                    hh = v * (b.height() - 6)
                    bars.addRect(QRectF(b.left() + i * bw, b.bottom() - hh, bw + 0.3, hh))
            p.fillPath(bars, col)
            # outside the LUT range: label 8 % veil
            veil = theme.color('label')
            veil.setAlphaF(0.08)
            x0, x1 = self._x(self.vmin), self._x(self.vmax)
            p.fillRect(QRectF(b.left(), b.top(), max(x0 - b.left(), 0), b.height()), veil)
            p.fillRect(QRectF(x1, b.top(), max(b.right() - x1, 0), b.height()), veil)
            accent = theme.color('accent')
            p.setPen(QPen(accent, 1.2))
            p.drawLine(QPointF(x0, b.bottom()), QPointF(x1, b.top() + 2))  # the LUT ramp
            p.setPen(QPen(accent, 1))
            p.drawLine(QPointF(x0, b.top()), QPointF(x0, b.bottom()))
            p.drawLine(QPointF(x1, b.top()), QPointF(x1, b.bottom()))
        p.setClipping(False)
        if self.editable and self.counts is not None:
            accent = theme.color('accent')
            for key, v in (('min', self.vmin), ('max', self.vmax)):
                x = self._x(v)
                y = b.bottom() + 1
                tri = QPolygonF([QPointF(x, y), QPointF(x - HANDLE, y + HANDLE + 1),
                                 QPointF(x + HANDLE, y + HANDLE + 1)])
                p.setPen(QPen(accent, 1))
                active = self._drag == key or (self.hasFocus() and self._focus == key)
                p.setBrush(accent if active else theme.color('background-tertiary'))
                p.drawPolygon(tri)
        p.end()

    # -- editing -------------------------------------------------------------
    def _nearest(self, x: float) -> str:
        return 'min' if abs(x - self._x(self.vmin)) <= abs(x - self._x(self.vmax)) else 'max'

    def _set(self, key: str, v: float):
        if key == 'min':
            self.vmin = min(v, self.vmax)
        else:
            self.vmax = max(v, self.vmin)
        self.update()
        self.rangeEdited.emit(float(self.vmin), float(self.vmax))

    def mousePressEvent(self, e):
        if not self.editable or e.button() != Qt.MouseButton.LeftButton or self.counts is None:
            return super().mousePressEvent(e)
        self._drag = self._focus = self._nearest(e.position().x())
        self._set(self._drag, self._value(e.position().x()))

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self._set(self._drag, self._value(e.position().x()))
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._drag is not None:
            self._drag = None
            self.update()
            return
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        if not self.editable or self.counts is None:
            return super().keyPressEvent(e)
        k = e.key()
        if k in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self._focus = 'max' if self._focus == 'min' else 'min'
            self.update()
            return
        if k in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            step = (self.hi - self.lo) / 128 * (10 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier
                                                 else 1)
            v = self.vmin if self._focus == 'min' else self.vmax
            self._set(self._focus, min(max(v + (step if k == Qt.Key.Key_Right else -step),
                                           self.lo), self.hi))
            return
        super().keyPressEvent(e)
