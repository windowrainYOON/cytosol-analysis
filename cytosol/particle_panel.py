"""입자 ROI tab: particle ROIs inside every cell (cytosol.intensity), drawn on the
image, saved and loaded as ImageJ ROIs, and the intensity of the particle
region (and of the rest of the region they were found in) per cell."""

from __future__ import annotations

import traceback
from dataclasses import astuple, replace

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup,
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
    QRadioButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .intensity import (
    ParticleSettings,
    bit_depth,
    detect_particles,
    load_particles,
    make_regions,
    save_particles,
    trace_outlines,
)
from .lut import item_stem
from .measure_box import MeasureBox, cells_key

THR_STEPS = 1000
WITHIN = [('cyto', '세포질 (핵 제외)'), ('cell', '세포 전체')]


def _outlines(p, cells):
    """Pixel-edge outlines of every particle, touching ones drawn apart."""
    if p.labels is None:
        return trace_outlines(p.mask)
    from scipy import ndimage as ndi
    comp = p.components(cells)
    loops = []
    for k, sl in enumerate(ndi.find_objects(comp), start=1):
        if sl is not None:
            loops += trace_outlines(comp[sl] == k, sl[1].start, sl[0].start)
    return loops


class ParticlePanel(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.item = None
        self._busy = False
        self._hidden = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)  # coalesce ROI edits and slider drags
        self._timer.timeout.connect(self.refresh)
        lay = QVBoxLayout(self)

        help_ = QLabel('세포질 ROI 탭의 세포마다 한 채널에서 입자(점)를 찾아 입자 ROI로 만듭니다. '
                       '현재 Z(또는 MIP)와 시점에서 찾으며, ROI를 고치면 바로 다시 찾습니다.')
        help_.setWordWrap(True)
        help_.setStyleSheet('color: gray; font-size: 11px;')
        lay.addWidget(help_)

        part = QGroupBox('입자 ROI 추출')
        pl = QFormLayout(part)
        self.part_on = QCheckBox('이 이미지에서 입자 ROI 정의')
        self.part_on.setToolTip('세포마다 아래 채널에서 입자를 찾습니다.')
        pl.addRow(self.part_on)
        self.part_channel = QComboBox()
        pl.addRow('채널', self.part_channel)
        self.within = QComboBox()
        for key, text in WITHIN:
            self.within.addItem(text, key)
        pl.addRow('찾을 영역', self.within)
        self.thr_auto = QRadioButton('자동 (점 검출)')
        self.thr_auto.setToolTip('Hessian 필터로 세포마다 배경보다 뚜렷한 점(중앙값 + 민감도 × MAD)을 '
                                 '찾고, 배경을 뺀 이미지에서 각 점을 봉우리 높이의 일정 비율까지 '
                                 '넓힙니다. 붙어 있는 점은 따로 나뉩니다.')
        self.thr_manual = QRadioButton('수동 threshold')
        self.thr_auto.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.thr_auto)
        grp.addButton(self.thr_manual)
        row = QHBoxLayout()
        row.addWidget(self.thr_auto)
        row.addWidget(self.thr_manual)
        row.addStretch()
        pl.addRow('방법', row)
        self.spot_k = QDoubleSpinBox()
        self.spot_k.setRange(1.0, 20.0)
        self.spot_k.setSingleStep(0.5)
        self.spot_k.setDecimals(1)
        self.spot_k.setValue(3.0)
        self.spot_k.setToolTip('점의 중심이 세포 배경의 중앙값 + 이 값 × MAD(잡음)를 넘어야 '
                               '입자로 봅니다. 작을수록 흐린 점까지 찾습니다.')
        pl.addRow('자동 민감도 (k)', self.spot_k)
        self.spot_size = QDoubleSpinBox()
        self.spot_size.setRange(0.05, 20.0)
        self.spot_size.setSingleStep(0.05)
        self.spot_size.setDecimals(2)
        self.spot_size.setValue(0.4)
        self.spot_size.setSuffix(' µm')
        self.spot_size.setToolTip('찾을 입자의 대표 지름. 픽셀 크기 정보가 없는 이미지는 '
                                  '0.1 µm/px로 봅니다.')
        pl.addRow('자동 입자 지름', self.spot_size)
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
        self.show_particles.toggled.connect(lambda _: self.schedule())
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
        self.spot_k.valueChanged.connect(self._particle_changed)
        self.spot_size.valueChanged.connect(self._particle_changed)
        self.thr_spin.valueChanged.connect(self._thr_spin_changed)
        self.thr_slider.valueChanged.connect(self._thr_slider_changed)
        self.thr_manual.toggled.connect(self._manual_toggled)
        lay.addWidget(part)

        reg = QGroupBox('측정할 영역')
        row = QHBoxLayout(reg)
        self.reg_particle = QCheckBox('입자')
        self.reg_particle.setChecked(True)
        self.reg_rest = QCheckBox('입자를 뺀 나머지')
        self.reg_rest.setChecked(True)
        self.reg_rest.setToolTip('입자를 찾은 영역(세포질 또는 세포 전체)에서 입자를 뺀 나머지')
        for b in (self.reg_particle, self.reg_rest):
            b.toggled.connect(lambda _: self.measure.schedule())
            row.addWidget(b)
        row.addStretch()
        lay.addWidget(reg)
        self.measure = MeasureBox(win, 'particle_tab', self.regions_for, 'particle_intensity',
                                  '입자 강도 측정')
        lay.addWidget(self.measure, 1)

    # ---- helpers ----------------------------------------------------------

    def status(self, msg):
        self.win.statusBar().showMessage(msg)

    def schedule(self, *_):
        self._timer.start()
        self.measure.schedule()

    def visible_tab(self) -> bool:
        tabs = getattr(self.win, 'right_tabs', None)
        return tabs is not None and tabs.currentIndex() == getattr(self.win, 'particle_tab', -1)

    def overlay_changed(self, hidden=False):
        """Called whenever the ROI overlay is redrawn (edits, plane changes)."""
        self._hidden = hidden
        self.schedule()
        self._draw_particles()

    def regions_for(self, item):
        """Particle regions to measure; none on an image without particles."""
        if item.particles is None and item.particle_settings is None:
            return []
        exprs = []
        if self.reg_particle.isChecked():
            exprs.append('particle')
        if self.reg_rest.isChecked():
            s = item.particle_settings
            exprs.append(f'{s.within if s is not None else self.within.currentData()} - particle')
        return make_regions([], exprs)

    # ---- particles ----------------------------------------------------------

    def settings(self) -> ParticleSettings:
        name = self.part_channel.currentText().split(': ', 1)[-1]
        return ParticleSettings(
            channel=name, index=max(self.part_channel.currentData() or 0, 0),
            within=self.within.currentData(),
            method='manual' if self.thr_manual.isChecked() else 'auto',
            manual=self.thr_spin.value(), min_px=self.min_px.value(),
            k=self.spot_k.value(), size_um=self.spot_size.value())

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
        key = (item.z, item.t, astuple(s), cells_key(cells))
        p = item.particles
        if p is not None and p.plane_key == key:
            return p
        p = detect_particles(cells, item.planes()[c], s, bit_depth(item, c), item.pixel_um)
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
        self.win.particles_changed()

    def _manual_toggled(self, on):
        for w in (self.thr_spin, self.thr_slider):
            w.setEnabled(on)
        for w in (self.spot_k, self.spot_size):
            w.setEnabled(not on)
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
        self.win.particles_changed()

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
        self.win.particles_changed()

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
            loops = _outlines(p, it.cells) if p.mask.any() else []
            p._outline = loops
        canvas.show_particles(loops)

    def refresh(self):
        """Find the current image's particles when someone looks: this tab, or
        the outlines drawn on the image."""
        it = self.win.current
        if it is not self.item:
            return
        if it is not None and it.cells is not None and len(it.cells) and (
                self.visible_tab() or (it.particle_settings is not None
                                       and self.show_particles.isChecked())):
            try:
                self.particles_for(it)
            except Exception as exc:
                traceback.print_exc()
                self.part_info.setText(f'입자 찾기 실패: {exc}')
                return
        self._particle_info(it)
        self._draw_particles()

    def _particle_info(self, it):
        p = it.particles if it is not None else None
        if p is None or it.cells is None:
            self.part_info.setText('')
            return
        n = sum(p.counts(it.cells).values())
        txt = f'입자 {n}개, {int(p.mask.sum())} px'
        thr = [v for v in p.thresholds.values() if np.isfinite(v)]
        method = it.particle_settings.method if it.particle_settings is not None else None
        if thr and method == 'otsu':
            txt += f' · 세포별 threshold {min(thr):.4g}–{max(thr):.4g}'
        elif thr and method == 'auto':
            txt += f' · 세포별 입자 하한 {min(thr):.4g}–{max(thr):.4g}'
        elif it.particle_settings is None:
            txt += ' · 파일에서 불러온 입자 ROI'
        self.part_info.setText(txt)

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
                self.spot_k.setValue(s.k)
                self.spot_size.setValue(s.size_um)
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
        for w in (self.spot_k, self.spot_size):
            w.setEnabled(not self.thr_manual.isChecked())
        self._busy = False
        self.refresh()
        self.measure.bind(item)
