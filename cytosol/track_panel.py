"""입자 추적 tab (v0.66, particle-tracking proposal 2026-11-13/14): the 입자 ROI
tab's detection on every frame, linked between frames and measured
(cytosol.tracking, ported from ParticleTracker), cell ROIs as they are or
detected per frame with their IDs linked, tracks drawn on the canvas, the
track table, ParticleTracker results loaded, graph tables, export, batch."""

from __future__ import annotations

import json
import math
import time
import traceback
from dataclasses import replace
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGraphicsEllipseItem,
    QGraphicsPathItem,
    QGraphicsSimpleTextItem,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import theme
from . import tracking as tk
from .flow import FlowLayout

CELL_MODES = [('static', '세포질 ROI 탭 · 지금 세포 ROI 그대로'), ('frame', '세포질 ROI 탭 · 프레임마다 검출 + ID 연결'),
              ('none', '세포 ROI 없이 (이미지 전체)')]
TAIL = 8          # frames of track tail drawn
IN_CLASSES = ('inside', 'signal')      # 4 트랙 chips: 세포 안 / 신호 있음
OUT_CLASSES = ('outside', 'nosignal')  # 세포 밖 / 신호 없음
MEAN_CACHE_BYTES = 1 << 30   # mean-projected frames kept during one run
PALETTE = [(255, 99, 71), (255, 215, 0), (0, 230, 230), (124, 252, 0), (255, 105, 180), (135, 206, 250),
           (255, 165, 0), (186, 85, 211), (64, 224, 208), (240, 230, 140)]


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


