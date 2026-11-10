"""Pieces of the graph editor's step flow (owner request 2026-11-09), used
both in the 새 그래프 window (GraphWizard: 종류 → 축 배치 → 그룹) and in the
inspector's 데이터 / 통계 tabs: the chart kind cards, the 축 배치 card (X / Y
as 범주 or 값, several Y columns, colour split, error bars), the 그룹 list
(check = drawn, drag = order) and the significance settings (StatsEditor,
StatsDialog). Each editor works on a spec returned by a callable and calls
`changed()` after an edit; the owner rebuilds the series and redraws."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import graph as G
from . import stats as ST
from . import theme

KINDS = [('xy', '선 · 점 (XY)', '시간 · 거리 같은 숫자 x'),
         ('bar', '막대', '그룹 평균 ± 에러바'),
         ('strip', '점 그림', '개별 값 + 평균'),
         ('box', '상자 그림', '중앙값과 사분위'),
         ('violin', '바이올린', '값의 분포 모양'),
         ('hist', '히스토그램', '한 값의 분포'),
         ('heatmap', '히트맵', 'x · y 위의 값')]
STATS_DEFAULTS = {k: getattr(G.Stats(), k) for k in G.STATS_LOOK}


def stats_defaults() -> dict:
    """Initial look of significance marks (Preferences › 그래프 · 유의성 표시 초기값)."""
    from .settings import view_settings

    d = dict(STATS_DEFAULTS)
    saved = view_settings.defaults('stats') or {}
    d.update({k: v for k, v in saved.items() if k in d})
    return d


def apply_stats_defaults(spec: G.GraphSpec):
    st = G._build(G.Stats, {**G.asdict(spec.stats), **stats_defaults()})
    spec.stats = st


def hint(text) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    theme.hint(lab)
    return lab


def combo(items, cur=None) -> QComboBox:
    """items: [(text, data)]"""
    c = QComboBox()
    for t, d in items:
        c.addItem(t, d)
    if cur is not None:
        i = c.findData(cur)
        c.setCurrentIndex(max(i, 0))
    return c


# ---------------------------------------------------------------------------
# chart kinds
# ---------------------------------------------------------------------------

_THUMBS = {}


def thumb(kind) -> QIcon:
    """A small picture of the chart kind (same sample data for all)."""
    if kind in _THUMBS:
        return _THUMBS[kind]
    import numpy as np
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    fig = Figure(figsize=(1.5, 1.0), dpi=160)
    fig.patch.set_alpha(0)
    FigureCanvasAgg(fig)
    ax = fig.add_axes([0.08, 0.1, 0.88, 0.85])
    ax.set_facecolor('none')
    r = np.random.default_rng(1)
    data = [r.normal(m, 1.0, 12) for m in (4, 6, 4.6)]
    cs = ['#000000', '#d62728', '#1f77b4']
    if kind == 'xy':
        t = np.linspace(0, 10, 12)
        for c, a in zip(cs, (0.5, 0.75, 0.9)):
            ax.plot(t, a * (1 - np.exp(-t / 2.5)), '-o', color=c, ms=2.2, lw=1)
    elif kind == 'bar':
        ax.bar(range(3), [d.mean() for d in data], 0.6, color=cs, alpha=0.4, edgecolor=cs)
        for k, d in enumerate(data):
            ax.errorbar(k, d.mean(), d.std(), fmt='none', ecolor=cs[k], capsize=2, lw=0.8)
    elif kind == 'strip':
        for k, d in enumerate(data):
            ax.plot(k + r.uniform(-.2, .2, d.size), d, 'o', ms=2.2, color=cs[k])
            ax.hlines(d.mean(), k - .25, k + .25, color=cs[k], lw=1.4)
    elif kind == 'box':
        bp = ax.boxplot(data, widths=0.55, patch_artist=True, showfliers=False)
        for b, c in zip(bp['boxes'], cs):
            b.set(facecolor=c, alpha=0.35, edgecolor=c)
        for k in ('whiskers', 'caps', 'medians'):
            for ln in bp[k]:
                ln.set(color='#333', lw=0.8)
    elif kind == 'violin':
        vp = ax.violinplot(data, showextrema=False, showmedians=True)
        for b, c in zip(vp['bodies'], cs):
            b.set(facecolor=c, alpha=0.4, edgecolor=c)
        vp['cmedians'].set(color='#333', lw=0.8)
    elif kind == 'hist':
        for d, c in zip(data, cs):
            ax.hist(d, bins=8, color=c, alpha=0.4, histtype='stepfilled', edgecolor=c)
    else:
        ax.imshow(r.random((6, 9)) + np.linspace(0, 1, 9), cmap='magma', aspect='auto')
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    for s in ('left', 'bottom'):
        ax.spines[s].set_color('#888')
    fig.canvas.draw()
    buf = fig.canvas.buffer_rgba()
    from PySide6.QtGui import QImage

    h, w = int(fig.bbox.height), int(fig.bbox.width)
    img = QImage(bytes(buf), w, h, QImage.Format.Format_RGBA8888)
    _THUMBS[kind] = QIcon(QPixmap.fromImage(img.copy()))
    return _THUMBS[kind]


class KindCard(QAbstractButton):
    """One chart kind: thumbnail + name (+ description); checked = accent ring."""

    def __init__(self, key, name, desc, big=True, parent=None):
        super().__init__(parent)
        self.key, self.big, self.desc = key, big, desc
        self.recommended = False
        self.setCheckable(True)
        self.setAutoExclusive(True)
        self.setText(name)
        self.setToolTip(f'{name}: {desc}')
        self.isz = QSize(120, 80) if big else QSize(60, 40)
        self.setFixedSize(QSize(150, 158) if big else QSize(78, 70))
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, _e):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(1, 1, -1, -1)
        on = self.isChecked()
        if on:
            c = QColor(theme.color('blue'))
            c.setAlphaF(0.10)
            qp.setPen(QPen(theme.color('blue'), 2))
            qp.setBrush(c)
        else:
            qp.setPen(Qt.PenStyle.NoPen)
            qp.setBrush(theme.color('fill-tertiary'))
        qp.drawRoundedRect(r, 12, 12)
        isz = self.isz
        y = 10 if self.big else 5
        thumb(self.key).paint(qp, (self.width() - isz.width()) // 2, y, isz.width(), isz.height())
        f = QFont(self.font())
        f.setWeight(QFont.Weight.DemiBold if on else QFont.Weight.Medium)
        if not self.big:
            f.setPixelSize(10)
        qp.setFont(f)
        qp.setPen(theme.color('label'))
        ty = y + isz.height() + (6 if self.big else 2)
        qp.drawText(0, ty, self.width(), 20 if self.big else 16, Qt.AlignmentFlag.AlignHCenter, self.text())
        if self.big:
            f2 = QFont(self.font())
            f2.setPixelSize(11)
            qp.setFont(f2)
            qp.setPen(theme.color('label-secondary'))
            qp.drawText(6, ty + 20, self.width() - 12, 30,
                        Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap, self.desc)
            if self.recommended:
                f3 = QFont(self.font())
                f3.setPixelSize(10)
                f3.setWeight(QFont.Weight.DemiBold)
                qp.setFont(f3)
                qp.setPen(Qt.PenStyle.NoPen)
                qp.setBrush(theme.color('green'))
                qp.drawRoundedRect(self.width() - 42, 8, 34, 17, 8.5, 8.5)
                qp.setPen(QColor('white'))
                qp.drawText(self.width() - 42, 8, 34, 17, Qt.AlignmentFlag.AlignCenter, '추천')
        qp.end()


class KindPicker(QWidget):
    picked = Signal(str)

    def __init__(self, cols=4, big=True, parent=None):
        super().__init__(parent)
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(10 if big else 6)
        self.cards = {}
        for i, (k, n, d) in enumerate(KINDS):
            c = KindCard(k, n, d, big)
            c.clicked.connect(lambda _=False, k=k: self.picked.emit(k))
            g.addWidget(c, i // cols, i % cols)
            self.cards[k] = c
        g.setColumnStretch(cols, 1)

    def set_kind(self, k):
        c = self.cards.get(k)
        if c is not None and not c.isChecked():
            c.setChecked(True)

    def set_recommended(self, keys):
        for k, c in self.cards.items():
            c.recommended = k in keys
            c.update()


# ---------------------------------------------------------------------------
# 축 배치
# ---------------------------------------------------------------------------

class RoleSwitch(QWidget):
    """범주 | 값 for one axis."""

    toggled = Signal(bool)  # True = 범주

    def __init__(self, parent=None):
        from .hig_widgets import Chip

        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        h.addStretch()
        self.cat, self.val = Chip('범주', False), Chip('값', False)
        for c in (self.cat, self.val):
            c.setAutoExclusive(True)
            h.addWidget(c)
        self.cat.clicked.connect(lambda: self.toggled.emit(True))
        self.val.clicked.connect(lambda: self.toggled.emit(False))
        self.setToolTip('범주: 같은 값끼리 한 자리에 모읍니다 · 값: 숫자 눈금 위에 놓습니다')

    def set(self, cat: bool, value_ok=True):
        self.val.setEnabled(value_ok)
        self.val.setToolTip('' if value_ok else '글자 열은 범주로만 쓸 수 있습니다.')
        (self.cat if cat or not value_ok else self.val).setChecked(True)


def _align_end(form: QFormLayout):
    """Settings rows: title leading, a pop-up at the end of the row."""
    end = Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    for r in range(form.rowCount()):
        it = form.itemAt(r, QFormLayout.ItemRole.FieldRole)
        w = it.widget() if it is not None else None
        if w is not None and (isinstance(w, QComboBox) or not (
                w.sizePolicy().expandingDirections() & Qt.Orientation.Horizontal)):
            it.setAlignment(end)
        lab = form.itemAt(r, QFormLayout.ItemRole.LabelRole)
        if lab is not None and isinstance(lab.widget(), QLabel):
            lab.widget().setMinimumHeight(theme.SETTINGS_ROW_H)


class MappingEditor(QGroupBox):
    """축 배치 card. get_spec / get_tables are callables; changed() is called
    after every edit (mapping.on is set)."""

    def __init__(self, get_spec, get_tables, changed, parent=None):
        super().__init__('', parent)
        self.get_spec, self.get_tables, self.changed = get_spec, get_tables, changed
        self.form = QFormLayout(self)
        self._busy = False
        self.refresh()

    # helpers
    def _table(self):
        sp = self.get_spec()
        return self.get_tables().get(sp.mapping.table) if sp is not None else None

    def _edit(self, fn):
        if self._busy:
            return
        sp = self.get_spec()
        if sp is None:
            return
        fn(sp.mapping)
        sp.mapping.on = True
        self.changed()
        QTimer.singleShot(0, self.refresh)

    def _col_combo(self, cols, cur, allow_none=False):
        c = QComboBox()
        if allow_none:
            c.addItem('(없음)', '')
        for x in cols:
            c.addItem(x, x)
        i = c.findData(cur)
        c.setCurrentIndex(max(i, 0))
        return c

    def refresh(self):
        self._busy = True
        try:
            while self.form.rowCount():
                self.form.removeRow(0)
            sp = self.get_spec()
            tabs = self.get_tables()
            if sp is None or not tabs:
                self.form.addRow(hint('데이터가 없습니다. 위의 분석 칩에서 데이터를 고르세요.'))
                return
            m = sp.mapping
            if m.table not in tabs:
                m.table = next(iter(tabs))
            t = tabs[m.table]
            nums = t.numeric_columns()
            chart = sp.chart
            cat_chart = chart in G.CATEGORY_CHARTS
            tc = combo([(f'{n} ({len(tabs[n].rows)}행)', n) for n in tabs], m.table)
            tc.currentIndexChanged.connect(lambda _i, c=tc: self._set_table(c.currentData()))
            self.form.addRow('데이터 표', tc)
            if not m.on:
                self.form.addRow(hint('지금 그래프는 분석 탭이 만든 구성입니다. 여기서 바꾸면 이 표로 다시 그립니다.'))
            # X
            if chart != 'hist':
                xr = RoleSwitch()
                x_text = bool(m.x) and m.x in t.columns and m.x not in nums
                xr.set(m.x_cat, value_ok=not x_text)
                xr.toggled.connect(lambda cat: self._role('x', cat))
                xcols = list(t.columns) if m.x_cat else nums
                xc = self._col_combo(xcols, m.x, allow_none=cat_chart)
                xc.currentIndexChanged.connect(lambda _i, c=xc: self._edit(lambda mm: setattr(mm, 'x', c.currentData())))
                self.form.addRow('X 축', xr)
                self.form.addRow('    열', xc)
                theme.group_rows(xr, xc)
            # Y
            yr = RoleSwitch()
            y_text = bool(m.ys) and m.ys[0] in t.columns and m.ys[0] not in nums
            if chart == 'hist':
                yr.set(False, True)
                yr.setEnabled(False)
            else:
                yr.set(m.y_cat, value_ok=not y_text)
            yr.toggled.connect(lambda cat: self._role('y', cat))
            self.form.addRow('Y 축' if chart != 'hist' else '값 (분포)', yr)
            ycols = list(t.columns) if m.y_cat else nums
            ys = list(m.ys) or ['']
            multi = not m.y_cat and chart != 'heatmap'
            rows = [yr]
            for k, y in enumerate(ys if multi else ys[:1]):
                w = QWidget()
                h = QHBoxLayout(w)
                h.setContentsMargins(0, 0, 0, 0)
                h.setSpacing(6)
                h.addStretch()
                c = self._col_combo(ycols, y)
                c.currentIndexChanged.connect(lambda _i, c=c, k=k: self._set_y(k, c.currentData()))
                h.addWidget(c)
                if multi and len(ys) > 1:
                    from .hig_widgets import IconButton

                    x = IconButton('xmark', '이 열 빼기')
                    x.clicked.connect(lambda _=False, k=k: self._del_y(k))
                    h.addWidget(x)
                self.form.addRow('    열' if k == 0 else '', w)
                rows.append(w)
            if multi:
                add = QPushButton('＋ Y 열 추가')
                add.setToolTip('Y 축에 열을 하나 더 놓습니다 (열마다 색이 다른 시리즈)')
                add.clicked.connect(self._add_y)
                aw = QWidget()
                ah = QHBoxLayout(aw)
                ah.setContentsMargins(0, 0, 0, 0)
                ah.addStretch()
                ah.addWidget(add)
                self.form.addRow('', aw)
                rows.append(aw)
            theme.group_rows(*rows)
            if chart == 'heatmap':
                zc = self._col_combo(nums, m.z, allow_none=True)
                zc.currentIndexChanged.connect(lambda _i, c=zc: self._edit(lambda mm: setattr(mm, 'z', c.currentData())))
                self.form.addRow('값 (색)', zc)
            # colour split
            items = [('나누지 않음', ''), (f'Y 열마다{" (" + " · ".join(m.ys[:3]) + ")" if len(m.ys) > 1 else ""}', '@y')]
            for c in t.columns:
                n = len(set(G._text(v) for v in t.values(c)))
                if (c not in nums or c in (m.x if m.x_cat else '',)) and 1 < n <= 60:
                    label = c + (' (X 축 범주와 같음)' if c == G.category_column(sp) else '')
                    items.append((label, c))
            cc = combo(items, m.color)
            cc.currentIndexChanged.connect(lambda _i, c=cc: self._edit(lambda mm: setattr(mm, 'color', c.currentData())))
            self.form.addRow('색으로 나누기', cc)
            if cat_chart or chart == 'xy':
                if chart == 'xy':
                    ag = combo([(v, k) for k, v in G.AGGREGATES.items()], m.agg)
                    ag.currentIndexChanged.connect(lambda _i, c=ag: self._edit(lambda mm: setattr(mm, 'agg', c.currentData())))
                    self.form.addRow('같은 x 묶기', ag)
                if cat_chart or m.agg != 'none':
                    ec = combo([(v, k) for k, v in G.ERR_KINDS.items()], m.err)
                    ec.currentIndexChanged.connect(lambda _i, c=ec: self._edit(lambda mm: setattr(mm, 'err', c.currentData())))
                    self.form.addRow('에러바', ec)
            _align_end(self.form)
        finally:
            self._busy = False

    def _set_table(self, name):
        def f(m):
            sp = self.get_spec()
            nm = G.guess_mapping(G.GraphSpec(chart=sp.chart), self.get_tables(), name)
            m.table, m.x, m.x_cat, m.ys, m.y_cat, m.color = name, nm.x, nm.x_cat, nm.ys, False, '@y'
            sp.cat_order, sp.cat_hidden = [], []
        self._edit(f)

    def _set_y(self, k, col):
        def f(m):
            ys = list(m.ys) or ['']
            while len(ys) <= k:
                ys.append('')
            ys[k] = col
            m.ys = ys
        self._edit(f)

    def _add_y(self):
        t = self._table()
        nums = t.numeric_columns() if t is not None else []

        def f(m):
            rest = [c for c in nums if c not in m.ys and c != m.x]
            if rest:
                m.ys = list(m.ys) + [rest[0]]
                if m.color == '':
                    m.color = '@y'
        self._edit(f)

    def _del_y(self, k):
        self._edit(lambda m: setattr(m, 'ys', [y for i, y in enumerate(m.ys) if i != k]))

    def _role(self, axis, cat):
        sp = self.get_spec()
        t = self._table()
        nums = t.numeric_columns() if t is not None else []
        texts = [c for c in (t.columns if t is not None else []) if c not in nums]

        def f(m):
            if sp.chart in G.CATEGORY_CHARTS:
                # one axis holds the categories: switching one switches both (axes swap)
                want_x_cat = cat if axis == 'x' else not cat
                if want_x_cat != m.x_cat:
                    xs = m.x
                    m.x = m.ys[0] if m.ys else ''
                    m.ys = [xs] if xs else []
                m.x_cat, m.y_cat = want_x_cat, not want_x_cat
                return
            if axis == 'x':
                m.x_cat = cat
                if not cat and m.x not in nums:
                    m.x = nums[0] if nums else ''
            else:
                m.y_cat = cat
                if cat:
                    m.ys = [m.ys[0] if m.ys and m.ys[0] in (t.columns if t else []) else (texts[0] if texts else '')]
                elif m.ys and m.ys[0] not in nums:
                    m.ys = [nums[0]] if nums else []
        self._edit(f)


# ---------------------------------------------------------------------------
# 그룹
# ---------------------------------------------------------------------------

class _GroupTree(QTreeWidget):
    reordered = Signal()

    def dropEvent(self, e):
        super().dropEvent(e)
        self.reordered.emit()


class GroupEditor(QGroupBox):
    """The values of the group column: check = drawn, drag = order."""

    def __init__(self, get_spec, get_tables, changed, parent=None):
        super().__init__('', parent)
        self.get_spec, self.get_tables, self.changed = get_spec, get_tables, changed
        v = QVBoxLayout(self)
        head = QHBoxLayout()
        self.head = QLabel()
        theme.secondary(self.head)
        head.addWidget(self.head, 1)
        self.all_b, self.none_b = QPushButton('모두'), QPushButton('없음')
        self.all_b.clicked.connect(lambda: self._set_all(True))
        self.none_b.clicked.connect(lambda: self._set_all(False))
        head.addWidget(self.all_b)
        head.addWidget(self.none_b)
        v.addLayout(head)
        self.tree = _GroupTree()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(['그룹', 'n'])
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(0)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setFrameShape(QFrame.Shape.NoFrame)
        hh = self.tree.header()
        hh.setStretchLastSection(False)
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.resizeSection(1, 56)
        self.tree.itemChanged.connect(lambda *_: self._apply())
        self.tree.reordered.connect(self._apply)
        v.addWidget(self.tree)
        self.note = hint('체크한 그룹만 그래프에 그립니다. 줄을 끌어 순서를 바꿉니다.')
        v.addWidget(self.note)
        self._busy = False
        self.refresh()

    def refresh(self):
        self._busy = True
        try:
            self.tree.clear()
            sp = self.get_spec()
            tabs = self.get_tables()
            col = G.group_column(sp) if sp is not None and sp.mapping.on or (sp is not None and sp.mapping.table) else ''
            vals = G.group_values(sp, tabs) if sp is not None and col else []
            if not vals:
                self.head.setText('나눌 범주가 없습니다')
                self.note.setText('X 축(또는 Y 축)을 범주로 두거나 색으로 나눌 열을 고르면 그 값이 여기에 나옵니다.')
                for w in (self.tree, self.all_b, self.none_b):
                    w.setVisible(False)
                return
            for w in (self.tree, self.all_b, self.none_b):
                w.setVisible(True)
            self.head.setText(f'기준: {col} 열')
            self.note.setText('체크한 그룹만 그래프에 그립니다. 줄을 끌어 순서를 바꿉니다.')
            hid = set(sp.cat_hidden)
            for name, n in vals:
                it = QTreeWidgetItem([name, str(n)])
                it.setFlags((it.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsDragEnabled)
                            & ~Qt.ItemFlag.ItemIsDropEnabled)
                it.setCheckState(0, Qt.CheckState.Unchecked if name in hid else Qt.CheckState.Checked)
                self.tree.addTopLevelItem(it)
            self.tree.setFixedHeight(min(28 * len(vals) + 30, 320))
        finally:
            self._busy = False

    def _apply(self):
        if self._busy:
            return
        sp = self.get_spec()
        if sp is None:
            return
        order, hidden = [], []
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            order.append(it.text(0))
            if it.checkState(0) != Qt.CheckState.Checked:
                hidden.append(it.text(0))
        sp.cat_order, sp.cat_hidden = order, hidden
        sp.mapping.on = True
        self.changed()

    def _set_all(self, on):
        self._busy = True
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self._busy = False
        self._apply()


# ---------------------------------------------------------------------------
# preview
# ---------------------------------------------------------------------------

class Preview(QFrame):
    """A small drawing of a spec."""

    def __init__(self, w=3.2, h=2.6, parent=None):
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from matplotlib.figure import Figure

        super().__init__(parent)
        self.setObjectName('hig_content')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        self.fig = Figure(figsize=(w, h), dpi=100, layout='constrained')
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.canvas.setMinimumSize(int(w * 90), int(h * 90))
        lay.addWidget(self.canvas)

    def show_spec(self, spec, tables):
        try:
            sp = spec.copy()
            sp.plot_auto = True
            G.draw(self.fig, sp, tables)
        except Exception as exc:  # noqa: BLE001
            self.fig.clear()
            self.fig.text(0.5, 0.5, f'그릴 수 없습니다: {exc}', ha='center', va='center', wrap=True)
        self.canvas.draw_idle()


# ---------------------------------------------------------------------------
# 새 그래프: 종류 → 축 배치 → 그룹
# ---------------------------------------------------------------------------

class StepBar(QWidget):
    def __init__(self, steps, parent=None):
        super().__init__(parent)
        self.steps, self.cur = steps, 0
        self.setFixedHeight(40)

    def set_step(self, i):
        self.cur = i
        self.update()

    def paintEvent(self, _e):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        n = len(self.steps)
        seg = self.width() / n
        f = QFont(self.font())
        for i, name in enumerate(self.steps):
            cx = seg * i + 20
            done, now = i < self.cur, i == self.cur
            qp.setPen(Qt.PenStyle.NoPen)
            qp.setBrush(theme.color('blue') if (done or now) else theme.color('fill'))
            qp.drawEllipse(int(cx - 12), 8, 24, 24)
            f.setWeight(QFont.Weight.DemiBold)
            f.setPixelSize(12)
            qp.setFont(f)
            qp.setPen(QColor('white') if (done or now) else theme.color('label-secondary'))
            qp.drawText(int(cx - 12), 8, 24, 24, Qt.AlignmentFlag.AlignCenter, '✓' if done else str(i + 1))
            f.setPixelSize(14)
            f.setWeight(QFont.Weight.DemiBold if now else QFont.Weight.Normal)
            qp.setFont(f)
            qp.setPen(theme.color('label') if (done or now) else theme.color('label-secondary'))
            qp.drawText(int(cx + 20), 8, int(seg - 60), 24, Qt.AlignmentFlag.AlignVCenter, name)
            if i < n - 1:
                x0 = cx + 28 + qp.fontMetrics().horizontalAdvance(name)
                qp.setPen(QPen(theme.color('separator'), 1.5))
                qp.drawLine(int(x0), 20, int(seg * (i + 1) + 2), 20)
        qp.end()


def _titled(title, w) -> QWidget:
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lab = QLabel(title)
    theme.text_style(lab, 'headline')
    lay.addWidget(lab)
    lay.addWidget(w)
    return box


class GraphWizard(QDialog):
    """새 그래프 (owner request 2026-11-09): an analysis' result becomes a
    graph in three steps, with a preview; everything stays editable in the
    inspector's 데이터 tab afterwards."""

    STEPS = ('그래프 종류', '축 배치', '그룹')

    def __init__(self, title, data: G.GraphData, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'새 그래프 · {title}')
        self.resize(1080, 640)
        self.data = data
        self.tables = {t.name: t for t in data.tables}
        sp = G.GraphSpec(chart='strip')
        m = G.guess_mapping(data.spec, self.tables)
        if not m.x_cat:  # the tool's own graph is an XY graph (time, distance)
            sp.chart = data.spec.chart if data.spec.chart in G.CHARTS else 'xy'
        else:
            sp.chart = 'strip' if data.spec.chart not in G.CATEGORY_CHARTS else data.spec.chart
        m.on = True
        sp.mapping = m
        for a in ('x', 'y'):
            src = getattr(data.spec, a)
            getattr(sp, a).unit = src.unit
        apply_stats_defaults(sp)
        self.spec = sp
        self._rebuild()

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)
        tl = QLabel(f'새 그래프 · {title}')
        theme.text_style(tl, 'title-2')
        root.addWidget(tl)
        self.bar = StepBar(('분석: ' + title,) + self.STEPS)
        self.bar.set_step(1)
        root.addWidget(self.bar)
        body = QHBoxLayout()
        body.setSpacing(24)
        self.pages = QStackedWidget()
        get = lambda: self.spec  # noqa: E731
        tabs = lambda: self.tables  # noqa: E731
        self.kinds = KindPicker(4, True)
        self.kinds.set_kind(sp.chart)
        self.kinds.set_recommended({G.recommend_chart(m, self.tables)} |
                                   ({'bar', 'box'} if m.x_cat else set()))
        self.kinds.picked.connect(self._kind)
        p0 = QWidget()
        l0 = QVBoxLayout(p0)
        l0.addWidget(_titled('어떤 그래프로 그릴까요?', self.kinds))
        l0.addWidget(hint('추천은 표의 열을 보고 고릅니다: 글자 열(그룹, 이미지)이 있으면 범주별로 비교하는 그래프, '
                          '숫자 두 열이면 XY. 나중에 오른쪽 ‘데이터’ 탭에서 언제든 바꿀 수 있습니다.'))
        l0.addStretch()
        self.mapping = MappingEditor(get, tabs, self._changed)
        p1 = QWidget()
        l1 = QVBoxLayout(p1)
        l1.addWidget(_titled('어떤 값을 어느 축에 놓을까요?', self.mapping))
        l1.addWidget(hint('범주: 같은 값끼리 한 자리에 모읍니다 (그룹, 이미지) · 값: 숫자 눈금 위에 놓습니다. '
                          'Y 축에는 열을 여러 개 놓을 수 있고, 색으로 나누기는 이 열의 값마다 색이 다른 점이 됩니다.'))
        l1.addStretch()
        self.groups = GroupEditor(get, tabs, self._changed)
        p2 = QWidget()
        l2 = QVBoxLayout(p2)
        l2.addWidget(_titled('어떤 그룹을 그래프에 넣을까요?', self.groups))
        l2.addStretch()
        for p in (p0, p1, p2):
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.setFrameShape(QFrame.Shape.NoFrame)
            sc.setWidget(p)
            theme.unify(p)
            self.pages.addWidget(sc)
        self.pages.setFixedWidth(660)
        body.addWidget(self.pages)
        right = QVBoxLayout()
        pl = QLabel('미리보기')
        theme.secondary(pl)
        right.addWidget(pl)
        self.preview = Preview()
        right.addWidget(self.preview)
        right.addWidget(hint('지금 고른 설정으로 그린 모양입니다.'))
        right.addStretch()
        body.addLayout(right, 1)
        root.addLayout(body, 1)
        bar = QHBoxLayout()
        cancel = QPushButton('취소')
        cancel.clicked.connect(self.reject)
        bar.addWidget(cancel)
        bar.addStretch()
        self.prev_b = QPushButton('이전')
        self.prev_b.clicked.connect(lambda: self.go(self.step - 1))
        bar.addWidget(self.prev_b)
        self.next_b = theme.prominent(QPushButton('다음'))
        self.next_b.setDefault(True)
        self.next_b.clicked.connect(self._next)
        bar.addWidget(self.next_b)
        root.addLayout(bar)
        self.step = 0
        self.go(0)

    def _rebuild(self):
        G.build_series(self.spec, self.tables)
        self.spec.legend_show = sum(1 for s in self.spec.series if s.visible) > 1 and \
            self.spec.mapping.color not in ('', G.category_column(self.spec))

    def _changed(self):
        self._rebuild()
        self.preview.show_spec(self.spec, self.tables)
        if self.pages.currentIndex() != 2:
            QTimer.singleShot(0, self.groups.refresh)

    def _kind(self, k):
        sp = self.spec
        old = sp.chart
        sp.chart = k
        m = sp.mapping
        if k in G.CATEGORY_CHARTS and old not in G.CATEGORY_CHARTS and not (m.x_cat or m.y_cat):
            t = self.tables.get(m.table)
            texts = G.text_columns(t) if t is not None else []
            if texts:
                m.x, m.x_cat = texts[0], True
        if k in G.CATEGORY_CHARTS and m.x_cat and m.y_cat:
            m.y_cat = False
        self.mapping.refresh()
        self._changed()

    def go(self, i):
        self.step = max(0, min(2, i))
        self.pages.setCurrentIndex(self.step)
        self.bar.set_step(self.step + 1)
        self.prev_b.setEnabled(self.step > 0)
        self.next_b.setText('그래프 만들기' if self.step == 2 else '다음')
        if self.step == 1:
            self.mapping.refresh()
        if self.step == 2:
            self.groups.refresh()
        self.preview.show_spec(self.spec, self.tables)

    def _next(self):
        if self.step == 2:
            self.accept()
        else:
            self.go(self.step + 1)


