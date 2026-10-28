"""일괄 분석 (파일 메뉴): pick image groups and analyses with check boxes, run
them on every image of those groups in one go, review the results per image
(open an image to fix its ROIs in the feature's tab, then measure again) and
save only these results and settings.

Each analysis uses the settings of its own tab; the batch only decides which
analyses run on which images.  The state (steps, groups, per-image results)
is kept in MainWindow.batch, in projects and in batch settings files
(JSON, ``format: cytosol-viewer-batch``)."""

from __future__ import annotations

import json
import time
import traceback
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

FORMAT = 'cytosol-viewer-batch'
NO_GROUP = '(그룹 없음)'

# key, title, tab that holds its settings, tip
STEPS = [
    ('cells', '세포질 ROI 검출', 'roi_tab',
     '세포·핵·세포질 ROI를 세포질 ROI 탭의 설정(자동 / 수동 threshold, 크기 범위 …)으로 검출합니다.'),
    ('particles', '입자 ROI 검출', 'particle_tab',
     '입자 ROI 탭의 설정(채널, 찾을 영역, 자동 / 수동 threshold …)을 이미지마다 적용해 입자를 찾습니다.'),
    ('roi_measure', '세포질 ROI 강도 측정', 'roi_tab',
     '세포 / 핵 / 세포질 ROI의 강도 (ImageJ Measure 값)'),
    ('particle_measure', '입자 측정', 'particle_tab',
     '입자 ROI 탭의 측정 (세포별 또는 입자마다, 요약 포함)'),
    ('intensity', '강도 측정 (논리 영역)', 'intensity_tab',
     '강도 측정 탭의 영역식 (예: cyto - particle)으로 측정합니다.'),
    ('bands', '핵 → 세포막 등거리 띠', 'intensity_tab',
     '강도 측정 탭의 등거리 띠 설정으로 띠마다 측정합니다.'),
    ('coloc', 'Coloc 2', 'coloc_tab', 'Coloc 2 탭에서 고른 두 채널과 ROI 종류로 계산합니다.'),
    ('frap', 'FRAP 측정', 'frap_tab',
     '시간축이 있는 이미지마다 bleach / control / background ROI를 놓고 회복 곡선을 맞춥니다.'),
]
TITLES = {k: t for k, t, _, _ in STEPS}
TABS = {k: tab for k, _, tab, _ in STEPS}
DETECT = ('cells', 'particles')
# panel objects (MainWindow._panel_objects keys) whose settings a batch settings file keeps
PANELS = ('roi', 'roi_measure', 'particle', 'particle_measure', 'intensity',
          'intensity_measure', 'intensity_bands', 'coloc', 'frap')


@dataclass
class BatchState:
    steps: list = field(default_factory=list)     # STEPS keys, in STEPS order
    groups: list = field(default_factory=list)    # group names; '' = images without a group
    redo: bool = False                            # detect again where ROIs exist
    ran_at: str = ''
    images: list = field(default_factory=list)    # labels of the images it ran on
    results: dict = field(default_factory=dict)   # label -> {column: value}
    errors: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d) -> 'BatchState':
        d = d or {}
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


def is_batch_file(path) -> bool:
    try:
        return json.loads(Path(path).read_text(encoding='utf-8')).get('format') == FORMAT
    except Exception:
        return False


def group_key(it) -> str:
    return it.group or ''


def items_of(win, groups) -> list:
    groups = set(groups)
    return [it for it in win.items if group_key(it) in groups]


def ran_items(win, state) -> list:
    """The images the batch ran on that are still open."""
    labels = set(state.images)
    return [it for it in win.items if it.label in labels]


# ---- running ------------------------------------------------------------------

def _boxes(win) -> dict:
    return {'roi_measure': win.roi_panel.measure, 'particle_measure': win.particle_panel.measure,
            'intensity': win.intensity_panel.measure, 'bands': win.intensity_panel.bands_measure}


def _release(win, it):
    if it is not win.current:
        it.image.release()


def particle_count(win, it) -> int | None:
    pp = win.particle_panel
    cells = pp.cells_for(it)
    if it.particle_settings is None and it.particles is None:
        return None
    p = pp.particles_for(it)
    if p is None or cells is None or not len(cells):
        return 0
    return int(sum(p.counts(cells).values()))