class TrackPanel(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.item = None
        self._scene = []
        self._sel = None
        self._busy = False
        lay = QVBoxLayout(self)
        lay.addWidget(_hint('입자 ROI 탭의 검출 설정을 모든 프레임에 적용하고, 프레임 사이 같은 입자를 이어 트랙을 '
                            '만듭니다. 세포 ROI가 있으면 세포의 움직임과 세포 안/밖을 함께 씁니다.'))
        self.run_btn = theme.prominent(QPushButton('추적 실행'))
        self.run_btn.clicked.connect(lambda: self.run_current())
        self.all_btn = QPushButton('모든 이미지에 실행')
        self.all_btn.clicked.connect(lambda: self.run_all())
        # the run buttons live in the inspector's 측정 바 (MainWindow.measure_bar, v0.68)

        # 1 검출
        det = QGroupBox('1  검출')
        f = QFormLayout(det)
        self.det_info = QLabel()
        self.det_info.setWordWrap(True)
        f.addRow('입자 검출', self.det_info)
        self.cell_mode = QComboBox()
        for key, text in CELL_MODES:
            self.cell_mode.addItem(text, key)
        self.cell_mode.setToolTip('프레임마다 검출: 세포질 ROI 탭의 설정으로 프레임마다 세포를 찾고, 앞 프레임과 30 % 이상 '
                                  '겹치면 같은 세포 번호를 이어 줍니다 (세포가 움직이거나 모양이 바뀔 때).')
        f.addRow('세포 ROI', self.cell_mode)
        # TCF with RI + fluorescence: ParticleTracker's own pipeline (v0.69, pt_engine)
        self.pt_engine = QCheckBox('ParticleTracker와 같게 (형광 원본 해상도)')
        self.pt_engine.setChecked(True)
        self.pt_engine.setToolTip('Tomocube TCF: ParticleTracker 앱의 코드로 형광 원본 해상도에서 입자를 찾고, 형광 → RI '
                                  '정합, RI 세포 분할, 세포 흐름, 연결, 측정, 분열 세포 제외까지 같은 순서로 실행합니다. '
                                  '끄면 입자 ROI 탭과 세포질 ROI 탭의 방법으로 화면의 영상에서 추적합니다.')
        self.pt_engine.toggled.connect(lambda _: self.refresh())
        f.addRow('방식', self.pt_engine)
        # Z stacks: project every frame before detecting (v0.69, independent of the viewer's Z slider)
        self.z_proj = QCheckBox('Z 투영 후 추적')
        self.z_proj.setChecked(True)
        self.z_proj.setToolTip('프레임마다 Z 스택을 2D로 투영한 영상에서 입자를 찾고 잇습니다 (ParticleTracker와 같은 '
                               '방식). 끄면 뷰어의 Z 슬라이더에서 고른 위치를 씁니다.')
        self.z_method = QComboBox()
        self.z_method.addItem('최대 투영 (MIP)', 'mip')
        self.z_method.addItem('평균 투영', 'mean')
        self.z_method.setToolTip('최대 투영: Z마다 가장 밝은 값 (작은 입자가 잘 보임, ParticleTracker 기본). '
                                 '평균 투영: Z 평균 (잡음이 적고 밝기가 Z 전체를 대표).')
        self.z_proj.toggled.connect(lambda _: self._z_ui())
        self.z_row = _row(self.z_proj, None, self.z_method)
        f.addRow('Z 스택', self.z_row)
        self.z_hint = _hint('')
        f.addRow(self.z_hint)
        self._det_form = f
        self.f_from = QSpinBox()
        self.f_to = QSpinBox()
        for s in (self.f_from, self.f_to):
            s.setRange(1, 1)
        fr = QWidget()
        fr.setProperty('hig_no_reflow', True)
        frl = QHBoxLayout(fr)
        frl.setContentsMargins(0, 0, 0, 0)
        frl.addStretch(1)
        frl.addWidget(self.f_from)
        frl.addWidget(QLabel('–'))
        frl.addWidget(self.f_to)
        f.addRow('프레임', fr)
        self.det_state = theme.StatusLabel(kind='info')
        self.det_state.setWordWrap(True)
        f.addRow(self.det_state)
        lay.addWidget(det)

        # 2 연결
        link = QGroupBox('2  연결 (추적)')
        f = QFormLayout(link)
        chips = QWidget()
        fl = FlowLayout(chips)
        fl.setContentsMargins(0, 0, 0, 0)
        self.use_flow = theme.chip(QCheckBox('세포 움직임'))
        self.use_flow.setToolTip('세포 채널의 optical flow (TV-L1)로 세포에 실려 가는 이동을 예측합니다.')
        self.use_pattern = theme.chip(QCheckBox('주변 패턴 매칭'))
        self.use_pattern.setToolTip('입자와 주변 입자 배치를 템플릿으로 다음 프레임에서 찾습니다 (점수가 낮으면 작은 '
                                    '템플릿으로 넓게 다시).')
        self.use_velocity = theme.chip(QCheckBox('트랙 속도 (Kalman)'))
        self.use_velocity.setToolTip('트랙 자체 속도(α-β 필터)로 예측하고, 예측 오차에 맞춰 트랙마다 gate를 넓힙니다.')
        for c in (self.use_flow, self.use_pattern, self.use_velocity):
            c.setChecked(True)
            fl.addWidget(c)
        f.addRow('위치 예측', chips)
        self.gate = QDoubleSpinBox()
        self.gate.setRange(0.1, 50)
        self.gate.setDecimals(2)
        self.gate.setSingleStep(0.1)
        self.gate.setSuffix(' µm')
        self.gate.setValue(1.55)
        self.gate.setToolTip('예측 위치에서 이 거리 밖의 검출은 이을 수 없습니다 (빠른 트랙은 최대 gate까지 넓어짐).')
        f.addRow('최대 이동 (gate)', self.gate)
        self.gate_max = QDoubleSpinBox()
        self.gate_max.setRange(0.1, 100)
        self.gate_max.setDecimals(2)
        self.gate_max.setSuffix(' µm')
        self.gate_max.setValue(2.48)
        f.addRow('최대 gate', self.gate_max)
        self.gap_max = QSpinBox()
        self.gap_max.setRange(0, 10)
        self.gap_max.setValue(2)
        self.gap_max.setSuffix(' 프레임')
        self.gap_max.setToolTip('검출이 이만큼의 프레임 동안 빠져도 앞뒤 조각을 같은 트랙으로 잇습니다 (0 = 잇지 않음).')
        f.addRow('누락 프레임 연결', self.gap_max)
        self.w_int = QDoubleSpinBox()
        self.w_int.setRange(0, 20)
        self.w_int.setValue(3.0)
        self.w_int.setToolTip('비용 = 거리 + 이 값 × |ln(밝기 비)| …')
        f.addRow('밝기 차이 가중치', self.w_int)
        self.w_area = QDoubleSpinBox()
        self.w_area.setRange(0, 20)
        self.w_area.setValue(1.5)
        f.addRow('크기 차이 가중치', self.w_area)
        lay.addWidget(link)

        # 3 측정
        meas = QGroupBox('3  측정')
        f = QFormLayout(meas)
        f.addRow(_hint('채널마다 입자 ROI 평균 − ROI 둘레 고리의 중앙값 (다른 입자는 고리에서 뺌).'))
        self.ratio_b = QComboBox()
        self.ratio_a = QComboBox()
        rr = QWidget()
        rr.setProperty('hig_no_reflow', True)
        rl = QHBoxLayout(rr)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addStretch(1)
        rl.addWidget(self.ratio_b)
        rl.addWidget(QLabel('/'))
        rl.addWidget(self.ratio_a)
        f.addRow('비율', rr)
        self.inside = QSpinBox()
        self.inside.setRange(1, 100)
        self.inside.setValue(50)
        self.inside.setSuffix(' % 넘는 프레임')
        self.inside.setToolTip('트랙 프레임 중 이 비율을 넘게 세포 안(세포질)에 있으면 세포 안 트랙입니다 (ParticleTracker와 같은 기준).')
        f.addRow('세포 안 기준', self.inside)
        self.min_track = QSpinBox()
        self.min_track.setRange(2, 10000)
        self.min_track.setValue(10)
        self.min_track.setSuffix(' 프레임 이상')
        f.addRow('긴 트랙', self.min_track)
        self.exclude_merged = QCheckBox('합쳐짐 / 가림 시점은 비율에서 제외')
        self.exclude_merged.setChecked(True)
        f.addRow(self.exclude_merged)
        lay.addWidget(meas)

        # 5 신호 기준 (v0.72, owner request 2026-11-19; shown after 4 트랙's settings order: placed before it)
        self.sig_box = self._build_signal_card()
        lay.addWidget(self.sig_box)

        # 4 트랙
        tr = QGroupBox('4  트랙')
        v = QVBoxLayout(tr)
        self.state = theme.StatusLabel(kind='info')
        self.state.setWordWrap(True)
        v.addWidget(self.state)
        chips = QWidget()
        fl = FlowLayout(chips)
        fl.setContentsMargins(0, 0, 0, 0)
        self.show_in = theme.chip(QCheckBox('세포 안'))
        self.show_out = theme.chip(QCheckBox('세포 밖'))
        self.show_short = theme.chip(QCheckBox('짧은 트랙'))
        for c, on in ((self.show_in, True), (self.show_out, True), (self.show_short, False)):
            c.setChecked(on)
            c.toggled.connect(lambda _: self.refresh())
            fl.addWidget(c)
        v.addWidget(chips)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['트랙', '프레임', '세포', 'µm/min', '비율 끝/처음'])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumHeight(220)
        self.table.itemSelectionChanged.connect(self._picked)
        self.table.hide()  # v0.68: the tables are in the graph window, no table in the page
        from .measure_bar import DataRows
        self.data_rows = DataRows(win, self.data_tables, '입자 추적')
        v.addWidget(self.data_rows)
        self.show_tracks = QCheckBox('이미지에 트랙 표시 (최근 8 프레임 꼬리)')
        self.show_tracks.setChecked(True)
        self.show_tracks.toggled.connect(lambda _: self.draw())
        v.addWidget(self.show_tracks)
        self.graph_btn = QPushButton('그래프 ›')
        self.graph_btn.setToolTip('그래프 편집 창에서 입자 추적 · 시점 표로 새 그래프를 만듭니다.')
        self.graph_btn.clicked.connect(self.open_graph)
        self.load_btn = QPushButton('트랙 불러오기…')
        self.load_btn.setToolTip('ParticleTracker 결과 폴더나 tracks_points CSV를 현재 이미지에 불러옵니다.')
        self.load_btn.clicked.connect(self.load_dialog)
        v.addWidget(_row(self.load_btn, None, self.graph_btn))
        lay.addWidget(tr)
        lay.addStretch(1)

    # ---- 5 신호 기준 ------------------------------------------------------------------

    def _build_signal_card(self):
        from PySide6.QtWidgets import QSlider

        from .app import Histogram
        box = QGroupBox('5  신호 기준 (긴 트랙)')
        v = QVBoxLayout(box)
        f = QFormLayout()
        self.sig_on = QCheckBox('신호 있는 트랙으로 나누기')
        self.sig_on.setToolTip('세포 안 / 밖 대신 신호 있음 / 없음으로 긴 트랙을 나눕니다.')
        f.addRow(self.sig_on)
        f.addRow(_hint('세포 안 / 밖 대신, 긴 트랙을 이 채널의 Min(LUT 최솟값) 이상인 프레임이 있는 트랙과 없는 '
                       '트랙으로 나눕니다. 그래프 · 표 · 일괄 분석 · 내보내기가 이 두 그룹을 씁니다.'))
        self.sig_channel = QComboBox()
        f.addRow('채널', self.sig_channel)
        v.addLayout(f)
        self.sig_hist = Histogram()
        v.addWidget(self.sig_hist)
        scale = QHBoxLayout()
        scale.setContentsMargins(0, 0, 0, 0)
        self.sig_lo, self.sig_hi = QLabel(), QLabel()
        note = QLabel('데이터 범위 · 미리보기와 같이 바뀜')
        for w in (self.sig_lo, note, self.sig_hi):
            theme.hint(w)
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scale.addWidget(self.sig_lo)
        scale.addWidget(note, 1)
        scale.addWidget(self.sig_hi)
        v.addLayout(scale)
        f2 = QFormLayout()
        self.sig_min_slider = QSlider(Qt.Orientation.Horizontal)
        self.sig_max_slider = QSlider(Qt.Orientation.Horizontal)
        self.sig_min = QDoubleSpinBox()
        self.sig_max = QDoubleSpinBox()
        for s in (self.sig_min, self.sig_max):
            s.setKeyboardTracking(False)
            s.setRange(-1e9, 1e9)
        f2.addRow('Min = 신호 기준', theme.slider_field(self.sig_min_slider, self.sig_min))
        f2.addRow('Max', theme.slider_field(self.sig_max_slider, self.sig_max))
        v.addLayout(f2)
        btns = QWidget()
        bl = QHBoxLayout(btns)
        bl.setContentsMargins(0, 0, 0, 0)
        self.sig_auto = QPushButton('Auto')
        self.sig_full = QPushButton('Min/Max')
        self.sig_full.setToolTip('현재 이미지 데이터의 최소값~최대값으로 설정')
        self.sig_all = QPushButton('전체 이미지에 적용')
        self.sig_all.setToolTip('이 채널의 Min / Max를 모든 이미지의 같은 채널에 적용')
        for b in (self.sig_auto, self.sig_full, self.sig_all):
            bl.addWidget(b)
        bl.addStretch(1)
        v.addWidget(btns)
        v.addWidget(_hint('LUT 탭의 이 채널 Min / Max와 같은 값입니다 (한쪽에서 바꾸면 다른 쪽도 바뀜).'))
        f3 = QFormLayout()
        self.sig_basis = QComboBox()
        from .track_signal import BASES
        for k, t in BASES:
            self.sig_basis.addItem(t, k)
        f3.addRow('기준 값', self.sig_basis)
        self.sig_frames = QSpinBox()
        self.sig_frames.setRange(1, 10000)
        self.sig_frames.setValue(3)
        self.sig_frames.setSuffix(' 프레임 이상')
        f3.addRow('신호 프레임', self.sig_frames)
        self.sig_preview = QCheckBox('미리보기: 신호 있는 입자 표시')
        self.sig_preview.setChecked(True)
        f3.addRow(self.sig_preview)
        f3.addRow(_hint('초록 고리 = 신호 트랙, 이 프레임에서 Min 이상 · 흰 점선 고리 = 신호 트랙, 이 프레임은 Min 아래.'))
        v.addLayout(f3)
        self.sig_state = theme.StatusLabel(kind='info')
        self.sig_state.setWordWrap(True)
        v.addWidget(self.sig_state)
        self._sig_lo, self._sig_hi, self._sig_steps = 0.0, 1.0, 1000
        self.sig_on.toggled.connect(lambda _: self._sig_changed())
        self.sig_channel.currentIndexChanged.connect(lambda _: self._sig_bind_lut())
        self.sig_basis.currentIndexChanged.connect(lambda _: self._sig_changed())
        self.sig_frames.valueChanged.connect(lambda _: self._sig_changed())
        self.sig_preview.toggled.connect(lambda _: self.draw())
        self.sig_min_slider.valueChanged.connect(lambda x: self._sig_slider(self.sig_min, x))
        self.sig_max_slider.valueChanged.connect(lambda x: self._sig_slider(self.sig_max, x))
        self.sig_min.valueChanged.connect(lambda _: self._sig_lut_edit())
        self.sig_max.valueChanged.connect(lambda _: self._sig_lut_edit())
        self.sig_auto.clicked.connect(lambda: self._sig_lut_button('auto'))
        self.sig_full.clicked.connect(lambda: self._sig_lut_button('full'))
        self.sig_all.clicked.connect(lambda: self._sig_lut_button('all'))
        self._sig_busy = False
        self._sig_cls = {}
        self._sig_text = ''
        return box

    def signal_on(self) -> bool:
        return self.sig_on.isChecked()

    def _sig_ch(self, item=None):
        it = item or self.item
        name = self.sig_channel.currentData()
        if it is None:
            return ''
        if name in it.channels:
            return name
        from .track_signal import default_channel
        return default_channel(it, it.tracks)

    def signal_settings(self, item):
        from .track_signal import SignalSettings, threshold_of
        ch = self._sig_ch(item)
        return SignalSettings(on=self.sig_on.isChecked(), channel=ch, basis=self.sig_basis.currentData() or 'max',
                              frames=self.sig_frames.value(), thr=threshold_of(item, ch) if ch else 0.0)

    def _sig_fill_channels(self, item):
        self._sig_busy = True
        keep = self.sig_channel.currentData()
        self.sig_channel.clear()
        if item is not None:
            from .track_signal import default_channel
            for name in item.channels:
                if str(name) != 'RI':
                    self.sig_channel.addItem(name, name)
            want = keep if keep in item.channels else default_channel(item, item.tracks)
            self.sig_channel.setCurrentIndex(max(self.sig_channel.findData(want), 0))
        self._sig_busy = False
        self._sig_bind_lut()

    def _sig_bind_lut(self):
        """Histogram and Min / Max of the chosen channel, as in the LUT tab."""
        it = self.item
        if self._sig_busy:
            return
        ch = self._sig_ch()
        if it is None or not ch:
            return
        ci = it.channels.index(ch)
        lo, hi, note = it.value_range(ci)
        integer = bool(note) and note != 'RI' and float(lo).is_integer() and float(hi).is_integer()
        self._sig_lo, self._sig_hi = float(lo), float(hi)
        span = max(hi - lo, 1e-12)
        self._sig_steps = int(span) if integer and 0 < span <= 1_000_000 else 1000
        self._sig_busy = True
        for s in (self.sig_min_slider, self.sig_max_slider):
            s.setRange(0, self._sig_steps)
        for s in (self.sig_min, self.sig_max):
            s.setDecimals(0 if integer else 4)
            s.setRange(lo, hi)
            s.setSingleStep(1 if integer else span / 100)
        fmt = (lambda x: f'{x:.0f}') if integer else (lambda x: f'{x:.4f}')
        self.sig_lo.setText(fmt(lo))
        self.sig_hi.setText(fmt(hi))
        try:
            self.sig_hist.set_data(it.planes()[ci], lo, hi)
        except Exception:  # noqa: BLE001
            pass
        self._sig_busy = False
        self.lut_changed()
        self._sig_changed()

    def _sig_to_slider(self, x):
        return int(round((x - self._sig_lo) / max(self._sig_hi - self._sig_lo, 1e-12) * self._sig_steps))

    def _sig_slider(self, spin, value):
        if self._sig_busy:
            return
        spin.setValue(self._sig_lo + value / self._sig_steps * (self._sig_hi - self._sig_lo))

    def lut_changed(self):
        """The LUT of the current image changed (LUT tab or here): show it, re-classify."""
        it = self.item
        ch = self._sig_ch()
        if it is None or not ch:
            return
        lut = it.luts[it.channels.index(ch)]
        self._sig_busy = True
        self.sig_min.setValue(lut.vmin)
        self.sig_max.setValue(lut.vmax)
        self.sig_min_slider.setValue(self._sig_to_slider(lut.vmin))
        self.sig_max_slider.setValue(self._sig_to_slider(lut.vmax))
        self.sig_hist.set_lut(lut.vmin, lut.vmax, lut.color)
        self._sig_busy = False
        if self.sig_on.isChecked():
            self._sig_changed()

    def _sig_lut_edit(self):
        it = self.item
        if self._sig_busy or it is None:
            return
        ci = it.channels.index(self._sig_ch())
        lut = it.luts[ci]
        lut.vmin, lut.vmax = self.sig_min.value(), self.sig_max.value()
        self._sig_lut_pushed(ci)

    def _sig_lut_button(self, what):
        it = self.item
        if it is None or not self._sig_ch():
            return
        ci = it.channels.index(self._sig_ch())
        if what == 'auto':
            it.auto_lut(ci)
        elif what == 'full':
            plane = it.planes()[ci]
            lo, hi = float(np.nanmin(plane)), float(np.nanmax(plane))
            it.luts[ci].vmin, it.luts[ci].vmax = lo, (hi if hi > lo else self._sig_hi)
        else:
            self.win.apply_channel_to_all(ci)
        self._sig_lut_pushed(ci)

    def _sig_lut_pushed(self, ci):
        w = self.win
        for p in getattr(w, 'panels', []):
            if p.index == ci and p.item is self.item:
                p.refresh()
        w.update_preview()
        w.set_dirty()
        self.lut_changed()
        self._sig_changed()

    def signal_classes(self, it, compute=False):
        """track_id -> classify() row for long tracks, or None (off / no tracks / values not measured yet)."""
        if not self.sig_on.isChecked() or it is None or it.tracks is None or not it.tracks.points:
            return None
        from . import track_signal as ts
        s = self.signal_settings(it)
        if not s.channel:
            return None
        vals = ts.point_values(it, it.tracks, s.channel, s.basis, self.z_source(it), compute=compute,
                               progress=(lambda i, n: self._progress(f'신호 값 측정 {i}/{n} ({it.label})'))
                               if compute else None)
        if vals is None:
            return None
        return ts.classify(it.tracks, vals, s.thr, s.frames, self.min_track.value())

    def _sig_changed(self):
        if self._sig_busy:
            return
        self._chip_names()
        it = self.item
        cls = self.signal_classes(it, compute=True) if it is not None else None
        self._sig_cls = cls or {}
        self._sig_text = ''
        if not self.sig_on.isChecked():
            self.sig_state.set_kind('info')
            self.sig_state.setText('꺼져 있습니다 (세포 안 / 밖으로 나눔).')
        elif cls is None:
            self.sig_state.set_kind('info')
            self.sig_state.setText('트랙이 없습니다.' if it is None or it.tracks is None else '신호 값이 없습니다.')
        else:
            sig = [c for c in cls.values() if c['signal']]
            first = [c['first_signal_frame'] for c in sig if c['first_signal_frame']]
            times = list(it.image.times) if it.image.times else None
            med = ''
            if first and times:
                h = [times[f - 1] / 3600 for f in first if f - 1 < len(times)]
                med = f' · 처음 신호 중앙값 {np.median(h):.1f} h' if h else ''
            self._sig_text = f'신호 있음 {len(sig)} / 긴 트랙 {len(cls)} ({len(sig) / max(len(cls), 1) * 100:.1f} %){med}'
            self.sig_state.set_kind('success')
            self.sig_state.setText(self._sig_text)
        self._fill_table()
        self.data_rows.refresh()
        self.draw()

    def _chip_names(self):
        on = self.sig_on.isChecked()
        self.show_in.setText('신호 있음' if on else '세포 안')
        self.show_out.setText('신호 없음' if on else '세포 밖')

    def _sig_draw(self, it, sc):
        """Rings on the particles of signal tracks in the frame shown."""
        if not (self.sig_on.isChecked() and self.sig_preview.isChecked()) or not self._sig_cls:
            return
        s = self.signal_settings(it)
        vals = (getattr(it.tracks, 'signal_cache', None) or {}).get((s.channel, s.basis), {})
        f_now = it.t + 1
        n_lit = 0
        for p in it.tracks.points:
            if p['frame'] != f_now:
                continue
            c = self._sig_cls.get(p['track_id'])
            if c is None or not c['signal']:
                continue
            lit = vals.get((p['track_id'], f_now), -np.inf) >= s.thr
            n_lit += lit
            r = 9.0
            e = QGraphicsEllipseItem(p['x'] + 0.5 - r, p['y'] + 0.5 - r, 2 * r, 2 * r)
            pen = QPen(QColor(60, 220, 90) if lit else QColor(255, 255, 255), 2.0)
            if not lit:
                pen.setStyle(Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            e.setPen(pen)
            e.setZValue(16)
            sc.addItem(e)
            self._scene.append(e)
        if getattr(self, '_sig_text', ''):
            self.sig_state.setText(f'{self._sig_text} · 이 프레임 신호 입자 {n_lit}')

    # ---- settings -----------------------------------------------------------

    def settings(self) -> tk.TrackSettings:
        return tk.TrackSettings(
            cells=self.cell_mode.currentData() or 'static', flow=self.use_flow.isChecked(),
            pattern=self.use_pattern.isChecked(), velocity=self.use_velocity.isChecked(),
            gate_um=self.gate.value(), gate_max_um=max(self.gate_max.value(), self.gate.value()),
            gap_max=self.gap_max.value(), w_int=self.w_int.value(), w_area=self.w_area.value(),
            inside_fraction=self.inside.value() / 100, min_track=self.min_track.value(),
            exclude_merged=self.exclude_merged.isChecked(),
            engine='pt' if self.pt_engine.isChecked() else 'app',
            z_project=(self.z_method.currentData() or 'mip') if self.z_proj.isChecked() else '',
            ratio_b=self.ratio_b.currentData() or '', ratio_a=self.ratio_a.currentData() or '')

    def status(self, msg):
        self.win.statusBar().showMessage(msg)

    def z_source(self, item):
        """Which plane of each frame is tracked: 'mip' / 'mean' (Z projection) or the viewer's Z."""
        if item is None or item.nz < 2:
            return item.z if item is not None else 'mip'
        return self.settings().z_project or item.z

    def uses_pt(self, item, prm=None) -> bool:
        """Whether this image is tracked with ParticleTracker's pipeline."""
        from . import pt_engine
        prm = prm or self.settings()
        return item is not None and prm.engine == 'pt' and pt_engine.is_tcf_pair(item) and \
            (item.nz < 2 or bool(prm.z_project))

    def pt_channels(self, item):
        """(reference, measure) channel names for ParticleTracker: the 입자 ROI
        channel (or ratio A) as reference, ratio B (or the other one) as measure."""
        fl = [c for c in item.channels if str(c).startswith('CH')]
        s = self._particle_settings(item)
        ref = s.channel if s.channel in fl else self.ratio_a.currentData() if self.ratio_a.currentData() in fl \
            else fl[-1]
        b = self.ratio_b.currentData()
        mea = b if b in fl and b != ref else next((c for c in fl if c != ref), ref)
        return ref, mea

    def _z_ui(self):
        it = self.item
        from . import pt_engine
        tcf = it is not None and pt_engine.is_tcf_pair(it)
        self._det_form.setRowVisible(self.pt_engine, tcf)
        self._det_form.setRowVisible(self.cell_mode, not (tcf and self.pt_engine.isChecked()))
        stack = it is not None and it.nz > 1
        self._det_form.setRowVisible(self.z_row, stack)
        self._det_form.setRowVisible(self.z_hint, stack)
        self.z_method.setEnabled(self.z_proj.isChecked())
        if stack:
            z = it.z
            where = '최대 투영 (MIP)' if z == 'mip' else '가운데 Z' if z == 'mid' else f'Z {int(z) + 1}'
            self.z_hint.setText(f'Z {it.nz}장을 프레임마다 투영해 추적합니다. 뷰어의 Z 슬라이더와는 따로입니다.'
                                if self.z_proj.isChecked() else
                                f'뷰어의 Z 슬라이더 위치 ({where})의 한 장으로 추적합니다.' +
                                (' ParticleTracker 방식은 Z 투영이 켜져 있을 때만 쓰고, 지금은 이 앱의 방식으로 추적합니다.'
                                 if tcf and self.pt_engine.isChecked() else ''))

    def visible_tab(self):
        return self.win.tab_current('track_tab')

    # ---- run ----------------------------------------------------------------

    def _particle_settings(self, item):
        pp = self.win.particle_panel
        s = item.particle_settings
        if s is None and item is pp.item and pp.part_on.isChecked():
            s = pp.settings()
        if s is None:
            s = replace(pp.settings(), within='image' if self.cell_mode.currentData() == 'none' else pp.settings().within)
        return pp.with_criterion(s, item)

    def _frame_cells(self, item, planes, mode, p=None):
        """Cell ROIs of one frame: the image's own, detected on this frame, or the whole image."""
        from .intensity import whole_image_cells
        h, w = planes.shape[-2:]
        if mode == 'none' or (mode == 'static' and (item.cells is None or not len(item.cells))):
            return whole_image_cells((h, w), item.pixel_um)
        if mode == 'static':
            return item.cells
        rp = self.win.roi_panel
        roles = dict(rp.roles(item))
        p = p if p is not None else self._cell_params(item)
        rois = rp._run_planes(planes, item.pixel_um, roles, p, rp.manual_mode(),
                              rp._man_value('cell'), rp._man_value('nuc'))
        rois.renumber()
        return rois

    def _cell_params(self, item, planes_of=None, frames=()):
        """세포질 ROI tab settings for cells detected on every frame, set once
        per image as ParticleTracker does: cells at the frame edge kept, and for
        HT (RI) cells one threshold for all frames (median over every 4th
        frame), so cells don't come and go with small RI changes."""
        from .cellroi import is_ri
        rp = self.win.roi_panel
        roles = dict(rp.roles(item))
        p = rp.params()
        try:
            if rp._any_size_auto():
                p = rp._sized(p, rp._auto_sizes(rp._image_sizes(item, roles)))
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        p = replace(p, edge_mode='keep')
        if planes_of is None or rp.manual_mode() or p.cell_threshold or roles.get('bg') is None:
            return p
        thr = []
        for t in list(frames)[::4]:
            planes = planes_of(t)
            if not is_ri(planes[roles['bg']]):
                return p
            r = rp._run_planes(planes, item.pixel_um, roles, p, False, None, None)
            if getattr(r, 'cell_threshold', None):
                thr.append(float(r.cell_threshold))
        return replace(p, cell_threshold=float(np.median(thr))) if thr else p

    def run(self, item, frames=None, progress=None) -> tk.TrackState | None:
        """Detect, link and measure the particles of one image over its frames."""
        from .cellroi import CellRois, link_cell_frames
        from .intensity import bit_depth, detect_particles, whole_image_cells
        prm = self.settings()
        if self.uses_pt(item, prm):
            return self._run_pt(item, frames, progress, prm)
        s = self._particle_settings(item)
        c = s.channel_for(item)
        if c is None:
            raise ValueError('입자 채널이 이 이미지에 없습니다.')
        if prm.cells == 'none':
            s = replace(s, within='image')
        T = item.nt
        frames = list(frames if frames is not None else range(T))
        px = item.pixel_um or 0.1
        times = list(item.image.times) if item.image.times else [float(t) for t in range(T)]
        depth = bit_depth(item, c)
        mode = prm.cells

        zsel = self.z_source(item)
        kept, budget = {}, [MEAN_CACHE_BYTES]   # mean projections read every plane: keep them while they fit

        def planes_of(t):
            if T < 2 and zsel == item.z:
                return np.asarray(item.planes(), np.float32)
            if t in kept:
                return kept[t]
            p = frame_planes(item, t, zsel)
            if zsel == 'mean' and budget[0] >= p.nbytes:
                kept[t] = p
                budget[0] -= p.nbytes
            return p

        # cells per frame (IDs linked when detected per frame)
        cell_rois = {}
        pt_flow = None
        roles0 = dict(self.win.roi_panel.roles(item))
        from .cellroi import is_ri
        ri_cells = mode == 'frame' and roles0.get('bg') is not None and not self.win.roi_panel.manual_mode() \
            and frames and is_ri(planes_of(frames[0])[roles0['bg']])
        if ri_cells:
            # HT (RI) cells as ParticleTracker finds them (ptcore.cells, unchanged): cell body image,
            # triangle / Otsu thresholds from every 4th frame, IDs linked by overlap; flow of the body images
            from .ptcore import cells as ptc
            from .ptcore.config import CellParams
            cp = CellParams()
            f = tk.UNIT_UM / px
            cp.open_radius = max(1, int(round(cp.open_radius * f)))
            cp.smooth_sigma = cp.smooth_sigma * f
            cp.min_cell_area = int(round(cp.min_cell_area * f * f))
            ht = np.stack([planes_of(t)[roles0['bg']] for t in frames]).astype(np.float32)
            cim = ptc.cell_body_images(ht, cp)
            CID, _lo, _core = ptc.segment_cells(cim, cp, (lambda fr, m: progress(f'{m} ({item.label})')) if progress else None)
            if prm.flow:
                pt_flow = ptc.cell_flow(cim, cp, (lambda fr, m: progress(f'{m} ({item.label})')) if progress else None)
            del cim, ht
            for k, t in enumerate(frames):
                cell_rois[t] = CellRois(CID[k].astype(np.int32), None, item.pixel_um)
        elif mode == 'frame':
            cp = self._cell_params(item, planes_of, frames)
            raw = {}
            for k, t in enumerate(frames):
                raw[t] = self._frame_cells(item, planes_of(t), mode, cp)
                if progress:
                    progress(f'입자 추적 세포 {k + 1}/{len(frames)} ({item.label})')
            linked = link_cell_frames([raw[t].labels for t in frames])
            for t, lab in zip(frames, linked):
                nuc = raw[t].nuclei
                cell_rois[t] = CellRois(lab, np.where(nuc > 0, lab, 0).astype(np.int32) if nuc is not None else None,
                                        item.pixel_um)
        roles = self.win.roi_panel.roles(item) if item.cells is not None or mode == 'frame' else {'bg': c}
        flow_ch = roles.get('bg', c) if roles.get('bg') is not None else c
        rows, outlines = [], {}
        det_cache = {}
        prev = None
        t0 = time.perf_counter()
        for k, t in enumerate(frames):
            planes = planes_of(t)
            cells = cell_rois.get(t) or self._frame_cells(item, planes, mode if mode != 'frame' else 'static')
            if s.within == 'image' and mode != 'frame':
                cells = whole_image_cells(planes.shape[-2:], item.pixel_um) if mode == 'none' else cells
            p = detect_particles(cells if s.within != 'image' else whole_image_cells(planes.shape[-2:], item.pixel_um),
                                 planes[c], s, depth, item.pixel_um)
            lab = p.labels if p.labels is not None else None
            if lab is None:
                from skimage import measure
                lab = measure.label(p.mask, connectivity=2)
            r, outs = tk.frame_detections(t + 1, lab, planes, item.channels, c,
                                          cells.labels if mode != 'none' else None,
                                          getattr(cells, "nuclei", None) if mode != "none" else None, prm, item.pixel_um)
            # cell movement between this frame and the next (inside cells only)
            for q in r:
                q['flow_y'] = q['flow_x'] = 0.0
            if prev is not None:
                pt, pr, pplanes = prev
                if prm.flow and mode != 'none' and pr:
                    try:
                        fl = pt_flow[k - 1] if pt_flow is not None else tk.cell_flow(pplanes[flow_ch], planes[flow_ch])
                        for q in pr:
                            if q['cell'] > 0:
                                iy, ix = int(round(q['y'])), int(round(q['x']))
                                q['flow_y'], q['flow_x'] = float(fl[0, iy, ix]), float(fl[1, iy, ix])
                    except Exception:  # noqa: BLE001
                        traceback.print_exc()
            for q, o in zip(r, outs):
                outlines[(q['frame'], q['label'])] = o
            rows += r
            prev = (t, r, planes)
            if prm.pattern:
                det_cache[t] = tk.bg_subtracted(planes[c], px)
                for old in [x for x in det_cache if x < t - 1]:
                    det_cache.pop(old)
            if progress:
                progress(f'입자 추적 검출 {k + 1}/{len(frames)} ({item.label})')
        # pattern matching needs consecutive bg-subtracted frames: recompute pairs lazily
        cache = {}

        def det_at(z):
            if z not in cache:
                if len(cache) > 2:
                    cache.pop(next(iter(cache)))
                cache[z] = tk.bg_subtracted(planes_of(z)[c], px)
            return cache[z]
        pts, n_gap = tk.track(rows, det_at, prm, px, times,
                              (lambda f, m: progress(f'{m} ({item.label})')) if progress else None)
        ratio = tk.add_ratio(pts, prm)
        st = tk.TrackState(points=pts, outlines=outlines, settings=prm.to_dict(), source='app',
                           channels=list(item.channels), ratio=ratio, n_gap=n_gap,
                           key=(self.key_of(item), tuple(frames)))
        st.seconds = time.perf_counter() - t0
        st.n_det = len(rows)
        st.frames = (frames[0] + 1, frames[-1] + 1) if frames else (0, 0)
        st.cells = len({q['cell'] for q in rows if q['cell'] > 0})
        return st

    def _run_pt(self, item, frames, progress, prm):
        """ParticleTracker's own pipeline on the TCF file (pt_engine)."""
        from . import pt_engine as pe
        T = item.nt
        frames = list(frames if frames is not None else range(T))
        ref, mea = self.pt_channels(item)
        s = self._particle_settings(item)
        cfg = pe.config(prm, pt_k=s.pt_k if s.method == 'pt' else None)
        dt = np.diff(item.image.times) if item.image.times and len(item.image.times) > 1 else None
        if dt is not None and len(dt):
            cfg.channel.frame_interval_min = float(np.median(dt)) / 60
        prm = replace(prm, ratio_a=ref, ratio_b=mea)
        say = (lambda m: progress(f'ParticleTracker 방식 · {m} ({item.label})')) if progress else None
        res = pe.run(item.path, pe.tcf_channel(ref), pe.tcf_channel(mea), cfg,
                     frames=None if frames == list(range(T)) else frames,
                     zmode=prm.z_project or 'mip', progress=say)
        f0 = frames[0] if frames else 0
        pts = pe.to_points(res, item, ref, mea, frame0=f0)
        outl = pe.outlines(res['LAB'], res['reg'], res['S'], {(p['frame'] - f0, p['label']) for p in pts})
        st = tk.TrackState(points=pts, outlines={(f + f0, k): v for (f, k), v in outl.items()},
                           settings=prm.to_dict(), source='app', channels=list(item.channels),
                           ratio=f'ratio_{mea}_{ref}', n_gap=int(res['n_gap']),
                           key=(self.key_of(item), tuple(frames)))
        st.seconds = res['seconds']['total']
        st.stage_seconds = res['seconds']
        st.n_det = res['n_det']
        st.frames = (frames[0] + 1, frames[-1] + 1) if frames else (0, 0)
        st.cells = len({p['cell'] for p in pts if p['cell'] > 0})
        st.engine = 'pt'
        st.appearance = res['appearance']
        st.pt = res['pt']     # ParticleTracker tables for its result folder (pt_engine.write_outputs)
        return st

    def key_of(self, item):
        s = self._particle_settings(item)
        return (str(s), str(self.settings().to_dict()), id(item.cells))

    def run_current(self, item=None):
        it = item or self.win.current
        if it is None:
            return None
        frames = range(self.f_from.value() - 1, self.f_to.value()) if it is self.item else None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            st = self.run(it, frames, progress=self._progress)
        except Exception as exc:
            traceback.print_exc()
            QApplication.restoreOverrideCursor()
            self.status(f'입자 추적 실패: {exc}')
            return None
        QApplication.restoreOverrideCursor()
        it.tracks = st
        self._after_run(it)
        return st

    def run_all(self):
        done = 0
        for it in list(self.win.items):
            if it.nt < 2:
                continue
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                it.tracks = self.run(it, progress=self._progress)
                done += 1
            except Exception as exc:
                traceback.print_exc()
                self.status(f'{it.label}: 입자 추적 실패 ({exc})')
            finally:
                QApplication.restoreOverrideCursor()
        self.status(f'입자 추적: 이미지 {done}개를 추적했습니다.')
        self.refresh()
        self.win.set_dirty(True) if hasattr(self.win, 'set_dirty') else None
        self.win.update_tab_badges()
        return done

    def _progress(self, msg):
        self.win.statusBar().showMessage(msg, 2000)
        QApplication.processEvents()

    def _after_run(self, it):
        st = it.tracks
        if st is None:
            return
        n_tr = len(st.tracks())
        self.status(f'입자 추적 ({it.label}): 검출 {getattr(st, "n_det", len(st.points))}개, 트랙 {n_tr}개, '
                    f'누락 연결 {st.n_gap} ({getattr(st, "seconds", 0):.1f}초)')
        if hasattr(self.win, 'set_dirty'):
            self.win.set_dirty(True)
        self.refresh()
        self.win.update_tab_badges()
        self.win.live_box.schedule()

    # ---- tables -------------------------------------------------------------

    def summary_of(self, it):
        st = it.tracks
        if st is None:
            return []
        prm = tk.TrackSettings.from_dict(st.settings)
        prm.min_track, prm.inside_fraction = self.min_track.value(), self.inside.value() / 100 - 1e-9
        chans = [c for c in st.channels if any(f'I_{c}' in p for p in st.points[:1])]
        rows = tk.summary(st.points, chans, prm, st.ratio)
        cls = self.signal_classes(it) if self.sig_on.isChecked() else None
        if cls:   # 신호 기준: long tracks are signal / nosignal instead of inside / outside
            for r in rows:
                c = cls.get(r['track_id'])
                if c is not None and r['class'] in ('inside', 'outside'):
                    r['class'] = 'signal' if c['signal'] else 'nosignal'
                    r['signal_frames'] = c['signal_frames']
                    r['first_signal_frame'] = c['first_signal_frame'] or ''
                    r['signal_value_max'] = c['value_max']
        return rows

    def data_tables(self):
        """(name, 점 하나 =, rows) of every image with tracks."""
        pts, summ, cells = [], [], []
        for it in self.win.items:
            st = it.tracks
            if st is None or not st.points:
                continue
            head = {'image_id': it.image_id, 'image': it.label, 'group': it.group or ''}
            sm = self.summary_of(it)
            cls = {r['track_id']: r['class'] for r in sm}
            pts += [{**head, 'track': f'{it.label} T{r["track_id"]:03d}', 'class': cls.get(r['track_id'], ''), **r}
                    for r in tk.point_rows(st.points, st.ratio)]
            summ += [{**head, **r} for r in sm]
            cells += [{**head, **r} for r in tk.per_cell(st.points, st.ratio)]
        return [('입자 추적 · 시점', '트랙 × 시점', pts), ('입자 추적 · 트랙', '트랙', summ),
                ('입자 추적 · 세포 × 시점', '세포 × 시점', cells)]

    def open_graph(self):
        gw = self.win.graph_window()
        gw.show()
        gw.start_data('입자 추적 · 시점')

    # ---- image selection / drawing -----------------------------------------------

    def bind(self, item):
        self.item = item
        self._busy = True
        for cb in (self.ratio_b, self.ratio_a):
            keep = cb.currentData()
            cb.clear()
            cb.addItem('없음', '')
            if item is not None:
                for name in item.channels:
                    cb.addItem(name, name)
            i = cb.findData(keep)
            cb.setCurrentIndex(max(i, 0))
        if item is not None and self.ratio_b.currentIndex() == 0 and len(item.channels) >= 2:
            pp = self.win.particle_panel
            s = item.particle_settings
            a = s.channel if s is not None and s.channel in item.channels else item.channels[0]
            b = next((n for n in item.channels if n != a and n != 'RI'), '')
            if b:
                self.ratio_a.setCurrentIndex(self.ratio_a.findData(a))
                self.ratio_b.setCurrentIndex(self.ratio_b.findData(b))
            del pp
        nt = item.nt if item is not None else 1
        for s in (self.f_from, self.f_to):
            s.setRange(1, max(nt, 1))
        self.f_from.setValue(1)
        self.f_to.setValue(max(nt, 1))
        self._busy = False
        self._sig_fill_channels(item)
        self.refresh()

    def refresh(self):
        it = self.item
        self._z_ui()
        pp = self.win.particle_panel
        if it is None:
            self.det_info.setText('이미지가 없습니다.')
        else:
            s = self._particle_settings(it)
            method = {'auto': '자동 (유의성)', 'spot': '점 모양 강조', 'manual': 'threshold', 'otsu': 'Otsu'}.get(s.method, s.method)
            crit = ' · 사용자 기준' if s.method == 'auto' and s.crit_k else ''
            if self.uses_pt(it):
                ref, mea = self.pt_channels(it)
                k = s.pt_k if s.method == 'pt' else 10.0
                self.det_info.setText(f'ParticleTracker 방식 · reference {ref} · measure {mea} · k {k:g} × MAD')
            else:
                self.det_info.setText(f'입자 ROI 탭 · {s.channel} · {method}{crit}')
        del pp
        st = it.tracks if it is not None else None
        if it is not None and it.nt < 2 and st is None:
            self.det_state.set_kind('warning')
            self.det_state.setText('시간축이 없는 이미지입니다 (프레임 1개).')
        elif st is not None:
            self.det_state.set_kind('success')
            fr = getattr(st, 'frames', None)
            src = '불러옴 (ParticleTracker)' if st.source != 'app' else f'{fr[0]}–{fr[1]} 프레임' if fr else ''
            if getattr(st, 'engine', '') == 'pt':
                src += ' · ParticleTracker 방식'
            zp = (st.settings or {}).get('z_project', '') if st.source == 'app' and it.nz > 1 else ''
            src += {'mip': ' · Z 최대 투영', 'mean': ' · Z 평균 투영'}.get(zp, '')
            self.det_state.setText(f'{src} · 입자 {len(st.points):,}개' +
                                   (f' · 세포 {st.cells}개' if getattr(st, 'cells', 0) else ''))
        else:
            self.det_state.set_kind('info')
            self.det_state.setText('아래 측정 버튼을 누르면 모든 프레임에서 입자를 찾고 잇습니다.')
        self._fill_table()
        self.data_rows.refresh()
        self.draw()

    def bar_status(self):
        """One line for the 측정 바."""
        ok = [it for it in self.win.items if it.nt >= 2]
        done = [it for it in ok if it.tracks is not None]
        if not ok:
            return '시간축이 있는 이미지가 없습니다.', None
        if not done:
            return f'시간축이 있는 이미지 {len(ok)}개 · 아직 추적하지 않았습니다.', None
        return f'{len(ok)} 이미지 중 {len(done)}개 추적됨', 'success' if len(done) >= len(ok) else None

    def _class_ok(self, row):
        k = row['class']
        return (k in IN_CLASSES and self.show_in.isChecked()) or (k in OUT_CLASSES and self.show_out.isChecked()) \
            or (k not in IN_CLASSES + OUT_CLASSES and self.show_short.isChecked())

    def _fill_table(self):
        it = self.item
        summ = self.summary_of(it) if it is not None else []
        st = it.tracks if it is not None else None
        shown = [r for r in summ if self._class_ok(r)]
        self._rows = shown
        self.table.blockSignals(True)
        self.table.setRowCount(len(shown))
        for i, r in enumerate(shown):
            ratio = (r.get('ratio_last3', float('nan')) / r['ratio_first3']) if r.get('ratio_first3') else float('nan')
            vals = [f'T{r["track_id"]:03d}', f'{r["start_frame"]}–{r["end_frame"]}',
                    f'cell{r["main_cell_id"]:03d}' if r['main_cell_id'] else '밖',
                    '' if r['mean_speed_um_min'] != r['mean_speed_um_min'] else f'{r["mean_speed_um_min"]:.2f}',
                    '' if ratio != ratio else f'{ratio:.1f}×']
            for j, v in enumerate(vals):
                self.table.setItem(i, j, QTableWidgetItem(v))
        self.table.blockSignals(False)
        if st is None:
            self.state.set_kind('info')
            self.state.setText('트랙이 없습니다.')
            return
        n = len(summ)
        long_ = [r for r in summ if r['class'] != 'short']
        ins = sum(1 for r in long_ if r['class'] in IN_CLASSES)
        merged = sum(1 for p in st.points if p.get('merged'))
        a, b = ('신호 있음', '없음') if any(r['class'] in ('signal', 'nosignal') for r in long_) else ('세포 안', '밖')
        self.state.set_kind('success')
        self.state.setText(f'트랙 {n}개 · 긴 트랙 {len(long_)}개 ({a} {ins}, {b} {len(long_) - ins}) · '
                           f'누락 연결 {st.n_gap}, 합쳐짐 {merged} 시점' +
                           (' · 불러옴 (ParticleTracker)' if st.source != 'app' else ''))

    def _picked(self):
        rows = self.table.selectionModel().selectedRows()
        self._sel = self._rows[rows[0].row()]['track_id'] if rows and rows[0].row() < len(self._rows) else None
        self.draw()
        if hasattr(self.win, 'live_box'):
            self.win.live_box.schedule()

    def selected_points(self):
        it = self.item
        if it is None or it.tracks is None or self._sel is None:
            return []
        return [p for p in it.tracks.points if p['track_id'] == self._sel]

    def _clear(self):
        sc = self.win.canvas.scene()
        for x in self._scene:
            sc.removeItem(x)
        self._scene = []

    def draw(self):
        """Track tails up to the current frame and the current positions."""
        self._clear()
        it = self.win.current
        if it is None or it is not self.item or it.tracks is None:
            return
        if not (self.visible_tab() or self._sel is not None):
            return
        sc = self.win.canvas.scene()
        self._sig_draw(it, sc)
        if not self.show_tracks.isChecked():
            return
        st = it.tracks
        f_now = it.t + 1
        cls = {r['track_id']: r['class'] for r in self.summary_of(it)}
        for tid, pts in st.tracks().items():
            k = cls.get(tid, 'short')
            if not ((k in IN_CLASSES and self.show_in.isChecked()) or (k in OUT_CLASSES and self.show_out.isChecked())
                    or (k == 'short' and self.show_short.isChecked())):
                continue
            tail = [p for p in pts if f_now - TAIL <= p['frame'] <= f_now]
            if not tail:
                continue
            sel = tid == self._sel
            col = QColor(*PALETTE[tid % len(PALETTE)]) if k not in OUT_CLASSES else QColor(170, 170, 170)
            if self._sel is not None and not sel:
                col.setAlpha(90)
            path = QPainterPath(QPointF(tail[0]['x'] + 0.5, tail[0]['y'] + 0.5))
            for p in tail[1:]:
                path.lineTo(QPointF(p['x'] + 0.5, p['y'] + 0.5))
            item = QGraphicsPathItem(path)
            pen = QPen(col)
            pen.setCosmetic(True)
            pen.setWidthF(2.6 if sel else 1.2)
            item.setPen(pen)
            item.setZValue(14)
            sc.addItem(item)
            self._scene.append(item)
            last = tail[-1]
            if last['frame'] == f_now:
                r = 4.0 if not sel else 7.0
                e = QGraphicsEllipseItem(last['x'] + 0.5 - r, last['y'] + 0.5 - r, 2 * r, 2 * r)
                e.setPen(pen)
                e.setZValue(14)
                sc.addItem(e)
                self._scene.append(e)
                if sel:
                    t = QGraphicsSimpleTextItem(f'T{tid:03d}')
                    t.setBrush(col)
                    t.setFlag(QGraphicsSimpleTextItem.GraphicsItemFlag.ItemIgnoresTransformations)
                    font = t.font()
                    font.setPointSize(13)
                    font.setBold(True)
                    t.setFont(font)
                    t.setPos(last['x'] + 6, last['y'] - 6)
                    t.setZValue(15)
                    sc.addItem(t)
                    self._scene.append(t)

    # ---- ParticleTracker results ------------------------------------------------

    def load_dialog(self):
        it = self.win.current
        if it is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, '트랙 불러오기 (ParticleTracker)', str(it.path.parent),
                                              'CSV (*.csv);;모든 파일 (*)')
        if not path:
            return
        try:
            n = self.load_pt(Path(path), it)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, '트랙 불러오기 실패', str(exc))
            return
        self.status(f'트랙 불러오기: {n}개 점 ({Path(path).name})')

    def load_pt(self, path: Path, item=None, chan_a=None, chan_b=None) -> int:
        """A ParticleTracker results folder or points CSV (or this app's own)
        onto an image: by dataset.json's input / image ID when it names one of
        the images, else onto ``item`` (the current image)."""
        path = Path(path)
        folder = path if path.is_dir() else path.parent
        csvs = [path] if path.is_file() else sorted(folder.glob('*tracks_points*.csv'))
        if not csvs:
            raise ValueError('tracks_points CSV를 찾지 못했습니다.')
        target = item
        meta = folder / 'dataset.json'
        if meta.exists():
            try:
                d = json.loads(meta.read_text(encoding='utf-8'))
                names = {str(v) for v in d.values() if isinstance(v, str)}
                for it in self.win.items:
                    if it.image_id in names or str(it.path) in names or it.path.name in {Path(n).name for n in names}:
                        target = it
                        break
            except Exception:  # noqa: BLE001
                pass
        if target is None:
            raise ValueError('붙일 이미지가 없습니다.')
        rows = tk.read_csv_rows(csvs[0])
        if rows and 'x_px' in rows[0] and 'location' in rows[0]:
            pts, source = tk.from_app_rows(rows), 'app-csv'
        else:
            ch = target.channels
            a = chan_a or (ch[0] if ch else 'A')
            b = chan_b or (ch[1] if len(ch) > 1 else 'B')
            ds = None
            if rows and 'dataset' in rows[0]:
                vals = {r.get('dataset') for r in rows}
                ds = next((v for v in vals if v and (v in target.label or v in target.path.name)), None)
            pts, source = tk.from_pt(rows, target.pixel_um, None, a, b, ds), 'ParticleTracker'
        ratio = next((k for k in (pts[0] if pts else {}) if k.startswith('ratio_') and not k.endswith('_unfiltered')), '')
        target.tracks = tk.TrackState(points=pts, source=source, channels=list(target.channels), ratio=ratio,
                                      settings=self.settings().to_dict())
        if target is self.item:
            self.refresh()
        self.win.update_tab_badges()
        return len(pts)

    # ---- export -------------------------------------------------------------

    def save_item(self, it, folder: Path, stem: str, pt_names=False, rois=True) -> list[str]:
        """<stem>_tracks_points.csv, <stem>_tracks_summary.csv, <stem>_tracks.zip (ImageJ ROIs)."""
        st = it.tracks
        if st is None or not st.points:
            return []
        folder.mkdir(parents=True, exist_ok=True)
        head = {'image_id': it.image_id, 'image': it.label, 'group': it.group or ''}
        rows = [{**head, **r} for r in tk.point_rows(st.points, st.ratio)]
        if pt_names:
            rows = [_pt_names(r, st) for r in rows]
        out = []
        p1 = folder / f'{stem}_tracks_points.csv'
        tk.write_csv(p1, rows)
        out.append(str(p1))
        p2 = folder / f'{stem}_tracks_summary.csv'
        tk.write_csv(p2, [{**head, **r} for r in self.summary_of(it)])
        out.append(str(p2))
        if rois and st.outlines:
            p3 = folder / f'{stem}_tracks.zip'
            if save_track_rois(p3, st, it.id_properties()):
                out.append(str(p3))
        return out


