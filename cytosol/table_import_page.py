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


from .ui.import_parts import GroupCard  # noqa: E402,F401  (component library)

