"""The graph of each feature tab as GraphData for the 그래프 편집 창: its
result tables and a GraphSpec that draws what the tab shows."""

from __future__ import annotations

import math

import numpy as np

from . import graph as G
from .lut import item_stem


def _hex(rgb) -> str:
    return '#%02x%02x%02x' % tuple(int(round(max(0.0, min(1.0, float(c))) * 255)) for c in rgb[:3])


def _folder(it) -> str:
    return str(it.path.parent) if it is not None and getattr(it, 'path', None) else ''


def _stem(it, suffix) -> str:
    return f'{item_stem(it)}_{suffix}' if it is not None else suffix


def _plain(spec: G.GraphSpec):
    """FRAP-figure look: left / bottom axes, ticks out, no grid, legend above."""
    spec.spine_top = spec.spine_right = False
    spec.grid = False
    spec.legend_loc = 'above'
    spec.label_font = G.Font(9.0)
    spec.tick_font = G.Font(8.0)
    spec.legend_font = G.Font(7.0)
    spec.width_in, spec.height_in = 4.0, 3.4


# ---- line profile -------------------------------------------------------------------------------

def profile(panel) -> G.GraphData | None:
    from .lineprofile import plot_color

    p, it = panel.profile, panel.item
    if p is None or it is None:
        return None
    norm = panel.normalize.isChecked()
    cols = {'distance': p.distance}
    for c, name in enumerate(p.channels):
        cols[name] = p.values[c]
    for c, name in enumerate(p.channels):
        y = np.asarray(p.values[c], float)
        lo, hi = float(np.nanmin(y)), float(np.nanmax(y))
        cols[f'{name} (0–1)'] = (y - lo) / (hi - lo) if hi > lo else y * 0
    t = G.Table.from_arrays('라인 프로파일', cols)
    vis = panel._visible()
    colors = panel._colors()
    series = []
    for c, name in enumerate(p.channels):
        if vis is not None and not vis[c]:
            continue
        series.append(G.Series(table=t.name, x='distance', y=f'{name} (0–1)' if norm else name, label=name,
                               style='line', color=_hex(plot_color(colors[c])), line_width=1.2,
                               marker='none'))
    spec = G.GraphSpec(chart='xy', series=series, spine_top=True, spine_right=True, grid=True)
    spec.x.label = f'Distance ({"microns" if p.unit == "µm" else "pixels"})'
    spec.y.label = 'Normalized intensity' if norm else 'Intensity'
    if len(p.distance):
        spec.x.auto_range, spec.x.lo, spec.x.hi = False, 0.0, float(p.distance[-1])
    spec.legend_font = G.Font(8.0)
    return G.GraphData(f'라인 프로파일 · {it.label}', [t], spec, _stem(it, 'profile'), _folder(it))


# ---- FRAP ---------------------------------------------------------------------------------------