def frame_planes(item, t, z) -> np.ndarray:
    """(C, Y, X) float32 of timepoint t: plane z, the max ('mip') or the mean ('mean') over Z."""
    from .prefetch import plane_at
    img = item.image
    if z == 'mean':
        nz = item.nz
        if nz < 2:
            return np.asarray(plane_at(img, t, 'mid'), np.float32)
        if not img.lazy:
            vol = img.data if t == img.t else img.loader(t)
            return np.asarray(vol, np.float32).mean(axis=1)
        acc = None
        for k in range(nz):
            p = np.asarray(plane_at(img, t, k), np.float32)
            acc = p.copy() if acc is None else acc + p
        return acc / nz
    return np.asarray(plane_at(img, t, z), np.float32)


def _pt_names(r, st):
    """ParticleTracker column names (x_fl, y_fl, roi_label, region, I_A …)."""
    out = dict(r)
    out['x_fl'], out['y_fl'] = out.pop('x_px'), out.pop('y_px')
    out['roi_label'] = out.pop('particle_id')
    out['region'] = {'cytosol': 'cytoplasm', 'nucleus': 'cytoplasm', 'outside': 'background'}.get(out.get('location'), '')
    if st.ratio:
        _, b, a = st.ratio.split('_', 2)
        for pre in ('I_', 'bg_'):
            for suf in ('_raw', ''):
                if f'{pre}{a}{suf}' in out:
                    out[f'{pre}A{suf}'] = out[f'{pre}{a}{suf}']
                if f'{pre}{b}{suf}' in out:
                    out[f'{pre}B{suf}'] = out[f'{pre}{b}{suf}']
        out['ratio_BA'] = out.get(st.ratio)
    return out