def run(win, state: BatchState, items, detect=True) -> list[str]:
    """Run state's steps on items. detect=False keeps the ROIs as they are
    (edited) and only measures again. Results go into state.results."""
    errors = []
    res = {it.label: dict(state.results.get(it.label, {})) if not detect else {} for it in items}
    steps = state.steps
    rp, pp = win.roi_panel, win.particle_panel
    if 'cells' in steps and detect:
        src = win.current if win.current in items else items[0]
        jobs = [(it, roles) for it, roles in rp._jobs(src) if it in items]
        if not state.redo:
            jobs = [(it, ro) for it, ro in jobs if it.cells is None or not len(it.cells)]
        for it in items:
            if all(it is not j for j, _ in jobs) and (it.cells is None or not len(it.cells)):
                errors.append(f'{it.label}: 세포질 ROI 역할에 맞는 채널이 없습니다.')
        _, _, _, errs = rp.detect_jobs(jobs, rp._any_size_auto())
        errors += errs
    if 'particles' in steps:
        s = pp.settings() if detect else None
        for it in items:
            try:
                if s is not None and (state.redo or it.particle_settings is None):
                    if s.channel not in it.channels and s.index >= len(it.channels):
                        errors.append(f'{it.label}: 입자 채널 {s.channel}이 없습니다.')
                        continue
                    it.particle_settings = replace(s)
                    it.particles = None
                n = particle_count(win, it)
                if n is not None:
                    res[it.label]['particles'] = n
            except Exception as exc:
                traceback.print_exc()
                errors.append(f'{it.label} 입자: {exc}')
            finally:
                _release(win, it)
        pp._busy = True
        pp.part_on.setChecked(win.current is not None and win.current.particle_settings is not None)
        pp._busy = False
    for key, box in _boxes(win).items():
        if key not in steps:
            continue
        todo = [it for it in items if box.has_rois(it)]
        try:
            rows = box.measure_items(todo)
        except Exception as exc:
            traceback.print_exc()
            errors.append(f'{TITLES[key]}: {exc}')
            continue
        box.batch_rows = [r for it in todo for r in rows.get(id(it), [])]
        box.view.setCurrentIndex(box.view.findData('batch'))
        box._fill_table()
        for it in items:
            res[it.label][key] = len(rows.get(id(it), []))
    if 'coloc' in steps:
        cp = win.coloc_panel
        if cp.ch1.currentData() == cp.ch2.currentData():
            errors.append('Coloc 2: Coloc 2 탭에서 서로 다른 두 채널을 고르세요.')
        else:
            todo = [it for it in items if (it.cells is not None and len(it.cells))
                    or cp.whole.isChecked()]
            try:
                _, errs = cp._run(todo)
                errors += errs
            except Exception as exc:
                traceback.print_exc()
                errors.append(f'Coloc 2: {exc}')
            for it in todo:
                res[it.label]['coloc'] = len(it.coloc or [])
    if 'frap' in steps:
        fp = win.frap_panel
        try:
            for g in fp.groups(items=items):
                for c in g.members:
                    s = c.summary()
                    res.setdefault(c.label, {})['frap'] = _frap_text(s)
        except Exception as exc:
            traceback.print_exc()
            errors.append(f'FRAP: {exc}')
        for it in items:
            if it.nt < 2:
                res[it.label]['frap'] = 'T 없음'
    state.results.update(res)
    state.errors = errors
    win.coloc_panel.bind(win.current)
    win.roi_panel.refresh_list()
    pp.bind(win.current)
    win.frap_panel.forget()
    win.update_preview()
    return errors


def _frap_text(s) -> str:
    mf, th = s.get('mobile_fraction', np.nan), s.get('half_time_s', np.nan)
    if not np.isfinite(mf):
        return '피팅 실패'
    return f'Mf {mf:.3f}' + (f', t½ {th:.3g} s' if np.isfinite(th) else '')


def columns(state) -> list[tuple[str, str]]:
    """(result key, header) of the results table."""
    heads = {'cells': '세포 ROI', 'particles': '입자', 'roi_measure': '세포질 ROI 측정 (행)',
             'particle_measure': '입자 측정 (행)', 'intensity': '강도 측정 (행)',
             'bands': '등거리 띠 (행)', 'coloc': 'Coloc 2 (ROI)', 'frap': 'FRAP'}
    return [(k, heads[k]) for k, *_ in STEPS if k in state.steps]


def value(win, state, it, key):
    if key == 'cells':  # live: follows edits
        return len(it.cells) if it.cells is not None else 0
    if key == 'coloc' and it.coloc is not None:
        return len(it.coloc)
    return state.results.get(it.label, {}).get(key, '')


