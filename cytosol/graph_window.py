"""그래프 편집 창: one window for every graph (owner request 2026-11-05).
Sidebar: the graphs (several at once). Canvas: a chip per tool (세포질 ROI
측정, 입자 ROI 측정, 강도 측정, 등거리 띠, Coloc 2, 라인 프로파일, FRAP,
일괄 분석) whose result becomes the graph's data (tools with nothing
analysed look disabled), the graph, and its data underneath. Inspector:
종류 / 값 / 모양 / 컴포넌트; the first three show 선택한 요소 (what was
clicked on the graph: a series, an axis name, the title, the legend, a text
box) above 전체 그래프. Graphs and their data are saved through
파일 › 내보내기 (exporter.py)."""

from __future__ import annotations

import re
import traceback
from dataclasses import asdict
from pathlib import Path

import numpy as np
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import theme
from . import graph as G
from .flow import FlowLayout

IMAGE_FILTERS = {'PNG (*.png)': '.png', 'TIFF (*.tif)': '.tif', 'PDF (*.pdf)': '.pdf',
                 'SVG (*.svg)': '.svg'}
EDITOR_W = 400
SIDEBAR_W = 220
ZOOM_STEP = 1.25
ZOOM_DRAG_RATE = 0.004
HANDLE_PX = 9
OBJECT_NAMES = {'plot': '그래프 영역', 'title': '제목', 'xlabel': 'X 축 이름', 'ylabel': 'Y 축 이름',
                'legend': '범례', 'text': '글자 상자'}


def _safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', '_', name).strip('_') or 'table'


class ColorButton(QPushButton):
    """Shows a color; click to pick another. allow_empty: right-click = '' (auto)."""

    changed = Signal(str)

    def __init__(self, allow_empty=False, parent=None):
        super().__init__(parent)
        self.allow_empty = allow_empty
        self._color = '#000000'
        self.setFixedWidth(64)
        self.clicked.connect(self._pick)
        if allow_empty:
            self.setToolTip('클릭: 색 고르기 · 오른쪽 클릭: 자동 (시리즈 색)')

    def color(self) -> str:
        return self._color

    def setColor(self, c: str):
        self._color = c or ''
        if self._color:
            q = QColor(self._color)
            self.setText(self._color)
            self.setStyleSheet(f'background-color: {q.name()}; color: '
                               f"{'black' if q.lightness() > 128 else 'white'}; font-size: 10px;")
        else:
            self.setText('자동')
            self.setStyleSheet('font-size: 10px;')

    def _pick(self):
        c = QColorDialog.getColor(QColor(self._color or '#000000'), self, '색 고르기')
        if c.isValid():
            self.setColor(c.name())
            self.changed.emit(self._color)

    def mousePressEvent(self, e):
        if self.allow_empty and e.button() == Qt.MouseButton.RightButton:
            self.setColor('')
            self.changed.emit('')
            return
        super().mousePressEvent(e)


class FloatEdit(QLineEdit):
    """A number field that keeps full precision (axis limits, tick spacing)."""

    valueChanged = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMaximumWidth(90)
        self.editingFinished.connect(self._done)

    def value(self) -> float:
        t = self.text().replace(',', '.').strip()
        try:
            if '/' in t:  # 1/60 for s -> min
                a, b = t.split('/', 1)
                return float(a) / float(b)
            return float(t)
        except (ValueError, ZeroDivisionError):
            return float('nan')

    def setValue(self, v: float):
        self.setText('' if v is None or not np.isfinite(v) else f'{v:.6g}')

    def _done(self):
        v = self.value()
        if np.isfinite(v):
            self.valueChanged.emit(v)


class Binder:
    """Two-way links between widgets and fields of the spec (or of the
    selected series / text box): a widget change writes the field and asks for
    a redraw; sync() fills every widget from the spec."""

    def __init__(self, changed):
        self.changed = changed
        self.syncs = []
        self.busy = False

    def _set(self, obj, attr, value):
        if self.busy:
            return
        o = obj()
        if o is None:
            return
        setattr(o, attr, value)
        self.changed()

    def bind(self, w, obj, attr, data=False):
        if isinstance(w, QCheckBox):
            w.toggled.connect(lambda v: self._set(obj, attr, bool(v)))
            put = w.setChecked
        elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
            w.valueChanged.connect(lambda v: self._set(obj, attr, v))
            put = w.setValue
        elif isinstance(w, FloatEdit):
            w.valueChanged.connect(lambda v: self._set(obj, attr, v))
            put = w.setValue
        elif isinstance(w, ColorButton):
            w.changed.connect(lambda v: self._set(obj, attr, v))
            put = w.setColor
        elif isinstance(w, QComboBox) and data:
            w.currentIndexChanged.connect(lambda i: self._set(obj, attr, w.itemData(i)))

            def put(v, w=w):
                i = w.findData(v)
                w.setCurrentIndex(i if i >= 0 else 0)
        elif isinstance(w, QComboBox):
            (w.currentTextChanged if not w.isEditable() else w.editTextChanged).connect(
                lambda v: self._set(obj, attr, v))

            def put(v, w=w):
                i = w.findText(v)
                if i >= 0:
                    w.setCurrentIndex(i)
                elif w.isEditable():
                    w.setEditText(v)
        elif isinstance(w, QPlainTextEdit):
            w.textChanged.connect(lambda: self._set(obj, attr, w.toPlainText()))

            def put(v, w=w):
                if w.toPlainText() != v:
                    w.setPlainText(v)
        else:  # QLineEdit
            w.textChanged.connect(lambda v: self._set(obj, attr, v))

            def put(v, w=w):
                if w.text() != v:
                    w.setText(v)

        def sync(w=w, put=put):
            o = obj()
            w.setEnabled(o is not None)
            if o is not None:
                put(getattr(o, attr))

        self.syncs.append(sync)
        return w

    def sync(self):
        self.busy = True
        try:
            for f in self.syncs:
                f()
        finally:
            self.busy = False


def _combo(options: dict) -> QComboBox:
    c = QComboBox()
    for k, v in options.items():
        c.addItem(v, k)
    return c


def _dspin(lo, hi, step=0.1, dec=2, suffix='') -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setDecimals(dec)
    if suffix:
        s.setSuffix(suffix)
    return s


def _row(*ws) -> QWidget:
    w = QWidget()
    f = FlowLayout(w)
    f.setContentsMargins(0, 0, 0, 0)
    for x in ws:
        f.addWidget(x)
    return w


def _hint(text) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    theme.hint(lab)
    return lab


class TableModel(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self.table = G.Table('', [], [])
        self._text = []

    def set_table(self, t: G.Table):
        self.beginResetModel()
        self.table = t
        self._text = t.text_rows()
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._text)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.table.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            r = self._text[index.row()]
            return r[index.column()] if index.column() < len(r) else ''
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self.table.columns[section] if section < len(self.table.columns) else ''
        return str(section + 1)


class GraphDoc:
    """One graph of the window: its data (from a tool or tables brought in),
    its settings and what is selected on it."""

    def __init__(self, key, title, data_fn=None, source=None):
        self.key = key
        self.title = title
        self.data_fn = data_fn or (lambda: None)
        self.source = source  # graph_sources key the data comes from (None: own tables)
        self.data: G.GraphData | None = None
        self.spec = G.GraphSpec()
        self.default_spec = G.GraphSpec()
        self.extra = []  # tables brought in from other analyses / CSV files
        self.series_i = -1
        self.text_i = -1
        self.item_i = -1
        self.sel = None  # selected object on the graph: (kind, index)

    def tables(self) -> dict:
        return {t.name: t for t in (self.data.tables if self.data else [])}


def _doc(name):
    return property(lambda self: getattr(self.doc, name), lambda self, v: setattr(self.doc, name, v))


class _AllSeries:
    """Every series at once (전체 그래프 settings): reads the first one,
    writes all of them."""

    def __init__(self, spec):
        object.__setattr__(self, '_spec', spec)

    def __getattr__(self, k):
        s = self._spec.series[0]
        if k == 'err_show':
            return s.err_style != 'none'
        if k == 'err_kind':
            return self._spec.bar_err if self._spec.chart in G.CATEGORY_CHARTS else s.agg_err
        return getattr(s, k)

    def __setattr__(self, k, v):
        sp = self._spec
        for s in sp.series:
            if k == 'err_show':
                s.err_style = ('bar' if s.err_style == 'none' else s.err_style) if v else 'none'
            elif k == 'err_kind':
                s.agg_err = v
            else:
                setattr(s, k, v)
        if k == 'err_kind':
            sp.bar_err = v
        if k == 'err_show' and not v:
            sp.bar_err = 'none'
        elif k == 'err_show' and sp.bar_err == 'none':
            sp.bar_err = 'sd'


SEL_KINDS = ('none', 'series', 'axis', 'title', 'legend', 'text')


