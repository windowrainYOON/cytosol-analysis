"""표 가져오기 step of the 새 그래프 window (owner request 2026-11-20, mockup v2,
built in v0.73): roles (이름 / 그룹 / 범주 / 값 / 빼기) chosen on the preview sheet, columns or
rows, groups from the sample names."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import graph as G
from . import table_import as T
from . import theme

PREVIEW_ROWS = 40
ROLE_COLOR = {'name': 'blue', 'group': 'orange', 'cat': 'gray'}


def col_letter(j: int) -> str:
    s = ''
    j += 1
    while j:
        j, r = divmod(j - 1, 26)
        s = chr(65 + r) + s
    return s


class ImportPage(QWidget):
    changed = Signal()

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.path = Path(path)
        self.opts = T.ImportOptions()
        self.grid = []
        self.roles = {}
        self.by_rows = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        card = QGroupBox('읽는 방법')
        f = QFormLayout(card)
        row = QHBoxLayout()
        self.name = QLabel()
        row.addWidget(self.name, 1)
        self.other = QPushButton('다른 파일…')
        row.addWidget(self.other)
        f.addRow('파일', row)
        self.sheet = QComboBox()
        f.addRow('시트', self.sheet)
        self._form = f
        self.orient = QComboBox()
        self.orient.addItem('열마다 항목 하나 (세로로 긴 표)', False)
        self.orient.addItem('행마다 항목 하나 (가로로 긴 표)', True)
        f.addRow('항목 방향', self.orient)
        hrow = QHBoxLayout()
        self.head = QSpinBox()
        self.head.setRange(0, 99999)
        self.head.setSpecialValueText('없음')
        hrow.addWidget(self.head)
        self.head_auto = QCheckBox('자동')
        theme.switch(self.head_auto)
        self.head_auto.setChecked(True)
        hrow.addWidget(self.head_auto)
        f.addRow('항목 이름 줄', hrow)
        self.decimal = QComboBox()
        self.decimal.addItem('점 (1.5)', False)
        self.decimal.addItem('쉼표 (1,5)', True)
        f.addRow('소수점', self.decimal)
        lay.addWidget(card)
        top = QHBoxLayout()
        lab = QLabel('미리보기 · 역할 정하기')
        theme.text_style(lab, 'headline')
        top.addWidget(lab)
        top.addStretch()
        self.count = QLabel()
        theme.secondary(self.count)
        top.addWidget(self.count)
        lay.addLayout(top)
        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.horizontalHeader().setDefaultSectionSize(104)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.setMinimumHeight(470)
        lay.addWidget(self.table, 1)
        h = QLabel('맨 위 줄에서 열마다 역할을 고릅니다: 이름 = 점 하나의 이름(이미지, 시료), 그룹 = 비교할 묶음, '
                   '범주 = 나눠 볼 글자 열, 값 = 그래프에 그릴 숫자, 빼기 = 쓰지 않음. 파란 줄이 항목 이름입니다.')
        h.setWordWrap(True)
        theme.hint(h)
        lay.addWidget(h)
        self.sheet.currentIndexChanged.connect(lambda _i: self._load())
        self.orient.currentIndexChanged.connect(lambda _i: self._load())
        self.head.valueChanged.connect(lambda _v: self._opts_changed())
        self.head_auto.toggled.connect(lambda _v: self._opts_changed())
        self.decimal.currentIndexChanged.connect(lambda _i: self._opts_changed())
        self.other.clicked.connect(self._pick)
        self.setAcceptDrops(True)
        self.set_path(path)

    def _pick(self):
        path, _ = QFileDialog.getOpenFileName(self, '파일 불러오기', str(self.path.parent), T.FILTER)
        if path:
            self.set_path(path)

    def dragEnterEvent(self, e):  # a table file dropped on the page replaces the file
        if any(T.is_table_file(u.toLocalFile()) for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            if T.is_table_file(u.toLocalFile()):
                self.set_path(u.toLocalFile())
                e.acceptProposedAction()
                return

    def set_path(self, path):
        self.path = Path(path)
        self.name.setText(self.path.name)
        self.sheet.blockSignals(True)
        self.sheet.clear()
        names = T.sheets(self.path)
        for n in names:
            self.sheet.addItem(n)
        self.sheet.blockSignals(False)
        self.sheet.setEnabled(len(names) > 1)
        self._form.setRowVisible(self.sheet, bool(names))
        self.decimal.setEnabled(not names)
        self._load()

    def _load(self):
        self.opts.sheet = self.sheet.currentText()
        self.by_rows = bool(self.orient.currentData())
        self.raw = T.read_grid(self.path, self.opts.sheet)
        self.grid = T.transpose(self.raw) if self.by_rows else self.raw
        self.roles = {}
        self._opts_changed(guess=True)

    def _opts_changed(self, guess=False):
        o = self.opts
        o.decimal_comma = bool(self.decimal.currentData())
        if self.head_auto.isChecked():
            o.header = -1
            h = T.guess_header(self.grid, o.decimal_comma)
            self.head.blockSignals(True)
            self.head.setValue(0 if h is None else h + 1)
            self.head.blockSignals(False)
            self.head.setEnabled(False)
        else:
            self.head.setEnabled(True)
            o.header = None if self.head.value() == 0 else self.head.value() - 1
        base = T.build_table(self.grid, T.ImportOptions(header=o.header, decimal_comma=o.decimal_comma,
                                                         skip_empty=False))
        if guess or len(self.roles) != len(base.columns):
            r = T.guess_roles(base)
            self.roles = {j: r[c] for j, c in enumerate(base.columns)}
            for j, c in enumerate(base.columns):
                if not any(str(v).strip() for v in base.values(c)):
                    self.roles[j] = 'off'
        self.base = base
        self._fill()
        self.changed.emit()

    def set_role(self, j, role):
        self.roles[j] = role
        if role == 'name':
            for k, v in self.roles.items():
                if k != j and v == 'name':
                    self.roles[k] = 'cat'
        self._fill()
        self.changed.emit()

    def _fill(self):
        t = self.table
        g = self.raw
        n = max((len(r) for r in g), default=0)
        rows = g[:PREVIEW_ROWS]
        t.clear()
        off = 1
        if not self.by_rows:
            t.setRowCount(len(rows) + off)
            t.setColumnCount(n)
            t.setHorizontalHeaderLabels([col_letter(j) for j in range(n)])
            t.setVerticalHeaderLabels(['역할'] + [str(i + 1) for i in range(len(rows))])
        else:
            n = min(n, 12)
            t.setRowCount(len(rows))
            t.setColumnCount(n + off)
            t.setHorizontalHeaderLabels(['역할'] + [col_letter(j) for j in range(n)])
            t.setVerticalHeaderLabels([str(i + 1) for i in range(len(rows))])
        h = T.header_row(self.grid, self.opts)
        grey = theme.color('label-tertiary')
        for i, r in enumerate(rows):
            for j in range(n):
                v = r[j] if j < len(r) else ''
                it = QTableWidgetItem('' if v == '' else (f'{v:.6g}' if isinstance(v, float) else str(v)))
                item_k, head_k = (i, j) if self.by_rows else (j, i)
                role = self.roles.get(item_k, 'off')
                if isinstance(v, (int, float)) or T.to_number(v, self.opts.decimal_comma) is not None:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                c = ROLE_COLOR.get(role)
                if head_k == h:
                    q = theme.color('blue')
                    q.setAlpha(60)
                    it.setBackground(QBrush(q))
                    fnt = it.font()
                    fnt.setBold(True)
                    it.setFont(fnt)
                elif c:
                    q = QColor(theme.color(c))
                    q.setAlpha(26)
                    it.setBackground(QBrush(q))
                if role == 'off' or (h is not None and head_k < h):
                    it.setForeground(QBrush(grey))
                if self.by_rows:
                    t.setItem(i, j + off, it)
                else:
                    t.setItem(i + off, j, it)
        count = len(rows) if self.by_rows else n
        for k in range(count):
            cb = QComboBox()
            for key in T.ROLES:
                cb.addItem(T.ROLE_TEXT[key], key)
            cb.setCurrentIndex(T.ROLES.index(self.roles.get(k, 'off')))
            cb.currentIndexChanged.connect(lambda _i, k=k, cb=cb: self.set_role(k, cb.currentData()))
            if self.by_rows:
                t.setCellWidget(k, 0, cb)
            else:
                t.setCellWidget(0, k, cb)
        if self.by_rows:
            t.setColumnWidth(0, 96)
        else:
            t.setRowHeight(0, 34)
        tab = self.result()
        self.count.setText(T.summary(tab) if tab is not None else '')

    def name_column(self):
        return next((self.base.columns[j] for j, r in self.roles.items() if r == 'name'), None)

    def roles_by_name(self):
        return {self.base.columns[j]: r for j, r in self.roles.items() if j < len(self.base.columns)}

    def result(self, groups=None):
        if not self.grid:
            return None
        t = T.build_table(self.grid, self.opts, self.path.stem if not self.opts.sheet
                          else f'{self.path.stem} · {self.opts.sheet}')
        roles = {c: r for c, r in self.roles_by_name().items() if c in t.columns}
        return T.apply_roles(t, roles, groups)


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

