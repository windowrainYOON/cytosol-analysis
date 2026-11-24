"""미토 형태 (MiNA) tab (owner request 2026-11-24 10:45, pipeline design v3.2 /
v3.6): the MiNA skeleton measurement split from mitoROI. mitoROI finds the
mitochondria (detection); this tab measures their form on any mito object:
per cell (footprint, networks, branches, branch lengths, donuts: Mito
Analyzer's ``mina.analyze_cells`` unchanged, given the detected mask) and per
mito fragment (skeleton length, branches, junctions, end points, axes,
solidity, form factor). The numbers equal mitoROI's MiNA columns for the same
mask (Mito Analyzer 1.8 code in ``mitoan/``).
"""

from __future__ import annotations

import csv
import traceback
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QFormLayout, QGroupBox, QLabel, QVBoxLayout, QWidget

from . import theme

DATA_NAMES = {'cells': ('미토 형태 (MiNA) · 세포', '세포'), 'objects': ('미토 형태 (MiNA) · 미토 조각', '미토 조각')}
SOURCES = (('mito', 'mitoROI 미토 조각'),)
CELL_COLS = ('mitochondrial_footprint_um2', 'footprint_fraction', 'n_networks', 'n_branches',
             'total_branch_length_um', 'branch_length_mean_um', 'summed_branch_lengths_mean_um',
             'network_branches_mean', 'donuts')


@dataclass
class MinaResult:
    source: str = 'mito'
    cells: list = field(default_factory=list)
    objects: list = field(default_factory=list)


def object_rows(mlab, lab, red, px) -> list:
    """Skeleton measurements of every labelled mito object (Mito Analyzer
    ``mina.analyze_skeleton`` on each object, as mitoROI without a POI)."""
    from scipy import ndimage as ndi
    from skimage import measure, morphology

    from .mitoan import mina
    rows = []
    for mr in measure.regionprops(np.asarray(mlab, int), intensity_image=red):
        obj = mr.image
        cid = int(lab[mr.slice][obj][0]) if lab is not None else 0
        edges, _ng, _br, _summed, donuts, e_, j_ = mina.analyze_skeleton(
            np.pad(morphology.skeletonize(obj, method='lee').astype(bool), 1), px)
        major, minor = max(mr.axis_major_length, 1.0), max(mr.axis_minor_length, 1.0)
        rows.append(dict(
            mito=f'm{mr.label:04d}', cell=f'cell{cid:02d}' if cid else '', area_um2=mr.area * px * px,
            length_um=float(sum(e[3] for e in edges)), n_branches=len(edges),
            n_junctions=int(ndi.label(j_, structure=np.ones((3, 3)))[1]), n_endpoints=int(e_.sum()),
            donut=bool(donuts), major_axis_um=major * px, minor_axis_um=minor * px, aspect_ratio=major / minor,
            solidity=mr.solidity, form_factor=(mr.perimeter * px) ** 2 / (4 * np.pi * mr.area * px * px),
            red_mean=float(mr.intensity_mean), centroid_x=mr.centroid[1], centroid_y=mr.centroid[0]))
    return rows


def measure(item, source='mito') -> MinaResult:
    """MiNA on the item's mito objects (mitoROI's detected mask)."""
    from .mitoan import REF_PX_UM, mina
    res = getattr(item, 'mito', None)
    if res is None or not getattr(res, 'layers', None) or res.layers.get('mito') is None:
        raise ValueError('미토 ROI가 없습니다. mitoROI 탭에서 먼저 미토콘드리아를 찾으세요.')
    if item.cells is None or not len(item.cells):
        raise ValueError('세포 ROI가 없습니다.')
    ch = res.settings.get('mito_channel') or item.channels[0]
    red = np.asarray(item.planes()[list(item.channels).index(ch) if ch in item.channels else 0], float)
    lab = np.asarray(item.cells.labels, np.int32)
    mask = np.asarray(res.layers['mito'], bool)
    px = float(item.pixel_um or REF_PX_UM)
    done = [r.get('cell') for r in res.cells]
    rois = [dict(roi=c, status='ok') for c in done if c]
    rows, *_ = mina.analyze_cells(red, lab, rois, px, None, True, log=lambda m: None,
                                  mask_fn=lambda cell: (cell & mask, {}))
    mlab = res.mlab if res.mlab is not None else None
    if mlab is None:
        from skimage import measure as skm
        mlab = skm.label(mask, connectivity=2)
    return MinaResult(source, rows, object_rows(mlab, lab, red, px))


def write_csv(path, rows) -> bool:
    if not rows:
        return False
    cols = list(dict.fromkeys(k for r in rows for k in r))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: (f'{v:.4f}' if isinstance(v, float) else v) for k, v in r.items()})
    return True


