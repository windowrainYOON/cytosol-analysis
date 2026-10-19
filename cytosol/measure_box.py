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
    QAbstractItemView,
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
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .intensity import STATS, measure_cells, overlay_image, region_names, save_particles, write_rows
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
                 extra_files=None, overlay_regions=None):
        super().__init__()
        self.win = win
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
        self._timer.timeout.connect(self.refresh)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

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

        res = QGroupBox('강도 측정 결과')
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
        self.table.setMinimumHeight(200)
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
        row = QHBoxLayout()
        b = QPushButton('CSV 저장 (현재 이미지)…')
        b.clicked.connect(self.save_current)
        row.addWidget(b)
        b = QPushButton('모든 이미지 측정 + 저장 (폴더)…')
        b.setToolTip(f'모든 이미지를 다시 잰 뒤 전체 결과 {suffix}.csv와, 이미지마다 '
                     f'<이름>_<ID> 폴더에 그 이미지의 <이름>_{suffix}.csv를 저장합니다.')
        b.clicked.connect(self.save_all)
        row.addWidget(b)
        tl.addLayout(row)
        self.with_roi = QCheckBox('ROI(.zip)와 ROI가 그려진 이미지(.png)도 함께 저장')
        self.with_roi.setChecked(True)
        self.with_roi.setToolTip('<이름>_RoiSet.zip (세포·핵·세포질), 입자를 쓰면 <이름>_particles.zip, '
                                 '<이름>_image.png (현재 LUT 이미지 위에 ROI 경계)')
        tl.addWidget(self.with_roi)
        lay.addWidget(res, 1)

    # ---- helpers ----------------------------------------------------------

    def status(self, msg):
        self.win.statusBar().showMessage(msg)

    def schedule(self, *_):
        self._timer.start()

    def visible_tab(self) -> bool:
        tabs = getattr(self.win, 'right_tabs', None)
        return tabs is not None and tabs.currentIndex() == getattr(self.win, self.tab_attr, -1)

    def stats(self) -> tuple:
        return tuple(k for k in STATS if self.stat_boxes[k].isChecked()) or ('Mean',)

    def channels_for(self, item) -> list[int]:
        idx = list(range(len(item.channels)))
        if self.only_visible.isChecked():
            idx = [i for i in idx if i >= len(item.luts) or item.luts[i].visible]
        return idx

    def particles_for(self, item):
        pp = getattr(self.win, 'particle_panel', None)
        return pp.particles_for(item) if pp is not None else item.particles

    # ---- measuring ------------------------------------------------------------

    def measure_item(self, it) -> list[dict]:
        """Rows for an image's current plane and timepoint."""
        cells = it.cells
        if cells is None or not len(cells):
            return []
        regions = self.regions(it)
        if not regions:
            return []
        particles = self.particles_for(it) if uses_particles(regions) else None
        rows = measure_cells(it.planes(), cells, regions, it.channels, it.pixel_um,
                             particles, self.channels_for(it), self.stats())
        z = 'MIP' if it.z == 'mip' else ('mid' if it.z == 'mid' else f'z {int(it.z) + 1}')
        head = {'image': it.label, 'image_id': it.image_id, 'source': it.source_name,
                'timepoint': it.t + 1, 'plane': z}
        if particles is not None and particles.channel is not None:
            head['particle_channel'] = it.channels[particles.channel]
        return [{**head, **r} for r in rows]

    def _signature(self, it):
        regions = self.regions(it)
        part = None
        if uses_particles(regions):
            s = it.particle_settings
            part = astuple(s) if s is not None else id(it.particles)
        return (id(it), cells_key(it.cells), it.z, it.t, tuple(r.name for r in regions), part,
                self.stats(), tuple(self.channels_for(it)))

    def refresh(self, force=False):
        it = self.win.current
        if it is None or it.cells is None or not len(it.cells):
            self.rows = []
            self._sig = None
            self._fill_table()
            self.info.setText('세포질 ROI 탭에서 ROI를 검출하거나 그리세요.' if it is not None
                              else '이미지를 추가하세요.')
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
            return
        self._sig = sig
        self._fill_table()

    def bind(self, item):
        self._sig = None
        self.rows = []
        self.refresh(force=self.visible_tab())
        if not self.visible_tab():
            self._fill_table()

    # ---- table ------------------------------------------------------------------

    def _rows_shown(self):
        if self.view.currentData() == 'batch':
            return self.batch_rows, True
        return self.rows, False

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
                if rows:
                    t = f', t {it.t + 1}/{it.nt}' if it.nt > 1 else ''
                    self.info.setText(f'세포 {len(it.cells)}개 · {rows[0]["plane"]}{t} · {len(rows)}행')
                elif not self.regions(it):
                    self.info.setText('측정할 영역이 없습니다.')
                else:
                    self.info.setText('')

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

    def measure_items(self, items) -> dict[int, list[dict]]:
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
        items = [it for it in self.win.items if it.cells is not None and len(it.cells)]
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
        self.view.setCurrentIndex(self.view.findData('batch'))
        self._fill_table()
        self.status(f'{self.title}: 이미지 {len(res)}개, {len(self.batch_rows)}행')
        self.refresh(force=True)

    # ---- save -----------------------------------------------------------------------

    def save_companions(self, path, it) -> list[str]:
        """<stem>_RoiSet.zip, <stem>_particles.zip (when measured), any extra
        ROI files of the tab and <stem>_image.png next to a CSV."""
        from PIL import Image

        base = str(Path(path).with_suffix(''))
        tail = '_' + self.suffix
        stem = base[:-len(tail)] if base.endswith(tail) else base
        files = it.cells.save(f'{stem}_RoiSet.zip', properties=it.id_properties())
        regions = self.regions(it)
        particles = self.particles_for(it) if uses_particles(regions) else None
        if particles is not None and particles.mask.any():
            files.append(save_particles(f'{stem}_particles.zip', it.cells, particles,
                                        it.id_properties()))
        if self.extra_files is not None:
            files += self.extra_files(it, stem)
        extra = self.overlay_regions(it) if self.overlay_regions is not None else None
        png = f'{stem}_image.png'
        Image.fromarray(overlay_image(it.composite(), it.cells, particles, regions=extra)).save(png)
        return files + [png]

    def save_current(self):
        it = self.win.current
        if it is None or it.cells is None or not len(it.cells):
            QMessageBox.information(self, self.title, '먼저 세포 ROI를 검출하거나 그리세요.')
            return
        default = str(it.path.with_name(f'{item_stem(it)}_{self.suffix}.csv'))
        path, _ = QFileDialog.getSaveFileName(self, f'{self.title} CSV 저장', default, 'CSV (*.csv)')
        if not path:
            return
        try:
            rows = self.measure_item(it)
            write_rows(path, rows)
            if self.with_roi.isChecked():
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
        if self.with_roi.isChecked() if companions is None else companions:
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
        self.batch_rows = rows
        self.view.setCurrentIndex(self.view.findData('batch'))
        self._fill_table()
        msg = (f'이미지 {n}개의 {self.title} 결과를 이미지별 폴더에, 전체 {len(rows)}행을 '
               f'{self.suffix}.csv에 저장했습니다.\n{out}')
        if errors:
            msg += '\n\n실패:\n' + '\n'.join(errors)
        QMessageBox.information(self, '저장 완료', msg)
