"""mitoROI tab (v0.67, design doc mito-tracking ch. 3): Mito Analyzer's
mitochondria / protein-of-interest measurements on the 세포질 ROI tab's
cells (cytosol.mito), the MiNA picture as canvas layers, result tables for
the graph window, export, batch, Mito Analyzer results loaded."""

from __future__ import annotations

import traceback
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsSimpleTextItem,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import mito as M
from . import theme
from .flow import FlowLayout

LAYERS = [('mito', '미토 면적', (255, 0, 255, 150)), ('skeleton', '골격', (0, 255, 0, 255)),
          ('ends', '끝점', (255, 255, 0, 255)), ('junctions', '분기점', (60, 120, 255, 255)),
          ('puncta', 'green 점', (120, 255, 120, 255)), ('numbers', '세포 번호', None)]
TABLES = [('cells', '세포마다'), ('mito', '미토 조각마다'), ('puncta', '점마다')]
TABLE_COLS = {'cells': [('cell', '세포'), ('green_status', 'green'), ('footprint_fraction', 'footprint'),
                        ('n_branches', '가지'), ('n_mito_objects', '조각'), ('n_green_puncta', '점')],
              'mito': [('mito', '조각'), ('cell', '세포'), ('length_um', '길이 µm'), ('aspect_ratio', '장단축비'),
                       ('n_branches', '가지'), ('green_mean', 'green')],
              'puncta': [('punctum', '점'), ('cell', '세포'), ('area_um2', '면적 µm²'), ('green_mean', 'green'),
                         ('on_mito', '미토 위')]}
DATA_NAMES = {'cells': ('mitoROI · 세포', '세포'), 'mito': ('mitoROI · 미토 조각', '미토 조각'),
              'puncta': ('mitoROI · 점', '점')}


def _hint(text):
    w = QLabel(text)
    w.setWordWrap(True)
    theme.hint(w)
    return w


def _row(*ws):
    w = QWidget()
    w.setProperty('hig_no_reflow', True)
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(8)
    for x in ws:
        h.addWidget(x) if isinstance(x, QWidget) else h.addStretch(1)
    return w


class AutoField:
    """[value][자동]: while 자동 is on the value is greyed and shows the value
    the last run used; editing it turns 자동 off (owner rule 2026-11-04)."""

    def __init__(self, lo, hi, decimals=1, step=1.0, suffix='', slider=False):
        self.spin = QDoubleSpinBox()
        self.spin.setRange(lo, hi)
        self.spin.setDecimals(decimals)
        self.spin.setSingleStep(step)
        if suffix:
            self.spin.setSuffix(suffix)
        self.auto = theme.switch(QCheckBox('자동'))
        self.auto.setChecked(True)
        self.auto.toggled.connect(self._toggled)
        self.spin.setEnabled(False)
        self.spin.valueChanged.connect(self._edited)
        self.slider = None
        if slider:
            self.slider = QSlider(Qt.Orientation.Horizontal)
            self.slider.setRange(0, 1000)
            self.slider.valueChanged.connect(self._slid)
            self.spin.valueChanged.connect(self._to_slider)
            self.widget = theme.slider_field(self.slider, self.spin, self.auto)
        else:
            self.widget = _row(None, self.spin, self.auto)

    def _toggled(self, on):
        self.spin.setEnabled(not on)
        if self.slider is not None:
            self.slider.setEnabled(not on)

    def _edited(self, _v):
        if self.spin.hasFocus() and self.auto.isChecked():
            self.auto.setChecked(False)

    def _slid(self, v):
        if self.slider.hasFocus() or self.slider.isSliderDown():
            if self.auto.isChecked():
                self.auto.setChecked(False)
            lo, hi = self.spin.minimum(), self.spin.maximum()
            self.spin.setValue(lo + (hi - lo) * v / 1000)

    def _to_slider(self, v):
        if self.slider is not None and not self.slider.isSliderDown():
            lo, hi = self.spin.minimum(), self.spin.maximum()
            self.slider.blockSignals(True)
            self.slider.setValue(int(round(1000 * (v - lo) / max(hi - lo, 1e-9))))
            self.slider.blockSignals(False)

    def value(self):
        """0 = automatic."""
        return 0.0 if self.auto.isChecked() else float(self.spin.value())

    def show_used(self, v):
        if self.auto.isChecked() and v is not None and np.isfinite(v):
            self.spin.blockSignals(True)
            self.spin.setValue(float(v))
            self.spin.blockSignals(False)
            self._to_slider(float(v))


