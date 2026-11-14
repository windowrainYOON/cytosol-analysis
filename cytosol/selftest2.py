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


def _spots_plane(seed=0, n=24, amp=40.0, noise=4.0, size=(240, 320), sigma_px=1.6):
    rng = np.random.default_rng(seed)
    h, w = size
    yy, xx = np.mgrid[:h, :w]
    img = 100 + rng.normal(0, noise, size)
    pts = []
    while len(pts) < n:
        y, x = int(rng.integers(15, h - 15)), int(rng.integers(15, w - 15))
        if all((y - a) ** 2 + (x - b) ** 2 > 20 ** 2 for a, b in pts):
            pts.append((y, x))
    for k, (y, x) in enumerate(pts):
        a = amp * (0.6 + 0.8 * k / n)
        img += a * np.exp(-((yy - y) ** 2 + (xx - x) ** 2) / (2 * sigma_px ** 2))
    return img.astype(np.float32), pts


def particle_criterion_step(out: Path):
    """v0.65: 자동 = significance (k from the image size, noise alone gives
    almost nothing), 점 모양 강조 kept, 입자 기준 잡기 (candidates, steps,
    scope, project round trip), HT (RI) cell ROIs without nuclei, cell IDs
    linked between frames."""
    from dataclasses import replace

    from .cellroi import link_cell_frames, segment_ht_cells
    from .intensity import ParticleSettings, detect_particles, whole_image_cells
    from .io import Image
    from .lut import ImageItem
    from .particle_detect import significance_k
    from .roi_panel import RoiPanel

    px = 0.1
    img, pts = _spots_plane()
    cells = whole_image_cells(img.shape, px)
    s = ParticleSettings('CH', 0, 'image', 'auto')
    p = detect_particles(cells, img, s, 16, px)
    comp = p.components(cells)
    hit = {int(comp[y, x]) for y, x in pts}
    if 0 in hit or len(hit) != len(pts) or p.labels.max() > len(pts) + 1:
        raise AssertionError(f'significance particles: {p.labels.max()} for {len(pts)} spots')
    if not 3 < p.info['k'] < 6 or p.info['source'] != 'stat':
        raise AssertionError(f'k {p.info}')
    flat = np.random.default_rng(3).normal(100, 4, img.shape).astype(np.float32)
    if detect_particles(cells, flat, s, 16, px).labels.max() > 2:
        raise AssertionError('noise taken for particles')
    if significance_k(4_000_000, px, 0.5, 0.4) <= significance_k(40_000, px, 0.5, 0.4):
        raise AssertionError('k does not grow with the image area')
    spot = detect_particles(cells, img, replace(s, method='spot'), 16, px)
    if spot.labels is None or not spot.mask.any():
        raise AssertionError('점 모양 강조 (Hessian) gone')
    strict = detect_particles(cells, img, replace(s, crit_k=20.0), 16, px)
    if not 0 < strict.labels.max() < p.labels.max() or strict.info['source'] != 'user':
        raise AssertionError('user criterion k not used')
    back = ParticleSettings.from_properties(replace(s, crit_k=5.5, crit_area=0.1, noise=1.0).properties())
    if (back.crit_k, back.crit_area, back.noise) != (5.5, 0.1, 1.0):
        raise AssertionError('criterion not kept in ROI properties')

    # the calibration page on an image
    app, win = _window()
    win.show()
    image = Image(img[None, None], ['CH'], {'Z': None, 'Y': px, 'X': px}, colors=[(0.2, 1, 0.3)],
                  metadata={'image_id': 'SPOTS'})
    item = ImageItem(path=out / 'spots.tif', image=image, label='spots')
    item.reset_luts()
    win._add_item(item)
    win.file_list.setCurrentRow(0)
    win.show_tab('particle_tab')
    pp = win.particle_panel
    pp.within.setCurrentIndex(pp.within.findData('image'))
    pp.part_on.setChecked(True)
    app.processEvents()
    if not pp.calib_btn.isVisibleTo(pp) or '기본 기준' not in pp.crit_state.text():
        raise AssertionError('입자 기준 row')
    pp.start_calibration()
    cal = pp.calib
    if not cal.isVisible() or len(cal.shown) < 5 or not cal._scene or pp.measure.isVisible():
        raise AssertionError('calibration page / canvas boxes')
    snrs = [c['snr'] for c in cal.shown]
    if snrs != sorted(snrs) or cal.next_btn.isEnabled():
        raise AssertionError('brightness candidates not faint -> bright')
    cal.choose(2)
    cal.next()
    areas = [c['area'] for c in cal.shown]
    if cal.step != 1 or areas != sorted(areas) or min(c['snr'] for c in cal.shown) < snrs[2]:
        raise AssertionError('size candidates')
    cal.choose(0)
    cal.next()
    if cal.step != 2 or cal._scene or '→' not in cal.n_lab.text():
        raise AssertionError('apply page')
    cal.scope['image'].setChecked(True)
    cal.next()
    app.processEvents()
    crit = pp.criteria.get('CH')
    if cal.isVisible() or not pp.measure.isVisibleTo(pp) or crit is None or crit['scope'] != 'image' \
            or abs(crit['k'] - snrs[2] * 0.98) > 1e-2:
        raise AssertionError(f'criterion {crit}')
    pp.refresh()
    if item.particle_settings.crit_k != crit['k'] or item.particles.info.get('source') != 'user' \
            or '사용자 기준' not in pp.crit_state.text() or pp.noise.isVisibleTo(pp):
        raise AssertionError('criterion not applied to the image')
    other = ImageItem(path=out / 'spots2.tif', image=image, label='spots2')
    other.image = Image(img[None, None], ['CH'], {'Z': None, 'Y': px, 'X': px}, metadata={'image_id': 'OTHER'})
    if pp.criterion_for(other, 'CH') is not None:
        raise AssertionError('scope 이 이미지만 used on another image')
    proj = out / 'criterion.cyproj'
    win.write_project_to(proj)
    pp.criteria = {}
    win.open_project(proj, settings_only=True)
    if win.particle_panel.criteria.get('CH', {}).get('k') != crit['k']:
        raise AssertionError('criterion not kept in the project')
    win.particle_panel.clear_criterion()
    if win.particle_panel.criteria:
        raise AssertionError('criterion reset')
    _close(win)

    # HT (RI): cells from RI alone, routed by the RI values, no nuclei
    yy, xx = np.mgrid[:200, :300]
    ri = np.full((200, 300), 1.337, np.float32) + np.random.default_rng(1).normal(0, 0.0005, (200, 300))
    for cx, cy in ((60, 100), (150, 90), (240, 110)):
        ri[(xx - cx) ** 2 + (yy - cy) ** 2 < 32 ** 2] += 0.02
    ri = ri.astype(np.float32)
    rois = segment_ht_cells(ri, 0.2)
    if len(rois) != 3 or rois.nuclei is not None:
        raise AssertionError(f'HT cells: {len(rois)}')
    from .cellroi import RoiParams
    via = RoiPanel._run_planes([ri], 0.2, {'bg': 0, 'nuc': None}, RoiParams(), False, 0, 0)
    if len(via) != 3:
        raise AssertionError('RI channel not routed to the HT detection')
    man = RoiPanel._run_planes([ri], 0.2, {'bg': 0, 'nuc': None}, RoiParams(), True, 1.347, 0)
    if len(man) != 3:
        raise AssertionError('manual RI threshold')
    # cell IDs between frames
    a = rois.labels
    b = np.roll(a, 3, axis=1)
    b = np.where(b > 0, 4 - b, 0)          # same cells, numbered the other way round
    linked = link_cell_frames([a, b])
    for cx, cy in ((60, 100), (150, 90), (240, 110)):
        if linked[0][cy, cx] != linked[1][cy, cx + 3]:
            raise AssertionError('cell IDs not linked between frames')
    return (f'{p.labels.max()} spots (k {p.info["k"]:.1f}σ), criterion {crit["k"]:.1f}σ, '
            f'HT cells {len(rois)}, linked frames')