def table_rows(win, state) -> list[dict]:
    out = []
    for it in ran_items(win, state):
        row = {'group': it.group, 'image': it.label, 'image_id': it.image_id}
        for key, head in columns(state):
            row[head] = value(win, state, it, key)
        out.append(row)
    return out


# ---- saving -----------------------------------------------------------------------

def settings_dict(win, state) -> dict:
    from .project import widget_state

    objs = win._panel_objects()
    return {'format': FORMAT, 'version': 1,
            'steps': list(state.steps), 'groups': list(state.groups), 'redo': state.redo,
            'panels': {k: widget_state(objs[k], skip=('tool_btns',)) for k in PANELS},
            'measure_channels_off': {k: sorted(objs[k].channels_off) for k in PANELS
                                     if objs[k] in win._measure_boxes()}}


def apply_settings(win, d) -> BatchState:
    from .project import restore_widgets

    objs = win._panel_objects()
    for k in PANELS:
        restore_widgets(objs[k], (d.get('panels') or {}).get(k, {}))
    off = d.get('measure_channels_off') or {}
    for k in PANELS:
        if objs[k] in win._measure_boxes():
            objs[k].set_channels_off(off.get(k, ()))
    st = win.batch
    st.steps = [k for k, *_ in STEPS if k in (d.get('steps') or [])]
    st.groups = list(d.get('groups') or [])
    st.redo = bool(d.get('redo', False))
    return st


def save_settings(win, path):
    Path(path).write_text(json.dumps(settings_dict(win, win.batch), ensure_ascii=False, indent=1,
                                     default=str), encoding='utf-8')


def load_settings(win, path) -> BatchState:
    return apply_settings(win, json.loads(Path(path).read_text(encoding='utf-8')))


def save_results(win, out, state=None) -> tuple[list[str], list[str]]:
    """Only the batch's analyses of the batch's images, measured again so
    edits made since the run are in: per image a folder <stem>_<ID> and for
    the set the combined CSVs, summaries, batch_summary.csv and
    batch_settings.json. Returns (files written, errors)."""
    from .coloc_panel import write_coloc_csv
    from .groups import GROUP_FILE, write_groups
    from .intensity import write_rows
    from .lut import item_folder, item_stem
    from .roi_panel import write_csv

    state = state or win.batch
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    items = ran_items(win, state)
    steps = state.steps
    files, errors, cell_rows, coloc = [], [], [], []
    for it in items:
        folder = out / item_folder(it)
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if 'cells' in steps and it.cells is not None and len(it.cells):
                rows = win.roi_panel.save_item(it, folder)
                write_csv(folder / f'{item_stem(it)}_cell_rois.csv', rows)
                cell_rows += rows
                files.append(str(folder / f'{item_stem(it)}_cell_rois.csv'))
            if 'particles' in steps:
                pp = win.particle_panel
                cells = pp.cells_for(it)
                p = pp.particles_for(it) if cells is not None and len(cells) else None
                if p is not None and p.mask.any():
                    files += pp.save_particle_files(it, folder / f'{item_stem(it)}_particles.zip',
                                                    cells, p)
            if 'coloc' in steps and it.coloc:
                write_coloc_csv(folder / f'{item_stem(it)}_coloc2.csv', it.coloc)
                coloc += it.coloc
        except Exception as exc:
            traceback.print_exc()
            errors.append(f'{it.label}: {exc}')
        _release(win, it)
    if cell_rows:
        write_csv(out / 'cell_rois.csv', cell_rows)
        files.append(str(out / 'cell_rois.csv'))
    if coloc:
        write_coloc_csv(out / 'coloc2.csv', coloc)
        files.append(str(out / 'coloc2.csv'))
    for key, box in _boxes(win).items():
        if key not in steps:
            continue
        todo = [it for it in items if box.has_rois(it)]
        try:
            res = box.measure_items(todo)
        except Exception as exc:
            traceback.print_exc()
            errors.append(f'{TITLES[key]}: {exc}')
            continue
        rows = []
        for it in todo:
            item_rows = res.get(id(it), [])
            state.results.setdefault(it.label, {})[key] = len(item_rows)
            try:
                files += box.save_item(it, out / item_folder(it), item_rows)
            except Exception as exc:
                traceback.print_exc()
                errors.append(f'{it.label} {TITLES[key]}: {exc}')
            rows += item_rows
            _release(win, it)
        if write_rows(out / f'{box.suffix}.csv', rows):
            files.append(str(out / f'{box.suffix}.csv'))
        files += box.write_summaries(out, rows)
        box.batch_rows = rows
        box._fill_table()
    if 'frap' in steps:
        try:
            files += win.frap_panel.save_all(out, ask=False, items=items)
        except Exception as exc:
            traceback.print_exc()
            errors.append(f'FRAP: {exc}')
        win.frap_panel.forget()
    if write_groups(out / GROUP_FILE, items):
        files.append(str(out / GROUP_FILE))
    if write_rows(out / 'batch_summary.csv', table_rows(win, state)):
        files.append(str(out / 'batch_summary.csv'))
    d = settings_dict(win, state)
    d.update(ran_at=state.ran_at, images=state.images, errors=state.errors)
    (out / 'batch_settings.json').write_text(json.dumps(d, ensure_ascii=False, indent=1, default=str),
                                             encoding='utf-8')
    files.append(str(out / 'batch_settings.json'))
    return files, errors


