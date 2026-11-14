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
        lay.addWidget(_row(self.run_btn, self.all_btn, None))

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
        self.gate_max.setValue(2.5)
        f.addRow('최대 gate', self.gate_max)
        self.gap_max = QSpinBox()
        self.gap_max.setRange(0, 10)
        self.gap_max.setValue(1)
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
        self.inside.setSuffix(' % 이상의 프레임')
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
        v.addWidget(self.table)
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

    # ---- settings -----------------------------------------------------------

    def settings(self) -> tk.TrackSettings:
        return tk.TrackSettings(
            cells=self.cell_mode.currentData() or 'static', flow=self.use_flow.isChecked(),
            pattern=self.use_pattern.isChecked(), velocity=self.use_velocity.isChecked(),
            gate_um=self.gate.value(), gate_max_um=max(self.gate_max.value(), self.gate.value()),
            gap_max=self.gap_max.value(), w_int=self.w_int.value(), w_area=self.w_area.value(),
            inside_fraction=self.inside.value() / 100 - 1e-9, min_track=self.min_track.value(),
            exclude_merged=self.exclude_merged.isChecked(),
            ratio_b=self.ratio_b.currentData() or '', ratio_a=self.ratio_a.currentData() or '')

    def status(self, msg):
        self.win.statusBar().showMessage(msg)

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

    def _frame_cells(self, item, planes, mode):
        """Cell ROIs of one frame: the image's own, detected on this frame, or the whole image."""
        from .intensity import whole_image_cells
        h, w = planes.shape[-2:]
        if mode == 'none' or (mode == 'static' and (item.cells is None or not len(item.cells))):
            return whole_image_cells((h, w), item.pixel_um)
        if mode == 'static':
            return item.cells
        rp = self.win.roi_panel
        roles = dict(rp.roles(item))
        p = rp.params()
        try:
            if rp._any_size_auto():
                p = rp._sized(p, rp._auto_sizes(rp._image_sizes(item, roles)))
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        rois = rp._run_planes(planes, item.pixel_um, roles, p, rp.manual_mode(),
                              rp._man_value('cell'), rp._man_value('nuc'))
        rois.renumber()
        return rois

    def run(self, item, frames=None, progress=None) -> tk.TrackState | None:
        """Detect, link and measure the particles of one image over its frames."""
        from .cellroi import CellRois, link_cell_frames
        from .intensity import bit_depth, detect_particles, whole_image_cells
        from .prefetch import plane_at

        prm = self.settings()
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

        def planes_of(t):
            return np.asarray(plane_at(item.image, t, item.z) if T > 1 else item.planes(), np.float32)

        # cells per frame (IDs linked when detected per frame)
        cell_rois = {}
        if mode == 'frame':
            raw = {t: self._frame_cells(item, planes_of(t), mode) for t in frames}
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
                                          getattr(cells, 'nuclei', None) if mode != 'none' else None, prm)
            # cell movement between this frame and the next (inside cells only)
            for q in r:
                q['flow_y'] = q['flow_x'] = 0.0
            if prev is not None:
                pt, pr, pplanes = prev
                if prm.flow and mode != 'none' and pr:
                    try:
                        fl = tk.cell_flow(pplanes[flow_ch], planes[flow_ch])
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
        return tk.summary(st.points, chans, prm, st.ratio)

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
        self.refresh()

    def refresh(self):
        it = self.item
        pp = self.win.particle_panel
        if it is None:
            self.det_info.setText('이미지가 없습니다.')
        else:
            s = self._particle_settings(it)
            method = {'auto': '자동 (유의성)', 'spot': '점 모양 강조', 'manual': 'threshold', 'otsu': 'Otsu'}.get(s.method, s.method)
            crit = ' · 사용자 기준' if s.method == 'auto' and s.crit_k else ''
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
            self.det_state.setText(f'{src} · 입자 {len(st.points):,}개' +
                                   (f' · 세포 {st.cells}개' if getattr(st, 'cells', 0) else ''))
        else:
            self.det_state.set_kind('info')
            self.det_state.setText('추적 실행을 누르면 모든 프레임에서 입자를 찾고 잇습니다.')
        self._fill_table()
        self.draw()

    def _class_ok(self, row):
        k = row['class']
        return (k == 'inside' and self.show_in.isChecked()) or (k == 'outside' and self.show_out.isChecked()) \
            or (k == 'short' and self.show_short.isChecked())

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
        ins = sum(1 for r in long_ if r['class'] == 'inside')
        merged = sum(1 for p in st.points if p.get('merged'))
        self.state.set_kind('success')
        self.state.setText(f'트랙 {n}개 · 긴 트랙 {len(long_)}개 (세포 안 {ins}, 밖 {len(long_) - ins}) · '
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
        if it is None or it is not self.item or it.tracks is None or not self.show_tracks.isChecked():
            return
        if not (self.visible_tab() or self._sel is not None):
            return
        st = it.tracks
        f_now = it.t + 1
        cls = {r['track_id']: r['class'] for r in self.summary_of(it)}
        sc = self.win.canvas.scene()
        for tid, pts in st.tracks().items():
            k = cls.get(tid, 'short')
            if not ((k == 'inside' and self.show_in.isChecked()) or (k == 'outside' and self.show_out.isChecked())
                    or (k == 'short' and self.show_short.isChecked())):
                continue
            tail = [p for p in pts if f_now - TAIL <= p['frame'] <= f_now]
            if not tail:
                continue
            sel = tid == self._sel
            col = QColor(*PALETTE[tid % len(PALETTE)]) if k != 'outside' else QColor(170, 170, 170)
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