# ---------------------------------------------------------------------------
# 통계 · 유의성 표시
# ---------------------------------------------------------------------------

def _small_table(cols, widths=()):
    tw = QTableWidget(0, len(cols))
    tw.setHorizontalHeaderLabels(cols)
    tw.verticalHeader().hide()
    tw.setShowGrid(False)
    tw.setFrameShape(QFrame.Shape.NoFrame)
    tw.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    tw.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    tw.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    hh = tw.horizontalHeader()
    hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    hh.setStretchLastSection(False)
    for i, w in widths:
        tw.setColumnWidth(i, w)
    tw.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return tw


def _fit_rows(tw, h=30):
    for r in range(tw.rowCount()):
        tw.setRowHeight(r, h)
    tw.setFixedHeight(h * tw.rowCount() + 32)


class StatsEditor(QWidget):
    """The significance settings: 데이터 확인 (full), 검정, 비교할 쌍, 표시.
    Works on get_spec().stats; changed() after every edit."""

    def __init__(self, get_spec, get_tables, changed, full=True, parent=None):
        super().__init__(parent)
        self.get_spec, self.get_tables, self.changed = get_spec, get_tables, changed
        self.full = full
        self._busy = False
        self.res = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        # 데이터 확인
        self.diag_box = QGroupBox('데이터 확인')
        dv = QVBoxLayout(self.diag_box)
        self.diag = _small_table(['그룹', 'n', '정규성 (Shapiro-Wilk)', ''], ((1, 44), (2, 170), (3, 70)))
        self.diag.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        dv.addWidget(self.diag)
        df = QWidget()
        dfl = QFormLayout(df)
        self.levene = QLabel()
        dfl.addRow('등분산 (Levene)', self.levene)
        dv.addWidget(df)
        lay.addWidget(self.diag_box)
        self.diag_box.setVisible(full)
        # 검정
        box = QGroupBox('검정')
        f = QFormLayout(box)
        self.rec = theme.StatusLabel('', kind='info')
        f.addRow(self.rec)
        self.target = QComboBox()
        self.target.setToolTip('범주끼리 비교할 값 (Y 열 / 시리즈)')
        self.target.currentIndexChanged.connect(lambda _i: self._set('series', self.target.currentData()))
        f.addRow('비교할 값', self.target)
        self.paired = combo([('독립 (그룹마다 다른 세포)', False), ('짝지음 (같은 세포 · 이미지)', True)])
        self.paired.currentIndexChanged.connect(lambda _i: self._set('paired', self.paired.currentData()))
        f.addRow('표본', self.paired)
        self.method = QComboBox()
        self.method.currentIndexChanged.connect(lambda _i: self._set('method', self.method.currentData()))
        f.addRow('방법', self.method)
        tails = QWidget()
        tl = QVBoxLayout(tails)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(4)
        self.tail_group = QButtonGroup(self)
        self.tails = {}
        for k, t in ST.TAILS.items():
            r = QRadioButton(t + (' — 추천' if k == 'two' else ''))
            self.tail_group.addButton(r)
            r.toggled.connect(lambda on, k=k: on and self._set('tail', k))
            tl.addWidget(r)
            self.tails[k] = r
        f.addRow('꼬리', tails)
        self.corr = combo([(v, k) for k, v in ST.CORRECTIONS.items()])
        self.corr.currentIndexChanged.connect(lambda _i: self._set('correction', self.corr.currentData()))
        f.addRow('다중 비교 보정', self.corr)
        self.alpha = combo([('0.05', 0.05), ('0.01', 0.01), ('0.001', 0.001)])
        self.alpha.currentIndexChanged.connect(lambda _i: self._set('alpha', self.alpha.currentData()))
        f.addRow('유의 수준 α', self.alpha)
        self.test_note = hint('')
        f.addRow(self.test_note)
        lay.addWidget(box)
        # 비교할 쌍
        pbox = QGroupBox('비교할 쌍')
        pv = QVBoxLayout(pbox)
        from .hig_widgets import Chip

        quick = QWidget()
        ql = QHBoxLayout(quick)
        ql.setContentsMargins(0, 0, 0, 0)
        ql.setSpacing(6)
        self.modes = {}
        for k, t in (('all', '모든 쌍'), ('ref', '기준 대 나머지'), ('custom', '직접 고르기')):
            c = Chip(t, False)
            c.setAutoExclusive(True)
            c.clicked.connect(lambda _=False, k=k: self._set('pairs_mode', k))
            ql.addWidget(c)
            self.modes[k] = c
        ql.addStretch()
        pv.addWidget(quick)
        rf = QWidget()
        rfl = QFormLayout(rf)
        self.ref = QComboBox()
        self.ref.currentIndexChanged.connect(lambda _i: self._set('ref', self.ref.currentText()))
        rfl.addRow('기준 그룹', self.ref)
        pv.addWidget(rf)
        self.pairs = _small_table(['', '쌍', '보정 p', '표시'], ((0, 36), (2, 80), (3, 70)))
        self.pairs.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.pairs.itemChanged.connect(self._pair_checked)
        pv.addWidget(self.pairs)
        lay.addWidget(pbox)
        # 표시
        mbox = QGroupBox('표시')
        mf = QFormLayout(mbox)
        self.display = combo([(v, k) for k, v in ST.DISPLAYS.items()])
        self.display.currentIndexChanged.connect(lambda _i: self._set('display', self.display.currentData()))
        mf.addRow('표시 방식', self.display)
        self.levels = combo([('4단계 (* ~ ****)', 4), ('3단계 (* ~ ***)', 3)])
        self.levels.currentIndexChanged.connect(lambda _i: self._set('levels', self.levels.currentData()))
        mf.addRow('별표 기준', self.levels)
        self.ns = QCheckBox('유의하지 않으면 ns 표시')
        self.ns.toggled.connect(lambda v: self._set('ns', bool(v)))
        mf.addRow(self.ns)
        self.bracket = combo([('꺾쇠', 'tick'), ('직선', 'line')])
        self.bracket.currentIndexChanged.connect(lambda _i: self._set('bracket', self.bracket.currentData()))
        mf.addRow('괄호', self.bracket)
        self.lw = QDoubleSpinBox()
        self.lw.setRange(0.1, 6)
        self.lw.setSingleStep(0.1)
        self.lw.setSuffix(' pt')
        self.lw.valueChanged.connect(lambda v: self._set('line_width', float(v)))
        mf.addRow('선 굵기', self.lw)
        self.fsize = QDoubleSpinBox()
        self.fsize.setRange(4, 40)
        self.fsize.setSingleStep(0.5)
        self.fsize.setSuffix(' pt')
        self.fsize.valueChanged.connect(lambda v: self._set('font_size', float(v)))
        mf.addRow('글자 크기', self.fsize)
        self.bold = QCheckBox('별표 굵게')
        self.bold.toggled.connect(lambda v: self._set('bold', bool(v)))
        mf.addRow(self.bold)
        mf.addRow(hint('* p < 0.05 · ** < 0.01 · *** < 0.001 · **** < 0.0001'))
        self.cap_on = QCheckBox('캡션 문장 만들기')
        self.cap_on.toggled.connect(lambda v: self._set('caption', bool(v)))
        mf.addRow(self.cap_on)
        self.cap = QPlainTextEdit()
        self.cap.setReadOnly(True)
        self.cap.setFixedHeight(84)
        mf.addRow(self.cap)
        cb = QPushButton('캡션 복사')
        cb.clicked.connect(lambda: QApplication.clipboard().setText(self.cap.toPlainText()))
        self.cap_copy = cb
        mf.addRow(cb)
        lay.addWidget(mbox)
        lay.addStretch()

    # ---- spec <-> widgets ----
    def _set(self, k, v):
        if self._busy:
            return
        sp = self.get_spec()
        if sp is None:
            return
        st = sp.stats
        if k == 'pairs_mode' and v == 'custom' and not st.pairs and self.res is not None:
            st.pairs = [[a, b] for a, b, _p in self.res.pairs]
        setattr(st, k, v)
        self.changed()
        QTimer.singleShot(0, self.refresh)

    def _pair_checked(self, it):
        if self._busy or it.column() != 0:
            return
        sp = self.get_spec()
        chosen = []
        for r in range(self.pairs.rowCount()):
            c = self.pairs.item(r, 0)
            if c is not None and c.checkState() == Qt.CheckState.Checked:
                chosen.append(list(c.data(Qt.ItemDataRole.UserRole)))
        sp.stats.pairs = chosen
        sp.stats.pairs_mode = 'custom'
        self.changed()
        QTimer.singleShot(0, self.refresh)

    def refresh(self):
        sp = self.get_spec()
        tabs = self.get_tables()
        if sp is None:
            return
        self._busy = True
        try:
            st = sp.stats
            opts = G.stats_options(sp, tabs) if sp.chart in G.CATEGORY_CHARTS else {}
            self.target.clear()
            for name in opts:
                self.target.addItem(name, name)
            self.target.setCurrentIndex(max(self.target.findData(st.series), 0))
            self.target.setEnabled(len(opts) > 1)
            groups, _idx = G.stats_groups(sp, tabs) if opts else ({}, [])
            names = list(groups)
            if len(names) >= 2:
                pairs = ST.pairs_for(names, st.pairs_mode, st.ref, st.pairs)
                all_pairs = ST.pairs_for(names, 'all')
                self.res = res = ST.run(groups, st.method, all_pairs, st.tail, st.correction, st.paired, st.alpha)
                shown = ST.run(groups, st.method, pairs, st.tail, st.correction, st.paired, st.alpha)
            else:
                self.res = res = shown = None
            # 데이터 확인
            self.diag.setRowCount(0)
            if res is not None:
                c = res.check
                for r, (g, n, p) in enumerate(zip(c.names, c.n, c.normal_p)):
                    self.diag.insertRow(r)
                    ok = '확인 불가' if p != p else ('정규' if p >= st.alpha else '비정규')
                    for j, t in enumerate((g, str(n), 'n < 3' if p != p else f'p = {p:.2f}', ok)):
                        self.diag.setItem(r, j, QTableWidgetItem(t))
                lv = c.levene_p
                self.levene.setText('확인 불가' if lv != lv else f'p = {lv:.2f} · {"비슷함" if lv >= st.alpha else "다름"}')
            _fit_rows(self.diag)
            # 검정
            self.paired.setCurrentIndex(1 if st.paired else 0)
            if res is not None:
                self.rec.setText(f'추천: {res.reason}')
                self.rec.setVisible(True)
            else:
                self.rec.setText('범주가 둘 이상인 막대 · 점 · 상자 · 바이올린 그래프에서 비교합니다.')
            self.method.clear()
            rec = res.recommended if res is not None else ''
            self.method.addItem(f'추천: {ST.METHODS[rec][0]}' if rec else '추천 (데이터에 맞게)', 'auto')
            many = len(names) > 2
            for k, (n, _c, kind) in ST.METHODS.items():
                if not many and kind != 'pair':
                    continue
                if (k in ST.PAIRED) != bool(st.paired) and kind == 'pair':
                    continue
                self.method.addItem(n, k)
            self.method.setCurrentIndex(max(self.method.findData(st.method), 0))
            m = res.method if res is not None else 'auto'
            kind = ST.METHODS[m][2] if m in ST.METHODS else 'pair'
            for k, r in self.tails.items():
                r.setChecked(st.tail == k)
                r.setEnabled(kind == 'pair' or k == 'two')
            self.corr.setCurrentIndex(max(self.corr.findData(st.correction), 0))
            self.corr.setEnabled(kind != 'omni')
            self.corr.setToolTip('Tukey · Games-Howell은 자체 보정을 씁니다.' if kind == 'omni' else '')
            self.alpha.setCurrentIndex(max(self.alpha.findData(st.alpha), 0))
            note = []
            if res is not None and res.omnibus:
                note.append(f'전체 {res.omnibus[0]}: p = {res.omnibus[2]:.2g}.')
            if kind != 'pair':
                note.append('사후 검정은 양측으로만 계산합니다.')
            note.append('단측은 실험 전에 방향을 정해 둔 경우에만 씁니다.')
            if res is not None and res.note:
                note.append(res.note)
            self.test_note.setText(' '.join(note))
            # 쌍
            for k, c in self.modes.items():
                c.setChecked(st.pairs_mode == k)
            self.ref.clear()
            self.ref.addItems(names)
            self.ref.setCurrentIndex(max(self.ref.findText(st.ref), 0))
            self.ref.setEnabled(st.pairs_mode == 'ref')
            self.pairs.setRowCount(0)
            chosen = {(a, b) for a, b, _p in (shown.pairs if shown else [])}
            lookup = {(a, b): p for a, b, p in (shown.pairs if shown else [])}
            listing = (res.pairs if res is not None else [])
            if st.pairs_mode == 'ref' and shown is not None:
                listing = shown.pairs
            for r, (a, b, p) in enumerate(listing):
                self.pairs.insertRow(r)
                it = QTableWidgetItem()
                it.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                it.setCheckState(Qt.CheckState.Checked if (a, b) in chosen else Qt.CheckState.Unchecked)
                it.setData(Qt.ItemDataRole.UserRole, (a, b))
                self.pairs.setItem(r, 0, it)
                self.pairs.setItem(r, 1, QTableWidgetItem(f'{a}  ↔  {b}'))
                pp = lookup.get((a, b), p)
                self.pairs.setItem(r, 2, QTableWidgetItem(
                    'n/a' if pp != pp else (f'{pp:.1e}' if pp < 0.001 else f'{pp:.3f}')))
                self.pairs.setItem(r, 3, QTableWidgetItem(ST.stars(pp, st.levels, st.alpha)))
            _fit_rows(self.pairs, 30)
            # 표시
            self.display.setCurrentIndex(max(self.display.findData(st.display), 0))
            self.levels.setCurrentIndex(max(self.levels.findData(st.levels), 0))
            self.ns.setChecked(st.ns)
            self.bracket.setCurrentIndex(max(self.bracket.findData(st.bracket), 0))
            self.lw.setValue(st.line_width)
            self.fsize.setValue(st.font_size)
            self.bold.setChecked(st.bold)
            self.cap_on.setChecked(st.caption)
            text = ST.caption(shown, st.levels, st.alpha) if (shown is not None and st.caption) else ''
            self.cap.setPlainText(text)
            self.cap.setVisible(st.caption)
            self.cap_copy.setVisible(st.caption)
        finally:
            self._busy = False


