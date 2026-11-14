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
import re
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
    'corr': '상관 행렬',
    'corrcmp': '상관 비교 (그룹 사이)',
}
CORR_CHARTS = ('corr', 'corrcmp')
REG_FITS = {'ls': '최소제곱', 'log': 'log 값으로 맞춤', 'origin': '원점 통과'}
QUADRANTS = {'none': '없음', 'mean': '평균에서', 'median': '중앙값에서'}
COMPARE = {'ab': 'A 대 B', 'all': '모든 그룹'}
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
    labels: dict = field(default_factory=dict)       # column -> shown name (with unit)
    column_sets: dict = field(default_factory=dict)  # set name -> columns (X / Y defaults)

    def label(self, col) -> str:
        return self.labels.get(col, col) if self.labels else col

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


def safe_name(name: str) -> str:
    """A file-name part from a graph / table name."""
    return re.sub(r'[\\/:*?"<>|\s]+', '_', str(name)).strip('_') or 'graph'


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
    # rows whose hide_col value is in hide are left out (그룹 not drawn)
    hide_col: str = ''
    hide: list = field(default_factory=list)
    x_cat: bool = False  # x values as categories (also numbers)
    y_cat: bool = False  # y values as categories (XY)
    auto: bool = False   # made from the spec's 축 배치 (Mapping)
    key: str = ''        # which Y column / colour value an automatic series is (its name may change)


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
    unit: str = ''       # shown after the name: 'Time (min)'
    scale: float = 1.0   # values are multiplied by this (unit change, e.g. s -> min = 1/60)

    def title(self) -> str:
        """The axis name with its unit; a unit already in brackets at the end
        of the name is replaced."""
        if not self.unit:
            return self.label
        base = re.sub(r'\s*[(\[][^()\[\]]*[)\]]\s*$', '', self.label)
        return f'{base} ({self.unit})' if base else self.unit


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
class Mapping:
    """축 배치 (owner request 2026-11-09): which columns of one table go on
    which axis, each axis as 범주 (categories) or 값 (numbers), several Y
    columns, the colour split and the error bars. The series are made from
    it (build_series); series of other tables stay as overlays."""

    on: bool = False
    table: str = ''
    x: str = ''
    x_cat: bool = True
    ys: list = field(default_factory=list)
    y_cat: bool = False
    z: str = ''          # heat map value
    color: str = '@y'    # '' = one colour, '@y' = one per Y column, else a column
    err: str = 'sd'      # error bars of means (ERR_KINDS)
    agg: str = 'none'    # XY: points of the same x as their mean / median
    unit: str = 'rows'   # 점 하나 = rows / image (image mean) / group (group mean)


@dataclass
class Calc:
    """상관 계산 and XY 회귀 (owner request 2026-11-14): the columns of the
    correlation matrix, the method, filters, the groups compared and the
    regression / quadrant overlay of XY graphs."""

    table: str = ''
    method: str = 'r'       # r (Pearson) / rho (Spearman)
    xset: str = ''          # column set ('' = every number column) unless xs
    xs: list = field(default_factory=list)
    yset: str = '@x'        # '@x' = same as X
    ys: list = field(default_factory=list)
    log_x: bool = False
    log_y: bool = False
    where: str = ''
    equals: str = ''
    group: str = ''         # 상관 비교: the category column
    a: str = ''
    b: str = ''
    compare: str = 'ab'     # ab / all
    correction: str = 'none'
    numbers: bool = True    # values in the cells (≤ 100 cells)
    reg_on: bool = False
    reg_fit: str = 'ls'
    reg_text: bool = True
    reg_split: bool = False  # one line per colour
    quadrant: str = 'none'


@dataclass
class Stats:
    """유의성 표시 (owner request 2026-11-09): the test, the pairs compared
    and how the marks look. The look's initial values come from Preferences."""

    on: bool = False
    series: str = ''      # label of the series whose categories are compared ('' = first)
    paired: bool = False
    method: str = 'auto'  # 'auto' = recommended for the data, else stats.METHODS
    tail: str = 'two'
    correction: str = 'holm'
    alpha: float = 0.05
    pairs_mode: str = 'all'  # all / ref / custom
    ref: str = ''
    pairs: list = field(default_factory=list)  # [[a, b], ...] when custom
    display: str = 'stars'   # stars / p / both
    levels: int = 4
    ns: bool = True
    bracket: str = 'tick'    # tick (ends bent down) / line
    line_width: float = 1.0
    tip: float = 0.02        # bracket ends, fraction of the value axis
    gap: float = 0.06        # space between brackets, fraction of the value axis
    font_family: str = ''    # '' = the graph's font
    font_size: float = 10.0
    bold: bool = False
    caption: bool = True


STATS_LOOK = ('display', 'levels', 'ns', 'tail', 'alpha', 'bracket', 'line_width', 'tip', 'gap',
              'font_family', 'font_size', 'bold', 'caption')


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
    # where the parts sit: automatic, or moved / resized on the graph
    plot_auto: bool = True   # plot area laid out automatically
    plot_x: float = 0.15     # plot area: left, bottom, width, height (figure fractions)
    plot_y: float = 0.15
    plot_w: float = 0.75
    plot_h: float = 0.7
    title_auto: bool = True
    title_x: float = 0.5     # axes fractions (centre, bottom of the text)
    title_y: float = 1.03
    xlabel_auto: bool = True
    xlabel_x: float = 0.5
    xlabel_y: float = -0.12
    ylabel_auto: bool = True
    ylabel_x: float = -0.12
    ylabel_y: float = 0.5
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
    mapping: Mapping = field(default_factory=Mapping)
    horizontal: bool = False  # categories on the y axis (Y 범주, X 값)
    cat_order: list = field(default_factory=list)   # order of the 그룹 (categories / colours)
    cat_hidden: list = field(default_factory=list)  # 그룹 left out
    stats: Stats = field(default_factory=Stats)
    calc: Calc = field(default_factory=Calc)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> 'GraphSpec':
        return _build(cls, d)

    def copy(self) -> 'GraphSpec':
        return GraphSpec.from_dict(self.to_dict())


_NESTED = {'x': Axis, 'y': Axis, 'title_font': Font, 'label_font': Font, 'tick_font': Font,
           'legend_font': Font, 'mapping': Mapping, 'stats': Stats,
           'calc': Calc}
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
                if isinstance(cur, list):
                    v = list(v) if isinstance(v, (list, tuple)) else cur
                elif isinstance(cur, bool):
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
        for k in ('label', 'auto_range', 'lo', 'hi', 'auto_step', 'step', 'log', 'unit', 'scale'):
            setattr(mine, k, getattr(theirs, k))
    out.texts = [TextBox(**asdict(t)) for t in spec.texts]
    out.legend_items = [LegendItem(**asdict(t)) for t in spec.legend_items]
    out.legend_title = spec.legend_title
    out.mapping = _build(Mapping, asdict(spec.mapping))
    out.horizontal, out.cat_order, out.cat_hidden = spec.horizontal, list(spec.cat_order), list(spec.cat_hidden)
    st = _build(Stats, asdict(spec.stats))
    for k in STATS_LOOK:
        setattr(st, k, getattr(style.stats, k))
    out.stats = st
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
    if s.hide_col and s.hide and s.hide_col in t.columns:
        j, hid = t.index(s.hide_col), {str(v) for v in s.hide}
        rows = [i for i in rows if _text(t.rows[i][j]) not in hid]
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


def _ordered(vals, order) -> list:
    """vals in the order of `order` first (the 그룹 list), then as they come."""
    if not order:
        return list(vals)
    pos = {str(v): i for i, v in enumerate(order)}
    return sorted(vals, key=lambda v: (pos.get(str(v), len(pos)), 0))


