"""Cell / cytosol ROI tab of Cytosol Viewer: detection, editing, ImageJ ROI I/O."""

from __future__ import annotations

import csv
import re
import copy
import threading
import time
import traceback
from dataclasses import replace
from pathlib import Path

import numpy as np
from skimage import filters
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .cellroi import (
    CellRois,
    RoiParams,
    ThresholdPreview,
    image_size_range,
    merged_preview,
    segment_cells,
    threshold_cells,
)
from .imageid import roi_id
from .intensity import make_regions
from .lut import ImageItem, item_folder, item_stem, match_channel, unique_stems
from .measure_box import MeasureBox

EDGE_LABELS = [
    ('trim', '안쪽 경계로 자르기'),
    ('exclude', '제외'),
    ('keep', '그대로 두기'),
]
STATUS_KO = {'ok': '', 'edge-trimmed': '프레임 안쪽으로 자름', 'edge': '프레임에 걸침'}
TOOLS = [
    ('select', '선택/이동', 'V', '클릭: 세포 선택, 드래그: 화면 이동'),
    ('add', '더하기', 'A', '드래그로 영역을 그려 선택한 세포에 더하기'),
    ('sub', '빼기', 'S', '드래그로 영역을 그려 선택한 세포에서 빼기 (선택 없으면 모든 세포에서)'),
    ('new', '새 세포', 'N', '드래그로 그린 영역을 새 세포로 추가'),
    ('cut', '자르기', 'C', '선을 그어 세포를 둘로 자르기 (선택한 세포, 선택이 없으면 선이 지나는 모든 세포)'),
]
THR_STEPS = 1000
THRESHOLDS = [
    ('nuc', '핵 threshold',
     '핵 채널(약하게 스무딩)에서 이 값보다 밝은 곳을 핵으로 봅니다. 자동을 켜면 Otsu 값을 쓰고 칸에 표시합니다.'),
    ('cell', '세포 threshold',
     '배경 신호 채널에서 이 값보다 밝은 곳을 세포로 봅니다 (세포 사이 틈은 이보다 어둡게). '
     '배경 포화값보다 작아야 합니다. 자동을 켜면 Otsu 값을 쓰고 칸에 표시합니다.'),
]
SIZE_STEPS = 1000
SIZE_LOG = (0.0, 5.0)  # size sliders span 10**0 … 10**5 µm²
THR_COLORS = {'cell': (1.0, 0.85, 0.0), 'nuc': (0.2, 0.5, 1.0)}
NUC_HINT = re.compile(r'dapi|hoechst|nuc|draq|h2b|405', re.I)


def guess_roles(item: ImageItem) -> dict:
    """Nucleus = a DAPI/Hoechst-like or blue channel; background = first other channel."""
    nuc = None
    for i, name in enumerate(item.channels):
        if NUC_HINT.search(name):
            nuc = i
            break
    if nuc is None and len(item.channels) > 1:
        for i, lut in enumerate(item.luts):
            r, g, b = lut.color
            if b > 0.6 and r < 0.4 and g < 0.6:
                nuc = i
                break
    others = [i for i in range(len(item.channels)) if i != nuc]
    return {'nuc': nuc, 'bg': others[0] if others else 0}