class MinaPanel(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.item = None
        lay = QVBoxLayout(self)
        h = QLabel('mitoROI 탭이 찾은 미토콘드리아(미토 ROI)의 형태를 MiNA로 잽니다: 세포마다 footprint, 네트워크, '
                   '가지 수 · 길이, 도넛, 조각마다 골격 길이 · 가지 · 분기점 · 끝점 · 축 · solidity. Mito Analyzer '
                   '1.8과 같은 코드이며, 실행은 아래 측정 바에서 합니다.')
        h.setWordWrap(True)
        theme.hint(h)
        lay.addWidget(h)
        box = QGroupBox('1  대상 object')
        f = QFormLayout(box)
        self.source = QComboBox()
        for k, name in SOURCES:
            self.source.addItem(name, k)
        self.source.setToolTip('형태를 잴 미토 object. 파이프라인에서 연산으로 만든 미토 object도 고를 수 있습니다.')
        f.addRow('미토 object', self.source)
        self.state = theme.StatusLabel('', 'info')
        f.addRow(self.state)
        lay.addWidget(box)
        box2 = QGroupBox('2  측정 항목')
        v = QVBoxLayout(box2)
        cols = QLabel('세포: ' + ', '.join(CELL_COLS) + '\n조각: length_um, n_branches, n_junctions, n_endpoints, '
                      'donut, major / minor axis, aspect_ratio, solidity, form_factor')
        cols.setWordWrap(True)
        theme.hint(cols)
        v.addWidget(cols)
        self.result = theme.StatusLabel('', None)
        v.addWidget(self.result)
        lay.addWidget(box2)
        lay.addStretch()

    # ---- running ------------------------------------------------------------

    def status(self, msg):
        self.win.statusBar().showMessage(msg)

    def run(self, it) -> MinaResult:
        return measure(it, self.source.currentData() or 'mito')

    def run_current(self, item=None):
        it = item or self.win.current
        if it is None:
            return None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            it.mina = self.run(it)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self.status(f'미토 형태 (MiNA) 실패: {exc}')
            return None
        finally:
            QApplication.restoreOverrideCursor()
        self.status(f'미토 형태 (MiNA) ({it.label}): 세포 {len(it.mina.cells)}개, 조각 {len(it.mina.objects)}개')
        self._after()
        return it.mina

    def run_all(self):
        done = 0
        for it in list(self.win.items):
            if getattr(it, 'mito', None) is None:
                continue
            try:
                it.mina = self.run(it)
                done += 1
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                self.status(f'{it.label}: 미토 형태 (MiNA) 실패 ({exc})')
            QApplication.processEvents()
        self.status(f'미토 형태 (MiNA): 이미지 {done}개를 측정했습니다.' if done else
                    '미토 형태 (MiNA): 미토 ROI가 있는 이미지가 없습니다.')
        self._after()
        return done

    def _after(self):
        self.win.set_dirty(True)
        self.refresh()
        self.win.update_tab_badges()
        self.win.live_box.schedule()

    def bar_status(self):
        n = sum(1 for it in self.win.items if getattr(it, 'mito', None) is not None)
        if not n:
            return 'mitoROI 탭에서 먼저 미토콘드리아를 찾으세요.', 'warning'
        return f'미토 ROI가 있는 이미지 {n}개', None

    # ---- view ---------------------------------------------------------------

    def bind(self, item):
        self.item = item
        self.refresh()

    def refresh(self):
        it = self.item
        mito = getattr(it, 'mito', None) if it is not None else None
        r = getattr(it, 'mina', None) if it is not None else None
        if it is None:
            self.state.set_kind('info')
            self.state.setText('이미지가 없습니다.')
        elif mito is None:
            self.state.set_kind('warning')
            self.state.setText('미토 ROI가 없습니다. mitoROI 탭에서 먼저 미토콘드리아를 찾으세요.')
        else:
            self.state.set_kind('success')
            self.state.setText(f'미토 조각 {len(mito.mito):,}개 · 세포 {len(mito.cells)}개')
        if r is not None:
            self.result.set_kind('success')
            self.result.setText(f'측정함: 세포 {len(r.cells)}개, 조각 {len(r.objects):,}개')
        else:
            self.result.set_kind(None)
            self.result.setText('아직 측정하지 않았습니다.')

    def data_tables(self):
        out = {k: [] for k in DATA_NAMES}
        for it in self.win.items:
            r = getattr(it, 'mina', None)
            if r is None:
                continue
            head = {'image': it.label, 'image_id': it.image_id, 'group': it.group or ''}
            for k in DATA_NAMES:
                out[k] += [{**head, **row} for row in getattr(r, k)]
        return [(DATA_NAMES[k][0], DATA_NAMES[k][1], out[k]) for k in DATA_NAMES]

    def save_item(self, it, folder: Path, stem: str) -> list:
        r = getattr(it, 'mina', None)
        if r is None:
            return []
        files = []
        for k, suffix in (('cells', 'mina_per_cell'), ('objects', 'mina_per_mito')):
            p = Path(folder) / f'{stem}_{suffix}.csv'
            if write_csv(p, getattr(r, k)):
                files.append(p)
        return files


def mina_live(panel):
    it = panel.item
    r = getattr(it, 'mina', None) if it is not None else None
    if r is None:
        return None
    nets = [x.get('n_networks') for x in r.cells if x.get('n_networks') is not None]
    lens = [x.get('length_um') for x in r.objects]
    return [('세포', len(r.cells)), ('조각', len(r.objects)),
            ('네트워크 평균', f'{np.mean(nets):.2f}' if nets else '–'),
            ('조각 길이 평균 (µm)', f'{np.mean(lens):.2f}' if lens else '–')]
