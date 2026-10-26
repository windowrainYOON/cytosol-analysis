"""Coloc 2 tab: Fiji's Coloc 2 analysis (cytosol.coloc) for every cell ROI,
with the Coloc 2 options, a results table, the 2D histograms and CSV/PDF export."""

from __future__ import annotations

import csv
import math
import re
import traceback
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .coloc import REGRESSIONS, Coloc2Result, Coloc2Settings, ValueType, d2s, run_coloc2
from .lut import item_folder, item_stem

REGIONS = [
    ('cell', '세포 전체', 'cell'),
    ('cyto', '세포질 (핵 제외)', 'cyto'),
    ('nuc', '핵', 'nuc'),
]
ALGORITHMS = [
    ('li_ch1', 'Li Histogram Channel 1'),
    ('li_ch2', 'Li Histogram Channel 2'),
    ('li_icq', 'Li ICQ'),
    ('spearman', "Spearman's Rank Correlation"),
    ('manders', "Manders' Correlation"),
    ('kendall', "Kendall's Tau Rank Correlation"),
    ('histogram', '2D Intensity Histogram'),
    ('costes', "Costes' Significance Test"),
]
# columns of the results table: (header, Coloc 2 value name)
SUMMARY = [
    ('Pearson R', "Pearson's R value (no threshold)"),
    ('R above thr', "Pearson's R value (above threshold)"),
    ('tM1', "Manders' tM1 (Above autothreshold of Ch2)"),
    ('tM2', "Manders' tM2 (Above autothreshold of Ch1)"),
    ('M1', "Manders' M1 (Above zero intensity of Ch2)"),
    ('M2', "Manders' M2 (Above zero intensity of Ch1)"),
    ('ICQ', "Li's ICQ value"),
    ('Spearman', "Spearman's rank correlation value"),
    ('Kendall', "Kendall's Tau-b rank correlation value"),
    ('Costes P', 'Costes P-Value'),
]
REGION_NAMES = {'cell': 'cell', 'cyto': 'cytosol', 'nuc': 'nucleus'}
INT_NOTE = re.compile(r'^(u?int)(8|16|32)$|^(\d+)-bit$')


@dataclass
class ColocRecord:
    """One Coloc 2 run: an image, timepoint, plane, ROI and channel pair."""

    image: str
    image_id: str
    source: str
    t: int
    plane: str
    roi: str
    region: str
    label: int
    ch1: str
    ch2: str
    n_pixels: int
    result: Coloc2Result

    def row(self) -> dict:
        r = {'image': self.image, 'image_id': self.image_id, 'source': self.source,
             'timepoint': self.t + 1, 'plane': self.plane, 'roi': self.roi,
             'region': self.region, 'channel_1': self.ch1, 'channel_2': self.ch2,
             'n_pixels': self.n_pixels}
        for name, value, _ in self.result.values:
            r[name] = value if isinstance(value, str) else _num(value)
        r['warnings'] = ' | '.join(w for w, _ in self.result.warnings)
        return r


def _num(v):
    if v is None:
        return ''
    if isinstance(v, (int, np.integer)):
        return int(v)
    v = float(v)
    if math.isnan(v):
        return 'NaN'
    if math.isinf(v):
        return 'Infinity' if v > 0 else '-Infinity'
    return repr(v)


