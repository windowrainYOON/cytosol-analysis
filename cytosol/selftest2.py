"""Self-test steps of the features built from the 2026-11-14 proposals
(이미지 묶기, graph correlation tools, measurement data display, particle
tracking, mitoROI).  `selftest.run` calls them like its own steps."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np


def _app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([sys.argv[0]])


def _window():
    from .app import MainWindow

    app = _app()
    win = MainWindow()
    app.processEvents()
    return app, win


def _close(win):
    win.set_dirty(False)
    win.close()
    win.deleteLater()
    _app().processEvents()


def _rgb_tiffs(folder: Path, sample: str, seed=0) -> list[Path]:
    import tifffile

    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    out = []
    for k, col in enumerate(('Red', 'Green', 'Blue')):
        a = (rng.random((40, 48)) * 50 + 20 * k).astype(np.uint8)
        p = folder / f'{sample}_Ch{k + 1}_{col}.tif'
        tifffile.imwrite(p, a, imagej=True, resolution=(10.0, 10.0), metadata={'unit': 'um'})
        out.append(p)
    return out


def stacking_step(out: Path):
    """이미지 묶기: RGB splits stacked on load, the dialog for C / T stacks,
    the same naming pattern, 묶음 풀기, the project round trip."""
    from . import stacking
    from .stack_dialog import StackDialog

    app, win = _window()
    d = out / 'stacking'
    a = _rgb_tiffs(d, 'Control_01', 1)
    b = _rgb_tiffs(d, 'Control_02', 2)
    win.add_files(a)
    if len(win.items) != 1 or win.items[0].stack is None or len(win.items[0].channels) != 3:
        raise AssertionError(f'RGB set not stacked on load: {[it.label for it in win.items]}')
    st = win.items[0]
    if st.label != 'Control_01':
        raise AssertionError(f'stack name {st.label}')
    plane = st.planes()
    if plane.shape != (3, 40, 48):
        raise AssertionError(f'stack plane {plane.shape}')
    import tifffile
    if not np.array_equal(plane[1], tifffile.imread(a[1]).astype(np.float32)):
        raise AssertionError('stack channel 2 is not the Green file')
    # the tree shows the files greyed under the stack
    leaf = win.file_list.item(0)
    if leaf.childCount() != 3 or '(3채널)' not in leaf.text(0):
        raise AssertionError(f'tree row {leaf.text(0)} / {leaf.childCount()}')
    # 묶음 풀기, then the dialog with the same naming pattern
    win.unstack([st])
    if len(win.items) != 3 or any(it.stack for it in win.items):
        raise AssertionError('묶음 풀기')
    win.add_files(b, explicit=True)
    win.unstack([it for it in win.items if it.stack is not None])
    if len(win.items) != 6:
        raise AssertionError(f'items {len(win.items)}')
    items = [it for it in win.items if it.path in a]
    dlg = StackDialog(win, [it.path for it in items], [it.image for it in items],
                      [it.path for it in win.items if it not in items])
    if not dlg.more_sets or dlg.more_sets[0][0] != 'Control_02':
        raise AssertionError(f'same naming pattern {dlg.more_sets}')
    dlg.move_row(0, 2)  # order Green, Blue, Red
    specs = [dlg.spec()] + dlg.extra_specs()
    if [Path(s.path).name for s in specs[1].sources][0] != 'Control_02_Ch2_Green.tif':
        raise AssertionError('other set not in the dialog order')
    made = win.make_stacks(specs)
    if len(made) != 2 or len(win.items) != 2:
        raise AssertionError(f'make_stacks {len(made)} / {len(win.items)}')
    if made[0].channels[0] != 'Green':
        raise AssertionError(f'channel order {made[0].channels}')
    # T stack
    t_spec = stacking.StackSpec(axis='T', interval_s=5.0, name='time', fold=False,
                                sources=[stacking.StackSource(str(p)) for p in a])
    t_item = stacking.load_item(t_spec)
    if t_item.nt != 3 or t_item.image.times[2] != 10.0:
        raise AssertionError('T stack')
    t_item.set_t(2)
    if not np.array_equal(t_item.planes()[0], tifffile.imread(a[2]).astype(np.float32)):
        raise AssertionError('T stack plane 3')
    # mismatch
    import tifffile as tf
    odd = d / 'odd.tif'
    tf.imwrite(odd, np.zeros((30, 30), np.uint8))
    try:
        stacking.load_item(stacking.StackSpec(sources=[stacking.StackSource(str(a[0])),
                                                       stacking.StackSource(str(odd))]))
        raise AssertionError('different sizes stacked')
    except stacking.StackError:
        pass
    pad = stacking.load_item(stacking.StackSpec(mismatch='pad', sources=[
        stacking.StackSource(str(a[0])), stacking.StackSource(str(odd))]))
    if pad.planes().shape != (2, 40, 48):
        raise AssertionError('pad')
    # project round trip
    proj = d / 'stack.cyproj'
    win.write_project_to(proj)
    win.set_dirty(False)
    win.open_project(proj)
    if len(win.items) != 2 or win.items[0].stack is None or win.items[0].channels[0] != 'Green':
        raise AssertionError('stack not restored from the project')
    _close(win)
    app.processEvents()
    return '2 RGB sets stacked, dialog order, same pattern, T stack, pad, project'


def _cells_csv(path: Path, seed=0) -> Path:
    import csv

    rng = np.random.default_rng(seed)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['group', 'image', 'cell', 'm1', 'm2', 'm3'])
        for g in ('A', 'B', 'C'):
            for im in range(4):
                for c in range(15):
                    a = rng.normal()
                    w.writerow([g, f'{g}{im}', c, a, a * (1 if g == 'A' else -0.5) + rng.normal(), rng.random() + 1])
    return path


def graph_corr_step(out: Path):
    """그래프 창 상관 분석: 상관 행렬 / 상관 비교 equal to Mito Analyzer's
    stats (Pearson, Fisher z, Cochran Q), 점 하나 = 이미지 평균, a cell click
    makes the scatter with its regression, 그룹 요약표, the wizard's kinds."""
    from scipy import stats as SS

    from . import graph as G
    from . import graph_calc as GC

    app, win = _window()
    d = out / 'graph_corr'
    d.mkdir(parents=True, exist_ok=True)
    csvp = _cells_csv(d / 'cells.csv')
    gw = win.graph_window()
    wz = gw.start_wizard_csv(csvp, run=False)
    wz._kind('corr')
    if 'corr' not in wz.kinds.cards or 'corrcmp' not in wz.kinds.cards:
        raise AssertionError('new chart kinds missing from the wizard')
    doc = wz.finish()
    app.processEvents()
    tabs = gw.tables()
    t = tabs[gw.spec.mapping.table]
    res = G.corr_result(gw.spec, tabs)
    m1, m2 = t.numbers('m1'), t.numbers('m2')
    if res['xs'] != ['m1', 'm2', 'm3'] or abs(res['vals'][1, 0] - SS.pearsonr(m1, m2).statistic) > 1e-9:
        raise AssertionError(f'correlation matrix {res["xs"]} {res["vals"][1, 0]}')
    gw.render()
    if gw.art.get('corr') is None or len(G.plotted_table(gw.spec, tabs).rows) != 9:
        raise AssertionError('correlation matrix not drawn')
    # Spearman
    gw.spec.calc.method = 'rho'
    if abs(G.corr_result(gw.spec, tabs)['vals'][1, 0] - SS.spearmanr(m1, m2).statistic) > 1e-9:
        raise AssertionError('Spearman')
    gw.spec.calc.method = 'r'
    # 상관 비교 A vs B: Fisher z equals the formula
    gw.spec.chart = 'corrcmp'
    gw.spec.calc.group, gw.spec.calc.a, gw.spec.calc.b = 'group', 'A', 'B'
    res = G.corr_result(gw.spec, tabs)
    ga = [i for i, v in enumerate(t.values('group')) if v == 'A']
    gb = [i for i, v in enumerate(t.values('group')) if v == 'B']
    ra, rb = SS.pearsonr(m1[ga], m2[ga]).statistic, SS.pearsonr(m1[gb], m2[gb]).statistic
    z = (np.arctanh(rb) - np.arctanh(ra)) / np.sqrt(1 / (len(ga) - 3) + 1 / (len(gb) - 3))
    if abs(res['p_raw'][1, 0] - 2 * SS.norm.sf(abs(z))) > 1e-9 or res['p'][1, 0] != res['p_raw'][1, 0]:
        raise AssertionError('Fisher z')
    gw.spec.calc.correction = 'holm'
    if not np.allclose(G.corr_result(gw.spec, tabs)['p'], GC.holm(res['p_raw']), equal_nan=True):
        raise AssertionError('Holm')
    gw.spec.calc.correction = 'none'
    gw.spec.calc.compare = 'all'
    res = G.corr_result(gw.spec, tabs)
    if res['q_p'].shape != (3, 3) or not np.isfinite(res['q_p'][1, 0]):
        raise AssertionError('Cochran Q')
    gw.render()
    gw.spec.calc.compare = 'ab'
    gw.render()
    if len(gw.art.get('axes', [])) != 3:
        raise AssertionError('A / B / Δ panels')
    # 점 하나 = 이미지 평균
    gw.spec.mapping.unit = 'image'
    res = G.corr_result(gw.spec, tabs)
    if int(res['per']['A']['ns'][0, 0]) != 4:
        raise AssertionError(f'image means n {res["per"]["A"]["ns"][0, 0]}')
    gw.spec.mapping.unit = 'rows'
    # a cell click: the scatter with its regression
    gw.spec.chart = 'corr'
    gw.render()
    n = len(gw.docs)
    sc = gw.open_scatter('m1', 'm2')
    if len(gw.docs) != n + 1 or not sc.spec.calc.reg_on or sc.spec.chart != 'xy':
        raise AssertionError('scatter from a matrix cell')
    rows = G.regression_rows(gw.spec, gw.tables())
    if abs(rows[0]['r'] - SS.pearsonr(m1, m2).statistic) > 1e-9:
        raise AssertionError('regression r')
    gw.spec.calc.quadrant = 'median'
    gw.render()
    gw.reg_ed.refresh()
    if gw.reg_ed.isHidden():
        raise AssertionError('regression card hidden on XY')
    # 그룹 요약표
    summ = gw.group_summary(d / 'group_summary.csv', run=False)
    if summ is None or len(summ.rows) != 3 * 3 or not (d / 'group_summary.csv').exists():
        raise AssertionError(f'group summary {None if summ is None else len(summ.rows)}')
    # settings JSON keeps the new fields
    back = G.GraphSpec.from_dict(gw.spec.to_dict())
    if back.calc.quadrant != 'median' or not back.calc.reg_on:
        raise AssertionError('calc settings not saved')
    gw.remove_doc(sc)
    gw.remove_doc(doc)
    gw.hide()
    _close(win)
    return 'corr matrix = Pearson / Spearman, Fisher z, Holm, Cochran Q, image means, scatter + regression, summary'


STEPS = [
    ('image stacking', stacking_step),
    ('graph correlation', graph_corr_step),
]