class MitoPanel(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.item = None
        self._scene = []
        self._sel = None
        lay = QVBoxLayout(self)
        lay.addWidget(_hint('세포질 ROI 탭의 세포마다 미토콘드리아를 나누고 골격(MiNA)과 조각을 측정합니다. 관심 단백질 '
                            '채널이 있으면 미토 위 / 밖의 신호, 점(puncta), 공존(Pearson, Manders)도 함께 잽니다.'))
        self.run_btn = theme.prominent(QPushButton('분석 실행'))
        self.run_btn.clicked.connect(lambda: self.run_current())
        self.all_btn = QPushButton('모든 이미지에 실행')
        self.all_btn.clicked.connect(lambda: self.run_all())
        lay.addWidget(_row(self.run_btn, self.all_btn, None))

        # 1 채널 · 세포
        box = QGroupBox('1  채널 · 세포')
        f = QFormLayout(box)
        self.mito_ch = QComboBox()
        self.poi_ch = QComboBox()
        f.addRow('미토콘드리아', self.mito_ch)
        f.addRow('관심 단백질', self.poi_ch)
        f.addRow('세포 ROI', QLabel('세포질 ROI 탭 (핵 하나 = 세포 하나)'))
        chips = QWidget()
        fl = FlowLayout(chips)
        fl.setContentsMargins(0, 0, 0, 0)
        self.include_edge = theme.chip(QCheckBox('가장자리 세포 포함'))
        self.include_edge.setToolTip('이미지 가장자리에 닿은 세포도 분석합니다.')
        self.exclude_weak = theme.chip(QCheckBox('경계 약한 이웃 제외'))
        self.exclude_weak.setToolTip('이웃 세포와의 경계가 주변보다 어둡지 않은 세포(한 세포가 둘로 나뉜 경우)를 '
                                     '분석에서 뺍니다.')
        fl.addWidget(self.include_edge)
        fl.addWidget(self.exclude_weak)
        f.addRow(chips)
        self.binuc = QDoubleSpinBox()
        self.binuc.setRange(0, 1)
        self.binuc.setDecimals(2)
        self.binuc.setSingleStep(0.05)
        self.binuc.setValue(0.1)
        self.binuc.setToolTip('경계가 두 세포 중 어두운 쪽보다 이 비율 이상 어둡지 않으면 「경계 약함」.')
        f.addRow('경계 대비 기준', self.binuc)
        self.exclude_weak.toggled.connect(lambda on: theme.show_rows(f, [self.binuc], on))
        theme.show_rows(f, [self.binuc], False)
        self.cell_state = theme.StatusLabel(kind='info')
        self.cell_state.setWordWrap(True)
        f.addRow(self.cell_state)
        lay.addWidget(box)

        # 2 미토 분할
        box = QGroupBox('2  미토 분할')
        f = QFormLayout(box)
        self.method_group = QButtonGroup(self)
        mv = QWidget()
        ml = QVBoxLayout(mv)
        ml.setContentsMargins(0, 0, 0, 0)
        self.method_btns = {}
        for i, (key, text) in enumerate(M.METHODS):
            b = QRadioButton(text)
            self.method_group.addButton(b, i)
            self.method_btns[key] = b
            ml.addWidget(b)
        self.method_btns['split'].setChecked(True)
        f.addRow('방법', mv)
        self.thr_mito = AutoField(0, 1000, 1, 1, slider=True)
        self.thr_mito.spin.setToolTip('전처리한 미토 채널(rolling ball 1.5 µm, σ 0.7 px)의 임계값. 자동 = 세포마다 '
                                      '국소 평균 AND 0.5 × Otsu (조각 분할) / 세포마다 Otsu (MiNA 기본).')
        f.addRow('임계값', self.thr_mito.widget)
        self.min_mito = QDoubleSpinBox()
        self.min_mito.setRange(0, 10)
        self.min_mito.setDecimals(2)
        self.min_mito.setSingleStep(0.01)
        self.min_mito.setValue(0.05)
        self.min_mito.setSuffix(' µm²')
        f.addRow('최소 조각', self.min_mito)
        self.mito_state = theme.StatusLabel(kind='info')
        self.mito_state.setWordWrap(True)
        f.addRow(self.mito_state)
        lay.addWidget(box)

        # 3 관심 단백질
        box = QGroupBox('3  관심 단백질')
        f = QFormLayout(box)
        self.poi_form = f
        self.green_bg = AutoField(0, 100000, 2, 0.5)
        self.green_bg.spin.setToolTip('관심 단백질 채널에서 빼는 배경. 자동 = 세포 사이 어두운 틈의 값 '
                                      '(σ 4 px 평활 영상의 1 백분위).')
        f.addRow('배경', self.green_bg.widget)
        self.green_pos = QDoubleSpinBox()
        self.green_pos.setRange(0, 100)
        self.green_pos.setDecimals(1)
        self.green_pos.setValue(2.0)
        self.green_pos.setSuffix(' % 세포질')
        self.green_pos.setToolTip('밝은 green이 세포질의 이 비율 이상을 덮으면 green+ 세포.')
        f.addRow('green+ 기준', self.green_pos)
        self.sens = QDoubleSpinBox()
        self.sens.setRange(0.1, 10)
        self.sens.setDecimals(2)
        self.sens.setSingleStep(0.1)
        self.sens.setValue(1.0)
        self.sens.setSuffix(' ×')
        self.sens.setToolTip('자동 점 임계값에 곱하는 값 (1보다 크면 더 밝은 점만).')
        f.addRow('점 (puncta) 민감도', self.sens)
        self.thr_puncta = AutoField(0, 100000, 1, 1)
        self.thr_puncta.spin.setToolTip('배경을 뺀 green의 top-hat 임계값. 자동 = max(Otsu, 중앙값 + 6 MAD) × 민감도 '
                                        '(이미지마다 하나).')
        f.addRow('점 임계값', self.thr_puncta.widget)
        self.poi_state = theme.StatusLabel(kind='info')
        self.poi_state.setWordWrap(True)
        f.addRow(self.poi_state)
        self.poi_box = box
        lay.addWidget(box)

        # 4 표시
        box = QGroupBox('4  표시')
        v = QVBoxLayout(box)
        chips = QWidget()
        fl = FlowLayout(chips)
        fl.setContentsMargins(0, 0, 0, 0)
        self.layer_on = {}
        for key, text, _c in LAYERS:
            c = theme.chip(QCheckBox(text))
            c.setChecked(key not in ('mito',))
            c.toggled.connect(lambda _: self.draw())
            self.layer_on[key] = c
            fl.addWidget(c)
        self.layer_on['mito'].setChecked(True)
        v.addWidget(chips)
        lay.addWidget(box)

        # 5 결과
        box = QGroupBox('5  결과')
        v = QVBoxLayout(box)
        self.state = theme.StatusLabel(kind='info')
        self.state.setWordWrap(True)
        v.addWidget(self.state)
        chips = QWidget()
        fl = FlowLayout(chips)
        fl.setContentsMargins(0, 0, 0, 0)
        self.table_group = QButtonGroup(self)
        self.table_btns = {}
        for i, (key, text) in enumerate(TABLES):
            b = QRadioButton(text)
            self.table_group.addButton(b, i)
            self.table_btns[key] = b
            b.toggled.connect(lambda on: on and hasattr(self, 'table') and self._fill_table())
            fl.addWidget(b)
        self.table_btns['cells'].setChecked(True)
        v.addWidget(chips)
        self.table = QTableWidget(0, 6)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumHeight(200)
        self.table.itemSelectionChanged.connect(self._picked)
        v.addWidget(self.table)
        self.corr_btn = QPushButton('상관 히트맵 ›')
        self.corr_btn.setToolTip('그래프 편집 창에서 mitoROI · 세포 표로 상관 행렬 그래프를 만듭니다.')
        self.corr_btn.clicked.connect(lambda: self.open_graph('corr'))
        self.group_btn = QPushButton('그룹 비교 ›')
        self.group_btn.setToolTip('그래프 편집 창에서 mitoROI · 세포 표로 그룹 사이 상관 비교를 만듭니다.')
        self.group_btn.clicked.connect(lambda: self.open_graph('corrcmp'))
        v.addWidget(_row(self.corr_btn, self.group_btn, None))
        self.load_btn = QPushButton('Mito Analyzer 결과 불러오기…')
        self.load_btn.setToolTip('Mito Analyzer 결과 폴더의 _per_cell.csv (와 _per_mito, _green_puncta)를 현재 '
                                 '이미지에 불러옵니다.')
        self.load_btn.clicked.connect(self.load_dialog)
        v.addWidget(_row(self.load_btn, None))
        lay.addWidget(box)
        lay.addStretch(1)
        self.poi_ch.currentIndexChanged.connect(lambda _: self._poi_rows())

    # ---- settings ------------------------------------------------------------

    def settings(self) -> M.MitoSettings:
        method = next(k for k, b in self.method_btns.items() if b.isChecked())
        return M.MitoSettings(
            mito_channel=self.mito_ch.currentData() or '', poi_channel=self.poi_ch.currentData() or '',
            include_edge_cells=self.include_edge.isChecked(), exclude_weak=self.exclude_weak.isChecked(),
            binuc_tau=self.binuc.value(), mito_method=method, thr_mito=self.thr_mito.value(),
            min_mito_area_um2=self.min_mito.value(), green_bg=self.green_bg.value(),
            green_pos_percent=self.green_pos.value(), puncta_sensitivity=self.sens.value(),
            thr_puncta=self.thr_puncta.value())

    def _poi_rows(self):
        on = bool(self.poi_ch.currentData())
        for w in (self.green_bg.widget, self.green_pos, self.sens, self.thr_puncta.widget):
            w.setEnabled(on)
        if not on:
            self.poi_state.set_kind('info')
            self.poi_state.setText('관심 단백질 채널 없음: 미토 형태만 잽니다.')

    def status(self, msg):
        self.win.statusBar().showMessage(msg)

    # ---- run ------------------------------------------------------------------

    def run(self, item, s: M.MitoSettings | None = None) -> M.MitoResult:
        s = s or self.settings()
        if not s.mito_channel or s.mito_channel not in item.channels:
            guess = next((c for c in item.channels if 'mito' in c.lower() or 'red' in c.lower()), None)
            s.mito_channel = guess or item.channels[0]
        if s.poi_channel and s.poi_channel not in item.channels:
            s.poi_channel = ''
        cells = item.cells
        if cells is None or not len(cells):
            raise ValueError('세포 ROI가 없습니다. 세포질 ROI 탭에서 먼저 세포를 찾으세요.')
        planes = np.asarray(item.planes(), float)
        return M.analyze(planes, list(item.channels), cells, item.pixel_um, s)

    def run_current(self, item=None):
        it = item or self.win.current
        if it is None:
            return None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            it.mito = self.run(it)
        except Exception as exc:
            traceback.print_exc()
            QApplication.restoreOverrideCursor()
            self.status(f'mitoROI 실패: {exc}')
            return None
        QApplication.restoreOverrideCursor()
        self._after(it)
        return it.mito

    def run_all(self):
        done = 0
        for it in list(self.win.items):
            if it.cells is None or not len(it.cells):
                continue
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                it.mito = self.run(it)
                done += 1
            except Exception as exc:
                traceback.print_exc()
                self.status(f'{it.label}: mitoROI 실패 ({exc})')
            finally:
                QApplication.restoreOverrideCursor()
            self.win.statusBar().showMessage(f'mitoROI {done}개 …', 1500)
            QApplication.processEvents()
        self.status(f'mitoROI: 이미지 {done}개를 분석했습니다.')
        self.refresh()
        self.win.set_dirty(True)
        self.win.update_tab_badges()
        return done

    def _after(self, it):
        r = it.mito
        u = r.used
        self.status(f'mitoROI ({it.label}): 세포 {u.get("n_analysed", 0)}개, 미토 조각 {u.get("n_mito", 0)}개, '
                    f'점 {len(r.puncta)}개')
        self.win.set_dirty(True)
        self.refresh()
        self.win.update_tab_badges()
        self.win.live_box.schedule()

    # ---- image ----------------------------------------------------------------

    def bind(self, item):
        self.item = item
        for cb, none in ((self.mito_ch, False), (self.poi_ch, True)):
            keep = cb.currentData()
            cb.blockSignals(True)
            cb.clear()
            if none:
                cb.addItem('없음', '')
            for name in (item.channels if item is not None else []):
                cb.addItem(name, name)
            i = cb.findData(keep)
            cb.setCurrentIndex(max(i, 0))
            cb.blockSignals(False)
        if item is not None:
            ch = list(item.channels)
            if self.poi_ch.currentIndex() == 0 and len(ch) >= 2:
                guess = next((c for c in ch if c.lower() in ('green', 'poi', 'gfp')), ch[1])
                if guess != self.mito_ch.currentData():
                    self.poi_ch.setCurrentIndex(self.poi_ch.findData(guess))
        self._poi_rows()
        self.refresh()

    def refresh(self):
        it = self.item
        r = it.mito if it is not None else None
        n = len(it.cells) if it is not None and it.cells is not None else 0
        if it is None:
            self.cell_state.set_kind('info')
            self.cell_state.setText('이미지가 없습니다.')
        elif not n:
            self.cell_state.set_kind('warning')
            self.cell_state.setText('세포 ROI가 없습니다. 세포질 ROI 탭에서 먼저 세포를 찾으세요.')
        elif r is not None and r.source == 'app':
            u = r.used
            self.cell_state.set_kind('success')
            self.cell_state.setText(f'세포 {u.get("n_cells", n)}개 · {u.get("n_analysed", 0)}개 분석 (가장자리 '
                                    f'{u.get("n_edge", 0)}, 경계 약한 이웃 {u.get("n_weak", 0)})')
        else:
            self.cell_state.set_kind('info')
            self.cell_state.setText(f'세포 {n}개 · 분석 실행을 누르세요.')
        if r is not None:
            u = r.used
            self.thr_mito.show_used(u.get('mito_threshold') if isinstance(u.get('mito_threshold'), float) else None)
            rng = u.get('mito_threshold_range')
            how = (f' · 세포당 임계값 {rng[0]:.0f}–{rng[1]:.0f} (자동)' if rng else
                   ' · 세포마다 적응 임계값 (자동)' if u.get('mito_threshold') == 'auto' else
                   f' · 임계값 {u.get("mito_threshold")}')
            self.mito_state.set_kind('success')
            self.mito_state.setText(f'미토 조각 {len(r.mito):,}개' + (how if r.source == 'app' else ' · 불러옴'))
            if r.settings.get('poi_channel') or r.puncta:
                self.green_bg.show_used(u.get('green_background'))
                self.thr_puncta.show_used(u.get('puncta_threshold'))
                c = r.status_counts()
                self.poi_state.set_kind('success')
                self.poi_state.setText(f'green+ {c.get("positive", 0)}개 · green− {c.get("negative", 0)}개 · '
                                       f'점 {len(r.puncta):,}개')
        else:
            self.mito_state.set_kind('info')
            self.mito_state.setText('아직 분석하지 않았습니다.')
            if self.poi_ch.currentData():
                self.poi_state.set_kind('info')
                self.poi_state.setText('아직 분석하지 않았습니다.')
        self._fill_table()
        self.draw()

    def _table_key(self):
        return next(k for k, b in self.table_btns.items() if b.isChecked())

    def _fill_table(self):
        it = self.item
        r = it.mito if it is not None else None
        key = self._table_key()
        rows = getattr(r, key) if r is not None else []
        cols = TABLE_COLS[key]
        self._rows = rows
        self.table.blockSignals(True)
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels([h for _c, h in cols])
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, (c, _h) in enumerate(cols):
                v = row.get(c, '')
                if isinstance(v, bool):
                    v = '예' if v else ''
                elif isinstance(v, float):
                    v = '' if v != v else f'{v:.3g}'
                elif c == 'green_status':
                    v = {'positive': '+', 'negative': '−'}.get(v, v)
                self.table.setItem(i, j, QTableWidgetItem(str(v)))
        self.table.blockSignals(False)
        if r is None:
            self.state.set_kind('info')
            self.state.setText('결과가 없습니다.')
        else:
            self.state.set_kind('success')
            self.state.setText(f'세포 {len(r.cells)} · 미토 조각 {len(r.mito):,} · 점 {len(r.puncta):,}' +
                               (' · 불러옴 (Mito Analyzer)' if r.source != 'app' else ''))

    def _picked(self):
        rows = self.table.selectionModel().selectedRows()
        row = self._rows[rows[0].row()] if rows and rows[0].row() < len(self._rows) else None
        self._sel = row.get('cell') if row else None
        self.draw()

    # ---- canvas -----------------------------------------------------------------

    def _clear(self):
        sc = self.win.canvas.scene()
        for x in self._scene:
            sc.removeItem(x)
        self._scene = []

    def draw(self):
        self._clear()
        it = self.win.current
        if it is None or it is not self.item or it.mito is None or not self.win.tab_current('mito_tab'):
            return
        r = it.mito
        sc = self.win.canvas.scene()
        off = self.win._view_offset() if hasattr(self.win, '_view_offset') else (0, 0)
        if r.layers:
            shape = next(iter(r.layers.values())).shape
            rgba = np.zeros(shape + (4,), np.uint8)
            for key, _t, col in LAYERS:
                if col is None or not self.layer_on[key].isChecked() or key not in r.layers:
                    continue
                m = np.asarray(r.layers[key], bool)
                if key in ('ends', 'junctions'):
                    from scipy import ndimage as ndi
                    m = ndi.binary_dilation(m, iterations=1)
                rgba[m] = col
            img = QImage(rgba.data, shape[1], shape[0], 4 * shape[1], QImage.Format.Format_RGBA8888).copy()
            pix = QGraphicsPixmapItem(QPixmap.fromImage(img))
            pix.setOffset(-off[0], -off[1])
            pix.setZValue(13)
            sc.addItem(pix)
            self._scene.append(pix)
        cells = it.cells
        if cells is not None and (self.layer_on['numbers'].isChecked() or self._sel):
            from skimage import measure
            done = {row['cell'] for row in r.cells}
            for rp in measure.regionprops(cells.labels):
                name = f'cell{rp.label:02d}'
                if self._sel == name:
                    for loop in measure.find_contours(np.pad(cells.labels == rp.label, 1).astype(float), 0.5):
                        from PySide6.QtGui import QPainterPath
                        from PySide6.QtCore import QPointF
                        path = QPainterPath(QPointF(loop[0][1] - 1 - off[0], loop[0][0] - 1 - off[1]))
                        for y, x in loop[1:]:
                            path.lineTo(QPointF(x - 1 - off[0], y - 1 - off[1]))
                        p = QGraphicsPathItem(path)
                        pen = QPen(QColor(255, 220, 0))
                        pen.setCosmetic(True)
                        pen.setWidthF(2.5)
                        p.setPen(pen)
                        p.setZValue(15)
                        sc.addItem(p)
                        self._scene.append(p)
                if self.layer_on['numbers'].isChecked():
                    t = QGraphicsSimpleTextItem(f'{rp.label:02d}')
                    t.setBrush(QColor(255, 255, 255) if name in done else QColor(160, 160, 160))
                    t.setFlag(QGraphicsSimpleTextItem.GraphicsItemFlag.ItemIgnoresTransformations)
                    font = t.font()
                    font.setPointSize(14)
                    font.setBold(True)
                    t.setFont(font)
                    t.setPos(rp.centroid[1] - off[0], rp.centroid[0] - off[1])
                    t.setZValue(15)
                    sc.addItem(t)
                    self._scene.append(t)

    # ---- tables ------------------------------------------------------------------

    def data_tables(self):
        """(name, 점 하나 =, rows) of every analysed image."""
        out = {k: [] for k in DATA_NAMES}
        for it in self.win.items:
            r = getattr(it, 'mito', None)
            if r is None:
                continue
            head = {'image': it.label, 'image_id': it.image_id, 'group': it.group or ''}
            for k in DATA_NAMES:
                out[k] += [{**head, **row} for row in getattr(r, k)]
        return [(DATA_NAMES[k][0], DATA_NAMES[k][1], out[k]) for k in DATA_NAMES]

    def open_graph(self, kind='corr'):
        """상관 히트맵 / 그룹 비교: a 상관 행렬 (or 상관 비교 by image group)
        of the mitoROI · 세포 table in the graph window."""
        gw = self.win.graph_window()
        gw.new_doc()
        d = gw.load_source('mito')
        if d is None:
            return None
        if kind == 'corrcmp':
            gw.spec.chart = 'corrcmp'
            gw.spec.calc.group = 'group'
            groups = sorted({it.group for it in self.win.items if it.group and it.mito is not None})
            if len(groups) >= 2:
                gw.spec.calc.a, gw.spec.calc.b = groups[0], groups[1]
        gw._changed()
        gw.show()
        gw.raise_()
        return d

    # ---- Mito Analyzer results --------------------------------------------------------

    def load_dialog(self):
        it = self.win.current
        if it is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Mito Analyzer 결과 불러오기', str(it.path.parent),
                                              'per_cell CSV (*_per_cell.csv);;CSV (*.csv)')
        if not path:
            return
        try:
            n = self.load_results(Path(path), it)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, '불러오기 실패', str(exc))
            return
        self.status(f'Mito Analyzer 결과: 세포 {n}개 ({Path(path).name})')

    def load_results(self, path: Path, item=None) -> int:
        """``<name>_per_cell.csv`` (+ ``_per_mito``, ``_green_puncta`` beside it)
        onto the image whose name matches ``<name>``, else ``item``."""
        path = Path(path)
        stem = path.name[:-len('_per_cell.csv')] if path.name.endswith('_per_cell.csv') else path.stem
        target = next((it for it in self.win.items if stem and (stem == it.path.stem or stem == it.label
                                                                or it.label.startswith(stem))), None) or item
        if target is None:
            raise ValueError('붙일 이미지가 없습니다.')
        cells = M.read_csv(path)
        mito = M.read_csv(path.parent / f'{stem}_per_mito.csv') if (path.parent / f'{stem}_per_mito.csv').exists() \
            else []
        pun = path.parent / f'{stem}_green_puncta.csv'
        puncta = M.read_csv(pun) if pun.exists() else []
        target.mito = M.MitoResult(cells=cells, mito=mito, puncta=puncta, source='Mito Analyzer',
                                   settings={'poi_channel': 'green' if puncta else ''})
        if target is self.item:
            self.refresh()
        self.win.update_tab_badges()
        return len(cells)

    # ---- export ----------------------------------------------------------------------

    def save_item(self, it, folder: Path, stem: str, rois=True) -> list:
        """Mito Analyzer's file names: _per_cell / _per_mito / _green_puncta /
        _correlations CSVs, _mito_RoiSet.zip (one ROI per mito object)."""
        r = it.mito
        if r is None:
            return []
        folder.mkdir(parents=True, exist_ok=True)
        out = []
        for key, suf in (('cells', 'per_cell'), ('mito', 'per_mito'), ('puncta', 'green_puncta')):
            p = folder / f'{stem}_{suf}.csv'
            if M.write_csv(p, getattr(r, key)):
                out.append(p)
        if r.cells:
            try:
                p = folder / f'{stem}_correlations.csv'
                if M.write_csv(p, M.correlations(r.cells, r.mito)):
                    out.append(p)
            except Exception:  # noqa: BLE001
                traceback.print_exc()
        if rois and r.mlab is not None and np.asarray(r.mlab).max():
            p = folder / f'{stem}_mito_RoiSet.zip'
            if save_label_rois(np.asarray(r.mlab), 'm', p):
                out.append(p)
        return out