def frap(panel) -> G.GraphData | None:
    from . import frap as F

    view = panel.view.currentData()
    it = panel.item
    if view == 'groups':
        gs = panel.shown([g for g in panel.groups() if g is not None])
        return _frap_groups(panel, gs) if gs else None
    c = panel.curve
    if c is None:
        return None
    k = F._scale(c.normalize)
    t = c.t_rel
    n = len(t)
    after = (t >= 0) if c.normalize == 'full' else np.ones(n, bool)
    curve = G.Table.from_arrays('회복 곡선', {
        'frame': list(range(1, n + 1)), 'time_s': c.times, 't_after_bleach_s': t,
        'recovery': c.values * k, 'shown': [int(v) for v in after],
        **{f'{F.ROI_TITLES[r]}_mean': c.means[r] for r in F.ROI_NAMES}, 'ratio': c.ratio})
    tables = [curve]
    spec = G.GraphSpec(chart='xy')
    _plain(spec)
    spec.x.label = 'Time (s)' if view != 'raw' else 'Time after bleach (s)'
    if view == 'raw':
        for r in F.ROI_NAMES:
            spec.series.append(G.Series(table=curve.name, x='t_after_bleach_s', y=f'{F.ROI_TITLES[r]}_mean',
                                        label=F.ROI_TITLES[r], style='line+marker', marker_size=3.0,
                                        line_width=1.2, color=_hex(np.array(F.ROI_COLORS[r]) / 255)))
        spec.y.label = 'Mean intensity'
        spec.grid = True
        spec.legend_loc = 'best'
        tables.append(_vline(curve, 'Mean intensity'))
        spec.series.append(_vline_series())
        return G.GraphData(f'FRAP · ROI 평균 강도 · {c.label}', tables, spec, _stem(it, 'frap_raw'), _folder(it))
    spec.series.append(G.Series(table=curve.name, x='t_after_bleach_s', y='recovery', where='shown', equals='1',
                                label=c.label, style='marker', marker='s', marker_fill=False,
                                marker_size=4.0, marker_edge=0.8, color='#000000'))
    spec.y.label = F._ylabel(c.normalize)
    if panel.fit.isChecked() and c.fit is not None:
        if c.fit.ok:
            x = np.linspace(0, float(t[-1]), 200)
            fit = G.Table.from_arrays('피팅 곡선', {'t_s': x, 'fit': c.fit.value(x) * k})
            tables.append(fit)
            spec.series.append(G.Series(table=fit.name, x='t_s', y='fit', style='line', marker='none',
                                        line_width=1.0, color='#000000',
                                        label=f'fit: t½ {c.fit.half_time:.3g} s, Mf {c.fit.mobile:.2f}'))
        else:
            spec.legend_items.append(G.LegendItem(label=f'fit: {c.fit.problem}', marker='none'))
    if c.normalize == 'full':
        _full_range(spec, curve.numbers('recovery')[after], float(np.nanmax(t)))
    else:
        tables.append(_vline(curve, 'recovery'))
        spec.series.append(_vline_series())
    s = c.summary()
    tables.append(G.Table('요약', ['parameter', 'value'], [[key, s[key]] for key in s]))
    return G.GraphData(f'FRAP · 회복 곡선 · {c.label}', tables, spec, _stem(it, 'frap'), _folder(it))


def _vline(t: G.Table, col) -> G.Table:
    v = t.numbers(col)
    v = v[np.isfinite(v)]
    lo, hi = (float(v.min()), float(v.max())) if v.size else (0.0, 1.0)
    return G.Table.from_arrays('bleach 시점', {'t_s': [0.0, 0.0], 'y': [lo, hi]})


def _vline_series() -> G.Series:
    return G.Series(table='bleach 시점', x='t_s', y='y', style='line', marker='none', line_style='--',
                    line_width=0.8, color='#999999', legend=False, label='bleach')


def _full_range(spec, vals, tmax):
    """Recovery (%) from 0 as the tab draws it."""
    vals = vals[np.isfinite(vals)]
    lo = min(float(vals.min()) if vals.size else 0.0, -5.0)
    hi = max(float(vals.max()) if vals.size else 100.0, 100.0) + 5
    spec.y.auto_range, spec.y.lo, spec.y.hi = False, lo, hi
    spec.x.auto_range, spec.x.lo, spec.x.hi = False, -0.04 * tmax, tmax * 1.04


