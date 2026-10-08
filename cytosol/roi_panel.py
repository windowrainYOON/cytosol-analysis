"""Cell / cytosol ROI tab of Cytosol Viewer: detection, editing, ImageJ ROI I/O."""

from __future__ import annotations

import csv
import re
import traceback
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
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
    QVBoxLayout,
    QWidget,
)

from .cellroi import CellRois, RoiParams, auto_saturation, merged_preview, segment_cells
from .lut import ImageItem, item_stem, match_channel

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
]
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
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.selected = 0
        self._busy = False

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
        self.sat.setSpecialValueText('자동')
        self.sat.setToolTip('배경 신호 채널을 이 값에서 흰색으로 포화시킵니다 (LUT를 밝게). '
                            '세포질 전체가 하나의 덩어리로 보이도록 낮추세요.')
        self.sat.valueChanged.connect(self._sat_changed)
        self.sat_auto_btn = QPushButton('자동값')
        self.sat_auto_btn.clicked.connect(lambda: self.sat.setValue(0))
        self.input_view = QCheckBox('검출용 합성 이미지 보기 (배경 밝게 + 핵)')
        self.input_view.toggled.connect(lambda _: self.win.update_preview())
        self.min_cell = QDoubleSpinBox()
        self.min_cell.setRange(1, 1e6)
        self.min_cell.setValue(RoiParams.min_cell_um2)
        self.min_cell.setSuffix(' µm²')
        self.min_nuc = QDoubleSpinBox()
        self.min_nuc.setRange(1, 1e6)
        self.min_nuc.setValue(RoiParams.min_nucleus_um2)
        self.min_nuc.setSuffix(' µm²')
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
        det = QGroupBox('자동 검출')
        dl = QFormLayout(det)
        row = QHBoxLayout()
        row.addWidget(self.sat, 1)
        row.addWidget(self.sat_auto_btn)
        dl.addRow('배경 포화값', row)
        dl.addRow(self.input_view)
        dl.addRow('최소 세포 크기', self.min_cell)
        dl.addRow('최소 핵 크기', self.min_nuc)
        dl.addRow('스무딩', self.smooth)
        dl.addRow('프레임에 걸친 세포', self.edge_combo)
        dl.addRow('안쪽 경계 여백', self.edge_margin)
        run_one = QPushButton('ROI 검출 (현재 이미지)')
        run_one.clicked.connect(self.detect_current)
        run_all = QPushButton('모든 이미지')
        run_all.setToolTip('같은 이름의 채널을 같은 역할로 모든 이미지에서 검출')
        run_all.clicked.connect(self.detect_all)
        row = QHBoxLayout()
        row.addWidget(run_one, 2)
        row.addWidget(run_all, 1)
        dl.addRow(row)

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
                      '오른쪽 버튼 드래그나 휠로 화면을 움직일 수 있습니다.')
        hint.setWordWrap(True)
        hint.setStyleSheet('color: gray;')
        el.addWidget(hint)

        # save / load
        self.save_cell = QCheckBox('세포 전체')
        self.save_cell.setChecked(True)
        self.save_nuc = QCheckBox('핵')
        self.save_nuc.setChecked(True)
        self.save_cyto = QCheckBox('세포질 (핵 제외)')
        self.save_cyto.setChecked(True)
        save_btn = QPushButton('ROI 저장…')
        save_btn.setToolTip('.zip: ImageJ RoiSet 하나로, .roi: ROI마다 .roi 파일 하나씩')
        save_btn.clicked.connect(self.save_current)
        load_btn = QPushButton('ROI 불러오기…')
        load_btn.clicked.connect(self.load_current)
        save_all = QPushButton('모든 이미지 ROI 저장 (폴더)…')
        save_all.clicked.connect(self.save_all)
        self.per_image = QCheckBox('이미지별 폴더에 나눠 저장')
        self.per_image.setChecked(True)
        self.per_image.setToolTip('폴더 안에 이미지마다 하위 폴더를 만들어 그 이미지의 파일을 넣습니다.')
        io = QGroupBox('ImageJ ROI 파일')
        il = QVBoxLayout(io)
        row = QHBoxLayout()
        row.addWidget(self.save_cell)
        row.addWidget(self.save_nuc)
        row.addWidget(self.save_cyto)
        il.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(save_btn)
        row.addWidget(load_btn)
        il.addLayout(row)
        il.addWidget(self.per_image)
        il.addWidget(save_all)

        lay = QVBoxLayout(self)
        lay.addWidget(roles)
        lay.addWidget(det)
        lay.addWidget(ed, 1)
        lay.addWidget(io)

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
            saturation=self.sat.value() or None,
            smooth_um=self.smooth.value(),
            min_cell_um2=self.min_cell.value(),
            min_nucleus_um2=self.min_nuc.value(),
            edge_mode=self.edge_combo.currentData(),
            edge_margin_um=self.edge_margin.value(),
        )

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
            if item.cells is not None and item.cells.saturation:
                self.sat.setValue(item.cells.saturation)
        self._busy = False
        self.selected = 0
        self.refresh_list()

    def _roles_changed(self, _):
        if self._busy or self.item is None:
            return
        self.item.roi_roles = {'nuc': self.nuc_combo.currentData(), 'bg': self.bg_combo.currentData()}
        if self.input_view.isChecked():
            self.win.update_preview()

    def _sat_changed(self, _):
        if self.input_view.isChecked():
            self.win.update_preview()

    def preview_rgb(self, item: ImageItem) -> np.ndarray:
        """What the detector sees: the background channel with a bright LUT plus nuclei."""
        r = self.roles(item)
        planes = item.planes()
        bg = planes[r['bg']]
        nuc = planes[r['nuc']] if r['nuc'] is not None else None
        sat = self.sat.value() or auto_saturation(bg, item.pixel_um or 0.1)
        return merged_preview(bg, nuc, sat)

    # ---- detection ------------------------------------------------------

    def _detect(self, item: ImageItem, roles: dict) -> CellRois:
        planes = item.planes()
        bg = planes[roles['bg']]
        nuc = planes[roles['nuc']] if roles['nuc'] is not None else None
        rois = segment_cells(bg, nuc, item.pixel_um, self.params())
        rois.renumber()
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
        msg = f'세포 {len(it.cells)}개 검출'
        if not self.sat.value():
            msg += f' (배경 포화값 자동: {it.cells.saturation:.3g})'
        if self.roles()['nuc'] is not None and it.cells.nuclei is None:
            msg += '. 핵 채널에서 핵을 찾지 못해 핵 없이 나눴습니다.'
        self.status(msg)
        self.selected = 0
        self.refresh_list()
        self.win.update_preview()

    def _confirm_replace(self):
        r = QMessageBox.question(self, 'ROI 다시 검출', '이 이미지의 ROI(수정 포함)를 새로 검출한 결과로 바꿀까요?')
        return r == QMessageBox.StandardButton.Yes

    def detect_all(self):
        src = self.item
        if src is None:
            return
        r = self.roles(src)
        jobs = []
        for it in self.win.items:
            bg = match_channel(it, src.channels[r['bg']], r['bg'], like=src)
            nuc = None
            if r['nuc'] is not None:
                nuc = match_channel(it, src.channels[r['nuc']], r['nuc'], like=src)
                if nuc is None:
                    continue
            if bg is None:
                continue
            jobs.append((it, {'nuc': nuc, 'bg': bg}))
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
        prog = QProgressDialog('ROI 검출 중…', '취소', 0, len(jobs), self.win)
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        errors, n = [], 0
        for i, (it, roles) in enumerate(jobs):
            if prog.wasCanceled():
                break
            prog.setLabelText(f'ROI 검출 중: {it.label}')
            prog.setValue(i)
            QApplication.processEvents()
            try:
                it.roi_roles = roles
                it.cells = self._detect(it, roles)
                n += 1
            except Exception as exc:
                errors.append(f'{it.label}: {exc}')
                traceback.print_exc()
        prog.setValue(len(jobs))
        skipped = len(self.win.items) - len(jobs)
        msg = f'이미지 {n}개에서 ROI를 검출했습니다.'
        if skipped:
            msg += f' (역할에 맞는 채널이 없거나 건너뛴 이미지 {skipped}개)'
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

    def draw_overlay(self, hidden=False):
        c = self.cells
        if hidden or c is None or not self.show_rois.isChecked():
            self.win.canvas.show_cells([], 0)
            return
        shapes = []
        for l in c.ids():
            xy = c.contour(l)
            if xy is None:
                continue
            nxy = c.nucleus_contour(l) if self.show_nuc.isChecked() else None
            shapes.append((l, xy, nxy, c.status.get(l, 'ok'), c.centroid(l)))
        self.win.canvas.show_cells(shapes, self.selected)

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
            h, w = it.image.data.shape[-2:]
            it.cells = CellRois(np.zeros((h, w), np.int32), None, it.pixel_um)
        return it.cells

    def _lasso(self, tool, pts):
        c = self._ensure_cells()
        if c is None:
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
            self.status(f'cell{l:03d} 추가')
        elif tool == 'add':
            l = self.selected
            if not l:
                ov = c.labels[mask]
                ov = ov[ov > 0]
                l = int(np.bincount(ov).argmax()) if len(ov) else 0
            if not l:
                l = c.new_cell(mask)
                self.selected = l
                self.status(f'선택한 세포가 없어 cell{l:03d}로 새로 추가했습니다.')
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

    def _save_kwargs(self):
        return dict(cells=self.save_cell.isChecked(), nuclei=self.save_nuc.isChecked(),
                    cytosol=self.save_cyto.isChecked())

    def _stem(self, item):
        return item_stem(item)

    def save_item(self, it, folder) -> list[dict]:
        """Write <stem>_RoiSet.zip into folder; returns the measurement rows."""
        it.cells.save(Path(folder) / f'{self._stem(it)}_RoiSet.zip', **self._save_kwargs())
        return [{'image': it.label, **r} for r in it.cells.measurements()]

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
            files = it.cells.save(path, **self._save_kwargs())
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
        if it.cells is not None and len(it.cells) and not self._confirm_load():
            return
        try:
            h, w = it.image.data.shape[-2:]
            it.cells = CellRois.load(files, (h, w), it.pixel_um)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, '불러오기 실패', str(exc))
            return
        self.selected = 0
        self.refresh_list()
        self.win.update_preview()
        self.status(f'세포 ROI {len(it.cells)}개 불러옴')

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
        for it in items:
            folder = Path(out) / self._stem(it) if per_image else Path(out)
            try:
                folder.mkdir(parents=True, exist_ok=True)
                item_rows = self.save_item(it, folder)
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
