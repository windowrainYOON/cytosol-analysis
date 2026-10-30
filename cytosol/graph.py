"""Graphs for the 그래프 편집 창: data tables, a graph description that every
style setting lives in (GraphSpec, saved as JSON), drawing it with
matplotlib, and the data the graph shows as tables (CSV export).

A feature hands the window a GraphData: its result tables and a GraphSpec
that draws the graph its tab shows. Everything the user changes in the
window is a field of the GraphSpec."""

from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

import numpy as np

CHARTS = {
    'xy': 'XY (선 / 점)',
    'bar': '막대 (평균 ± 에러바)',
    'strip': '점 그림 (개별 값 + 평균)',
    'box': '상자 그림 (box plot)',
    'violin': '바이올린',
    'hist': '히스토그램',
    'heatmap': '히트맵 (2D)',
}
CATEGORY_CHARTS = ('bar', 'strip', 'box', 'violin')
STYLES = {'line+marker': '선 + 점', 'line': '선', 'marker': '점', 'step': '계단', 'area': '면적 (채움)'}
LINE_STYLES = {'-': '실선', '--': '파선', ':': '점선', '-.': '일점쇄선', 'none': '없음'}
MARKERS = {'o': '원', 's': '사각형', '^': '삼각형', 'v': '역삼각형', 'D': '마름모', 'x': 'x',
           '+': '+', '*': '별', 'none': '없음'}
ERR_STYLES = {'bar': '에러바', 'band': '띠 (음영)', 'none': '없음'}
ERR_KINDS = {'sd': 'SD', 'sem': 'SEM', 'ci95': '95% CI', 'none': '없음'}
AGGREGATES = {'none': '그대로 (모든 점)', 'mean': '평균 (같은 x끼리)', 'median': '중앙값 (같은 x끼리)'}
LEGEND_LOCS = {'best': '자동 (빈 곳)', 'above': '그래프 위', 'right': '그래프 오른쪽',
               'upper right': '안쪽 오른쪽 위', 'upper left': '안쪽 왼쪽 위',
               'lower right': '안쪽 오른쪽 아래', 'lower left': '안쪽 왼쪽 아래',
               'custom': '직접 놓기 (끌어 옮긴 자리)'}
TICK_DIRS = {'out': '바깥', 'in': '안쪽', 'inout': '양쪽'}
ALIGNS = {'left': '왼쪽', 'center': '가운데', 'right': '오른쪽'}
CMAPS = ['inferno', 'viridis', 'magma', 'plasma', 'gray', 'hot', 'Greens', 'Reds', 'Blues']
PALETTE = ['#000000', '#d62728', '#1f77b4', '#2ca02c', '#9467bd', '#ff7f0e', '#8c564b',
           '#e377c2', '#17becf', '#7f7f7f', '#bcbd22']
FORMAT = 'cytosol-viewer-graph'


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------

def _num(v) -> float:
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float, np.integer, np.floating)):
        return float(v)
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return math.nan


def _text(v) -> str:
    if isinstance(v, float):
        return '' if math.isnan(v) else f'{v:.6g}'
    return '' if v is None else str(v)


@dataclass
class Table:
    """One result table: column names and rows (lists of numbers / text)."""

    name: str
    columns: list
    rows: list

    @classmethod
    def from_dicts(cls, name, dicts, columns=None) -> 'Table':
        cols = list(columns or [])
        for d in dicts:
            cols += [k for k in d if k not in cols]
        return cls(name, cols, [[d.get(c, '') for c in cols] for d in dicts])

    @classmethod
    def from_arrays(cls, name, data: dict) -> 'Table':
        """Columns of (possibly different) lengths; short ones are padded with ''."""
        cols = list(data)
        vals = [list(np.asarray(v).tolist()) if not isinstance(v, list) else v for v in data.values()]
        n = max((len(v) for v in vals), default=0)
        rows = [[v[i] if i < len(v) else '' for v in vals] for i in range(n)]
        return cls(name, cols, rows)

    def index(self, col) -> int:
        return self.columns.index(col)

    def values(self, col) -> list:
        if col not in self.columns:
            return [''] * len(self.rows)
        j = self.index(col)
        return [r[j] if j < len(r) else '' for r in self.rows]

    def numbers(self, col) -> np.ndarray:
        return np.array([_num(v) for v in self.values(col)], float)

    def is_numeric(self, col) -> bool:
        vals = [v for v in self.values(col) if _text(v) != '']
        return bool(vals) and all(math.isfinite(_num(v)) or _text(v).lower() in ('nan', 'inf', '-inf')
                                  for v in vals)

    def numeric_columns(self) -> list:
        return [c for c in self.columns if self.is_numeric(c)]

    def text_rows(self) -> list:
        return [[_text(v) for v in r] for r in self.rows]