def _texts(t: Table, col, rows) -> list:
    vals = t.values(col)
    out = []
    for i in rows:
        c = _text(vals[i])
        if c not in out:
            out.append(c)
    return out


def axis_cats(spec: 'GraphSpec', tables: dict, which: str) -> list:
    """The categories of an XY axis shown as 범주 ('x' / 'y'; [] = numbers),
    shared by every series."""
    cats = []
    for s in spec.series:
        if not s.visible:
            continue
        t, rows = _rows_of(s, tables)
        col = s.x if which == 'x' else s.y
        if t is None or col not in t.columns:
            continue
        flag = s.x_cat if which == 'x' else s.y_cat
        if flag or not t.is_numeric(col):
            cats += [c for c in _texts(t, col, rows) if c not in cats]
    return _ordered(cats, spec.cat_order)


def xy_parts(s: Series, tables: dict, sx=1.0, sy=1.0, xcats=None, ycats=None) -> list[dict]:
    """[{key, x, y, err, n}]: one part per split value (one part without split);
    x, y numeric; categories (text columns, or x_cat / y_cat) become 0, 1, …
    with the names in 'ticks' (xcats / ycats: the shared list of every series)."""
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
    numeric_x = s.x not in t.columns or (t.is_numeric(s.x) and not s.x_cat)
    cats = []
    if not numeric_x:
        cats = list(xcats) if xcats else _texts(t, s.x, rows)
    ycat = s.y_cat or not t.is_numeric(s.y)
    if ycat:
        ycl = list(ycats) if ycats else _texts(t, s.y, rows)
        yraw = t.values(s.y)
        yv = np.array([ycl.index(_text(v)) if _text(v) in ycl else math.nan for v in yraw], float)
    else:
        yv = t.numbers(s.y)
    ev = t.numbers(s.err) if s.err and s.err in t.columns else None
    parts = []
    for key, idx in groups.items():
        if numeric_x:
            x = np.array([_num(xs_all[i]) for i in idx], float)
        else:
            x = np.array([cats.index(_text(xs_all[i])) if _text(xs_all[i]) in cats else math.nan
                          for i in idx], float)
        y = yv[idx]
        e = ev[idx] if ev is not None else None
        n = np.ones(len(idx), int)
        if s.agg in ('mean', 'median') and not ycat:
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
        if numeric_x and sx != 1:
            x = x * sx
        if sy != 1 and not ycat:
            y = y * sy
            e = e * abs(sy) if e is not None else None
        order = np.argsort(x, kind='stable')
        parts.append({'key': key, 'x': x[order], 'y': y[order],
                      'err': e[order] if e is not None else None, 'n': n[order], 'ticks': cats,
                      'yticks': ycl if ycat else []})
    return parts


def category_values(s: Series, tables: dict, sy=1.0) -> dict:
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
    return {k: np.array(v, float) * sy for k, v in out.items()}


def categories(spec: GraphSpec, tables: dict) -> list:
    cats = []
    for s in spec.series:
        if s.visible:
            cats += [c for c in category_values(s, tables) if c not in cats]
    return _ordered(cats, spec.cat_order)


def _label(s: Series, i: int) -> str:
    return s.label or s.y or f'series {i + 1}'


def plotted_table(spec: GraphSpec, tables: dict, only=None) -> Table:
    """Every value the graph draws, one row per point (only: series indexes)."""
    if spec.chart in CORR_CHARTS:
        return corr_long_table(spec, tables)
    tables = view_tables(spec, tables)
    pick = [i for i, s in enumerate(spec.series) if s.visible and (only is None or i in only)]
    if spec.chart in CATEGORY_CHARTS:
        rows = []
        for i in pick:
            s = spec.series[i]
            for c, v in category_values(s, tables, _vscale(spec)).items():
                rows += [[_label(s, i), c, float(x)] for x in v]
        return Table('그래프에 쓰인 데이터', ['series', 'category', 'value'], rows)
    if spec.chart == 'hist':
        rows = []
        for i in pick:
            s = spec.series[i]
            v = np.concatenate([p['y'] for p in xy_parts(_no_agg(s), tables, sy=spec.x.scale)]
                               or [np.zeros(0)])
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
                xs, ys, zs = t.numbers(s.x) * spec.x.scale, t.numbers(s.y) * spec.y.scale, t.numbers(s.z)
                rows += [[_label(s, i), xs[j], ys[j], zs[j]] for j in idx]
            else:
                for p in xy_parts(s, tables, spec.x.scale, spec.y.scale):
                    rows += [[_label(s, i), a, b, ''] for a, b in zip(p['x'], p['y'])]
        return Table('그래프에 쓰인 데이터', ['series', 'x', 'y', 'z'], rows)
    rows = []
    agg = any(spec.series[i].agg != 'none' for i in pick)
    xc, yc = axis_cats(spec, tables, 'x'), axis_cats(spec, tables, 'y')
    for i in pick:
        s = spec.series[i]
        for p in xy_parts(s, tables, spec.x.scale, spec.y.scale, xc, yc):
            ticks, yt = p['ticks'], p['yticks']
            for j in range(len(p['x'])):
                if not (np.isfinite(p['x'][j]) and np.isfinite(p['y'][j])):
                    continue
                xv = ticks[int(p['x'][j])] if ticks else float(p['x'][j])
                if yt:
                    rows.append([_label(s, i), p['key'], xv, yt[int(p['y'][j])], ''] +
                                ([int(p['n'][j])] if agg else []))
                    continue
                e = float(p['err'][j]) if p['err'] is not None else ''
                rows.append([_label(s, i), p['key'], xv, float(p['y'][j]), e] + ([int(p['n'][j])] if agg else []))
    return Table('그래프에 쓰인 데이터', ['series', 'part', 'x', 'y', 'err'] + (['n'] if agg else []), rows)


def summary_table(spec: GraphSpec, tables: dict, only=None) -> Table:
    """n, mean, SD, SEM, median, min, max per series and category (bar, box, …)."""
    tables = view_tables(spec, tables)
    rows = []
    for i, s in enumerate(spec.series):
        if not s.visible or (only is not None and i not in only):
            continue
        for c, v in category_values(s, tables, _vscale(spec)).items():
            v = v[np.isfinite(v)]
            n = int(v.size)
            rows.append([_label(s, i), c, n,
                         float(v.mean()) if n else math.nan, _err(v, 'sd') if n > 1 else math.nan,
                         _err(v, 'sem') if n > 1 else math.nan, float(np.median(v)) if n else math.nan,
                         float(v.min()) if n else math.nan, float(v.max()) if n else math.nan])
    return Table('그래프 요약 (평균 · SD · SEM)', ['series', 'category', 'n', 'mean', 'sd', 'sem', 'median',
                                              'min', 'max'], rows)


def _vscale(spec: GraphSpec) -> float:
    """Scale of the value axis of a category chart."""
    return spec.x.scale if spec.horizontal else spec.y.scale


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


def _draw_xy(ax, s: Series, i, tables, handles, sx=1.0, sy=1.0, xcats=None, ycats=None):
    from matplotlib.lines import Line2D

    color = s.color or PALETTE[i % len(PALETTE)]
    ecolor = s.err_color or color
    first = True
    ticks = []
    for p in xy_parts(s, tables, sx, sy, xcats, ycats):
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


def _orient(horiz) -> dict:
    """boxplot / violinplot orientation (matplotlib 3.10 'orientation', older 'vert')."""
    import matplotlib

    new = tuple(int(x) for x in matplotlib.__version__.split('.')[:2]) >= (3, 10)
    if new:
        return {'orientation': 'horizontal' if horiz else 'vertical'}
    return {'vert': not horiz}


