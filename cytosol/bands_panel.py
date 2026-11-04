"""핵 → 세포막 등거리 띠 (in the 세포질 ROI tab since v0.57): the cytosol of
every cell cut into bands of equal distance from the nucleus
(cytosol.radial), measured per band, drawn as a graph whose axes can be any
measured column, and (optionally) the band edges drawn on the image."""

from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .intensity import make_regions
from .lut import item_stem
from .measure_box import MeasureBox
from .radial import MODES, BandSettings, band_outlines, draw_bands, measure_bands, numeric_columns

# widgets of this panel that projects before v0.57 kept under the 강도 측정 panel
LEGACY_KEYS = ('band_mode', 'band_start', 'band_stop', 'band_n', 'show_bands', 'graph_x', 'graph_y')


class BandMeasureBox(MeasureBox):
    """MeasureBox whose table changes also redraw the band graph."""

    def __init__(self, *a, changed=None, **k):
        self.changed = changed
        super().__init__(*a, **k)

    def _fill_table(self):
        super()._fill_table()
        if self.changed is not None:
            self.changed()


class BandsPanel(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.item = None
        self._hidden = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self.draw_regions)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        # ---- distance bands from the nucleus to the cell edge ----
        band = QGroupBox('핵 → 세포막 등거리 띠')
        bl = QFormLayout(band)
        note = QLabel('세포질을 핵에서의 거리가 같은 띠로 나눠 띠마다 강도(와 입자)를 잽니다. '
                      '핵이 있는 세포만 잽니다.')
        note.setWordWrap(True)
        theme.hint(note)
        bl.addRow(note)
        self.band_mode = QComboBox()
        for key, text in MODES:
            self.band_mode.addItem(text, key)
        self.band_mode.setToolTip(
            '상대 거리: 핵에서의 거리 / (핵에서의 거리 + 세포 경계까지의 거리). 세포 크기와 '
            '상관없이 0 = 핵 경계, 1 = 세포 경계.\n'
            '핵 경계에서의 거리: µm (보정 정보가 없으면 픽셀).')
        bl.addRow('거리', self.band_mode)
        self.band_start = QDoubleSpinBox()
        self.band_stop = QDoubleSpinBox()
        for w in (self.band_start, self.band_stop):
            w.setRange(0, 10000)
            w.setDecimals(2)
            w.setSingleStep(0.1)
        self.band_start.setValue(0.0)
        self.band_stop.setValue(1.0)
        row = QHBoxLayout()
        row.addWidget(self.band_start, 1)
        row.addWidget(QLabel('–'))
        row.addWidget(self.band_stop, 1)
        bl.addRow('범위', row)
        self.band_n = QSpinBox()
        self.band_n.setRange(1, 200)
        self.band_n.setValue(10)
        bl.addRow('띠 개수', self.band_n)
        self.show_bands = QCheckBox('이미지에 띠 표시 (청록색)')
        self.show_bands.setToolTip('켜면 세포질 ROI 탭에서 띠의 경계를 이미지 위에 그립니다.')
        self.show_bands.toggled.connect(self.schedule_bands)
        bl.addRow(self.show_bands)
        self.band_mode.currentIndexChanged.connect(self._band_mode_changed)
        for w in (self.band_start, self.band_stop):
            w.valueChanged.connect(self.schedule_bands)
        self.band_n.valueChanged.connect(self.schedule_bands)
        lay.addWidget(band)

        self._axes_wanted = ('distance_rel', None)  # kept while the columns change
        self.bands_measure = BandMeasureBox(
            win, 'roi_tab', self.band_regions_for, 'bands', '등거리 띠 강도 측정',
            rows=self._band_rows, key=lambda: self.band_settings(), changed=self.draw_graph)
        lay.addWidget(self.bands_measure, 1)
        # the 세포질 ROI tab's main action stays its own 지금 측정 (at most two filled buttons a tab)
        for b in self.bands_measure.findChildren(QPushButton):
            b.setProperty('hig_prominent', False)

        graph = QGroupBox('그래프')
        gl = QVBoxLayout(graph)
        row = QHBoxLayout()
        self.graph_x = QComboBox()
        self.graph_y = QComboBox()
        row.addWidget(QLabel('x'))
        row.addWidget(self.graph_x, 1)
        row.addWidget(QLabel('y'))
        row.addWidget(self.graph_y, 1)
        gl.addLayout(row)
        for w in (self.graph_x, self.graph_y):
            w.setToolTip('측정한 열 중 아무거나 고를 수 있습니다 (입자를 정했으면 입자 개수, '
                         '입자 면적 비율, 채널별 입자 평균도).')
            w.currentIndexChanged.connect(self._graph_axis_changed)
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from matplotlib.figure import Figure
        self.fig = Figure(figsize=(4, 3), layout='constrained')
        self.ax = self.fig.add_subplot(111)
        self.plot = FigureCanvasQTAgg(self.fig)
        self.plot.setMinimumHeight(260)
        gl.addWidget(self.plot, 1)
        hint = QLabel('회색: 세포마다, 빨강: 세포 평균 ± SD (띠별). 표에서 ‘모든 이미지’를 고르면 '
                      '일괄 측정 결과를 그립니다.')
        hint.setWordWrap(True)
        theme.hint(hint)
        gl.addWidget(hint)
        lay.addWidget(graph, 1)

    def schedule(self, *_):
        self._timer.start()
        self.bands_measure.schedule()

    def schedule_bands(self, *_):
        self.schedule()

    def overlay_changed(self, hidden=False):
        self._hidden = hidden
        self.schedule()

    def visible_tab(self) -> bool:
        return self.bands_measure.visible_tab()

    def draw_regions(self):
        """Band edges on the image while the 세포질 ROI tab is shown; the
        강도 측정 tab draws its own regions."""
        if self.win.tab_current('intensity_tab'):
            return
        canvas = self.win.canvas
        it = self.win.current
        if (not self.show_bands.isChecked() or self._hidden or it is None or it.cells is None
                or not len(it.cells) or not self.visible_tab() or self.win._stack_on()):
            canvas.show_regions([])
            return
        try:
            canvas.show_regions(band_outlines(it.cells, it.pixel_um, self.band_settings()))
        except Exception:
            traceback.print_exc()

    def bind(self, item):
        self.item = item
        self.bands_measure.bind(item)
        self.schedule()

    def band_settings(self) -> BandSettings:
        return BandSettings(self.band_mode.currentData(), self.band_start.value(),
                            self.band_stop.value(), self.band_n.value())

    def _band_mode_changed(self, _):
        if self.band_mode.currentData() == 'relative':
            self.band_start.setValue(0.0)
            self.band_stop.setValue(1.0)
        else:
            self.band_start.setValue(0.0)
            self.band_stop.setValue(10.0)
        self.schedule_bands()

    def band_regions_for(self, item):
        """Only to hand the measurement the image's particles when it has them."""
        has_p = item.particles is not None or item.particle_settings is not None
        return make_regions([], ['cyto | particle'] if has_p else ['cyto'])

    def _band_rows(self, it, cells, particles, channels, stats):
        return measure_bands(it.planes(), cells, it.channels, it.pixel_um, self.band_settings(),
                             particles, channels, stats)

    def _graph_axis_changed(self, _):
        if not self._filling:
            self._axes_wanted = (self.graph_x.currentText(), self.graph_y.currentText())
            self.draw_graph()

    _filling = False

    def draw_graph(self):
        rows = self.bands_measure._rows_shown()[0]
        cols = numeric_columns(rows)
        cols = [c for c in cols if not c.endswith(('_from', '_to'))] + \
            [c for c in cols if c.endswith(('_from', '_to'))]
        self._filling = True
        try:
            for w, want, default in ((self.graph_x, self._axes_wanted[0], self._default_x(cols)),
                                     (self.graph_y, self._axes_wanted[1], self._default_y(cols))):
                w.clear()
                w.addItems(cols)
                pick = want if want in cols else default
                if pick in cols:
                    w.setCurrentIndex(cols.index(pick))
        finally:
            self._filling = False
        x, y = self.graph_x.currentText(), self.graph_y.currentText()
        try:
            if rows and x and y:
                draw_bands(self.ax, rows, x, y)
            else:
                self.ax.clear()
        except Exception:
            traceback.print_exc()
            self.ax.clear()
        self.plot.draw_idle()

    @staticmethod
    def _default_x(cols):
        return next((c for c in cols if c.startswith('distance') and not c.endswith(('_from', '_to'))),
                    cols[0] if cols else None)

    @staticmethod
    def _default_y(cols):
        return next((c for c in cols if c.endswith('_Mean') and '_particle_' not in c), None)

    def save_plot(self):
        rows = self.bands_measure._rows_shown()[0]
        if not rows:
            QMessageBox.information(self, '등거리 띠 그래프', '먼저 등거리 띠를 측정하세요.')
            return
        it = self.win.current
        default = str(it.path.with_name(f'{item_stem(it)}_bands.png')) if it is not None else 'bands.png'
        path, flt = QFileDialog.getSaveFileName(
            self, '그래프 저장', default, 'PNG (*.png);;PDF (*.pdf);;SVG (*.svg);;TIFF (*.tif)')
        if not path:
            return
        if not Path(path).suffix:
            path += {'PDF': '.pdf', 'SVG': '.svg', 'TIF': '.tif'}.get(flt[:3], '.png')
        try:
            self.fig.savefig(path, dpi=300)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, '저장 실패', str(exc))
            return
        self.win.statusBar().showMessage(f'등거리 띠 그래프 저장: {path}')
