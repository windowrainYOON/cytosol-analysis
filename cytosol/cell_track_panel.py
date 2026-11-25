"""세포질 강도 추적 tab (``cyto_track_tab``; owner request 2026-11-19/20,
mockups v073b–e, pipeline design v3.5; built in v0.73).

Cards: 1 세포 검출 (algorithm, channels, Z projection, frames), 2 세포 추적
(연결) (optical flow, overlap, missed frames, long cells, cells left out:
divided / at the image edge), 3 밝기 측정 (region, channels, background ring,
baseline time, early threshold), 4 필터 (named filters made of conditions,
조건 추가 / 필터 추가), 5 세포 (classes as chips, outlines on the canvas,
data rows). Running is on the measure bar (이 이미지만 / 전체 이미지).
The maths is in `cell_track.py`.
"""

from __future__ import annotations

import csv
import time
import traceback
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGraphicsPathItem,
    QGraphicsSimpleTextItem,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from . import cell_track as CT
from . import theme
from .flow import FlowLayout

DATA_NAMES = {'frames': ('세포질 강도 추적 · 세포 × 시점', '세포 × 시점'), 'cells': ('세포질 강도 추적 · 세포', '세포')}
PALETTE = [(255, 99, 71), (30, 144, 255), (50, 205, 50), (255, 0, 255), (0, 206, 209), (255, 140, 0),
           (138, 43, 226), (0, 191, 255), (255, 105, 180), (154, 205, 50)]
FILTER_COLOR = (255, 214, 0)


def combo(items, tip=''):
    c = QComboBox()
    for k, text in items:
        c.addItem(text, k)
    if tip:
        c.setToolTip(tip)
    return c


def set_data(c: QComboBox, v):
    i = c.findData(v)
    if i >= 0:
        c.setCurrentIndex(i)


def dspin(lo, hi, v, step=0.5, dec=1, suffix=''):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setSingleStep(step)
    s.setValue(v)
    if suffix:
        s.setSuffix(suffix)
    return s


def ispin(lo, hi, v, suffix='', prefix=''):
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setValue(v)
    if suffix:
        s.setSuffix(suffix)
    if prefix:
        s.setPrefix(prefix)
    return s


def pair(a, b):
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.addWidget(a)
    h.addWidget(QLabel('–'))
    h.addWidget(b)
    return w


class ConditionRows:
    """The rows of one condition of a filter (in the filter card's form)."""

    def __init__(self, panel, form: QFormLayout, f_i, c_i, c: dict):
        self.panel = panel
        self.head = QWidget()
        h = QHBoxLayout(self.head)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(theme.section_header(f'조건 {c_i + 1}'))
        h.addStretch()
        rm = QPushButton('조건 지우기')
        theme.destructive(rm)
        rm.setToolTip('이 조건을 지웁니다.')
        rm.clicked.connect(lambda: panel.remove_condition(f_i, c_i))
        h.addWidget(rm)
        self.rm = rm
        form.addRow(self.head)
        self.t0, self.t1 = dspin(0, 1000, c.get('t0', 2.0), suffix=''), dspin(0, 1000, c.get('t1', 6.0), suffix=' h')
        form.addRow('구간', pair(self.t0, self.t1))
        self.value = combo(CT.VALUES)
        set_data(self.value, c.get('value', 'thr'))
        form.addRow('값', self.value)
        self.change = combo(CT.CHANGES)
        set_data(self.change, c.get('change', 'risefall'))
        form.addRow('변화', self.change)
        iw = QWidget()
        ih = QHBoxLayout(iw)
        ih.setContentsMargins(0, 0, 0, 0)
        self.inc_mode = combo((('top', '상위 %'), ('abs', '값 이상')))
        set_data(self.inc_mode, c.get('inc_mode', 'top'))
        self.inc = dspin(0, 1e6, c.get('inc', 25.0), step=1, dec=2)
        ih.addWidget(self.inc_mode)
        ih.addWidget(self.inc)
        self.inc_label = QLabel('증가 크기')
        form.addRow(self.inc_label, iw)
        self.f0, self.f1 = dspin(0, 1000, c.get('f0', 7.0)), dspin(0, 1000, c.get('f1', 9.5), suffix=' h')
        self.fall_row = pair(self.f0, self.f1)
        form.addRow('감소 구간', self.fall_row)
        self.fall = dspin(0, 100, c.get('fall', 60.0), step=5, dec=0, suffix=' % 이상')
        form.addRow('감소 크기', self.fall)
        self.note = QLabel()
        self.note.setWordWrap(True)
        theme.hint(self.note)
        form.addRow(self.note)
        self.form = form
        for w in (self.t0, self.t1, self.inc, self.f0, self.f1, self.fall):
            w.valueChanged.connect(lambda _v: panel.filters_edited())
        for w in (self.value, self.change, self.inc_mode):
            w.currentIndexChanged.connect(lambda _i: panel.filters_edited())
        self.sync()

    def sync(self):
        ch = self.change.currentData()
        theme.show_rows(self.form, [self.fall_row, self.fall], ch == 'risefall')
        self.inc_label.setText({'fall': '감소 크기', 'above': '기준'}.get(ch, '증가 크기'))
        top = self.inc_mode.currentData() == 'top'
        self.inc.setSuffix(' %' if top else '')
        c = self.get()
        what = {'rise': '증가가', 'fall': '감소가', 'above': '평균이', 'risefall': '증가가'}[ch]
        size = f'모든 세포 중 상위 {c["inc"]:g} %' if top else f'{c["inc"]:g} 이상'
        text = f'「{self.change.currentText()}」: {c["t0"]:g}–{c["t1"]:g} h 구간 안의 {what} {size}'
        if ch == 'risefall':
            text += f'이고, {c["f0"]:g}–{c["f1"]:g} h 구간까지 그 증가분의 {c["fall"]:g} % 이상이 사라진 세포.'
        else:
            text += '인 세포.'
        self.note.setText(text)

    def get(self) -> dict:
        return dict(t0=self.t0.value(), t1=self.t1.value(), value=self.value.currentData(),
                    change=self.change.currentData(), inc_mode=self.inc_mode.currentData(), inc=self.inc.value(),
                    f0=self.f0.value(), f1=self.f1.value(), fall=self.fall.value())


