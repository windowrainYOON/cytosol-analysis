"""자 (ruler) on the canvas (owner request 2026-11-24, v0.74).

A temporary line like the line profile's: drawn with the ruler icon on,
gone when the icon is turned off (never saved). Ticks every 1 µm along the
line (every 5 µm longer, every 10 µm longest), the length written beside the
end ("10.3 µm"). The item paints in screen pixels, so ticks and text keep their
size at every zoom; when 1 µm is closer than ``MIN_GAP`` screen px only the
5 / 10 µm ticks are drawn.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QTransform
from PySide6.QtWidgets import QGraphicsItem

MIN_GAP = 4.0  # screen px between drawn ticks
TICK = (4.0, 7.0, 10.0)  # half lengths (screen px): 1 µm, 5 µm, 10 µm
WHITE = QColor(255, 255, 255)
SHADOW = QColor(0, 0, 0, 170)


def length_um(line, pixel_um) -> float | None:
    x0, y0, x1, y1 = line
    if not pixel_um:
        return None
    return math.hypot(x1 - x0, y1 - y0) * float(pixel_um)


def label(line, pixel_um) -> str:
    """'10.3 µm' (pixels when the image has no pixel size)."""
    um = length_um(line, pixel_um)
    if um is None:
        x0, y0, x1, y1 = line
        return f'{math.hypot(x1 - x0, y1 - y0):.1f} px'
    return f'{um:.3g} µm' if um < 10 else f'{um:.1f} µm'


def ticks(line, pixel_um, px_per_um_screen: float | None = None):
    """[(distance µm, level 0 / 1 / 2)] every 1 µm from the start (0 included).
    With px_per_um_screen, levels too dense to see are left out."""
    um = length_um(line, pixel_um)
    if um is None:
        return []
    step = 1
    if px_per_um_screen is not None:
        if px_per_um_screen < MIN_GAP:
            step = 5
        if px_per_um_screen * 5 < MIN_GAP:
            step = 10
        if px_per_um_screen * 10 < MIN_GAP:
            return [(0.0, 2)]
    out = []
    for k in range(0, int(math.floor(um + 1e-9)) + 1, step):
        out.append((float(k), 2 if k % 10 == 0 else 1 if k % 5 == 0 else 0))
    return out


class RulerItem(QGraphicsItem):
    """The ruler line with ticks and its length, drawn in screen pixels."""

    def __init__(self, line, pixel_um, bounds: QRectF):
        """pixel_um: µm per image pixel, or a callable giving it."""
        super().__init__()
        self.line = tuple(float(v) for v in line)
        self.pixel_um = pixel_um
        self._bounds = QRectF(bounds)
        self.setZValue(26)

    def set_line(self, line):
        self.line = tuple(float(v) for v in line)
        self.update()

    def boundingRect(self) -> QRectF:  # the whole image (+ room for the label)
        b = self._bounds
        m = max(b.width(), b.height()) * 0.5 + 50
        return b.adjusted(-m, -m, m, m)

    def um(self):
        v = self.pixel_um() if callable(self.pixel_um) else self.pixel_um
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        return v if v > 0 else None

    def paint(self, p: QPainter, _opt, _w=None):
        x0, y0, x1, y1 = self.line
        um = self.um()  # read each time: the image shown may have changed
        t = p.worldTransform()
        a, b = t.map(QPointF(x0, y0)), t.map(QPointF(x1, y1))
        dx, dy = b.x() - a.x(), b.y() - a.y()
        L = math.hypot(dx, dy)
        p.save()
        p.setWorldTransform(QTransform())
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        ux, uy = (dx / L, dy / L) if L > 0 else (1.0, 0.0)
        nx, ny = -uy, ux
        um_total = length_um(self.line, um)
        px_per_um = (L / um_total) if um_total else None
        segs = [(a, b)]
        for d, level in ticks(self.line, um, px_per_um):
            c = QPointF(a.x() + ux * d * px_per_um, a.y() + uy * d * px_per_um)
            h = TICK[level]
            segs.append((QPointF(c.x() - nx * h, c.y() - ny * h), QPointF(c.x() + nx * h, c.y() + ny * h)))
        end = TICK[2]
        segs.append((QPointF(b.x() - nx * end, b.y() - ny * end), QPointF(b.x() + nx * end, b.y() + ny * end)))
        for pen in (QPen(SHADOW, 3.2), QPen(WHITE, 1.4)):
            p.setPen(pen)
            for s, e in segs:
                p.drawLine(s, e)
        # the length beside the end, on the side away from the line
        f = QFont(p.font())
        f.setBold(True)
        p.setFont(f)
        text = label(self.line, um)
        fm = p.fontMetrics()
        tw, th = fm.horizontalAdvance(text), fm.ascent()
        side = -1 if ny > 0 else 1  # put it above the line where possible
        cx = b.x() + ux * 14 + nx * side * 18
        cy = b.y() + uy * 14 + ny * side * 18
        pos = QPointF(cx - tw / 2 + ux * tw / 2, cy + th / 2)
        p.setPen(SHADOW)
        p.drawText(pos + QPointF(1, 1), text)
        p.setPen(WHITE)
        p.drawText(pos, text)
        p.restore()
