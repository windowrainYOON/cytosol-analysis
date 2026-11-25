"""Table variants: ``reorder`` (rows moved by drag), ``check`` (check column with select-all)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget


class _RowTable(QTableWidget):
    """Rows moved by dragging (the whole row; the widgets are rebuilt)."""

    def __init__(self, dialog):
        super().__init__(0, 5)
        self.dialog = dialog
        self.setHorizontalHeaderLabels(['', '파일', '쓸 채널', '채널 이름', '색'])
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDropIndicatorShown(True)
        h = self.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)

    def dropEvent(self, ev):
        src = self.currentRow()
        dst = self.rowAt(round(ev.position().y()))
        if dst < 0:
            dst = self.rowCount() - 1
        ev.setDropAction(Qt.DropAction.IgnoreAction)
        ev.accept()
        if src >= 0 and dst != src:
            self.dialog.move_row(src, dst)