def write_coloc_csv(path, records) -> int:
    """All records as rows (one per ROI/timepoint); columns as Coloc 2 names them."""
    rows = [r.row() for r in records]
    if not rows:
        return 0
    fields = []
    for row in rows:
        for k in row:
            if k not in fields:
                fields.append(k)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fields, restval='')
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def channel_value_type(item, c1: int, c2: int) -> tuple[ValueType, str]:
    """ImageJ pixel type of the two channels as stored in the file (8/16-bit
    integer or 32-bit float) and a warning when they differ."""
    notes = list(getattr(item.image, 'range_notes', []) or [])
    types = []
    for c in (c1, c2):
        note = notes[c] if c < len(notes) else ''
        m = INT_NOTE.match(note or '')
        if m and m.group(1):
            dt = np.dtype(f'{m.group(1)}{m.group(2)}')
            types.append(ValueType.for_dtype('uint8' if dt.itemsize == 1 and dt.kind == 'u'
                                             else 'uint16' if dt.itemsize <= 2 else 'float32'))
        elif m and m.group(3):
            bits = int(m.group(3))
            types.append(ValueType.for_dtype('uint8' if bits <= 8 else
                                             'uint16' if bits <= 16 else 'float32'))
        else:
            types.append(ValueType.for_dtype('float32'))
    if types[0].name != types[1].name:
        return ValueType.for_dtype('float32'), (
            f'두 채널의 비트 깊이가 다릅니다 ({types[0].name}, {types[1].name}). '
            'Coloc 2는 이 경우 실행하지 않습니다; 32-bit float로 계산했습니다.')
    return types[0], ''


def region_mask(cells, label: int, region: str) -> np.ndarray:
    cell = cells.labels == label
    if region == 'cell':
        return cell
    nuc = (cells.nuclei == label) & cell if cells.nuclei is not None else np.zeros_like(cell)
    return nuc if region == 'nuc' else cell & ~nuc