def save_track_rois(path, st, properties=None) -> bool:
    """One ImageJ ROI per tracked particle and frame (``T001-f012``, position = frame)
    plus one polyline per track (``T001-path``)."""
    import roifile

    rois = []
    for tid, pts in sorted(st.tracks().items()):
        for p in pts:
            loops = st.outlines.get((p['frame'], p['label']))
            if not loops:
                continue
            xy = np.asarray(loops[0], float)
            r = roifile.ImagejRoi.frompoints(xy)
            r.roitype = roifile.ROI_TYPE.POLYGON
            r.name = f'T{tid:03d}-f{p["frame"]:03d}'
            r.position = int(p['frame'])
            r.t_position = int(p['frame'])
            rois.append(r)
        if len(pts) > 1:
            r = roifile.ImagejRoi.frompoints(np.array([[p['x'] + 0.5, p['y'] + 0.5] for p in pts]))
            r.roitype = roifile.ROI_TYPE.POLYLINE
            r.name = f'T{tid:03d}-path'
            rois.append(r)
    if not rois:
        return False
    if Path(path).exists():
        Path(path).unlink()
    roifile.roiwrite(path, rois)
    return True


def track_live(panel):
    """(tiles, plot fn) for the 실시간 값 박스: tracks of the current image."""
    it = panel.item
    st = it.tracks if it is not None else None
    if st is None:
        return None
    summ = panel.summary_of(it)
    f_now = it.t + 1
    here = sum(1 for p in st.points if p['frame'] == f_now)
    long_ = [r for r in summ if r['class'] != 'short']
    sp = [r['mean_speed_um_min'] for r in long_ if r['mean_speed_um_min'] == r['mean_speed_um_min']]
    tiles = [('트랙', len(summ)), ('긴 트랙', len(long_)), ('이 프레임 입자', here),
             ('평균 속도 µm/min', f'{np.mean(sp):.2f}' if sp else '–')]
    return tiles, panel.selected_points(), st.ratio