def _moving_spots(T=12, n=14, size=(200, 260), seed=0):
    """(T, C=2, Y, X) frames: n spots drifting 1.5 px a frame, channel B rising
    over time; plus the true positions per frame."""
    rng = np.random.default_rng(seed)
    h, w = size
    y0 = rng.uniform(25, h - 25, n)
    x0 = rng.uniform(25, w - 60, n)
    yy, xx = np.mgrid[:h, :w]
    frames, truth = [], []
    for t in range(T):
        a = rng.normal(100, 3, size).astype(np.float32)
        b = rng.normal(100, 3, size).astype(np.float32)
        pos = []
        for i in range(n):
            y, x = y0[i] + 0.3 * t, x0[i] + 1.5 * t
            g = np.exp(-((yy - y) ** 2 + (xx - x) ** 2) / (2 * 1.6 ** 2))
            a += 60 * g
            b += (10 + 5 * t) * g
            pos.append((y, x))
        frames.append(np.stack([a, b])[:, None])
        truth.append(pos)
    return np.stack(frames), truth


def tracking_step(out: Path):
    """v0.66 입자 추적: detection on every frame with the 입자 ROI settings,
    LAP linking (cell movement / pattern / velocity predictions), tracks of
    the moving spots kept whole, ratio over time, track table, canvas
    drawing, graph source + data list, export, batch step, project round
    trip, ParticleTracker CSV loaded back."""
    from . import batch
    from . import tracking as tk
    from .exporter import run as export_run
    from .io import Image
    from .lut import ImageItem

    T, n = 12, 14
    frames, truth = _moving_spots(T, n)
    px = 0.155
    image = Image(frames[0].copy(), ['A', 'B'], {'Z': None, 'Y': px, 'X': px}, colors=[(0, 1, 0), (1, 0, 1)],
                  metadata={'image_id': 'TRACKS'}, times=[30.0 * t for t in range(T)],
                  loader=lambda t: frames[t].copy())
    item = ImageItem(path=out / 'tracks.tif', image=image, label='tracks')
    item.reset_luts()
    app, win = _window()
    win.show()
    win._add_item(item)
    win.file_list.setCurrentRow(0)
    win.show_tab('track_tab')
    pp, tp = win.particle_panel, win.track_panel
    pp.part_channel.setCurrentIndex(0)
    pp.within.setCurrentIndex(pp.within.findData('image'))
    tp.cell_mode.setCurrentIndex(tp.cell_mode.findData('none'))
    tp.ratio_b.setCurrentIndex(tp.ratio_b.findData('B'))
    tp.ratio_a.setCurrentIndex(tp.ratio_a.findData('A'))
    app.processEvents()
    st = tp.run_current()
    if st is None or not st.points:
        raise AssertionError('no tracks')
    tracks = st.tracks()
    whole = [v for v in tracks.values() if len(v) == T]
    if len(whole) < n - 2:
        raise AssertionError(f'{len(whole)} of {n} spots tracked over all {T} frames ({len(tracks)} tracks)')
    # each whole track follows one true spot
    for v in whole:
        first = min(range(n), key=lambda i: (truth[0][i][0] - v[0]['y']) ** 2 + (truth[0][i][1] - v[0]['x']) ** 2)
        for p in v:
            ty, tx = truth[p['frame'] - 1][first]
            if (ty - p['y']) ** 2 + (tx - p['x']) ** 2 > 4:
                raise AssertionError('a track jumped to another spot')
    if st.ratio != 'ratio_B_A':
        raise AssertionError(f'ratio column {st.ratio}')
    r0 = np.nanmean([v[0][st.ratio] for v in whole])
    r1 = np.nanmean([v[-1][st.ratio] for v in whole])
    if not r1 > 3 * r0:
        raise AssertionError(f'ratio over time {r0:.2f} -> {r1:.2f}')
    if tp.table.rowCount() < n - 2 or not tp._scene:
        raise AssertionError('track table / canvas tails')
    tp.table.selectRow(0)
    app.processEvents()
    if not tp.selected_points():
        raise AssertionError('track selection')
    # data list, graph source, badge
    names = [e['name'] for e in win.data_entries() if e['key'] == 'track']
    if '입자 추적 · 시점' not in names or '입자 추적 · 트랙' not in names:
        raise AssertionError(f'data list {names}')
    data = win.graph_sources()['track'][2]()
    if data is None or data.spec.series[0].y != 'ratio_B_A' or len(data.tables) < 2:
        raise AssertionError(f'track graph source {data and (data.spec.series[0].y, len(data.tables), data.tables[0].columns[:40])}')
    win.live_box.refresh()
    if not win.live_box.isVisible() or win.live_box.values().get('트랙') != len(tracks):
        raise AssertionError(f'live box {win.live_box.values()}')
    # export
    res = export_run(win, [item], out / 'export', {'per_image': True, 'track_csv': True, 'track_rois': True,
                                                   'track_all': True})
    names = {Path(f).name for f in res.files}
    need = {'tracks_tracks_points.csv', 'tracks_tracks_summary.csv', 'tracks_tracks.zip', 'tracks_points.csv'}
    if not need <= names or res.errors:
        raise AssertionError(f'export {sorted(names)} {res.errors}')
    pts_csv = next(Path(f) for f in res.files if Path(f).name == 'tracks_tracks_points.csv')
    # ParticleTracker-named CSV loads back onto the image
    res2 = export_run(win, [item], out / 'export_pt', {'per_image': False, 'track_csv': True, 'track_pt': True})
    pt_csv = next(Path(f) for f in res2.files if Path(f).name.endswith('_tracks_points.csv'))
    if not tk.is_pt_points(pt_csv) or not tk.is_pt_points(pts_csv):
        raise AssertionError('points CSV not recognised')
    n_pts = len(st.points)
    item.tracks = None
    win.import_paths([pts_csv])
    if item.tracks is None or len(item.tracks.points) != n_pts or len(item.tracks.tracks()) != len(tracks):
        raise AssertionError('own points CSV not loaded back')
    item.tracks = None
    win.import_paths([pt_csv])
    if item.tracks is None or len(item.tracks.tracks()) != len(tracks) or item.tracks.source != 'ParticleTracker':
        raise AssertionError('ParticleTracker CSV not loaded')
    # project round trip
    from .project import item_files, restore_item_files
    item.tracks = st
    files = {}
    names = item_files(item, 0, None, files, out)
    item.tracks = None
    restore_item_files(item, names, files, out, [])
    back = item.tracks
    if back is None or len(back.points) != n_pts or not back.outlines:
        raise AssertionError('tracks not kept in the project')
    # batch step
    win.batch.steps = ['track']
    win.batch.groups = ['']
    errs = batch.run(win, win.batch, win.items)
    if errs or not str(win.batch.results.get('tracks', {}).get('track', '')).startswith('트랙'):
        raise AssertionError(f'batch {errs} {win.batch.results}')
    win.batch = batch.BatchState()
    _close(win)
    return (f'{len(tracks)} tracks, {len(whole)}/{n} whole over {T} frames, ratio {r0:.2f} → {r1:.2f}, '
            f'{len(res.files)} files, PT CSV loaded, project, batch')


