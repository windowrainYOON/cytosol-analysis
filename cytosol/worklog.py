"""Work log: what was done, when and on which image. Every lasting status
bar message is recorded (detections, edits, loads, saves, ...), kept in the
project file and shown in Tool > 작업 기록."""

from __future__ import annotations

import csv
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

COLUMNS = ('time', 'image', 'image_id', 'action')
TITLES = ('시간', '이미지', '이미지 ID', '내용')


class WorkLog:
    def __init__(self, entries=None):
        self.entries: list[dict] = list(entries or [])
        self.listeners = []

    def add(self, action: str, item=None):
        action = str(action).strip()
        if not action:
            return
        e = {'time': datetime.now().isoformat(timespec='seconds'),
             'image': getattr(item, 'label', '') if item is not None else '',
             'image_id': getattr(item, 'image_id', '') if item is not None else '',
             'action': action}
        if self.entries and {k: v for k, v in self.entries[-1].items() if k != 'time'} \
                == {k: v for k, v in e.items() if k != 'time'}:
            self.entries[-1]['time'] = e['time']  # the same message again
        else:
            self.entries.append(e)
        for fn in self.listeners:
            fn()

    def clear(self):
        self.entries = []
        for fn in self.listeners:
            fn()

    def write_csv(self, path) -> int:
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fieldnames=list(COLUMNS))
            w.writeheader()
            w.writerows({k: e.get(k, '') for k in COLUMNS} for e in self.entries)
        return len(self.entries)


class LoggingStatusBar(QStatusBar):
    """A status bar whose lasting messages (no timeout) also go to the
    window's work log and mark the project as changed."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win

    def showMessage(self, text, timeout=0):
        super().showMessage(text, timeout)
        if not timeout and text:
            self.win.log(text)


class LogWindow(QWidget):
    def __init__(self, log: WorkLog, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.log = log
        self.setWindowTitle('작업 기록 - Cytosol Viewer')
        self.resize(820, 480)
        lay = QVBoxLayout(self)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(list(TITLES))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table, 1)
        note = QLabel('상태 표시줄에 나온 작업(검출, 수정, 측정, 불러오기, 저장 …)이 시간 순서로 쌓이고 '
                      '프로젝트 파일에 함께 저장됩니다. CSV로 저장: 파일 → 내보내기 → 작업 기록.')
        note.setWordWrap(True)
        note.setStyleSheet('color: gray; font-size: 11px;')
        lay.addWidget(note)
        log.listeners.append(self.refresh)

    def refresh(self):
        if not self.isVisible():
            return  # filled when shown
        rows = self.log.entries
        self.table.setRowCount(len(rows))
        for i, e in enumerate(rows):
            for j, k in enumerate(COLUMNS):
                self.table.setItem(i, j, QTableWidgetItem(str(e.get(k, '')).replace('T', ' ', 1)
                                                          if k == 'time' else str(e.get(k, ''))))
        self.table.resizeColumnsToContents()
        self.table.scrollToBottom()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
