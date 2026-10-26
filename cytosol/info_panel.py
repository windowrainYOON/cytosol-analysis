"""이미지 정보 tab: the acquisition metadata of the current image as tables
(general settings, and per channel: fluorophore, laser, intensity, exposure /
pixel dwell, detector gain, pinhole, ...), with CSV and raw-metadata export."""

from __future__ import annotations

import csv
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .imageinfo import InfoSummary, summarize

NOTE = ('레이저 세기는 소프트웨어에 저장된 설정값(%)입니다. 정격 최대 출력과 곱한 명목 출력은 '
        '광섬유 입력 기준이며, 시료 면에서의 실제 파워는 파일에 기록되지 않습니다.')


def _table(columns) -> QTableWidget:
    t = QTableWidget(0, len(columns))
    t.setHorizontalHeaderLabels(columns)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    t.setWordWrap(True)
    t.setAlternatingRowColors(True)
    return t


class InfoPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.item = None
        self.summary: InfoSummary | None = None
        lay = QVBoxLayout(self)
        self.title = QLabel('이미지를 고르세요.')
        self.title.setWordWrap(True)
        f = self.title.font()
        f.setBold(True)
        self.title.setFont(f)
        lay.addWidget(self.title)

        lay.addWidget(QLabel('채널별 획득 설정'))
        self.chan = _table(['항목'])
        lay.addWidget(self.chan, 1)
        lay.addWidget(QLabel('이미지 · 장비 · Bleaching'))
        self.gen = _table(['구분', '항목', '값'])
        self.gen.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.gen, 2)
        note = QLabel(NOTE)
        note.setWordWrap(True)
        note.setStyleSheet('color: gray;')
        lay.addWidget(note)

        row = QHBoxLayout()
        self.copy_btn = QPushButton('표 복사')
        self.copy_btn.setToolTip('두 표를 탭으로 구분된 글로 복사합니다 (엑셀에 붙여넣기).')
        self.copy_btn.clicked.connect(self.copy)
        row.addWidget(self.copy_btn)
        hint = QLabel('저장: 파일 → 내보내기 → 이미지 정보')
        hint.setStyleSheet('color: gray; font-size: 11px;')
        row.addWidget(hint, 1)
        lay.addLayout(row)
        self._enable(False)

    def _enable(self, on):
        self.copy_btn.setEnabled(on)

    def bind(self, item, refresh=False):
        self.item = item
        if item is None:
            self.summary = None
            self.title.setText('이미지를 고르세요.')
            self.gen.setRowCount(0)
            self.chan.setRowCount(0)
            self._enable(False)
            return
        s = getattr(item, '_info_summary', None)
        if refresh or s is None:
            s = item._info_summary = summarize(item)
        self.summary = s
        self.title.setText(item.label)
        self._fill_general(s)
        self._fill_channels(s)
        self._enable(True)

    def _fill_general(self, s: InfoSummary):
        t = self.gen
        t.setRowCount(0)
        bold = QFont()
        bold.setBold(True)
        last = None
        for sec, key, val in s.general:
            r = t.rowCount()
            t.insertRow(r)
            cell = QTableWidgetItem(sec if sec != last else '')
            if sec != last:
                cell.setFont(bold)
            t.setItem(r, 0, cell)
            t.setItem(r, 1, QTableWidgetItem(key))
            v = QTableWidgetItem(val)
            v.setToolTip(val)
            t.setItem(r, 2, v)
            last = sec
        t.resizeColumnToContents(0)
        t.resizeColumnToContents(1)
        t.resizeRowsToContents()

    def _fill_channels(self, s: InfoSummary):
        t = self.chan
        t.clear()
        t.setColumnCount(1 + len(s.channels))
        t.setHorizontalHeaderLabels(['항목'] + list(s.channels))
        rows = [r for r in s.channel_rows if r[0] != '채널']
        t.setRowCount(len(rows))
        bold = QFont()
        bold.setBold(True)
        for r, (name, vals) in enumerate(rows):
            head = QTableWidgetItem(name)
            head.setFont(bold)
            t.setItem(r, 0, head)
            for c, v in enumerate(vals, 1):
                cell = QTableWidgetItem(v)
                cell.setToolTip(v)
                cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                t.setItem(r, c, cell)
        t.resizeColumnsToContents()
        t.resizeRowsToContents()

    # ---- export ---------------------------------------------------------

    def copy(self):
        if self.summary is None:
            return
        text = '\n'.join('\t'.join(row) for row in self.summary.rows_csv())
        QGuiApplication.clipboard().setText(text)

    def _stem(self):
        from .lut import item_stem

        return item_stem(self.item)

    def save_csv(self):
        if self.summary is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, '이미지 정보 저장', f'{self._stem()}_info.csv',
                                              'CSV (*.csv)')
        if not path:
            return
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            csv.writer(f).writerows(self.summary.rows_csv())

    def save_raw(self):
        if self.item is None:
            return
        meta = self.item.image.metadata or {}
        xml = meta.get('xml')
        if isinstance(xml, str):
            ext, text = 'xml', xml
        elif isinstance(xml, dict):  # OIR: several XML documents
            ext, text = 'xml', '\n\n'.join(f'<!-- block {k} -->\n{v}' for k, v in xml.items())
        else:
            import json

            ext = 'json'
            text = json.dumps({k: v for k, v in meta.items() if k != 'bleach_rois'},
                              ensure_ascii=False, indent=1, default=str)
        path, _ = QFileDialog.getSaveFileName(self, '원본 메타데이터 저장',
                                              f'{self._stem()}_metadata.{ext}', f'*.{ext}')
        if not path:
            return
        try:
            Path(path).write_text(text, encoding='utf-8')
        except Exception as exc:
            QMessageBox.warning(self, '저장 실패', str(exc))