def _mito_field(seed=7, n=320):
    """Mito (tubules), POI (on mito in cell 1, faint in cell 2), nuclei: three
    channels and the cell labels."""
    from scipy import ndimage as ndi
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[:n, :n]
    centres = [(90, 90), (90, 230), (230, 160)]
    lab = np.zeros((n, n), np.int32)
    for i, (cy, cx) in enumerate(centres, 1):
        lab[(yy - cy) ** 2 + (xx - cx) ** 2 < 62 ** 2] = i
    nucm = np.zeros((n, n), bool)
    for cy, cx in centres:
        nucm |= ((yy - cy) / 20) ** 2 + ((xx - cx) / 16) ** 2 < 1
    red = np.zeros((n, n), np.float32)
    for i, (cy, cx) in enumerate(centres, 1):
        m = (lab == i) & ~nucm
        ys, xs = np.nonzero(ndi.binary_erosion(m, iterations=3))
        for _ in range(60):
            k = rng.integers(len(ys))
            y, x, a = float(ys[k]), float(xs[k]), rng.uniform(0, 2 * np.pi)
            for _ in range(25):
                iy, ix = int(round(y)), int(round(x))
                if not (0 <= iy < n and 0 <= ix < n) or not m[iy, ix]:
                    break
                red[iy, ix] = 1
                a += rng.normal(0, 0.3)
                y += 1.4 * np.sin(a)
                x += 1.4 * np.cos(a)
    red = ndi.gaussian_filter(red, 1.0)
    red = red / red.max() * 200
    green = np.where(lab == 1, red * 0.6 + 8, 0) + np.where(lab == 2, 1.0, 0)
    for cy, cx in ((70, 60), (110, 120), (60, 100)):
        green += 120 * np.exp(-((yy - cy) ** 2 + (xx - cx) ** 2) / 8.0)
    cells = lab > 0
    red += cells * 7 + rng.normal(0, 1.5, red.shape)
    green += cells * 2 + rng.normal(0, 1.0, green.shape)
    nuc = np.where(nucm, 160, 0) + cells * 4 + rng.normal(0, 1.5, red.shape)
    planes = np.stack([np.clip(c, 0, 255) for c in (red, green, nuc)]).astype(np.float32)
    return planes, lab, nucm


