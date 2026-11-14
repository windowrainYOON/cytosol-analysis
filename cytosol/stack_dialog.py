"""이미지 묶기… window (owner request 2026-11-13, v0.62; mockup stack-1):
pick the direction (채널 / Z / 시간), order the files (drag a row or ▲ ▼),
the channel each file gives, its name and colour, check that sizes match,
name the stack and, optionally, stack the other files named the same way."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import stacking, theme
from .marker_panel import ColorButton

AXIS_TEXT = {'C': '채널 — 같은 시야를 다른 염색 · 채널로 찍은 파일',
             'Z': 'Z — 초점면마다 하나씩인 파일',
             'T': '시간 (T) — 시점마다 하나씩인 파일'}


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


class StackDialog(theme.RoundedDialog):
    def __init__(self, parent, paths, images=None, others=()):
        super().__init__(parent, '이미지 묶기',
                         '고른 이미지를 한 이미지로 쌓습니다. 원본 파일은 그대로 두고, 목록에는 묶음 '
                         '하나로 보입니다. 모든 탭 · 내보내기 · 일괄 분석에서 보통 이미지처럼 씁니다.')
        from .io import read_image

        paths = [Path(p) for p in paths]
        if images is None:
            images = [read_image(p) for p in paths]
        order = sorted(range(len(paths)), key=lambda i: stacking.sort_key(paths[i]))
        self.images = [images[i] for i in order]
        self.paths = [paths[i] for i in order]
        self.others = [Path(p) for p in others]
        self.rows = []
        for p, im in zip(self.paths, self.images):
            col = stacking.color_of_name(p.name)
            self.rows.append({'path': p, 'image': im, 'channel': stacking.default_channel(im, p),
                              'name': col.capitalize() if col else '',
                              'color': list(stacking.COLOR_RGB[col]) if col else None})
        self.setMinimumWidth(560)

        g = QGroupBox('쌓는 방향')
        lay = QVBoxLayout(g)
        self.axis = QButtonGroup(self)
        for k, t in AXIS_TEXT.items():
            rb = QRadioButton(t)
            rb.setProperty('axis', k)
            self.axis.addButton(rb)
            lay.addWidget(rb)
            if k == 'C':
                rb.setChecked(True)
        self.axis.buttonToggled.connect(lambda *_: self._axis_changed())
        self.body.addWidget(g)

        g = QGroupBox('순서 · 채널')
        lay = QVBoxLayout(g)
        self.table = _RowTable(self)
        self.table.setMinimumHeight(150)
        lay.addWidget(self.table)
        hint = QLabel('행을 끌거나 ▲ ▼로 순서를 바꿉니다. RGB 파일은 이름의 색(Red / Green / Blue)에 '
                      '맞는 채널을 자동으로 고릅니다.')
        hint.setWordWrap(True)
        theme.hint(hint)
        lay.addWidget(hint)
        btns = QHBoxLayout()
        self.up = QPushButton('▲ 위로')
        self.down = QPushButton('▼ 아래로')
        self.up.clicked.connect(lambda: self._step(-1))
        self.down.clicked.connect(lambda: self._step(1))
        btns.addStretch(1)
        btns.addWidget(self.up)
        btns.addWidget(self.down)
        lay.addLayout(btns)
        self.body.addWidget(g)

        g = QGroupBox('확인')
        form = QFormLayout(g)
        self.status = theme.StatusLabel('')
        form.addRow(self.status)
        self.mismatch = QComboBox()
        for k, t in stacking.MISMATCH.items():
            self.mismatch.addItem(t, k)
        form.addRow('크기가 다르면', self.mismatch)
        self.interval = QDoubleSpinBox()
        self.interval.setRange(0.0, 1e6)
        self.interval.setDecimals(3)
        self.interval.setSuffix(' s')
        self.interval.setValue(1.0)
        form.addRow('시점 간격', self.interval)
        self.zstep = QDoubleSpinBox()
        self.zstep.setRange(0.0, 1000.0)
        self.zstep.setDecimals(3)
        self.zstep.setSuffix(' µm')
        form.addRow('Z 간격', self.zstep)
        self.form = form
        self.name = QLineEdit(stacking.sample_name(self.paths))
        form.addRow('이름', self.name)
        self.fold = QCheckBox('원본 파일은 묶음 아래에 접어 두기')
        self.fold.setChecked(True)
        form.addRow(self.fold)
        self.more_sets = stacking.same_pattern_sets(self.paths, self.others)
        self.same = QCheckBox(self._same_text())
        self.same.setChecked(bool(self.more_sets))
        self.same.setEnabled(bool(self.more_sets))
        form.addRow(self.same)
        self.body.addWidget(g)

        cancel = QPushButton('취소')
        self.ok = QPushButton('묶기')
        cancel.clicked.connect(self.reject)
        self.ok.clicked.connect(self.accept)
        self.button_row(cancel, self.ok, default=self.ok)
        self._fill()
        self._axis_changed()

    def _same_text(self) -> str:
        if not self.more_sets:
            return '같은 이름 규칙의 나머지 파일도 묶기 (없음)'
        first = self.more_sets[0][0]
        more = f' · {len(self.more_sets) - 1}세트 더' if len(self.more_sets) > 1 else ''
        return f'같은 이름 규칙의 나머지 파일도 묶기 ({first}{more})'

    # ---- rows ---------------------------------------------------------------

    def _fill(self):
        t = self.table
        t.setRowCount(len(self.rows))
        for i, r in enumerate(self.rows):
            num = QTableWidgetItem(f'{i + 1}  ≡')
            num.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                         | Qt.ItemFlag.ItemIsDragEnabled)
            t.setItem(i, 0, num)
            f = QTableWidgetItem(r['path'].name)
            f.setToolTip(str(r['path']))
            f.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                       | Qt.ItemFlag.ItemIsDragEnabled)
            t.setItem(i, 1, f)
            combo = QComboBox()
            im = r['image']
            combo.addItem(f'전체 ({len(im.channels)}채널)', -1)
            for k, nm in enumerate(im.channels):
                combo.addItem(f'{k + 1}: {nm}', k)
            combo.setCurrentIndex(max(combo.findData(r['channel']), 0))
            combo.currentIndexChanged.connect(lambda _=0, i=i, c=combo: self._set(i, 'channel', c.currentData()))
            t.setCellWidget(i, 2, combo)
            name = QLineEdit(r['name'])
            name.setPlaceholderText(im.channels[0] if len(im.channels) == 1 else '파일의 이름')
            name.textChanged.connect(lambda v, i=i: self._set(i, 'name', v))
            t.setCellWidget(i, 3, name)
            col = r['color'] or ((im.colors[0] if im.colors and im.colors[0] else None)
                                 if len(im.channels) == 1 or r['channel'] >= 0 else None)
            btn = ColorButton(col or (1.0, 1.0, 1.0))
            btn.setFixedWidth(36)
            btn.changed.connect(lambda i=i, b=btn: self._set(i, 'color', list(b.rgb)))
            t.setCellWidget(i, 4, btn)
        self._check()

    def _set(self, i, key, v):
        self.rows[i][key] = v

    def move_row(self, src, dst):
        r = self.rows.pop(src)
        self.rows.insert(dst, r)
        self._fill()
        self.table.selectRow(dst)

    def _step(self, d):
        i = self.table.currentRow()
        if 0 <= i and 0 <= i + d < len(self.rows):
            self.move_row(i, i + d)

    def _axis(self) -> str:
        b = self.axis.checkedButton()
        return b.property('axis') if b is not None else 'C'

    def _axis_changed(self):
        a = self._axis()
        theme.show_rows(self.form, [self.interval], a == 'T')
        theme.show_rows(self.form, [self.zstep], a == 'Z')
        self.table.setColumnHidden(3, a != 'C')
        self.table.setColumnHidden(4, a != 'C')

    def _check(self):
        same, line = stacking.check([r['image'] for r in self.rows], None)
        self.status.setText(line)
        self.status.set_kind('success' if same else 'warning')

    # ---- result ---------------------------------------------------------------

    def spec(self) -> stacking.StackSpec:
        a = self._axis()
        srcs = [stacking.StackSource(str(r['path']), int(r['channel']), r['name'] if a == 'C' else '',
                                     r['color'] if a == 'C' else None) for r in self.rows]
        return stacking.StackSpec(axis=a, sources=srcs, name=self.name.text().strip(),
                                  interval_s=self.interval.value() if a == 'T' else 0.0,
                                  z_step_um=self.zstep.value() if a == 'Z' else 0.0,
                                  mismatch=self.mismatch.currentData(), fold=self.fold.isChecked())

    def extra_specs(self) -> list[stacking.StackSpec]:
        """The same settings for the other sets named the same way."""
        if not (self.same.isChecked() and self.more_sets):
            return []
        base = self.spec()
        out = []
        for name, paths in self.more_sets:
            srcs = []
            for p, src in zip(self._match_order(paths), base.sources):
                srcs.append(stacking.StackSource(str(p), src.channel, src.name, src.color))
            out.append(stacking.StackSpec(axis=base.axis, sources=srcs, name=name,
                                          interval_s=base.interval_s, z_step_um=base.z_step_um,
                                          mismatch=base.mismatch, fold=base.fold))
        return out

    def _match_order(self, paths):
        """`paths` are in the order the dialog opened with (sorted); put them
        in the rows' current order."""
        by_rest = {}
        names = [p.name for p in self.paths]
        pre = names[0]
        for n in names[1:]:
            while not n.startswith(pre):
                pre = pre[:-1]
        for p, orig in zip(paths, self.paths):
            by_rest[orig.name[len(pre):]] = p
        return [by_rest.get(r['path'].name[len(pre):], paths[0]) for r in self.rows]