class RoiPanel(QWidget):
    liveDone = Signal(int, object, float)  # job number, CellRois or error text, seconds
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.selected = 0
        self._busy = False
        self._tp_cache = None  # (key, ThresholdPreview, detector-input RGB)
        # coalesce preview updates while a threshold slider moves
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(30)
        self._preview_timer.timeout.connect(self.win.update_preview)

        # roles
        self.nuc_combo = QComboBox()
        self.bg_combo = QComboBox()
        self.nuc_combo.currentIndexChanged.connect(self._roles_changed)
        self.bg_combo.currentIndexChanged.connect(self._roles_changed)
        roles = QGroupBox('채널 역할')
        fl = QFormLayout(roles)
        fl.addRow('핵', self.nuc_combo)
        fl.addRow('배경 신호', self.bg_combo)

        # detection parameters
        self.sat = QDoubleSpinBox()
        self.sat.setRange(0, 1e9)
        self.sat.setDecimals(2)
        self.sat.setEnabled(False)
        self.sat.setToolTip('배경 신호 채널을 이 값에서 흰색으로 포화시킵니다 (LUT를 밝게). '
                            '세포질 전체가 하나의 덩어리로 보이도록 낮추세요.')
        self.sat.valueChanged.connect(self._sat_changed)
        self.sat_auto = QCheckBox('자동')
        self.sat_auto.setChecked(True)
        self.sat_auto.setToolTip('켜면 배경 신호 채널의 중앙값(스무딩 후)을 포화값으로 씁니다. '
                                 '칸에는 실제로 쓰는 값이 표시됩니다. 끄면 직접 입력합니다.')
        self.sat_auto.toggled.connect(self._sat_auto_toggled)
        self.input_view = QCheckBox('검출용 합성 이미지 보기 (배경 밝게 + 핵)')
        self.input_view.toggled.connect(lambda _: self.win.update_preview())
        # thresholds: 자동 checkbox (Otsu), value shown either way, slider over
        # the channel's value range
        self.thr = {}
        for key, label, tip in THRESHOLDS:
            auto = QCheckBox('자동')
            auto.setChecked(True)
            auto.setToolTip(tip)
            spin = QDoubleSpinBox()
            spin.setRange(-1e9, 1e9)
            spin.setDecimals(2)
            spin.setToolTip(tip)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, THR_STEPS)
            for w in (spin, slider):
                w.setEnabled(False)
            auto.toggled.connect(lambda on, k=key: self._thr_auto(k, on))
            spin.valueChanged.connect(lambda _, k=key: self._thr_spin(k))
            slider.valueChanged.connect(lambda v, k=key: self._thr_slider(k, v))
            self.thr[key] = {'label': label, 'auto': auto, 'spin': spin, 'slider': slider,
                             'range': (0.0, 1.0)}
        self.thr_view = QCheckBox('threshold 영역 미리보기 (노랑: 세포, 파랑: 핵)')
        self.thr_view.setToolTip('threshold를 넘는 영역을 검출용 합성 이미지 위에 칠해 보여줍니다. '
                                 '수동 threshold 슬라이더를 움직이면 자동으로 켜지고 바로 갱신됩니다.')
        self.thr_view.toggled.connect(lambda _: self.win.update_preview())
        def area_spin(value, special=None):
            w = QDoubleSpinBox()
            w.setRange(0 if special else 1, 1e6)
            w.setDecimals(1)
            w.setValue(value)
            w.setSuffix(' µm²')
            if special:
                w.setSpecialValueText(special)
            return w

        # size ranges (both modes): cells / nuclei outside them are dropped
        self.min_cell = area_spin(RoiParams.min_cell_um2)
        self.max_cell = area_spin(RoiParams.max_cell_um2, '제한 없음')
        self.min_nuc = area_spin(RoiParams.min_nucleus_um2)
        self.max_nuc = area_spin(RoiParams.max_nucleus_um2, '제한 없음')
        for w in (self.min_cell, self.max_cell):
            w.setToolTip('이 범위 밖의 세포는 버립니다 (최대 0 = 제한 없음).')
        for w in (self.min_nuc, self.max_nuc):
            w.setToolTip('이 범위 밖의 핵은 핵으로 쓰지 않습니다 (최대 0 = 제한 없음).')
        self.size_auto = QCheckBox('자동 (이미지마다 추정)')
        self.size_auto.setToolTip(
            '이미지마다 크기 제한 없이 한 번 검출해 (프레임에 걸친 세포 제외) 그 이미지의 '
            '범위를 정합니다: 세포 크기의 중앙값 ÷ 4 ~ × 3 (핵은 ÷ 20 ~ × 3; 작은 핵을 버리면 그 세포가 '
            '이웃 세포에 붙기 때문), 그리고 동떨어진 값(먼지, 덩어리; '
            '로그 크기의 Tukey 기준, 사분위 ± 1.5 IQR)을 뺀 가장 작은 ~ 가장 큰 크기를 모두 '
            '포함하는 범위입니다. 칸에는 현재 이미지에 쓴 값이 표시되고, 끄면 직접 입력합니다.')
        self.size_auto.toggled.connect(self._size_auto_toggled)
        self._size_cache = {}  # image key -> (cell range, nucleus range) estimated on it
        self.fit_size = QCheckBox('붙은 세포를 크기 범위에 맞게 나누기 · 합치기')
        self.fit_size.setToolTip(
            '최대보다 큰 덩어리는 세포 사이 어두운 골을 따라 범위에 맞는 개수로 나누고, '
            '최소보다 작은 조각은 경계가 가장 약한 이웃과 합칩니다 (합친 크기가 범위에 더 맞을 때만). '
            '핵 크기 범위에도 똑같이 적용합니다. 그래도 범위 밖이면 버립니다.')
        self.neck_cut = QCheckBox('가는 목으로 붙은 세포 자르기')
        self.neck_cut.setToolTip(
            '핵에서 세포 안쪽으로 같은 거리의 고리를 넓혀 가다가, 고리가 좁은 틈(아래 목 폭 이하)을 '
            '지나 다시 넓어지는(목보다 2.5배 이상) 곳을 목으로 보고, 목 부근에서 신호가 가장 어두운 '
            '경로로 자릅니다. 그런 목이 없으면 윤곽에서 깊게 파인 오목점 두 개를 잇는 가장 짧은 선으로 '
            '자릅니다. 잘린 쪽은 핵 없는 새 세포가 됩니다 (핵을 놓친 이웃 세포).')
        self.neck_max = QDoubleSpinBox()
        self.neck_max.setRange(0.5, 50)
        self.neck_max.setSingleStep(0.5)
        self.neck_max.setValue(RoiParams.neck_max_um)
        self.neck_max.setSuffix(' µm')
        self.neck_max.setToolTip('이 폭 이하의 좁은 연결만 목으로 봅니다.')
        self.smooth = QDoubleSpinBox()
        self.smooth.setRange(0.1, 20)
        self.smooth.setSingleStep(0.1)
        self.smooth.setValue(RoiParams.smooth_um)
        self.smooth.setSuffix(' µm')
        self.edge_combo = QComboBox()
        for key, text in EDGE_LABELS:
            self.edge_combo.addItem(text, key)
        self.edge_margin = QDoubleSpinBox()
        self.edge_margin.setRange(0.1, 100)
        self.edge_margin.setValue(RoiParams.edge_margin_um)
        self.edge_margin.setSuffix(' µm')
        self.edge_margin.setToolTip('프레임에 걸친 세포는 프레임에서 이만큼 안쪽에 새 경계선을 그어 자릅니다.')

        # 자동 sub-tab: the full pipeline (manual thresholds feed into it)
        auto = QWidget()
        dl = QFormLayout(auto)
        row = QHBoxLayout()
        row.addWidget(self.sat_auto)
        row.addWidget(self.sat, 1)
        dl.addRow('배경 포화값', row)
        dl.addRow(self.input_view)
        for key, t in self.thr.items():
            row = QHBoxLayout()
            row.addWidget(t['auto'])
            row.addWidget(t['spin'], 1)
            dl.addRow(t['label'], row)
            dl.addRow('', t['slider'])
        dl.addRow(self.thr_view)
        dl.addRow('스무딩', self.smooth)
        dl.addRow(self.fit_size)
        row = QHBoxLayout()
        row.addWidget(self.neck_cut)
        row.addWidget(QLabel('목 폭 ≤'))
        row.addWidget(self.neck_max)
        dl.addRow(row)

        # 수동 sub-tab: threshold only (at or above = ROI, below = discarded)
        manual = QWidget()
        ml = QFormLayout(manual)
        note = QLabel('배경 신호 채널에서 threshold 이상인 연결된 영역이 그대로 세포 ROI가 되고, '
                      '그 아래는 버립니다. 핵은 세포 안에서 핵 threshold 이상인 가장 큰 영역입니다. '
                      '스무딩·분할 없이 크기 범위와 프레임 처리만 적용합니다.')
        note.setWordWrap(True)
        note.setStyleSheet('color: gray;')
        ml.addRow(note)
        self.man = {}
        for key, label in (('cell', '세포 threshold'), ('nuc', '핵 threshold')):
            spin = QDoubleSpinBox()
            spin.setRange(-1e9, 1e9)
            spin.setDecimals(2)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, THR_STEPS)
            spin.valueChanged.connect(lambda _, k=key: self._man_spin(k))
            slider.valueChanged.connect(lambda v, k=key: self._man_slider(k, v))
            self.man[key] = {'spin': spin, 'slider': slider, 'range': (0.0, 1.0)}
            ml.addRow(label, spin)
            ml.addRow('', slider)
        self.last_seconds = 0.0  # time the last detection took
        self.last_sizes = None  # size ranges the last detection used, when set per image
        self.man_view = QCheckBox('threshold 영역 미리보기 (노랑: 세포, 파랑: 핵)')
        self.man_view.setChecked(True)
        self.man_view.toggled.connect(lambda _: self.win.update_preview())
        ml.addRow(self.man_view)

        self.mode_tabs = QTabWidget()
        self.mode_tabs.addTab(auto, '자동')
        self.mode_tabs.addTab(manual, '수동 (threshold)')
        self.mode_tabs.currentChanged.connect(self._mode_changed)

        det = QGroupBox('ROI 검출')
        top = QVBoxLayout(det)
        top.addWidget(self.mode_tabs)
        dl = QFormLayout()
        top.addLayout(dl)

        def span(a, b):
            row = QHBoxLayout()
            row.addWidget(a, 1)
            row.addWidget(QLabel('–'))
            row.addWidget(b, 1)
            return row

        # a log-scale slider under every size field (1 µm² … 100 000 µm²; the
        # right end of a maximum slider = no limit)
        self._size_sliders = {}
        for spin in (self.min_cell, self.max_cell, self.min_nuc, self.max_nuc):
            sl = QSlider(Qt.Orientation.Horizontal)
            sl.setRange(0, SIZE_STEPS)
            sl.valueChanged.connect(lambda v, w=spin: self._size_slider(w, v))
            spin.valueChanged.connect(lambda _, w=spin: self._size_sync(w))
            self._size_sliders[spin] = sl
            self._size_sync(spin)
        dl.addRow('세포 크기', span(self.min_cell, self.max_cell))
        dl.addRow('', span(self._size_sliders[self.min_cell], self._size_sliders[self.max_cell]))
        dl.addRow('핵 크기', span(self.min_nuc, self.max_nuc))
        dl.addRow('', span(self._size_sliders[self.min_nuc], self._size_sliders[self.max_nuc]))
        dl.addRow('', self.size_auto)
        dl.addRow('프레임에 걸친 세포', self.edge_combo)
        dl.addRow('안쪽 경계 여백', self.edge_margin)
        run_one = QPushButton('ROI 검출 (현재 이미지)')
        run_one.clicked.connect(self.detect_current)
        run_all = QPushButton('모든 이미지')
        run_all.setToolTip('같은 이름의 채널을 같은 역할로 모든 이미지에서 검출 (선택한 자동/수동 방식)')
        run_all.clicked.connect(self.detect_all)
        row = QHBoxLayout()
        row.addWidget(run_one, 2)
        row.addWidget(run_all, 1)
        dl.addRow(row)
        self.live = QCheckBox('실시간 미리보기 (값을 바꾸면 바로 검출)')
        self.live.setToolTip(
            'threshold, 크기 범위, 스무딩 등을 바꿀 때마다 현재 이미지에서 검출을 다시 돌려 '
            '점선 ROI로 보여줍니다 (이미지 한 장에 약 1초). ROI 검출을 누르면 그 결과를 씁니다. '
            '느리면 끄세요.')
        self.live.toggled.connect(self._live_toggled)
        dl.addRow(self.live)
        # live preview: debounced, one background job at a time
        self._live = None  # (key, CellRois) of the preview shown
        self._live_job = 0
        self._live_busy = False
        self._live_again = False
        self._live_timer = QTimer(self)
        self._live_timer.setSingleShot(True)
        self._live_timer.setInterval(250)
        self._live_timer.timeout.connect(self._live_start)
        self.liveDone.connect(self._live_finished)
        for w in (self.min_cell, self.max_cell, self.min_nuc, self.max_nuc, self.smooth,
                  self.edge_margin, self.sat, self.neck_max):
            w.valueChanged.connect(self.live_changed)
        for w in (self.fit_size, self.sat_auto, self.neck_cut):
            w.toggled.connect(self.live_changed)
        self.edge_combo.currentIndexChanged.connect(self.live_changed)
        self.mode_tabs.currentChanged.connect(self.live_changed)
        for t in list(self.thr.values()) + list(self.man.values()):
            t['spin'].valueChanged.connect(self.live_changed)
            if 'auto' in t:
                t['auto'].toggled.connect(self.live_changed)

        # editing
        self.tool_group = QButtonGroup(self)
        self.tool_group.setExclusive(True)
        tools = QHBoxLayout()
        self.tool_btns = {}
        for key, text, sc, tip in TOOLS:
            b = QPushButton(f'{text} ({sc})')
            b.setCheckable(True)
            b.setToolTip(tip)
            self.tool_group.addButton(b)
            tools.addWidget(b)
            self.tool_btns[key] = b
            b.toggled.connect(lambda on, k=key: on and self.set_tool(k))
            QShortcut(QKeySequence(sc), win, activated=lambda k=key: self.tool_btns[k].setChecked(True))
        self.tool_btns['select'].setChecked(True)
        del_btn = QPushButton('선택 세포 삭제')
        del_btn.clicked.connect(self.delete_selected)
        undo_btn = QPushButton('되돌리기')
        undo_btn.clicked.connect(self.undo)
        redo_btn = QPushButton('다시 실행')
        redo_btn.clicked.connect(self.redo)
        renum_btn = QPushButton('번호 다시 매기기')
        renum_btn.clicked.connect(self.renumber)
        QShortcut(QKeySequence.StandardKey.Undo, win, activated=self.undo)
        QShortcut(QKeySequence.StandardKey.Redo, win, activated=self.redo)
        QShortcut(QKeySequence('Ctrl+Shift+Z'), win, activated=self.redo)
        for k in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            QShortcut(QKeySequence(k), win, activated=self.delete_selected)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), win, activated=self._escape)
        self.show_rois = QCheckBox('ROI 표시')
        self.show_rois.setChecked(True)
        self.show_rois.toggled.connect(lambda _: self.draw_overlay())
        self.show_nuc = QCheckBox('핵 경계 표시')
        self.show_nuc.setChecked(True)
        self.show_nuc.toggled.connect(lambda _: self.draw_overlay())
        self.cell_list = QListWidget()
        self.cell_list.setMinimumHeight(120)
        self.cell_list.currentRowChanged.connect(self._list_selected)
        ed = QGroupBox('확인 · 수정')
        el = QVBoxLayout(ed)
        el.addLayout(tools)
        row = QHBoxLayout()
        row.addWidget(del_btn)
        row.addWidget(undo_btn)
        row.addWidget(redo_btn)
        el.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(self.show_rois)
        row.addWidget(self.show_nuc)
        row.addStretch()
        row.addWidget(renum_btn)
        el.addLayout(row)
        el.addWidget(self.cell_list, 1)
        hint = QLabel('세포를 클릭해 선택한 뒤 더하기/빼기로 영역을 그리세요. '
                      '가운데 버튼 드래그로 화면을 움직이고, Cmd(Ctrl)+드래그로 확대·축소합니다.')
        hint.setWordWrap(True)
        hint.setStyleSheet('color: gray;')
        el.addWidget(hint)

        # which ROIs the 세포질 ROI menu writes (menu check items)
        self.save_cell = QAction('저장할 ROI: 세포 전체', self, checkable=True)
        self.save_nuc = QAction('저장할 ROI: 핵', self, checkable=True)
        self.save_cyto = QAction('저장할 ROI: 세포질 (핵 제외)', self, checkable=True)
        for a in (self.save_cell, self.save_nuc, self.save_cyto):
            a.setChecked(True)
        self.per_image = win.opt_per_image

        meas = QGroupBox('측정할 영역')
        row = QHBoxLayout(meas)
        self.reg_boxes = {}
        for key, text in (('cell', '세포 전체'), ('nuc', '핵'), ('cyto', '세포질')):
            b = QCheckBox(text)
            b.setChecked(True)
            b.toggled.connect(lambda _: self.measure.schedule())
            self.reg_boxes[key] = b
            row.addWidget(b)
        row.addStretch()
        self.measure = MeasureBox(win, 'roi_tab', self.regions_for, 'cell_intensity',
                                  '세포 강도 측정')

        lay = QVBoxLayout(self)
        lay.addWidget(roles)
        lay.addWidget(det)
        lay.addWidget(ed, 1)
        lay.addWidget(meas)
        lay.addWidget(self.measure, 1)

        self._hover = {}  # label -> (text, anchor) of the ROIs drawn now
        self._hover_rois = None
        win.canvas.hover_info = self.hover_info
        win.canvas.cellClicked.connect(self._canvas_click)
        win.canvas.lassoDrawn.connect(self._lasso)

    # ---- helpers --------------------------------------------------------

    @property
    def item(self) -> ImageItem | None:
        return self.win.current

    @property
    def cells(self) -> CellRois | None:
        return self.item.cells if self.item is not None else None

    def status(self, msg):
        self.win.statusBar().showMessage(msg)

    def params(self) -> RoiParams:
        return RoiParams(
            saturation=None if self.sat_auto.isChecked() else (self.sat.value() or None),
            smooth_um=self.smooth.value(),
            min_cell_um2=self.min_cell.value(),
            max_cell_um2=self.max_cell.value(),
            min_nucleus_um2=self.min_nuc.value(),
            max_nucleus_um2=self.max_nuc.value(),
            fit_size=self.fit_size.isChecked(),
            neck_cut=self.neck_cut.isChecked(),
            neck_max_um=self.neck_max.value(),
            edge_mode=self.edge_combo.currentData(),
            edge_margin_um=self.edge_margin.value(),
            nuc_threshold=self._thr_value('nuc'),
            cell_threshold=self._thr_value('cell'),
        )

    # ---- manual thresholds ----------------------------------------------

    def _thr_value(self, key):
        t = self.thr[key]
        return None if t['auto'].isChecked() else t['spin'].value()

    def show_input(self) -> bool:
        """Whether the preview shows the detector's input instead of the composite."""
        if self.manual_mode():
            return self.win.tab_current('roi_tab') and self.man_view.isChecked()
        return self.input_view.isChecked() or self.thr_view.isChecked()

    # ---- manual (threshold only) mode -------------------------------------

    def manual_mode(self) -> bool:
        return self.mode_tabs.currentIndex() == 1

    def _mode_changed(self, _):
        if self.item is not None:
            self._man_fill(self.item)
        self.win.update_preview()

    def _man_fill(self, item):
        """A threshold never set (0) starts from Otsu of the image's channel; set
        ones are kept for every image, so a batch uses one threshold."""
        if not self.manual_mode():
            return
        bg, nuc = self._inputs(item)
        for key, plane in (('cell', bg), ('nuc', nuc)):
            if plane is not None and self._man_value(key) == 0:
                self._man_show(key, float(filters.threshold_otsu(plane)))

    def _man_value(self, key):
        return self.man[key]['spin'].value()

    def _man_show(self, key, value):
        t = self.man[key]
        t['spin'].blockSignals(True)
        t['spin'].setValue(value)
        t['spin'].blockSignals(False)
        self._man_sync_slider(key)

    def _man_sync_slider(self, key):
        t = self.man[key]
        lo, hi = t['range']
        t['slider'].blockSignals(True)
        t['slider'].setValue(int(round((t['spin'].value() - lo) / (hi - lo) * THR_STEPS)))
        t['slider'].blockSignals(False)

    def _man_spin(self, key):
        self._man_sync_slider(key)
        if self.show_input():
            self._preview_timer.start()

    def _man_slider(self, key, v):
        t = self.man[key]
        lo, hi = t['range']
        t['spin'].setValue(lo + (hi - lo) * v / THR_STEPS)

    def _man_preview(self, item) -> np.ndarray:
        """The composite with the areas at or above each manual threshold painted."""
        rgb = item.composite().copy()
        bg, nuc = self._inputs(item)
        masks = {'cell': bg >= self._man_value('cell')}
        if nuc is not None:
            masks['nuc'] = nuc >= self._man_value('nuc')
        for key, m in masks.items():
            if m.shape == rgb.shape[:2]:
                rgb[m] = rgb[m] * 0.55 + 0.45 * np.asarray(THR_COLORS[key], np.float32)
        return rgb

    def _thr_ranges(self, item):
        """Slider spans the current plane's value range of each role's channel."""
        r = self.roles(item)
        planes = item.planes()
        for key, ch in (('nuc', r['nuc']), ('cell', r['bg'])):
            t = self.thr[key]
            if ch is None:
                t['range'] = (0.0, 1.0)
            else:
                plane = planes[ch]
                lo, hi = float(np.nanmin(plane)), float(np.nanmax(plane))
                t['range'] = (lo, hi if hi > lo else lo + 1.0)
            self._thr_sync_slider(key)
            self.man[key]['range'] = t['range']
            self._man_sync_slider(key)
        has_nuc = r['nuc'] is not None
        for w in (self.man['nuc']['spin'], self.man['nuc']['slider']):
            w.setEnabled(has_nuc)
        self.thr['nuc']['auto'].setEnabled(has_nuc)
        if not has_nuc:
            self.thr['nuc']['auto'].setChecked(True)

    def _thr_sync_slider(self, key):
        t = self.thr[key]
        lo, hi = t['range']
        t['slider'].blockSignals(True)
        t['slider'].setValue(int(round((t['spin'].value() - lo) / (hi - lo) * THR_STEPS)))
        t['slider'].blockSignals(False)

    def _thr_show(self, key, value):
        """Show a value (e.g. the automatic one) without triggering an update."""
        if value is None:
            return
        t = self.thr[key]
        t['spin'].blockSignals(True)
        t['spin'].setValue(value)
        t['spin'].blockSignals(False)
        self._thr_sync_slider(key)

    def _thr_auto(self, key, auto_on):
        t = self.thr[key]
        on = not auto_on  # manual value
        if self.item is not None:  # the field holds the automatic value either way
            self._thr_show(key, self._auto_thresholds(self.item).get(key))
        t['spin'].setEnabled(on)
        t['slider'].setEnabled(on)
        if on and not self.thr_view.isChecked():
            self.thr_view.setChecked(True)  # updates the preview
        elif self.show_input():
            self.win.update_preview()

    def _thr_spin(self, key):
        self._thr_sync_slider(key)
        if not self.thr_view.isChecked():
            self.thr_view.setChecked(True)  # show what the threshold covers
        else:
            self._preview_timer.start()

    def _thr_slider(self, key, v):
        t = self.thr[key]
        lo, hi = t['range']
        t['spin'].setValue(lo + (hi - lo) * v / THR_STEPS)

    def _inputs(self, item):
        r = self.roles(item)
        planes = item.planes()
        return planes[r['bg']], (planes[r['nuc']] if r['nuc'] is not None else None)

    def _preview_data(self, item):
        """(ThresholdPreview, detector-input RGB) for the current plane, cached
        until the plane, the channel roles, saturation or smoothing change."""
        bg, nuc = self._inputs(item)
        key = (id(item), id(item.planes()), self.roles(item)['bg'], self.roles(item)['nuc'],
               self.sat_auto.isChecked() or self.sat.value(), self.smooth.value())
        if self._tp_cache is None or self._tp_cache[0] != key:
            p = self.params()
            tp = ThresholdPreview(bg, nuc, item.pixel_um, p)
            # hold the planes so their id is not reused while cached
            self._tp_cache = (key, tp, merged_preview(bg, nuc, tp.saturation), item.planes())
        return self._tp_cache[1], self._tp_cache[2]

    def _auto_thresholds(self, item) -> dict:
        """The Otsu thresholds the detector would pick now (raw channel values)."""
        tp = self._preview_data(item)[0]()
        return {'nuc': tp['nuc_threshold'], 'cell': tp['cell_threshold']}

    def roles(self, item=None):
        item = item or self.item
        if not item.roi_roles:
            item.roi_roles = guess_roles(item)
        return item.roi_roles

    # ---- image selection ---------------------------------------------------

    def bind(self, item: ImageItem | None):
        """Called by the main window when the current image changes."""
        self._busy = True
        self.nuc_combo.clear()
        self.bg_combo.clear()
        if item is not None:
            r = self.roles(item)
            self.nuc_combo.addItem('없음', None)
            for i, name in enumerate(item.channels):
                self.nuc_combo.addItem(f'C{i}: {name}', i)
                self.bg_combo.addItem(f'C{i}: {name}', i)
            self.nuc_combo.setCurrentIndex(max(0, self.nuc_combo.findData(r['nuc'])))
            self.bg_combo.setCurrentIndex(max(0, self.bg_combo.findData(r['bg'])))
            if not self.sat_auto.isChecked():
                pass
            elif item.cells is not None and item.cells.saturation:
                self._sat_show(item.cells.saturation)
            elif self.win.tab_open('roi_tab'):
                self.show_auto_values(item)
            self._thr_ranges(item)
            self._man_fill(item)
            if self.size_auto.isChecked():
                sizes = self._size_cache.get(self._size_key(item, r))
                if sizes is not None:
                    self._show_sizes(sizes)
            if item.cells is not None:
                for key in self.thr:
                    if self.thr[key]['auto'].isChecked():
                        self._thr_show(key, getattr(item.cells, f'{key}_threshold', None))
        self._busy = False
        self.selected = 0
        self.refresh_list()
        self.measure.bind(item)
        self.live_changed()

    def _roles_changed(self, _):
        if self._busy or self.item is None:
            return
        self.item.roi_roles = {'nuc': self.nuc_combo.currentData(), 'bg': self.bg_combo.currentData()}
        self._thr_ranges(self.item)
        self.show_auto_values(self.item)
        if self.show_input():
            self.win.update_preview()

    def _sat_show(self, value):
        """Show the saturation in use (automatic) without triggering an update."""
        if value is None:
            return
        self.sat.blockSignals(True)
        self.sat.setValue(value)
        self.sat.blockSignals(False)

    def _sat_auto_toggled(self, on):
        self.sat.setEnabled(not on)
        if self.item is not None:
            self.show_auto_values(self.item)
        if self.show_input():
            self.win.update_preview()

    def show_auto_values(self, item):
        """Fill the 자동 fields (saturation, thresholds) with the values the
        detection would use on this image now."""
        try:
            tp = self._preview_data(item)[0]
            if self.sat_auto.isChecked():
                self._sat_show(tp.saturation)
            got = tp(self._thr_value('nuc'), self._thr_value('cell'))
        except Exception:
            traceback.print_exc()
            return
        for key in self.thr:
            if self.thr[key]['auto'].isChecked():
                self._thr_show(key, got[f'{key}_threshold'])

    def _sat_changed(self, _):
        if self.show_input():
            self.win.update_preview()

    def preview_rgb(self, item: ImageItem) -> np.ndarray:
        """What the detector sees: the background channel with a bright LUT plus nuclei."""
        if self.manual_mode():
            return self._man_preview(item)
        prev, base = self._preview_data(item)
        rgb = base.copy()
        if self.thr_view.isChecked():
            tp = prev(self._thr_value('nuc'), self._thr_value('cell'))
            for key in ('cell', 'nuc'):
                m = tp[key]
                if m is not None:
                    rgb[m] = rgb[m] * 0.55 + 0.45 * np.asarray(THR_COLORS[key], np.float32)
                if self.thr[key]['auto'].isChecked():
                    self._thr_show(key, tp[f'{key}_threshold'])
        return rgb

    # ---- detection ------------------------------------------------------

    @staticmethod
    def _run_planes(planes, px_um, roles, p, manual, man_cell, man_nuc) -> CellRois:
        bg = planes[roles['bg']]
        nuc = planes[roles['nuc']] if roles['nuc'] is not None else None
        if manual:
            return threshold_cells(bg, nuc, px_um, man_cell,
                                   man_nuc if nuc is not None else None, p)
        return segment_cells(bg, nuc, px_um, p)

    def _run(self, item: ImageItem, roles: dict, p: RoiParams) -> CellRois:
        """Detect with the selected method (자동 / 수동 sub-tab)."""
        return self._run_planes(item.planes(), item.pixel_um, roles, p, self.manual_mode(),
                                self._man_value('cell'), self._man_value('nuc'))

    def _detect(self, item: ImageItem, roles: dict, sizes=None) -> CellRois:
        """sizes: (cell, nucleus) ranges to use; None = the fields, or this
        image's own range when 자동 is on."""
        t0 = time.perf_counter()
        live = self._live if sizes is None or self.size_auto.isChecked() else None
        if sizes is None and self.size_auto.isChecked():
            sizes = self._image_sizes(item, roles)
        self.last_sizes = sizes
        if (live is not None and item is self.item and roles == self.roles(item)
                and live[0] == self._live_key(item)):
            rois = copy.deepcopy(live[1])  # the preview shown is exactly this detection
        else:
            p = self.params() if sizes is None else self._sized(self.params(), sizes)
            rois = self._run(item, roles, p)
            rois.renumber()
        self.last_seconds = time.perf_counter() - t0
        return rois

    def detect_current(self):
        it = self.item
        if it is None:
            return
        if it.cells is not None and len(it.cells) and not self._confirm_replace():
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            it.cells = self._detect(it, self.roles())
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, '검출 실패', str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        self._live = None
        sz = ''
        if self.last_sizes is not None:
            self._show_sizes(self.last_sizes)
            sz = f', 크기 범위 자동: {self._sizes_text(self.last_sizes)}'
        if self.manual_mode():
            msg = (f'세포 {len(it.cells)}개 검출 (수동: 세포 ≥ {self._man_value("cell"):.4g}'
                   + (f', 핵 ≥ {self._man_value("nuc"):.4g}' if self.roles()['nuc'] is not None else '')
                   + f', {self.last_seconds:.1f}초{sz})')
            self.status(msg)
            self.selected = 0
            self.refresh_list()
            self.win.update_preview()
            return
        msg = f'세포 {len(it.cells)}개 검출 ({self.last_seconds:.1f}초)'
        if self.sat_auto.isChecked():
            self._sat_show(it.cells.saturation)
            msg += f' (배경 포화값 자동: {it.cells.saturation:.3g})'
        used = []
        for key in self.thr:
            v = getattr(it.cells, f'{key}_threshold', None)
            if v is not None:
                how = '자동' if self.thr[key]['auto'].isChecked() else '수동'
                used.append(f"{self.thr[key]['label']} {v:.4g} ({how})")
                if how == '자동':
                    self._thr_show(key, v)
        if used:
            msg += ', ' + ', '.join(used)
        msg += sz
        if self.roles()['nuc'] is not None and it.cells.nuclei is None:
            msg += '. 핵 채널에서 핵을 찾지 못해 핵 없이 나눴습니다.'
        self.status(msg)
        self.selected = 0
        self.refresh_list()
        self.win.update_preview()

    # ---- automatic size range -------------------------------------------

    def _size_slider(self, spin, v):
        if v >= SIZE_STEPS and spin.specialValueText():
            spin.setValue(0)  # right end of a maximum: no limit
        else:
            spin.setValue(round(10 ** (SIZE_LOG[0] + (SIZE_LOG[1] - SIZE_LOG[0]) * v / SIZE_STEPS), 1))

    def _size_sync(self, spin):
        sl = self._size_sliders.get(spin)
        if sl is None:
            return
        v = spin.value()
        if v <= 0:
            pos = SIZE_STEPS
        else:
            pos = (np.log10(v) - SIZE_LOG[0]) / (SIZE_LOG[1] - SIZE_LOG[0]) * SIZE_STEPS
        sl.blockSignals(True)
        sl.setValue(int(round(min(max(pos, 0), SIZE_STEPS))))
        sl.blockSignals(False)

    # ---- live preview -------------------------------------------------------

    def _live_key(self, item):
        r = self.roles(item)
        p = self.params()
        if self.size_auto.isChecked():  # the fields only show the range in use
            p = replace(p, min_cell_um2=-1, max_cell_um2=-1, min_nucleus_um2=-1, max_nucleus_um2=-1)
        return (id(item), id(item.planes()), r['bg'], r['nuc'], self.manual_mode(),
                self._man_value('cell'), self._man_value('nuc'), repr(p))

    def live_changed(self, *_):
        if self.live.isChecked() and self.item is not None and not self._busy:
            self._live_timer.start()

    def _live_toggled(self, on):
        if on:
            self._live_timer.start()
        else:
            self._live = None
            self._live_timer.stop()
            self.draw_overlay()

    def _live_start(self):
        it = self.item
        if it is None or not self.live.isChecked():
            return
        if self._live_busy:
            self._live_again = True
            return
        key = self._live_key(it)
        if self._live is not None and self._live[0] == key:
            return
        self._live_busy = True
        self._live_job += 1
        job, roles, p = self._live_job, dict(self.roles(it)), self.params()
        planes = it.planes()
        man = self.manual_mode(), self._man_value('cell'), self._man_value('nuc')
        skey = self._size_key(it, roles) if self.size_auto.isChecked() else None
        cache = self._size_cache

        def work():
            t0 = time.perf_counter()
            try:
                pp = p
                if skey is not None:
                    if skey not in cache:
                        cache[skey] = self._estimate_planes(planes, it.pixel_um, roles, p, man)
                    pp = self._sized(p, cache[skey])
                res = self._run_planes(planes, it.pixel_um, roles, pp, *man)
                res.renumber()
            except Exception as exc:
                traceback.print_exc()
                res = str(exc)
            self.liveDone.emit(job, (key, res), time.perf_counter() - t0)

        threading.Thread(target=work, daemon=True).start()

    def _live_finished(self, job, result, secs):
        self._live_busy = False
        key, res = result
        if self.live.isChecked() and self.item is not None and job == self._live_job:
            if isinstance(res, str):
                self.win.statusBar().showMessage(f'미리보기 실패: {res}', 5000)
            elif key == self._live_key(self.item):
                self._live = (key, res)
                if self.size_auto.isChecked():
                    sizes = self._size_cache.get(self._size_key(self.item, self.roles()))
                    if sizes is not None:
                        self._show_sizes(sizes)
                self.win.statusBar().showMessage(
                    f'미리보기: 세포 {len(res)}개 ({secs:.1f}초). ROI 검출을 누르면 이 결과를 씁니다.', 8000)
                self.draw_overlay()
        if self._live_again:
            self._live_again = False
            self._live_timer.start()

    def _size_auto_toggled(self, on):
        for w in (self.min_cell, self.max_cell, self.min_nuc, self.max_nuc):
            w.setEnabled(not on)
            self._size_sliders[w].setEnabled(not on)
        if on and self.item is not None:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                self._show_sizes(self._image_sizes(self.item, self.roles()))
            finally:
                QApplication.restoreOverrideCursor()

    def _jobs(self, src):
        """(image, roles) for every image with channels matching src's roles."""
        r = self.roles(src)
        jobs = []
        for it in self.win.items:
            bg = match_channel(it, src.channels[r['bg']], r['bg'], like=src)
            nuc = None
            if r['nuc'] is not None:
                nuc = match_channel(it, src.channels[r['nuc']], r['nuc'], like=src)
                if nuc is None:
                    continue
            if bg is not None:
                jobs.append((it, {'nuc': nuc, 'bg': bg}))
        return jobs

    # ---- size range per image ---------------------------------------------

    def _size_key(self, item, roles):
        """What an image's automatic size range depends on."""
        p = self.params()
        return (id(item), id(item.planes()), item.z, item.image.t, roles['bg'], roles['nuc'],
                self.manual_mode(), self._man_value('cell'), self._man_value('nuc'),
                p.saturation, p.smooth_um, p.nuc_threshold, p.cell_threshold)

    @classmethod
    def _estimate_planes(cls, planes, px_um, roles, p, man):
        """(cell range, nucleus range) in µm² for one image: a detection
        without size limits (cells on the frame left out), then image_size_range."""
        pe = replace(p, min_cell_um2=10.0, max_cell_um2=0.0, min_nucleus_um2=2.0,
                     max_nucleus_um2=0.0, fit_size=False, edge_mode='exclude')
        rois = cls._run_planes(planes, px_um, roles, pe, *man)
        px2 = (rois.px_um or 0.1) ** 2
        out = []
        # nuclei are the seeds of the cells: a small (partial, dim) nucleus
        # dropped hands its cell to a neighbour, so their minimum stays low
        for lab, below in ((rois.labels, 4.0), (rois.nuclei, 20.0)):
            if lab is None:
                out.append(None)
                continue
            a = np.bincount(np.asarray(lab).ravel())[1:]
            out.append(image_size_range(a[a > 0] * px2, below=below))
        return tuple(out)

    def _image_sizes(self, item, roles):
        key = self._size_key(item, roles)
        if key not in self._size_cache:
            man = self.manual_mode(), self._man_value('cell'), self._man_value('nuc')
            self._size_cache[key] = self._estimate_planes(
                item.planes(), item.pixel_um, roles, self.params(), man)
        return self._size_cache[key]

    @staticmethod
    def _sized(p, sizes):
        """p with the size ranges of one image (None: keep p's)."""
        cell, nuc = sizes
        if cell is not None:
            p = replace(p, min_cell_um2=cell[0], max_cell_um2=cell[1])
        if nuc is not None:
            p = replace(p, min_nucleus_um2=nuc[0], max_nucleus_um2=nuc[1])
        return p

    def _show_sizes(self, sizes):
        """Show the range in use (automatic) in the fields."""
        for (lo_w, hi_w), rng in zip(((self.min_cell, self.max_cell), (self.min_nuc, self.max_nuc)),
                                     sizes):
            if rng is not None:
                lo_w.setValue(max(1.0, np.floor(rng[0] * 10) / 10))
                hi_w.setValue(np.ceil(rng[1] * 10) / 10)

    def _sizes_text(self, sizes):
        names = ('세포', '핵')
        return ', '.join(f'{n} {r[0]:.0f}–{r[1]:.0f} µm²' for n, r in zip(names, sizes) if r is not None)

    def _confirm_replace(self):
        r = QMessageBox.question(self, 'ROI 다시 검출', '이 이미지의 ROI(수정 포함)를 새로 검출한 결과로 바꿀까요?')
        return r == QMessageBox.StandardButton.Yes

    def detect_all(self):
        src = self.item
        if src is None:
            return
        jobs = self._jobs(src)
        edited = [it for it, _ in jobs if it.cells is not None and it is not src]
        if edited:
            q = QMessageBox.question(
                self, 'ROI 다시 검출',
                f'ROI가 이미 있는 이미지 {len(edited)}개도 새로 검출할까요?\n'
                '아니오: ROI가 없는 이미지만 검출합니다.',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel)
            if q == QMessageBox.StandardButton.Cancel:
                return
            if q == QMessageBox.StandardButton.No:
                jobs = [(it, ro) for it, ro in jobs if it.cells is None]
        sizes = None  # None: the fields (자동: each image's own range)
        if not self.size_auto.isChecked() and len(jobs) > 1:
            fixed = ((self.min_cell.value(), self.max_cell.value()),
                     (self.min_nuc.value(), self.max_nuc.value()))

            def txt(r):
                return f"{r[0]:g}–{r[1]:g} µm²" if r[1] else f"{r[0]:g} µm² 이상"
            q = QMessageBox.question(
                self, '크기 범위',
                f'모든 이미지에 같은 크기 범위를 적용할까요?\n'
                f'세포 {txt(fixed[0])}, 핵 {txt(fixed[1])}\n\n'
                '아니오: 이미지마다 크기 범위를 자동으로 추정해 씁니다.',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel)
            if q == QMessageBox.StandardButton.Cancel:
                return
            per_image = q == QMessageBox.StandardButton.No
        else:
            per_image = self.size_auto.isChecked()
        prog = QProgressDialog('ROI 검출 중…', '취소', 0, len(jobs), self.win)
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        errors, n, secs, ranges = [], 0, 0.0, []
        for i, (it, roles) in enumerate(jobs):
            if prog.wasCanceled():
                break
            prog.setLabelText(f'ROI 검출 중: {it.label}')
            prog.setValue(i)
            QApplication.processEvents()
            try:
                it.roi_roles = roles
                if per_image:
                    prog.setLabelText(f'크기 범위 추정 · ROI 검출 중: {it.label}')
                    QApplication.processEvents()
                    sizes = self._image_sizes(it, roles)
                it.cells = self._detect(it, roles, sizes)
                if per_image:
                    ranges.append(f'{it.label}: {self._sizes_text(sizes)}')
                secs += self.last_seconds
                n += 1
            except Exception as exc:
                errors.append(f'{it.label}: {exc}')
                traceback.print_exc()
        prog.setValue(len(jobs))
        skipped = len(self.win.items) - len(jobs)
        msg = f'이미지 {n}개에서 ROI를 검출했습니다' + (
            f' (이미지당 평균 {secs / n:.1f}초).' if n else '.')
        if skipped:
            msg += f' (역할에 맞는 채널이 없거나 건너뛴 이미지 {skipped}개)'
        if ranges:
            msg += ' 이미지별 크기 범위: ' + '; '.join(ranges)
            if src.cells is not None and per_image:
                self._show_sizes(self._image_sizes(src, self.roles(src)))
        self.status(msg)
        if errors:
            QMessageBox.warning(self, '검출 실패', '\n'.join(errors))
        self.selected = 0
        self.refresh_list()
        self.win.update_preview()

    # ---- list / overlay ---------------------------------------------------

    def refresh_list(self):
        self.cell_list.blockSignals(True)
        self.cell_list.clear()
        c = self.cells
        if c is not None:
            px = c.px_um
            for l in c.ids():
                area = int((c.labels == l).sum())
                a = f'{area * px ** 2:.0f} µm²' if px else f'{area} px'
                st = STATUS_KO.get(c.status.get(l, 'ok'), '')
                e = QListWidgetItem(f'cell{l:03d}   {a}' + (f'   ({st})' if st else ''))
                e.setData(Qt.ItemDataRole.UserRole, l)
                self.cell_list.addItem(e)
                if l == self.selected:
                    self.cell_list.setCurrentItem(e)
        self.cell_list.blockSignals(False)

    def _list_selected(self, row):
        e = self.cell_list.item(row)
        self.selected = e.data(Qt.ItemDataRole.UserRole) if e is not None else 0
        self.draw_overlay()

    def select(self, label):
        self.selected = label
        for i in range(self.cell_list.count()):
            if self.cell_list.item(i).data(Qt.ItemDataRole.UserRole) == label:
                self.cell_list.blockSignals(True)
                self.cell_list.setCurrentRow(i)
                self.cell_list.blockSignals(False)
                break
        else:
            self.cell_list.clearSelection()
        self.draw_overlay()

    def regions_for(self, item):
        return make_regions([k for k, b in self.reg_boxes.items() if b.isChecked()], [])

    def draw_overlay(self, hidden=False):
        c = self.cells
        changed = getattr(self.win, 'rois_changed', None)
        if changed is not None:  # measurements and particles follow every ROI edit
            changed(hidden)
        self._hover = {}
        self.win.canvas.hide_hover()
        live = (self._live is not None and self.live.isChecked() and self.item is not None
                and self._live[0][0] == id(self.item))
        if live:  # the live preview replaces the ROIs while it is on
            c = self._live[1]
        self._hover_rois = c
        if hidden or c is None or not self.show_rois.isChecked():
            self.win.canvas.show_cells([], 0)
            return
        shapes = []
        n = int(c.labels.max()) + 1
        cell_px = np.bincount(c.labels.ravel(), minlength=n)
        nuc_px = (np.bincount(c.labels[c.nuclei == c.labels].ravel(), minlength=n)
                  if c.nuclei is not None else np.zeros(n, int))
        for l in c.ids():
            xy = c.contour(l)
            if xy is None:
                continue
            nxy = c.nucleus_contour(l) if self.show_nuc.isChecked() else None
            shapes.append((l, xy, nxy, 'preview' if live else c.status.get(l, 'ok'),
                           c.centroid(l)))
            lines = [f'cell{l:03d}   {self._area_text(cell_px[l], c.px_um)}']
            if nuc_px[l]:
                lines += [f'nuc{l:03d}   {self._area_text(nuc_px[l], c.px_um)}',
                          f'cyto{l:03d}   {self._area_text(cell_px[l] - nuc_px[l], c.px_um)}']
            top = (float((xy[:, 0].min() + xy[:, 0].max()) / 2), float(xy[:, 1].min()))
            self._hover[l] = ('\n'.join(lines), top)
        self.win.canvas.show_cells(shapes, 0 if live else self.selected)

    @staticmethod
    def _area_text(px, px_um):
        return f'{px * px_um ** 2:.1f} µm²' if px_um else f'{int(px)} px'

    def hover_info(self, x, y):
        """Name and area of the cell ROI under (x, y), shown above it."""
        c = self._hover_rois
        if c is None or not self._hover:
            return None
        return self._hover.get(c.label_at(x, y))

    # ---- editing ----------------------------------------------------------

    def set_tool(self, tool):
        self.win.canvas.set_roi_tool(tool)
        if tool != 'select' and self.cells is None:
            self.status('먼저 ROI를 검출하거나 불러오세요. (새 세포는 바로 그릴 수 있습니다)')

    def _escape(self):
        self.tool_btns['select'].setChecked(True)
        self.select(0)

    def _canvas_click(self, x, y):
        c = self.cells
        if c is None:
            return
        self.select(c.label_at(x, y))

    def _ensure_cells(self):
        it = self.item
        if it is None:
            return None
        if it.cells is None:
            h, w = it.image.shape[-2:]
            it.cells = CellRois(np.zeros((h, w), np.int32), None, it.pixel_um)
        return it.cells

    def _lasso(self, tool, pts):
        c = self._ensure_cells()
        if c is None:
            return
        if tool == 'cut':
            new = c.cut(pts, self.selected or None)
            if not new:
                self.status('자를 세포가 없습니다. 선이 세포를 완전히 가로지르도록 그려주세요.')
            else:
                self.status(f'세포를 잘라 {", ".join(f"cell{l:03d}" for l in new)}을(를) 새로 만들었습니다.')
            self.refresh_list()
            self.draw_overlay()
            return
        mask = c.polygon_mask(pts)
        if not mask.any():
            return
        if tool == 'new':
            l = c.new_cell(mask)
            if not l:
                self.status('그린 영역이 모두 다른 세포 안에 있습니다.')
                return
            self.selected = l
            self.status(f'cell{l:03d} 추가' + self._find_nucleus(c, l))
        elif tool == 'add':
            l = self.selected
            if not l:
                ov = c.labels[mask]
                ov = ov[ov > 0]
                l = int(np.bincount(ov).argmax()) if len(ov) else 0
            if not l:
                l = c.new_cell(mask)
                if not l:
                    self.status('그린 영역이 모두 다른 세포 안에 있습니다.')
                    return
                self.selected = l
                self.status(f'선택한 세포가 없어 cell{l:03d}로 새로 추가했습니다'
                            + self._find_nucleus(c, l))
            else:
                before = int((c.labels == l).sum())
                c.add(l, mask)
                self.selected = l
                after = int((c.labels == l).sum())
                if after <= before:
                    self.status(f'cell{l:03d}: 세포와 이어지지 않은 영역은 더할 수 없습니다.')
                else:
                    self.status(f'cell{l:03d}에 {after - before} px 더함')
        elif tool == 'sub':
            l = self.selected or None
            before = int((c.labels > 0).sum())
            c.subtract(l, mask)
            if l and l not in c.ids():
                self.selected = 0
                self.status(f'cell{l:03d}이(가) 모두 지워졌습니다.')
            elif int((c.labels > 0).sum()) == before:
                c.undo()
                c._redo.clear()
                self.status('세포 안쪽에 구멍은 만들 수 없습니다 (ImageJ 다각형 ROI). '
                            '세포 경계에 걸치도록 그려주세요.')
            else:
                self.status(f'cell{l:03d}에서 뺌' if l else '그린 영역을 모든 세포에서 뺌')
        self.refresh_list()
        self.draw_overlay()

    def _find_nucleus(self, c: CellRois, l: int) -> str:
        """Detect the nucleus inside a newly drawn cell; returns a status note."""
        it = self.item
        ch = self.roles(it)['nuc']
        if ch is None:
            return ''
        thr = self._thr_value('nuc')
        if thr is None:
            thr = c.nuc_threshold
        if thr is None:
            thr = self._auto_thresholds(it)['nuc']
        try:
            found = c.find_nucleus(l, it.planes()[ch], thr, self.min_nuc.value())
        except Exception:
            traceback.print_exc()
            found = False
        return ', 핵 자동 검출' if found else ', 핵을 찾지 못함'

    def delete_selected(self):
        c, l = self.cells, self.selected
        if c is None or not l:
            return
        c.delete(l)
        self.selected = 0
        self.status(f'cell{l:03d} 삭제')
        self.refresh_list()
        self.draw_overlay()

    def undo(self):
        if self.cells is not None and self.cells.undo():
            self.refresh_list()
            self.draw_overlay()
            self.status('되돌림')

    def redo(self):
        if self.cells is not None and self.cells.redo():
            self.refresh_list()
            self.draw_overlay()
            self.status('다시 실행')

    def renumber(self):
        if self.cells is not None:
            self.cells._push()
            self.cells.renumber()
            self.selected = 0
            self.refresh_list()
            self.draw_overlay()

    # ---- files ----------------------------------------------------------

    def _save_kwargs(self, item):
        return dict(cells=self.save_cell.isChecked(), nuclei=self.save_nuc.isChecked(),
                    cytosol=self.save_cyto.isChecked(), properties=item.id_properties())

    def _stem(self, item):
        return item_stem(item)

    def save_item(self, it, folder, stem=None) -> list[dict]:
        """Write <stem>_RoiSet.zip into folder; returns the measurement rows."""
        stem = stem or self._stem(it)
        it.cells.save(Path(folder) / f'{stem}_RoiSet.zip', **self._save_kwargs(it))
        return [{'image': it.label, 'image_id': it.image_id, **r}
                for r in it.cells.measurements()]

    def save_current(self):
        it = self.item
        if it is None or it.cells is None or not len(it.cells):
            QMessageBox.information(self, 'ROI 저장', '저장할 ROI가 없습니다.')
            return
        default = str(it.path.with_name(f'{self._stem(it)}_RoiSet.zip'))
        path, flt = QFileDialog.getSaveFileName(
            self, 'ROI 저장', default,
            'ImageJ RoiSet (*.zip);;ROI마다 .roi 파일 (*.roi)')
        if not path:
            return
        if '.roi' in flt and not path.lower().endswith('.roi'):
            path = str(Path(path).with_suffix('.roi'))
        try:
            files = it.cells.save(path, **self._save_kwargs(it))
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, '저장 실패', str(exc))
            return
        self.status(f'ROI 파일 {len(files)}개 저장: {Path(files[0]).parent}')

    def load_current(self):
        it = self.item
        if it is None:
            return
        files, _ = QFileDialog.getOpenFileNames(
            self, 'ROI 불러오기', str(it.path.parent), 'ImageJ ROI (*.zip *.roi)')
        if not files:
            return
        other = {i for i in map(roi_id, files) if i and i != it.image_id}
        if other:
            r = QMessageBox.question(
                self, 'ROI 불러오기',
                f'이 ROI는 다른 이미지(ID {", ".join(sorted(other))})에서 저장된 것입니다.\n'
                f'현재 이미지 ID: {it.image_id}\n그래도 불러올까요?')
            if r != QMessageBox.StandardButton.Yes:
                return
        if it.cells is not None and len(it.cells) and not self._confirm_load():
            return
        try:
            self.load_into(it, files)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, '불러오기 실패', str(exc))
            return
        self.status(f'세포 ROI {len(it.cells)}개 불러옴')

    def load_into(self, it: ImageItem, files):
        """Replace an image's cell ROIs with the ones in files."""
        h, w = it.image.shape[-2:]
        it.cells = CellRois.load(files, (h, w), it.pixel_um)
        if it is self.item:
            self.selected = 0
            self.refresh_list()
            self.win.update_preview()

    def _confirm_load(self):
        r = QMessageBox.question(self, 'ROI 불러오기', '현재 ROI를 불러온 ROI로 바꿀까요?')
        return r == QMessageBox.StandardButton.Yes

    def save_all(self):
        items = [it for it in self.win.items if it.cells is not None and len(it.cells)]
        if not items:
            QMessageBox.information(self, 'ROI 저장', '저장할 ROI가 없습니다.')
            return
        out = QFileDialog.getExistingDirectory(self, 'ROI를 저장할 폴더')
        if not out:
            return
        per_image = self.per_image.isChecked()
        rows, errors = [], []
        stems = unique_stems(items)
        for it in items:
            folder = Path(out) / item_folder(it) if per_image else Path(out)
            stem = None if per_image else stems[id(it)]
            try:
                folder.mkdir(parents=True, exist_ok=True)
                item_rows = self.save_item(it, folder, stem)
                if per_image:
                    write_csv(folder / f'{self._stem(it)}_cell_rois.csv', item_rows)
                rows += item_rows
            except Exception as exc:
                errors.append(f'{it.label}: {exc}')
        write_csv(Path(out) / 'cell_rois.csv', rows)
        msg = f'이미지 {len(items) - len(errors)}개의 ROI와 cell_rois.csv를 저장했습니다.\n{out}'
        if errors:
            msg += '\n\n실패:\n' + '\n'.join(errors)
        QMessageBox.information(self, '저장 완료', msg)


def write_csv(path, rows):
    if not rows:
        return
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