class ColocPanel(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.item = None
        self.records: list[ColocRecord] = []
        lay = QVBoxLayout(self)

        help_ = QLabel('Fiji Coloc 2와 같은 계산(원본 코드를 그대로 옮김)을 세포 ROI마다 실행합니다. '
                       '세포질 ROI 탭에서 ROI를 먼저 검출하거나 불러오세요.')
        help_.setWordWrap(True)
        help_.setStyleSheet('color: gray; font-size: 11px;')
        lay.addWidget(help_)

        ch = QGroupBox('채널')
        fl = QFormLayout(ch)
        self.ch1 = QComboBox()
        self.ch2 = QComboBox()
        fl.addRow('Channel 1', self.ch1)
        fl.addRow('Channel 2', self.ch2)
        lay.addWidget(ch)

        roi = QGroupBox('ROI')
        rl = QVBoxLayout(roi)
        row = QHBoxLayout()
        self.region_boxes = {}
        for key, text, _ in REGIONS:
            b = QCheckBox(text)
            b.setChecked(key in ('cell', 'cyto'))
            self.region_boxes[key] = b
            row.addWidget(b)
        rl.addLayout(row)
        row = QHBoxLayout()
        self.selected_only = QCheckBox('선택한 세포만')
        self.whole = QCheckBox('이미지 전체 (ROI 없음)')
        self.whole.setToolTip('Coloc 2에서 ROI_or_mask를 <None>으로 둔 것과 같습니다.')
        row.addWidget(self.selected_only)
        row.addWidget(self.whole)
        row.addStretch()
        rl.addLayout(row)
        lay.addWidget(roi)

        data = QGroupBox('데이터')
        dl = QFormLayout(data)
        self.z_mode = QComboBox()
        self.z_mode.addItem('현재 평면 (화면의 Z 또는 MIP)', 'plane')
        self.z_mode.addItem('Z 스택 전체 (3D, ROI를 모든 Z에 적용)', 'stack')
        self.z_mode.setToolTip('Z 스택: Coloc 2에 2D ROI와 스택을 넣은 것처럼 ROI가 모든 Z 평면에 적용됩니다.')
        dl.addRow('Z', self.z_mode)
        self.all_t = QCheckBox('모든 시점')
        dl.addRow('시점', self.all_t)
        lay.addWidget(data)

        opt = QGroupBox('Coloc 2 옵션')
        ol = QGridLayout(opt)
        self.regression = QComboBox()
        self.regression.addItems(REGRESSIONS)
        ol.addWidget(QLabel('Threshold regression'), 0, 0)
        ol.addWidget(self.regression, 0, 1)
        self.algo = {}
        for i, (key, text) in enumerate(ALGORITHMS):
            b = QCheckBox(text)
            b.setChecked(True)
            self.algo[key] = b
            ol.addWidget(b, 1 + i // 2, i % 2)
        r = 1 + (len(ALGORITHMS) + 1) // 2
        self.psf = QSpinBox()
        self.psf.setRange(1, 100)
        self.psf.setValue(3)
        self.psf.setSuffix(' px')
        self.psf.setToolTip('Costes 검정에서 섞는 블록의 한 변 (= PSF 크기, 픽셀)')
        self.nrand = QSpinBox()
        self.nrand.setRange(2, 100000)
        self.nrand.setValue(10)
        ol.addWidget(QLabel('PSF'), r, 0)
        ol.addWidget(self.psf, r, 1)
        ol.addWidget(QLabel('Costes randomisations'), r + 1, 0)
        ol.addWidget(self.nrand, r + 1, 1)
        self.show_shuffled = QCheckBox('Display Shuffled Images')
        self.show_images = QCheckBox('Display Images in Result')
        ol.addWidget(self.show_images, r + 2, 0)
        ol.addWidget(self.show_shuffled, r + 2, 1)
        self.algo['costes'].toggled.connect(self._costes_toggled)
        lay.addWidget(opt)

        row = QHBoxLayout()
        run_one = QPushButton('계산 (현재 이미지)')
        run_one.clicked.connect(self.run_current)
        run_all = QPushButton('모든 이미지')
        run_all.setToolTip('ROI가 있는 모든 이미지에서 같은 이름의 채널로 계산')
        run_all.clicked.connect(self.run_all)
        row.addWidget(run_one, 2)
        row.addWidget(run_all, 1)
        lay.addLayout(row)

        res = QGroupBox('결과')
        vl = QVBoxLayout(res)
        self.table = QTableWidget(0, 0)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setMinimumHeight(160)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._row_selected)
        vl.addWidget(self.table, 1)

        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from matplotlib.figure import Figure

        self.view = QComboBox()
        self.view.currentIndexChanged.connect(lambda _: self._draw())
        vl.addWidget(self.view)
        self.fig = Figure(figsize=(4, 3.6), dpi=100, layout='constrained')
        self.plot = FigureCanvasQTAgg(self.fig)
        self.plot.setMinimumHeight(300)
        vl.addWidget(self.plot)
        self.values = QTableWidget(0, 2)
        self.values.setHorizontalHeaderLabels(['Coloc 2 결과', '값'])
        self.values.verticalHeader().setVisible(False)
        self.values.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.values.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.values.setMinimumHeight(220)
        vl.addWidget(self.values)
        self.warn = QLabel()
        self.warn.setWordWrap(True)
        self.warn.setStyleSheet('color: #b35c00; font-size: 11px;')
        vl.addWidget(self.warn)
        lay.addWidget(res, 1)

        self._draw()

    # ---- settings ---------------------------------------------------------

    def _costes_toggled(self, on):
        for w in (self.psf, self.nrand, self.show_shuffled):
            w.setEnabled(on)

    def settings(self) -> Coloc2Settings:
        a = {k: b.isChecked() for k, b in self.algo.items()}
        return Coloc2Settings(
            regression=self.regression.currentText(), psf=self.psf.value(),
            costes_randomisations=self.nrand.value(),
            display_shuffled=self.show_shuffled.isChecked() and a['costes'],
            display_images=self.show_images.isChecked(), **a)

    def status(self, msg):
        self.win.statusBar().showMessage(msg)

    # ---- image selection ---------------------------------------------------

    def bind(self, item):
        self.item = item
        keep = (self.ch1.currentText(), self.ch2.currentText())
        for combo in (self.ch1, self.ch2):
            combo.blockSignals(True)
            combo.clear()
        if item is not None:
            for i, name in enumerate(item.channels):
                self.ch1.addItem(f'C{i}: {name}', i)
                self.ch2.addItem(f'C{i}: {name}', i)
            i1, i2 = self._default_channels(item, keep)
            self.ch1.setCurrentIndex(i1)
            self.ch2.setCurrentIndex(i2)
            self.all_t.setEnabled(item.nt > 1)
        for combo in (self.ch1, self.ch2):
            combo.blockSignals(False)
        self.records = list(item.coloc) if item is not None else []
        self._fill_table()

    def _default_channels(self, item, keep):
        n = len(item.channels)
        texts = [f'C{i}: {c}' for i, c in enumerate(item.channels)]
        if keep[0] in texts and keep[1] in texts and keep[0] != keep[1]:
            return texts.index(keep[0]), texts.index(keep[1])
        nuc = (item.roi_roles or {}).get('nuc')
        cand = [i for i in range(n) if i != nuc] or list(range(n))
        if len(cand) >= 2:
            return cand[0], cand[1]
        return 0, min(1, n - 1)

    def _channels_for(self, item):
        """The chosen channels, matched by name on another image."""
        if item is self.item:
            return self.ch1.currentData(), self.ch2.currentData()
        out = []
        for combo in (self.ch1, self.ch2):
            name = combo.currentText().split(': ', 1)[-1]
            idx = item.channels.index(name) if name in item.channels else combo.currentData()
            if idx is None or idx >= len(item.channels):
                return None
            out.append(idx)
        return tuple(out)

    # ---- running ------------------------------------------------------------

    def _jobs(self, item):
        """(label, region key, region name) for every ROI to measure."""
        jobs = []
        if self.whole.isChecked():
            jobs.append((0, 'image', 'image'))
        cells = item.cells
        if cells is not None and len(cells):
            ids = cells.ids()
            if self.selected_only.isChecked() and item is self.win.current:
                sel = self.win.roi_panel.selected
                ids = [l for l in ids if l == sel]
            for l in ids:
                for key, _, prefix in REGIONS:
                    if self.region_boxes[key].isChecked():
                        jobs.append((l, key, f'{prefix}{l:03d}'))
        return jobs

    def _volumes(self, item, c1, c2):
        if self.z_mode.currentData() == 'stack':
            data = item.image.data
            return data[c1], data[c2], f'Z stack ({item.nz})'
        p = item.planes()
        z = 'MIP' if item.z == 'mip' else ('mid' if item.z == 'mid' else f'z {int(item.z) + 1}')
        return p[c1], p[c2], z

    def _run(self, items) -> tuple[int, list[str]]:
        settings = self.settings()
        plan = []
        for it in items:
            chans = self._channels_for(it)
            jobs = self._jobs(it)
            if chans is None or not jobs:
                continue
            ts = list(range(it.nt)) if self.all_t.isChecked() and it.nt > 1 else [it.t]
            plan.append((it, chans, jobs, ts))
        total = sum(len(j) * len(ts) for _, _, j, ts in plan)
        if not total:
            return 0, []
        prog = QProgressDialog('Coloc 2 계산 중…', '취소', 0, total, self)
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(300)
        done, errors = 0, []
        for it, (c1, c2), jobs, ts in plan:
            start_t = it.t
            vt, type_warning = channel_value_type(it, c1, c2)
            n1, n2 = it.channels[c1], it.channels[c2]
            records = []
            try:
                for t in ts:
                    if prog.wasCanceled():
                        break
                    if t != it.t:
                        it.set_t(t)
                    a, b, plane = self._volumes(it, c1, c2)
                    for label, key, name in jobs:
                        if prog.wasCanceled():
                            break
                        prog.setLabelText(f'Coloc 2: {it.label} · {name}'
                                          + (f' · t {t + 1}' if len(ts) > 1 else ''))
                        prog.setValue(done)
                        QApplication.processEvents()
                        done += 1
                        mask = None if key == 'image' else region_mask(it.cells, label, key)
                        if mask is not None and not mask.any():
                            continue
                        try:
                            res = run_coloc2(a, b, mask, settings, vt, names=(n1, n2),
                                             mask_id=name)
                        except Exception as exc:
                            traceback.print_exc()
                            errors.append(f'{it.label} {name}: {exc}')
                            continue
                        if type_warning:
                            res.warnings.insert(0, ('Bit depth differs', type_warning))
                        npx = int(np.broadcast_to(mask, a.shape).sum()) if mask is not None \
                            else int(a.size)
                        records.append(ColocRecord(
                            it.label, it.image_id, it.source_name, t, plane, name,
                            REGION_NAMES.get(key, 'image'), label,
                            n1, n2, npx, res))
            finally:
                if it.t != start_t:
                    it.set_t(start_t)
                if it is not self.win.current:
                    it.image.release()
            it.coloc = records
            if prog.wasCanceled():
                break
        prog.setValue(total)
        return done, errors

    def run_current(self):
        it = self.win.current
        if it is None:
            return
        if not self._check(it):
            return
        self._run_and_report([it])

    def run_all(self):
        items = [it for it in self.win.items
                 if (it.cells is not None and len(it.cells)) or self.whole.isChecked()]
        if not items:
            QMessageBox.information(self, 'Coloc 2', 'ROI가 있는 이미지가 없습니다.')
            return
        self._run_and_report(items)

    def _check(self, it) -> bool:
        if self.ch1.currentData() == self.ch2.currentData():
            QMessageBox.information(self, 'Coloc 2', '서로 다른 두 채널을 고르세요.')
            return False
        if not self._jobs(it):
            QMessageBox.information(
                self, 'Coloc 2', '계산할 ROI가 없습니다. 세포질 ROI 탭에서 ROI를 검출하거나 불러오고, '
                                 'ROI 종류(세포 전체/세포질/핵)를 하나 이상 고르세요.')
            return False
        return True

    def _run_and_report(self, items):
        if self.ch1.currentData() == self.ch2.currentData():
            QMessageBox.information(self, 'Coloc 2', '서로 다른 두 채널을 고르세요.')
            return
        try:
            n, errors = self._run(items)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, 'Coloc 2 실패', str(exc))
            return
        self.bind(self.win.current)
        msg = f'Coloc 2: ROI {sum(len(it.coloc) for it in items)}개 계산'
        self.status(msg)
        if errors:
            QMessageBox.warning(self, 'Coloc 2', '일부 ROI는 계산하지 못했습니다:\n' + '\n'.join(errors[:20]))
        self.win.update_preview()

    # ---- results ----------------------------------------------------------------

    def _fill_table(self):
        heads = ['ROI', '시점'] + [h for h, _ in SUMMARY] + ['경고']
        self.table.blockSignals(True)
        self.table.clear()
        self.table.setColumnCount(len(heads))
        self.table.setHorizontalHeaderLabels(heads)
        self.table.setRowCount(len(self.records))
        for i, rec in enumerate(self.records):
            cells = [rec.roi, str(rec.t + 1)]
            for _, name in SUMMARY:
                v = rec.result.value(name, None)
                cells.append('' if v is None else d2s(v, 3))
            cells.append(str(len(rec.result.warnings)) if rec.result.warnings else '')
            for j, text in enumerate(cells):
                self.table.setItem(i, j, QTableWidgetItem(text))
        self.table.resizeColumnsToContents()
        self.table.blockSignals(False)
        if self.records:
            self.table.selectRow(0)
        else:
            self._show(None)

    def current_record(self) -> ColocRecord | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        i = rows[0].row()
        return self.records[i] if 0 <= i < len(self.records) else None

    def _row_selected(self):
        rec = self.current_record()
        self._show(rec)
        if rec is not None and rec.label and self.item is self.win.current:
            self.win.roi_panel.select(rec.label)

    def _show(self, rec):
        self.values.setRowCount(0)
        self.warn.setText('')
        prev = self.view.currentText()
        self.view.blockSignals(True)
        self.view.clear()
        if rec is not None:
            res = rec.result
            self.values.setRowCount(len(res.values))
            for i, (name, value, dec) in enumerate(res.values):
                self.values.setItem(i, 0, QTableWidgetItem(name))
                self.values.setItem(i, 1, QTableWidgetItem(d2s(value, dec)))
            if res.warnings:
                self.warn.setText('경고: ' + ' · '.join(w for w, _ in res.warnings))
                self.warn.setToolTip('\n\n'.join(f'{w}: {l}' for w, l in res.warnings))
            for h in res.histograms:
                self.view.addItem(h.title, ('hist', h))
            for title, img in res.images:
                self.view.addItem(title, ('image', img))
            # keep the plot chosen for the previous row, else the 2D histogram
            for want in (prev, '2D intensity histogram'):
                i = self.view.findText(want) if want else -1
                if i >= 0:
                    self.view.setCurrentIndex(i)
                    break
        self.view.blockSignals(False)
        self._draw()

    def _draw(self):
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        rec = self.current_record() if hasattr(self, 'table') else None
        data = self.view.currentData() if self.view.count() else None
        if rec is None or data is None:
            ax.set_axis_off()
            ax.text(0.5, 0.5, 'No Coloc 2 result', ha='center', va='center', color='0.5')
        else:
            draw_result(ax, rec, *data)
        self.plot.draw_idle()

    # ---- saving ------------------------------------------------------------------

    def save_csv(self):
        it = self.win.current
        if it is None or not it.coloc:
            QMessageBox.information(self, 'Coloc 2', '저장할 결과가 없습니다. 먼저 계산하세요.')
            return
        default = str(it.path.with_name(f'{item_stem(it)}_coloc2.csv'))
        path, _ = QFileDialog.getSaveFileName(self, 'Coloc 2 CSV 저장', default, 'CSV (*.csv)')
        if not path:
            return
        try:
            n = write_coloc_csv(path, it.coloc)
        except Exception as exc:
            QMessageBox.warning(self, '저장 실패', str(exc))
            return
        self.status(f'Coloc 2 결과 {n}행 저장: {path}')

    def save_all(self):
        items = [it for it in self.win.items if it.coloc]
        if not items:
            QMessageBox.information(self, 'Coloc 2', '저장할 결과가 없습니다. 먼저 계산하세요.')
            return
        out = QFileDialog.getExistingDirectory(self, 'Coloc 2 결과를 저장할 폴더')
        if not out:
            return
        per_image = self.win.opt_per_image.isChecked()
        records = []
        try:
            for it in items:
                if per_image:
                    write_coloc_csv(Path(out) / item_folder(it) / f'{item_stem(it)}_coloc2.csv',
                                    it.coloc)
                records += it.coloc
            n = write_coloc_csv(Path(out) / 'coloc2.csv', records)
        except Exception as exc:
            QMessageBox.warning(self, '저장 실패', str(exc))
            return
        QMessageBox.information(self, '저장 완료',
                                f'이미지 {len(items)}개의 Coloc 2 결과 {n}행을 저장했습니다.\n{out}')

    def _default(self, rec, suffix):
        it = self.win.current
        base = it.path.with_name(f'{item_stem(it)}_{rec.roi}_coloc2') if it else Path(rec.roi)
        return str(base) + suffix

    def save_plot(self):
        rec = self.current_record()
        data = self.view.currentData()
        if rec is None or data is None:
            QMessageBox.information(self, 'Coloc 2', '저장할 그래프가 없습니다.')
            return
        path, _ = QFileDialog.getSaveFileName(self, '그래프 저장', self._default(rec, '.png'),
                                              'PNG (*.png);;PDF (*.pdf);;SVG (*.svg);;TIFF (*.tif)')
        if not path:
            return
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure

        fig = Figure(figsize=(5, 4.5), dpi=300, layout='constrained')
        FigureCanvasAgg(fig)
        draw_result(fig.add_subplot(111), rec, *data)
        try:
            fig.savefig(path, dpi=300)
        except Exception as exc:
            QMessageBox.warning(self, '저장 실패', str(exc))

    def save_pdf(self):
        rec = self.current_record()
        if rec is None:
            QMessageBox.information(self, 'Coloc 2', '저장할 결과가 없습니다.')
            return
        path, _ = QFileDialog.getSaveFileName(self, 'PDF 리포트 저장', self._default(rec, '.pdf'),
                                              'PDF (*.pdf)')
        if not path:
            return
        try:
            save_pdf_report(path, rec)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, '저장 실패', str(exc))


