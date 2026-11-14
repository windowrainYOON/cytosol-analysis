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


def _cell_tiff(path: Path, seed=0) -> Path:
    """Two-channel image with three bright cells (channel 1) and spots (channel 2)."""
    import tifffile

    rng = np.random.default_rng(seed)
    a = np.zeros((2, 80, 120), np.uint16)
    yy, xx = np.mgrid[:80, :120]
    for cx in (25, 60, 95):
        d = (xx - cx) ** 2 + (yy - 40) ** 2
        a[0][d < 15 ** 2] = 800
        a[1][d < 15 ** 2] = 200
        for _ in range(4):
            px, py = cx + rng.integers(-8, 9), 40 + rng.integers(-8, 9)
            a[1][(xx - px) ** 2 + (yy - py) ** 2 < 4] = 2000
    a = (a + rng.integers(0, 30, a.shape)).astype(np.uint16)
    tifffile.imwrite(path, a, imagej=True, resolution=(5.0, 5.0), metadata={'unit': 'um', 'axes': 'CYX'})
    return path


def _cells_of(it):
    from .cellroi import CellRois

    lab = np.zeros(it.image.shape[-2:], np.int32)
    yy, xx = np.mgrid[:lab.shape[0], :lab.shape[1]]
    for k, cx in enumerate((25, 60, 95), 1):
        lab[(xx - cx) ** 2 + (yy - 40) ** 2 < 15 ** 2] = k
    nuc = np.where((xx % 1 == 0) & (lab > 0) & (((xx - 25) % 35) ** 2 + (yy - 40) ** 2 < 25), lab, 0).astype(np.int32)
    return CellRois(lab, nuc, it.pixel_um)


def data_display_step(out: Path):
    """측정 데이터 표시 통일: 측정 항목 / 데이터 cards (no inspector table,
    no auto refresh), data names, 설정 바뀜 and re-measuring only the changed
    images, the tab chip dot, the ROI hover values, the live box, the graph
    window 데이터 list + 열 설명, the 측정 현황 · 일괄 분석 window."""
    from . import graph as G

    app, win = _window()
    win.show()
    d = out / 'data_display'
    d.mkdir(parents=True, exist_ok=True)
    win.add_files([_cell_tiff(d / 'a.tif', 1), _cell_tiff(d / 'b.tif', 2)], explicit=True)
    for it in win.items:
        it.cells = _cells_of(it)
    win.file_list.setCurrentRow(0)
    win.show_tab('roi_tab')
    app.processEvents()
    box = win.roi_panel.measure
    if box.table.isVisible() or box.view.isVisible() or box.auto.isChecked():
        raise AssertionError('inspector result table still shown')
    if box.data_name() != '세포질 ROI · 세포' or win.particle_panel.measure.data_name('group') != '입자 ROI · 그룹 요약':
        raise AssertionError(f'data names {box.data_name()}')
    box.measure_all()
    n0 = len(box.batch_rows)
    if not n0 or box.stale_items() or len({r['image_id'] for r in box.batch_rows}) != 2:
        raise AssertionError(f'measure all: {n0} rows, stale {box.stale_items()}')
    # the chip dot and its tool tip
    win.update_tab_badges()
    i = win.right_tabs.indexOf(win.tab_pages['roi_tab'][0])
    if not win.right_tabs.badge(i) or '세포질 ROI' not in win.right_tabs._chips()[i].toolTip():
        raise AssertionError('tab chip dot')
    # a changed ROI marks that image only; the graph window re-measures it
    second = win.items[1]
    second.cells = _cells_of(second)
    second.cells.labels[second.cells.labels == 3] = 0
    if [it.label for it in box.stale_items()] != [second.label]:
        raise AssertionError(f'stale images {[it.label for it in box.stale_items()]}')
    box._fill_table()
    if '다시 측정' not in box.state.text():
        raise AssertionError(f'state line {box.state.text()}')
    gw = win.graph_window()
    gw.refresh_chips()
    names = [gw.data_list.topLevelItem(k).text(0) for k in range(gw.data_list.topLevelItemCount())]
    if '세포질 ROI' not in names or names[-1] != 'CSV 불러오기…':
        raise AssertionError(f'graph window data list {names}')
    wz = gw.start_data('세포질 ROI · 세포', run=False)
    if box.stale_items() or len([r for r in box.batch_rows if r['image_id'] == second.image_id]) * 3 != \
            len([r for r in box.batch_rows if r['image_id'] == win.items[0].image_id]) * 2:
        raise AssertionError('stale image not measured again when the table was opened')
    doc = wz.finish()
    if gw.spec.mapping.table != '세포질 ROI · 세포' or '세포질 ROI · 세포' not in gw.data_head.text():
        raise AssertionError(f'wizard table {gw.spec.mapping.table} / {gw.data_head.text()}')
    k = gw.table_pick.findText('열 설명: 세포질 ROI · 세포')
    gw.table_pick.setCurrentIndex(k)
    t = gw.shown_table()
    if k < 0 or t.columns[:2] != ['열', '표시 이름'] or not any('평균 세기' in str(r[4]) for r in t.rows):
        raise AssertionError('열 설명')
    gw.remove_doc(doc)
    gw.hide()
    # hover values of the ROI under the cursor
    txt = win.roi_panel.hover_values(1)
    if 'Mean' not in txt:
        raise AssertionError(f'hover values {txt!r}')
    # live box under the canvas follows the tab
    win.live_box.refresh()
    vals = win.live_box.values()
    if not win.live_box.isVisible() or vals.get('세포') != 3:
        raise AssertionError(f'live box {vals}')
    win.show_tab('frap_tab')
    app.processEvents()
    win.live_box.refresh()
    if win.live_box.plots.currentWidget() is not win.frap_panel.plot:
        raise AssertionError('FRAP curve not in the live box')
    win.show_tab('stack_tab')
    win.live_box.refresh()
    if win.live_box.isVisible():
        raise AssertionError('live box shown for a tab without one')
    # 측정 현황 · 일괄 분석
    win.show_batch_results()
    ov = win.batch_win
    col = 2 + [c[0] for c in ov._cols].index('roi')
    if ov.table.rowCount() != 2 or '최신' not in ov.table.item(0, col).text():
        raise AssertionError('measurement overview')
    second.cells.labels[second.cells.labels == 2] = 0
    ov.refresh()
    if ov.table.item(1, col).text() != '설정 바뀜' or '(1)' not in ov.stale_btn.text():
        raise AssertionError(f'overview stale {ov.table.item(1, col).text()} {ov.stale_btn.text()}')
    if ov.remeasure_stale() != 1 or box.stale_items():
        raise AssertionError('overview re-measure')
    ov.close()
    box.batch_rows = []
    _close(win)
    return f'{n0} rows, stale = 1 image, data list, 열 설명, hover, live box, overview'


STEPS = [
    ('image stacking', stacking_step),
    ('graph correlation', graph_corr_step),
    ('data display', data_display_step),
]