def _frap_groups(panel, gs) -> G.GraphData:
    from . import frap as F

    norm = gs[0].members[0].normalize if gs[0].members else 'full'
    k = F._scale(norm)
    error = panel.error.currentData()
    rows, members, fits = [], [], []
    tmax = 1.0
    for g in gs:
        for j in range(len(g.t)):
            show = g.offset[j] >= 0 if norm == 'full' else True
            rows.append({'group': g.name, 'frame_from_bleach': int(g.offset[j]), 't_s': float(g.t[j]),
                         'mean': float(g.mean[j] * k), 'sd': float(g.sd[j] * k), 'sem': float(g.sem[j] * k),
                         'n': int(g.n[j]), 'shown': int(show)})
        for c in g.members:
            for j, (tv, v) in enumerate(zip(c.t_rel, c.values)):
                members.append({'group': g.name, 'image': c.label, 'frame': j + 1, 't_s': float(tv),
                                'recovery': float(v * k), 'shown': int(tv >= 0 if norm == 'full' else 1)})
        if g.fit is not None and g.fit.ok:
            x = np.linspace(0, float(np.nanmax(g.t)), 200)
            fits += [{'group': g.name, 't_s': float(a), 'fit': float(b * k)} for a, b in zip(x, g.fit.value(x))]
        tmax = max(tmax, float(np.nanmax(g.t)))
    means = G.Table.from_dicts('그룹 평균', rows)
    images = G.Table.from_dicts('이미지별 곡선', members)
    tables = [means, images]
    spec = G.GraphSpec(chart='xy')
    _plain(spec)
    spec.x.label = 'Time (s)'
    spec.y.label = F._ylabel(norm) + (f' (mean ± {error.upper()})' if norm != 'full' else '')
    spec.legend_title = f'mean ± {error.upper()}' if norm == 'full' else ''
    spec.legend_font = G.Font(7.0, color='#000000')
    if panel.members.isChecked():
        for g in gs:
            spec.series.append(G.Series(table=images.name, x='t_s', y='recovery', where='group', equals=g.name,
                                        where2='shown', equals2='1', split='image', style='line',
                                        marker='none', line_width=0.5, color='#999999', alpha=0.6,
                                        legend=False, label=f'{g.name} images'))
    for i, g in enumerate(gs):
        m, filled = F.MARKERS[i % len(F.MARKERS)]
        spec.series.append(G.Series(table=means.name, x='t_s', y='mean', err=error, where='group', equals=g.name,
                                    where2='shown', equals2='1', label=f'{g.name} (n={len(g.members)})',
                                    style='marker', marker=m, marker_fill=filled, marker_size=4.0,
                                    marker_edge=0.8, color='#000000', err_width=0.7, capsize=1.5))
    if panel.fit.isChecked() and fits:
        ft = G.Table.from_dicts('그룹 피팅 곡선', fits)
        tables.append(ft)
        for g in gs:
            if g.fit is not None and g.fit.ok:
                spec.series.append(G.Series(table=ft.name, x='t_s', y='fit', where='group', equals=g.name,
                                            style='line', marker='none', line_width=1.0, color='#000000',
                                            legend=False, label=f'{g.name} fit'))
    summ = []
    for g in gs:
        s = F.group_summary(g)
        row = {'group': g.name, 'n_images': len(g.members)}
        for key, (m, sd, sem, n) in s.items():
            row |= {f'{key}_mean': m, f'{key}_sd': sd, f'{key}_sem': sem}
        summ.append(row)
    tables.append(G.Table.from_dicts('그룹 요약', summ))
    if norm == 'full':
        vals = means.numbers('mean')[np.array(means.values('shown')) == 1]
        _full_range(spec, vals, tmax)
    else:
        tables.append(_vline(means, 'mean'))
        spec.series.append(_vline_series())
    return G.GraphData('FRAP · 그룹 평균', tables, spec, 'frap_groups', _folder(panel.item))


# ---- intensity: distance bands --------------------------------------------------------------------

def bands(panel) -> G.GraphData | None:
    rows = panel.bands_measure._rows_shown()[0]
    x, y = panel.graph_x.currentText(), panel.graph_y.currentText()
    if not rows or not x or not y:
        return None
    rows = [{**r, 'cell': f'{r.get("image_id", "")} t{r.get("timepoint", "")} {r.get("roi", "")}'} for r in rows]
    t = G.Table.from_dicts('등거리 띠', rows)
    ncell = len(set(t.values('cell')))
    spec = G.GraphSpec(chart='xy', grid=True, spine_top=True, spine_right=True)
    spec.series.append(G.Series(table=t.name, x=x, y=y, split='cell', style='line', marker='none',
                                line_width=0.7, color='#999999', alpha=0.6, legend=False, label='cells'))
    if ncell > 1:
        spec.series.append(G.Series(table=t.name, x=x, y=y, agg='mean', agg_by='band' if 'band' in t.columns
                                    else '', agg_err='sd', err_style='band', style='line', marker='none',
                                    line_width=2.0, color='#d62728', label=f'mean ± SD ({ncell} cells)'))
    spec.x.label, spec.y.label = x, y
    it = panel.win.current
    return G.GraphData('강도 측정 · 등거리 띠', [t], spec, _stem(it, 'bands'), _folder(it))


# ---- measurement tables ---------------------------------------------------------------------------

def measure(box, title) -> G.GraphData | None:
    rows, _ = box._rows_shown()
    it = box.win.current
    return G.measure_graph(rows, f'{title} · {box.view.currentText()}', _stem(it, box.suffix), _folder(it))


