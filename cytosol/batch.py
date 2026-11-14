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

from . import theme

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
    ('bands', '핵 → 세포막 등거리 띠', 'bands_tab',
     '등거리 띠 탭의 설정으로 띠마다 측정합니다.'),
    ('coloc', 'Coloc 2', 'coloc_tab', 'Coloc 2 탭에서 고른 두 채널과 ROI 종류로 계산합니다.'),
    ('frap', 'FRAP 측정', 'frap_tab',
     '시간축이 있는 이미지마다 bleach / control / background ROI를 놓고 회복 곡선을 맞춥니다.'),
    ('track', '입자 추적', 'track_tab',
     '시간축이 있는 이미지마다 입자 추적 탭의 설정으로 입자를 찾고 프레임 사이를 잇습니다.'),
    ('mito', 'mitoROI', 'mito_tab',
     '세포 ROI가 있는 이미지마다 mitoROI 탭의 설정으로 미토콘드리아와 관심 단백질을 측정합니다.'),
]
TITLES = {k: t for k, t, _, _ in STEPS}
TABS = {k: tab for k, _, tab, _ in STEPS}
DETECT = ('cells', 'particles')
# panel objects (MainWindow._panel_objects keys) whose settings a batch settings file keeps
PANELS = ('roi', 'roi_measure', 'particle', 'particle_measure', 'intensity',
          'intensity_measure', 'intensity_bands', 'bands', 'coloc', 'frap', 'track', 'mito')


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
            'intensity': win.intensity_panel.measure, 'bands': win.bands_panel.bands_measure}


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
        box._measured = {}
        box._remember([it for it in todo if id(it) in rows])
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
    if 'track' in steps:
        tp = win.track_panel
        for it in items:
            if it.nt < 2:
                res[it.label]['track'] = 'T 없음'
                continue
            if not detect and it.tracks is not None:
                res[it.label]['track'] = f'트랙 {len(it.tracks.tracks())}'
                continue
            try:
                it.tracks = tp.run(it)
                res[it.label]['track'] = f'트랙 {len(it.tracks.tracks())}'
            except Exception as exc:
                traceback.print_exc()
                errors.append(f'{it.label} 입자 추적: {exc}')
            _release(win, it)
        tp.refresh()
    if 'mito' in steps:
        mp = win.mito_panel
        for it in items:
            if it.cells is None or not len(it.cells):
                res[it.label]['mito'] = '세포 ROI 없음'
                continue
            try:
                it.mito = mp.run(it)
                res[it.label]['mito'] = f'세포 {len(it.mito.cells)}'
            except Exception as exc:
                traceback.print_exc()
                errors.append(f'{it.label} mitoROI: {exc}')
            _release(win, it)
        mp.refresh()
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
             'bands': '등거리 띠 (행)', 'coloc': 'Coloc 2 (ROI)', 'frap': 'FRAP',
             'track': '입자 추적', 'mito': 'mitoROI'}
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
    if 'track' in steps:
        for it in items:
            if it.tracks is not None and it.tracks.points:
                try:
                    files += win.track_panel.save_item(it, out / item_folder(it), item_stem(it))
                except Exception as exc:
                    traceback.print_exc()
                    errors.append(f'{it.label} 입자 추적: {exc}')
    if 'mito' in steps:
        for it in items:
            if getattr(it, 'mito', None) is not None:
                try:
                    files += [str(f) for f in win.mito_panel.save_item(it, out / item_folder(it), item_stem(it))]
                except Exception as exc:
                    traceback.print_exc()
                    errors.append(f'{it.label} mitoROI: {exc}')
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
    """측정 현황 · 일괄 분석 (owner decision 2026-11-14; replaces the 일괄
    분석 결과 window): images by group × every data table of the tabs, each
    cell 최신 / 설정 바뀜 / empty.  Double-click opens the image in that tab,
    right-click measures that cell again; the toolbar picks groups and
    analyses, runs the batch and measures again what changed."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle('측정 현황 · 일괄 분석')
        self.resize(900, 520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        bar = QHBoxLayout()
        self.pick_btn = QPushButton('그룹 · 분석 고르기…')
        self.pick_btn.setToolTip('일괄 분석할 그룹과 분석을 고르고 실행합니다.')
        self.pick_btn.clicked.connect(lambda: win.batch_dialog())
        bar.addWidget(self.pick_btn)
        self.run_btn = QPushButton('일괄 분석 실행')
        self.run_btn.setToolTip('고른 그룹 · 분석으로 처음부터 실행합니다 (검출 포함).')
        self.run_btn.clicked.connect(self.run)
        bar.addWidget(self.run_btn)
        self.stale_btn = QPushButton('바뀐 것 다시 측정')
        theme.prominent(self.stale_btn)
        self.stale_btn.setToolTip('ROI나 측정 항목이 바뀐 이미지만 다시 잽니다 (검출은 그대로).')
        self.stale_btn.clicked.connect(self.remeasure_stale)
        bar.addWidget(self.stale_btn)
        bar.addStretch(1)
        exp = QPushButton('내보내기…')
        exp.clicked.connect(lambda: win.export_dialog('batch'))
        bar.addWidget(exp)
        lay.addLayout(bar)
        self.head = QLabel()
        self.head.setWordWrap(True)
        theme.secondary(self.head)
        lay.addWidget(self.head)
        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.cellDoubleClicked.connect(self.open_cell)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.table, 1)
        hint = QLabel('칸을 두 번 누르면 그 이미지를 그 탭에서 엽니다. 오른쪽 클릭: 그 칸만 다시 측정.')
        hint.setWordWrap(True)
        theme.hint(hint)
        lay.addWidget(hint)
        self.refresh()

    def _boxes(self):
        w = self.win
        return [('roi', '세포질 ROI', w.roi_panel.measure), ('particle', '입자 ROI', w.particle_panel.measure),
                ('intensity', '강도 측정', w.intensity_panel.measure),
                ('bands', '등거리 띠', w.bands_panel.bands_measure)]

    TAB_OF = {'roi': 'roi_tab', 'particle': 'particle_tab', 'intensity': 'intensity_tab', 'bands': 'bands_tab',
              'coloc': 'coloc_tab'}

    def refresh(self):
        st = self.win.batch
        items = sorted(self.win.items, key=lambda it: (it.group or '~', self.win.items.index(it)))
        cols = [(key, box.data_name(), box) for key, _f, box in self._boxes()]
        cols.append(('coloc', 'Coloc 2 · ROI', None))
        stale = {key: {id(it) for it in box.stale_items()} for key, _f, box in self._boxes()}
        n_stale = sum(len(v) for v in stale.values())
        self.stale_btn.setText(f'바뀐 것 다시 측정 ({n_stale})')
        self.stale_btn.setEnabled(bool(n_stale))
        self.run_btn.setEnabled(bool(st.steps))
        txt = (f'일괄 분석 {st.ran_at} · 그룹 ' + ', '.join(g or NO_GROUP for g in st.groups) + ' · 분석: '
               + ', '.join(TITLES[k] for k in st.steps)) if st.ran_at else '일괄 분석은 아직 실행하지 않았습니다.'
        if st.errors:
            txt += f'\n문제 {len(st.errors)}건: ' + '; '.join(st.errors[:5]) + (' …' if len(st.errors) > 5 else '')
        self.head.setText(txt)
        self.table.clear()
        self.table.setColumnCount(2 + len(cols))
        self.table.setHorizontalHeaderLabels(['그룹', '이미지'] + [name for _k, name, _b in cols])
        self.table.setRowCount(len(items))
        self._items, self._cols = items, cols
        for r, it in enumerate(items):
            self.table.setItem(r, 0, QTableWidgetItem(it.group or NO_GROUP))
            self.table.setItem(r, 1, QTableWidgetItem(it.label))
            for c, (key, _name, box) in enumerate(cols):
                if box is not None:
                    n = sum(1 for row in box.batch_rows if row.get('image_id') == it.image_id)
                    bad = id(it) in stale.get(key, set())
                else:
                    n, bad = len(it.coloc or []), False
                text = '설정 바뀜' if n and bad else (f'최신 · {n}행' if n else '')
                cell = QTableWidgetItem(text)
                if n:
                    cell.setIcon(theme.status_icon('warning' if bad else 'success'))
                self.table.setItem(r, 2 + c, cell)

    def open_cell(self, row, col):
        if not 0 <= row < len(self._items):
            return
        it = self._items[row]
        if it in self.win.items:
            self.win.file_list.setCurrentRow(self.win.items.index(it))
        key = self._cols[col - 2][0] if col >= 2 else None
        if key is None:
            steps = self.win.batch.steps
            if steps:
                self.win.show_tab(TABS[steps[0]])
            return
        self.win.show_tab(self.TAB_OF[key])

    def remeasure_cell(self, row, col):
        if not (0 <= row < len(self._items)) or col < 2:
            return
        it = self._items[row]
        key, _name, box = self._cols[col - 2]
        if box is None:
            return
        if not box.has_rois(it):
            return
        res = box.measure_items([it])
        box._merge([it], res)
        box._fill_table()
        self.refresh()

    def _menu(self, pos):
        idx = self.table.indexAt(pos)
        if not idx.isValid() or idx.column() < 2:
            return
        from PySide6.QtWidgets import QMenu

        m = QMenu(self)
        m.addAction('이 칸만 다시 측정', lambda: self.remeasure_cell(idx.row(), idx.column()))
        m.addAction('이 이미지를 이 탭에서 열기', lambda: self.open_cell(idx.row(), idx.column()))
        m.exec(self.table.viewport().mapToGlobal(pos))

    def remeasure_stale(self) -> int:
        n = 0
        for _key, _f, box in self._boxes():
            n += box.update_stale()
        self.refresh()
        return n

    def run(self):
        if not self.win.batch.steps:
            self.win.batch_dialog()
        else:
            self.win.run_batch()

    def open_selected(self):
        idx = self.table.currentIndex()
        self.open_cell(idx.row() if idx.isValid() else 0, idx.column() if idx.isValid() else 0)

    def remeasure(self):
        self.win.run_batch(detect=False)


def stamp() -> str:
    return time.strftime('%Y-%m-%d %H:%M')