def _draw_categories(ax, spec: GraphSpec, tables, handles) -> dict:
    """Bars / points / boxes / violins per category. Series that share a
    category stand side by side; a series alone in its categories (colour =
    the category) sits in the middle. Returns {(series index, category):
    (position, top of what is drawn)} for the significance brackets."""
    from matplotlib.patches import Patch

    horiz = spec.horizontal
    cats = categories(spec, tables)
    shown = [(i, s) for i, s in enumerate(spec.series) if s.visible]
    vals_of = {i: category_values(s, tables, _vscale(spec)) for i, s in shown}
    present = {c: [i for i, _s in shown if c in vals_of[i]] for c in cats}
    n = max([len(v) for v in present.values()] or [1])
    w = spec.bar_width / max(n, 1)
    rng = np.random.default_rng(0)
    where = {}

    def pt(p, v):  # (category position, value) -> (x, y)
        return (v, p) if horiz else (p, v)

    for i, s in shown:
        before = set(ax.get_children())
        color = s.color or PALETTE[i % len(PALETTE)]
        ecolor = s.err_color or color
        vals = vals_of[i]
        pos, data, names = [], [], []
        for k, c in enumerate(cats):
            if c in vals:
                v = vals[c][np.isfinite(vals[c])]
                m = len(present[c])
                pos.append(k - m * w / 2 + w * (present[c].index(i) + 0.5))
                data.append(v)
                names.append(c)
        if not pos:
            continue
        pos = np.array(pos)
        tops = [float(v.max()) if v.size else math.nan for v in data]
        means = [float(v.mean()) if v.size else math.nan for v in data]
        errs = [(_err(v, spec.bar_err) if spec.bar_err != 'none' else 0.0) for v in data]
        if spec.chart == 'bar':
            (ax.barh if horiz else ax.bar)(pos, means, w * 0.9, color=color, alpha=spec.bar_alpha,
                                           edgecolor=color, linewidth=s.line_width, zorder=2)
            if spec.bar_err != 'none' and s.err_style != 'none':
                ek = {'xerr' if horiz else 'yerr': np.nan_to_num(errs)}
                ax.errorbar(*pt(pos, means), **ek, fmt='none', ecolor=ecolor, elinewidth=s.err_width,
                            capsize=s.capsize, capthick=s.err_width, zorder=3)
                tops = [max(t, m + (e if np.isfinite(e) else 0)) for t, m, e in zip(tops, means, errs)]
            if not spec.bar_points:
                tops = [m + (e if np.isfinite(e) else 0) for m, e in zip(means, errs)]
        elif spec.chart == 'box':
            bp = ax.boxplot([v if v.size else [math.nan] for v in data], positions=pos, widths=w * 0.8,
                            patch_artist=True, showfliers=not spec.bar_points, manage_ticks=False,
                            **_orient(horiz))
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
                                   showmeans=False, showmedians=True, showextrema=False,
                                   **_orient(horiz))
                for b in vp['bodies']:
                    b.set(facecolor=color, alpha=spec.bar_alpha, edgecolor=color, linewidth=s.line_width)
                if 'cmedians' in vp:
                    vp['cmedians'].set(color=color, linewidth=s.line_width * 1.5)
        elif spec.chart == 'strip':
            half = w * 0.35
            (ax.vlines if horiz else ax.hlines)(means, pos - half, pos + half, colors=color,
                                                linewidth=s.line_width * 1.5, zorder=4)
            if spec.bar_err != 'none' and s.err_style != 'none':
                ek = {'xerr' if horiz else 'yerr': np.nan_to_num(errs)}
                ax.errorbar(*pt(pos, means), **ek, fmt='none', ecolor=ecolor,
                            elinewidth=s.err_width, capsize=s.capsize, capthick=s.err_width, zorder=4)
                tops = [max(t, m + (e if np.isfinite(e) else 0)) for t, m, e in zip(tops, means, errs)]
        if spec.bar_points or spec.chart == 'strip':
            for p, v in zip(pos, data):
                jit = rng.uniform(-1, 1, v.size) * w * spec.point_jitter * 2
                ax.plot(*pt(p + jit, v), ls='none', alpha=s.alpha, zorder=5, **_marker_kw(s, color))
        for p, c, t in zip(pos, names, tops):
            where[(i, c)] = (float(p), t)
        for a in set(ax.get_children()) - before:  # the window picks a series by its artists
            a.set_gid(f'series:{i}')
        if s.legend:
            handles.append((Patch(facecolor=color, edgecolor=color, alpha=max(spec.bar_alpha, 0.35)),
                            _label(s, i)))
    if horiz:
        ax.set_yticks(range(len(cats)))
        ax.set_yticklabels(cats)
        if cats:
            ax.set_ylim(len(cats) - 0.4, -0.6)  # first category on top
    else:
        ax.set_xticks(range(len(cats)))
        ax.set_xticklabels(cats)
        if cats:
            ax.set_xlim(-0.6, len(cats) - 0.4)
    return where


# ---- significance (stats.py) ----

def stats_options(spec: GraphSpec, tables: dict) -> dict:
    """What a significance test can compare: {name: ({category: values},
    [series indexes])}. Series of one Y column that sit alone in their
    categories (colour = the category) count as one; others one each."""
    tabs = view_tables(spec, tables)
    shown = [(i, s) for i, s in enumerate(spec.series) if s.visible]
    vals = {i: category_values(s, tabs, _vscale(spec)) for i, s in shown}
    cats = categories(spec, tabs)
    keys = {}
    for i, s in shown:
        keys.setdefault(s.y if s.auto else f'#{i}', []).append(i)
    out = {}
    for k, idx in keys.items():
        seen, disjoint = set(), True
        for i in idx:
            if seen & set(vals[i]):
                disjoint = False
            seen |= set(vals[i])
        if disjoint and (len(idx) > 1 or k.startswith('#') is False):
            merged = {}
            for i in idx:
                merged.update(vals[i])
            name = k if not k.startswith('#') else _label(spec.series[idx[0]], idx[0])
            out[name] = ({c: merged[c] for c in cats if c in merged}, idx)
        else:
            for i in idx:
                out[_label(spec.series[i], i)] = ({c: vals[i][c] for c in cats if c in vals[i]}, [i])
    return out


def stats_groups(spec: GraphSpec, tables: dict) -> tuple[dict, list]:
    """{category: values} compared by the test and the series they come from."""
    opts = stats_options(spec, tables)
    if not opts:
        return {}, []
    return opts.get(spec.stats.series) or next(iter(opts.values()))


def stats_result(spec: GraphSpec, tables: dict):
    from . import stats as ST

    groups, _pick = stats_groups(spec, tables)
    st = spec.stats
    pairs = ST.pairs_for(list(groups), st.pairs_mode, st.ref, st.pairs)
    return ST.run(groups, st.method, pairs, st.tail, st.correction, st.paired, st.alpha)