# ---- dialogs ----------------------------------------------------------------------

class BatchDialog(QDialog):
    """Choose the groups and the analyses, then 실행."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        st = win.batch
        self.setWindowTitle('일괄 분석')
        lay = QVBoxLayout(self)
        intro = QLabel('그룹을 고르고 수행할 분석을 체크하면 그 그룹의 모든 이미지에 차례로 실행합니다. '
                       '각 분석의 세부 설정은 해당 탭의 현재 값을 씁니다 (실행 전에 탭에서 바꿀 수 있습니다). '
                       '실행 후 결과 창에서 이미지를 열어 ROI를 고치고 다시 측정할 수 있습니다.')
        intro.setWordWrap(True)
        lay.addWidget(intro)

        gbox = QGroupBox('이미지 그룹')
        gl = QVBoxLayout(gbox)
        self.group_list = QListWidget()
        counts = {}
        for it in win.items:
            counts[group_key(it)] = counts.get(group_key(it), 0) + 1
        chosen = set(st.groups) if st.groups else set(counts)
        for g in win.groups() + ([''] if '' in counts else []):
            li = QListWidgetItem(f'{g or NO_GROUP}  (이미지 {counts.get(g, 0)}개)')
            li.setData(Qt.ItemDataRole.UserRole, g)
            li.setFlags(li.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            li.setCheckState(Qt.CheckState.Checked if g in chosen else Qt.CheckState.Unchecked)
            self.group_list.addItem(li)
        self.group_list.setMaximumHeight(160)
        gl.addWidget(self.group_list)
        row = QHBoxLayout()
        for text, on in (('모두 선택', True), ('모두 해제', False)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, on=on: self._check_groups(on))
            row.addWidget(b)
        row.addStretch(1)
        gl.addLayout(row)
        if not win.groups():
            hint = QLabel('그룹이 없으면 모든 이미지가 ‘그룹 없음’에 들어갑니다. 왼쪽 목록의 그룹 지정… 으로 '
                          '이미지를 묶으면 그룹별로 고르고 요약할 수 있습니다.')
            hint.setWordWrap(True)
            gl.addWidget(hint)
        lay.addWidget(gbox)

        abox = QGroupBox('수행할 분석')
        al = QVBoxLayout(abox)
        self.step_boxes = {}
        default = st.steps or ['cells', 'roi_measure']
        for key, title, tab, tip in STEPS:
            cb = QCheckBox(title)
            cb.setToolTip(tip + f'\n설정: {win.tab_pages[tab][1]} 탭')
            cb.setChecked(key in default)
            al.addWidget(cb)
            self.step_boxes[key] = cb
        self.redo = QCheckBox('ROI가 이미 있는 이미지도 다시 검출 (수정한 ROI를 바꿉니다)')
        self.redo.setChecked(st.redo)
        al.addWidget(self.redo)
        tabs_btn = QPushButton('선택한 분석의 설정 탭 열기')
        tabs_btn.setToolTip('체크한 분석의 탭을 오른쪽에 열어 실행 전에 설정을 확인합니다.')
        tabs_btn.clicked.connect(self._open_tabs)
        al.addWidget(tabs_btn)
        lay.addWidget(abox)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.run_btn = bb.addButton('실행', QDialogButtonBox.ButtonRole.AcceptRole)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _check_groups(self, on):
        for i in range(self.group_list.count()):
            self.group_list.item(i).setCheckState(
                Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)

    def groups(self) -> list[str]:
        out = []
        for i in range(self.group_list.count()):
            li = self.group_list.item(i)
            if li.checkState() == Qt.CheckState.Checked:
                out.append(li.data(Qt.ItemDataRole.UserRole))
        return out

    def steps(self) -> list[str]:
        return [k for k, cb in self.step_boxes.items() if cb.isChecked()]

    def _open_tabs(self):
        for k in self.steps():
            self.win.show_tab(TABS[k], focus=False)

    def _accept(self):
        if not self.groups() or not self.steps():
            QMessageBox.information(self, '일괄 분석', '그룹과 분석을 하나 이상 고르세요.')
            return
        st = self.win.batch
        st.groups, st.steps, st.redo = self.groups(), self.steps(), self.redo.isChecked()
        self.accept()


class BatchResults(QDialog):
    """Results per image: double-click opens the image in the step's tab to
    fix it; 다시 측정 measures again keeping the edited ROIs."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle('일괄 분석 결과')
        self.resize(760, 460)
        lay = QVBoxLayout(self)
        self.head = QLabel()
        self.head.setWordWrap(True)
        lay.addWidget(self.head)
        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.cellDoubleClicked.connect(self.open_cell)
        lay.addWidget(self.table, 1)
        hint = QLabel('행을 두 번 누르면 그 이미지를 열고, 누른 열의 분석 탭으로 갑니다. '
                      'ROI나 설정을 고친 뒤 ‘다시 측정’을 누르면 고친 ROI 그대로 측정만 다시 합니다.')
        hint.setWordWrap(True)
        lay.addWidget(hint)
        row = QHBoxLayout()
        for text, fn, tip in (
                ('이미지 열기', self.open_selected, '선택한 이미지를 열어 고칩니다.'),
                ('다시 측정 (수정 반영)', self.remeasure, '검출은 다시 하지 않고 측정만 다시 합니다.'),
                ('전체 다시 실행…', win.batch_dialog, '분석과 그룹을 다시 골라 처음부터 실행합니다.'),
                ('결과 저장 (폴더)…', win.save_batch_results, '일괄 분석 결과와 설정만 저장합니다.')):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, fn=fn: fn())
            row.addWidget(b)
        row.addStretch(1)
        close = QPushButton('닫기')
        close.clicked.connect(self.close)
        row.addWidget(close)
        lay.addLayout(row)
        self.refresh()

    def refresh(self):
        st = self.win.batch
        items = ran_items(self.win, st)
        cols = columns(st)
        groups = ', '.join(g or NO_GROUP for g in st.groups)
        txt = (f'{st.ran_at} · 그룹 {groups} · 이미지 {len(items)}개 · 분석: '
               + ', '.join(TITLES[k] for k in st.steps)) if st.ran_at else '아직 실행하지 않았습니다.'
        if st.errors:
            txt += f'\n문제 {len(st.errors)}건: ' + '; '.join(st.errors[:5]) + (
                ' …' if len(st.errors) > 5 else '')
        self.head.setText(txt)
        self.table.clear()
        self.table.setColumnCount(2 + len(cols))
        self.table.setHorizontalHeaderLabels(['그룹', '이미지'] + [h for _, h in cols])
        self.table.setRowCount(len(items))
        self._items = items
        self._cols = cols
        for r, it in enumerate(items):
            vals = [it.group or NO_GROUP, it.label] + [value(self.win, st, it, k) for k, _ in cols]
            for c, v in enumerate(vals):
                cell = QTableWidgetItem(str(v))
                if c >= 2 and v in ('', 0):
                    cell.setForeground(Qt.GlobalColor.red)
                self.table.setItem(r, c, cell)

    def open_cell(self, row, col):
        if not 0 <= row < len(self._items):
            return
        it = self._items[row]
        if it in self.win.items:
            self.win.file_list.setCurrentRow(self.win.items.index(it))
        steps = self.win.batch.steps
        key = self._cols[col - 2][0] if col >= 2 else (steps[0] if steps else None)
        if key is not None:
            self.win.show_tab(TABS[key])

    def open_selected(self):
        rows = self.table.selectionModel().selectedRows()
        self.open_cell(rows[0].row() if rows else 0, 0)

    def remeasure(self):
        self.win.run_batch(detect=False)


def stamp() -> str:
    return time.strftime('%Y-%m-%d %H:%M')
