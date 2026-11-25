"""Chip variant ``overlay``: a small label chip floating on a canvas view (3D projection axes, section names)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget


class Chip(QWidget):
    """Small capsule label drawn over the view (progress, angles)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.text = ''
        self.frac = None
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set(self, text, frac=None):
        self.text, self.frac = text, frac
        fm = self.fontMetrics()
        w = fm.horizontalAdvance(text) + 24
        self.setFixedSize(w, fm.height() + 10 + (4 if frac is not None else 0))
        self.setVisible(bool(text))
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pal = self.palette()
        base = QColor(pal.window().color())
        base.setAlpha(225)
        r = self.rect().adjusted(0, 0, -1, -1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(base)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.setPen(pal.windowText().color())
        fm = self.fontMetrics()
        p.drawText(QPointF(12, 5 + fm.ascent()), self.text)
        if self.frac is not None:
            y = r.bottom() - 4
            p.setPen(Qt.PenStyle.NoPen)
            track = QColor(pal.windowText().color())
            track.setAlpha(40)
            p.setBrush(track)
            p.drawRoundedRect(12, y, r.width() - 24, 3, 1.5, 1.5)
            p.setBrush(pal.highlight())
            p.drawRoundedRect(12, y, int((r.width() - 24) * max(0.0, min(1.0, self.frac))), 3, 1.5, 1.5)
        p.end()