def mito_step(out: Path):
    """v0.67 mitoROI: Mito Analyzer's measurements on the app's cell ROIs
    (MiNA skeleton, mito objects, POI on / off mito, puncta, green+ / −),
    canvas layers, tables + column sets for the graph window (상관 행렬),
    export with Mito Analyzer's file names, results loaded back, project,
    batch."""
    from . import batch
    from . import mito as M
    from .cellroi import CellRois
    from .exporter import run as export_run
    from .io import Image
    from .lut import ImageItem
    from .project import item_files, restore_item_files

    planes, lab, nucm = _mito_field()
    px = 0.099
    image = Image(planes[:, None].copy(), ['Mito', 'POI', 'DAPI'], {'Z': None, 'Y': px, 'X': px},
                  colors=[(1, 0, 1), (0, 1, 0), (0, 0, 1)], metadata={'image_id': 'MITO-1'})
    item = ImageItem(path=out / 'mito_cells.tif', image=image, label='mito_cells')
    item.reset_luts()
    item.cells = CellRois(lab, np.where(nucm, lab, 0).astype(np.int32), px)
    app, win = _window()
    win.show()
    win._add_item(item)
    win.file_list.setCurrentRow(0)
    win.show_tab('mito_tab')
    mp = win.mito_panel
    app.processEvents()
    if mp.mito_ch.currentData() != 'Mito' or mp.poi_ch.currentData() != 'POI':
        raise AssertionError(f'channels {mp.mito_ch.currentData()} / {mp.poi_ch.currentData()}')
    r = mp.run_current()
    if r is None or len(r.cells) != 3:
        raise AssertionError(f'cells {r and len(r.cells)}')
    by = {c['cell']: c for c in r.cells}
    if not all(c['n_branches'] > 10 and 0 < c['footprint_fraction'] < 0.6 for c in r.cells):
        raise AssertionError('MiNA values')
    if by['cell01']['green_status'] != 'positive' or by['cell02']['green_status'] != 'negative':
        raise AssertionError(f'green+ / −: {[c["green_status"] for c in r.cells]}')
    if not by['cell01']['green_enrichment_on_mito'] > 2 or not r.puncta or len(r.mito) < 30:
        raise AssertionError('POI on mito / puncta / mito objects')
    if not mp._scene or '미토 조각' not in mp.mito_state.text() or mp.table.rowCount() != 3:
        raise AssertionError('canvas layers / state / table')
    # MiNA classic and a manual threshold
    mp.method_btns['otsu'].setChecked(True)
    r2 = mp.run(item)
    if r2.used.get('mito_threshold_range') is None or not r2.cells:
        raise AssertionError('MiNA classic')
    mp.method_btns['split'].setChecked(True)
    # data list + graph source with column sets
    names = [e['name'] for e in win.data_entries() if e['key'] == 'mito']
    if names[:3] != ['mitoROI · 세포', 'mitoROI · 미토 조각', 'mitoROI · 점']:
        raise AssertionError(f'data list {names}')
    data = win.graph_sources()['mito'][2]()
    t = data.tables[0]
    if data.spec.chart != 'corr' or len(t.column_sets.get('미토 형태', [])) < 10 \
            or t.labels.get('footprint_fraction') != 'Mito footprint fraction':
        raise AssertionError('graph source')
    d = mp.open_graph('corr')
    if d is None or win.graph_win.spec.chart != 'corr':
        raise AssertionError('상관 히트맵 button')
    # export (Mito Analyzer names) and loading back
    res = export_run(win, [item], out / 'mito_export', {'per_image': False, 'mito_csv': True, 'mito_rois': True,
                                                        'mito_all': True})
    got = {Path(f).name for f in res.files}
    need = {'mito_cells_per_cell.csv', 'mito_cells_per_mito.csv', 'mito_cells_green_puncta.csv',
            'mito_cells_correlations.csv', 'mito_cells_mito_RoiSet.zip', 'mito_per_cell.csv'}
    if not need <= got or res.errors:
        raise AssertionError(f'export {sorted(got)} {res.errors}')
    keep = r
    item.mito = None
    win.import_paths([out / 'mito_export' / 'mito_cells_per_cell.csv'])
    if item.mito is None or item.mito.source != 'Mito Analyzer' or len(item.mito.cells) != 3 \
            or len(item.mito.mito) != len(keep.mito):
        raise AssertionError('Mito Analyzer CSV not loaded')
    if abs(item.mito.cells[0]['footprint_fraction'] - keep.cells[0]['footprint_fraction']) > 1e-3:
        raise AssertionError('loaded values')
    # project
    item.mito = keep
    files = {}
    names = item_files(item, 0, None, files, out)
    item.mito = None
    restore_item_files(item, names, files, out, [])
    if item.mito is None or len(item.mito.mito) != len(keep.mito):
        raise AssertionError('mitoROI not kept in the project')
    # batch
    win.batch.steps = ['mito']
    win.batch.groups = ['']
    errs = batch.run(win, win.batch, win.items)
    if errs or win.batch.results.get('mito_cells', {}).get('mito') != '세포 3':
        raise AssertionError(f'batch {errs} {win.batch.results}')
    win.batch = batch.BatchState()
    _close(win)
    c1 = by['cell01']
    return (f'3 cells, {len(r.mito)} mito objects, {len(r.puncta)} puncta, cell01 green+ '
            f'(enrichment {c1["green_enrichment_on_mito"]:.1f}), {len(res.files)} files, loaded back, batch')


STEPS = [
    ('image stacking', stacking_step),
    ('graph correlation', graph_corr_step),
    ('data display', data_display_step),
    ('particle criterion + HT cells', particle_criterion_step),
    ('particle tracking', tracking_step),
    ('mitoROI', mito_step),
]
