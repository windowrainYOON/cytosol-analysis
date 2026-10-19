"""Intensity tab: ImageJ Measure values of every cell's cell / nucleus / cytosol
/ particle region and of set expressions over them (cytosol.intensity). The
current image's table follows the ROIs, plane and particle settings as they
change; a button runs the same on every image, and both can be saved."""

from __future__ import annotations

import traceback
import zlib
from dataclasses import astuple, replace
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
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
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QRadioButton,
    QSlider,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .intensity import (
    STATS,
    ExpressionError,
    ParticleSettings,
    bit_depth,
    detect_particles,
    load_particles,
    make_regions,
    measure_cells,
    overlay_image,
    parse_region,
    region_names,
    save_particles,
    trace_outlines,
    write_rows,
)
from .lut import item_folder, item_stem

THR_STEPS = 1000
BASE = [('cell', '세포 전체'), ('nuc', '핵'), ('cyto', '세포질'), ('particle', '입자')]
WITHIN = [('cyto', '세포질 (핵 제외)'), ('cell', '세포 전체')]
EXPR_HELP = ('세미콜론(;)으로 여러 식을 나눕니다. 이름: cell(세포), nuc(핵), cyto(세포질), '
             'particle(입자). 연산: & 교집합, | 합집합, - 빼기, 괄호. '
             '예: cyto - particle;  cell & particle;  (cell - nuc) | particle')


