"""Legend — the series names beside a live plot (live box under the canvas)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget


PLOT_H = 150


class PlotLegend(QWidget):
    """The line profile's legend beside its plot (owner request 2026-11-24,
    v0.74): the white plot background goes on to the left over the place of the
    number tiles, the legend in it, the plot itself keeps its size."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries = []  # [(name, rgb 0–1)]
        self.setFixedHeight(PLOT_H)

    def set_entries(self, entries):
        self.entries = list(entries)
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(255, 255, 255))  # the plot's white
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        f = QFont(self.font())
        f.setPixelSize(11)  # matplotlib's 8 pt legend at the plot's 100 dpi
        p.setFont(f)
        fm = p.fontMetrics()
        y = 14.0
        for name, rgb in self.entries:
            col = QColor.fromRgbF(*rgb)
            p.setPen(QPen(col, 1.6))
            cy = y + fm.ascent() / 2 - 1
            p.drawLine(QPointF(12, cy), QPointF(32, cy))
            p.setPen(QColor(0, 0, 0))
            p.drawText(QPointF(38, y + fm.ascent()), fm.elidedText(name, Qt.TextElideMode.ElideRight,
                                                                    max(10, self.width() - 44)))
            y += fm.height() + 4
        p.end()