class StatsDialog(QDialog):
    """통계 · 유의성 표시 (owner request 2026-11-09): the data check, the
    recommended test, the pairs and the marks, with a preview; 적용 writes
    them into the graph."""

    def __init__(self, spec: G.GraphSpec, tables: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle('통계 · 유의성 표시')
        self.resize(1240, 760)
        self.spec = spec.copy()
        self.spec.stats.on = True
        self.tables = tables
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)
        tl = QLabel('통계 · 유의성 표시')
        theme.text_style(tl, 'title-2')
        root.addWidget(tl)
        body = QHBoxLayout()
        body.setSpacing(24)
        self.editor = StatsEditor(lambda: self.spec, lambda: self.tables, self._changed, full=True)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sc.setWidget(self.editor)
        theme.unify(self.editor)
        sc.setFixedWidth(640)
        body.addWidget(sc)
        right = QVBoxLayout()
        pl = QLabel('미리보기')
        theme.secondary(pl)
        right.addWidget(pl)
        self.preview = Preview(4.2, 3.4)
        right.addWidget(self.preview)
        right.addStretch()
        body.addLayout(right, 1)
        root.addLayout(body, 1)
        bar = QHBoxLayout()
        cancel = QPushButton('취소')
        cancel.clicked.connect(self.reject)
        bar.addWidget(cancel)
        bar.addStretch()
        ok = theme.prominent(QPushButton('적용'))
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        bar.addWidget(ok)
        root.addLayout(bar)
        self.editor.refresh()
        self._changed()

    def _changed(self):
        self.preview.show_spec(self.spec, self.tables)
