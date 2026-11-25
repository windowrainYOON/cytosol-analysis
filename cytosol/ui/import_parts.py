"""SettingsCard variant ``editor``: one group of an imported table (graph window 파일 불러오기)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QRadioButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
from .. import graph as G
from .. import table_import as T
from .. import theme

if TYPE_CHECKING:
    from ..table_import_page import ImportPage


class GroupCard(QWidget):
    """그룹 정하기 beside the 표 가져오기 page: groups from the sample names
    (자동 / 구분자), the group column, the column names of a wide table, or
    none; group names are renamed in the list (the same name joins two)."""

    changed = Signal()
    MODES = ('auto', 'split', 'col', 'wide', 'none')

    def __init__(self, page: ImportPage, parent=None):
        super().__init__(parent)
        self.page = page
        self.renames = {}
        self._busy = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        card = QGroupBox('그룹 정하기')
        v = QVBoxLayout(card)
        self.auto = QRadioButton('이름에서 자동으로')
        self.split = QRadioButton('이름을 구분자로 잘라서')
        self.col = QRadioButton('그룹 열 그대로')
        self.wide = QRadioButton('열 이름이 그룹 (Prism처럼 넓은 표)')
        self.none = QRadioButton('그룹 없음')
        self.auto.setChecked(True)
        for b in self.buttons():
            v.addWidget(b)
            b.toggled.connect(lambda on: on and self._mode_changed())
        h = QLabel('자동: 채널 표시(- C=1), 확장자(.oir), 끝 번호(_0001)를 빼고 같은 이름끼리 묶은 뒤, '
                   '모든 그룹에 똑같이 붙은 앞부분(Split mNG,)은 지웁니다.')
        h.setWordWrap(True)
        theme.hint(h)
        v.addWidget(h)
        f = QFormLayout()
        srow = QHBoxLayout()
        self.sep = QLineEdit(',')
        self.sep.setMaximumWidth(60)
        srow.addWidget(self.sep)
        self.parts = QSpinBox()
        self.parts.setRange(1, 9)
        self.parts.setValue(2)
        self.parts.setSuffix(' 조각')
        srow.addWidget(self.parts)
        f.addRow('구분자 · 앞에서', srow)
        self.short = QCheckBox('공통 앞부분 빼기')
        self.short.setChecked(True)
        f.addRow('', self.short)
        v.addLayout(f)
        lay.addWidget(card)
        top = QHBoxLayout()
        lab = QLabel('찾은 그룹')
        theme.text_style(lab, 'headline')
        top.addWidget(lab)
        top.addStretch()
        self.n = QLabel()
        theme.secondary(self.n)
        top.addWidget(self.n)
        lay.addLayout(top)
        self.list = QTableWidget(0, 3)
        self.list.setHorizontalHeaderLabels(['그룹 이름', '수', '예'])
        self.list.verticalHeader().hide()
        self.list.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.list.setColumnWidth(0, 150)
        self.list.setColumnWidth(1, 64)
        self.list.setMinimumHeight(220)
        self.list.itemChanged.connect(self._renamed)
        lay.addWidget(self.list, 1)
        h2 = QLabel('그룹 이름은 두 번 눌러서 바꿉니다. 같은 이름을 주면 두 그룹이 하나로 합쳐집니다.')
        h2.setWordWrap(True)
        theme.hint(h2)
        lay.addWidget(h2)
        self.sep.textChanged.connect(lambda _t: self.refresh())
        self.parts.valueChanged.connect(lambda _v: self.refresh())
        self.short.toggled.connect(lambda _v: self.refresh())
        page.changed.connect(self.refresh)
        if 'group' in page.roles.values():
            self.col.setChecked(True)
        elif page.name_column() is None:
            self.none.setChecked(True)
        self._mode_changed()

    def buttons(self):
        return (self.auto, self.split, self.col, self.wide, self.none)

    def mode(self) -> str:
        return next(m for m, b in zip(self.MODES, self.buttons()) if b.isChecked())

    def set_mode(self, mode):
        dict(zip(self.MODES, self.buttons()))[mode].setChecked(True)

    def _mode_changed(self):
        m = self.mode()
        self.sep.setEnabled(m == 'split')
        self.parts.setEnabled(m == 'split')
        self.short.setEnabled(m in ('auto', 'split'))
        self.renames = {}
        self.refresh()

    def groups(self):
        """sample name -> group for 자동 / 구분자, else None."""
        p = self.page
        name = p.name_column()
        m = self.mode()
        if name is None or m not in ('auto', 'split'):
            return None
        names = list(dict.fromkeys(str(v) for v in p.base.values(name) if str(v).strip()))
        if m == 'auto':
            return T.name_groups(names, 'auto', short=self.short.isChecked())
        return T.name_groups(names, 'split', self.sep.text() or ',', self.parts.value(), short=self.short.isChecked())

    def result(self):
        """The imported table with its groups (and renames)."""
        p = self.page
        m = self.mode()
        t = p.result(self.groups())
        if t is None:
            return None
        if m == 'wide':
            keep = [c for c in t.columns if c != 'group']
            t = T.to_long(G.Table(t.name, keep, [[r[t.index(c)] for c in keep] for r in t.rows]))
            t.labels = {}
        elif m == 'none' and 'group' in t.columns:
            k = t.index('group')
            t.rows = [r[:k] + [''] + r[k + 1:] for r in t.rows]
        gcol = '그룹' if m == 'wide' else 'group'
        if self.renames and gcol in t.columns:
            k = t.index(gcol)
            t.rows = [r[:k] + [self.renames.get(r[k], r[k])] + r[k + 1:] for r in t.rows]
        return t

    def _renamed(self, it):
        if self._busy or it.column() != 0:
            return
        old = it.data(Qt.ItemDataRole.UserRole)
        new = it.text().strip()
        if old is None or not new:
            return
        for k, v in list(self.renames.items()):
            if v == old:
                self.renames[k] = new
        self.renames[old] = new
        self.refresh()
        self.changed.emit()

    def refresh(self):
        t = self.result()
        by = {}
        if t is not None:
            gcol = '그룹' if self.mode() == 'wide' else 'group'
            name = t.columns[0] if t.columns and t.columns[0] not in ('group', '그룹') else None
            if gcol in t.columns:
                k = t.index(gcol)
                for r in t.rows:
                    g = r[k]
                    if g == '' or g is None:
                        continue
                    ex = r[t.index(name)] if name else ''
                    by.setdefault(str(g), []).append(ex)
        self._busy = True
        self.list.setRowCount(len(by))
        for i, (k, ns) in enumerate(sorted(by.items())):
            it = QTableWidgetItem(k)
            it.setData(Qt.ItemDataRole.UserRole, k)
            self.list.setItem(i, 0, it)
            c = QTableWidgetItem(str(len(ns)))
            c.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            c.setFlags(c.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.list.setItem(i, 1, c)
            e = QTableWidgetItem(str(next((x for x in ns if x != ''), '')))
            e.setFlags(e.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.list.setItem(i, 2, e)
        self._busy = False
        self.n.setText(f'{len(by)}개 그룹' if by else '그룹 없음')
        self.changed.emit()