def _draw_stats(ax, spec: GraphSpec, tables, where: dict, res):
    """Brackets with stars / p values over the compared categories."""
    from . import stats as ST

    st = spec.stats
    groups, pick = stats_groups(spec, tables)
    cats = list(groups)
    horiz = spec.horizontal

    def loc(c):
        return next((where[(i, c)] for i in pick if (i, c) in where), None)

    lo, hi = ax.get_xlim() if horiz else ax.get_ylim()
    span = abs(hi - lo) or 1.0
    gap, tip = st.gap * span, st.tip * span
    items = []
    for a, b, p in res.pairs:
        text = ST.mark(p, st.display, st.levels, st.alpha, st.ns)
        la, lb = loc(a), loc(b)
        if not text or la is None or lb is None:
            continue
        items.append((abs(cats.index(a) - cats.index(b)), la, lb, text, a, b))
    items.sort(key=lambda t: t[0])
    placed = []
    font = {'size': st.font_size, 'weight': 'bold' if st.bold else 'normal',
            'color': spec.tick_font.color}
    fam = st.font_family or spec.font_family
    if fam:
        font['family'] = fam
    top_all = max([v[1] for v in where.values() if np.isfinite(v[1])] or [hi])
    peak = top_all
    for _d, la, lb, text, a, b in items:
        x0, x1 = sorted((la[0], lb[0]))
        inside = [v[1] for (i, c), v in where.items() if x0 - 1e-9 <= v[0] <= x1 + 1e-9 and np.isfinite(v[1])]
        y = max(inside or [top_all]) + gap
        for px0, px1, py in placed:
            if px0 <= x1 + 1e-9 and x0 <= px1 + 1e-9:
                y = max(y, py + gap * (1.6 if st.display != 'stars' else 1.3))
        placed.append((x0, x1, y))
        if st.bracket == 'tick':
            cs, vs = [x0, x0, x1, x1], [y - tip, y, y, y - tip]
        else:
            cs, vs = [x0, x1], [y, y]
        xs, ys = (vs, cs) if horiz else (cs, vs)
        ax.plot(xs, ys, color=spec.tick_font.color, lw=st.line_width, solid_capstyle='butt', zorder=6,
                gid='stats', clip_on=False)
        mid = (x0 + x1) / 2
        if horiz:
            ax.text(y + gap * 0.15, mid, text, ha='left', va='center', rotation=270, fontdict=font,
                    zorder=7, gid='stats')
        else:
            ax.text(mid, y + (gap * 0.05 if text != 'ns' else gap * 0.12), text, ha='center',
                    va='bottom', fontdict=font, zorder=7, gid='stats')
        peak = max(peak, y)
    if placed:  # room for the last marks (autoscaled axes)
        room = peak + gap * (1.6 if st.display != 'stars' else 1.1)
        if horiz:
            ax.plot([room], [cats and 0], alpha=0, gid='stats')
        else:
            ax.plot([cats and 0], [room], alpha=0, gid='stats')


def _draw_hist(ax, spec: GraphSpec, tables, handles):
    from matplotlib.patches import Patch

    for i, s in enumerate(spec.series):
        if not s.visible:
            continue
        color = s.color or PALETTE[i % len(PALETTE)]
        v = np.concatenate([p['y'] for p in xy_parts(_no_agg(s), tables, sy=spec.x.scale)] or [np.zeros(0)])
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
            xs, ys, zs = (t.numbers(s.x)[idx] * spec.x.scale, t.numbers(s.y)[idx] * spec.y.scale,
                          t.numbers(s.z)[idx])
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
        _draw_xy(ax, s, i, tables, handles, spec.x.scale, spec.y.scale)  # overlays: regression line, thresholds


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
    fd = _font(spec.label_font, spec.font_family)
    (ax.set_xlabel if which == 'x' else ax.set_ylabel)(a.title(), fontdict=fd)
    if which == 'x' and not spec.xlabel_auto:
        ax.xaxis.set_label_coords(spec.xlabel_x, spec.xlabel_y)
    if which == 'y' and not spec.ylabel_auto:
        ax.yaxis.set_label_coords(spec.ylabel_x, spec.ylabel_y)


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

    tabs = view_tables(spec, tables)
    fig.clear()
    fig.set_facecolor(spec.background)
    if spec.chart in CORR_CHARTS:
        fig.set_layout_engine('constrained')
        ax, info = _draw_corr(fig, spec, tabs)
        title = ax.figure.suptitle(spec.title, **{'fontsize': spec.title_font.size,
                                                  'fontweight': 'bold' if spec.title_font.bold else 'normal'}) \
            if spec.title else None
        return {'ax': ax, 'legend': None, 'texts': [], 'title': title, 'xlabel': ax.xaxis.label,
                'ylabel': ax.yaxis.label, 'stats': None, **info}
    if spec.plot_auto:
        fig.set_layout_engine('constrained')
        ax = fig.add_subplot(111)
    else:  # placed by hand: no automatic layout
        fig.set_layout_engine('none')
        ax = fig.add_axes((spec.plot_x, spec.plot_y, max(spec.plot_w, 0.02), max(spec.plot_h, 0.02)))
    ax.set_facecolor(spec.background)
    handles = []
    xticks, yticks = [], []
    stats_res = None
    cat = spec.chart in CATEGORY_CHARTS
    if cat:
        where = _draw_categories(ax, spec, tabs, handles)
        if spec.stats.on:
            try:
                stats_res = stats_result(spec, tabs)
                _draw_stats(ax, spec, tabs, where, stats_res)
            except Exception:  # noqa: BLE001  a test that cannot run draws no marks
                import traceback

                traceback.print_exc()
    elif spec.chart == 'hist':
        _draw_hist(ax, spec, tabs, handles)
    elif spec.chart == 'heatmap':
        _draw_heatmap(fig, ax, spec, tabs, handles)
    else:
        xc, yc = axis_cats(spec, tabs, 'x'), axis_cats(spec, tabs, 'y')
        for i, s in enumerate(spec.series):
            if s.visible:
                before = set(ax.get_children())
                xticks = _draw_xy(ax, s, i, tabs, handles, spec.x.scale, spec.y.scale, xc, yc) or xticks
                for a in set(ax.get_children()) - before:  # the window picks a series by its artists
                    a.set_gid(f'series:{i}')
        if xticks:
            ax.set_xticks(range(len(xticks)))
            ax.set_xticklabels(xticks)
        if yc:
            yticks = yc
            ax.set_yticks(range(len(yc)))
            ax.set_yticklabels(yc)
        if spec.calc.reg_on and not xticks and not yc:
            _draw_regression(ax, spec, tabs)
    _axis(ax, 'x', spec.x, spec, ticks_fixed=(cat and not spec.horizontal) or bool(xticks))
    _axis(ax, 'y', spec.y, spec, ticks_fixed=(cat and spec.horizontal) or bool(yticks))
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
    title = None
    if spec.title and spec.title_auto:
        title = ax.set_title(spec.title, fontdict=_font(spec.title_font, spec.font_family))
    elif spec.title:
        title = ax.text(spec.title_x, spec.title_y, spec.title, transform=ax.transAxes, ha='center',
                        va='bottom', fontdict=_font(spec.title_font, spec.font_family), clip_on=False)
        title.set_in_layout(False)
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
        if loc == 'custom' or not spec.plot_auto:
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
            'xlabel': ax.xaxis.label, 'ylabel': ax.yaxis.label, 'stats': stats_res}


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


# ---------------------------------------------------------------------------
# 축 배치 (Mapping) -> series, 그룹
# ---------------------------------------------------------------------------

def value_columns(spec: GraphSpec) -> list:
    """The Y columns the mapping draws as values (categories excluded)."""
    m = spec.mapping
    if spec.chart in CATEGORY_CHARTS and m.y_cat and not m.x_cat:
        return [m.x] if m.x else []
    if spec.chart in CATEGORY_CHARTS and m.y_cat:
        return []
    return [y for y in m.ys if y]


def category_column(spec: GraphSpec) -> str:
    """The column whose values are the categories ('' = none)."""
    m = spec.mapping
    if spec.chart in CATEGORY_CHARTS:
        if m.y_cat and not m.x_cat:
            return m.ys[0] if m.ys else ''
        return m.x
    if spec.chart == 'xy':
        if m.x_cat and m.x:
            return m.x
        if m.y_cat and m.ys:
            return m.ys[0]
    return ''


