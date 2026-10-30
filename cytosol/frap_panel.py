"""FRAP 측정 tab: bleach / control / background ROIs on the image (placed
automatically, dragged by hand), the recovery curve of the current image, the
mean curve of each image group with error bars, and the usual FRAP numbers
(cytosol.frap)."""

from __future__ import annotations

import json
import traceback
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from . import frap
from .flow import FlowLayout
from .frap import ROI_NAMES, FrapCurve, FrapState
from .lut import item_folder, item_stem

NO_GROUP = 'No group'  # images not put in a group (also the plot legend)
SLIDER_STEPS = 1000


def _row(*widgets, stretch=True) -> QHBoxLayout:
    r = QHBoxLayout()
    for w in widgets:
        r.addWidget(w)
    if stretch:
        r.addStretch()
    return r


def _auto(tip) -> QCheckBox:
    b = QCheckBox('자동')
    b.setToolTip(tip)
    return b


class FrapPanel(QWidget):
    """The window gives it the current image (bind) and draws the ROIs it
    reports (rois_for_view); dragging one on the canvas calls drag_preview
    while it moves and move_roi when it is let go."""

    def __init__(self, win, parent=None):
        super().__init__(parent)
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from matplotlib.figure import Figure

        self.win = win
        self.item = None
        self._binding = False
        self._stacks = {}  # (id(item), channel, z) -> (T, Y, X) float32, the latest few
        self._curves = {}  # id(item) -> (key, FrapCurve)
        self._tracks = {}  # (id(item), channel, z, mode, centre, window) -> (T, 2) movement
        self._drag = None  # (name, dx, dy) while a ROI is dragged
        self.curve: FrapCurve | None = None
        lay = QVBoxLayout(self)

        help_ = QLabel('bleach 실험의 회복 곡선: 값 = (Bleach − Background) / (Control − Background). '
                       'Bleach ROI는 파일에 기록된 bleach 영역(없으면 가장 크게 어두워진 곳), Control은 '
                       '주변 응집체 중 강도가 가장 안정된 곳(또는 같은 응집체의 bleach되지 않은 부분), '
                       'Background는 Bleach ROI와 같은 크기로 응집체 '
                       '신호가 없는 가까운 곳에 자동으로 놓입니다. 이미지 위에서 ROI를 끌어 옮기면 값과 '
                       '그래프가 바로 바뀝니다.')
        help_.setWordWrap(True)
        help_.setStyleSheet('color: gray; font-size: 11px;')
        lay.addWidget(help_)

        # ---- data (same for every image) ----
        data = QGroupBox('데이터')
        fl = QFormLayout(data)
        self.channel = QComboBox()
        self.channel.setToolTip('측정할 채널 (모든 이미지에 같은 이름의 채널을 씁니다).')
        self.channel.currentIndexChanged.connect(self._channel_changed)
        fl.addRow('채널', self.channel)
        self.normalize = QCheckBox('bleach 전 강도로 정규화')
        self.normalize.setChecked(True)
        self.normalize.setToolTip('켜면 bleach 전 값을 1로 정규화합니다 (Phair의 double normalization).\n'
                                  'bleach 전 = 1, 직후 = 0: (값 − 직후) / (bleach 전 평균 − 직후), '
                                  'Recovery (%)로 표시\n'
                                  '첫 프레임 / bleach 전 프레임 평균: 그 값으로 나눔')
        self.norm_ref = QComboBox()
        self.norm_ref.addItem('bleach 전 = 1, 직후 = 0', 'full')
        self.norm_ref.addItem('첫 프레임 = 1', 'first')
        self.norm_ref.addItem('bleach 전 프레임 평균 = 1', 'pre')
        for w in (self.normalize, self.norm_ref):
            (w.toggled if isinstance(w, QCheckBox) else w.currentIndexChanged).connect(self._settings_changed)
        fl.addRow(_row(self.normalize, self.norm_ref))
        self._bf = QSpinBox()
        self._bf.setRange(1, 1)
        self._bf.setToolTip('bleach 바로 다음 프레임 (1부터). 이 프레임부터 회복 곡선을 피팅합니다.')
        self._bf_auto = _auto('파일의 bleach 기록, 없으면 Bleach ROI 강도가 가장 크게 떨어진 프레임')
        self._bf.valueChanged.connect(self._bf_changed)
        self._bf_auto.toggled.connect(self._bf_auto_toggled)
        fl.addRow('bleach 후 첫 프레임', _row(self._bf, self._bf_auto))
        self.drift = QCheckBox('드리프트 보정 (ROI가 움직임을 따라감)')
        self.drift.setChecked(True)
        self.drift.setToolTip('시간에 따라 응집체나 시야가 움직이면 프레임마다 그 움직임을 찾아 ROI를 '
                              '함께 옮겨 측정합니다 (이미지는 바꾸지 않음). 끄면 ROI가 모든 프레임에서 '
                              '같은 자리에 있습니다.')
        self.drift_mode = QComboBox()
        self.drift_mode.addItem('ROI 주변 추적', 'roi')
        self.drift_mode.addItem('전체 이미지', 'image')
        self.drift_mode.setToolTip('ROI 주변 추적: Bleach ROI 둘레(Control이 다른 응집체면 그 둘레도 따로)의 '
                                   '움직임을 따라감 (응집체가 움직일 때).\n전체 이미지: 시야 전체의 움직임 '
                                   '(스테이지·시료 드리프트).')
        self.drift_win = QSpinBox()
        self.drift_win.setRange(16, 4096)
        self.drift_win.setSuffix(' px')
        self.drift_win.setToolTip('움직임을 찾는 정사각형 창의 한 변 (ROI 주변 추적)')
        self.drift_win_auto = _auto('ROI 크기의 8배, 최소 128 px')
        self.drift_win_auto.setChecked(True)
        for w in (self.drift, self.drift_win_auto):
            w.toggled.connect(self._drift_changed)
        self.drift_mode.currentIndexChanged.connect(self._drift_changed)
        self.drift_win.valueChanged.connect(self._drift_changed)
        fl.addRow(self.drift)
        fl.addRow(_row(self.drift_mode))
        fl.addRow('추적 창', _row(self.drift_win, self.drift_win_auto))
        self._drift_info = QLabel()
        self._drift_info.setWordWrap(True)
        self._drift_info.setStyleSheet('color: gray; font-size: 11px;')
        fl.addRow(self._drift_info)
        lay.addWidget(data)

        # ---- ROIs of the current image ----
        rbox = QGroupBox('측정 ROI (현재 이미지, 이미지 위에서 끌어 옮기기)')
        rl = QVBoxLayout(rbox)
        self.show_rois = QCheckBox('ROI 표시')
        self.show_rois.setChecked(True)
        self.show_rois.toggled.connect(lambda _: self.win.draw_frap())
        rl.addWidget(self.show_rois)
        self._auto_roi = {}
        self._roi_info = {}
        tips = {'bleach': '파일의 bleach 영역, 없으면 두 프레임 사이에 가장 크게 어두워진 곳',
                'control': '아래에서 고른 곳 (주변의 다른 응집체 중 강도가 가장 안정된 곳 / 같은 응집체의 '
                           'bleach 영역 밖)',
                'background': 'Bleach ROI와 같은 모양·크기로, 응집체 신호가 없는 가장 가까운 곳'}
        colors = {n: '#%02x%02x%02x' % frap.ROI_COLORS[n] for n in ROI_NAMES}
        for n in ROI_NAMES:
            title = QLabel(f'<b style="color:{colors[n]}">■ {frap.ROI_TITLES[n]}</b>')
            b = _auto(f'자동 위치: {tips[n]}. 끌어 옮기면 꺼집니다.')
            b.toggled.connect(lambda on, n=n: self._roi_auto_toggled(n, on))
            self._auto_roi[n] = b
            rl.addLayout(_row(title, b))
            info = QLabel()
            info.setWordWrap(True)
            info.setStyleSheet('color: gray; font-size: 11px;')
            self._roi_info[n] = info
            rl.addWidget(info)
            if n == 'bleach':
                self._file_roi = QComboBox()
                self._file_roi.setToolTip('파일에 bleach 영역이 여러 개일 때 측정할 영역')
                self._file_roi.currentIndexChanged.connect(self._file_roi_changed)
                self._bleach_d = QSpinBox()
                self._bleach_d.setRange(2, 2000)
                self._bleach_d.setSuffix(' px')
                self._bleach_d.setToolTip('찾은 / 직접 둔 bleach 원의 지름 (파일의 bleach 영역은 그 모양 그대로)')
                self._bleach_d_auto = _auto('어두워진 영역의 넓이와 같은 원의 지름')
                self._bleach_d.valueChanged.connect(lambda _: self._size_changed('bleach'))
                self._bleach_d_auto.toggled.connect(lambda _: self._size_changed('bleach'))
                rl.addLayout(_row(self._file_roi))
                self._bleach_d_row = QWidget()  # hidden for the file's own bleach region
                drow = _row(QLabel('지름'), self._bleach_d, self._bleach_d_auto)
                drow.setContentsMargins(0, 0, 0, 0)
                self._bleach_d_row.setLayout(drow)
                rl.addWidget(self._bleach_d_row)
            elif n == 'control':
                self.control_src = QComboBox()
                for key, text in frap.CONTROL_SOURCES.items():
                    self.control_src.addItem(text, key)
                self.control_src.setToolTip(
                    '자동 Control 위치 (모든 이미지):\n주변의 다른 응집체: bleach한 응집체 둘레의 가까운 '
                    '응집체들 중 시간에 따라 강도가 가장 적게 변하는 곳 (변동계수가 가장 작은 곳)\n'
                    '같은 응집체 안: bleach한 응집체에서 bleach 영역 밖의 가장 안쪽')
                self.control_src.currentIndexChanged.connect(self._control_src_changed)
                rl.addLayout(_row(QLabel('위치'), self.control_src))
                self._control_d = QSpinBox()
                self._control_d.setRange(2, 2000)
                self._control_d.setSuffix(' px')
                self._control_d.setToolTip('Control 원의 지름 (Bleach ROI와 같지 않아도 됩니다)')
                self._control_d_auto = _auto('Bleach ROI 크기까지, 응집체 안에 들어가는 가장 큰 원')
                self._control_d.valueChanged.connect(lambda _: self._size_changed('control'))
                self._control_d_auto.toggled.connect(lambda _: self._size_changed('control'))
                rl.addLayout(_row(QLabel('지름'), self._control_d, self._control_d_auto))
        self._thr = QDoubleSpinBox()
        self._thr.setDecimals(1)
        self._thr.setRange(-1e9, 1e9)
        self._thr.setToolTip('이 값 이상(bleach 전 이미지, σ 1 px 가우시안)이 응집체 신호입니다. '
                             'Control과 Background 자동 위치에 씁니다.')
        self._thr_auto = _auto('Bleach ROI 둘레 창 안에서 Otsu threshold')
        self._thr.valueChanged.connect(self._thr_changed)
        self._thr_auto.toggled.connect(self._thr_changed)
        self._thr_slider = QSlider(Qt.Orientation.Horizontal)
        self._thr_slider.setRange(0, SLIDER_STEPS)
        self._thr_slider.valueChanged.connect(self._thr_slid)
        self._thr_range = (0.0, 1.0)
        rl.addLayout(_row(QLabel('응집체 threshold'), self._thr, self._thr_auto))
        rl.addWidget(self._thr_slider)
        reset = QPushButton('모두 자동 배치')
        reset.setToolTip('이 이미지의 ROI·프레임·threshold를 모두 자동으로 되돌립니다.')
        reset.clicked.connect(self.reset_auto)
        self.notes = QLabel()
        self.notes.setWordWrap(True)
        self.notes.setStyleSheet('color: #b36b00; font-size: 11px;')
        rl.addLayout(_row(reset))
        rl.addWidget(self.notes)
        lay.addWidget(rbox)

        # ---- plot ----
        pbox = QGroupBox('그래프')
        pl = QVBoxLayout(pbox)
        self.view = QComboBox()
        self.view.addItem('회복 곡선 (현재 이미지)', 'curve')
        self.view.addItem('ROI 평균 강도 (현재 이미지)', 'raw')
        self.view.addItem('그룹 평균 ± 에러바', 'groups')
        self.view.currentIndexChanged.connect(self._view_changed)
        pl.addWidget(self.view)
        opts = FlowLayout()
        self.error = QComboBox()
        self.error.addItem('SEM', 'sem')
        self.error.addItem('SD', 'sd')
        self.error.setToolTip('그룹 평균의 에러바')
        self.fit = QCheckBox('지수 회복 피팅')
        self.fit.setChecked(True)
        self.fit.setToolTip('y = a·(1 − e^(−k·t)) + c (ImageJ Exponential recovery), bleach 후 프레임')
        self.members = QCheckBox('개별 곡선도 표시')
        for w in (self.error, self.fit, self.members):
            (w.toggled if isinstance(w, QCheckBox) else w.currentIndexChanged).connect(self._replot)
            opts.addWidget(w)
        pl.addLayout(opts)
        # which groups the graph shows (names of the hidden ones, saved with the project)
        self.groups_hidden = QLineEdit()
        self.groups_hidden.setVisible(False)
        self._group_pick = QWidget()
        self._group_flow = FlowLayout(self._group_pick)
        self._group_flow.setContentsMargins(0, 0, 0, 0)
        self._group_checks = {}
        pl.addWidget(self._group_pick)
        self.fig = Figure(figsize=(4, 3), dpi=100, layout='constrained')
        self.ax = self.fig.add_subplot(111)
        self.plot = FigureCanvasQTAgg(self.fig)
        self.plot.setMinimumHeight(260)
        pl.addWidget(self.plot, 1)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.summary.setStyleSheet('font-size: 11px;')
        pl.addWidget(self.summary)
        lay.addWidget(pbox, 1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(40)  # live updates while a ROI is dragged
        self._timer.timeout.connect(self._update_live)
        self._binding = True
        self._drift_changed()
        self._binding = False
        self._show_empty('이미지를 추가하세요.')

    # ---- binding -----------------------------------------------------------

    def bind(self, item):
        self.item = item
        self._binding = True
        try:
            name = self.channel.currentText()
            self.channel.clear()
            if item is not None:
                self.channel.addItems(item.channels)
                i = item.channels.index(name) if name in item.channels else self._default_channel(item)
                self.channel.setCurrentIndex(i)
        finally:
            self._binding = False
        self.refresh()

    @staticmethod
    def _default_channel(item) -> int:
        for i, n in enumerate(item.channels):
            if not any(k in n.upper() for k in ('HT', 'RI', 'BF', 'T-PMT', 'TPMT')):
                return i
        return 0

    def channel_index(self, item) -> int:
        name = self.channel.currentText()
        return item.channels.index(name) if name in item.channels else self._default_channel(item)

    def active(self) -> bool:
        return self.win.tab_current('frap_tab')

    # ---- data --------------------------------------------------------------

    def stack_for(self, item, progress=True) -> np.ndarray:
        """(T, Y, X) of the FRAP channel at the item's Z (MIP / plane), cached."""
        from .prefetch import plane_at

        c = self.channel_index(item)
        key = (id(item), c, item.z)
        if key in self._stacks:
            return self._stacks[key]
        T = item.nt
        out = None
        cursor = progress and T > 1
        if cursor:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            tc = item.time_cache
            for t in range(T):
                planes = tc.get(item, t) if tc is not None else None
                if planes is None:
                    planes = plane_at(item.image, t, item.z) if T > 1 else item.planes()
                p = np.asarray(planes[c], np.float32)
                if out is None:
                    out = np.empty((T,) + p.shape, np.float32)
                out[t] = p
        finally:
            if cursor:
                QApplication.restoreOverrideCursor()
        while len(self._stacks) >= 3:
            self._stacks.pop(next(iter(self._stacks)))
        self._stacks[key] = out
        return out

    def forget(self, item=None):
        """Drop cached stacks / curves (of one image, or all)."""
        if item is None:
            self._stacks.clear()
            self._curves.clear()
            self._tracks.clear()
            return
        for cache in (self._stacks, self._tracks):
            for k in [k for k in cache if k[0] == id(item)]:
                del cache[k]
        self._curves.pop(id(item), None)

    def state_for(self, item, stack=None) -> FrapState:
        """The item's FRAP state with its automatic parts filled in."""
        st = item.frap if isinstance(item.frap, FrapState) else FrapState()
        item.frap = st
        if stack is None:
            stack = self.stack_for(item)
        info = item.image.metadata.get('bleach')
        track = None
        if self.drift.isChecked():
            track = lambda roi: self.drift_for(item, {'bleach': roi}, stack)['bleach']  # noqa: E731
        frap.auto_place(st, stack, item.bleach_rois, frap.file_bleach_frame(info, item.nt),
                        self.control_src.currentData(), track)
        return st

    def _key(self, item, st) -> str:
        return json.dumps([self.channel_index(item), str(item.z), self._norm(),
                           self._drift_key(), self.control_src.currentData(), st.to_dict()],
                          sort_keys=True)

    def _drift_key(self):
        if not self.drift.isChecked():
            return None
        return [self.drift_mode.currentData(),
                None if self.drift_win_auto.isChecked() else self.drift_win.value()]

    def drift_for(self, item, rois: dict, stack=None) -> dict:
        """ROI name -> (T, 2) x, y movement of each frame against the first (px),
        or {} with drift correction off. Background follows the Bleach ROI;
        Control has its own track when it sits away from the Bleach ROI."""
        if not self.drift.isChecked() or 'bleach' not in rois:
            return {}
        if stack is None:
            stack = self.stack_for(item)
        mode = self.drift_mode.currentData()
        c = self.channel_index(item)
        if mode == 'image':
            H, W = stack.shape[1:]
            side = min(512, H, W)  # the middle of the field is enough and keeps it quick
            key = (id(item), c, item.z, 'image', side)
            if key not in self._tracks:
                self._tracks[key] = frap.track_drift(stack, (W / 2, H / 2), side)
            d = self._tracks[key]
            return {n: d for n in ROI_NAMES}
        size = None if self.drift_win_auto.isChecked() else self.drift_win.value()
        b = rois['bleach']
        side = frap.drift_window(b, stack.shape[1:], size)

        def track(roi):
            cx, cy = (int(round(v)) for v in roi.center())
            key = (id(item), c, item.z, 'roi', (cx, cy), side)
            if key not in self._tracks:
                while len(self._tracks) > 40:
                    self._tracks.pop(next(iter(self._tracks)))
                self._tracks[key] = frap.track_drift(stack, (cx, cy), side)
            return self._tracks[key]

        db = track(b)
        out = {'bleach': db, 'background': db, 'control': db}
        ctl = rois.get('control')
        if ctl is not None:
            (bx, by), (cx, cy) = b.center(), ctl.center()
            if max(abs(cx - bx), abs(cy - by)) > side / 4:
                out['control'] = track(ctl)
        return out

    def _norm(self) -> str:
        return self.norm_ref.currentData() if self.normalize.isChecked() else ''

    def curve_for(self, item, rois=None, progress=True) -> FrapCurve | None:
        """Measured curve of an image (rois: other positions, e.g. during a drag)."""
        if item.nt < 2:
            return None
        hit = self._curves.get(id(item))
        if rois is None and hit is not None and isinstance(item.frap, FrapState) \
                and hit[0] == self._key(item, item.frap):
            return hit[1]
        stack = self.stack_for(item, progress)
        st = self.state_for(item, stack)
        key = self._key(item, st) if rois is None else None
        use = dict(st.rois)
        use.update(rois or {})
        # while a ROI is dragged its track is the one of where it was (re-tracked when let go)
        drift = self.drift_for(item, st.rois, stack)
        means = {n: frap.roi_means_tracked(stack, use[n], drift.get(n)) for n in ROI_NAMES}
        b = use['bleach']
        r_um = None
        if b.kind == 'oval' and b.w == b.h and item.pixel_um:
            r_um = b.w / 2 * item.pixel_um
        px = item.pixel_um
        times = np.asarray(item.image.times[:len(stack)], float)
        if len(times) != len(stack) or not np.all(np.diff(times) > 0):
            times = np.arange(len(stack), dtype=float)
        curve = FrapCurve(item.label, item.group or NO_GROUP, times, st.bleach_frame, means,
                          self._norm(), item.channels[self.channel_index(item)],
                          {n: use[n].describe(px) for n in ROI_NAMES}, r_um,
                          dict(item.id_properties(), plane=self._plane_text(item)),
                          drift=drift, drift_mode=self.drift_mode.currentData() if drift else '',
                          control_source=self.control_src.currentData() if st.auto.get('control', True)
                          else 'manual')
        curve.do_fit()
        if key is not None:
            self._curves[id(item)] = (key, curve)
        return curve

    @staticmethod
    def _plane_text(item) -> str:
        return 'MIP' if item.z == 'mip' else f'z {int(item.z) + 1}/{item.nz}' if item.z != 'mid' else 'mid'

    # ---- refresh -------------------------------------------------------------

    def refresh(self):
        """Measure the current image and redraw (only while the tab is shown)."""
        it = self.item
        self.curve = None
        if it is None:
            self._show_empty('이미지를 추가하세요.')
            return
        if it.nt < 2:
            self._sync_widgets(None)
            self._show_empty('시간축(T)이 있는 이미지에서만 FRAP을 측정합니다.')
            return
        if not self.active():
            return  # measured when the tab is opened
        try:
            self.curve = self.curve_for(it)
        except Exception as exc:
            traceback.print_exc()
            self._show_empty(f'FRAP 측정 실패: {exc}')
            return
        self._sync_widgets(it.frap)
        self._show_drift(self.curve)
        self._replot()
        self.win.draw_frap()

    def tab_shown(self):
        if self.item is not None and self.curve is None:
            self.refresh()

    def _show_empty(self, text):
        self.ax.clear()
        self.ax.set_xlabel('Time after bleach (s)')
        self.ax.set_ylabel('Recovery')
        self.ax.grid(True, color='0.88', lw=0.6)
        self.plot.draw_idle()
        self.summary.setText(text)

    def _sync_widgets(self, st):
        """Show the current image's FRAP state in the per-image widgets."""
        self._binding = True
        try:
            it = self.item
            ok = st is not None
            for w in (self._bf, self._bf_auto, self._thr, self._thr_auto, self._thr_slider,
                      self._bleach_d, self._bleach_d_auto, self._control_d, self._control_d_auto,
                      self._file_roi, *self._auto_roi.values()):
                w.setEnabled(ok)
            if not ok:
                for lab in self._roi_info.values():
                    lab.setText('')
                self.notes.setText('')
                return
            self._bf.setRange(1, max(1, it.nt))
            self._bf.setValue(st.bleach_frame + 1)
            self._bf_auto.setChecked(st.bleach_frame_auto)
            self._bf.setEnabled(not st.bleach_frame_auto)
            for n in ROI_NAMES:
                self._auto_roi[n].setChecked(bool(st.auto.get(n, True)))
            files = it.bleach_rois
            self._file_roi.clear()
            for k, b in enumerate(files, 1):
                self._file_roi.addItem(f'파일 bleach 영역 {k}: {b.name}')
            self._file_roi.setCurrentIndex(min(st.file_roi, max(len(files) - 1, 0)))
            self._file_roi.setVisible(len(files) > 1)
            from_file = st.source == 'file'
            self._bleach_d_row.setVisible(not from_file)
            self._bleach_d.setValue(int(st.bleach_d or 10))
            self._bleach_d_auto.setChecked(st.bleach_d_auto)
            self._bleach_d.setEnabled(not from_file and not st.bleach_d_auto)
            self._bleach_d_auto.setEnabled(not from_file and st.source == 'detected')
            self._control_d.setValue(int(st.control_d or 6))
            self._control_d_auto.setChecked(st.control_d_auto)
            self._control_d.setEnabled(not st.control_d_auto)
            stack = self._stacks.get((id(it), self.channel_index(it), it.z))
            if stack is not None:
                lo, hi = float(stack[0].min()), float(stack[0].max())
                self._thr_range = (lo, hi if hi > lo else lo + 1)
            self._thr.setValue(float(st.threshold or 0))
            self._thr_auto.setChecked(st.threshold_auto)
            self._thr.setEnabled(not st.threshold_auto)
            self._thr_slider.setEnabled(not st.threshold_auto)
            lo, hi = self._thr_range
            self._thr_slider.setValue(int(round((float(st.threshold or lo) - lo) / (hi - lo) * SLIDER_STEPS)))
            src = {'file': '파일에 기록된 bleach 영역', 'detected': '자동 검출 (가장 크게 어두워진 곳)',
                   'manual': '직접 배치'}.get(st.source, '')
            px = it.pixel_um
            for n in ROI_NAMES:
                r = st.rois.get(n)
                text = r.describe(px) + f', {r.area()} px' if r is not None else ''
                if n == 'bleach' and src:
                    text = f'{src} · {text}'
                if n == 'background':
                    text += ' (Bleach ROI와 같은 크기)'
                self._roi_info[n].setText(text)
            self.notes.setText('\n'.join(st.notes))
        finally:
            self._binding = False

    # ---- plotting ------------------------------------------------------------

    def _replot(self, *_):
        view = self.view.currentData()
        if view == 'groups':
            self._plot_groups()
            return
        c = self.curve
        if c is None:
            if self.item is not None and self.item.nt > 1 and self.active():
                self.refresh()
            return
        frap.draw_curve(self.ax, c, self.fit.isChecked(), raw=view == 'raw')
        self.plot.draw_idle()
        self.summary.setText(self.summary_text(c.summary(), c.fit is not None))

    @staticmethod
    def summary_text(s, fitted=True) -> str:
        def f(v, d=3):
            return '–' if v is None or not np.isfinite(v) else f'{v:.{d}g}'

        lines = [f'bleach 전 {f(s["pre_bleach"])} → 직후 {f(s["post_bleach"])} '
                 f'(깊이 {f(s["bleach_depth"] * 100)} %) → 마지막 {f(s["final"])} '
                 f'(회복 {f(s["final_recovery"] * 100)} %)']
        if fitted and not s.get('fit_ok', 1):
            lines.append(f'관찰 시간 안에 회복이 거의 없거나 너무 느려 피팅값(mobile fraction, t½ 등)은 '
                         f'비웠습니다 (R² {f(s["fit_r2"], 4)}). 최종 회복률을 보세요.')
        elif fitted:
            lines.append(f'Mobile fraction {f(s["mobile_fraction"])} · Immobile {f(s["immobile_fraction"])} · '
                         f'plateau {f(s["plateau"])}')
            lines.append(f't½ {f(s["half_time_s"])} s · k {f(s["k_per_s"])} /s · τ {f(s["tau_s"])} s · '
                         f'R² {f(s["fit_r2"], 4)}')
            if np.isfinite(s.get('D_um2_per_s', np.nan)):
                lines.append(f'D ≈ {f(s["D_um2_per_s"])} µm²/s (원형 bleach, Soumpasis 참고값)')
        else:
            lines.append('피팅 실패 (bleach 후 프레임이 너무 적거나 회복이 없음)')
        return '\n'.join(lines)

    def groups(self, progress=True, items=None) -> list:
        """GroupCurve per image group (images without a group: one set);
        items: only these images (default all)."""
        items = [it for it in (self.win.items if items is None else items) if it.nt > 1]
        if not items:
            return []
        prog = None
        if progress and len(items) > 1:
            prog = QProgressDialog('FRAP 측정 중…', '취소', 0, len(items), self)
            prog.setWindowModality(Qt.WindowModality.WindowModal)
            prog.setMinimumDuration(400)
        by = {}
        try:
            for i, it in enumerate(items):
                if prog is not None:
                    if prog.wasCanceled():
                        break
                    prog.setValue(i)
                    prog.setLabelText(f'FRAP 측정: {it.label}')
                    QApplication.processEvents()
                try:
                    c = self.curve_for(it, progress=False)
                except Exception:
                    traceback.print_exc()
                    c = None
                if it is not self.item:
                    for k in [k for k in self._stacks if k[0] == id(it)]:
                        del self._stacks[k]  # keep memory for the current image
                    it.image.release()
                if c is not None:
                    by.setdefault(it.group or NO_GROUP, []).append(c)
        finally:
            if prog is not None:
                prog.setValue(len(items))
        order = [g for g in self.win.groups() if g in by] + [g for g in by if g not in self.win.groups()]
        return [frap.group_curve(g, by[g]) for g in order]

    def hidden_groups(self) -> set:
        try:
            v = json.loads(self.groups_hidden.text() or '[]')
        except ValueError:
            v = []
        return set(v) if isinstance(v, list) else set()

    def shown(self, gs) -> list:
        """The groups ticked for the graph."""
        hidden = self.hidden_groups()
        return [g for g in gs if g is not None and g.name not in hidden]

    def _sync_group_checks(self, names):
        """One check box per group above the graph (ticked = drawn)."""
        hidden = self.hidden_groups()
        if list(self._group_checks) != list(names):
            for b in self._group_checks.values():
                self._group_flow.removeWidget(b)
                b.deleteLater()
            self._group_checks = {}
            for n in names:
                b = QCheckBox(n)
                b.setToolTip('그래프에 이 그룹을 표시')
                b.toggled.connect(self._group_ticked)
                self._group_flow.addWidget(b)
                self._group_checks[n] = b
        for n, b in self._group_checks.items():
            b.blockSignals(True)
            b.setChecked(n not in hidden)
            b.blockSignals(False)
        self._group_pick.setVisible(self.view.currentData() == 'groups' and len(names) > 0)

    def _group_ticked(self, _):
        hidden = self.hidden_groups() - set(self._group_checks)
        hidden |= {n for n, b in self._group_checks.items() if not b.isChecked()}
        self.groups_hidden.setText(json.dumps(sorted(hidden), ensure_ascii=False))
        self.win.set_dirty()
        self._replot()

    def _plot_groups(self):
        try:
            all_gs = [g for g in self.groups() if g is not None]
            self._sync_group_checks([g.name for g in all_gs])
            gs = self.shown(all_gs)
        except Exception as exc:
            traceback.print_exc()
            self._show_empty(f'그룹 측정 실패: {exc}')
            return
        if not gs:
            self._show_empty('그래프에 표시할 그룹을 고르세요.' if all_gs else '시간축이 있는 이미지가 없습니다.')
            return
        frap.draw_groups(self.ax, gs, self.error.currentData(), self.fit.isChecked(),
                         self.members.isChecked())
        self.plot.draw_idle()
        lines = []
        for g in gs:
            s = frap.group_summary(g)

            def f(k, scale=1, d=3):
                m, sd, sem, n = s[k]
                e = sem if self.error.currentData() == 'sem' else sd
                return '–' if not np.isfinite(m) else (f'{m * scale:.{d}g}'
                                                       + (f' ± {e * scale:.2g}' if np.isfinite(e) else ''))

            warn = ' (n < 3)' if len(g.members) < 3 else ''
            lines.append(f'<b>{g.name}</b> n={len(g.members)}{warn}: Mobile {f("mobile_fraction")}, '
                         f't½ {f("half_time_s")} s, 최종 회복 {f("final_recovery", 100)} %')
        self.summary.setText('<br>'.join(lines))

    def _view_changed(self, _):
        self._group_pick.setVisible(self.view.currentData() == 'groups' and bool(self._group_checks))
        if self.view.currentData() != 'groups':
            self.refresh()
        else:
            self._replot()

    # ---- canvas -------------------------------------------------------------

    def rois_for_view(self) -> list:
        """(name, outline xy, rgb) of the ROIs to draw on the current image."""
        it = self.item
        if (it is None or not self.show_rois.isChecked() or not self.active()
                or not isinstance(it.frap, FrapState) or it.nt < 2):
            return []
        rois = dict(it.frap.rois)
        drift = self.curve.drift if self.curve is not None and self.item is it else {}
        t = min(max(int(it.t), 0), it.nt - 1)
        for n in rois:
            if n in drift and t < len(drift[n]):
                rois[n] = rois[n].moved(*np.rint(drift[n][t]))
        if self._drag is not None:
            n, dx, dy = self._drag
            if n in rois:
                rois[n] = rois[n].moved(dx, dy)
        return [(n, rois[n].outline(), frap.ROI_COLORS[n]) for n in ROI_NAMES if n in rois]

    def drag_preview(self, name, dx, dy):
        self._drag = (name, dx, dy)
        self._timer.start()

    def _update_live(self):
        if self._drag is None or self.item is None or not isinstance(self.item.frap, FrapState):
            return
        n, dx, dy = self._drag
        st = self.item.frap
        moved = {n: st.rois[n].moved(dx, dy)}
        try:
            c = self.curve_for(self.item, rois=moved)
        except Exception:
            traceback.print_exc()
            return
        if c is not None and self.view.currentData() != 'groups':
            frap.draw_curve(self.ax, c, self.fit.isChecked(), raw=self.view.currentData() == 'raw')
            self.plot.draw_idle()
            self.summary.setText(self.summary_text(c.summary(), c.fit is not None))

    def move_roi(self, name, dx, dy):
        """A ROI was dragged and let go: it stays there (its 자동 turns off)."""
        self._drag = None
        self._timer.stop()
        if not dx and not dy:  # a click
            self.win.draw_frap()
            return
        it = self.item
        if it is None or not isinstance(it.frap, FrapState) or name not in it.frap.rois:
            return
        st = it.frap
        st.rois[name] = st.rois[name].moved(dx, dy)
        st.auto[name] = False
        if name == 'bleach':
            st.source = 'manual' if st.source != 'file' else 'file'
        self.win.set_dirty()
        self.win.statusBar().showMessage(
            f'FRAP {frap.ROI_TITLES[name]} ROI 이동 ({dx:+d}, {dy:+d} px): {it.label}')
        self.refresh()

    # ---- per-image settings ----------------------------------------------------

    def _state(self) -> FrapState | None:
        if self._binding or self.item is None or not isinstance(self.item.frap, FrapState):
            return None
        return self.item.frap

    def _changed(self):
        self.win.set_dirty()
        self.refresh()

    def _roi_auto_toggled(self, name, on):
        st = self._state()
        if st is None:
            return
        st.auto[name] = on
        self._changed()

    def _bf_changed(self, v):
        st = self._state()
        if st is None or st.bleach_frame_auto:
            return
        st.bleach_frame = v - 1
        self._changed()

    def _bf_auto_toggled(self, on):
        st = self._state()
        if st is None:
            return
        st.bleach_frame_auto = on
        self._changed()

    def _file_roi_changed(self, i):
        st = self._state()
        if st is None or i < 0:
            return
        st.file_roi = i
        st.auto['bleach'] = True
        self._changed()

    def _size_changed(self, name):
        st = self._state()
        if st is None:
            return
        if name == 'bleach':
            st.bleach_d_auto = self._bleach_d_auto.isChecked()
            if not st.bleach_d_auto:
                st.bleach_d = self._bleach_d.value()
                b = st.rois.get('bleach')
                if b is not None and st.source != 'file':
                    st.rois['bleach'] = frap.FrapRoi.oval(*b.center(), st.bleach_d)
        else:
            st.control_d_auto = self._control_d_auto.isChecked()
            if not st.control_d_auto:
                st.control_d = self._control_d.value()
        self._changed()

    def _thr_changed(self, *_):
        st = self._state()
        if st is None:
            return
        st.threshold_auto = self._thr_auto.isChecked()
        if not st.threshold_auto:
            st.threshold = self._thr.value()
        self._changed()

    def _thr_slid(self, v):
        if self._binding or self._thr_auto.isChecked():
            return
        lo, hi = self._thr_range
        self._thr.setValue(lo + (hi - lo) * v / SLIDER_STEPS)

    def _channel_changed(self, _):
        if self._binding:
            return
        self._curves.clear()  # automatic positions and thresholds follow the new channel
        self.win.set_dirty()
        self.refresh()

    def _control_src_changed(self, _):
        if self._binding:
            return
        self._curves.clear()  # every image with an automatic Control is placed again
        self.win.set_dirty()
        self.win.statusBar().showMessage(f'FRAP Control 위치: {self.control_src.currentText()}')
        self.refresh()

    def _settings_changed(self, *_):
        self.win.set_dirty()
        self.refresh()

    def _drift_changed(self, *_):
        on = self.drift.isChecked()
        self.drift_mode.setEnabled(on)
        roi = on and self.drift_mode.currentData() == 'roi'
        self.drift_win_auto.setEnabled(roi)
        self.drift_win.setEnabled(roi and not self.drift_win_auto.isChecked())
        if self._binding:
            return
        self.win.set_dirty()
        self.refresh()

    def _show_drift(self, curve):
        """The window in use (filled in while automatic) and how far the ROIs moved."""
        it = self.item
        b = it.frap.rois.get('bleach') if it is not None and isinstance(it.frap, FrapState) else None
        stack = self._stacks.get((id(it), self.channel_index(it), it.z)) if it is not None else None
        if self.drift_win_auto.isChecked() and b is not None and stack is not None:
            self._binding = True
            try:
                self.drift_win.setValue(frap.drift_window(b, stack.shape[1:]))
            finally:
                self._binding = False
        if curve is None or not curve.drift:
            self._drift_info.setText('드리프트 보정 꺼짐' if not self.drift.isChecked() else '')
            return
        px = it.pixel_um if it is not None else None
        parts = []
        names = ['bleach'] + (['control'] if curve.drift['control'] is not curve.drift['bleach'] else [])
        for n in names:
            m = curve.max_drift(n)
            um = f' ({m * px:.2f} µm)' if px else ''
            parts.append(f'{frap.ROI_TITLES[n]} {m:.1f} px{um}')
        last = curve.drift['bleach'][-1]
        self._drift_info.setText('최대 이동: ' + ', '.join(parts)
                                 + f' · 마지막 프레임 ({last[0]:+.1f}, {last[1]:+.1f}) px')

    def reset_auto(self):
        it = self.item
        if it is None:
            return
        it.frap = FrapState()
        self.forget(it)
        self.win.set_dirty()
        self.win.statusBar().showMessage(f'FRAP ROI 모두 자동 배치: {it.label}')
        self.refresh()

    def set_rois(self, item, rois: dict):
        """ROIs loaded from a file (they stay where they are)."""
        st = item.frap if isinstance(item.frap, FrapState) else FrapState()
        for n, r in rois.items():
            st.rois[n] = r
            st.auto[n] = False
        if 'bleach' in rois:
            st.source = 'manual'
        item.frap = st
        self._curves.pop(id(item), None)
        if item is self.item:
            self.refresh()

    # ---- saving --------------------------------------------------------------

    def _need_curve(self) -> bool:
        if self.curve is None and self.item is not None and self.item.nt > 1:
            self.curve = self.curve_for(self.item)
        if self.curve is None:
            QMessageBox.information(self, 'FRAP 측정', '시간축(T)이 있는 이미지를 고르세요.')
            return False
        return True

    def _default(self, suffix):
        it = self.item
        return str(it.path.with_name(f'{item_stem(it)}_frap{suffix}'))

    def save_csv(self):
        if not self._need_curve():
            return
        path, _ = QFileDialog.getSaveFileName(self, 'FRAP CSV 저장', self._default('.csv'), 'CSV (*.csv)')
        if not path:
            return
        try:
            frap.write_curve_csv(path, self.curve)
            if self.win.opt_with_roi.isChecked():
                frap.save_rois(Path(path).with_name(Path(path).stem + '_rois.zip'), self.item.frap.rois,
                               self.item.id_properties())
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, '저장 실패', str(exc))
            return
        self.win.statusBar().showMessage(f'FRAP CSV 저장: {path}')

    def save_plot(self):
        if self.view.currentData() != 'groups' and not self._need_curve():
            return
        default = (self._default('.png') if self.view.currentData() != 'groups'
                   else str(self.item.path.with_name('frap_groups.png')) if self.item else 'frap_groups.png')
        path, flt = QFileDialog.getSaveFileName(self, 'FRAP 그래프 저장', default,
                                                'PNG (*.png);;PDF (*.pdf);;SVG (*.svg);;TIFF (*.tif)')
        if not path:
            return
        if not Path(path).suffix:
            path += {'PDF': '.pdf', 'SVG': '.svg', 'TIF': '.tif'}.get(flt[:3], '.png')
        try:
            self.write_plot(path)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, '저장 실패', str(exc))
            return
        self.win.statusBar().showMessage(f'FRAP 그래프 저장: {path}')

    def write_plot(self, path, groups=None):
        view = self.view.currentData()
        if view == 'groups' or groups is not None:
            gs = self.shown(groups if groups is not None else self.groups())
            return frap.save_figure(path, lambda ax: frap.draw_groups(
                ax, gs, self.error.currentData(), self.fit.isChecked(), self.members.isChecked()))
        c = self.curve
        return frap.save_figure(path, lambda ax: frap.draw_curve(ax, c, self.fit.isChecked(), view == 'raw'))

    def save_rois_current(self):
        it = self.item
        if it is None or not isinstance(it.frap, FrapState) or not it.frap.rois:
            QMessageBox.information(self, 'FRAP 측정', '저장할 FRAP ROI가 없습니다.')
            return
        path, _ = QFileDialog.getSaveFileName(self, 'FRAP ROI 저장', self._default('_rois.zip'),
                                              'ImageJ RoiSet (*.zip)')
        if path:
            frap.save_rois(path, it.frap.rois, it.id_properties())
            self.win.statusBar().showMessage(f'FRAP ROI 저장: {path}')

    def write_formulas(self, path, curves) -> str:
        """frap_formulas.txt: how every number is computed, with the settings used."""
        c = curves[0] if curves else None
        return frap.write_formulas(path, c.normalize if c else self._norm(), c.drift_mode if c else '',
                                   c.control_source if c else self.control_src.currentData(),
                                   self.error.currentData())

    def save_all(self, out=None, ask=True, items=None) -> list[str]:
        """요약 저장: every image measured; per image the curve CSV, graph and
        ROIs, and for the set frap_summary.csv (FRAP numbers per image and
        group), frap_group_curves.csv, frap_groups.png/.pdf (mean ± error)
        and frap_summary.png (mobile fraction, t½ per group)."""
        if out is None:
            out = QFileDialog.getExistingDirectory(self, 'FRAP 결과를 저장할 폴더')
            if not out:
                return []
        out = Path(out)
        gs = [g for g in self.groups(items=items) if g is not None]
        if not gs:
            if ask:
                QMessageBox.information(self, 'FRAP 측정', '시간축(T)이 있는 이미지가 없습니다.')
            return []
        written = []
        per_image = self.win.opt_per_image.isChecked()
        by_label = {it.label: it for it in self.win.items}
        curves = [c for g in gs for c in g.members]
        fit, raw = self.fit.isChecked(), False
        try:
            for c in curves:
                it = by_label.get(c.label)
                folder = out / item_folder(it) if (per_image and it is not None) else out
                stem = item_stem(it) if it is not None else c.label
                written.append(frap.write_curve_csv(folder / f'{stem}_frap.csv', c))
                written.append(frap.save_figure(folder / f'{stem}_frap.png',
                                                lambda ax, c=c: frap.draw_curve(ax, c, fit, raw)))
                if it is not None and isinstance(it.frap, FrapState):
                    written.append(frap.save_rois(folder / f'{stem}_frap_rois.zip', it.frap.rois,
                                                  it.id_properties()))
            written.append(frap.write_summary_csv(out / 'frap_summary.csv', curves, gs))
            written.append(frap.write_group_curves_csv(out / 'frap_group_curves.csv', gs,
                                                       self.error.currentData()))
            written.append(self.write_formulas(out / 'frap_formulas.txt', curves))
            for ext in ('.png', '.pdf'):
                written.append(self.write_plot(out / f'frap_groups{ext}', groups=gs))
            written.append(frap.save_summary_figure(out / 'frap_summary.png', gs,
                                                    self.error.currentData()))
        except Exception as exc:
            traceback.print_exc()
            if ask:
                QMessageBox.warning(self, '저장 실패', str(exc))
            return written
        self.win.statusBar().showMessage(f'FRAP 요약 저장: 이미지 {len(curves)}개, 그룹 {len(gs)}개 → {out}')
        if ask:
            QMessageBox.information(self, '저장 완료',
                                    f'이미지 {len(curves)}개, 그룹 {len(gs)}개의 FRAP 결과를 저장했습니다.\n'
                                    f'요약: frap_summary.csv, frap_summary.png, frap_groups.png\n{out}')
        return written