class IntensityPanel(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.item = None
        self._busy = False
        self._sig = None
        self._hidden = False
        self.batch_rows: list[dict] = []
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)  # coalesce ROI edits and slider drags
        self._timer.timeout.connect(self.refresh)
        lay = QVBoxLayout(self)

        help_ = QLabel('세포질 ROI 탭의 세포마다 세포 전체·핵·세포질(과 입자) 영역의 채널별 강도를 '
                       '원본값으로 잽니다 (ImageJ Measure와 같은 값). 현재 Z(또는 MIP)와 시점의 값이며, '
                       'ROI를 그리거나 고치면 바로 갱신됩니다.')
        help_.setWordWrap(True)
        help_.setStyleSheet('color: gray; font-size: 11px;')
        lay.addWidget(help_)

        # regions
        reg = QGroupBox('측정할 영역')
        rl = QVBoxLayout(reg)
        row = QHBoxLayout()
        self.base_boxes = {}
        for key, text in BASE:
            b = QCheckBox(text)
            b.setChecked(True)
            b.toggled.connect(self.schedule)
            self.base_boxes[key] = b
            row.addWidget(b)
        row.addStretch()
        rl.addLayout(row)
        self.minus_particle = QCheckBox('입자를 뺀 영역 (세포질 − 입자 또는 세포 − 입자)')
        self.minus_particle.setChecked(True)
        self.minus_particle.setToolTip('입자를 찾은 영역(입자 ROI의 범위)에서 입자를 뺀 나머지')
        self.minus_particle.toggled.connect(self.schedule)
        rl.addWidget(self.minus_particle)
        rl.addWidget(QLabel('논리식 영역'))
        self.expr = QLineEdit()
        self.expr.setPlaceholderText('예: cyto - particle; cell & particle')
        self.expr.setToolTip(EXPR_HELP)
        self.expr.textChanged.connect(self.schedule)
        rl.addWidget(self.expr)
        self.expr_info = QLabel(EXPR_HELP)
        self.expr_info.setWordWrap(True)
        self.expr_info.setStyleSheet('color: gray; font-size: 11px;')
        rl.addWidget(self.expr_info)
        lay.addWidget(reg)

        # values
        val = QGroupBox('측정값 (채널마다)')
        vl = QVBoxLayout(val)
        row = QHBoxLayout()
        self.stat_boxes = {}
        for k in STATS:
            b = QCheckBox(k)
            b.setChecked(k == 'Mean')
            b.toggled.connect(self.schedule)
            self.stat_boxes[k] = b
            row.addWidget(b)
        row.addStretch()
        vl.addLayout(row)
        self.only_visible = QCheckBox('LUT에서 숨긴 채널 제외')
        self.only_visible.toggled.connect(self.schedule)
        vl.addWidget(self.only_visible)
        lay.addWidget(val)

        # particles
        part = QGroupBox('입자 ROI')
        pl = QFormLayout(part)
        self.part_on = QCheckBox('이 이미지에서 입자 ROI 정의')
        self.part_on.setToolTip('세포마다 아래 채널에서 threshold 이상인 픽셀을 입자로 봅니다 '
                                '(8방향으로 이어진 픽셀이 한 입자).')
        pl.addRow(self.part_on)
        self.part_channel = QComboBox()
        pl.addRow('채널', self.part_channel)
        self.within = QComboBox()
        for key, text in WITHIN:
            self.within.addItem(text, key)
        pl.addRow('찾을 영역', self.within)
        self.thr_auto = QRadioButton('자동 (세포마다 Otsu)')
        self.thr_auto.setToolTip('ImageJ에서 세포 ROI를 선택하고 setAutoThreshold("Otsu dark")를 '
                                 '실행한 것과 같은 값을 세포마다 따로 구합니다.')
        self.thr_manual = QRadioButton('수동')
        self.thr_auto.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.thr_auto)
        grp.addButton(self.thr_manual)
        row = QHBoxLayout()
        row.addWidget(self.thr_auto)
        row.addWidget(self.thr_manual)
        row.addStretch()
        pl.addRow('Threshold', row)
        self.thr_spin = QDoubleSpinBox()
        self.thr_spin.setRange(-1e9, 1e9)
        self.thr_spin.setDecimals(2)
        self.thr_slider = QSlider(Qt.Orientation.Horizontal)
        self.thr_slider.setRange(0, THR_STEPS)
        self._thr_range = (0.0, 1.0)
        pl.addRow('수동 값', self.thr_spin)
        pl.addRow('', self.thr_slider)
        self.min_px = QSpinBox()
        self.min_px.setRange(1, 1000000)
        self.min_px.setSuffix(' px')
        self.min_px.setToolTip('이보다 작은 입자는 버립니다 (ImageJ Analyze Particles의 최소 크기).')
        pl.addRow('최소 입자 크기', self.min_px)
        self.show_particles = QCheckBox('이미지에 입자 경계 표시 (자홍색)')
        self.show_particles.setChecked(True)
        self.show_particles.toggled.connect(lambda _: self._draw_particles())
        pl.addRow(self.show_particles)
        self.part_info = QLabel()
        self.part_info.setWordWrap(True)
        self.part_info.setStyleSheet('color: gray; font-size: 11px;')
        pl.addRow(self.part_info)
        row = QHBoxLayout()
        b = QPushButton('이 설정을 모든 이미지에 적용')
        b.setToolTip('같은 이름의 채널에서, 같은 방법으로 모든 이미지의 세포마다 입자를 찾습니다.')
        b.clicked.connect(self.apply_to_all)
        row.addWidget(b)
        pl.addRow(row)
        row = QHBoxLayout()
        b = QPushButton('입자 ROI 저장…')
        b.clicked.connect(self.save_particles_current)
        row.addWidget(b)
        b = QPushButton('입자 ROI 불러오기…')
        b.clicked.connect(self.load_particles_current)
        row.addWidget(b)
        pl.addRow(row)
        for w in (self.part_on, self.thr_auto, self.thr_manual):
            w.toggled.connect(self._particle_changed)
        self.part_channel.currentIndexChanged.connect(self._particle_channel_changed)
        self.within.currentIndexChanged.connect(self._particle_changed)
        self.min_px.valueChanged.connect(self._particle_changed)
        self.thr_spin.valueChanged.connect(self._thr_spin_changed)
        self.thr_slider.valueChanged.connect(self._thr_slider_changed)
        self.thr_manual.toggled.connect(self._manual_toggled)
        lay.addWidget(part)

        # results
        res = QGroupBox('결과')
        tl = QVBoxLayout(res)
        row = QHBoxLayout()
        self.view = QComboBox()
        self.view.addItem('현재 이미지', 'current')
        self.view.addItem('모든 이미지 (일괄 측정 결과)', 'batch')
        self.view.currentIndexChanged.connect(lambda _: self._fill_table())
        row.addWidget(self.view, 1)
        self.auto = QCheckBox('자동 갱신')
        self.auto.setChecked(True)
        self.auto.setToolTip('ROI·Z·시점·설정이 바뀔 때마다 현재 이미지 결과를 다시 계산합니다.')
        self.auto.toggled.connect(lambda on: on and self.schedule())
        row.addWidget(self.auto)
        tl.addLayout(row)
        self.table = QTableWidget(0, 0)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(220)
        self.table.itemSelectionChanged.connect(self._row_selected)
        tl.addWidget(self.table, 1)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setStyleSheet('color: gray; font-size: 11px;')
        tl.addWidget(self.info)
        row = QHBoxLayout()
        b = QPushButton('지금 측정 (현재 이미지)')
        b.clicked.connect(lambda: self.refresh(force=True))
        row.addWidget(b, 1)
        b = QPushButton('모든 이미지 측정')
        b.setToolTip('ROI가 있는 모든 이미지에서 같은 영역·측정값으로 잽니다 '
                     '(입자는 각 이미지의 입자 설정대로).')
        b.clicked.connect(self.measure_all)
        row.addWidget(b, 1)
        tl.addLayout(row)
        self.all_t = QCheckBox('일괄 측정에 모든 시점 포함')
        tl.addWidget(self.all_t)
        lay.addWidget(res, 1)

        # save
        io = QGroupBox('저장')
        il = QVBoxLayout(io)
        row = QHBoxLayout()
        b = QPushButton('CSV 저장 (현재 이미지)…')
        b.clicked.connect(self.save_current)
        row.addWidget(b)
        b = QPushButton('모든 이미지 측정 + 저장 (폴더)…')
        b.setToolTip('모든 이미지를 다시 잰 뒤 전체 결과 intensity.csv와, 이미지마다 '
                     '<이름>_<ID> 폴더에 그 이미지의 CSV를 저장합니다.')
        b.clicked.connect(self.save_all)
        row.addWidget(b)
        il.addLayout(row)
        self.with_roi = QCheckBox('ROI(.zip)와 ROI가 그려진 이미지(.png)도 함께 저장')
        self.with_roi.setChecked(True)
        self.with_roi.setToolTip('<이름>_RoiSet.zip (세포·핵·세포질), <이름>_particles.zip (입자), '
                                 '<이름>_image.png (현재 LUT 이미지 위에 ROI 경계)')
        il.addWidget(self.with_roi)
        lay.addWidget(io)

    # ---- helpers ----------------------------------------------------------

    def status(self, msg):
        self.win.statusBar().showMessage(msg)

    def schedule(self, *_):
        self._timer.start()

    def visible_tab(self) -> bool:
        tabs = getattr(self.win, 'right_tabs', None)
        return tabs is not None and tabs.currentIndex() == getattr(self.win, 'intensity_tab', -1)

    def overlay_changed(self, hidden=False):
        """Called whenever the ROI overlay is redrawn (edits, plane changes)."""
        self._hidden = hidden
        if self.auto.isChecked():
            self.schedule()
        self._draw_particles()

    def stats(self) -> tuple:
        return tuple(k for k in STATS if self.stat_boxes[k].isChecked()) or ('Mean',)

    def expressions(self) -> tuple[list[str], list[str]]:
        """(valid expressions, error messages)."""
        ok, bad = [], []
        for e in self.expr.text().split(';'):
            e = e.strip()
            if not e:
                continue
            try:
                parse_region(e)
                ok.append(e)
            except ExpressionError as exc:
                bad.append(f'“{e}”: {exc}')
        return ok, bad

    def regions_for(self, item):
        """Regions to measure on an image; ones using particles only when it has them."""
        base = [k for k, _ in BASE if self.base_boxes[k].isChecked()]
        exprs, _ = self.expressions()
        s = item.particle_settings
        if self.minus_particle.isChecked():
            within = s.within if s is not None else self.within.currentData()
            exprs = [f'{within} - particle'] + exprs
        regions = make_regions(base, exprs)
        if item.particles is None and item.particle_settings is None:
            regions = [r for r in regions if 'particle' not in region_names(r.tree)]
        return regions

    def channels_for(self, item) -> list[int]:
        idx = list(range(len(item.channels)))
        if self.only_visible.isChecked():
            idx = [i for i in idx if i >= len(item.luts) or item.luts[i].visible]
        return idx

    # ---- particles ----------------------------------------------------------

    def settings(self) -> ParticleSettings:
        name = self.part_channel.currentText().split(': ', 1)[-1]
        return ParticleSettings(
            channel=name, index=max(self.part_channel.currentData() or 0, 0),
            within=self.within.currentData(),
            method='manual' if self.thr_manual.isChecked() else 'otsu',
            manual=self.thr_spin.value(), min_px=self.min_px.value())

    def particles_for(self, item):
        """Particles of an image's current plane: from its settings, or as loaded."""
        s = item.particle_settings
        cells = item.cells
        if s is None:
            return item.particles
        if cells is None or not len(cells):
            return None
        c = s.channel_for(item)
        if c is None:
            return None
        key = (item.z, item.t, astuple(s), self._cells_key(cells))
        p = item.particles
        if p is not None and p.plane_key == key:
            return p
        p = detect_particles(cells, item.planes()[c], s, bit_depth(item, c))
        p.channel, p.plane_key = c, key
        item.particles = p
        return p

    def _particle_channel_changed(self, _):
        if self._busy:
            return
        self._sync_range()
        self._particle_changed()

    def _particle_changed(self, *_):
        if self._busy or self.item is None:
            return
        it = self.item
        if self.part_on.isChecked():
            it.particle_settings = self.settings()
        elif it.particle_settings is not None or it.particles is not None:
            it.particle_settings = None
            it.particles = None
        self.schedule()

    def _manual_toggled(self, on):
        for w in (self.thr_spin, self.thr_slider):
            w.setEnabled(on)
        p = self.item.particles if self.item is not None else None
        if on and p is not None and p.thresholds and not self._busy:
            # start from the automatic values
            self._show_thr(float(np.median(list(p.thresholds.values()))))
            self._particle_changed()

    def _sync_range(self):
        it = self.item
        c = self.part_channel.currentData()
        if it is None or c is None or c < 0:
            return
        lo, hi, _ = it.value_range(c)
        self._thr_range = (lo, hi if hi > lo else lo + 1.0)
        self._show_thr(self.thr_spin.value())

    def _show_thr(self, value):
        lo, hi = self._thr_range
        for w in (self.thr_spin, self.thr_slider):
            w.blockSignals(True)
        self.thr_spin.setValue(value)
        self.thr_slider.setValue(int(round((value - lo) / (hi - lo) * THR_STEPS)))
        for w in (self.thr_spin, self.thr_slider):
            w.blockSignals(False)

    def _thr_spin_changed(self, v):
        self._show_thr(v)
        self._particle_changed()

    def _thr_slider_changed(self, v):
        lo, hi = self._thr_range
        self.thr_spin.setValue(lo + (hi - lo) * v / THR_STEPS)

    def apply_to_all(self):
        it = self.item
        if it is None:
            return
        s = self.settings()
        n = 0
        for other in self.win.items:
            if s.channel not in other.channels and s.index >= len(other.channels):
                continue
            other.particle_settings = replace(s)
            other.particles = None
            n += 1
        self._busy = True
        self.part_on.setChecked(True)
        self._busy = False
        self.status(f'입자 ROI 설정을 이미지 {n}개에 적용했습니다.')
        self.schedule()

    def save_particles_current(self):
        it = self.item
        p = self.particles_for(it) if it is not None else None
        if p is None or not p.mask.any():
            QMessageBox.information(self, '입자 ROI', '저장할 입자가 없습니다.')
            return
        default = str(it.path.with_name(f'{item_stem(it)}_particles.zip'))
        path, _ = QFileDialog.getSaveFileName(self, '입자 ROI 저장', default,
                                              'ImageJ RoiSet (*.zip)')
        if not path:
            return
        try:
            save_particles(path, it.cells, p, it.id_properties())
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, '저장 실패', str(exc))
            return
        self.status(f'입자 ROI 저장: {path}')

    def load_particles_current(self):
        it = self.item
        if it is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, '입자 ROI 불러오기', str(it.path.parent),
                                              'ImageJ RoiSet (*.zip)')
        if not path:
            return
        try:
            self.load_particles_into(it, path)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, '불러오기 실패', str(exc))
            return
        self.bind(it)

    def load_particles_into(self, it, path):
        """Particle ROIs from a file: the settings stored in them (so they
        follow later ROI edits), else the outlines as they are."""
        h, w = it.image.shape[-2:]
        p, s = load_particles(path, (h, w))
        if s is not None:
            it.particle_settings, it.particles = s, None
        else:
            it.particle_settings, it.particles = None, p

    def _draw_particles(self):
        canvas = self.win.canvas
        it = self.win.current
        p = it.particles if it is not None else None
        if (self._hidden or p is None or it.cells is None or not self.show_particles.isChecked()
                or self.win._stack_on()):
            canvas.show_particles([])
            return
        loops = getattr(p, '_outline', None)
        if loops is None:
            loops = trace_outlines(p.mask) if p.mask.any() else []
            p._outline = loops
        canvas.show_particles(loops)

    # ---- image selection ----------------------------------------------------

    def bind(self, item):
        self.item = item
        self._busy = True
        keep = self.part_channel.currentText().split(': ', 1)[-1]
        self.part_channel.clear()
        if item is not None:
            for i, name in enumerate(item.channels):
                self.part_channel.addItem(f'C{i}: {name}', i)
            s = item.particle_settings
            if s is not None:
                c = s.channel_for(item)
                self.part_channel.setCurrentIndex(c if c is not None else 0)
                self.within.setCurrentIndex(max(0, self.within.findData(s.within)))
                (self.thr_manual if s.method == 'manual' else self.thr_auto).setChecked(True)
                self.min_px.setValue(s.min_px)
            elif keep in item.channels:
                self.part_channel.setCurrentIndex(item.channels.index(keep))
            else:
                nuc = (item.roi_roles or {}).get('nuc')
                cand = [i for i in range(len(item.channels)) if i != nuc]
                self.part_channel.setCurrentIndex(cand[0] if cand else 0)
            self.part_on.setChecked(s is not None or item.particles is not None)
            self._sync_range()
            if s is not None:
                self._show_thr(s.manual)
        for w in (self.thr_spin, self.thr_slider):
            w.setEnabled(self.thr_manual.isChecked())
        self._busy = False
        self._sig = None
        self.refresh(force=True)

    # ---- measuring ------------------------------------------------------------

    @staticmethod
    def _cells_key(cells):
        nuc = cells.nuclei
        return (id(cells), zlib.crc32(np.ascontiguousarray(cells.labels)),
                zlib.crc32(np.ascontiguousarray(nuc)) if nuc is not None else 0)

    def measure_item(self, it) -> list[dict]:
        """Rows for an image's current plane and timepoint."""
        cells = it.cells
        if cells is None or not len(cells):
            return []
        planes = it.planes()
        particles = self.particles_for(it)
        rows = measure_cells(planes, cells, self.regions_for(it), it.channels, it.pixel_um,
                             particles, self.channels_for(it), self.stats())
        z = 'MIP' if it.z == 'mip' else ('mid' if it.z == 'mid' else f'z {int(it.z) + 1}')
        head = {'image': it.label, 'image_id': it.image_id, 'source': it.source_name,
                'timepoint': it.t + 1, 'plane': z}
        if particles is not None and particles.channel is not None:
            head['particle_channel'] = it.channels[particles.channel]
        return [{**head, **r} for r in rows]

    def refresh(self, force=False):
        it = self.win.current
        if it is not self.item:
            return
        _, bad = self.expressions()
        self.expr_info.setText('\n'.join(bad) if bad else EXPR_HELP)
        self.expr_info.setStyleSheet(f'color: {"#b35c00" if bad else "gray"}; font-size: 11px;')
        if it is None or it.cells is None or not len(it.cells):
            if it is not None:
                it.intensity = []
            self._sig = None
            self._fill_table()
            self.part_info.setText('')
            self.info.setText('세포질 ROI 탭에서 ROI를 검출하거나 그리세요.' if it is not None
                              else '이미지를 추가하세요.')
            self._draw_particles()
            return
        # only work when someone looks: the tab, or particles drawn on the image
        if not force and not self.visible_tab() and not (
                it.particle_settings is not None and self.show_particles.isChecked()):
            return
        s = it.particle_settings
        sig = (id(it), self._cells_key(it.cells), it.z, it.t,
               astuple(s) if s is not None else id(it.particles),
               self.base_boxes_state(), self.minus_particle.isChecked(), self.expr.text(),
               self.stats(), tuple(self.channels_for(it)))
        if not force and sig == self._sig:
            return
        try:
            it.intensity = self.measure_item(it)
        except Exception as exc:
            traceback.print_exc()
            self.info.setText(f'측정 실패: {exc}')
            return
        self._sig = sig
        self._particle_info(it)
        self._fill_table()
        self._draw_particles()

    def base_boxes_state(self):
        return tuple(b.isChecked() for b in self.base_boxes.values())

    def _particle_info(self, it):
        p = it.particles
        if p is None:
            self.part_info.setText('')
            return
        n = sum(p.counts(it.cells).values())
        txt = f'입자 {n}개, {int(p.mask.sum())} px'
        thr = [v for v in p.thresholds.values() if np.isfinite(v)]
        if thr and it.particle_settings is not None and it.particle_settings.method == 'otsu':
            txt += f' · 세포별 threshold {min(thr):.4g}–{max(thr):.4g}'
        elif it.particle_settings is None:
            txt += ' · 파일에서 불러온 입자 ROI'
        self.part_info.setText(txt)

    # ---- table ------------------------------------------------------------------

    def _rows_shown(self):
        if self.view.currentData() == 'batch':
            return self.batch_rows, True
        it = self.win.current
        return (it.intensity if it is not None else []), False

    def _fill_table(self):
        rows, batch = self._rows_shown()
        skip = {'image_id', 'source', 'plane', 'status', 'particle_channel'}
        if not batch:
            skip |= {'image', 'timepoint'}
        cols = []
        for r in rows:
            for k in r:
                if k not in skip and k not in cols:
                    cols.append(k)
        self.table.blockSignals(True)
        self.table.clear()
        self.table.setColumnCount(len(cols))
        self.table.setRowCount(len(rows))
        self.table.setHorizontalHeaderLabels(cols)
        for i, r in enumerate(rows):
            for j, k in enumerate(cols):
                v = r.get(k, '')
                text = f'{v:.4g}' if isinstance(v, float) else str(v)
                cell = QTableWidgetItem(text)
                if isinstance(v, (int, float)):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(i, j, cell)
        self.table.resizeColumnsToContents()
        self.table.blockSignals(False)
        if batch:
            n = len({r['image_id'] for r in rows})
            self.info.setText(f'일괄 측정: 이미지 {n}개, {len(rows)}행' if rows
                              else '‘모든 이미지 측정’을 누르세요.')
        else:
            it = self.win.current
            if it is not None and it.cells is not None and len(it.cells):
                z = rows[0]['plane'] if rows else ''
                t = f', t {it.t + 1}/{it.nt}' if it.nt > 1 else ''
                self.info.setText(f'세포 {len(it.cells)}개 · {z}{t} · {len(rows)}행')

    def _row_selected(self):
        rows, batch = self._rows_shown()
        sel = self.table.selectedItems()
        if batch or not sel:
            return
        r = rows[sel[0].row()]
        try:
            self.win.roi_panel.select(int(r['roi'][4:]))
        except (KeyError, ValueError):
            pass

    # ---- all images ---------------------------------------------------------------

    def _measure_items(self, items) -> dict[int, list[dict]]:
        plan = []
        for it in items:
            if it.cells is None or not len(it.cells):
                continue
            ts = list(range(it.nt)) if self.all_t.isChecked() and it.nt > 1 else [it.t]
            plan.append((it, ts))
        total = sum(len(ts) for _, ts in plan)
        out = {}
        if not total:
            return out
        prog = QProgressDialog('강도 측정 중…', '취소', 0, total, self)
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(300)
        done = 0
        for it, ts in plan:
            start_t = it.t
            rows = []
            try:
                for t in ts:
                    if prog.wasCanceled():
                        break
                    prog.setLabelText(f'강도 측정: {it.label}' + (f' · t {t + 1}' if len(ts) > 1 else ''))
                    prog.setValue(done)
                    QApplication.processEvents()
                    done += 1
                    if t != it.t:
                        it.set_t(t)
                    rows += self.measure_item(it)
            finally:
                if it.t != start_t:
                    it.set_t(start_t)
                if it is not self.win.current:
                    it.image.release()
            out[id(it)] = rows
            if prog.wasCanceled():
                break
        prog.setValue(total)
        return out

    def measure_all(self):
        items = [it for it in self.win.items if it.cells is not None and len(it.cells)]
        if not items:
            QMessageBox.information(self, '강도 측정', 'ROI가 있는 이미지가 없습니다.')
            return
        try:
            res = self._measure_items(items)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, '측정 실패', str(exc))
            return
        self.batch_rows = [r for it in items for r in res.get(id(it), [])]
        self.view.setCurrentIndex(self.view.findData('batch'))
        self._fill_table()
        self.status(f'강도 측정: 이미지 {len(res)}개, {len(self.batch_rows)}행')
        self.refresh(force=True)

    # ---- save -----------------------------------------------------------------------

    def save_companions(self, path, it, particles=None) -> list[str]:
        """<stem>_RoiSet.zip, <stem>_particles.zip and <stem>_image.png next to a CSV."""
        from PIL import Image

        base = Path(path).with_suffix('')
        files = it.cells.save(f'{base}_RoiSet.zip', properties=it.id_properties())
        if particles is not None and particles.mask.any():
            files.append(save_particles(f'{base}_particles.zip', it.cells, particles,
                                        it.id_properties()))
        png = f'{base}_image.png'
        Image.fromarray(overlay_image(it.composite(), it.cells, particles)).save(png)
        return files + [png]

    def save_current(self):
        it = self.win.current
        if it is None or it.cells is None or not len(it.cells):
            QMessageBox.information(self, '강도 측정', '먼저 세포 ROI를 검출하거나 그리세요.')
            return
        default = str(it.path.with_name(f'{item_stem(it)}_intensity.csv'))
        path, _ = QFileDialog.getSaveFileName(self, '강도 측정 CSV 저장', default, 'CSV (*.csv)')
        if not path:
            return
        try:
            rows = self.measure_item(it)
            write_rows(path, rows)
            if self.with_roi.isChecked():
                self.save_companions(path, it, self.particles_for(it))
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, '저장 실패', str(exc))
            return
        self.status(f'강도 측정 {len(rows)}행 저장: {path}')

    def save_item(self, it, folder, rows) -> list[str]:
        """<stem>_intensity.csv (+ companions) into an image's export folder."""
        folder = Path(folder)
        path = folder / f'{item_stem(it)}_intensity.csv'
        write_rows(path, rows)
        files = [str(path)]
        if self.with_roi.isChecked():
            files += self.save_companions(path, it, it.particles)
        return files

    def save_all(self):
        items = [it for it in self.win.items if it.cells is not None and len(it.cells)]
        if not items:
            QMessageBox.information(self, '강도 측정', 'ROI가 있는 이미지가 없습니다.')
            return
        out = QFileDialog.getExistingDirectory(self, '저장할 폴더 선택')
        if not out:
            return
        try:
            res = self._measure_items(items)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, '측정 실패', str(exc))
            return
        rows, errors, n = [], [], 0
        for it in items:
            if id(it) not in res:
                continue
            item_rows = res[id(it)]
            try:
                self.particles_for(it)  # the current plane's particles for the ROI file
                self.save_item(it, Path(out) / item_folder(it), item_rows)
                n += 1
            except Exception as exc:
                traceback.print_exc()
                errors.append(f'{it.label}: {exc}')
            if it is not self.win.current:
                it.image.release()
            rows += item_rows
        write_rows(Path(out) / 'intensity.csv', rows)
        self.batch_rows = rows
        self.view.setCurrentIndex(self.view.findData('batch'))
        self._fill_table()
        msg = (f'이미지 {n}개의 강도 측정을 이미지별 폴더에, 전체 {len(rows)}행을 '
               f'intensity.csv에 저장했습니다.\n{out}')
        if errors:
            msg += '\n\n실패:\n' + '\n'.join(errors)
        QMessageBox.information(self, '저장 완료', msg)