def group_column(spec: GraphSpec) -> str:
    """The column the 그룹 list picks values of: the category axis, else the
    colour column."""
    c = category_column(spec)
    if c:
        return c
    col = spec.mapping.color
    return col if col and col != '@y' else ''


def group_values(spec: GraphSpec, tables: dict) -> list:
    """[(value, n rows)] of the group column, in the 그룹 order."""
    tabs = tables if isinstance(tables, dict) else {t.name: t for t in tables}
    col = group_column(spec)
    t = tabs.get(spec.mapping.table)
    if t is None or col not in t.columns:
        return []
    counts = {}
    for v in t.values(col):
        k = _text(v)
        counts[k] = counts.get(k, 0) + 1
    return [(k, counts[k]) for k in _ordered(list(counts), spec.cat_order)]


def build_series(spec: GraphSpec, tables: dict) -> GraphSpec:
    """Make spec.series from spec.mapping (when on): one series per Y column
    and colour value; styles of series with the same name are kept, series of
    other tables stay (overlays such as fitted curves)."""
    m = spec.mapping
    tabs = tables if isinstance(tables, dict) else {t.name: t for t in tables}
    t = tabs.get(m.table)
    if not m.on or t is None:
        return spec
    old = {(s.key or s.label): s for s in spec.series if s.table == m.table}
    keep = [s for s in spec.series if s.table != m.table]
    cat = spec.chart in CATEGORY_CHARTS
    spec.horizontal = bool(cat and m.y_cat and not m.x_cat)
    gcol = group_column(spec)
    if cat:
        cat_col = category_column(spec)
        vals = value_columns(spec)
    elif spec.chart == 'hist':
        cat_col, vals = '', [y for y in m.ys if y]
    else:
        cat_col, vals = m.x, [y for y in m.ys if y][:1 if spec.chart == 'heatmap' else None]
    vals = [v for v in vals if v in t.columns]
    color = m.color
    if color not in ('', '@y') and color not in t.columns:
        color = '@y'
    made = []
    if color in ('', '@y'):
        for v in vals:
            made.append((v, '', '', v))
    else:
        cv = _ordered(_texts(t, color, range(len(t.rows))), spec.cat_order if color == gcol else [])
        hid = set(spec.cat_hidden) if color == gcol else set()
        for v in vals:
            for c in cv:
                if c in hid:
                    continue
                made.append((v, color, c, c if len(vals) == 1 else f'{v} · {c}'))
    out = []
    for k, (y, where, equals, label) in enumerate(made):
        s = old.get(label)
        new = Series(table=m.table, label=label, key=label)
        if s is not None:
            for f in STYLE_FIELDS + ('legend', 'visible', 'label'):
                setattr(new, f, getattr(s, f))
        else:
            new.color = PALETTE[k % len(PALETTE)] if color != '' else PALETTE[0]
            if cat:
                new.marker_size = 3.5
            elif spec.chart == 'xy' and m.agg == 'none' and not m.x_cat:
                new.style = 'marker'
        new.auto = True
        if spec.horizontal:
            new.x, new.y = cat_col, y
        elif cat:
            new.x, new.y = cat_col, y
        else:
            new.x, new.y = (m.x if spec.chart != 'hist' else ''), y
            new.x_cat = bool(m.x_cat and m.x and spec.chart == 'xy')
            new.y_cat = bool(m.y_cat and spec.chart == 'xy')
            new.z = m.z if spec.chart == 'heatmap' else ''
            new.agg = m.agg if spec.chart == 'xy' and not new.y_cat else 'none'
            new.agg_err = m.err
            if m.agg != 'none' and m.err != 'none':
                new.err_style = new.err_style if new.err_style != 'none' else 'bar'
        new.where, new.equals = where, equals
        if gcol and spec.cat_hidden:
            new.hide_col, new.hide = gcol, list(spec.cat_hidden)
        out.append(new)
    spec.bar_err = m.err
    spec.series = out + keep
    # axis names follow the columns unless typed
    xs = [m.x] if m.x else []
    if spec.chart == 'hist':
        names = (', '.join(vals), 'count' if not spec.hist_density else 'density')
    elif spec.horizontal:
        names = (', '.join(vals), cat_col)
    else:
        names = (m.x, ', '.join(vals) if not (cat and not vals) else '')
    for a, name in zip((spec.x, spec.y), names):
        if not a.label or a.label in _auto_names(tabs, m) or a.label == '':
            a.label = name
    del xs
    return spec


def _auto_names(tabs, m: Mapping) -> set:
    t = tabs.get(m.table)
    cols = set(t.columns) if t is not None else set()
    out = set(cols) | {'count', 'density'}
    ys = [y for y in m.ys if y]
    for k in range(2, len(ys) + 1):
        out.add(', '.join(ys[:k]))
    return out


def text_columns(t: Table) -> list:
    return [c for c in t.columns if not t.is_numeric(c)]


def guess_mapping(spec: GraphSpec, tables: dict, table: str = '') -> Mapping:
    """A starting 축 배치 for a table: the tool's own columns when its graph
    uses that table, else a text column with several values as categories
    and the first measurement as the value."""
    tabs = tables if isinstance(tables, dict) else {t.name: t for t in tables}
    first = next((s for s in spec.series if s.table in tabs), None)
    name = table or (first.table if first else next(iter(tabs), ''))
    t = tabs.get(name)
    m = Mapping(on=False, table=name)
    if t is None:
        return m
    nums = [c for c in t.numeric_columns() if c not in ('timepoint', 'label', 'n', 'shown')]
    texts = [c for c in t.columns if c not in nums]
    cats = [c for c in ('group', 'image', 'region', 'roi', 'cell', 'channel') if c in t.columns
            and len(set(t.values(c))) > 1]
    cats += [c for c in texts if c not in cats and 1 < len(set(t.values(c))) < max(len(t.rows), 2)]
    if first is not None and first.table == name:
        m.x = first.x
        m.ys = list(dict.fromkeys(s.y for s in spec.series if s.table == name and s.y))
        m.x_cat = spec.chart in CATEGORY_CHARTS or bool(first.x and not t.is_numeric(first.x))
        if first.split:
            m.color = first.split
        elif first.where and all(s.where == first.where for s in spec.series if s.table == name):
            m.color = first.where
        else:
            m.color = '@y'
        m.err = spec.bar_err if spec.chart in CATEGORY_CHARTS else first.agg_err
        m.agg = first.agg if spec.chart == 'xy' else 'none'
        m.z = first.z
        return m
    m.x = cats[0] if cats else (nums[0] if nums else '')
    m.x_cat = bool(cats)
    ys = [c for c in nums if c != m.x]
    m.ys = ys[:1]
    m.color = '@y'
    return m


def recommend_chart(m: Mapping, tables: dict) -> str:
    """'strip' (점 그림) for values per category, 'xy' for two numbers."""
    return 'strip' if m.x_cat or m.y_cat else 'xy'


# ---------------------------------------------------------------------------
# 점 하나 = (unit), 상관 행렬 / 상관 비교, XY 회귀 (owner request 2026-11-14)
# ---------------------------------------------------------------------------

IMAGE_KEYS = ('image_id', 'image', '이미지', 'file', 'name')
GROUP_KEYS = ('group', '그룹')
ID_COLUMNS = ('cell', 'label', 'n_rows', 'timepoint', 'roi', 'particle', 'track', 'index')


def _key_column(t: Table, unit: str) -> str:
    for c in (IMAGE_KEYS if unit == 'image' else GROUP_KEYS):
        if c in t.columns:
            return c
    return ''