def save_label_rois(lab, prefix, path) -> bool:
    """One polygon ROI per label (Mito Analyzer pipeline.write_label_rois)."""
    import roifile
    from skimage import measure

    rois = []
    for rp in measure.regionprops(lab):
        c = max(measure.find_contours(np.pad(lab[rp.slice] == rp.label, 1).astype(float), 0.5), key=len) - 1
        c = c + [rp.slice[0].start, rp.slice[1].start]
        roi = roifile.ImagejRoi.frompoints(np.c_[c[:, 1], c[:, 0]])
        roi.roitype = roifile.ROI_TYPE.POLYGON
        roi.name = f'{prefix}{rp.label:04d}'
        rois.append(roi)
    if not rois:
        return False
    if Path(path).exists():
        Path(path).unlink()
    roifile.roiwrite(path, rois)
    return True


def mito_live(panel):
    it = panel.item
    r = it.mito if it is not None else None
    if r is None:
        return None
    c = r.status_counts()
    fp = [x.get('footprint_fraction') for x in r.cells if isinstance(x.get('footprint_fraction'), float)]
    tiles = [('세포', len(r.cells)), ('미토 조각', len(r.mito)), ('점', len(r.puncta)),
             ('green+', c.get('positive', 0)), ('footprint 평균', f'{np.mean(fp):.3f}' if fp else '–')]
    return tiles, r