class CellTrackPanel(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.item = None
        self._scene = []
        self._outline_cache = {}
        self._filters = [CT.default_filter()]
        self._cond_rows = []
        self._busy = False
        lay = QVBoxLayout(self)
        h = QLabel('세포를 프레임마다 검출하고 같은 세포를 이어 시간에 따라 따라가며, 세포마다 형광 밝기와 그 변화를 '
                   '잽니다. 조건을 넣어 원하는 변화를 보인 세포만 골라 전체 세포와 비교합니다.')
        h.setWordWrap(True)
        theme.hint(h)
        lay.addWidget(h)

        # 1 세포 검출 -----------------------------------------------------------
        b1 = QGroupBox('1  세포 검출')
        f1 = QFormLayout(b1)
        self.algorithm = combo(CT.ALGORITHMS, '세포를 찾는 방법. ParticleTracker와 같게: RI(HT) 채널에서 세포 몸체를 '
                                              '찾습니다. 세포질 ROI 알고리즘: 세포질 ROI 탭의 검출 설정으로 세포와 핵을 '
                                              '찾습니다. 입자 추적 결과의 세포: ParticleTracker 방식 입자 추적이 찾은 세포.')
        f1.addRow('알고리즘', self.algorithm)
        self.cell_ch = QComboBox()
        f1.addRow('세포 채널', self.cell_ch)
        self.nuc_ch = QComboBox()
        f1.addRow('핵 채널', self.nuc_ch)
        self.algo_hint = QLabel()
        self.algo_hint.setWordWrap(True)
        theme.hint(self.algo_hint)
        f1.addRow(self.algo_hint)
        zw = QWidget()
        zh = QHBoxLayout(zw)
        zh.setContentsMargins(0, 0, 0, 0)
        self.z_on = QCheckBox('Z 투영 후 검출')
        self.z_on.setChecked(True)
        zh.addWidget(self.z_on)
        self.z_mode = combo((('mip', '최대 투영 (MIP)'), ('mean', '평균 투영')))
        zh.addWidget(self.z_mode)
        self.z_row = zw
        f1.addRow('Z 스택', zw)
        self.frame0, self.frame1 = ispin(1, 100000, 1), ispin(1, 100000, 1)
        f1.addRow('프레임', pair(self.frame0, self.frame1))
        self.det_state = theme.StatusLabel('', 'info')
        f1.addRow(self.det_state)
        self.f1 = f1
        lay.addWidget(b1)

        # 2 세포 추적 (연결) ------------------------------------------------------
        b2 = QGroupBox('2  세포 추적 (연결)')
        f2 = QFormLayout(b2)
        self.flow = QCheckBox('세포 움직임 (optical flow)로 위치 예측')
        self.flow.setChecked(True)
        f2.addRow(self.flow)
        self.overlap = ispin(5, 100, 30, ' % 이상 겹침')
        self.overlap.setToolTip('예측한 위치의 앞 프레임 세포와 이만큼 겹치면 같은 세포로 잇습니다.')
        f2.addRow('같은 세포 기준', self.overlap)
        self.gap = ispin(0, 10, 2, ' 프레임')
        self.gap.setToolTip('세포를 이 프레임 수까지 놓쳐도 같은 자리에서 다시 찾으면 잇습니다.')
        f2.addRow('누락 프레임 연결', self.gap)
        self.min_frames = ispin(2, 100000, 20, ' 프레임 이상')
        f2.addRow('긴 세포', self.min_frames)
        f2.addRow(theme.section_header('제외할 세포'))
        self.ex_div = QCheckBox('추적 중 분열한 세포 제외')
        self.ex_div.setChecked(True)
        f2.addRow(self.ex_div)
        self.div_mode = combo(CT.DIV_MODES)
        f2.addRow('분열 판정', self.div_mode)
        self.ex_edge = QCheckBox('이미지 가장자리에 닿는 세포 제외')
        self.ex_edge.setChecked(True)
        f2.addRow(self.ex_edge)
        self.edge_mode = combo(CT.EDGE_MODES)
        f2.addRow('가장자리 기준', self.edge_mode)
        self.edge_px = ispin(0, 200, 3, ' px')
        f2.addRow('가장자리 여백', self.edge_px)
        self.link_state = theme.StatusLabel('', 'info')
        f2.addRow(self.link_state)
        self.f2 = f2
        lay.addWidget(b2)

        # 3 밝기 측정 -------------------------------------------------------------
        b3 = QGroupBox('3  밝기 측정')
        f3 = QFormLayout(b3)
        n3 = QLabel('배경은 세포마다 그 세포 둘레 고리(다른 세포 제외)의 평균이며, 시야 전체 값은 빼지 않습니다.')
        n3.setWordWrap(True)
        theme.hint(n3)
        f3.addRow(n3)
        self.region = combo((('cytosol', '세포질 (세포 − 핵)'), ('cell', '세포 전체')))
        f3.addRow('잴 영역', self.region)
        self.meas_ch = QComboBox()
        f3.addRow('측정 채널', self.meas_ch)
        self.ref_ch = QComboBox()
        f3.addRow('기준 채널 (비율 분모)', self.ref_ch)
        self.ring_in, self.ring_out = dspin(0, 100, 2.0), dspin(0.1, 200, 6.0, suffix=' µm')
        f3.addRow('배경 고리', pair(self.ring_in, self.ring_out))
        self.base_h = dspin(0, 1000, 1.0, suffix=' h')
        self.base_h.setToolTip('변화(_change 열)와 필터의 증가 · 감소는 이 시점까지의 평균에서 잽니다.')
        f3.addRow('변화 기준 시점', self.base_h)
        f3.addRow(theme.section_header('측정 채널 기준값'))
        self.thr_on = QCheckBox('기준 이하 픽셀을 0으로 한 값도 계산')
        self.thr_on.setChecked(True)
        f3.addRow(self.thr_on)
        self.thr_until = dspin(0, 100000, 100, step=10, dec=0, suffix=' 분까지')
        f3.addRow('초반 구간', self.thr_until)
        self.thr_pct = dspin(0, 100, 95, step=1, dec=0, suffix=' %')
        f3.addRow('백분위', self.thr_pct)
        n4 = QLabel('이미지마다 초반 구간 측정 채널 픽셀의 이 백분위를 기준값으로 씁니다.')
        n4.setWordWrap(True)
        theme.hint(n4)
        f3.addRow(n4)
        self.f3 = f3
        lay.addWidget(b3)

        # 4 필터 ------------------------------------------------------------------
        self.b4 = QGroupBox('4  필터 (조건으로 세포 고르기)')
        self.b4_lay = QVBoxLayout(self.b4)
        lay.addWidget(self.b4)

        # 5 세포 ------------------------------------------------------------------
        b5 = QGroupBox('5  세포')
        v5 = QVBoxLayout(b5)
        self.summary = theme.StatusLabel('아직 추적하지 않았습니다.', None)
        v5.addWidget(self.summary)
        self.chip_box = QWidget()
        self.chip_lay = FlowLayout(self.chip_box)
        self.chip_box.setProperty('hig_no_reflow', True)
        v5.addWidget(self.chip_box)
        self.chips = {}
        self.show_on = QCheckBox('이미지에 세포 윤곽과 번호 표시 (필터 세포 = 노랑)')
        self.show_on.setChecked(True)
        self.show_on.toggled.connect(lambda _v: self.draw())
        v5.addWidget(self.show_on)
        from .measure_bar import DataRows
        self.data_rows = DataRows(win, self.data_tables, '세포질 강도 추적')
        v5.addWidget(self.data_rows)
        lay.addWidget(b5)
        lay.addStretch()

        self.algorithm.currentIndexChanged.connect(lambda _i: self._sync())
        self.ex_div.toggled.connect(lambda _v: self._sync())
        self.ex_edge.toggled.connect(lambda _v: self._sync())
        self.z_on.toggled.connect(lambda _v: self._sync())
        for w in (self.min_frames, self.edge_px):
            w.valueChanged.connect(lambda _v: self.refresh())
        for w in (self.div_mode, self.edge_mode):
            w.currentIndexChanged.connect(lambda _i: self.refresh())
        self.ex_div.toggled.connect(lambda _v: self.refresh())
        self.ex_edge.toggled.connect(lambda _v: self.refresh())
        self.base_h.valueChanged.connect(lambda _v: self.refresh())
        self._build_filters()
        self._sync()

    # ---- settings -----------------------------------------------------------

    def _sync(self):
        a = self.algorithm.currentData()
        theme.show_rows(self.f1, [self.nuc_ch], a == 'roi')
        theme.show_rows(self.f1, [self.cell_ch], a != 'particle')
        self.algo_hint.setText({
            'roi': '세포질 ROI 탭의 검출 설정(자동 / 수동 threshold)으로 프레임마다 세포와 핵을 찾고, 세포에서 핵을 '
                   '뺀 영역을 세포질로 씁니다.',
            'pt': 'ParticleTracker의 세포 분할(RI 채널의 세포 몸체, triangle / Otsu threshold)을 프레임마다 그대로 '
                  '씁니다. 핵이 없으므로 세포 전체를 잽니다.',
            'particle': '입자 추적 탭을 ParticleTracker 방식으로 돌렸을 때 찾은 세포를 그대로 씁니다.'}[a])
        it = self.item
        theme.show_rows(self.f1, [self.z_row], it is not None and it.nz > 1 and a != 'particle')
        self.z_mode.setEnabled(self.z_on.isChecked())
        theme.show_rows(self.f2, [self.div_mode], self.ex_div.isChecked())
        theme.show_rows(self.f2, [self.edge_mode, self.edge_px], self.ex_edge.isChecked())

    def settings(self) -> CT.CellTrackSettings:
        def name(c):
            return c.currentData() or ''
        return CT.CellTrackSettings(
            algorithm=self.algorithm.currentData(), cell_channel=name(self.cell_ch), nuc_channel=name(self.nuc_ch),
            z_project=(self.z_mode.currentData() if self.z_on.isChecked() else ''),
            frame0=self.frame0.value(), frame1=self.frame1.value(), flow=self.flow.isChecked(),
            overlap=self.overlap.value() / 100, gap=self.gap.value(), min_frames=self.min_frames.value(),
            exclude_div=self.ex_div.isChecked(), div_mode=self.div_mode.currentData(),
            exclude_edge=self.ex_edge.isChecked(), edge_mode=self.edge_mode.currentData(),
            edge_px=self.edge_px.value(), region=self.region.currentData(), measure_channel=name(self.meas_ch),
            ref_channel=name(self.ref_ch), ring_in=self.ring_in.value(), ring_out=self.ring_out.value(),
            base_h=self.base_h.value(), thr_on=self.thr_on.isChecked(), thr_until_min=self.thr_until.value(),
            thr_pct=self.thr_pct.value(), filters=[dict(f, conditions=[dict(c) for c in f['conditions']])
                                                   for f in self._filters])

    def set_settings(self, d):
        s = CT.CellTrackSettings.from_dict(d)
        set_data(self.algorithm, s.algorithm)
        self.z_on.setChecked(bool(s.z_project))
        if s.z_project:
            set_data(self.z_mode, s.z_project)
        self.flow.setChecked(s.flow)
        self.overlap.setValue(int(round(s.overlap * 100)))
        self.gap.setValue(s.gap)
        self.min_frames.setValue(s.min_frames)
        self.ex_div.setChecked(s.exclude_div)
        set_data(self.div_mode, s.div_mode)
        self.ex_edge.setChecked(s.exclude_edge)
        set_data(self.edge_mode, s.edge_mode)
        self.edge_px.setValue(s.edge_px)
        set_data(self.region, s.region)
        self.ring_in.setValue(s.ring_in)
        self.ring_out.setValue(s.ring_out)
        self.base_h.setValue(s.base_h)
        self.thr_on.setChecked(s.thr_on)
        self.thr_until.setValue(s.thr_until_min)
        self.thr_pct.setValue(s.thr_pct)
        self._want = dict(cell=s.cell_channel, nuc=s.nuc_channel, meas=s.measure_channel, ref=s.ref_channel)
        self._filters = s.filters or [CT.default_filter()]
        self._build_filters()
        self.bind(self.item)

    # ---- filters ------------------------------------------------------------

    def _build_filters(self):
        lay = self.b4_lay
        while lay.count():
            w = lay.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._cond_rows = []
        n = QLabel('조건에 맞는 세포를 필터 이름으로 묶어 그래프 · 표 · 내보내기에서 전체 세포와 비교합니다.')
        n.setWordWrap(True)
        theme.hint(n)
        lay.addWidget(n)
        self._name_edits = []
        for fi, f in enumerate(self._filters):
            holder = QWidget()
            form = QFormLayout(holder)
            form.setContentsMargins(0, 0, 0, 0)
            if len(self._filters) > 1:
                hw = QWidget()
                hh = QHBoxLayout(hw)
                hh.setContentsMargins(0, 0, 0, 0)
                hh.addWidget(theme.section_header(f.get('name') or f'필터 {fi + 1}'))
                hh.addStretch()
                rmf = QPushButton('필터 지우기')
                theme.destructive(rmf)
                rmf.clicked.connect(lambda _=False, fi=fi: self.remove_filter(fi))
                hh.addWidget(rmf)
                form.addRow(hw)
            name = QLineEdit(f.get('name') or f'필터 {fi + 1}')
            name.editingFinished.connect(lambda fi=fi, e=name: self._rename(fi, e.text()))
            form.addRow('필터 이름', name)
            self._name_edits.append(name)
            comb = combo(CT.COMBINE)
            set_data(comb, f.get('combine', 'all'))
            comb.currentIndexChanged.connect(lambda _i, fi=fi, c=comb: self._combine(fi, c.currentData()))
            form.addRow('조건 결합', comb)
            rows = [ConditionRows(self, form, fi, ci, c) for ci, c in enumerate(f.get('conditions') or [])]
            for r in rows:
                r.rm.setEnabled(len(rows) > 1)
            self._cond_rows.append(rows)
            lay.addWidget(holder)
            theme.unify(holder)
        bw = QWidget()
        bh = QHBoxLayout(bw)
        bh.setContentsMargins(0, 0, 0, 0)
        add_c = QPushButton('조건 추가')
        add_c.clicked.connect(self.add_condition)
        bh.addWidget(add_c)
        bh.addStretch()
        add_f = QPushButton('필터 추가')
        add_f.clicked.connect(self.add_filter)
        bh.addWidget(add_f)
        lay.addWidget(bw)
        self.filter_state = theme.StatusLabel('', 'info')
        lay.addWidget(self.filter_state)

    def _rename(self, fi, text):
        if 0 <= fi < len(self._filters) and text.strip():
            self._filters[fi]['name'] = text.strip()
            self.refresh()

    def _combine(self, fi, v):
        self._filters[fi]['combine'] = v
        self.refresh()

    def filters_edited(self):
        if self._busy:
            return
        for fi, rows in enumerate(self._cond_rows):
            for ci, r in enumerate(rows):
                r.sync()
                self._filters[fi]['conditions'][ci] = r.get()
        self.refresh()

    def add_condition(self):
        self._filters[-1]['conditions'].append(CT.default_condition())
        self._build_filters()
        self.refresh()

    def remove_condition(self, fi, ci):
        conds = self._filters[fi]['conditions']
        if len(conds) > 1:
            del conds[ci]
            self._build_filters()
            self.refresh()

    def add_filter(self):
        self._filters.append(CT.default_filter(len(self._filters) + 1))
        self._build_filters()
        self.refresh()

    def remove_filter(self, fi):
        if len(self._filters) > 1:
            del self._filters[fi]
            self._build_filters()
            self.refresh()

    # ---- channels -----------------------------------------------------------

    def _fill_channels(self, it):
        want = getattr(self, '_want', None) or {}
        old = {k: (c.currentData() or want.get(k, '')) for k, c in
               (('cell', self.cell_ch), ('nuc', self.nuc_ch), ('meas', self.meas_ch), ('ref', self.ref_ch))}
        roles = {}
        if it is not None:
            try:
                roles = dict(self.win.roi_panel.roles(it))
            except Exception:  # noqa: BLE001
                roles = {}
        for key, c, none in (('cell', self.cell_ch, False), ('nuc', self.nuc_ch, True),
                             ('meas', self.meas_ch, False), ('ref', self.ref_ch, True)):
            c.blockSignals(True)
            c.clear()
            if none:
                c.addItem('없음', '')
            if it is not None:
                for i, n in enumerate(it.channels):
                    c.addItem(f'CH{i} ({n})', n)
            if old[key] and c.findData(old[key]) >= 0:
                set_data(c, old[key])
            elif it is not None and it.channels:
                ch = list(it.channels)
                guess = {'cell': roles.get('bg'), 'nuc': roles.get('nuc')}.get(key)
                if key == 'meas':
                    guess = next((i for i in range(len(ch)) if i not in (roles.get('bg'), roles.get('nuc'))), 0)
                if key == 'ref':
                    guess = None
                if guess is not None and guess < len(ch):
                    set_data(c, ch[guess])
            c.blockSignals(False)

    # ---- running ------------------------------------------------------------

    def status(self, msg):
        self.win.statusBar().showMessage(msg)

    def _idx(self, it, name, default=None):
        ch = list(it.channels)
        return ch.index(name) if name in ch else default

    def run(self, it, progress=None) -> CT.CellTrackState:
        """Detect, link and measure the cells of one image."""
        from .cellroi import is_ri
        from .track_panel import frame_planes
        s = self.settings()
        T = it.nt
        if T < 2:
            raise ValueError('시간축이 없는 이미지입니다.')
        f0 = max(1, s.frame0) - 1
        f1 = (s.frame1 if 0 < s.frame1 <= T else T) - 1
        if s.frame1 == 1 and T > 1 and s.frame0 == 1:
            f1 = T - 1
        frames = list(range(f0, f1 + 1))
        frames0 = list(frames)
        if len(frames) < 2:
            raise ValueError('프레임이 둘 이상이어야 합니다.')
        z = (s.z_project if it.nz > 1 and s.z_project else it.z)
        px = float(it.pixel_um or 0.1)
        times = list(it.image.times) if it.image.times else [float(t) for t in range(T)]
        th = [float(times[t]) / 3600 if it.image.times else float(t) for t in frames]
        roles = dict(self.win.roi_panel.roles(it))
        ci = self._idx(it, s.cell_channel, roles.get('bg', 0))
        ni = self._idx(it, s.nuc_channel) if s.nuc_channel else None
        mi = self._idx(it, s.measure_channel, None)
        if mi is None:
            raise ValueError('측정 채널이 이 이미지에 없습니다.')
        ri = self._idx(it, s.ref_channel) if s.ref_channel else None

        def say(m):
            if progress:
                progress(f'{m} ({it.label})')
            QApplication.processEvents()

        cells_img, meas, ref, nucs = [], [], [], []
        for k, t in enumerate(frames):
            p = frame_planes(it, t, z)
            cells_img.append(np.asarray(p[ci], np.float32))
            meas.append(np.asarray(p[mi], np.float32))
            ref.append(np.asarray(p[ri], np.float32) if ri is not None else None)
            if s.algorithm == 'roi':
                nucs.append(np.asarray(p[ni], np.float32) if ni is not None else None)
            say(f'세포질 강도 추적: 프레임 읽기 {k + 1}/{len(frames)}')
        detector = ''
        native = False
        flows = None
        nuc_labels = [None] * len(frames)
        if s.algorithm == 'pt':
            if not is_ri(cells_img[0]):
                raise ValueError('ParticleTracker 방식은 RI(HT) 세포 채널이 필요합니다. 세포 채널을 확인하세요.')
            labs, flows = CT.pt_cell_labels(np.stack(cells_img), px, s.flow, say)
            detector = f'RI 세포 분할 ({it.channels[ci]})'
        elif s.algorithm == 'particle':
            st = getattr(it, 'tracks', None)
            pt = getattr(st, 'pt', None) if st is not None else None
            if not pt:
                raise ValueError('입자 추적 결과에 세포가 없습니다. 입자 추적 탭을 ParticleTracker 방식으로 먼저 돌리세요.')
            from .pt_engine import _unpack
            CID = _unpack(pt['arrays'])['CID']
            if CID.shape[1:] != cells_img[0].shape:
                raise ValueError(f'입자 추적의 세포 격자 {CID.shape[1:]}가 이미지 {cells_img[0].shape}와 다릅니다.')
            labs = [CID[t].astype(np.int32) for t in frames if t < len(CID)]
            frames = frames[:len(labs)]
            th = th[:len(labs)]
            detector = '입자 추적 (ParticleTracker) 세포'
            say('세포질 강도 추적: ParticleTracker 형광 격자 읽기')
            ref_name = it.channels[ri] if ri is not None else (pt['sources']['reference'].rsplit('::', 1)[-1])
            nat = CT.pt_native(pt, it.channels[mi], ref_name)
            if nat is not None:   # measured as ParticleTracker's grid (the 2026-11-19 세포 단위 밝기)
                nl, nm, nr, npx = nat
                keep = [k for k, t in enumerate(frames) if t < len(nl)]
                frames, th = [frames[k] for k in keep], [th[k] for k in keep]
                labs = [nl[t] for t in frames]
                meas = [nm[t] for t in frames]
                ref = [nr[t] if nr is not None else None for t in frames]
                px, native = npx, True
                S_ht, reg_ht = float(pt['S']), pt['reg']
                detector = '입자 추적 (ParticleTracker) 세포 · 형광 격자'
        else:
            rp = self.win.roi_panel
            p = self.win.track_panel._cell_params(it)
            rl = {'bg': 0, 'nuc': 1 if ni is not None else None}
            labs = []
            for k in range(len(frames)):
                planes = np.stack([cells_img[k]] + ([nucs[k]] if ni is not None else []))
                r = rp._run_planes(planes, px, rl, p, rp.manual_mode(), rp._man_value('cell'), rp._man_value('nuc'))
                labs.append(np.asarray(r.labels, np.int32))
                nuc_labels[k] = np.asarray(r.nuclei, np.int32) if r.nuclei is not None else None
                say(f'세포질 강도 추적: 세포 검출 {k + 1}/{len(frames)}')
            if s.flow:
                flows = CT.image_flows(cells_img, say)
            detector = f'{it.channels[ci]} 세포' + (f' + {it.channels[ni]} 핵' if ni is not None else '')
        say('세포질 강도 추적: 세포 잇기')
        if s.algorithm == 'particle':
            linked, split = labs, set()      # ParticleTracker's cell IDs are linked already
        else:
            linked, split = CT.link(labs, s.overlap, s.gap, flows if s.flow else None)
        divided = set()
        if s.div_mode in ('split', 'both'):
            divided |= split
        if s.div_mode in ('ri', 'both') and is_ri(cells_img[0]):
            try:
                divided |= CT.ri_mitotic(np.stack([cells_img[frames0.index(t)] for t in frames]),
                                         [CID[t].astype(np.int32) for t in frames] if native else linked)
            except Exception:  # noqa: BLE001
                traceback.print_exc()
        thr = CT.early_threshold(meas, th, s.thr_until_min, s.thr_pct, 1 if native else 2) \
            if s.thr_on else float('nan')
        rows = []
        for k, t in enumerate(frames):
            for r in CT.measure_frame(linked[k], nuc_labels[k] if not native else None, meas[k], ref[k], px, s,
                                      thr, s.edge_px, *((50, True) if native else ())):
                r.update(frame=t + 1, time_h=th[k])
                if native:   # centre on the image (HT) grid for the canvas
                    r['x'] = float((r['x'] + .5) * S_ht - .5 + reg_ht.dx_ht.values[t])
                    r['y'] = float((r['y'] + .5) * S_ht - .5 + reg_ht.dy_ht.values[t])
                rows.append(r)
            say(f'세포질 강도 추적: 측정 {k + 1}/{len(frames)}')
        CT.add_changes(rows, s.base_h)
        return CT.CellTrackState(settings=s.to_dict(), frames=frames, times_h=th, labels=CT.pack_labels([CID[t].astype(np.int32) for t in frames] if native else linked),
                                 rows=rows, divided=sorted(divided), threshold=thr, detector=detector)

    def run_current(self, item=None):
        it = item or self.win.current
        if it is None:
            return None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        t0 = time.perf_counter()
        try:
            it.cell_tracks = self.run(it, self.status)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self.status(f'세포질 강도 추적 실패 ({it.label}): {exc}')
            return None
        finally:
            QApplication.restoreOverrideCursor()
        n = len(it.cell_tracks.cells())
        self.status(f'세포질 강도 추적 ({it.label}): 세포 {n}개, {len(it.cell_tracks.frames)} 프레임 '
                    f'({time.perf_counter() - t0:.1f}초)')
        self._after()
        return it.cell_tracks

    def run_all(self):
        done = 0
        for it in list(self.win.analysis_items()):
            if it.nt < 2:
                continue
            try:
                it.cell_tracks = self.run(it, self.status)
                done += 1
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                self.status(f'{it.label}: 세포질 강도 추적 실패 ({exc})')
        self.status(f'세포질 강도 추적: 이미지 {done}개를 추적했습니다.' if done else
                    '세포질 강도 추적: 시간축이 있는 이미지가 없습니다.')
        self._after()
        return done

    def _after(self):
        self._outline_cache = {}
        self.win.set_dirty(True)
        self.refresh()
        self.win.update_tab_badges()
        self.win.live_box.schedule()
        self.draw()

    def bar_status(self):
        n = sum(1 for it in self.win.analysis_items() if it.nt > 1)
        if not n:
            return '시간축이 있는 이미지가 없습니다.', 'warning'
        return f'시간축이 있는 이미지 {n}개', None

    # ---- classes ------------------------------------------------------------

    def classes(self) -> dict:
        """(image_id, cell_id) -> class over every tracked image."""
        s = self.settings()
        cells = []
        for it in self.win.analysis_items():
            st = getattr(it, 'cell_tracks', None)
            if st is None:
                continue
            div = set(st.divided)
            for cid, rs in st.cells().items():
                rs = sorted(rs, key=lambda r: r['frame'])
                edge = [r for r in rs if r['edge']] if s.edge_px == st.settings.get('edge_px', s.edge_px) else \
                    [r for r in rs if self._edge(it, r, s.edge_px)]
                cells.append(((it.image_id, cid), rs, dict(divided=cid in div, edge_frac=len(edge) / max(len(rs), 1))))
        return CT.classify(cells, s)

    def _edge(self, it, r, px):
        return r['edge']

    def summary_rows(self, cls=None) -> list:
        cls = self.classes() if cls is None else cls
        out = []
        for it in self.win.analysis_items():
            st = getattr(it, 'cell_tracks', None)
            if st is None:
                continue
            div = set(st.divided)
            for cid, rs in sorted(st.cells().items()):
                rs = sorted(rs, key=lambda r: r['frame'])
                k = cls.get((it.image_id, cid), 'short')

                def col(c):
                    v = np.array([r.get(c, np.nan) for r in rs], float)
                    return float(np.nanmax(v)) if np.isfinite(v).any() else float('nan')
                out.append(dict(image=it.label, image_id=it.image_id, group=it.group or '', cell=f'C{cid:03d}',
                                cell_id=cid, cls=CT.class_text(k), frames=len(rs), first_frame=rs[0]['frame'],
                                last_frame=rs[-1]['frame'], divided=cid in div,
                                edge_frames=sum(1 for r in rs if r['edge']),
                                area_um2_mean=float(np.mean([r['area_um2'] for r in rs])),
                                I_max=col('I'), I_thr_max=col('I_thr'), I_thr_change_max=col('I_thr_change'),
                                ratio_max=col('ratio')))
        return out

    def frame_rows(self, cls=None) -> list:
        cls = self.classes() if cls is None else cls
        out = []
        for it in self.win.analysis_items():
            st = getattr(it, 'cell_tracks', None)
            if st is None:
                continue
            for r in st.rows:
                k = cls.get((it.image_id, r['cell_id']), 'short')
                out.append({'image': it.label, 'image_id': it.image_id, 'group': it.group or '',
                            'cell': f'C{r["cell_id"]:03d}', 'cls': CT.class_text(k), **r})
        return out

    def data_tables(self):
        cls = self.classes()
        return [(DATA_NAMES['frames'][0], DATA_NAMES['frames'][1], self.frame_rows(cls)),
                (DATA_NAMES['cells'][0], DATA_NAMES['cells'][1], self.summary_rows(cls))]

    # ---- view ---------------------------------------------------------------

    def bind(self, item):
        self.item = item
        self._busy = True
        self._fill_channels(item)
        if item is not None:
            self.frame0.setMaximum(max(item.nt, 1))
            self.frame1.setMaximum(max(item.nt, 1))
            if self.frame1.value() <= 1 or self.frame1.value() > item.nt:
                self.frame1.setValue(item.nt)
        self._busy = False
        self._sync()
        self.refresh()

    def refresh(self):
        it = self.item
        st = getattr(it, 'cell_tracks', None) if it is not None else None
        if it is None:
            self.det_state.set_kind('info')
            self.det_state.setText('이미지가 없습니다.')
        elif it.nt < 2:
            self.det_state.set_kind('warning')
            self.det_state.setText('시간축이 없는 이미지입니다.')
        elif st is None:
            self.det_state.set_kind('info')
            self.det_state.setText(f'T {it.nt} 프레임 · 아래 측정 바에서 추적합니다.')
        else:
            per = [len(set(np.unique(st.labels_at(t))) - {0}) for t in st.frames] if st.labels else []
            self.det_state.set_kind('info')
            self.det_state.setText(f'{st.detector}: 프레임마다 세포 {min(per)}-{max(per)}개 ({it.label})' if per else
                                   st.detector)
        cls = self.classes()
        mine = {k[1]: v for k, v in cls.items() if it is not None and k[0] == it.image_id}
        counts = {}
        for v in cls.values():
            counts[v] = counts.get(v, 0) + 1
        names = [f.get('name') or '필터' for f in self._filters]
        n_long = sum(v for k, v in counts.items() if k != 'short')
        if st is not None:
            nd = sum(1 for c in st.divided if c in mine)
            ne = sum(1 for k, v in mine.items() if v == 'excluded')
            self.link_state.set_kind('info')
            self.link_state.setText(f'제외: 분열 {nd}개 · 가장자리 포함 {ne}개 → 남은 긴 세포 '
                                    f'{sum(1 for v in mine.values() if v not in ("short", "excluded"))}개')
        else:
            self.link_state.set_kind('info')
            self.link_state.setText('')
        if hasattr(self, 'filter_state'):
            here = ' · '.join(f'{n}: {sum(1 for v in mine.values() if v == n)}개' for n in names)
            self.filter_state.setText(' / '.join(f'{n}: 세포 {counts.get(n, 0)}개' for n in names) +
                                      f' / 남은 긴 세포 {n_long - counts.get("excluded", 0)}개' +
                                      (f' · 이 이미지: {here}' if st is not None else ''))
        total = sum(counts.values())
        if total:
            self.summary.set_kind('info')
            self.summary.setText(f'세포 {total}개 · 긴 세포 {n_long}개 · 제외 {counts.get("excluded", 0)}개')
        else:
            self.summary.set_kind(None)
            self.summary.setText('아직 추적하지 않았습니다.')
        for w in self.chips.values():
            self.chip_lay.removeWidget(w)
            w.setParent(None)
            w.deleteLater()
        self.chips = {}
        for k in names + ['rest', 'excluded', 'short']:
            if not counts.get(k):
                continue
            c = QCheckBox(f'{CT.class_text(k)} ({counts[k]})')
            c.setChecked(k != 'short')
            theme.chip(c)
            c.toggled.connect(lambda _v: self.draw())
            self.chip_lay.addWidget(c)
            self.chips[k] = c
        self.data_rows.refresh()
        self.draw()

    def shown(self, k) -> bool:
        c = self.chips.get(k)
        return c is None or c.isChecked()

    def visible_tab(self) -> bool:
        return self.win.tab_current('cyto_track_tab')

    def _clear(self):
        sc = self.win.canvas.scene()
        for i in self._scene:
            if i.scene() is sc:
                sc.removeItem(i)
        self._scene = []

    def _outlines(self, it, t):
        key = (id(it), t)
        if key not in self._outline_cache:
            from skimage import measure
            lab = it.cell_tracks.labels_at(t)
            out = {}
            if lab is not None:
                from scipy import ndimage as ndi
                for i, sl in enumerate(ndi.find_objects(lab), start=1):
                    if sl is None:
                        continue
                    y0, x0 = sl[0].start, sl[1].start
                    m = np.pad(lab[sl] == i, 1)
                    cs = measure.find_contours(m.astype(float), 0.5)
                    if cs:
                        c = max(cs, key=len)
                        out[i] = [(x + x0 - 1 + 0.5, y + y0 - 1 + 0.5) for y, x in c[::2]]
            self._outline_cache[key] = out
        return self._outline_cache[key]

    def draw(self):
        self._clear()
        it = self.win.current
        if it is None or getattr(it, 'cell_tracks', None) is None or not self.show_on.isChecked():
            return
        if not self.visible_tab():
            return
        sc = self.win.canvas.scene()
        cls = {k[1]: v for k, v in self.classes().items() if k[0] == it.image_id}
        for cid, xy in self._outlines(it, it.t).items():
            k = cls.get(cid, 'short')
            if not self.shown(k):
                continue
            if k in ('rest',):
                col = QColor(*PALETTE[cid % len(PALETTE)])
            elif k in ('excluded', 'short'):
                col = QColor(170, 170, 170)
            else:
                col = QColor(*FILTER_COLOR)
            path = QPainterPath(QPointF(*xy[0]))
            for p in xy[1:]:
                path.lineTo(QPointF(*p))
            path.closeSubpath()
            pi = QGraphicsPathItem(path)
            pen = QPen(col)
            pen.setCosmetic(True)
            pen.setWidthF(2.4 if k not in ('rest', 'excluded', 'short') else 1.4)
            if k == 'excluded':
                pen.setStyle(Qt.PenStyle.DashLine)
            pi.setPen(pen)
            pi.setZValue(13)
            sc.addItem(pi)
            self._scene.append(pi)
            xs, ys = zip(*xy)
            tx = QGraphicsSimpleTextItem(str(cid))
            tx.setBrush(col)
            tx.setFlag(QGraphicsSimpleTextItem.GraphicsItemFlag.ItemIgnoresTransformations)
            f = tx.font()
            f.setPointSize(12)
            f.setBold(True)
            tx.setFont(f)
            tx.setPos(float(np.mean(xs)), float(np.mean(ys)))
            tx.setZValue(14)
            sc.addItem(tx)
            self._scene.append(tx)

    # ---- saving -------------------------------------------------------------

    def save_item(self, it, folder: Path, stem: str, csv_on=True, fig=False) -> list:
        st = getattr(it, 'cell_tracks', None)
        if st is None:
            return []
        cls = self.classes()
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        files = []
        if fig:
            files += self.save_figure(it, folder / f'{stem}_cell_track.png', cls)
        if not csv_on:
            return files
        for rows, suffix in (([r for r in self.frame_rows(cls) if r['image_id'] == it.image_id], 'cell_track_points'),
                             ([r for r in self.summary_rows(cls) if r['image_id'] == it.image_id], 'cell_track_cells')):
            if not rows:
                continue
            p = folder / f'{stem}_{suffix}.csv'
            cols = list(dict.fromkeys(k for r in rows for k in r))
            with open(p, 'w', newline='', encoding='utf-8') as f:
                w = csv.DictWriter(f, fieldnames=cols)
                w.writeheader()
                for r in rows:
                    w.writerow({k: (f'{v:.6g}' if isinstance(v, float) else v) for k, v in r.items()})
            files.append(p)
        return files


def _save_figure(panel, it, path, cls):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    st = it.cell_tracks
    col = 'I_thr' if st.settings.get('thr_on') else 'I'
    mine = {k[1]: v for k, v in cls.items() if k[0] == it.image_id}
    names = [f.get('name') or '필터' for f in panel._filters]
    fig, ax = plt.subplots(figsize=(9, 4.5))
    groups = [(n, (0.85, 0.1, 0.1)) for n in names] + [('rest', (0, 0, 0))]
    for g, c in groups:
        ids = [cid for cid, v in mine.items() if v == g]
        if not ids:
            continue
        by = {}
        for cid in ids:
            rs = sorted((r for r in st.rows if r['cell_id'] == cid), key=lambda r: r['frame'])
            ax.plot([r['time_h'] for r in rs], [r.get(col, np.nan) for r in rs], '-', lw=.6, alpha=.3, color=c)
            for r in rs:
                by.setdefault(r['time_h'], []).append(r.get(col, np.nan))
        t = sorted(by)
        q = np.array([np.nanpercentile(by[x], [25, 50, 75]) for x in t])
        ax.fill_between(t, q[:, 0], q[:, 2], color=c, alpha=.15)
        ax.plot(t, q[:, 1], '-', lw=2.2, color=c, label=f'{CT.class_text(g)} (n = {len(ids)})')
    ax.set_xlabel('time (h)')
    ax.set_ylabel(col)
    ax.set_title(it.label)
    ax.legend(loc='upper left', bbox_to_anchor=(1.01, 1), fontsize=8)
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return [path]


CellTrackPanel.save_figure = lambda self, it, path, cls: _save_figure(self, it, path, cls)


def cell_track_live(panel):
    it = panel.item
    st = getattr(it, 'cell_tracks', None) if it is not None else None
    if st is None:
        return None
    cls = {k[1]: v for k, v in panel.classes().items() if k[0] == it.image_id}
    names = [f.get('name') or '필터' for f in panel._filters]
    t = it.t + 1
    now = [r for r in st.rows if r['frame'] == t]
    vals = [r.get('I_thr' if st.settings.get('thr_on') else 'I') for r in now]
    vals = [v for v in vals if v is not None and np.isfinite(v)]
    return [('세포 (이 시점)', len(now)), ('긴 세포', sum(1 for v in cls.values() if v not in ('short',))),
            (names[0] if names else '필터', sum(1 for v in cls.values() if v in names)),
            ('밝기 중앙값', f'{np.median(vals):.3g}' if vals else '–')]