def unit_table(t: Table, unit: str) -> Table:
    """The table with one row per image (their mean) or per group; the same
    table when unit is 'rows' or it has no image / group column."""
    if unit not in ('image', 'group') or getattr(t, '_unit', '') == unit:
        return t
    key = _key_column(t, unit)
    if not key:
        return t
    from . import graph_calc

    nums = [c for c in t.numeric_columns() if c != key]
    keep = [c for c in GROUP_KEYS + IMAGE_KEYS if c in t.columns and c != key and c not in nums] \
        if unit == 'image' else []
    keys = [_text(v) for v in t.values(key)]
    order, means, counts = graph_calc.sample_means(keys, {c: t.numbers(c) for c in nums})
    first = {}
    for i, k in enumerate(keys):
        first.setdefault(k, i)
    rows = []
    for j, k in enumerate(order):
        r = [k] + [t.rows[first[k]][t.index(c)] for c in keep] + [counts[j]]
        rows.append(r + [float(means[c][j]) for c in nums])
    out = Table(t.name, [key] + keep + ['n_rows'] + nums, rows, dict(t.labels), dict(t.column_sets))
    out._unit = unit
    return out


def view_tables(spec: GraphSpec, tables) -> dict:
    """Tables as the graph uses them: the 축 배치 / 상관 표 aggregated by
    mapping.unit (점 하나 =)."""
    tabs = tables if isinstance(tables, dict) else {t.name: t for t in tables}
    unit = spec.mapping.unit
    if unit == 'rows':
        return tabs
    out = dict(tabs)
    for name in {spec.mapping.table, spec.calc.table}:
        if name in out:
            out[name] = unit_table(out[name], unit)
    return out


def calc_table(spec: GraphSpec, tables) -> Table | None:
    tabs = view_tables(spec, tables)
    name = spec.calc.table or spec.mapping.table or next(iter(tabs), '')
    return tabs.get(name)


def calc_columns(spec: GraphSpec, t: Table, which: str) -> list:
    """X / Y columns of the correlation: picked ones, a column set, or every
    number column (ids left out)."""
    c = spec.calc
    if which == 'y' and c.yset == '@x' and not c.ys:
        return calc_columns(spec, t, 'x')
    picked, cset = (c.xs, c.xset) if which == 'x' else (c.ys, c.yset)
    nums = t.numeric_columns()
    if picked:
        return [x for x in picked if x in nums]
    if cset and cset in t.column_sets:
        return [x for x in t.column_sets[cset] if x in nums]
    return [x for x in nums if x not in ID_COLUMNS and x not in GROUP_KEYS + IMAGE_KEYS]


def _calc_rows(spec: GraphSpec, t: Table, extra=None) -> list:
    c = spec.calc
    rows = list(range(len(t.rows)))
    for col, val in ((c.where, c.equals),) + tuple(extra or ()):
        if col and col in t.columns:
            vals = t.values(col)
            rows = [i for i in rows if _text(vals[i]) == val]
    return rows


def _calc_values(spec: GraphSpec, t: Table, cols, rows, log) -> dict:
    out = {}
    for col in cols:
        v = t.numbers(col)[rows]
        if log:
            with np.errstate(divide='ignore', invalid='ignore'):
                v = np.where(v > 0, np.log10(v), np.nan)
        out[col] = v
    return out


def calc_groups(spec: GraphSpec, t: Table) -> list:
    g = spec.calc.group
    if not g or g not in t.columns:
        return []
    vals = _ordered(_texts(t, g, _calc_rows(spec, t)), spec.cat_order if g == group_column(spec) else [])
    return [v for v in vals if v != '' and v not in set(spec.cat_hidden)]


def corr_matrix_of(spec: GraphSpec, t: Table, extra=None) -> dict:
    from . import graph_calc

    xs, ys = calc_columns(spec, t, 'x'), calc_columns(spec, t, 'y')
    rows = _calc_rows(spec, t, extra)
    cx = _calc_values(spec, t, xs, rows, spec.calc.log_x)
    cy = _calc_values(spec, t, ys, rows, spec.calc.log_y)
    vals, ns = graph_calc.corr_matrix(cx, cy, spec.calc.method)
    why = [[graph_calc.why_nan(cx[x], cy[y], t.label(x), t.label(y)) for x in xs] for y in ys]
    return {'xs': xs, 'ys': ys, 'vals': vals, 'ns': ns, 'p': graph_calc.corr_p(vals, ns), 'why': why,
            'cx': cx, 'cy': cy}


def corr_result(spec: GraphSpec, tables) -> dict | None:
    """상관 행렬: one matrix; 상관 비교: one per group plus the A vs B
    difference (Fisher z) or the all-group heterogeneity (Cochran Q)."""
    from . import graph_calc

    t = calc_table(spec, tables)
    if t is None:
        return None
    if spec.chart == 'corr':
        res = corr_matrix_of(spec, t)
        res['table'] = t
        return res
    groups = calc_groups(spec, t)
    c = spec.calc
    per = {g: corr_matrix_of(spec, t, ((c.group, g),)) for g in groups}
    base = corr_matrix_of(spec, t)
    res = {'xs': base['xs'], 'ys': base['ys'], 'groups': groups, 'per': per, 'table': t}
    if c.compare == 'all' or len(groups) < 2:
        if len(groups) >= 2:
            q = graph_calc.corr_heterogeneity_p([per[g]['vals'] for g in groups],
                                                [per[g]['ns'] for g in groups])
            res['q_p'] = graph_calc.correct(q, c.correction)
            res['q_p_raw'] = q
        return res
    a = c.a if c.a in per else groups[0]
    b = c.b if c.b in per and c.b != a else next(g for g in groups if g != a)
    pa, pb = per[a], per[b]
    raw = graph_calc.corr_diff_p(pa['vals'], pa['ns'], pb['vals'], pb['ns'])
    res.update(a=a, b=b, diff=pb['vals'] - pa['vals'], p_raw=raw, p=graph_calc.correct(raw, c.correction))
    n_ok = int(np.isfinite(raw).sum())
    res['expected'] = n_ok * 0.05
    res['n_tests'] = n_ok
    return res


def corr_long_table(spec: GraphSpec, tables) -> Table:
    """그래프에 쓰인 데이터 of a 상관 행렬 / 상관 비교 (Mito Analyzer
    `_correlations.csv` content; A vs B sorted by |Δ|)."""
    from . import graph_calc

    res = corr_result(spec, tables)
    if res is None:
        return Table('그래프에 쓰인 데이터', [], [])
    t = res['table']
    if spec.chart == 'corr':
        rows = []
        for i, y in enumerate(res['ys']):
            for j, x in enumerate(res['xs']):
                ps = graph_calc.pair_stats(res['cx'][x], res['cy'][y])
                rows.append([t.label(y), t.label(x), ps['pearson_r'], ps['r2'], ps['p_value'],
                             ps['spearman_rho'], ps['spearman_p'], ps['n'], ps['note']])
        return Table('그래프에 쓰인 데이터', ['Y', 'X', 'Pearson r', 'R²', 'p', 'Spearman ρ', 'Spearman p',
                                       'n', '이유'], rows)
    m = graph_calc.METHODS.get(spec.calc.method, 'r')
    if 'diff' in res:
        a, b = res['a'], res['b']
        rows = []
        for i, y in enumerate(res['ys']):
            for j, x in enumerate(res['xs']):
                rows.append([t.label(y), t.label(x), res['per'][a]['vals'][i, j], int(res['per'][a]['ns'][i, j]),
                             res['per'][b]['vals'][i, j], int(res['per'][b]['ns'][i, j]), res['diff'][i, j],
                             res['p_raw'][i, j], res['p'][i, j], graph_calc.stars(res['p'][i, j])])
        rows.sort(key=lambda r: -abs(r[6]) if math.isfinite(r[6]) else 0)
        return Table('그래프에 쓰인 데이터', ['Y', 'X', f'{a} {m}', f'{a} n', f'{b} {m}', f'{b} n',
                                       'Δ (B − A)', 'p (Fisher z)', 'p (보정)', '표시'], rows)
    cols = ['Y', 'X']
    for g in res['groups']:
        cols += [f'{g} {m}', f'{g} n']
    cols += ['p (Cochran Q)', 'p (보정)']
    rows = []
    for i, y in enumerate(res['ys']):
        for j, x in enumerate(res['xs']):
            r = [t.label(y), t.label(x)]
            for g in res['groups']:
                r += [res['per'][g]['vals'][i, j], int(res['per'][g]['ns'][i, j])]
            q = res.get('q_p_raw')
            r += [q[i, j] if q is not None else math.nan,
                  res['q_p'][i, j] if q is not None else math.nan]
            rows.append(r)
    return Table('그래프에 쓰인 데이터', cols, rows)