class GraphWindow(QMainWindow):
    """그래프 편집 창 (owner request 2026-11-05): one window, Sidebar (the
    graphs) | Canvas (a chip per tool to take the data from, the graph, the
    data below it) | Inspector (종류 / 값 / 모양 / 컴포넌트, each split into
    선택한 요소 = what was clicked on the graph and 전체 그래프). Saving goes
    through 파일 › 내보내기 of the main window."""

    data = _doc('data')
    spec = _doc('spec')
    default_spec = _doc('default_spec')
    extra = _doc('extra')
    key = _doc('key')
    feature = _doc('title')
    data_fn = _doc('data_fn')
    _series_i = _doc('series_i')
    _text_i = _doc('text_i')
    _item_i = _doc('item_i')
    sel = _doc('sel')

    def __init__(self, win, parent=None):
        super().__init__(parent)
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from matplotlib.figure import Figure

        from . import hig_widgets

        self.win = win
        self.docs: list[GraphDoc] = []
        self.doc = GraphDoc(None, '')  # nothing yet
        self.art = {}
        self._drag = None
        self._scales = {}
        self.setWindowTitle('그래프 편집')
        self.resize(1440, 900)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self.render)
        self.b = Binder(self._changed)

        # ---- canvas box: data chips, the graph, the data table ----
        self.fig = Figure(figsize=(5, 3.6), dpi=100, layout='constrained')
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.canvas.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.canvas.setToolTip('클릭으로 고른 뒤 끌어 옮기고, 파란 모서리 핸들을 끌어 크기를 바꿉니다. '
                               '두 번 클릭: 글자 고치기 · 오른쪽 클릭: 글자 상자 추가 · '
                               '확대·축소: Cmd(Ctrl)+위아래 드래그, Cmd(Ctrl)+휠, ] [')
        self.zoom = 1.0  # 1 = the whole graph fits the preview
        self._overlay = []
        self._last_live = 0.0
        self.holder = QScrollArea()
        self.holder.setFrameShape(QScrollArea.Shape.NoFrame)
        self.holder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.holder.setWidgetResizable(False)
        self.holder.setWidget(self.canvas)
        self.holder.viewport().installEventFilter(self)
        for ev, fn in (('button_press_event', self._press), ('motion_notify_event', self._motion),
                       ('button_release_event', self._release), ('scroll_event', self._scroll_ev)):
            self.canvas.mpl_connect(ev, fn)

        self.chips = {}  # graph source key -> Chip
        chip_row = QWidget()
        cr = FlowLayout(chip_row)
        cr.setContentsMargins(0, 0, 0, 0)
        lab = QLabel('새 그래프')
        theme.secondary(lab)
        cr.addWidget(lab)
        for key, (title, *_r) in self._sources().items():
            c = hig_widgets.Chip(title, False)
            c.setCheckable(False)
            c.clicked.connect(lambda _=False, k=key: self.start_wizard(k))
            self.chips[key] = c
            cr.addWidget(c)
        csv_chip = hig_widgets.Chip('CSV…', False)
        csv_chip.setCheckable(False)
        csv_chip.setToolTip('CSV 표(첫 줄 = 열 이름)로 새 그래프를 만듭니다.')
        csv_chip.clicked.connect(lambda: self.start_wizard_csv())
        cr.addWidget(csv_chip)
        self.zoom_label = QLabel('100 %')
        theme.secondary(self.zoom_label)
        self.zoom_label.setToolTip('미리보기 배율 (보기 메뉴, Cmd/Ctrl+드래그)')

        table_box = QWidget()
        bl = QVBoxLayout(table_box)
        bl.setContentsMargins(0, 8, 0, 0)
        row = QHBoxLayout()
        self.table_pick = QComboBox()
        self.table_pick.currentIndexChanged.connect(lambda _: self.fill_table())
        row.addWidget(self.table_pick)
        self.only_sel = QCheckBox('선택한 시리즈만')
        self.only_sel.setToolTip('그래프에 쓰인 데이터 / 요약에서 고른 시리즈만 봅니다.')
        self.only_sel.toggled.connect(lambda _: self.fill_table())
        row.addWidget(self.only_sel)
        row.addStretch()
        self.table_info = QLabel()
        theme.secondary(self.table_info)
        row.addWidget(self.table_info)
        row.addWidget(self.zoom_label)
        bl.addLayout(row)
        self.model = TableModel()
        self.view = QTableView()
        self.view.setModel(self.model)
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.view.horizontalHeader().setDefaultSectionSize(110)
        copy = QAction('복사', self.view)
        copy.setShortcut(QKeySequence.StandardKey.Copy)
        copy.triggered.connect(self.copy_selection)
        self.view.addAction(copy)
        bl.addWidget(self.view, 1)

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.holder)
        split.addWidget(table_box)
        split.setStretchFactor(0, 7)
        split.setStretchFactor(1, 3)
        split.setSizes([640, 300])
        split.setChildrenCollapsible(False)
        self.split = split
        content = QWidget()
        content.setObjectName('hig_content')
        content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        cl = QVBoxLayout(content)
        cl.setContentsMargins(*theme.CONTENT_MARGINS)
        cl.setSpacing(12)
        cl.addWidget(chip_row)
        cl.addWidget(split, 1)

        # ---- inspector box: 종류 / 값 / 모양 / 컴포넌트 ----
        self._color_rows = {}
        self.editor = hig_widgets.ChipTabs()
        for title, build in (('데이터', self._build_data_tab), ('모양', self._build_look_tab),
                             ('통계', self._build_stats_tab)):
            self.editor.addTab(self._scroll(build()), title)
        insp = hig_widgets.inspector(self.editor)
        insp.setFixedWidth(EDITOR_W)

        # ---- sidebar: the graphs ----
        side = QWidget()
        side.setObjectName('hig_sidebar')
        side.setFixedWidth(SIDEBAR_W)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(*theme.SIDEBAR_MARGINS)
        sl.setSpacing(8)
        head = QLabel('그래프')
        theme.text_style(head, 'headline')
        head.setToolTip('오른쪽 클릭: 복제 · 이름 바꾸기 · 삭제')
        sl.addWidget(head)
        from .image_tree import WrapDelegate

        self.doc_list = QTreeWidget()
        self.doc_list.setHeaderHidden(True)
        self.doc_list.setRootIsDecorated(False)
        self.doc_list.setIndentation(0)
        self.doc_list.setItemDelegate(WrapDelegate(self.doc_list))
        self.doc_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.doc_list.currentItemChanged.connect(self._doc_picked)
        self.doc_list.itemDoubleClicked.connect(lambda *_: self.rename_doc())
        self.doc_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.doc_list.customContextMenuRequested.connect(self._doc_menu)
        sl.addWidget(self.doc_list, 1)

        body = hig_widgets.PaneSplitter()
        body.addWidget(side)
        body.addWidget(content)
        body.addWidget(insp)
        body.setChildrenCollapsible(False)
        for i, f in enumerate((0, 1, 0)):
            body.setStretchFactor(i, f)
        self.setCentralWidget(body)
        self._build_menus()
        self._show_selection()

    # ---- graphs (documents) ------------------------------------------------------------------

    def doc_for(self, key) -> GraphDoc | None:
        return next((d for d in self.docs if d.key == key), None)

    def _free_key(self) -> str:
        n = 1
        while self.doc_for(f'free{n}') is not None:
            n += 1
        return f'free{n}'

    def add_doc(self, key, title, data_fn=None, source=None) -> GraphDoc:
        d = GraphDoc(key, title, data_fn, source)
        self.docs.append(d)
        it = QTreeWidgetItem([title])
        self.doc_list.addTopLevelItem(it)
        return d

    def new_doc(self, key=None, title=None) -> GraphDoc:
        key = key or self._free_key()
        d = self.add_doc(key, title or f'새 그래프 {key[4:] if key.startswith("free") else ""}'.strip())
        d.data = G.GraphData(d.title, [], G.GraphSpec(title=''))
        d.spec = d.data.spec.copy()
        self.show_doc(d)
        return d

    def duplicate_doc(self):
        src = self.doc
        if src.key is None:
            return
        d = self.add_doc(self._free_key(), f'{src.title} (복제)', src.data_fn, src.source)
        d.data = G.GraphData(d.title, list(src.data.tables) if src.data else [], src.spec.copy(),
                             *(() if src.data is None else (src.data.name, src.data.folder)))
        d.spec, d.default_spec = src.spec.copy(), src.default_spec.copy()
        d.extra = list(src.extra)
        d.series_i = src.series_i
        self.show_doc(d)
        self._changed_no_redraw()

    def rename_doc(self):
        d = self.doc
        if d.key is None:
            return
        text, ok = QInputDialog.getText(self, '그래프 이름', '이름:', text=d.title)
        if ok and text.strip():
            d.title = text.strip()
            self._doc_item(d).setText(0, d.title)
            self._changed_no_redraw()

    def remove_doc(self, d=None):
        d = d or self.doc
        if d not in self.docs:
            return
        i = self.docs.index(d)
        self.docs.pop(i)
        self.doc_list.takeTopLevelItem(i)
        if self.docs:
            self.show_doc(self.docs[min(i, len(self.docs) - 1)])
        else:
            self.doc = GraphDoc(None, '')
            self.fig.clear()
            self.art = {}
            self.canvas.draw_idle()
            self._fill_lists()
            self.sync()
            self._show_selection()
        self._changed_no_redraw()

    def clear_docs(self):
        while self.docs:
            self.remove_doc(self.docs[-1])

    def _doc_item(self, d):
        return self.doc_list.topLevelItem(self.docs.index(d))

    def _doc_picked(self, cur, _prev):
        if cur is None:
            return
        i = self.doc_list.indexOfTopLevelItem(cur)
        if 0 <= i < len(self.docs) and self.docs[i] is not self.doc:
            self.show_doc(self.docs[i])

    def _doc_menu(self, pos):
        it = self.doc_list.itemAt(pos)
        m = QMenu(self)
        m.addAction('새 그래프', lambda: self.new_doc())
        if it is not None:
            self._doc_picked(it, None)
            m.addAction('복제', self.duplicate_doc)
            m.addAction('이름 바꾸기…', self.rename_doc)
            m.addSeparator()
            m.addAction('그래프 삭제…', self.confirm_remove_doc)
        m.exec(self.doc_list.viewport().mapToGlobal(pos))

    def confirm_remove_doc(self):
        if self.doc.key is not None and theme.confirm_destructive(
                self, '그래프 삭제', f'‘{self.doc.title}’ 그래프를 삭제할까요?', '삭제'):
            self.remove_doc()

    def show_doc(self, d: GraphDoc):
        """Make d the graph shown and edited."""
        self.doc = d
        self._scales = {}
        it = self._doc_item(d)
        if self.doc_list.currentItem() is not it:
            self.doc_list.blockSignals(True)
            self.doc_list.setCurrentItem(it)
            it.setSelected(True)
            self.doc_list.blockSignals(False)
        self.setWindowTitle(f'그래프 편집 · {d.title}')
        self._fill_lists()
        self.sync()
        self._show_selection()
        self.refresh_chips()
        if d.data is not None:
            self.render()
        else:
            self.fig.clear()
            self.art = {}
            self.canvas.draw_idle()

    def states(self) -> dict:
        """key -> settings of every graph (projects)."""
        cur = self.doc
        out = {}
        for d in self.docs:
            self.doc = d
            out[d.key] = self.state()
        self.doc = cur
        return out

    # ---- data sources (chips) -----------------------------------------------------------------

    def refresh_chips(self):
        """A chip per tool; tools with nothing analysed yet look disabled."""
        from PySide6.QtWidgets import QGraphicsOpacityEffect

        srcs = self._sources()
        for key, c in self.chips.items():
            title, _tab, fn, hint = srcs.get(key, ('', None, lambda: None, ''))
            try:
                ok = fn() is not None
            except Exception:
                ok = False
            c.setEnabled(ok)
            if ok:
                c.setGraphicsEffect(None)
                c.setToolTip(f'{title}의 결과로 새 그래프를 만듭니다 (종류 → 축 배치 → 그룹).')
            else:
                eff = QGraphicsOpacityEffect(c)
                eff.setOpacity(0.4)
                c.setGraphicsEffect(eff)
                c.setToolTip(hint)

    def load_source(self, key):
        """A data chip: the tool's result becomes the data of the graph shown."""
        title, _tab, fn, hint = self._sources()[key]
        try:
            data = fn()
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, '그래프 편집', f'데이터를 만들지 못했습니다: {exc}')
            data = None
        if data is None:
            self.refresh_chips()
            self._status(hint)
            return None
        d = self.doc if self.doc.key is not None else self.new_doc()
        d.source, d.data_fn = key, fn
        if d.title.startswith('새 그래프'):
            d.title = title
            self._doc_item(d).setText(0, title)
        self.set_data(data)
        self.refresh_chips()
        self._changed_no_redraw()
        return d

    def start_wizard(self, key, run=True):
        """An analysis chip: 새 그래프 window (종류 → 축 배치 → 그룹) on the
        tool's result; 그래프 만들기 adds the graph to the sidebar."""
        title, _tab, fn, hint = self._sources()[key]
        try:
            data = fn()
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, '그래프 편집', f'데이터를 만들지 못했습니다: {exc}')
            return None
        if data is None or not data.tables:
            self.refresh_chips()
            QMessageBox.information(self, '새 그래프', hint)
            return None
        return self._wizard(title, data, key, fn, run)

    def start_wizard_csv(self, path=None, run=True):
        t = self.read_csv(path)
        if t is None:
            return None
        data = G.GraphData(t.name, [t], G.GraphSpec(), G.safe_name(t.name))
        return self._wizard(t.name, data, None, None, run, extra=[t])

    def _wizard(self, title, data, key, fn, run, extra=()):
        from .graph_editors import GraphWizard

        wz = GraphWizard(title, data, self)
        wz.finish = lambda: self.add_from_wizard(wz, title, data, key, fn, extra)
        if not run:
            return wz
        if wz.exec() == QDialog.DialogCode.Accepted:
            return wz.finish()
        return None

    def add_from_wizard(self, wz, title, data, key, fn, extra=()):
        """The wizard's graph becomes a new graph of the window."""
        n = sum(1 for d in self.docs if d.title.startswith(title)) + 1
        d = self.add_doc(self._free_key(), title if n == 1 else f'{title} {n}', fn, source=key)
        d.extra = list(extra)
        d.data = G.GraphData(data.title, list(data.tables), wz.spec.copy(), data.name, data.folder)
        d.spec, d.default_spec = wz.spec.copy(), wz.spec.copy()
        d.series_i = 0 if d.spec.series else -1
        self.show_doc(d)
        self.editor.setCurrentIndex(0)
        self._changed_no_redraw()
        if not self.isVisible():
            self.show()
        return d

    def open_scatter(self, x, y, group=''):
        """A matrix cell clicked: the XY graph of those two columns (with the
        regression line) as a new graph of the window."""
        src = self.doc
        sp = G.scatter_spec(self.spec, x, y, group)
        G.build_series(sp, self.tables())
        for s in sp.series:
            s.style = 'marker'
        d = self.add_doc(self._free_key(), sp.title, src.data_fn, src.source)
        d.extra = list(src.extra)
        d.data = G.GraphData(sp.title, list(src.data.tables) if src.data else [], sp.copy(),
                             *(() if src.data is None else (src.data.name, src.data.folder)))
        d.spec, d.default_spec = sp.copy(), sp.copy()
        d.series_i = 0 if d.spec.series else -1
        self.show_doc(d)
        self._changed_no_redraw()
        return d

    def group_summary(self, path=None, run=True):
        """여러 열 그룹 요약표: every number column (or the 상관 X 열) × group
        as one CSV (n, mean, SD, SEM, 95 % CI, median, IQR, tests)."""
        t = G.calc_table(self.spec, self.tables())
        if t is None:
            return None
        texts = G.text_columns(t)
        gc = G.group_column(self.spec)
        gcol = (self.spec.calc.group if self.spec.chart == 'corrcmp' else '') \
            or next((c for c in ('group', '그룹') if c in t.columns), '') or (gc if gc in texts else '')
        if not gcol:
            QMessageBox.information(self, '그룹 요약표', '표에 그룹 열이 없습니다.')
            return None
        cols = G.calc_columns(self.spec, t, 'x')
        out = G.group_summary_table(t, cols, gcol)
        if path is None and run:
            path, _ = QFileDialog.getSaveFileName(self, '그룹 요약표 저장', f'{_safe(self.doc.title)}_group_summary.csv',
                                                  'CSV (*.csv)')
        if path:
            G.write_csv(path, out)
            if hasattr(self.win, 'statusBar'):
                self.win.statusBar().showMessage(f'그룹 요약표 저장: {path}')
        return out

    def showEvent(self, ev):
        super().showEvent(ev)
        QTimer.singleShot(0, self.refresh_chips)

    # ---- building -----------------------------------------------------------------

    @staticmethod
    def _scroll(w) -> QScrollArea:
        s = QScrollArea()
        s.setWidgetResizable(True)
        s.setFrameShape(QScrollArea.Shape.NoFrame)
        s.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        s.setWidget(w)
        theme.unify(w)
        return s

    def _act(self, menu, text, fn, key=None, tip=None):
        a = QAction(text, self)
        if key:
            a.setShortcut(key)
        if tip:
            a.setToolTip(tip)
            a.setStatusTip(tip)
        a.triggered.connect(fn)
        menu.addAction(a)
        return a

    def _build_menus(self):
        mb = self.menuBar()
        m = mb.addMenu('파일')
        exp = getattr(self.win, 'export_dialog', None)
        if exp is not None:
            self._act(m, '내보내기…', lambda: exp('graph'), 'Ctrl+E',
                      '그래프(하나 또는 모두)와 그 데이터를 파일 › 내보내기 창에서 저장합니다.')
            m.addSeparator()
        self._act(m, '그래프 설정 저장 (JSON)…', self.save_settings,
                  tip='모든 스타일·축·글꼴·범례·글자 상자 설정을 파일로 저장합니다.')
        self._act(m, '그래프 설정 불러오기 (전체)…', lambda: self.load_settings(False))
        self._act(m, '그래프 스타일만 불러오기…', lambda: self.load_settings(True),
                  tip='데이터(시리즈의 열, 글자 상자)는 그대로 두고 글꼴·축·범례·크기와 시리즈 '
                      '스타일(순서대로)만 가져옵니다.')
        m.addSeparator()
        self._act(m, '닫기', self.close, QKeySequence.StandardKey.Close)

        m = mb.addMenu('편집')
        self._act(m, '새 그래프', lambda: self.new_doc(), QKeySequence.StandardKey.New)
        self._act(m, '그래프 복제', self.duplicate_doc)
        self._act(m, '그래프 이름 바꾸기…', self.rename_doc)
        m.addSeparator()
        self._act(m, '통계 · 유의성 표시…', self.open_stats)
        self._act(m, '여러 열 그룹 요약표 저장 (CSV)…', lambda: self.group_summary(),
                  tip='표의 숫자 열(상관 그래프는 가로 열)마다 그룹별 n · 평균 · SD · SEM · 95% CI · 중앙값 · '
                      'IQR과 그룹 사이 검정 p를 한 표로 저장합니다.')
        self._act(m, '글자 상자 추가', lambda: self.add_text())
        self._act(m, '범례 항목 추가', self.add_legend_item)
        self._act(m, '모든 위치·크기 자동 배치로', self.auto_layout,
                  tip='끌어 옮기거나 크기를 바꾼 그래프 영역·제목·축 이름을 자동 배치로 되돌립니다.')
        m.addSeparator()
        self._act(m, '처음 그래프로 되돌리기', self.reset_spec,
                  tip='도구에서 가져온 처음 그래프로 모든 설정을 되돌립니다.')
        self._act(m, '도구의 현재 결과 다시 불러오기', self.reload, 'Ctrl+R',
                  tip='도구의 최신 결과로 데이터를 바꿉니다. 열이 그대로면 고친 설정은 유지합니다.')
        m.addSeparator()
        a = self._act(m, '그래프 삭제…', self.confirm_remove_doc)
        a.setProperty('hig_destructive', True)

        m = mb.addMenu('보기')
        self._act(m, '확대', lambda: self.zoom_by(ZOOM_STEP), ']')
        self._act(m, '축소', lambda: self.zoom_by(1 / ZOOM_STEP), '[')
        self._act(m, '화면 맞춤', self.zoom_fit, 'Ctrl+0')

    # ---- inspector pieces ----

    @staticmethod
    def _card(title='', *rows) -> QGroupBox:
        box = QGroupBox(title)
        f = QFormLayout(box)
        for r in rows:
            if isinstance(r, tuple):
                f.addRow(*r)
            else:
                f.addRow(r)
        return box

    def _axis(self):
        """The axis edited in 모양 › 축 (X / Y chips; clicking an axis name picks it)."""
        return getattr(self.spec, self.look_axis)

    def _all(self):
        return _AllSeries(self.spec) if self.spec.series else None

    def _font_rows(self, fo):
        return [('크기', self.b.bind(_dspin(2, 72, 0.5, 1, ' pt'), fo, 'size')),
                ('색', self.b.bind(ColorButton(), fo, 'color')),
                self.b.bind(QCheckBox('굵게'), fo, 'bold'), self.b.bind(QCheckBox('기울임'), fo, 'italic')]

    def _unit_combo(self, ax):
        unit = QComboBox()
        unit.setEditable(True)
        unit.addItems(['', 's', 'min', 'h', 'ms', 'µm', 'nm', 'mm', 'px', '%', 'a.u.', 'µm²'])
        unit.setToolTip('축 이름 뒤 괄호 안에 붙는 단위')
        return self.b.bind(unit, ax, 'unit')

    def _conv_combo(self, which):
        conv = QComboBox()
        conv.setToolTip('자주 쓰는 단위 바꾸기: 배율과 단위를 함께 정합니다.')
        for text, k, u in (('고르기…', None, None), ('그대로 (× 1)', 1.0, None), ('s → min', 1 / 60, 'min'),
                           ('min → s', 60.0, 's'), ('s → ms', 1000.0, 'ms'), ('min → h', 1 / 60, 'h'),
                           ('0–1 → %', 100.0, '%'), ('% → 0–1', 0.01, ''), ('µm → nm', 1000.0, 'nm'),
                           ('nm → µm', 0.001, 'µm')):
            conv.addItem(text, (k, u))
        conv.activated.connect(lambda i, c=conv: self._convert_unit(which, c))
        return conv

    def _build_data_tab(self) -> QWidget:
        """데이터: 그래프 종류, 축 배치, 그룹 (the wizard's steps, editable later)."""
        from .graph_editors import GroupEditor, KindPicker, MappingEditor

        w = QWidget()
        lay = QVBoxLayout(w)
        self.kinds = KindPicker(4, big=False)
        self.kinds.picked.connect(self._kind_picked)
        kbox = QGroupBox('그래프 종류')
        kl = QVBoxLayout(kbox)
        kl.addWidget(self.kinds)
        lay.addWidget(kbox)
        # the chart combo stays as the one place the chart is set (also for the self-test)
        self.chart = _combo(G.CHARTS)
        self.chart.setVisible(False)
        self.chart.currentIndexChanged.connect(lambda _i: self._kind_picked(self.chart.currentData()))
        lay.addWidget(self.chart)
        get, tabs = (lambda: self.spec if self.doc.key is not None else None), self.tables
        self.mapping_ed = MappingEditor(get, tabs, self._data_changed)
        self.mapping_ed.setTitle('축 배치')
        lay.addWidget(self.mapping_ed)
        self.groups_ed = GroupEditor(get, tabs, self._data_changed)
        self.groups_ed.setTitle('그룹')
        lay.addWidget(self.groups_ed)
        lay.addStretch()
        return w

    @staticmethod
    def _head(text) -> QLabel:
        lab = QLabel(text)
        theme.text_style(lab, 'headline')
        return lab

    def _build_look_tab(self) -> QWidget:
        """모양: 색, 점 · 선, 축, 제목, 범례, 글꼴, 그림, 글자 상자. Clicking a
        thing on the graph brings its card into view."""
        from . import hig_widgets
        from .figure import installed_families

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(_hint('그래프에서 제목, 축 이름, 범례, 점이나 막대, 글자 상자를 누르면 그 항목으로 바로 갑니다.'))
        sp = lambda: self.spec  # noqa: E731
        self.look_cards = {}
        # 색: one row per series
        self.color_box = QGroupBox('색')
        self.color_form = QFormLayout(self.color_box)
        lay.addWidget(self.color_box)
        self.look_cards['series'] = self.color_box
        # 점 · 선 (all series)
        al = self._all
        self.style_box = self._card('점 · 선',
                                    ('그리기 방식', self.b.bind(_combo(G.STYLES), al, 'style', data=True)),
                                    ('선 모양', self.b.bind(_combo(G.LINE_STYLES), al, 'line_style', data=True)),
                                    ('선 굵기', self.b.bind(_dspin(0, 20, 0.1, 2, ' pt'), al, 'line_width')),
                                    ('점 모양', self.b.bind(_combo(G.MARKERS), al, 'marker', data=True)),
                                    ('점 크기', self.b.bind(_dspin(0, 40, 0.5, 1, ' pt'), al, 'marker_size')),
                                    self.b.bind(QCheckBox('점 속 채우기 (끄면 속이 빈 점)'), al, 'marker_fill'),
                                    ('불투명도', self.b.bind(_dspin(0, 1, 0.05), al, 'alpha')),
                                    ('에러바 모양', self.b.bind(_combo(G.ERR_STYLES), al, 'err_style', data=True)),
                                    ('에러바 굵기', self.b.bind(_dspin(0, 10, 0.1, 2, ' pt'), al, 'err_width')),
                                    ('에러바 캡', self.b.bind(_dspin(0, 20, 0.5, 1, ' pt'), al, 'capsize')))
        self.style_rows = {}
        f = self.style_box.layout()
        for r in range(f.rowCount()):
            it = f.itemAt(r, QFormLayout.ItemRole.LabelRole)
            if it is not None and it.widget() is not None:
                self.style_rows[it.widget().text()] = r
        lay.addWidget(self.style_box)
        self.cat_box = self._card('막대 · 점 그림 · 상자 · 바이올린',
                                  self.b.bind(QCheckBox('개별 값을 점으로 표시'), sp, 'bar_points'),
                                  ('폭', self.b.bind(_dspin(0.1, 1.0, 0.05), sp, 'bar_width')),
                                  ('채움 투명도', self.b.bind(_dspin(0, 1, 0.05), sp, 'bar_alpha')),
                                  ('점 흩뿌림', self.b.bind(_dspin(0, 0.5, 0.05), sp, 'point_jitter')))
        lay.addWidget(self.cat_box)
        bins = QSpinBox()
        bins.setRange(0, 1000)
        bins.setSpecialValueText('자동')
        self.hist_box = self._card('히스토그램', ('구간 수', theme.auto_value(self.b.bind(bins, sp, 'hist_bins'), 20)),
                                   self.b.bind(QCheckBox('밀도 (넓이 = 1)'), sp, 'hist_density'),
                                   self.b.bind(QCheckBox('채우기'), sp, 'hist_fill'))
        lay.addWidget(self.hist_box)
        cm = QComboBox()
        cm.addItems(G.CMAPS)
        self.heat_box = self._card('히트맵', ('색 지도', self.b.bind(cm, sp, 'cmap')),
                                   self.b.bind(QCheckBox('로그 색 눈금'), sp, 'cmap_log'),
                                   self.b.bind(QCheckBox('색 막대 표시'), sp, 'colorbar'))
        lay.addWidget(self.heat_box)
        # 축: X / Y chips, one card per axis
        self.look_axis = 'x'
        sw = QWidget()
        sh = QHBoxLayout(sw)
        sh.setContentsMargins(0, 0, 0, 0)
        sh.setSpacing(6)
        self.axis_chips = {}
        for k, t in (('x', 'X 축'), ('y', 'Y 축')):
            c = hig_widgets.Chip(t, False)
            c.setAutoExclusive(True)
            c.clicked.connect(lambda _=False, k=k: self.pick_axis(k))
            sh.addWidget(c)
            self.axis_chips[k] = c
        sh.addStretch()
        axis_box = QGroupBox('축')
        av = QVBoxLayout(axis_box)
        av.addWidget(sw)
        self.range_edits = {}
        self.axis_forms = {}
        for which in ('x', 'y'):
            a = (lambda which=which: getattr(self.spec, which))
            form = QWidget()
            fl = QFormLayout(form)
            fl.setContentsMargins(0, 0, 0, 0)
            auto = self.b.bind(QCheckBox('범위 자동'), a, 'auto_range')
            auto.setToolTip('데이터에 맞춥니다. 칸에는 지금 쓰는 범위가 보입니다.')
            auto.toggled.connect(lambda on, w_=which: self._auto_toggled(w_, 'range', on))
            lo, hi = self.b.bind(FloatEdit(), a, 'lo'), self.b.bind(FloatEdit(), a, 'hi')
            sauto = self.b.bind(QCheckBox('눈금 간격 자동'), a, 'auto_step')
            sauto.toggled.connect(lambda on, w_=which: self._auto_toggled(w_, 'step', on))
            step = self.b.bind(FloatEdit(), a, 'step')
            self.range_edits[which] = (lo, hi, auto, step, sauto)
            for r in (('이름', self.b.bind(QLineEdit(), a, 'label')), ('단위', self._unit_combo(a)),
                      ('단위 바꾸기', self._conv_combo(which)), auto, ('최소', lo), ('최대', hi), sauto,
                      ('눈금 간격', step), self.b.bind(QCheckBox('로그 눈금'), a, 'log'),
                      self.b.bind(QCheckBox('보조 눈금'), a, 'minor'),
                      ('눈금 방향', self.b.bind(_combo(G.TICK_DIRS), a, 'tick_dir', data=True)),
                      ('눈금 글자 회전', self.b.bind(_dspin(-90, 90, 15, 0, '°'), a, 'rotation')),
                      ('값 배율 (×)', self.b.bind(FloatEdit(), a, 'scale'))):
                fl.addRow(*r) if isinstance(r, tuple) else fl.addRow(r)
            av.addWidget(form)
            self.axis_forms[which] = form
        lay.addWidget(axis_box)
        self.look_cards['axis'] = axis_box
        # 제목
        title = self._card('제목', ('글자', self.b.bind(QLineEdit(), sp, 'title')),
                           *self._font_rows(lambda: self.spec.title_font))
        lay.addWidget(title)
        self.look_cards['title'] = title
        # 범례 (+ its own entries)
        ncol = QSpinBox()
        ncol.setRange(1, 10)
        self.item_list = QListWidget()
        self.item_list.setMaximumHeight(80)
        self.item_list.currentRowChanged.connect(self._item_picked)
        add, rm = QPushButton('항목 추가'), theme.destructive(QPushButton('삭제…'))
        add.clicked.connect(self.add_legend_item)
        rm.setToolTip('선택한 범례 항목 삭제')
        rm.clicked.connect(lambda: self.cur_item() is not None and theme.confirm_destructive(
            self, '범례', '선택한 범례 항목을 삭제할까요?', '삭제') and self.del_legend_item())
        ci = self.cur_item
        it_label = self.b.bind(QLineEdit(), ci, 'label')
        it_label.textChanged.connect(lambda _: self._relabel_items())
        legend = self._card('범례', self.b.bind(QCheckBox('범례 표시'), sp, 'legend_show'),
                            ('위치', self.b.bind(_combo(G.LEGEND_LOCS), sp, 'legend_loc', data=True)),
                            ('범례 제목', self.b.bind(QLineEdit(), sp, 'legend_title')),
                            ('열 수', self.b.bind(ncol, sp, 'legend_ncol')),
                            self.b.bind(QCheckBox('테두리'), sp, 'legend_frame'),
                            *self._font_rows(lambda: self.spec.legend_font),
                            _hint('범례를 그래프 위에서 끌면 ‘직접 놓기’가 됩니다. 이름은 범례에서 두 번 클릭해 고칩니다. '
                                  '아래는 시리즈 말고 직접 넣는 항목입니다.'),
                            self.item_list, _row(add, rm), ('항목 이름', it_label),
                            ('항목 색', self.b.bind(ColorButton(), ci, 'color')),
                            ('항목 점 모양', self.b.bind(_combo(G.MARKERS), ci, 'marker', data=True)))
        lay.addWidget(legend)
        self.look_cards['legend'] = legend
        # 글꼴
        fam = QComboBox()
        fam.addItem('')
        fam.addItems(installed_families())
        fam.setToolTip('비우면 기본 글꼴 (한글은 자동으로 한글 글꼴)')
        tick = lambda: self.spec.tick_font  # noqa: E731
        lab = lambda: self.spec.label_font  # noqa: E731
        fonts = self._card('글꼴', ('글꼴', self.b.bind(fam, sp, 'font_family')),
                           ('축 이름 크기', self.b.bind(_dspin(2, 72, 0.5, 1, ' pt'), lab, 'size')),
                           self.b.bind(QCheckBox('축 이름 굵게'), lab, 'bold'),
                           ('눈금 글자 크기', self.b.bind(_dspin(2, 72, 0.5, 1, ' pt'), tick, 'size')),
                           ('글자 · 축선 색', self.b.bind(ColorButton(), tick, 'color')))
        lay.addWidget(fonts)
        self.look_cards['font'] = fonts
        # 그림
        self.w_in = self.b.bind(_dspin(1, 40, 0.1, 2, ' in'), sp, 'width_in')
        self.h_in = self.b.bind(_dspin(1, 40, 0.1, 2, ' in'), sp, 'height_in')
        dpi = QSpinBox()
        dpi.setRange(50, 1200)
        dpi.setSuffix(' dpi')
        b = QPushButton('모두 자동 배치로')
        b.setToolTip('끌어 옮기거나 크기를 바꾼 그래프 영역 · 제목 · 축 이름을 자동 배치로 되돌립니다.')
        b.clicked.connect(self.auto_layout)
        lay.addWidget(self._card('그림', ('가로', self.w_in), ('세로', self.h_in),
                                 ('해상도', self.b.bind(dpi, sp, 'dpi')),
                                 ('배경', self.b.bind(ColorButton(), sp, 'background')),
                                 self.b.bind(QCheckBox('위 축선'), sp, 'spine_top'),
                                 self.b.bind(QCheckBox('오른쪽 축선'), sp, 'spine_right'),
                                 ('축선 · 눈금 굵기', self.b.bind(_dspin(0, 5, 0.1, 2, ' pt'), sp, 'spine_width')),
                                 self.b.bind(QCheckBox('격자'), sp, 'grid'),
                                 ('격자 색', self.b.bind(ColorButton(), sp, 'grid_color')),
                                 self.b.bind(QCheckBox('그래프 영역 자동 배치'), sp, 'plot_auto'), b))
        # 글자 상자
        self.text_list = QListWidget()
        self.text_list.setMaximumHeight(90)
        self.text_list.currentRowChanged.connect(self._text_picked)
        add, rm = QPushButton('글자 상자 추가'), theme.destructive(QPushButton('삭제…'))
        add.clicked.connect(lambda: self.add_text())
        rm.setToolTip('선택한 글자 상자 삭제')
        rm.clicked.connect(lambda: self.cur_text() is not None and theme.confirm_destructive(
            self, '글자 상자', '선택한 글자 상자를 삭제할까요?', '삭제') and self.del_text())
        ct = self.cur_text
        te = QPlainTextEdit()
        te.setMaximumHeight(60)
        self.b.bind(te, ct, 'text')
        te.textChanged.connect(self._relabel_texts)
        texts = self._card('글자 상자', self.text_list, _row(add, rm), ('글자', te),
                           ('크기', self.b.bind(_dspin(2, 72, 0.5, 1, ' pt'), ct, 'size')),
                           ('색', self.b.bind(ColorButton(), ct, 'color')),
                           self.b.bind(QCheckBox('굵게'), ct, 'bold'),
                           self.b.bind(QCheckBox('테두리'), ct, 'frame'),
                           ('정렬', self.b.bind(_combo(G.ALIGNS), ct, 'align', data=True)),
                           _hint('그래프에서 오른쪽 클릭 › 여기에 글자 상자 추가. 끌어 옮기고 두 번 클릭해 고칩니다.'))
        lay.addWidget(texts)
        self.look_cards['text'] = texts
        lay.addStretch()
        self.pick_axis('x')
        return w

    def _build_stats_tab(self) -> QWidget:
        """통계: 유의성 표시 on / off, the test and the marks (StatsEditor),
        the full window with the data check."""
        from .graph_editors import StatsEditor

        w = QWidget()
        lay = QVBoxLayout(w)
        sp = lambda: self.spec  # noqa: E731
        st = lambda: self.spec.stats  # noqa: E731
        self.stats_on = self.b.bind(QCheckBox('자동 유의성 표시'), st, 'on')
        self.stats_on.setText('유의성 표시')
        theme.switch(self.stats_on)
        self.stats_on.toggled.connect(lambda on: (self._stats_switched(on)))
        open_b = theme.prominent(QPushButton('통계 창 열기…'))
        open_b.setToolTip('데이터 확인, 추천 검정, 비교할 쌍, 표시를 미리보기와 함께 정합니다.')
        open_b.clicked.connect(self.open_stats)
        lay.addWidget(self._card('', self.stats_on, open_b,
                                 _hint('막대 · 점 그림 · 상자 · 바이올린 그래프의 범주끼리 비교해 괄호와 별표(*)를 '
                                       '그립니다. 표시 모양의 초기값은 설정 › 그래프 · 유의성 표시 초기값에서 정합니다.')))
        del sp
        self.stats_ed = StatsEditor(lambda: self.spec if self.doc.key is not None else None, self.tables,
                                    self._stats_changed, full=False)
        lay.addWidget(self.stats_ed)
        from .graph_editors import RegressionEditor

        self.reg_ed = RegressionEditor(lambda: self.spec if self.doc.key is not None else None, self.tables,
                                       self._reg_changed)
        lay.addWidget(self.reg_ed)
        lay.addStretch()
        return w

    def _reg_changed(self):
        self._changed()
        self.render()

    # ---- inspector <-> graph ----

    def pick_axis(self, which):
        self.look_axis = which
        for k, c in self.axis_chips.items():
            c.setChecked(k == which)
        for k, f in self.axis_forms.items():
            f.setVisible(k == which)

    def _show_selection(self):
        """A thing clicked on the graph: its card in 모양 comes into view."""
        k = self.sel[0] if self.sel else None
        card = None
        if k in ('xlabel', 'ylabel'):
            self.pick_axis('y' if k == 'ylabel' else 'x')
            card = self.look_cards['axis']
        elif k in ('title', 'legend', 'series', 'text'):
            card = self.look_cards[k]
        self.b.sync()
        if card is not None and self.isVisible():
            self.editor.setCurrentIndex(1)
            sc = self.editor.widget(1)
            QTimer.singleShot(0, lambda: sc.ensureWidgetVisible(card, 0, 40))
            if k == 'series':
                row = self._color_rows.get(self._series_i)
                if row is not None:
                    QTimer.singleShot(0, lambda: row.setFocus())

    def _kind_picked(self, k):
        if not k or k == self.spec.chart:
            self.kinds.set_kind(self.spec.chart)
            return
        sp = self.spec
        old = sp.chart
        sp.chart = k
        m = sp.mapping
        if m.on and k in G.CATEGORY_CHARTS and old not in G.CATEGORY_CHARTS and not (m.x_cat or m.y_cat):
            t = self.tables().get(m.table)
            texts = G.text_columns(t) if t is not None else []
            if texts:
                m.x, m.x_cat = texts[0], True
        if k in G.CATEGORY_CHARTS and m.x_cat and m.y_cat:
            m.y_cat = False
        self._data_changed()

    def _data_changed(self):
        """축 배치 / 그룹 / 종류 changed: make the series again and redraw."""
        if self.doc.key is None:
            return
        if self.spec.mapping.on:
            G.build_series(self.spec, self.tables())
        self._series_i = min(max(self._series_i, 0), len(self.spec.series) - 1)
        self._fill_lists()
        self.sync()
        self._changed()
        self.render()

    def _stats_switched(self, on):
        if self.b.busy:
            return
        self.stats_ed.refresh()

    def _stats_changed(self):
        self.spec.stats.on = True
        self.b.sync()
        self._changed()

    def open_stats(self, run=True):
        """통계 · 유의성 표시 window; 적용 writes the settings into the graph."""
        from .graph_editors import StatsDialog

        if self.doc.key is None:
            return None
        if self.spec.chart not in G.CATEGORY_CHARTS:
            QMessageBox.information(self, '통계', '유의성 표시는 막대 · 점 그림 · 상자 · 바이올린 그래프에서 씁니다. '
                                    '‘데이터’ 탭에서 그래프 종류를 바꾸세요.')
            return None
        d = StatsDialog(self.spec, self.tables(), self)
        if not run:
            return d
        if d.exec() == QDialog.DialogCode.Accepted:
            self.spec.stats = d.spec.stats
            self.sync()
            self._changed()
        return d

    # ---- current selections ----------------------------------------------------------------

    def cur_series(self) -> G.Series | None:
        i = self._series_i
        return self.spec.series[i] if 0 <= i < len(self.spec.series) else None

    def cur_text(self) -> G.TextBox | None:
        i = self._text_i
        return self.spec.texts[i] if 0 <= i < len(self.spec.texts) else None

    def cur_item(self) -> G.LegendItem | None:
        i = self._item_i
        return self.spec.legend_items[i] if 0 <= i < len(self.spec.legend_items) else None

    # ---- data in / out -------------------------------------------------------------------

    def tables(self) -> dict:
        return {t.name: t for t in (self.data.tables if self.data else [])}

    def state(self) -> dict:
        """Settings plus the tables brought in from other analyses / CSV (for projects)."""
        d = self.spec.to_dict()
        d['_title'] = self.doc.title
        if self.doc.source and str(self.doc.key).startswith('free'):
            d['_source'] = self.doc.source  # made with 새 그래프 from a tool: data again from it
        d['_tables'] = [{'name': t.name, 'columns': list(t.columns), 'rows': [list(r) for r in t.rows],
                         'labels': dict(t.labels), 'column_sets': dict(t.column_sets)}
                        for t in self.extra]
        return d

    def _with_extra(self, data):
        have = {t.name for t in data.tables}
        data.tables = list(data.tables) + [t for t in self.extra if t.name not in have]
        return data

    def set_data(self, data: G.GraphData, keep_spec=False):
        data = self._with_extra(data)
        self.data = data
        self.setWindowTitle(f'그래프 편집 · {data.title}')
        self.default_spec = data.spec.copy()
        if keep_spec and self._spec_fits(self.spec, data):
            pass
        elif keep_spec:
            self.spec = G.apply_style(data.spec, self.spec)
        else:
            self.spec = data.spec.copy()
            from .graph_editors import apply_stats_defaults

            apply_stats_defaults(self.spec)
        if self.spec.mapping.on:
            G.build_series(self.spec, self.tables())
        self._series_i = 0 if self.spec.series else -1
        self._text_i = 0 if self.spec.texts else -1
        self._item_i = 0 if self.spec.legend_items else -1
        self._fill_lists()
        self.sync()
        self.render()

    @staticmethod
    def _spec_fits(spec, data) -> bool:
        tabs = {t.name: t for t in data.tables}
        for s in spec.series:
            t = tabs.get(s.table)
            if t is None or (s.y and s.y not in t.columns) or (s.x and s.x not in t.columns):
                return False
        return bool(spec.series)

    def use_spec(self, d: dict):
        """Settings saved in a project: as they were when they still fit the
        data, else only their style."""
        tabs = d.get('_tables') if isinstance(d, dict) else None
        if tabs:
            self.extra = [G.Table(str(t.get('name', '')), list(t.get('columns', [])), list(t.get('rows', [])),
                                  dict(t.get('labels') or {}), dict(t.get('column_sets') or {}))
                          for t in tabs if isinstance(t, dict)]
            if self.data is not None:
                self._with_extra(self.data)
        spec = G.GraphSpec.from_dict(d)
        if spec.mapping.on and self.data is not None:
            G.build_series(spec, self.tables())
        elif self.data is not None and not self._spec_fits(spec, self.data):
            spec = G.apply_style(self.data.spec, spec)
        self.spec = spec
        self._series_i = 0 if spec.series else -1
        self._text_i = 0 if spec.texts else -1
        self._item_i = 0 if spec.legend_items else -1
        self._fill_lists()
        self.sync()
        self.render()

    def reload(self):
        try:
            data = self.data_fn()
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, '다시 불러오기', f'결과를 가져오지 못했습니다: {exc}')
            return
        if data is None:
            QMessageBox.information(self, '다시 불러오기', '탭에 그릴 결과가 없습니다.')
            return
        self.set_data(data, keep_spec=True)
        self._status('탭의 현재 결과를 다시 불러왔습니다.')

    def reset_spec(self):
        self.spec = self.default_spec.copy()
        self._series_i = 0 if self.spec.series else -1
        self._text_i = 0 if self.spec.texts else -1
        self._item_i = 0 if self.spec.legend_items else -1
        self._fill_lists()
        self.sync()
        self.render()

    # ---- widgets <-> spec -------------------------------------------------------------------

    def _changed(self):
        self._timer.start()
        set_dirty = getattr(self.win, 'set_dirty', None)
        if set_dirty is not None:
            set_dirty()

    def sync(self):
        self.b.sync()
        if self.doc.key is not None:
            self.kinds.set_kind(self.spec.chart)
            self.b.busy = True
            i = self.chart.findData(self.spec.chart)
            self.chart.blockSignals(True)
            self.chart.setCurrentIndex(max(i, 0))
            self.chart.blockSignals(False)
            self.b.busy = False
        self.mapping_ed.refresh()
        self.groups_ed.refresh()
        self.stats_ed.refresh()
        self.reg_ed.refresh()
        self._chart_changed(sync=False)
        self._show_used()

    def _chart_changed(self, sync=True):
        c = self.spec.chart
        self.mapping_ed.setTitle('상관 계산' if c in G.CORR_CHARTS else '축 배치')
        self.cat_box.setVisible(c in G.CATEGORY_CHARTS)
        self.hist_box.setVisible(c == 'hist')
        self.heat_box.setVisible(c == 'heatmap')
        xy = c == 'xy'
        f = self.style_box.layout()
        for name in ('그리기 방식', '선 모양'):
            r = self.style_rows.get(name)
            if r is not None:
                f.setRowVisible(r, xy)
        if sync:
            self._fill_table_choices()

    def _fill_lists(self):
        """The colour rows (one per series) and the text / legend item lists."""
        f = self.color_form
        while f.rowCount():
            f.removeRow(0)
        self._color_rows = {}
        for i, s in enumerate(self.spec.series):
            if not s.visible and s.auto:
                continue
            btn = ColorButton()
            btn.setColor(s.color)
            btn.changed.connect(lambda v, i=i: self._set_color(i, v))
            box = QCheckBox()
            box.setChecked(s.visible)
            box.setToolTip('그래프에 표시')
            box.toggled.connect(lambda on, i=i: self._set_visible(i, on))
            w = btn
            if not s.auto:
                w = QWidget()
                h = QHBoxLayout(w)
                h.setContentsMargins(0, 0, 0, 0)
                h.addWidget(box)
                h.addWidget(btn)
            f.addRow(G._label(s, i), w)
            self._color_rows[i] = btn
        if not self.spec.series:
            f.addRow(_hint('시리즈가 없습니다.'))
        from .graph_editors import _align_end

        _align_end(f)
        for lst, items, i in ((self.text_list, self.spec.texts, self._text_i),
                              (self.item_list, self.spec.legend_items, self._item_i)):
            lst.blockSignals(True)
            lst.clear()
            for x in items:
                lst.addItem((x.text if isinstance(x, G.TextBox) else x.label).split('\n')[0] or '(빈 글자)')
            lst.setCurrentRow(i)
            lst.blockSignals(False)
        self._fill_table_choices()

    def _set_color(self, i, v):
        if 0 <= i < len(self.spec.series):
            self.spec.series[i].color = v
            self._changed()

    def _set_visible(self, i, on):
        if 0 <= i < len(self.spec.series):
            self.spec.series[i].visible = bool(on)
            self._changed()

    def _relabel_texts(self):
        t = self.cur_text()
        if t is not None and self._text_i < self.text_list.count():
            self.text_list.item(self._text_i).setText(t.text.split('\n')[0] or '(빈 글자)')

    def _relabel_items(self):
        t = self.cur_item()
        if t is not None and self._item_i < self.item_list.count():
            self.item_list.item(self._item_i).setText(t.label or '(빈 이름)')

    def _text_picked(self, i):
        self._text_i = i
        if i >= 0:
            self.sel = ('text', i)
        self.b.sync()
        self._draw_selection()

    def _item_picked(self, i):
        self._item_i = i
        self.b.sync()

    def _auto_toggled(self, which, what, on):
        """Switching 자동 off keeps the values in use (shown in the fields)."""
        if self.b.busy or on:
            return
        lo, hi, _, step, _ = self.range_edits[which]
        a = getattr(self.spec, which)
        if what == 'range' and np.isfinite(lo.value()) and np.isfinite(hi.value()):
            a.lo, a.hi = lo.value(), hi.value()
        elif what == 'step' and np.isfinite(step.value()) and step.value() > 0:
            a.step = step.value()
        self._changed()

    def _show_used(self):
        """Axis fields show the range and tick spacing in use, also while 자동."""
        ax = self.art.get('ax')
        if ax is None:
            return
        for which in ('x', 'y'):
            lo, hi, auto, step, sauto = self.range_edits[which]
            a = getattr(self.spec, which)
            lim = ax.get_xlim() if which == 'x' else ax.get_ylim()
            locs = (ax.xaxis if which == 'x' else ax.yaxis).get_majorticklocs()
            lo.setEnabled(not a.auto_range)
            hi.setEnabled(not a.auto_range)
            step.setEnabled(not a.auto_step)
            if a.auto_range:
                lo.setValue(min(lim))
                hi.setValue(max(lim))
            if a.auto_step and len(locs) > 1 and not a.log:
                step.setValue(float(np.median(np.diff(locs))))

    # ---- series / texts / legend items ---------------------------------------------------------

    def add_series(self):
        base = self.cur_series()
        s = G.Series(**asdict(base)) if base is not None else G.Series()
        if base is None and self.data and self.data.tables:
            t = self.data.tables[0]
            nums = t.numeric_columns()
            s.table = t.name
            s.x = nums[0] if nums else ''
            s.y = nums[1] if len(nums) > 1 else (nums[0] if nums else '')
        s.color = G.PALETTE[len(self.spec.series) % len(G.PALETTE)]
        s.label = ''
        self.spec.series.append(s)
        self._series_i = len(self.spec.series) - 1
        self._after_list_change()

    def dup_series(self):
        s = self.cur_series()
        if s is None:
            return
        d = G.Series(**asdict(s))
        d.label = (s.label or s.y) + ' (복제)'
        self.spec.series.insert(self._series_i + 1, d)
        self._series_i += 1
        self._after_list_change()

    def del_series(self):
        if self.cur_series() is None:
            return
        del self.spec.series[self._series_i]
        self._series_i = min(self._series_i, len(self.spec.series) - 1)
        self._after_list_change()

    def move_series(self, d):
        i, j = self._series_i, self._series_i + d
        if self.cur_series() is None or not 0 <= j < len(self.spec.series):
            return
        s = self.spec.series
        s[i], s[j] = s[j], s[i]
        self._series_i = j
        self._after_list_change()

    def split_series(self):
        s = self.cur_series()
        t = self.tables().get(s.table) if s is not None else None
        if t is None:
            return
        cols = [c for c in t.columns if 1 < len(set(G._text(v) for v in t.values(c))) <= 50]
        if not cols:
            QMessageBox.information(self, '값마다 나누기', '나눌 수 있는 열(값이 2–50가지)이 없습니다.')
            return
        pick = 'group' if 'group' in cols else cols[0]
        col, ok = QInputDialog.getItem(self, '값마다 나누기', '이 열의 값마다 시리즈를 하나씩 만듭니다:',
                                       cols, cols.index(pick), False)
        if not ok:
            return
        vals = list(dict.fromkeys(G._text(v) for v in t.values(col)))
        new = []
        for k, v in enumerate(vals):
            d = G.Series(**asdict(s))
            d.where, d.equals, d.label = col, v, v
            d.color = G.PALETTE[(k + 1) % len(G.PALETTE)] if k else s.color
            new.append(d)
        i = self._series_i
        self.spec.series[i:i + 1] = new
        self._after_list_change()

    def style_to_all(self):
        s = self.cur_series()
        if s is None:
            return
        for o in self.spec.series:
            for k in G.STYLE_FIELDS:
                if k != 'color':
                    setattr(o, k, getattr(s, k))
        self._changed()

    def add_text(self, x=0.05, y=0.9, text=None):
        if text is None:
            text, ok = QInputDialog.getMultiLineText(self, '글자 상자 추가', '글자:', 'Text')
            if not ok or not text:
                return
        self.spec.texts.append(G.TextBox(text=text, x=float(x), y=float(y),
                                         size=self.spec.label_font.size))
        self._text_i = len(self.spec.texts) - 1
        self.sel = ('text', self._text_i)
        self._after_list_change()
        self.editor.setCurrentIndex(1)

    def del_text(self):
        if self.cur_text() is None:
            return
        del self.spec.texts[self._text_i]
        self._text_i = min(self._text_i, len(self.spec.texts) - 1)
        self._after_list_change()

    def add_legend_item(self):
        self.spec.legend_items.append(G.LegendItem(label='항목', color=G.PALETTE[
            (len(self.spec.series) + len(self.spec.legend_items)) % len(G.PALETTE)]))
        self.spec.legend_show = True
        self._item_i = len(self.spec.legend_items) - 1
        self._after_list_change()
        self.editor.setCurrentIndex(1)

    def del_legend_item(self):
        if self.cur_item() is None:
            return
        del self.spec.legend_items[self._item_i]
        self._item_i = min(self._item_i, len(self.spec.legend_items) - 1)
        self._after_list_change()

    def _after_list_change(self):
        self._fill_lists()
        self.sync()
        self._changed()

    # ---- drawing --------------------------------------------------------------------------

    def eventFilter(self, obj, ev):
        if obj is self.holder.viewport() and ev.type() == ev.Type.Resize:
            QTimer.singleShot(0, self._fit)
        return False

    def _base_dpi(self) -> float:
        s = self.spec
        vp = self.holder.viewport()
        aw, ah = max(vp.width() - 16, 50), max(vp.height() - 16, 50)
        return max(10.0, min(aw / s.width_in, ah / s.height_in))

    def _fit(self) -> bool:
        """Show the figure at its saved proportions: as large as the pane allows
        times the zoom."""
        s = self.spec
        d = self._base_dpi() * self.zoom
        w, h = int(round(s.width_in * d)), int(round(s.height_in * d))
        self.zoom_label.setText(f'{self.zoom * 100:.0f} %')
        if (w, h) == (self.canvas.width(), self.canvas.height()) and abs(self.fig._original_dpi - d) < 0.01:
            return False
        r = self.canvas.device_pixel_ratio or 1
        self.fig._original_dpi = d
        self.fig.set_dpi(d * r)
        self.canvas.setFixedSize(w, h)
        self.fig.set_size_inches(s.width_in, s.height_in, forward=False)
        self.canvas.draw_idle()
        return True

    def zoom_by(self, f, anchor=None):
        """Zoom the preview; anchor (canvas px) stays under the mouse."""
        z = min(20.0, max(0.1, self.zoom * f))
        if abs(z - self.zoom) < 1e-9:
            return
        hs, vs = self.holder.horizontalScrollBar(), self.holder.verticalScrollBar()
        if anchor is None:
            anchor = (self.canvas.width() / 2, self.canvas.height() / 2)
        fx = anchor[0] / max(self.canvas.width(), 1)
        fy = anchor[1] / max(self.canvas.height(), 1)
        vx, vy = anchor[0] - hs.value(), anchor[1] - vs.value()  # where it is in the viewport
        self.zoom = z
        if self._fit():
            self.render()
        hs.setValue(int(fx * self.canvas.width() - vx))
        vs.setValue(int(fy * self.canvas.height() - vy))

    def zoom_fit(self):
        self.zoom = 1.0
        if self._fit():
            self.render()

    def _follow_scale(self):
        """A new value scale (unit change) also converts a manual range / tick
        spacing, so the axis shows the same part of the data."""
        for which in ('x', 'y'):
            a = getattr(self.spec, which)
            old = self._scales.get(which)
            self._scales[which] = (id(a), a.scale)
            if old is None or old[0] != id(a) or old[1] == a.scale or not old[1]:
                continue
            k = a.scale / old[1]
            if not a.auto_range:
                a.lo, a.hi = a.lo * k, a.hi * k
            if not a.auto_step:
                a.step = abs(a.step * k)

    def render(self):
        if self.data is None:
            return
        self._follow_scale()
        self._fit()
        self._overlay = []
        try:
            self.art = G.draw(self.fig, self.spec, self.tables())
        except Exception as exc:
            traceback.print_exc()
            self.fig.clear()
            self.fig.text(0.5, 0.5, f'그릴 수 없습니다: {exc}', ha='center', va='center', color='#b35c00',
                          wrap=True)
            self.art = {}
        try:
            self.canvas.draw()  # lay out, so the selection box knows where things are
        except Exception:
            traceback.print_exc()
        self._draw_selection()
        self.b.busy = True
        try:
            ax = self.art.get('ax')
            if self.spec.plot_auto and ax is not None:  # unchecking 자동 keeps it where it is now
                for k, v in zip(('plot_x', 'plot_y', 'plot_w', 'plot_h'), ax.get_position().bounds):
                    setattr(self.spec, k, float(v))
            self._show_used()
        finally:
            self.b.busy = False
        self.fill_table()

    # ---- objects on the graph: select, move, resize ------------------------------------------------

    def _artist(self, kind, i=None):
        if kind == 'text':
            texts = self.art.get('texts') or []
            return texts[i] if i is not None and 0 <= i < len(texts) else None
        if kind == 'plot':
            return self.art.get('ax')
        return self.art.get(kind)

    def _bbox(self, kind, i=None):
        a = self._artist(kind, i)
        if a is None:
            return None
        try:
            if kind == 'plot':
                return a.bbox
            return a.get_window_extent(self.canvas.get_renderer())
        except Exception:
            return None

    def _handle_rect(self, bb):
        r = HANDLE_PX * (self.canvas.device_pixel_ratio or 1)
        return bb.x1 - r / 2, bb.y0 - r / 2, r

    def _draw_selection(self):
        """Dashed box around the selected object, with its resize handle (bottom right)."""
        from matplotlib.patches import Rectangle
        from matplotlib.transforms import IdentityTransform

        for p in self._overlay:
            try:
                p.remove()
            except Exception:
                pass
        self._overlay = []
        if self.sel is None or not self.art or self.sel[0] == 'series':
            self.canvas.draw_idle()  # a series: picked only (its settings in the inspector)
            return
        bb = self._bbox(*self.sel)
        if bb is None:
            self.sel = None
            self.canvas.draw_idle()
            return
        t = IdentityTransform()
        box = Rectangle((bb.x0, bb.y0), bb.width, bb.height, transform=t, fill=False, ec='#1e88e5',
                        lw=1.0, ls='--', zorder=1000)
        hx, hy, r = self._handle_rect(bb)
        handle = Rectangle((hx, hy), r, r, transform=t, fc='#1e88e5', ec='white', lw=0.8, zorder=1001)
        for p in (box, handle):
            p.set_in_layout(False)
            self.fig.add_artist(p)
            self._overlay.append(p)
        self.canvas.draw_idle()
        self.statusBar().showMessage(f'선택: {OBJECT_NAMES.get(self.sel[0], self.sel[0])} — 끌어 옮기기, '
                                     '모서리 핸들로 크기', 4000)

    def _on_handle(self, event) -> bool:
        if self.sel is None or self.sel[0] == 'series':
            return False
        bb = self._bbox(*self.sel)
        if bb is None:
            return False
        hx, hy, r = self._handle_rect(bb)
        pad = r * 0.6
        return hx - pad <= event.x <= hx + r + pad and hy - pad <= event.y <= hy + r + pad

    def _hit(self, event):
        for i, t in reversed(list(enumerate(self.art.get('texts') or []))):
            if t.contains(event)[0]:
                return 'text', i
        leg = self.art.get('legend')
        if leg is not None and leg.contains(event)[0]:
            return 'legend', None
        for k in ('title', 'xlabel', 'ylabel'):
            a = self.art.get(k)
            if a is not None and a.get_text() and a.contains(event)[0]:
                return k, None
        ax = self.art.get('ax')
        if ax is not None:
            for a in reversed(ax.get_children()):
                gid = a.get_gid() or ''
                if gid.startswith('series:') and a.get_visible():
                    try:
                        hit = a.contains(event)[0]
                    except Exception:
                        hit = False
                    if hit:
                        return 'series', int(gid[7:])
        if ax is not None and ax.bbox.contains(event.x, event.y):
            return 'plot', None
        return None, None

    def _axes_xy(self, x, y):
        return self.art['ax'].transAxes.inverted().transform((x, y))

    @staticmethod
    def _mods(event) -> set:
        return set(getattr(event, 'modifiers', None) or ())

    def _press(self, event):
        if not self.art or event.x is None:
            return
        from PySide6.QtGui import QCursor

        mods = self._mods(event)
        if event.button == 2 or (event.button == 1 and 'alt' in mods and 'shift' in mods):
            hs, vs = self.holder.horizontalScrollBar(), self.holder.verticalScrollBar()
            self._drag = {'mode': 'pan', 'pos': QCursor.pos(), 'scroll': (hs.value(), vs.value())}
            return
        if event.button == 1 and mods & {'ctrl', 'cmd'}:
            self._drag = {'mode': 'zoom', 'pos': QCursor.pos(), 'zoom': self.zoom,
                          'anchor': self._qt_xy(event)}
            return
        if event.button == 3:
            self._context_menu(event)
            return
        if event.button != 1:
            return
        if self.spec.chart in G.CORR_CHARTS and event.inaxes is not None and event.xdata is not None:
            cell = G.corr_cell(self.spec, self.art, event.inaxes, event.xdata, event.ydata)
            if cell is not None:
                self.open_scatter(*cell)
                return
        if event.dblclick:
            kind, i = self._hit(event)
            self._edit(kind, i, event)
            return
        if self._on_handle(event):
            self._start_drag('resize', *self.sel, event)
            return
        kind, i = self._hit(event)
        self.sel = (kind, i) if kind else None
        if kind == 'text':
            self._text_i = i
            self._fill_lists()
        elif kind == 'series':
            self._series_i = i
        self._show_selection()
        self._draw_selection()
        if kind and kind != 'series':
            self._start_drag('move', kind, i, event)

    def _start_drag(self, mode, kind, i, event):
        """Remember where the object was; things laid out automatically are
        first pinned where they are now."""
        sp = self.spec
        ax = self.art['ax']
        if kind == 'plot' and sp.plot_auto:
            sp.plot_x, sp.plot_y, sp.plot_w, sp.plot_h = (float(v) for v in ax.get_position().bounds)
            sp.plot_auto = False
            self._pin_labels()
            self.render()
        elif kind in ('title', 'xlabel', 'ylabel') and getattr(sp, f'{kind}_auto'):
            self._pin_label(kind)
            self.render()
        elif kind == 'legend' and mode == 'move':
            leg = self.art['legend']
            bb = leg.get_window_extent()
            sp.legend_x, sp.legend_y = (float(v) for v in self._axes_xy(bb.x0, bb.y0))
            sp.legend_loc = 'custom'
            self.render()
        bb = self._bbox(kind, i)
        orig = {
            'text': lambda: (sp.texts[i].x, sp.texts[i].y, sp.texts[i].size),
            'legend': lambda: (sp.legend_x, sp.legend_y, sp.legend_font.size),
            'title': lambda: (sp.title_x, sp.title_y, sp.title_font.size),
            'xlabel': lambda: (sp.xlabel_x, sp.xlabel_y, sp.label_font.size),
            'ylabel': lambda: (sp.ylabel_x, sp.ylabel_y, sp.label_font.size),
            'plot': lambda: (sp.plot_x, sp.plot_y, sp.plot_w, sp.plot_h),
        }[kind]()
        self._drag = {'mode': mode, 'kind': kind, 'i': i, 'x0': event.x, 'y0': event.y, 'orig': orig,
                      'bbox': bb, 'moved': False}

    def _pin_label(self, kind):
        """Fix the title / an axis name where it is drawn now (axes fractions)."""
        sp, a = self.spec, self.art.get(kind)
        if a is None:
            setattr(sp, f'{kind}_auto', False)
            return
        bb = a.get_window_extent(self.canvas.get_renderer())
        if kind == 'title':
            x, y = self._axes_xy((bb.x0 + bb.x1) / 2, bb.y0)
        elif kind == 'xlabel':  # anchored at its top centre
            x, y = self._axes_xy((bb.x0 + bb.x1) / 2, bb.y1)
        else:  # y label (turned 90°): anchored at its right edge, middle
            x, y = self._axes_xy(bb.x1, (bb.y0 + bb.y1) / 2)
        setattr(sp, f'{kind}_x', float(x))
        setattr(sp, f'{kind}_y', float(y))
        setattr(sp, f'{kind}_auto', False)

    def _pin_labels(self):
        for k in ('title', 'xlabel', 'ylabel'):
            if getattr(self.spec, f'{k}_auto') and self.art.get(k) is not None and self.art[k].get_text():
                self._pin_label(k)

    def _qt_xy(self, event):
        r = self.canvas.device_pixel_ratio or 1
        return event.x / r, self.canvas.height() - event.y / r

    def _motion(self, event):
        from PySide6.QtGui import QCursor

        d = self._drag
        if d is None:
            if event.x is None or not self.art:
                return
            if self.spec.chart in G.CORR_CHARTS:
                tip = G.corr_cell_text(self.spec, self.art, event.inaxes, event.xdata, event.ydata) \
                    if event.inaxes is not None and event.xdata is not None else ''
                self.canvas.setToolTip(tip + ('\n클릭: 이 두 열의 산점도' if tip else ''))
                self.canvas.setCursor(Qt.CursorShape.PointingHandCursor if tip else Qt.CursorShape.ArrowCursor)
                return
            if self._on_handle(event):
                shape = Qt.CursorShape.SizeFDiagCursor
            else:
                kind, _ = self._hit(event)
                shape = Qt.CursorShape.OpenHandCursor if kind else Qt.CursorShape.ArrowCursor
            self.canvas.setCursor(shape)
            return
        if d['mode'] == 'pan':
            p = QCursor.pos() - d['pos']
            self.holder.horizontalScrollBar().setValue(d['scroll'][0] - p.x())
            self.holder.verticalScrollBar().setValue(d['scroll'][1] - p.y())
            return
        if d['mode'] == 'zoom':
            dy = d['pos'].y() - QCursor.pos().y()  # up = in
            z = d['zoom'] * float(np.exp(dy * ZOOM_DRAG_RATE * self._zoom_sens()))
            self.zoom_by(z / self.zoom, d['anchor'])
            return
        if event.x is None:
            return
        d['moved'] = True
        dx, dy = event.x - d['x0'], event.y - d['y0']
        self._apply_drag(d, dx, dy)

    def _zoom_sens(self) -> float:
        try:
            from .settings import view_settings
            return float(view_settings.value('zoom_drag'))
        except Exception:
            return 1.0

    def _apply_drag(self, d, dx, dy):
        """Write the dragged position / size into the spec and show it."""
        import time

        sp, kind, i, o = self.spec, d['kind'], d['i'], d['orig']
        ax = self.art['ax']
        fw, fh = self.fig.bbox.width, self.fig.bbox.height
        aw, ah = max(ax.bbox.width, 1), max(ax.bbox.height, 1)
        if d['mode'] == 'move':
            if kind == 'plot':
                sp.plot_x, sp.plot_y = o[0] + dx / fw, o[1] + dy / fh
                ax.set_position((sp.plot_x, sp.plot_y, sp.plot_w, sp.plot_h))
            else:
                nx, ny = o[0] + dx / aw, o[1] + dy / ah
                if kind == 'text':
                    sp.texts[i].x, sp.texts[i].y = nx, ny
                    self._artist('text', i).set_position((nx, ny))
                elif kind == 'legend':
                    sp.legend_x, sp.legend_y = nx, ny
                    self.art['legend'].set_bbox_to_anchor((nx, ny), transform=ax.transAxes)
                elif kind == 'title':
                    sp.title_x, sp.title_y = nx, ny
                    self.art['title'].set_position((nx, ny))
                elif kind == 'xlabel':
                    sp.xlabel_x, sp.xlabel_y = nx, ny
                    ax.xaxis.set_label_coords(nx, ny)
                elif kind == 'ylabel':
                    sp.ylabel_x, sp.ylabel_y = nx, ny
                    ax.yaxis.set_label_coords(nx, ny)
            self._draw_selection()
            return
        # resize with the bottom-right handle
        if kind == 'plot':
            w = max(0.05, o[2] + dx / fw)
            h = max(0.05, o[3] - dy / fh)
            sp.plot_w, sp.plot_h = w, h
            sp.plot_y = o[1] + o[3] - h  # the top edge stays
            ax.set_position((sp.plot_x, sp.plot_y, sp.plot_w, sp.plot_h))
            self._draw_selection()
            return
        bb = d['bbox']
        f = max(0.2, (bb.width + dx) / max(bb.width, 1))
        size = round(max(2.0, min(144.0, o[2] * f)), 1)
        if kind == 'text':
            sp.texts[i].size = size
        elif kind == 'legend':
            sp.legend_font.size = size
        elif kind == 'title':
            sp.title_font.size = size
        else:
            sp.label_font.size = size
        now = time.monotonic()
        if now - self._last_live > 0.05:  # redraw at most 20 times a second
            self._last_live = now
            self.render()

    def _release(self, event):
        d, self._drag = self._drag, None
        if d is None or d['mode'] in ('pan', 'zoom'):
            return
        if not d['moved']:
            return  # a click: selected only
        self.b.sync()
        self.render()
        self._changed_no_redraw()

    def _changed_no_redraw(self):
        set_dirty = getattr(self.win, 'set_dirty', None)
        if set_dirty is not None:
            set_dirty()

    def _scroll_ev(self, event):
        mods = self._mods(event)
        if mods & {'ctrl', 'cmd'}:
            self.zoom_by(ZOOM_STEP if event.step > 0 else 1 / ZOOM_STEP, self._qt_xy(event))
            return
        bar = self.holder.horizontalScrollBar() if 'shift' in mods else self.holder.verticalScrollBar()
        bar.setValue(int(bar.value() - event.step * 40))

    def auto_layout(self):
        sp = self.spec
        sp.plot_auto = sp.title_auto = sp.xlabel_auto = sp.ylabel_auto = True
        self.b.sync()
        self.render()
        self._changed_no_redraw()

    def _edit(self, kind, i, event):
        if kind == 'text':
            tb = self.spec.texts[i]
            text, ok = QInputDialog.getMultiLineText(self, '글자 상자', '글자:', tb.text)
            if ok:
                tb.text = text
        elif kind == 'title':
            text, ok = QInputDialog.getText(self, '제목', '제목:', text=self.spec.title)
            if ok:
                self.spec.title = text
        elif kind in ('xlabel', 'ylabel'):
            a = self.spec.x if kind == 'xlabel' else self.spec.y
            text, ok = QInputDialog.getText(self, '축 이름', '이름 (단위는 ‘축’ 탭):', text=a.label)
            if ok:
                a.label = text
        elif kind == 'legend':
            self._edit_legend_entry(event)
        else:
            return
        self._fill_lists()
        self.sync()
        self.render()

    def _edit_legend_entry(self, event):
        leg = self.art['legend']
        texts = leg.get_texts()
        hit = next((k for k, t in enumerate(texts) if t.contains(event)[0]), None)
        if hit is None:
            return
        # entries: shown series with legend on (in order), then the extra items
        owners = [s for s in self.spec.series if s.visible and s.legend] + list(self.spec.legend_items)
        old = texts[hit].get_text()
        text, ok = QInputDialog.getText(self, '범례 항목', '이름:', text=old)
        if not ok:
            return
        for o in owners:
            cur = o.label if isinstance(o, G.LegendItem) else (o.label or o.y)
            if cur == old:
                o.label = text
                break

    def _context_menu(self, event):
        x, y = self._axes_xy(event.x, event.y)
        kind, i = self._hit(event)
        m = QMenu(self)
        m.addAction('여기에 글자 상자 추가…', lambda: self.add_text(x, y))
        m.addAction('범례를 여기로 옮기기', lambda: self._legend_here(x, y))
        m.addAction('범례 항목 추가', self.add_legend_item)
        if kind == 'text':
            m.addAction('이 글자 상자 지우기', lambda: self._delete_text(i))
        m.addSeparator()
        m.addAction('모든 위치·크기 자동 배치로', self.auto_layout)
        m.addAction('화면 맞춤', self.zoom_fit)
        m.exec(self.canvas.mapToGlobal(self.canvas.rect().topLeft()) + self._qt_point(event))

    def _delete_text(self, i):
        self._text_i = i
        self.sel = None
        self.del_text()

    def _qt_point(self, event):
        from PySide6.QtCore import QPoint

        x, y = self._qt_xy(event)
        return QPoint(int(x), int(y))

    def _legend_here(self, x, y):
        self.spec.legend_loc = 'custom'
        self.spec.legend_x, self.spec.legend_y = float(x), float(y)
        self.spec.legend_show = True
        self.b.sync()
        self.render()

    def _convert_unit(self, which, combo):
        k, u = combo.currentData() or (None, None)
        combo.setCurrentIndex(0)
        if k is None:
            return
        a = getattr(self.spec, which)
        a.scale = a.scale * float(k) if k != 1.0 else 1.0  # s -> min twice = 1/3600
        if u is not None:
            a.unit = u
        self.b.sync()
        self._changed()

    # ---- more data: other analyses, CSV ----------------------------------------------------------

    def _sources(self) -> dict:
        fn = getattr(self.win, 'graph_sources', None)
        return fn(all_data=True) if fn is not None else {}

    def add_tables(self, title, tables, make_series=True) -> list:
        """Add tables (names prefixed with title) to this graph's data; with
        make_series, a series of the first one in the selected series' style."""
        if self.data is None:
            self.data = G.GraphData(title, [], G.GraphSpec())
        have = {t.name for t in self.data.tables}
        added = []
        for t in tables:
            name = f'{title} · {t.name}' if title else t.name
            base, k = name, 2
            while name in have:
                name = f'{base} ({k})'
                k += 1
            have.add(name)
            nt = G.Table(name, list(t.columns), [list(r) for r in t.rows], dict(t.labels), dict(t.column_sets))
            self.data.tables.append(nt)
            self.extra.append(nt)
            added.append(nt)
        if make_series and added:
            t = added[0]
            nums = t.numeric_columns()
            base = self.cur_series()
            s = G.Series(**asdict(base)) if base is not None else G.Series(style='line+marker')
            s.table, s.label = t.name, t.name
            s.where = s.equals = s.where2 = s.equals2 = s.split = s.err = s.z = s.agg_by = ''
            s.agg = 'none'
            texts = [c for c in t.columns if c not in nums]
            if self.spec.chart in G.CATEGORY_CHARTS:
                s.x = next((c for c in ('group', 'image', 'roi') if c in t.columns), texts[0] if texts else '')
                s.y = nums[0] if nums else ''
            else:
                s.x = nums[0] if nums else ''
                s.y = nums[1] if len(nums) > 1 else (nums[0] if nums else '')
            s.color = G.PALETTE[len(self.spec.series) % len(G.PALETTE)]
            s.visible = True
            self.spec.series.append(s)
            self._series_i = len(self.spec.series) - 1
        self._fill_lists()
        self.sync()
        self.render()
        self.table_pick.setCurrentIndex(max(self.table_pick.findData(('table', added[0].name)), 0)
                                        if added else 0)
        return added

    def import_source(self, key):
        title, _tab, fn, hint = self._sources()[key]
        try:
            data = fn()
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, '데이터 가져오기', f'데이터를 만들지 못했습니다: {exc}')
            return []
        if data is None or not data.tables:
            QMessageBox.information(self, '데이터 가져오기', hint)
            return []
        added = self.add_tables(title, data.tables)
        self._status(f'{title}: 표 {len(added)}개를 가져와 시리즈를 하나 더 그렸습니다.')
        return added

    def import_csv(self, path=None):
        t = self.read_csv(path)
        if t is None:
            return []
        added = self.add_tables('CSV', [t])
        self._status(f'CSV {t.name}: {len(t.rows)}행을 가져왔습니다.')
        return added

    def read_csv(self, path=None) -> G.Table | None:
        import csv

        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, 'CSV 불러오기', self._default(''), 'CSV (*.csv *.txt)')
            if not path:
                return None
        try:
            with open(path, newline='', encoding='utf-8-sig') as f:
                sample = f.read(4096)
                f.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=',;\t')
                except csv.Error:
                    dialect = csv.excel
                rows = list(csv.reader(f, dialect))
        except Exception as exc:
            QMessageBox.warning(self, 'CSV 불러오기', str(exc))
            return None
        if not rows:
            QMessageBox.information(self, 'CSV 불러오기', '빈 파일입니다.')
            return None
        head = rows[0]

        def conv(v):
            x = G._num(v)
            return x if v.strip() and np.isfinite(x) else v

        return G.Table(Path(path).stem, head, [[conv(v) for v in r] for r in rows[1:]])

    def remove_table(self):
        if self.data is None or not self.data.tables:
            return
        names = [t.name for t in self.data.tables]
        name, ok = QInputDialog.getItem(self, '표 지우기', '이 그래프에서 뺄 표 (그 표를 쓰는 시리즈도 지웁니다):',
                                        names, len(names) - 1, False)
        if not ok:
            return
        self.data.tables = [t for t in self.data.tables if t.name != name]
        self.extra = [t for t in self.extra if t.name != name]
        self.spec.series = [s for s in self.spec.series if s.table != name]
        self._series_i = min(self._series_i, len(self.spec.series) - 1)
        self._after_list_change()

    # ---- the data table -----------------------------------------------------------------------

    def _fill_table_choices(self):
        cur = self.table_pick.currentData()
        self.table_pick.blockSignals(True)
        self.table_pick.clear()
        self.table_pick.addItem('그래프에 쓰인 데이터', ('plotted', None))
        if self.spec.chart in G.CATEGORY_CHARTS:
            self.table_pick.addItem('그래프 요약 (평균 · SD · SEM · n)', ('summary', None))
        for name in self.tables():
            self.table_pick.addItem(f'표: {name}', ('table', name))
        i = self.table_pick.findData(cur) if cur is not None else 0
        self.table_pick.setCurrentIndex(max(i, 0))
        self.table_pick.blockSignals(False)
        self.fill_table()

    def shown_table(self) -> G.Table:
        kind, name = self.table_pick.currentData() or ('plotted', None)
        only = {self._series_i} if self.only_sel.isChecked() and self._series_i >= 0 else None
        if kind == 'plotted':
            return G.plotted_table(self.spec, self.tables(), only)
        if kind == 'summary':
            return G.summary_table(self.spec, self.tables(), only)
        return self.tables().get(name) or G.Table(name or '', [], [])

    def fill_table(self):
        if self.data is None:
            return
        try:
            t = self.shown_table()
        except Exception:
            traceback.print_exc()
            t = G.Table('', [], [])
        self.model.set_table(t)
        self.table_info.setText(f'{len(t.rows)}행 × {len(t.columns)}열')

    def copy_selection(self):
        idx = self.view.selectionModel().selectedIndexes()
        if not idx:
            return
        rows = sorted({i.row() for i in idx})
        cols = sorted({i.column() for i in idx})
        t = self.model.table
        lines = ['\t'.join(t.columns[c] for c in cols)]
        text = self.model._text
        lines += ['\t'.join(text[r][c] if c < len(text[r]) else '' for c in cols) for r in rows]
        QApplication.clipboard().setText('\n'.join(lines))

    # ---- export ---------------------------------------------------------------------------------

    def _status(self, msg):
        self.statusBar().showMessage(msg, 8000)
        sb = getattr(self.win, 'statusBar', None)
        if sb is not None:
            sb().showMessage(msg)

    def _default(self, suffix) -> str:
        d = self.data
        folder = Path(d.folder) if d and d.folder else Path.home()
        return str(folder / f'{d.name if d else "graph"}{suffix}')

    def _ask_csv(self, title, suffix) -> str:
        path, _ = QFileDialog.getSaveFileName(self, title, self._default(suffix), 'CSV (*.csv)')
        if path and not path.lower().endswith('.csv'):
            path += '.csv'
        return path

    def save_image(self, path=None):
        if path is None:
            path, flt = QFileDialog.getSaveFileName(self, '그래프 이미지 저장', self._default('.png'),
                                                    ';;'.join(IMAGE_FILTERS))
            if not path:
                return None
            if not Path(path).suffix:
                path += IMAGE_FILTERS.get(flt, '.png')
        try:
            G.save_figure(path, self.spec, self.tables())
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, '저장 실패', str(exc))
            return None
        self._status(f'그래프 저장: {path}')
        return path

    def _write(self, path, table, rows=None):
        if not path:
            return None
        try:
            n = G.write_csv(path, table, rows)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, '저장 실패', str(exc))
            return None
        self._status(f'{table.name} {n}행 저장: {path}')
        return path

    def export_plotted(self, selected=False, path=None):
        only = None
        if selected:
            if self.cur_series() is None:
                QMessageBox.information(self, '내보내기', '‘데이터 시리즈’ 탭에서 시리즈를 고르세요.')
                return None
            only = {self._series_i}
        t = G.plotted_table(self.spec, self.tables(), only)
        suffix = '_plotted.csv' if not selected else f'_{_safe(G._label(self.cur_series(), self._series_i))}.csv'
        return self._write(path or self._ask_csv('그래프에 쓰인 데이터 저장', suffix), t)

    def export_summary(self, path=None):
        t = G.summary_table(self.spec, self.tables())
        if not t.rows:
            QMessageBox.information(self, '내보내기', '요약은 막대·점 그림·상자·바이올린 그래프에서 만듭니다.')
            return None
        return self._write(path or self._ask_csv('그래프 요약 저장', '_summary.csv'), t)

    def export_table(self, path=None):
        t = self.model.table
        return self._write(path or self._ask_csv('표 저장', f'_{_safe(t.name)}.csv'), t)

    def export_selected_rows(self, path=None):
        rows = sorted({i.row() for i in self.view.selectionModel().selectedIndexes()})
        if not rows:
            QMessageBox.information(self, '내보내기', '아래 표에서 행을 고르세요 (Shift / Cmd·Ctrl + 클릭).')
            return None
        t = self.model.table
        return self._write(path or self._ask_csv('선택한 행 저장', f'_{_safe(t.name)}_selected.csv'), t,
                           [t.rows[r] for r in rows])

    def export_all(self, folder=None) -> list:
        if folder is None:
            folder = QFileDialog.getExistingDirectory(self, '데이터 표를 저장할 폴더',
                                                      str(Path(self._default('')).parent))
            if not folder:
                return []
        stem = self.data.name if self.data else 'graph'
        out = []
        try:
            tabs = list(self.data.tables) + [G.plotted_table(self.spec, self.tables())]
            summ = G.summary_table(self.spec, self.tables())
            if summ.rows:
                tabs.append(summ)
            for t in tabs:
                p = Path(folder) / f'{stem}_{_safe(t.name)}.csv'
                G.write_csv(p, t)
                out.append(str(p))
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, '저장 실패', str(exc))
            return out
        self._status(f'데이터 표 {len(out)}개 저장: {folder}')
        return out

    def save_settings(self, path=None):
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, '그래프 설정 저장', self._default('_graph.json'),
                                                  'JSON (*.json)')
            if not path:
                return None
        try:
            G.save_spec(path, self.spec)
        except Exception as exc:
            QMessageBox.warning(self, '저장 실패', str(exc))
            return None
        self._status(f'그래프 설정 저장: {path}')
        return path

    def load_settings(self, style_only=False, path=None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, '그래프 설정 불러오기', self._default(''),
                                                  'JSON (*.json)')
            if not path:
                return False
        try:
            spec = G.load_spec(path)
        except Exception as exc:
            QMessageBox.warning(self, '불러오기 실패', str(exc))
            return False
        self.spec = G.apply_style(self.spec, spec) if style_only else spec
        self._series_i = 0 if self.spec.series else -1
        self._text_i = 0 if self.spec.texts else -1
        self._item_i = 0 if self.spec.legend_items else -1
        self._fill_lists()
        self.sync()
        self.render()
        return True
