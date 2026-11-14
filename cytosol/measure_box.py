"""Intensity measurement block shared by the 세포질 ROI, 입자 ROI and 강도 측정
tabs: ImageJ Measure values (cytosol.intensity) of the regions its tab picks,
a table that follows the ROIs, plane and settings of the current image, a
button that runs the same on every image, and saving both."""

from __future__ import annotations

import traceback
import zlib
from dataclasses import astuple
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .flow import FlowLayout
from .groups import GROUP_FILE, summarize, write_groups
from .intensity import STATS, measure_cells, overlay_image, region_names, write_rows
from .lut import item_folder, item_stem


def cells_key(cells):
    """Changes whenever the cell or nucleus ROIs change."""
    nuc = cells.nuclei
    return (id(cells), zlib.crc32(np.ascontiguousarray(cells.labels)),
            zlib.crc32(np.ascontiguousarray(nuc)) if nuc is not None else 0)


def uses_particles(regions) -> bool:
    return any('particle' in region_names(r.tree) for r in regions)


class MeasureBox(QWidget):
    """regions(item) -> list[Region] picks what to measure on an image; files
    are <stem>_<suffix>.csv per image and <suffix>.csv for the set."""

    def __init__(self, win, tab_attr: str, regions, suffix: str, title: str,
                 extra_files=None, overlay_regions=None, cells=None, rows=None, key=None,
                 summary=False):
        super().__init__()
        self.win = win
        self.summary = summary  # also n/mean/SD/min/max per image and per group
        # rows(item, cells, particles, channels, stats) -> rows, or None for
        # the per-cell region rows; key() -> what else the rows depend on
        self.rows_fn = rows
        self.key = key
        self.cells = cells or (lambda it: it.cells)  # item -> CellRois measured on
        self.tab_attr = tab_attr
        self.regions = regions
        self.suffix = suffix
        self.title = title
        self.extra_files = extra_files          # (item, base path) -> list of files
        self.overlay_regions = overlay_regions  # item -> regions drawn in the PNG
        self.rows: list[dict] = []        # current image, current plane
        self.batch_rows: list[dict] = []
        self._sig = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)  # coalesce ROI edits and slider drags
        self._timer.timeout.connect(self._fill_table)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        val = QGroupBox('측정 항목')
        vl0 = QLabel('세기 (채널마다)')
        theme.secondary(vl0)
        vl = QVBoxLayout(val)
        vl.addWidget(vl0)
        row = QHBoxLayout()
        self.stat_boxes = {}
        for k in STATS:
            b = theme.chip(QCheckBox(k))
            b.setChecked(k == 'Mean')
            b.toggled.connect(self.schedule)
            self.stat_boxes[k] = b
            row.addWidget(b)
        row.addStretch()
        vl.addLayout(row)
        # channels measured: one check box per channel of the current image;
        # what is switched off is kept by channel name, so it holds for every
        # image with that channel (and in projects)
        self.channels_off: set[str] = set()
        self._chan_boxes: list[QCheckBox] = []
        lab = QLabel('측정할 채널:')
        lab.setToolTip('체크한 채널만 표와 CSV에 들어갑니다. 끈 채널은 이름으로 기억해서 '
                       '같은 이름의 채널이 있는 모든 이미지에 적용됩니다 (검출에 쓰는 채널과는 별개).')
        vl.addWidget(lab)
        self._chan_holder = QWidget()
        self._chan_flow = FlowLayout(self._chan_holder)
        vl.addWidget(self._chan_holder)
        self.only_visible = QCheckBox('LUT에서 숨긴 채널 제외')
        self.only_visible.toggled.connect(self.schedule)
        vl.addWidget(self.only_visible)
        lay.addWidget(val)

        # 데이터 card (owner request 2026-11-14, data-display proposal): no
        # result table in the inspector; one row per table this tab makes,
        # its state, and a way into the graph window. The table widget and
        # the view pop-up stay as hidden state for older callers.
        self.view = QComboBox()
        self.view.addItem('현재 이미지', 'current')
        self.view.addItem('모든 이미지 (일괄 측정 결과)', 'batch')
        if summary:
            self.view.addItem('요약: 이미지별 (일괄 측정 결과)', 'sum_image')
            self.view.addItem('요약: 그룹별 (일괄 측정 결과)', 'sum_group')
        self.view.setCurrentIndex(1)
        self.view.setVisible(False)
        self.auto = QCheckBox('자동 갱신')
        self.auto.setChecked(False)
        self.auto.setVisible(False)
        self.table = QTableWidget(0, 0)
        self.table.setVisible(False)
        self._measured: dict = {}  # image_id -> settings signature the batch rows were measured with
        res = QGroupBox('데이터')
        tl = QVBoxLayout(res)
        self.state = theme.StatusLabel('')
        tl.addWidget(self.state)
        self._data_holder = QWidget()
        self._data_lay = QVBoxLayout(self._data_holder)
        self._data_lay.setContentsMargins(0, 0, 0, 0)
        self._data_lay.setSpacing(6)
        tl.addWidget(self._data_holder)
        self.info = QLabel()
        self.info.setWordWrap(True)
        theme.hint(self.info)
        tl.addWidget(self.info)
        row = QHBoxLayout()
        b = theme.prominent(QPushButton('모든 이미지 측정'))
        b.setToolTip('ROI가 있는 모든 이미지에서 같은 영역·측정값으로 잽니다 '
                     '(입자는 각 이미지의 입자 설정대로).')
        b.clicked.connect(self.measure_all)
        self.all_btn = b
        row.addWidget(b, 1)
        b = QPushButton('현재 이미지만')
        b.setToolTip('지금 보는 이미지만 다시 재서 데이터에 넣습니다.')
        b.clicked.connect(self.measure_current)
        row.addWidget(b, 1)
        tl.addLayout(row)
        self.all_t = QCheckBox('일괄 측정에 모든 시점 포함')
        tl.addWidget(self.all_t)
        # saving is in the menu of each tab; with_roi: also <name>_RoiSet.zip,
        # <name>_particles.zip and <name>_image.png (ROIs on the LUT image)
        self.with_roi = getattr(win, 'opt_with_roi', None)
        self.save_tip = ''
        self.set_suffix(suffix)
        lay.addWidget(res)

    # ---- helpers ----------------------------------------------------------

    def set_suffix(self, suffix: str):
        """CSV names: <stem>_<suffix>.csv per image, <suffix>.csv for the set."""
        self.suffix = suffix
        tip = (f'모든 이미지를 다시 잰 뒤 전체 결과 {suffix}.csv와, 이미지마다 '
               f'<이름>_<ID> 폴더에 그 이미지의 <이름>_{suffix}.csv를 저장합니다.')
        if self.summary:
            tip += (f'\n요약: {suffix}_summary_image.csv (이미지별), {suffix}_summary_group.csv '
                    f'(그룹별) — 파라미터마다 n, 평균, SD, 최소, 최대.')
        self.save_tip = tip

    def status(self, msg):
        self.win.statusBar().showMessage(msg)

    def schedule(self, *_):
        self._timer.start()

    def visible_tab(self) -> bool:
        tab_current = getattr(self.win, 'tab_current', None)
        return tab_current is not None and tab_current(self.tab_attr)

    def stats(self) -> tuple:
        return tuple(k for k in STATS if self.stat_boxes[k].isChecked()) or ('Mean',)

    def channels_for(self, item) -> list[int]:
        idx = [i for i, name in enumerate(item.channels) if name not in self.channels_off]
        if self.only_visible.isChecked():
            idx = [i for i in idx if i >= len(item.luts) or item.luts[i].visible]
        return idx

    def set_channels_off(self, names):
        self.channels_off = set(names or ())
        self._build_channel_boxes()
        self.schedule()

    def _build_channel_boxes(self):
        """One check box per channel of the current image."""
        while self._chan_flow.count():
            w = self._chan_flow.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self._chan_boxes = []
        it = self.win.current
        names = list(it.channels) if it is not None else []
        for name in names:
            b = theme.chip(QCheckBox(name))
            b.setChecked(name not in self.channels_off)
            b.toggled.connect(lambda on, n=name: self._channel_toggled(n, on))
            self._chan_flow.addWidget(b)
            self._chan_boxes.append(b)
        if not names:
            self._chan_flow.addWidget(QLabel('(이미지 없음)'))
        self._chan_holder.updateGeometry()

    def _channel_toggled(self, name, on):
        if on:
            self.channels_off.discard(name)
        else:
            self.channels_off.add(name)
        self.schedule()

    def has_rois(self, it) -> bool:
        cells = self.cells(it)
        return cells is not None and len(cells) > 0

    def particles_for(self, item):
        """The particles intensities are measured in (pixel or iso-contour ROIs)."""
        pp = getattr(self.win, 'particle_panel', None)
        return pp.intensity_particles_for(item) if pp is not None else item.particles

    # ---- measuring ------------------------------------------------------------

    def measure_item(self, it) -> list[dict]:
        """Rows for an image's current plane and timepoint."""
        cells = self.cells(it)
        if cells is None or not len(cells):
            return []
        regions = self.regions(it)
        if not regions or not self.channels_for(it):
            return []
        particles = self.particles_for(it) if uses_particles(regions) else None
        rows = None
        if self.rows_fn is not None:
            rows = self.rows_fn(it, cells, particles, self.channels_for(it), self.stats())
        if rows is None:
            rows = measure_cells(it.planes(), cells, regions, it.channels, it.pixel_um,
                                 particles, self.channels_for(it), self.stats())
        z = 'MIP' if it.z == 'mip' else ('mid' if it.z == 'mid' else f'z {int(it.z) + 1}')
        head = {'group': it.group} if any(i.group for i in self.win.items) else {}
        head |= {'image': it.label, 'image_id': it.image_id, 'source': it.source_name,
                'timepoint': it.t + 1, 'plane': z}
        if particles is not None and particles.channel is not None:
            head['particle_channel'] = it.channels[particles.channel]
        if particles is not None and particles.outline != 'pixel':
            head['particle_intensity_roi'] = particles.outline
        if cells is not it.cells:  # the whole image, no cell ROIs
            rows = [{**r, 'roi': 'image'} | ({'region': r['region'].replace('cell', 'image')}
                                             if 'region' in r else {}) for r in rows]
        return [{**head, **r} for r in rows]

    def _signature(self, it):
        regions = self.regions(it)
        part = None
        if uses_particles(regions):
            s = it.particle_settings
            part = astuple(s) if s is not None else id(it.particles)
            pp = getattr(self.win, 'particle_panel', None)
            if pp is not None:
                part = (part, pp.intensity_value())
        return (id(it), cells_key(self.cells(it)), it.z, it.t, tuple(r.name for r in regions), part,
                self.stats(), tuple(self.channels_for(it)), self.key() if self.key else None)

    def refresh(self, force=False):
        it = self.win.current
        cells = self.cells(it) if it is not None else None
        if cells is None or not len(cells):
            self.rows = []
            self._sig = None
            self._fill_table()
            return
        if not force and (not self.auto.isChecked() or not self.visible_tab()):
            return  # only work when someone looks
        try:
            sig = self._signature(it)
            if not force and sig == self._sig:
                return
            self.rows = self.measure_item(it)
        except Exception as exc:
            traceback.print_exc()
            self.info.setText(f'측정 실패: {exc}')
            self.info.setVisible(True)
            return
        self._sig = sig
        self._fill_table()

    def bind(self, item):
        self._build_channel_boxes()
        self._sig = None
        self.rows = []
        self._fill_table()

    # ---- table ------------------------------------------------------------------

    def _rows_shown(self):
        """Rows a graph of this tab shows: every measured image, else the
        current image (measured now)."""
        if self.batch_rows:
            return self.batch_rows, True
        return self.current_rows(), False

    def current_rows(self) -> list[dict]:
        """The current image's rows, measured when the ROIs or settings changed
        (ROI hover pop-over, live box, graphs without a batch)."""
        it = self.win.current
        if it is None or not self.has_rois(it):
            return []
        try:
            sig = self._signature(it)
            if sig != self._sig:
                self.rows = self.measure_item(it)
                self._sig = sig
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            return []
        return self.rows

    # ---- data names and state -----------------------------------------------------

    BASE = {'roi_tab': '세포질 ROI', 'particle_tab': '입자 ROI', 'intensity_tab': '강도 측정',
            'bands_tab': '등거리 띠'}
    UNIT = {'cell_intensity': '세포', 'particle_intensity': '세포', 'particle_shape': '입자',
            'intensity': '영역', 'bands': '세포 × 띠'}

    def data_name(self, which='rows') -> str:
        base = self.BASE.get(self.tab_attr, self.title)
        if which == 'image':
            return f'{base} · 이미지 요약'
        if which == 'group':
            return f'{base} · 그룹 요약'
        return f'{base} · {self.UNIT.get(self.suffix, "행")}'

    def data_tables(self) -> list[tuple]:
        """(name, 점 하나 =, rows) of every table this tab makes."""
        out = [(self.data_name(), self.UNIT.get(self.suffix, '행'), self.batch_rows)]
        if self.summary:
            out.append((self.data_name('image'), '이미지', summarize(self.batch_rows, True) if self.batch_rows else []))
            out.append((self.data_name('group'), '그룹', summarize(self.batch_rows, False) if self.batch_rows else []))
        return out

    def _settings_sig(self, it):
        sig = self._signature(it)
        return (sig[1],) + tuple(sig[4:])  # ROIs, regions, particles, stats, channels, key (not z / t)

    def stale_items(self) -> list:
        """Images measured before their ROIs or the settings changed."""
        out = []
        for it in self.win.items:
            old = self._measured.get(it.image_id)
            if old is None or not self.has_rois(it):
                continue
            try:
                if self._settings_sig(it) != old:
                    out.append(it)
            except Exception:  # noqa: BLE001
                out.append(it)
        return out

    def _remember(self, items):
        for it in items:
            try:
                self._measured[it.image_id] = self._settings_sig(it)
            except Exception:  # noqa: BLE001
                pass

    def _merge(self, items, res):
        ids = {it.image_id for it in items}
        keep = [r for r in self.batch_rows if r.get('image_id') not in ids]
        order = [it.image_id for it in self.win.items]
        new = keep + [r for it in items for r in res.get(id(it), [])]
        self.batch_rows = sorted(new, key=lambda r: order.index(r.get('image_id'))
                                 if r.get('image_id') in order else len(order))
        self._remember(items)

    def update_stale(self) -> int:
        """Measure again only the images whose ROIs or settings changed; the
        graph window calls this when a table marked 설정 바뀜 is opened."""
        items = self.stale_items()
        if not items:
            return 0
        res = self.measure_items(items)
        self._merge(items, res)
        self._fill_table()
        self.status(f'{self.data_name()}: 바뀐 이미지 {len(items)}개를 다시 쟀습니다.')
        return len(items)

    def measure_current(self):
        it = self.win.current
        if it is None or not self.has_rois(it):
            QMessageBox.information(self, self.title, '먼저 ROI를 검출하거나 그리세요.')
            return
        self.refresh(force=True)
        self._merge([it], {id(it): list(self.rows)})
        self._fill_table()
        self.status(f'{self.data_name()}: {it.label} {len(self.rows)}행')

    def regroup(self):
        """Give rows measured before a group change their image's new group."""
        groups = {it.image_id: it.group for it in self.win.items}
        show = any(groups.values())
        for rows in (self.rows, self.batch_rows):
            for i, r in enumerate(rows):
                rest = {k: v for k, v in r.items() if k != 'group'}
                rows[i] = ({'group': groups.get(r.get('image_id'), r.get('group', ''))} | rest
                           if show else rest)
        self._fill_table()

    def write_summaries(self, folder, rows) -> list[str]:
        """<suffix>_summary_image.csv and <suffix>_summary_group.csv of a set."""
        if not self.summary or not rows:
            return []
        files = []
        for by_image, name in ((True, 'image'), (False, 'group')):
            path = Path(folder) / f'{self.suffix}_summary_{name}.csv'
            if write_rows(path, summarize(rows, by_image)):
                files.append(str(path))
        return files

    def _fill_table(self):
        """The 데이터 card: one line per table (name, 점 하나, size, state,
        그래프 ›) and the state line."""
        from .hig_widgets import IconButton  # noqa: F401

        while self._data_lay.count():
            w = self._data_lay.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        stale = self.stale_items() if self.batch_rows else []
        n_img = len({r.get('image_id') for r in self.batch_rows})
        total = sum(1 for it in self.win.items if self.has_rois(it))
        for name, unit, rows in self.data_tables():
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(8)
            lab = QLabel(f'<b>{name}</b>')
            lab.setToolTip(f'점 하나 = {unit}')
            h.addWidget(lab)
            size = QLabel(f'{len(rows)}행 · 이미지 {len({r.get("image_id", r.get("image")) for r in rows})}'
                          if rows else '없음')
            theme.secondary(size)
            h.addWidget(size)
            h.addStretch()
            kind = None if not rows else ('warning' if stale else 'success')
            st = theme.StatusLabel('설정 바뀜' if rows and stale else '최신' if rows else '', kind=kind)
            st.setVisible(bool(rows))
            h.addWidget(st)
            g = QPushButton('그래프 ›')
            g.setEnabled(bool(rows))
            g.setToolTip('그래프 창에서 이 표로 새 그래프를 만듭니다 (종류 → 축 배치 → 그룹).')
            g.clicked.connect(lambda _=False, n=name: self.open_graph(n))
            h.addWidget(g)
            self._data_lay.addWidget(w)
        if not total:
            it = self.win.current
            self.state.setText('세포질 ROI 탭에서 ROI를 검출하거나 그리세요.' if it is not None
                               else '이미지를 추가하세요.')
            self.state.set_kind(None)
        elif not self.batch_rows:
            self.state.setText(f'ROI가 있는 이미지 {total}개 · 아직 측정하지 않았습니다.')
            self.state.set_kind(None)
        elif stale:
            self.state.setText(f'{total} 이미지 중 {n_img}개 측정됨 · ROI나 측정 항목이 바뀐 이미지 '
                               f'{len(stale)}개는 다시 측정해야 합니다.')
            self.state.set_kind('warning')
        else:
            self.state.setText(f'{total} 이미지 중 {n_img}개 측정됨')
            self.state.set_kind('success' if n_img >= total else None)
        it = self.win.current
        cells = self.cells(it) if it is not None else None
        if cells is not None and len(cells) and not self.regions(it):
            self.info.setText('측정할 영역이 없습니다.')
        elif cells is not None and len(cells) and not self.channels_for(it):
            self.info.setText('측정할 채널을 하나 이상 체크하세요.')
        else:
            self.info.setText('')
        self.info.setVisible(bool(self.info.text()))
        badge = getattr(self.win, 'update_tab_badges', None)
        if badge is not None:
            badge()

    def open_graph(self, name):
        gw = getattr(self.win, 'graph_window', None)
        if gw is None:
            return
        w = gw()
        w.start_data(name)

    def _row_selected(self):
        return

    # ---- all images ---------------------------------------------------------------

    def measure_items(self, items) -> dict[int, list[dict]]:
        plan = []
        for it in items:
            cells = self.cells(it)
            if cells is None or not len(cells):
                continue
            ts = list(range(it.nt)) if self.all_t.isChecked() and it.nt > 1 else [it.t]
            plan.append((it, ts))
        total = sum(len(ts) for _, ts in plan)
        out = {}
        if not total:
            return out
        prog = QProgressDialog(f'{self.title} 중…', '취소', 0, total, self)
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
                    prog.setLabelText(f'{self.title}: {it.label}' + (f' · t {t + 1}' if len(ts) > 1 else ''))
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

    def _items(self):
        items = [it for it in self.win.items if self.has_rois(it)]
        if not items:
            QMessageBox.information(self, self.title, 'ROI가 있는 이미지가 없습니다.')
        return items

    def measure_all(self):
        items = self._items()
        if not items:
            return
        try:
            res = self.measure_items(items)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, '측정 실패', str(exc))
            return
        self.batch_rows = [r for it in items for r in res.get(id(it), [])]
        self._measured = {}
        self._remember([it for it in items if id(it) in res])
        self._fill_table()
        self.status(f'{self.data_name()}: 이미지 {len(res)}개, {len(self.batch_rows)}행')

    # ---- save -----------------------------------------------------------------------

    def save_companions(self, path, it) -> list[str]:
        """<stem>_RoiSet.zip, <stem>_particles.zip (when measured), any extra
        ROI files of the tab and <stem>_image.png next to a CSV."""
        from PIL import Image

        base = str(Path(path).with_suffix(''))
        tail = '_' + self.suffix
        stem = base[:-len(tail)] if base.endswith(tail) else base
        cells = self.cells(it)
        files = []
        if it.cells is not None and len(it.cells):
            files = it.cells.save(f'{stem}_RoiSet.zip', properties=it.id_properties())
        regions = self.regions(it)
        particles = self.particles_for(it) if uses_particles(regions) else None
        pixel = self.win.particle_panel.particles_for(it) if particles is not None else None
        if pixel is not None and pixel.mask.any():
            files += self.win.particle_panel.save_particle_files(
                it, f'{stem}_particles.zip', cells, pixel)
        if self.extra_files is not None:
            files += self.extra_files(it, stem)
        extra = self.overlay_regions(it) if self.overlay_regions is not None else None
        png = f'{stem}_image.png'
        Image.fromarray(overlay_image(it.composite(), cells, particles, regions=extra)).save(png)
        return files + [png]

    def save_current(self):
        it = self.win.current
        if it is None or not self.has_rois(it):
            QMessageBox.information(self, self.title, '먼저 ROI를 검출하거나 그리세요.')
            return
        default = str(it.path.with_name(f'{item_stem(it)}_{self.suffix}.csv'))
        path, _ = QFileDialog.getSaveFileName(self, f'{self.title} CSV 저장', default, 'CSV (*.csv)')
        if not path:
            return
        try:
            rows = self.measure_item(it)
            write_rows(path, rows)
            if self.summary:
                write_rows(Path(path).with_name(Path(path).stem + '_summary.csv'),
                           summarize(rows, True))
            if self.with_roi is None or self.with_roi.isChecked():
                self.save_companions(path, it)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, '저장 실패', str(exc))
            return
        self.status(f'{self.title} {len(rows)}행 저장: {path}')

    def save_item(self, it, folder, rows, companions=None) -> list[str]:
        """<stem>_<suffix>.csv (+ companions) into an image's export folder."""
        path = Path(folder) / f'{item_stem(it)}_{self.suffix}.csv'
        if not write_rows(path, rows):
            return []
        files = [str(path)]
        if self.summary:
            summ = path.with_name(f'{path.stem}_summary.csv')
            if write_rows(summ, summarize(rows, True)):
                files.append(str(summ))
        if (self.with_roi is None or self.with_roi.isChecked()) if companions is None else companions:
            files += self.save_companions(path, it)
        return files

    def save_all(self):
        items = self._items()
        if not items:
            return
        out = QFileDialog.getExistingDirectory(self, '저장할 폴더 선택')
        if not out:
            return
        try:
            res = self.measure_items(items)
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
                if self.save_item(it, Path(out) / item_folder(it), item_rows):
                    n += 1
            except Exception as exc:
                traceback.print_exc()
                errors.append(f'{it.label}: {exc}')
            if it is not self.win.current:
                it.image.release()
            rows += item_rows
        write_rows(Path(out) / f'{self.suffix}.csv', rows)
        summaries = self.write_summaries(out, rows)
        grouped = write_groups(Path(out) / GROUP_FILE, items)
        self.batch_rows = rows
        self._remember(items)
        self._fill_table()
        msg = (f'이미지 {n}개의 {self.title} 결과를 이미지별 폴더에, 전체 {len(rows)}행을 '
               f'{self.suffix}.csv에 저장했습니다.')
        if summaries:
            msg += f'\n요약: {", ".join(Path(f).name for f in summaries)}'
        if grouped:
            msg += f'\n그룹: {GROUP_FILE}'
        msg += f'\n{out}'
        if errors:
            msg += '\n\n실패:\n' + '\n'.join(errors)
        QMessageBox.information(self, '저장 완료', msg)