def _short(name: str, n=22) -> str:
    return name if len(name) <= n else name[:n - 1] + '…'


def _heat(fig, ax, vals, xs, ys, cmap, lim, numbers, fontsize, marks=None, title=''):
    im = ax.imshow(np.ma.masked_invalid(vals), cmap=cmap, vmin=-lim, vmax=lim, aspect='auto',
                   interpolation='nearest')
    ax.set_xticks(range(len(xs)))
    ax.set_xticklabels([_short(x) for x in xs], rotation=60, ha='right', rotation_mode='anchor')
    ax.set_yticks(range(len(ys)))
    ax.set_yticklabels([_short(y) for y in ys])
    ax.tick_params(length=0, labelsize=fontsize)
    for sp in ax.spines.values():
        sp.set_visible(False)
    if title:
        ax.set_title(title, fontsize=fontsize + 1)
    if numbers and vals.size <= 100:
        for i in range(vals.shape[0]):
            for j in range(vals.shape[1]):
                v = vals[i, j]
                txt = '–' if not np.isfinite(v) else f'{v:.2f}'
                if marks is not None and marks[i][j]:
                    txt += '\n' + marks[i][j]
                ax.text(j, i, txt, ha='center', va='center', fontsize=max(fontsize - 1.5, 5),
                        color='white' if np.isfinite(v) and abs(v) > lim * 0.6 else 'black')
    elif marks is not None:
        for i in range(vals.shape[0]):
            for j in range(vals.shape[1]):
                if marks[i][j]:
                    ax.text(j, i, marks[i][j], ha='center', va='center', fontsize=fontsize)
    return im


def _cbar(cb, label, fs):
    cb.set_label(label, fontsize=fs + 1)
    cb.ax.tick_params(labelsize=fs)
    cb.outline.set_visible(False)


def _draw_corr(fig, spec: GraphSpec, tables) -> tuple:
    """상관 행렬 / 상관 비교; returns (first axes, art info for the window)."""
    from . import graph_calc

    res = corr_result(spec, tables)
    fs = spec.tick_font.size
    m = graph_calc.METHODS.get(spec.calc.method, 'r')
    if res is None or not res['xs'] or not res['ys']:
        ax = fig.add_subplot(111)
        ax.text(0.5, 0.5, '상관을 계산할 숫자 열이 없습니다', ha='center', va='center', transform=ax.transAxes)
        ax.set_axis_off()
        return ax, {}
    t = res['table']
    xs = [t.label(x) for x in res['xs']]
    ys = [t.label(y) for y in res['ys']]
    if spec.chart == 'corr':
        ax = fig.add_subplot(111)
        im = _heat(fig, ax, res['vals'], xs, ys, 'RdBu_r', 1.0, spec.calc.numbers, fs)
        if spec.colorbar:
            _cbar(fig.colorbar(im, ax=ax, shrink=0.85), m, fs)
        return ax, {'corr': res, 'axes': [ax]}
    groups = res['groups']
    if len(groups) < 2:
        ax = fig.add_subplot(111)
        ax.text(0.5, 0.5, '비교할 그룹이 2개 이상 있어야 합니다 (그룹 열)', ha='center', va='center',
                transform=ax.transAxes)
        ax.set_axis_off()
        return ax, {}
    if 'diff' in res:
        a, b = res['a'], res['b']
        axes = [fig.add_subplot(1, 3, k + 1) for k in range(3)]
        _heat(fig, axes[0], res['per'][a]['vals'], xs, ys, 'RdBu_r', 1.0, spec.calc.numbers, fs,
              title=f'{a} (n = {int(res["per"][a]["ns"].max())})')
        im = _heat(fig, axes[1], res['per'][b]['vals'], xs, ys, 'RdBu_r', 1.0, spec.calc.numbers, fs,
                   title=f'{b} (n = {int(res["per"][b]["ns"].max())})')
        marks = [[graph_calc.stars(p) for p in row] for row in res['p']]
        d = res['diff']
        lim = float(np.nanmax(np.abs(d))) if np.isfinite(d).any() else 1.0
        im2 = _heat(fig, axes[2], d, xs, ys, 'PuOr_r', max(lim, 0.1), spec.calc.numbers, fs, marks,
                    title='Δ (B − A)')
        for k in (1, 2):
            axes[k].set_yticklabels([])
        if spec.colorbar:
            _cbar(fig.colorbar(im, ax=axes[:2], shrink=0.8, location='bottom'), m, fs)
            _cbar(fig.colorbar(im2, ax=axes[2], shrink=0.8, location='bottom'), 'Δ', fs)
        return axes[0], {'corr': res, 'axes': axes}
    k = len(groups)
    axes = [fig.add_subplot(1, k + 1, i + 1) for i in range(k + 1)]
    im = None
    for i, g in enumerate(groups):
        im = _heat(fig, axes[i], res['per'][g]['vals'], xs, ys, 'RdBu_r', 1.0, False, fs,
                   title=f'{g} (n = {int(res["per"][g]["ns"].max())})')
        if i:
            axes[i].set_yticklabels([])
    q = res.get('q_p')
    if q is not None:
        with np.errstate(divide='ignore'):
            lq = -np.log10(q)
        axes[-1].imshow(np.ma.masked_invalid(lq), cmap='Greys', vmin=0, vmax=3, aspect='auto',
                        interpolation='nearest')
        axes[-1].set_xticks(range(len(xs)))
        axes[-1].set_xticklabels([_short(x) for x in xs], rotation=60, ha='right', rotation_mode='anchor')
        axes[-1].set_yticks([])
        axes[-1].tick_params(length=0, labelsize=fs)
        axes[-1].set_title('그룹 사이 차이 (Cochran Q)', fontsize=fs + 1)
        for i in range(q.shape[0]):
            for j in range(q.shape[1]):
                s = graph_calc.stars(q[i, j])
                if s:
                    axes[-1].text(j, i, s, ha='center', va='center', fontsize=fs, color='white')
    if spec.colorbar and im is not None:
        _cbar(fig.colorbar(im, ax=axes[:-1], shrink=0.8, location='bottom'), m, fs)
    return axes[0], {'corr': res, 'axes': axes}