# ---- Coloc 2 --------------------------------------------------------------------------------------

def coloc(panel) -> G.GraphData | None:
    from .coloc_panel import SUMMARY

    it = panel.win.current
    recs = list(it.coloc) if it is not None and it.coloc else list(panel.records)
    if not recs:
        return None
    results = G.Table.from_dicts('Coloc 2 결과', [r.row() for r in recs])
    tables = [results]
    rec = panel.current_record()
    data = panel.view.currentData() if panel.view.count() else None
    if rec is not None and data is not None and data[0] == 'hist':
        h = data[1]
        counts = np.asarray(h.counts, float)
        nx, ny = counts.shape
        ii, jj = np.nonzero(counts)
        if h.regression:
            xs, ys = ii / h.x_bin_width, (ny - 1 - jj) / h.y_bin_width
        else:
            xs, ys = h.x_min + (ii + 0.5) / h.x_bin_width, (ny - 1 - jj + 0.5) / h.y_bin_width
        hist = G.Table.from_arrays('2D 히스토그램', {h.x_label: xs, h.y_label: ys, 'count': counts[ii, jj]})
        tables.append(hist)
        spec = G.GraphSpec(chart='heatmap', title=f'{h.title} · {rec.roi}', legend_show=False,
                           spine_top=True, spine_right=True, cmap='inferno', cmap_log=True)
        spec.title_font = G.Font(9.0)
        spec.series.append(G.Series(table=hist.name, x=h.x_label, y=h.y_label, z='count', label='count'))
        r = rec.result
        if h.regression and math.isfinite(r.slope):
            x0, x1 = -0.5 / h.x_bin_width, (nx - 0.5) / h.x_bin_width
            y0, y1 = -0.5 / h.y_bin_width, (ny - 0.5) / h.y_bin_width
            lines = G.Table.from_arrays('회귀선·threshold', {
                'line': ['regression'] * 2 + ['ch1 threshold'] * 2 + ['ch2 threshold'] * 2,
                'x': [x0, x1, r.ch1_threshold, r.ch1_threshold, x0, x1],
                'y': [r.slope * x0 + r.intercept, r.slope * x1 + r.intercept, y0, y1,
                      r.ch2_threshold, r.ch2_threshold]})
            tables.append(lines)
            spec.series.append(G.Series(table=lines.name, x='x', y='y', where='line', equals='regression',
                                        style='line', marker='none', color='#000000', line_width=1.0,
                                        label='regression'))
            for name in ('ch1 threshold', 'ch2 threshold'):
                spec.series.append(G.Series(table=lines.name, x='x', y='y', where='line', equals=name,
                                            style='line', marker='none', color='#4fc3f7', line_width=0.8,
                                            line_style='--', label=name))
            spec.x.auto_range, spec.x.lo, spec.x.hi = False, x0, x1
            spec.y.auto_range, spec.y.lo, spec.y.hi = False, y0, y1
        spec.x.label, spec.y.label = h.x_label, h.y_label
        spec.width_in, spec.height_in = 5.0, 4.5
        return G.GraphData(f'Coloc 2 · {h.title} · {rec.roi}', tables, spec,
                           _stem(it, f'{rec.roi}_coloc2'), _folder(it))
    # result images are not graphs: per-ROI values as bars
    y = next((name for _, name in SUMMARY if name in results.columns and results.is_numeric(name)), '')
    if not y:
        return None
    spec = G.GraphSpec(chart='bar', legend_show=False, bar_err='none')
    spec.series.append(G.Series(table=results.name, x='roi', y=y, label=y, color='#1f77b4', marker_size=3.0))
    spec.x.label, spec.y.label = 'ROI', y
    spec.x.rotation = 45 if len(recs) > 6 else 0
    return G.GraphData('Coloc 2 · ROI별 결과', tables, spec, _stem(it, 'coloc2'), _folder(it))


# ---- 일괄 분석 ------------------------------------------------------------------------------------

def batch(state) -> G.GraphData | None:
    """The batch results (one row per image) as a table."""
    res = getattr(state, 'results', None) or {}
    if not res:
        return None
    rows = [{'image': label} | dict(vals) for label, vals in res.items()]
    return G.measure_graph(rows, '일괄 분석 결과', 'batch', '')
