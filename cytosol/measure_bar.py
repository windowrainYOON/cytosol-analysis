"""측정 바: the two measure buttons fixed at the bottom of the inspector
(owner request 2026-11-15, after mockup measure-bar-1..5).

The bar sits under the tab pages inside the inspector box and is shown only
while a tab that measures is the current tab.  Every measuring tab registers a
`Measurer` (current image / all images / one status line); the bar calls it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from . import theme


@dataclass
class Measurer:
    """What the bar needs from a measuring tab."""
    current: Callable[[], object]
    all: Callable[[], object]
    status: Callable[[], tuple] = lambda: ('', None)   # (text, StatusLabel kind)
    one_text: str = '이 이미지만 측정'
    all_text: str = '전체 이미지 측정'


def box_measurer(box) -> Measurer:
    """Measurer of a `MeasureBox` (세포질 ROI, 입자 ROI, 강도 측정, 등거리 띠)."""
    return Measurer(box.measure_current, box.measure_all,
                    lambda: (box.state.text(), box.state.kind()))


class MeasureBar(QWidget):
    """[이 이미지만 측정] [전체 이미지 측정] + one status line."""

    def __init__(self, win, parent=None):
        super().__init__(parent)
        self.setObjectName('hig_measure_bar')
        self.win = win
        self.measurer: Measurer | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.state = QLabel()
        self.state.setWordWrap(True)
        theme.hint(self.state)
        lay.addWidget(self.state)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.one_btn = QPushButton('이 이미지만 측정')
        self.one_btn.setToolTip('지금 보는 이미지만 잽니다.')
        self.one_btn.clicked.connect(lambda: self._run('current'))
        self.all_btn = theme.prominent(QPushButton('전체 이미지 측정'))
        self.all_btn.setToolTip('모든 이미지를 같은 설정으로 잽니다.')
        self.all_btn.clicked.connect(lambda: self._run('all'))
        row.addWidget(self.one_btn, 1)
        row.addWidget(self.all_btn, 1)
        lay.addLayout(row)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)
        self.hide()

    def bind(self, measurer: Measurer | None, page=None):
        self.measurer = measurer
        self.setVisible(measurer is not None)
        if measurer is None:
            self._timer.stop()
            return
        self.one_btn.setText(measurer.one_text)
        self.all_btn.setText(measurer.all_text)
        self.align(page)
        self.refresh()
        self._timer.start()

    def align(self, page):
        """Line the buttons up with the cards: the page's scroll bar gutter
        stays free on the right."""
        from PySide6.QtWidgets import QScrollArea
        gap = 0
        if isinstance(page, QScrollArea):
            sb = page.verticalScrollBar()
            gap = max(0, page.width() - page.viewport().width()) if sb.isVisible() else 0
        self.layout().setContentsMargins(0, 0, gap, 0)

    def refresh(self):
        m = self.measurer
        if m is None:
            return
        has = self.win.current is not None
        self.one_btn.setEnabled(has)
        self.all_btn.setEnabled(bool(self.win.items))
        try:
            text, _kind = m.status()
        except Exception:  # noqa: BLE001
            text = ''
        text = (text or '').split(' · ')[0] if len(text or '') > 60 else (text or '')
        self.state.setText(text)
        self.state.setVisible(bool(text))

    def _run(self, which):
        m = self.measurer
        if m is None:
            return
        (m.current if which == 'current' else m.all)()
        self.refresh()


class DataRows(QWidget):
    """The 데이터 rows of a tab whose result table moved to the graph window
    (no scrolling table inside a scrolling page): name, size, state,
    그래프 ›.  `tables()` returns [(name, 점 하나 =, rows)]."""

    def __init__(self, win, tables: Callable[[], list], feature: str = '', parent=None):
        super().__init__(parent)
        self.win = win
        self.tables = tables
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(6)
        from .integrate import feeds_text
        note = QLabel(' '.join(x for x in (feeds_text(feature), '표 전체는 그래프 편집 창의 데이터에서 봅니다.') if x))
        note.setWordWrap(True)
        theme.hint(note)
        self.note = note
        self._rows: list[QWidget] = []
        self._lay.addWidget(note)
        self.refresh()

    def refresh(self):
        for w in self._rows:
            w.setParent(None)
            w.deleteLater()
        self._rows = []
        try:
            tables = self.tables()
        except Exception:  # noqa: BLE001
            tables = []
        for i, (name, unit, rows) in enumerate(tables):
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(8)
            lab = QLabel(f'<b>{name}</b>')
            lab.setToolTip(f'점 하나 = {unit}')
            h.addWidget(lab)
            n_img = len({r.get('image_id', r.get('image')) for r in rows})
            size = QLabel(f'{len(rows)}행 · 이미지 {n_img}' if rows else '없음')
            theme.secondary(size)
            h.addWidget(size)
            h.addStretch()
            g = QPushButton('그래프 ›')
            g.setEnabled(bool(rows))
            g.setToolTip('그래프 창에서 이 표로 새 그래프를 만듭니다 (종류 → 축 배치 → 그룹).')
            g.clicked.connect(lambda _=False, n=name: self.open_graph(n))
            h.addWidget(g)
            self._lay.insertWidget(i, w)
            self._rows.append(w)

    def open_graph(self, name):
        gw = self.win.graph_window()
        gw.show()
        gw.start_data(name)


def grow_to_content(view, min_rows: int = 1):
    """A list / table inside a scrolling inspector page shows all its rows
    and never scrolls itself (owner request 2026-11-15: nothing hidden in an
    inner scroll area)."""
    from PySide6.QtCore import Qt
    view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    view.setMinimumHeight(0)

    def fit(*_):
        try:
            _fit()
        except RuntimeError:  # the view is gone (window closing)
            pass

    def _fit():
        n = view.count() if hasattr(view, 'count') else view.rowCount()
        if hasattr(view, 'rowHeight') and n:
            body = sum(view.rowHeight(i) for i in range(n))
        else:
            body = (max(view.sizeHintForRow(0), 20) if n else 24) * n
        body = max(body, 24 * min_rows)
        head = 0
        hh = getattr(view, 'horizontalHeader', None)
        if hh is not None and hh().isVisible():
            head = hh().height()
        hbar = view.horizontalScrollBar()
        extra = hbar.sizeHint().height() if hbar.isVisible() else 0
        view.setFixedHeight(head + body + 2 * view.frameWidth() + extra)

    m = view.model()
    for sig in (m.rowsInserted, m.rowsRemoved, m.modelReset, m.layoutChanged):
        sig.connect(fit)
    view._fit = fit
    fit()
    return fit