def corr_cell(spec: GraphSpec, art: dict, ax, x: float, y: float):
    """(x column, y column, group or '') of the matrix cell under a click."""
    res = (art or {}).get('corr')
    if not res or ax not in art.get('axes', []):
        return None
    j, i = int(round(x)), int(round(y))
    if not (0 <= j < len(res['xs']) and 0 <= i < len(res['ys'])):
        return None
    k = art['axes'].index(ax)
    group = ''
    if spec.chart == 'corrcmp':
        if 'diff' in res:
            group = res['a'] if k == 0 else res['b'] if k == 1 else ''
        elif k < len(res['groups']):
            group = res['groups'][k]
    return res['xs'][j], res['ys'][i], group


def corr_cell_text(spec: GraphSpec, art: dict, ax, x, y) -> str:
    """Hover text of a matrix cell: r · n · p and why it is undefined."""
    cell = corr_cell(spec, art, ax, x, y)
    if cell is None:
        return ''
    res = art['corr']
    t = res['table']
    i, j = res['ys'].index(cell[1]), res['xs'].index(cell[0])
    src = res if spec.chart == 'corr' else res['per'].get(cell[2]) if cell[2] else None
    head = f'{t.label(cell[1])} × {t.label(cell[0])}'
    if src is None:
        if 'diff' in res:
            return f'{head}\nΔ = {res["diff"][i, j]:.3f}, p = {res["p"][i, j]:.3g}'
        return head
    v, n, p = src['vals'][i, j], int(src['ns'][i, j]), src['p'][i, j]
    why = src['why'][i][j]
    return f'{head}\n{"r" if spec.calc.method == "r" else "ρ"} = {v:.3f} · n = {n} · p = {p:.3g}' + \
        (f'\n{why}' if why else '')


def scatter_spec(spec: GraphSpec, x: str, y: str, group: str = '') -> GraphSpec:
    """The XY graph of one matrix cell (click on 상관 행렬): points + regression."""
    out = GraphSpec(chart='xy')
    out.mapping = Mapping(on=True, table=spec.calc.table or spec.mapping.table, x=x, x_cat=False, ys=[y],
                          color='@y', unit=spec.mapping.unit)
    out.calc = Calc(**{**asdict(spec.calc), 'reg_on': True})
    if group and spec.calc.group:
        out.calc.where, out.calc.equals = spec.calc.group, group
    out.x.log, out.y.log = spec.calc.log_x, spec.calc.log_y
    out.title = f'{y} × {x}' + (f' ({group})' if group else '')
    return out


def _reg_points(spec: GraphSpec, tables, ax_scale=(1.0, 1.0)) -> list:
    """(label, colour, x, y) per regression line: all visible series pooled,
    or one per series (reg_split)."""
    parts = []
    for i, s in enumerate(spec.series):
        if not s.visible:
            continue
        xs, ys = [], []
        for p in xy_parts(_no_agg(s), tables, *ax_scale):
            if p['ticks'] or p['yticks']:
                continue
            xs.append(np.asarray(p['x'], float))
            ys.append(np.asarray(p['y'], float))
        if xs:
            parts.append((_label(s, i), s.color, np.concatenate(xs), np.concatenate(ys)))
    if not spec.calc.reg_split and parts:
        return [('', '#000000', np.concatenate([p[2] for p in parts]), np.concatenate([p[3] for p in parts]))]
    return parts


def regression_rows(spec: GraphSpec, tables) -> list[dict]:
    from . import graph_calc

    out = []
    for label, _col, x, y in _reg_points(spec, view_tables(spec, tables), (spec.x.scale, spec.y.scale)):
        fx, fy = x, y
        if spec.calc.reg_fit == 'log':
            with np.errstate(divide='ignore', invalid='ignore'):
                fx, fy = np.where(x > 0, np.log10(x), np.nan), np.where(y > 0, np.log10(y), np.nan)
        reg = graph_calc.regression(fx, fy, through_origin=spec.calc.reg_fit == 'origin')
        rho, p_s, _ = graph_calc.spearman(x, y)
        out.append(dict(series=label or '전체', fit=REG_FITS.get(spec.calc.reg_fit, ''), **reg,
                        spearman_rho=rho, spearman_p=p_s, note=graph_calc.why_nan(fx, fy)))
    return out


def _draw_regression(ax, spec: GraphSpec, tables):
    from . import graph_calc

    c = spec.calc
    pts = _reg_points(spec, tables, (spec.x.scale, spec.y.scale))
    lines = []
    for (label, col, x, y), reg in zip(pts, regression_rows(spec, tables)):
        ok = np.isfinite(x) & np.isfinite(y)
        if not np.isfinite(reg['slope']) or ok.sum() < 3:
            lines.append(f'{label + ": " if label else ""}{reg["note"]}')
            continue
        lo, hi = float(np.nanmin(x[ok])), float(np.nanmax(x[ok]))
        if c.reg_fit == 'log':
            lo = max(lo, float(np.nanmin(x[ok & (x > 0)])) if (ok & (x > 0)).any() else lo)
            xx = np.geomspace(max(lo, 1e-12), max(hi, lo * 1.0001), 60)
            yy = 10 ** (reg['intercept'] + reg['slope'] * np.log10(xx))
        else:
            xx = np.linspace(min(lo, 0) if c.reg_fit == 'origin' else lo, hi, 60)
            yy = reg['intercept'] + reg['slope'] * xx
        ax.plot(xx, yy, color=col, lw=1.2, zorder=5, gid='regression')
        rho = reg['spearman_rho'] if 'spearman_rho' in reg else graph_calc.spearman(x, y)[0]
        lines.append(f'{label + ": " if label else ""}r = {reg["r"]:.3f}, R² = {reg["r2"]:.3f}, '
                     f'p = {reg["p"]:.3g}, ρ = {rho:.3f}, n = {reg["n"]}')
    if c.reg_text and lines:
        ax.text(0.02, 0.98, '\n'.join(lines), transform=ax.transAxes, ha='left', va='top',
                fontsize=spec.tick_font.size, zorder=11)
    if c.quadrant != 'none' and pts:
        x = np.concatenate([p[2] for p in pts])
        y = np.concatenate([p[3] for p in pts])
        ok = np.isfinite(x) & np.isfinite(y)
        if ok.any():
            f = np.nanmean if c.quadrant == 'mean' else np.nanmedian
            mx, my = float(f(x[ok])), float(f(y[ok]))
            ax.axvline(mx, color='#7f7f7f', lw=0.8, ls='--', zorder=1)
            ax.axhline(my, color='#7f7f7f', lw=0.8, ls='--', zorder=1)
            xo, yo = x[ok], y[ok]
            counts = {'I': int(((xo >= mx) & (yo >= my)).sum()), 'II': int(((xo < mx) & (yo >= my)).sum()),
                      'III': int(((xo < mx) & (yo < my)).sum()), 'IV': int(((xo >= mx) & (yo < my)).sum())}
            for name, (dx, dy, ha, va) in {'I': (4, 4, 'left', 'bottom'), 'II': (-4, 4, 'right', 'bottom'),
                                           'III': (-4, -4, 'right', 'top'),
                                           'IV': (4, -4, 'left', 'top')}.items():
                ax.annotate(f'{name} ({counts[name]})', (mx, my), xytext=(dx, dy), textcoords='offset points',
                            ha=ha, va=va, zorder=11,
                        fontsize=spec.tick_font.size, color='#7f7f7f')


def group_summary_table(t: Table, cols: list, group_col: str, control: str = '', groups=None) -> Table:
    """여러 열 그룹 요약표 (Mito Analyzer group_summary_long): one row per
    column × group."""
    from . import graph_calc

    labels = [_text(v) for v in t.values(group_col)]
    groups = list(groups or dict.fromkeys(labels))
    rows = graph_calc.group_summary_long({t.label(c): t.numbers(c) for c in cols}, labels, groups,
                                         control or None)
    return Table.from_dicts('그룹 요약', rows)