def write_csv(path, table: Table, rows=None) -> int:
    """UTF-8 with BOM (Excel), like the other CSVs of the program."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = table.rows if rows is None else rows
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(table.columns)
        for r in rows:
            w.writerow([_text(v) for v in r])
    return len(rows)


# ---------------------------------------------------------------------------
# graph description
# ---------------------------------------------------------------------------

@dataclass
class Series:
    """What one data series takes from a table and how it is drawn."""

    table: str = ''
    x: str = ''
    y: str = ''
    err: str = ''      # column with ± error values ('' = none)
    z: str = ''        # heat map value
    where: str = ''    # only rows whose column ...
    equals: str = ''   # ... has this value (as text)
    where2: str = ''   # and a second condition
    equals2: str = ''
    split: str = ''    # one line per value of this column, all in this style
    agg: str = 'none'  # 'mean' / 'median' of y over rows with the same x (or agg_by)
    agg_by: str = ''
    agg_err: str = 'sd'
    label: str = ''
    visible: bool = True
    legend: bool = True
    style: str = 'line+marker'
    color: str = '#000000'
    line_width: float = 1.0
    line_style: str = '-'
    marker: str = 'o'
    marker_size: float = 4.0
    marker_fill: bool = True
    marker_edge: float = 0.8
    alpha: float = 1.0
    err_style: str = 'bar'
    err_color: str = ''  # '' = the series color
    err_width: float = 0.8
    capsize: float = 2.0


STYLE_FIELDS = ('style', 'color', 'line_width', 'line_style', 'marker', 'marker_size', 'marker_fill',
                'marker_edge', 'alpha', 'err_style', 'err_color', 'err_width', 'capsize')


@dataclass
class Axis:
    label: str = ''
    auto_range: bool = True
    lo: float = 0.0
    hi: float = 1.0
    auto_step: bool = True  # tick spacing chosen by matplotlib (MaxNLocator)
    step: float = 1.0
    log: bool = False
    minor: bool = False
    tick_dir: str = 'out'
    rotation: float = 0.0


@dataclass
class Font:
    size: float = 9.0
    bold: bool = False
    italic: bool = False
    color: str = '#000000'


@dataclass
class TextBox:
    """Free text on the graph; x, y in axes fractions (0–1 = inside the axes)."""

    text: str = 'Text'
    x: float = 0.5
    y: float = 0.5
    size: float = 9.0
    bold: bool = False
    italic: bool = False
    color: str = '#000000'
    frame: bool = False
    align: str = 'left'


@dataclass
class LegendItem:
    """An extra legend entry that belongs to no series."""

    label: str = 'Item'
    color: str = '#000000'
    marker: str = 's'
    line_style: str = 'none'
    fill: bool = True


@dataclass
class GraphSpec:
    chart: str = 'xy'
    title: str = ''
    series: list = field(default_factory=list)
    x: Axis = field(default_factory=Axis)
    y: Axis = field(default_factory=Axis)
    texts: list = field(default_factory=list)
    legend_items: list = field(default_factory=list)
    legend_show: bool = True
    legend_loc: str = 'best'
    legend_x: float = 0.02  # lower left corner (axes fraction) when custom
    legend_y: float = 1.0
    legend_title: str = ''
    legend_frame: bool = False
    legend_ncol: int = 1
    font_family: str = ''  # '' = default sans-serif (with Korean fallback)
    title_font: Font = field(default_factory=lambda: Font(11.0, True))
    label_font: Font = field(default_factory=lambda: Font(9.0))
    tick_font: Font = field(default_factory=lambda: Font(8.0))
    legend_font: Font = field(default_factory=lambda: Font(8.0))
    width_in: float = 5.0
    height_in: float = 3.6
    dpi: int = 300
    background: str = '#ffffff'
    spine_top: bool = False
    spine_right: bool = False
    spine_width: float = 0.8
    grid: bool = False
    grid_color: str = '#d9d9d9'
    bar_width: float = 0.7
    bar_err: str = 'sd'
    bar_points: bool = True
    bar_alpha: float = 0.35
    point_jitter: float = 0.15
    hist_bins: int = 0  # 0 = automatic
    hist_density: bool = False
    hist_fill: bool = True
    cmap: str = 'inferno'
    cmap_log: bool = True
    colorbar: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> 'GraphSpec':
        return _build(cls, d)

    def copy(self) -> 'GraphSpec':
        return GraphSpec.from_dict(self.to_dict())


_NESTED = {'x': Axis, 'y': Axis, 'title_font': Font, 'label_font': Font, 'tick_font': Font,
           'legend_font': Font}
_LISTS = {'series': Series, 'texts': TextBox, 'legend_items': LegendItem}


def _build(cls, d):
    """A dataclass from a dict, ignoring unknown keys and wrong types."""
    obj = cls()
    if not isinstance(d, dict):
        return obj
    for f in fields(cls):
        if f.name not in d:
            continue
        v = d[f.name]
        if cls is GraphSpec and f.name in _NESTED:
            v = _build(_NESTED[f.name], v)
        elif cls is GraphSpec and f.name in _LISTS:
            v = [_build(_LISTS[f.name], e) for e in v] if isinstance(v, list) else []
        else:
            cur = getattr(obj, f.name)
            try:
                if isinstance(cur, bool):
                    v = bool(v)
                elif isinstance(cur, int):
                    v = int(v)
                elif isinstance(cur, float):
                    v = float(v)
                elif isinstance(cur, str):
                    v = str(v)
            except (TypeError, ValueError):
                continue
        setattr(obj, f.name, v)
    return obj


def save_spec(path, spec: GraphSpec) -> str:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps({'format': FORMAT, 'graph': spec.to_dict()}, ensure_ascii=False,
                                     indent=1), encoding='utf-8')
    return str(path)


def load_spec(path) -> GraphSpec:
    d = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(d, dict) or d.get('format') != FORMAT:
        raise ValueError('그래프 설정 파일이 아닙니다.')
    return GraphSpec.from_dict(d.get('graph') or {})


def apply_style(spec: GraphSpec, style: GraphSpec) -> GraphSpec:
    """spec's data (chart, series columns, texts) with style's look: fonts, axes
    options, legend, size; series styles by position."""
    out = style.copy()
    out.chart = spec.chart
    out.title = spec.title
    for a in ('x', 'y'):  # ranges and ticks belong to the data
        mine, theirs = getattr(out, a), getattr(spec, a)
        for k in ('label', 'auto_range', 'lo', 'hi', 'auto_step', 'step', 'log'):
            setattr(mine, k, getattr(theirs, k))
    out.texts = [TextBox(**asdict(t)) for t in spec.texts]
    out.legend_items = [LegendItem(**asdict(t)) for t in spec.legend_items]
    out.legend_title = spec.legend_title
    series = []
    for i, s in enumerate(spec.series):
        s = Series(**asdict(s))
        if i < len(style.series):
            for k in STYLE_FIELDS:
                setattr(s, k, getattr(style.series[i], k))
        series.append(s)
    out.series = series
    return out


@dataclass
class GraphData:
    """What a feature hands the graph window."""

    title: str               # window title, e.g. 'FRAP 측정 · 그룹 평균'
    tables: list             # Table
    spec: GraphSpec          # draws the graph the tab shows
    name: str = 'graph'      # default file name stem
    folder: str = ''         # default folder for saving

    def table(self, name) -> Table | None:
        return next((t for t in self.tables if t.name == name), None)


# ---------------------------------------------------------------------------
# the data each series shows
# ---------------------------------------------------------------------------

def _rows_of(s: Series, tables: dict) -> tuple[Table | None, list]:
    t = tables.get(s.table)
    if t is None:
        return None, []
    rows = list(range(len(t.rows)))
    for col, val in ((s.where, s.equals), (s.where2, s.equals2)):
        if col and col in t.columns:
            j = t.index(col)
            rows = [i for i in rows if _text(t.rows[i][j]) == val]
    return t, rows


def _err(vals: np.ndarray, kind: str) -> float:
    v = vals[np.isfinite(vals)]
    if kind == 'none' or v.size < 2:
        return math.nan if kind != 'none' else 0.0
    sd = float(v.std(ddof=1))
    if kind == 'sd':
        return sd
    sem = sd / math.sqrt(v.size)
    return sem if kind == 'sem' else 1.96 * sem


def xy_parts(s: Series, tables: dict) -> list[dict]:
    """[{key, x, y, err, n}]: one part per split value (one part without split);
    x, y numeric; non-numeric x become 0, 1, … with the names in 'ticks'."""
    t, rows = _rows_of(s, tables)
    if t is None or s.y not in t.columns:
        return []
    groups = {}
    if s.split and s.split in t.columns:
        j = t.index(s.split)
        for i in rows:
            groups.setdefault(_text(t.rows[i][j]), []).append(i)
    else:
        groups[''] = rows
    xs_all = t.values(s.x) if s.x in t.columns else list(range(len(t.rows)))
    numeric_x = s.x not in t.columns or t.is_numeric(s.x)
    cats = []
    if not numeric_x:
        for i in rows:
            c = _text(xs_all[i])
            if c not in cats:
                cats.append(c)
    yv = t.numbers(s.y)
    ev = t.numbers(s.err) if s.err and s.err in t.columns else None
    parts = []
    for key, idx in groups.items():
        if numeric_x:
            x = np.array([_num(xs_all[i]) for i in idx], float)
        else:
            x = np.array([cats.index(_text(xs_all[i])) for i in idx], float)
        y = yv[idx]
        e = ev[idx] if ev is not None else None
        n = np.ones(len(idx), int)
        if s.agg in ('mean', 'median'):
            if s.agg_by and s.agg_by in t.columns:
                by = [_text(v) for v in np.array(t.values(s.agg_by), object)[idx]]
            else:
                by = [f'{v:.9g}' for v in x]
            order, bucket = [], {}
            for k, xi, yi in zip(by, x, y):
                if k not in bucket:
                    order.append(k)
                    bucket[k] = ([], [])
                bucket[k][0].append(xi)
                bucket[k][1].append(yi)
            ax_, ay, ae, an = [], [], [], []
            for k in order:
                bx, byv = np.array(bucket[k][0]), np.array(bucket[k][1])
                fin = np.isfinite(byv)
                ax_.append(float(np.nanmean(bx)) if np.isfinite(bx).any() else math.nan)
                if fin.any():
                    ay.append(float(np.mean(byv[fin]) if s.agg == 'mean' else np.median(byv[fin])))
                else:
                    ay.append(math.nan)
                ae.append(_err(byv, s.agg_err))
                an.append(int(fin.sum()))
            x, y, n = np.array(ax_), np.array(ay), np.array(an)
            e = np.array(ae) if s.agg_err != 'none' else None
        order = np.argsort(x, kind='stable')
        parts.append({'key': key, 'x': x[order], 'y': y[order],
                      'err': e[order] if e is not None else None, 'n': n[order], 'ticks': cats})
    return parts


def category_values(s: Series, tables: dict) -> dict:
    """{category: values} of a bar / box / violin / strip series (x '' = one
    category named after the series)."""
    t, rows = _rows_of(s, tables)
    if t is None or s.y not in t.columns:
        return {}
    yv = t.numbers(s.y)
    out = {}
    cat = t.values(s.x) if s.x in t.columns else None
    for i in rows:
        k = _text(cat[i]) if cat is not None else (s.label or s.y)
        out.setdefault(k, []).append(yv[i])
    return {k: np.array(v, float) for k, v in out.items()}


def categories(spec: GraphSpec, tables: dict) -> list:
    cats = []
    for s in spec.series:
        if s.visible:
            cats += [c for c in category_values(s, tables) if c not in cats]
    return cats


def _label(s: Series, i: int) -> str:
    return s.label or s.y or f'series {i + 1}'


def plotted_table(spec: GraphSpec, tables: dict, only=None) -> Table:
    """Every value the graph draws, one row per point (only: series indexes)."""
    pick = [i for i, s in enumerate(spec.series) if s.visible and (only is None or i in only)]
    if spec.chart in CATEGORY_CHARTS:
        rows = []
        for i in pick:
            s = spec.series[i]
            for c, v in category_values(s, tables).items():
                rows += [[_label(s, i), c, float(x)] for x in v]
        return Table('그래프에 쓰인 데이터', ['series', 'category', 'value'], rows)
    if spec.chart == 'hist':
        rows = []
        for i in pick:
            s = spec.series[i]
            v = np.concatenate([p['y'] for p in xy_parts(_no_agg(s), tables)] or [np.zeros(0)])
            v = v[np.isfinite(v)]
            if not v.size:
                continue
            counts, edges = np.histogram(v, bins=spec.hist_bins or 'auto', density=spec.hist_density)
            rows += [[_label(s, i), float(a), float(b), float(c)]
                     for a, b, c in zip(edges[:-1], edges[1:], counts)]
        return Table('그래프에 쓰인 데이터', ['series', 'bin_from', 'bin_to',
                                       'density' if spec.hist_density else 'count'], rows)
    if spec.chart == 'heatmap':
        rows = []
        for i in pick:
            s = spec.series[i]
            t, idx = _rows_of(s, tables)
            if t is None:
                continue
            if s.z:
                xs, ys, zs = t.numbers(s.x), t.numbers(s.y), t.numbers(s.z)
                rows += [[_label(s, i), xs[j], ys[j], zs[j]] for j in idx]
            else:
                for p in xy_parts(s, tables):
                    rows += [[_label(s, i), a, b, ''] for a, b in zip(p['x'], p['y'])]
        return Table('그래프에 쓰인 데이터', ['series', 'x', 'y', 'z'], rows)
    rows = []
    agg = any(spec.series[i].agg != 'none' for i in pick)
    for i in pick:
        s = spec.series[i]
        for p in xy_parts(s, tables):
            ticks = p['ticks']
            for j in range(len(p['x'])):
                xv = ticks[int(p['x'][j])] if ticks else float(p['x'][j])
                e = float(p['err'][j]) if p['err'] is not None else ''
                rows.append([_label(s, i), p['key'], xv, float(p['y'][j]), e] + ([int(p['n'][j])] if agg else []))
    return Table('그래프에 쓰인 데이터', ['series', 'part', 'x', 'y', 'err'] + (['n'] if agg else []), rows)


def summary_table(spec: GraphSpec, tables: dict, only=None) -> Table:
    """n, mean, SD, SEM, median, min, max per series and category (bar, box, …)."""
    rows = []
    for i, s in enumerate(spec.series):
        if not s.visible or (only is not None and i not in only):
            continue
        for c, v in category_values(s, tables).items():
            v = v[np.isfinite(v)]
            n = int(v.size)
            rows.append([_label(s, i), c, n,
                         float(v.mean()) if n else math.nan, _err(v, 'sd') if n > 1 else math.nan,
                         _err(v, 'sem') if n > 1 else math.nan, float(np.median(v)) if n else math.nan,
                         float(v.min()) if n else math.nan, float(v.max()) if n else math.nan])
    return Table('그래프 요약 (평균 · SD · SEM)', ['series', 'category', 'n', 'mean', 'sd', 'sem', 'median',
                                              'min', 'max'], rows)


def _no_agg(s: Series) -> Series:
    d = asdict(s)
    d['agg'] = 'none'
    return Series(**d)


# ---------------------------------------------------------------------------
# drawing
# ---------------------------------------------------------------------------

def _font(f: Font, family: str) -> dict:
    d = {'size': f.size, 'weight': 'bold' if f.bold else 'normal',
         'style': 'italic' if f.italic else 'normal', 'color': f.color}
    if family:
        d['family'] = family
    return d


def _marker_kw(s: Series, color) -> dict:
    m = None if s.marker == 'none' else s.marker
    return dict(marker=m, ms=s.marker_size, mew=s.marker_edge, mec=color,
                mfc=color if s.marker_fill else 'white')


def _ls(s: Series):
    return 'none' if s.line_style == 'none' else s.line_style


def _draw_xy(ax, s: Series, i, tables, handles):
    from matplotlib.lines import Line2D

    color = s.color or PALETTE[i % len(PALETTE)]
    ecolor = s.err_color or color
    first = True
    ticks = []
    for p in xy_parts(s, tables):
        x, y, e = p['x'], p['y'], p['err']
        ticks = p['ticks'] or ticks
        if not len(x):
            continue
        style = s.style
        lw = s.line_width
        ls = _ls(s) if style != 'marker' else 'none'
        mk = _marker_kw(s, color) if style in ('line+marker', 'marker') else dict(marker=None)
        if style == 'step':
            ax.step(x, y, where='mid', color=color, lw=lw, ls=ls, alpha=s.alpha, zorder=2)
        elif style == 'area':
            ax.fill_between(x, y, color=color, alpha=s.alpha * 0.35, lw=0, zorder=1)
            ax.plot(x, y, color=color, lw=lw, ls=ls, alpha=s.alpha, zorder=2)
        else:
            ax.plot(x, y, color=color, lw=lw, ls=ls, alpha=s.alpha, zorder=3, **mk)
        if e is not None and s.err_style != 'none':
            ee = np.nan_to_num(e)
            if s.err_style == 'band':
                ax.fill_between(x, y - ee, y + ee, color=ecolor, alpha=0.2 * s.alpha, lw=0, zorder=1)
            else:
                ax.errorbar(x, y, yerr=ee, fmt='none', ecolor=ecolor, elinewidth=s.err_width,
                            capsize=s.capsize, capthick=s.err_width, alpha=s.alpha, zorder=2)
        if first and s.legend:
            h = Line2D([], [], color=color, lw=lw if style != 'marker' else 0,
                       ls=ls if style != 'marker' else 'none', alpha=s.alpha,
                       **(_marker_kw(s, color) if style in ('line+marker', 'marker') else {}))
            handles.append((h, _label(s, i)))
        first = False
    return ticks


def _draw_categories(ax, spec: GraphSpec, tables, handles):
    from matplotlib.patches import Patch

    cats = categories(spec, tables)
    shown = [(i, s) for i, s in enumerate(spec.series) if s.visible]
    n = max(len(shown), 1)
    w = spec.bar_width / n
    rng = np.random.default_rng(0)
    for j, (i, s) in enumerate(shown):
        color = s.color or PALETTE[i % len(PALETTE)]
        ecolor = s.err_color or color
        vals = category_values(s, tables)
        pos, data = [], []
        for k, c in enumerate(cats):
            if c in vals:
                v = vals[c][np.isfinite(vals[c])]
                pos.append(k - spec.bar_width / 2 + w * (j + 0.5))
                data.append(v)
        if not pos:
            continue
        pos = np.array(pos)
        if spec.chart == 'bar':
            means = [float(v.mean()) if v.size else math.nan for v in data]
            errs = [(_err(v, spec.bar_err) if spec.bar_err != 'none' else 0.0) for v in data]
            ax.bar(pos, means, w * 0.9, color=color, alpha=spec.bar_alpha, edgecolor=color,
                   linewidth=s.line_width, zorder=2)
            if spec.bar_err != 'none' and s.err_style != 'none':
                ax.errorbar(pos, means, yerr=np.nan_to_num(errs), fmt='none', ecolor=ecolor,
                            elinewidth=s.err_width, capsize=s.capsize, capthick=s.err_width, zorder=3)
        elif spec.chart == 'box':
            bp = ax.boxplot([v if v.size else [math.nan] for v in data], positions=pos, widths=w * 0.8,
                            patch_artist=True, showfliers=not spec.bar_points, manage_ticks=False)
            for b in bp['boxes']:
                b.set(facecolor=color, alpha=spec.bar_alpha, edgecolor=color, linewidth=s.line_width)
            for k in ('whiskers', 'caps', 'medians'):
                for ln in bp[k]:
                    ln.set(color=ecolor if k != 'medians' else color, linewidth=s.err_width
                           if k != 'medians' else s.line_width * 1.5)
        elif spec.chart == 'violin':
            ok = [k for k, v in enumerate(data) if v.size > 1]
            if ok:
                vp = ax.violinplot([data[k] for k in ok], positions=pos[ok], widths=w * 0.9,
                                   showmeans=False, showmedians=True, showextrema=False)
                for b in vp['bodies']:
                    b.set(facecolor=color, alpha=spec.bar_alpha, edgecolor=color, linewidth=s.line_width)
                if 'cmedians' in vp:
                    vp['cmedians'].set(color=color, linewidth=s.line_width * 1.5)
        elif spec.chart == 'strip':
            means = [float(v.mean()) if v.size else math.nan for v in data]
            errs = [(_err(v, spec.bar_err) if spec.bar_err != 'none' else 0.0) for v in data]
            half = w * 0.35
            ax.hlines(means, pos - half, pos + half, colors=color, linewidth=s.line_width * 1.5, zorder=4)
            if spec.bar_err != 'none' and s.err_style != 'none':
                ax.errorbar(pos, means, yerr=np.nan_to_num(errs), fmt='none', ecolor=ecolor,
                            elinewidth=s.err_width, capsize=s.capsize, capthick=s.err_width, zorder=4)
        if spec.bar_points or spec.chart == 'strip':
            for p, v in zip(pos, data):
                jit = rng.uniform(-1, 1, v.size) * w * spec.point_jitter * 2
                ax.plot(p + jit, v, ls='none', alpha=s.alpha, zorder=5, **_marker_kw(s, color))
        if s.legend:
            handles.append((Patch(facecolor=color, edgecolor=color, alpha=max(spec.bar_alpha, 0.35)),
                            _label(s, i)))
    ax.set_xticks(range(len(cats)))
    ax.set_xticklabels(cats)
    if cats:
        ax.set_xlim(-0.6, len(cats) - 0.4)


def _draw_hist(ax, spec: GraphSpec, tables, handles):
    from matplotlib.patches import Patch

    for i, s in enumerate(spec.series):
        if not s.visible:
            continue
        color = s.color or PALETTE[i % len(PALETTE)]
        v = np.concatenate([p['y'] for p in xy_parts(_no_agg(s), tables)] or [np.zeros(0)])
        v = v[np.isfinite(v)]
        if not v.size:
            continue
        ax.hist(v, bins=spec.hist_bins or 'auto', density=spec.hist_density,
                histtype='stepfilled' if spec.hist_fill else 'step', color=color,
                alpha=s.alpha * (0.5 if spec.hist_fill else 1), edgecolor=color, linewidth=s.line_width)
        if s.legend:
            handles.append((Patch(facecolor=color, edgecolor=color, alpha=0.5), _label(s, i)))


def _draw_heatmap(fig, ax, spec: GraphSpec, tables, handles):
    from matplotlib.colors import LogNorm, Normalize

    first = True
    for i, s in enumerate(spec.series):
        if not s.visible:
            continue
        t, idx = _rows_of(s, tables)
        if first and t is not None and s.z and s.z in t.columns:
            first = False
            xs, ys, zs = t.numbers(s.x)[idx], t.numbers(s.y)[idx], t.numbers(s.z)[idx]
            ux, uy = np.unique(xs[np.isfinite(xs)]), np.unique(ys[np.isfinite(ys)])
            if not ux.size or not uy.size:
                continue
            grid = np.full((uy.size, ux.size), np.nan)
            ix, iy = np.searchsorted(ux, xs), np.searchsorted(uy, ys)
            ok = np.isfinite(xs) & np.isfinite(ys)
            grid[iy[ok], ix[ok]] = zs[ok]
            dx = float(np.median(np.diff(ux))) if ux.size > 1 else 1.0
            dy = float(np.median(np.diff(uy))) if uy.size > 1 else 1.0
            pos = grid[np.isfinite(grid) & (grid > 0)]
            if spec.cmap_log and pos.size:
                norm = LogNorm(vmin=float(pos.min()), vmax=float(pos.max()))
                grid = np.where(grid > 0, grid, np.nan)
            else:
                norm = Normalize(vmin=float(np.nanmin(grid)), vmax=float(np.nanmax(grid)))
            im = ax.imshow(grid, origin='lower', aspect='auto', cmap=spec.cmap, norm=norm,
                           interpolation='nearest',
                           extent=(ux[0] - dx / 2, ux[-1] + dx / 2, uy[0] - dy / 2, uy[-1] + dy / 2))
            if spec.colorbar:
                cb = fig.colorbar(im, ax=ax, shrink=0.9)
                cb.set_label(s.label or s.z, fontdict=_font(spec.label_font, spec.font_family))
                cb.ax.tick_params(labelsize=spec.tick_font.size, labelcolor=spec.tick_font.color)
            continue
        _draw_xy(ax, s, i, tables, handles)  # overlays: regression line, thresholds


def _axis(ax, which, a: Axis, spec: GraphSpec, ticks_fixed=False):
    from matplotlib.ticker import AutoMinorLocator, MaxNLocator, MultipleLocator, NullLocator

    axis = ax.xaxis if which == 'x' else ax.yaxis
    if a.log:
        (ax.set_xscale if which == 'x' else ax.set_yscale)('log')
    if not a.auto_range and a.hi > a.lo and not (a.log and a.lo <= 0):
        (ax.set_xlim if which == 'x' else ax.set_ylim)(a.lo, a.hi)
    if not ticks_fixed and not a.log:
        lo, hi = (ax.get_xlim() if which == 'x' else ax.get_ylim())
        if not a.auto_step and a.step > 0 and abs(hi - lo) / a.step <= 500:
            axis.set_major_locator(MultipleLocator(a.step))
        else:
            axis.set_major_locator(MaxNLocator('auto'))
    if a.minor and not a.log:
        axis.set_minor_locator(AutoMinorLocator())
    elif not a.log:
        axis.set_minor_locator(NullLocator())
    tf = spec.tick_font
    ax.tick_params(axis=which, which='both', direction=a.tick_dir, width=spec.spine_width,
                   labelsize=tf.size, labelcolor=tf.color, color=tf.color, labelrotation=a.rotation)
    ax.tick_params(axis=which, which='major', length=3.5)
    ax.tick_params(axis=which, which='minor', length=2)
    label = a.label
    fd = _font(spec.label_font, spec.font_family)
    (ax.set_xlabel if which == 'x' else ax.set_ylabel)(label, fontdict=fd)


def _tick_fonts(ax, spec: GraphSpec):
    """Tick label weight / style / family (tick_params has no weight): set on the
    ticks the axis draws; new ticks copy them from the first one."""
    tf = spec.tick_font
    for axis in (ax.xaxis, ax.yaxis):
        ticks = axis.get_major_ticks(len(axis.get_majorticklocs()))
        for t in ticks[:1] or axis.get_major_ticks(1):
            for lab in (t.label1, t.label2):
                lab.set_fontweight('bold' if tf.bold else 'normal')
                lab.set_fontstyle('italic' if tf.italic else 'normal')
                if spec.font_family:
                    lab.set_family(spec.font_family)
        for t in ticks[1:]:
            t.label1.update_from(ticks[0].label1)


def draw(fig, spec: GraphSpec, tables) -> dict:
    """Draw the graph on a matplotlib Figure; returns the artists the window
    lets the user drag or edit: {'ax', 'legend', 'texts', 'title', 'xlabel', 'ylabel'}."""
    from matplotlib.lines import Line2D

    from . import frap  # noqa: F401  Korean font fallback for group / image names

    tabs = {t.name: t for t in tables} if not isinstance(tables, dict) else tables
    fig.clear()
    fig.set_facecolor(spec.background)
    ax = fig.add_subplot(111)
    ax.set_facecolor(spec.background)
    handles = []
    xticks = []
    if spec.chart in CATEGORY_CHARTS:
        _draw_categories(ax, spec, tabs, handles)
    elif spec.chart == 'hist':
        _draw_hist(ax, spec, tabs, handles)
    elif spec.chart == 'heatmap':
        _draw_heatmap(fig, ax, spec, tabs, handles)
    else:
        for i, s in enumerate(spec.series):
            if s.visible:
                xticks = _draw_xy(ax, s, i, tabs, handles) or xticks
        if xticks:
            ax.set_xticks(range(len(xticks)))
            ax.set_xticklabels(xticks)
    _axis(ax, 'x', spec.x, spec, ticks_fixed=spec.chart in CATEGORY_CHARTS or bool(xticks))
    _axis(ax, 'y', spec.y, spec)
    for side, on in (('top', spec.spine_top), ('right', spec.spine_right)):
        ax.spines[side].set_visible(on)
    for sp in ax.spines.values():
        sp.set_linewidth(spec.spine_width)
        sp.set_color(spec.tick_font.color)
    if spec.grid:
        ax.grid(True, color=spec.grid_color, lw=0.6, zorder=0)
        ax.set_axisbelow(True)
    else:
        ax.grid(False)
    title = ax.set_title(spec.title, fontdict=_font(spec.title_font, spec.font_family)) if spec.title else None
    for it in spec.legend_items:
        mk = None if it.marker == 'none' else it.marker
        handles.append((Line2D([], [], color=it.color, ls='none' if it.line_style == 'none' else it.line_style,
                               marker=mk, mfc=it.color if it.fill else 'white', mec=it.color, ms=5),
                        it.label))
    legend = None
    if spec.legend_show and handles:
        lf = spec.legend_font
        prop = {'size': lf.size, 'weight': 'bold' if lf.bold else 'normal',
                'style': 'italic' if lf.italic else 'normal'}
        if spec.font_family:
            prop['family'] = spec.font_family
        kw = dict(prop=prop, frameon=spec.legend_frame, ncols=max(1, spec.legend_ncol),
                  title=spec.legend_title or None, title_fontproperties=dict(prop),
                  handletextpad=0.4, borderaxespad=0.3, alignment='left')
        loc = spec.legend_loc
        if loc == 'above':
            kw.update(loc='lower left', bbox_to_anchor=(0, 1.0))
        elif loc == 'right':
            kw.update(loc='upper left', bbox_to_anchor=(1.02, 1.0))
        elif loc == 'custom':
            kw.update(loc='lower left', bbox_to_anchor=(spec.legend_x, spec.legend_y),
                      bbox_transform=ax.transAxes)
        else:
            kw.update(loc=loc if loc in LEGEND_LOCS else 'best')
        legend = ax.legend([h for h, _ in handles], [lab for _, lab in handles], **kw)
        for txt in legend.get_texts():
            txt.set_color(lf.color)
        if legend.get_title() is not None:
            legend.get_title().set_color(lf.color)
        if loc == 'custom':
            legend.set_in_layout(False)
    texts = []
    for tb in spec.texts:
        d = _font(Font(tb.size, tb.bold, tb.italic, tb.color), spec.font_family)
        bbox = dict(boxstyle='square,pad=0.3', facecolor='white', edgecolor=tb.color, lw=0.8) \
            if tb.frame else None
        txt = ax.text(tb.x, tb.y, tb.text, transform=ax.transAxes, ha=tb.align, va='bottom',
                      fontdict=d, bbox=bbox, zorder=10, clip_on=False)
        txt.set_in_layout(False)
        texts.append(txt)
    _tick_fonts(ax, spec)
    return {'ax': ax, 'legend': legend, 'texts': texts, 'title': title,
            'xlabel': ax.xaxis.label, 'ylabel': ax.yaxis.label}


def save_figure(path, spec: GraphSpec, tables) -> str:
    """The graph as PNG / TIFF (spec.dpi), PDF or SVG at spec's size."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fig = Figure(figsize=(spec.width_in, spec.height_in), dpi=spec.dpi, layout='constrained')
    FigureCanvasAgg(fig)
    draw(fig, spec, tables)
    fig.savefig(path, dpi=spec.dpi, facecolor=spec.background)
    return str(path)


