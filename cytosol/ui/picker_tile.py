"""PickerTile variant ``sample``: a numbered sample on the 입자 기준 잡기 page."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel


class Tile(QLabel):
    clicked = Signal(int)

    def __init__(self, n):
        super().__init__()
        self.n = n
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f'{n + 1}번 · 클릭 = 이 후보부터 입자')

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.n)
        super().mousePressEvent(ev)