def draw_result(ax, rec: ColocRecord, kind, obj):
    """A Coloc 2 histogram (log counts, regression line and thresholds on the
    2D intensity histogram) or a result image on a matplotlib Axes."""
    from matplotlib.colors import LogNorm

    ax.clear()
    if kind == 'image':
        ax.imshow(obj, cmap='gray', interpolation='nearest')
        ax.set_axis_off()
        ax.set_title(f'{rec.roi}', fontsize=9)
        return
    h = obj
    img = h.counts.T.astype(float)  # rows = y bins, row 0 = highest value
    ny, nx = img.shape
    if h.regression:
        x0, x1 = -0.5 / h.x_bin_width, (nx - 0.5) / h.x_bin_width
        y0, y1 = -0.5 / h.y_bin_width, (ny - 0.5) / h.y_bin_width
    else:
        x0, x1 = h.x_min, h.x_min + nx / h.x_bin_width
        y0, y1 = 0.0, ny / h.y_bin_width
    vmax = img.max()
    ax.imshow(np.where(img > 0, img, np.nan), extent=(x0, x1, y0, y1), origin='upper',
              aspect='auto', cmap='inferno', interpolation='nearest',
              norm=LogNorm(vmin=1, vmax=max(vmax, 1)))
    ax.set_facecolor('black')
    r = rec.result
    if h.regression and np.isfinite(r.slope):
        xs = np.array([x0, x1])
        ax.plot(xs, r.slope * xs + r.intercept, color='white', lw=1)
        ax.axvline(r.ch1_threshold, color='#4fc3f7', lw=0.8, ls='--')
        ax.axhline(r.ch2_threshold, color='#4fc3f7', lw=0.8, ls='--')
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_xlabel(h.x_label, fontsize=8)
    ax.set_ylabel(h.y_label, fontsize=8)
    ax.tick_params(labelsize=7)
    ax.set_title(f'{h.title} · {rec.roi}', fontsize=9)