# ---------------------------------------------------------------------------
# helpers for the features
# ---------------------------------------------------------------------------

def series(table, x, y, label='', color='#000000', **kw) -> Series:
    return Series(table=table, x=x, y=y, label=label, color=color, **kw)


def measure_graph(rows: list, title: str, name: str, folder: str = '') -> GraphData | None:
    """A measurement table (rows of dicts): bars (mean ± SD, one dot per row)
    of its first mean / area column by group, image or ROI."""
    if not rows:
        return None
    t = Table.from_dicts('측정 결과', rows)
    nums = [c for c in t.numeric_columns() if c not in ('timepoint', 'label', 'band', 'n')]
    y = next((c for c in nums if c.endswith('_Mean') and '_particle_' not in c),
             next((c for c in nums if c.lower() in ('area', 'area_um2')), nums[0] if nums else ''))
    if not y:
        return None
    by = ''
    for c in ('group', 'image', 'region', 'roi'):
        if c in t.columns and len(set(t.values(c))) > 1:
            by = c
            break
    spec = GraphSpec(chart='bar', series=[Series(table=t.name, x=by, y=y, label=y, color='#1f77b4',
                                                 marker_size=3.0)],
                     legend_show=False)
    spec.x.label = by
    spec.y.label = y
    return GraphData(title, [t], spec, name, folder)