def save_pdf_report(path, rec: ColocRecord):
    """Histograms/images on the first pages, all values and warnings on the last."""
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.figure import Figure

    res = rec.result
    with PdfPages(path) as pdf:
        for h in res.histograms:
            fig = Figure(figsize=(6, 5.5))
            draw_result(fig.add_subplot(111), rec, 'hist', h)
            pdf.savefig(fig)
        for title, img in res.images:
            fig = Figure(figsize=(6, 5.5))
            ax = fig.add_subplot(111)
            draw_result(ax, rec, 'image', img)
            ax.set_title(title, fontsize=9)
            pdf.savefig(fig)
        lines = [f'{rec.image}  ({rec.image_id})', f'ROI {rec.roi} · {rec.plane} · '
                 f'timepoint {rec.t + 1} · Ch1 {rec.ch1} · Ch2 {rec.ch2}', '']
        lines += [f'{n}: {d2s(v, dec)}' for n, v, dec in res.values]
        if res.warnings:
            lines += ['', 'Warnings:'] + [f'- {w}' for w, _ in res.warnings]
        per_page = 52
        for k in range(0, len(lines), per_page):
            fig = Figure(figsize=(8.27, 11.69))
            fig.text(0.06, 0.96, '\n'.join(lines[k:k + per_page]), va='top', ha='left',
                     fontsize=8, family='monospace')
            pdf.savefig(fig)
    return str(path)
