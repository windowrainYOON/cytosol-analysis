"""Figure panels: a table of images with row / column labels, zoom insets and
scale bars, exported as PNG, TIFF, PDF or SVG.

GUI-independent: the figure window (cytosol.figure_window) edits a
``FigureSpec`` and calls ``render_figure`` / ``save_figure``.

Layout is done in inches so text sizes are real point sizes. Each cell image
is resampled to exactly the cell's pixel size at the output DPI before the
scale bar, inset and boxes are drawn, so line widths look the same in every
cell whatever the source resolution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .render import NICE_LENGTHS_UM, add_scale_bar, parse_color

CORNERS = ['upper left', 'upper right', 'lower left', 'lower right']
FONT_FAMILIES = ['Arial', 'Helvetica', 'Apple SD Gothic Neo', 'AppleGothic',
                 'Malgun Gothic', 'NanumGothic', 'DejaVu Sans']


@dataclass
class Label:
    text: str = ''
    color: tuple | None = None  # None = default text color for the background


@dataclass
class Inset:
    """A zoomed copy of rect (x0, y0, x1, y1, in cell-image pixels) shown in a corner."""

    rect: tuple[int, int, int, int]
    corner: str = 'upper left'
    size: float = 0.45  # inset width as a fraction of the cell width
    # 'inside': pasted into a corner of the image; 'cell': shown in another table
    # cell (that cell's zoom_src / zoom_inset point back here)
    placement: str = 'inside'
    offset: tuple = (0, 1)  # (rows, cols) from the source cell to the zoom cell

    def copy(self) -> 'Inset':
        return Inset(self.rect, self.corner, self.size, self.placement, self.offset)


@dataclass(eq=False)
class FigureCell:
    """One table cell: an ImageItem (live LUTs) or a plain RGB image."""

    item: object = None             # cytosol.lut.ImageItem
    region: tuple | None = None     # crop (x0, y0, x1, y1) in item pixels; None = whole image
    channels: list | None = None    # channel indices; None = the item's visible channels
    rgb: np.ndarray | None = None   # external image (float 0..1, Y X 3) instead of item
    rgb_pixel_um: float | None = None
    name: str = ''
    insets: list = field(default_factory=list)
    # a zoom cell: shows zoom_inset.rect of the cell zoom_src
    zoom_src: 'FigureCell | None' = None
    zoom_inset: Inset | None = None

    @property
    def is_zoom(self) -> bool:
        return self.zoom_src is not None

    @property
    def empty(self) -> bool:
        if self.is_zoom:
            return self.zoom_src.empty or not any(i is self.zoom_inset
                                                  for i in self.zoom_src.insets)
        return self.item is None and self.rgb is None

    def image(self) -> np.ndarray:
        if self.is_zoom:
            x0, y0, x1, y1 = self.zoom_inset.rect
            return self.zoom_src.image()[y0:y1, x0:x1]
        if self.item is not None:
            return self.item.composite(self.region, self.channels)
        return self.rgb

    @property
    def pixel_um(self):
        if self.is_zoom:
            return self.zoom_src.pixel_um
        return self.item.pixel_um if self.item is not None else self.rgb_pixel_um

    def shape(self):
        if self.is_zoom:
            x0, y0, x1, y1 = self.zoom_inset.rect
            return y1 - y0, x1 - x0
        if self.item is not None:
            if self.region is not None:
                x0, y0, x1, y1 = self.region
                return y1 - y0, x1 - x0
            return tuple(self.item.image.data.shape[-2:])
        return self.rgb.shape[:2]

    def describe(self) -> str:
        if self.empty:
            return ''
        if self.is_zoom:
            return '확대: ' + self.zoom_src.describe().replace('\n', ' · ')
        if self.item is None:
            return self.name or '이미지'
        if self.channels is None:
            ch = '합성'
        else:
            ch = '+'.join(self.item.channels[i] for i in self.channels) or '채널 없음'
        crop = ''
        if self.region is not None:
            if self.region in self.item.crops:
                crop = f' · crop {self.item.crops.index(self.region) + 1}'
            else:
                crop = ' · crop'
        return f'{self.item.label}{crop}\n{ch}'

    def copy_from(self, other: 'FigureCell', insets=True):
        self.item, self.region, self.rgb = other.item, other.region, other.rgb
        self.rgb_pixel_um, self.name = other.rgb_pixel_um, other.name
        self.zoom_src, self.zoom_inset = other.zoom_src, other.zoom_inset
        self.channels = None if other.channels is None else list(other.channels)
        if insets:
            # zoom-cell links are not copied: those belong to the original cell
            self.insets = [i.copy() for i in other.insets if i.placement == 'inside']


@dataclass
class FigureSpec:
    rows: list = field(default_factory=lambda: [Label('Row 1')])
    cols: list = field(default_factory=lambda: [Label('Column 1')])
    cells: list = field(default_factory=lambda: [[FigureCell()]])  # [row][col]
    background: str = 'black'        # 'black' or 'white'
    cell_in: float = 1.6             # cell width in inches
    aspect: float | None = None      # cell height / width; None = first image
    gap_in: float = 0.04
    font_pt: float = 9.0
    font_family: str = 'Arial'
    bold: bool = True
    border: bool = True
    border_width_pt: float = 0.8
    scale_bar: bool = True
    scale_um: float | None = None    # None = automatic, same for every cell
    scale_position: str = 'lower right'
    scale_label: bool = False        # write "10 µm" in every cell
    caption: bool = True             # "(Scale bar = 10 µm)" under the table
    inset_scale_bar: bool = True
    inset_scale_um: float | None = None
    inset_color: tuple = (1.0, 1.0, 1.0)

    # ---- table editing --------------------------------------------------

    @property
    def nrows(self):
        return len(self.rows)

    @property
    def ncols(self):
        return len(self.cols)

    def add_row(self, index=None, text=None):
        index = self.nrows if index is None else index
        self.rows.insert(index, Label(text if text is not None else f'Row {self.nrows + 1}'))
        self.cells.insert(index, [FigureCell() for _ in range(self.ncols)])

    def add_col(self, index=None, text=None):
        index = self.ncols if index is None else index
        self.cols.insert(index, Label(text if text is not None else f'Column {self.ncols + 1}'))
        for row in self.cells:
            row.insert(index, FigureCell())

    def remove_row(self, index):
        if self.nrows > 1:
            self.rows.pop(index)
            self.cells.pop(index)

    def remove_col(self, index):
        if self.ncols > 1:
            self.cols.pop(index)
            for row in self.cells:
                row.pop(index)

    def move_row(self, index, step):
        j = index + step
        if 0 <= j < self.nrows:
            self.rows[index], self.rows[j] = self.rows[j], self.rows[index]
            self.cells[index], self.cells[j] = self.cells[j], self.cells[index]

    def move_col(self, index, step):
        j = index + step
        if 0 <= j < self.ncols:
            self.cols[index], self.cols[j] = self.cols[j], self.cols[index]
            for row in self.cells:
                row[index], row[j] = row[j], row[index]

    def find(self, cell):
        for r, row in enumerate(self.cells):
            for c, other in enumerate(row):
                if other is cell:
                    return r, c
        return None

    def zoom_cells(self, inset):
        return [c for row in self.cells for c in row if c.zoom_inset is inset]

    def unlink_inset(self, inset):
        """Empty the zoom cell(s) showing inset."""
        for cell in self.zoom_cells(inset):
            cell.copy_from(FigureCell())

    def link_inset(self, src: FigureCell, inset: Inset, overwrite=True) -> bool:
        """Show inset in the cell at src + inset.offset, adding rows/columns if needed.

        Returns False (and links nothing) when that cell is the source itself, or
        holds an image and overwrite is False.
        """
        pos = self.find(src)
        if pos is None:
            return False
        dr, dc = inset.offset
        r, c = pos[0] + dr, pos[1] + dc
        if r < 0 or c < 0 or (dr, dc) == (0, 0):
            return False
        while self.nrows <= r:
            self.add_row()
        while self.ncols <= c:
            self.add_col()
        target = self.cells[r][c]
        if target is src:
            return False
        if not overwrite and not target.empty and target.zoom_inset is not inset:
            return False
        self.unlink_inset(inset)
        target.copy_from(FigureCell(zoom_src=src, zoom_inset=inset))
        target.insets = []
        return True

    def forget_item(self, item):
        """Empty every cell that shows item (it was removed from the app)."""
        for row in self.cells:
            for k, cell in enumerate(row):
                if cell.item is item:
                    row[k] = FigureCell()

    # ---- derived --------------------------------------------------------

    @property
    def text_color(self):
        return (1.0, 1.0, 1.0) if self.background == 'black' else (0.0, 0.0, 0.0)

    @property
    def bg_color(self):
        return (0.0, 0.0, 0.0) if self.background == 'black' else (1.0, 1.0, 1.0)

    def filled(self):
        return [c for row in self.cells for c in row if not c.empty]

    def cell_aspect(self) -> float:
        if self.aspect:
            return self.aspect
        for c in self.filled():
            h, w = c.shape()
            return h / w
        return 1.0

    def auto_scale_um(self) -> float | None:
        """One bar length for all cells: fits 25% of the narrowest field of view."""
        fovs = [c.shape()[1] * c.pixel_um for c in self.filled()
                if c.pixel_um and not c.is_zoom]
        if not fovs:
            return None
        target = min(fovs) * 0.25
        fits = [v for v in NICE_LENGTHS_UM if v <= target]
        return fits[-1] if fits else NICE_LENGTHS_UM[0]

    def auto_inset_scale_um(self) -> float | None:
        """One inset bar length: fits 40% of the smallest inset's field of view."""
        fovs = [(i.rect[2] - i.rect[0]) * c.pixel_um
                for c in self.filled() if c.pixel_um for i in c.insets]
        if not fovs:
            return None
        target = min(fovs) * 0.4
        fits = [v for v in NICE_LENGTHS_UM if v <= target]
        return fits[-1] if fits else NICE_LENGTHS_UM[0]


# ---------------------------------------------------------------------------
# cell rendering
# ---------------------------------------------------------------------------


def _resize(rgb: np.ndarray, w: int, h: int) -> np.ndarray:
    from PIL import Image as PILImage

    img = PILImage.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8))
    return np.asarray(img.resize((max(1, w), max(1, h)), PILImage.Resampling.LANCZOS),
                      np.float32) / 255.0


def _box(rgb, x0, y0, x1, y1, color, t):
    """Draw a rectangle outline of thickness t (pixels) inside [x0, x1) x [y0, y1)."""
    h, w = rgb.shape[:2]
    x0, x1 = max(0, x0), min(w, x1)
    y0, y1 = max(0, y0), min(h, y1)
    if x1 <= x0 or y1 <= y0:
        return
    c = np.asarray(color, np.float32)
    rgb[y0:min(y0 + t, y1), x0:x1] = c
    rgb[max(y1 - t, y0):y1, x0:x1] = c
    rgb[y0:y1, x0:min(x0 + t, x1)] = c
    rgb[y0:y1, max(x1 - t, x0):x1] = c


def render_cell(cell: FigureCell, spec: FigureSpec, w_px: int, h_px: int,
                scale_um=None, inset_scale_um=None) -> np.ndarray:
    """(h_px, w_px, 3) float RGB of one cell, letterboxed in the background color."""
    out = np.empty((h_px, w_px, 3), np.float32)
    out[:] = spec.bg_color
    if cell.empty:
        return out
    src = cell.image()
    H, W = src.shape[:2]
    s = min(w_px / W, h_px / H)
    dw, dh = max(1, round(W * s)), max(1, round(H * s))
    disp = _resize(src, dw, dh)
    px = cell.pixel_um
    line = max(1, round(dw * 0.006))

    if cell.is_zoom:
        # a zoomed area in its own cell carries the inset scale bar
        if spec.inset_scale_bar and px and inset_scale_um and inset_scale_um * s / px < dw * 0.9:
            disp, _ = add_scale_bar(disp, px / s, inset_scale_um, spec.scale_position,
                                    label=spec.scale_label)
    elif spec.scale_bar and px and scale_um:
        disp, _ = add_scale_bar(disp, px / s, scale_um, spec.scale_position,
                                label=spec.scale_label)

    for inset in cell.insets:
        x0, y0, x1, y1 = inset.rect
        x0, x1 = max(0, x0), min(W, x1)
        y0, y1 = max(0, y0), min(H, y1)
        if x1 - x0 < 2 or y1 - y0 < 2:
            continue
        if inset.placement == 'cell':
            # only the box here; the zoomed copy is drawn in its own cell
            _box(disp, round(x0 * s), round(y0 * s), round(x1 * s), round(y1 * s),
                 spec.inset_color, line)
            continue
        iw = max(4, round(dw * inset.size))
        ih = max(4, round(iw * (y1 - y0) / (x1 - x0)))
        if ih > dh:
            ih = dh
            iw = max(4, round(ih * (x1 - x0) / (y1 - y0)))
        zoom = _resize(src[y0:y1, x0:x1], iw, ih)
        if spec.inset_scale_bar and px and inset_scale_um:
            zpx = px * (x1 - x0) / iw
            if inset_scale_um / zpx < iw * 0.9:
                zoom, _ = add_scale_bar(zoom, zpx, inset_scale_um, spec.scale_position,
                                        label=spec.scale_label)
        # box around the source area
        _box(disp, round(x0 * s), round(y0 * s), round(x1 * s), round(y1 * s),
             spec.inset_color, line)
        # the zoomed copy, flush with the chosen corner
        ox = 0 if 'left' in inset.corner else dw - iw
        oy = 0 if 'upper' in inset.corner else dh - ih
        disp[oy:oy + ih, ox:ox + iw] = zoom
        _box(disp, ox, oy, ox + iw, oy + ih, spec.inset_color, line)

    ox, oy = (w_px - dw) // 2, (h_px - dh) // 2
    out[oy:oy + dh, ox:ox + dw] = disp
    return out


# ---------------------------------------------------------------------------
# figure layout
# ---------------------------------------------------------------------------


def installed_families() -> list[str]:
    from matplotlib import font_manager

    return sorted({f.name for f in font_manager.fontManager.ttflist})


def _font_props(spec, weight=None):
    from matplotlib.font_manager import FontProperties

    have = set(installed_families())
    fams = [f for f in [spec.font_family] + FONT_FAMILIES if f in have]
    fams = list(dict.fromkeys(fams)) or ['DejaVu Sans']
    return FontProperties(family=fams, size=spec.font_pt,
                          weight=weight or ('bold' if spec.bold else 'normal'))


def _text_size_in(text, prop):
    """(width, height) in inches of possibly multi-line text."""
    from matplotlib.textpath import TextToPath

    if not text:
        return 0.0, 0.0
    ttp = TextToPath()
    lines = text.split('\n')
    w = 0.0
    for line in lines:
        if line:
            try:
                lw, _, _ = ttp.get_text_width_height_descent(line, prop, ismath=False)
            except Exception:
                lw = len(line) * prop.get_size_in_points() * 0.6
            w = max(w, lw)
    h = len(lines) * prop.get_size_in_points() * 1.25
    return w / 72.0, h / 72.0


def caption_text(spec, scale_um, inset_scale_um) -> str:
    if not (spec.caption and spec.scale_bar and scale_um):
        return ''
    text = f'(Scale bar = {scale_um:g} µm'
    if spec.inset_scale_bar and inset_scale_um:
        text += f'; inset = {inset_scale_um:g} µm'
    return text + ')'


def render_figure(spec: FigureSpec, dpi: float = 300):
    """Build a matplotlib Figure (not attached to pyplot)."""
    from matplotlib.figure import Figure
    from matplotlib.patches import Rectangle

    prop = _font_props(spec)
    cap_prop = _font_props(spec, weight='normal')
    tc = spec.text_color
    scale_um = spec.scale_um or spec.auto_scale_um()
    inset_um = spec.inset_scale_um or spec.auto_inset_scale_um()
    cap = caption_text(spec, scale_um, inset_um)

    cw = spec.cell_in
    ch = cw * spec.cell_aspect()
    g = spec.gap_in
    pad = 0.08
    lab_gap = spec.font_pt / 72.0 * 0.6
    row_w = max((_text_size_in(r.text, prop)[0] for r in spec.rows), default=0.0)
    col_h = max((_text_size_in(c.text, prop)[1] for c in spec.cols), default=0.0)
    cap_h = _text_size_in(cap, cap_prop)[1] + lab_gap if cap else 0.0

    left = pad + (row_w + lab_gap if row_w else 0.0)
    top = pad + (col_h + lab_gap * 0.5 if col_h else 0.0)
    grid_w = spec.ncols * cw + (spec.ncols - 1) * g
    grid_h = spec.nrows * ch + (spec.nrows - 1) * g
    W = left + grid_w + pad
    H = top + grid_h + cap_h + pad

    fig = Figure(figsize=(W, H), dpi=dpi, facecolor=spec.bg_color)
    w_px, h_px = max(1, round(cw * dpi)), max(1, round(ch * dpi))

    def fx(x):
        return x / W

    def fy(y_from_top):
        return 1.0 - y_from_top / H

    for r in range(spec.nrows):
        y = top + r * (ch + g)
        for c in range(spec.ncols):
            x = left + c * (cw + g)
            ax = fig.add_axes([fx(x), fy(y + ch), cw / W, ch / H])
            ax.set_facecolor(spec.bg_color)
            img = render_cell(spec.cells[r][c], spec, w_px, h_px, scale_um, inset_um)
            ax.imshow(img, interpolation='none', extent=(0, w_px, h_px, 0), aspect='auto')
            ax.set_xlim(0, w_px)
            ax.set_ylim(h_px, 0)
            ax.set_xticks([])
            ax.set_yticks([])
            for sp in ax.spines.values():
                sp.set_visible(False)
            if spec.border:
                ax.add_patch(Rectangle((0, 0), 1, 1, transform=ax.transAxes, fill=False,
                                       edgecolor=tc, linewidth=spec.border_width_pt,
                                       clip_on=False, zorder=5))
        lab = spec.rows[r]
        if lab.text:
            fig.text(fx(left - lab_gap), fy(y + ch / 2), lab.text, ha='right', va='center',
                     multialignment='right', color=lab.color or tc, fontproperties=prop)

    for c, lab in enumerate(spec.cols):
        if lab.text:
            x = left + c * (cw + g) + cw / 2
            fig.text(fx(x), fy(top - lab_gap * 0.5), lab.text, ha='center', va='bottom',
                     multialignment='center', color=lab.color or tc, fontproperties=prop)
    if cap:
        fig.text(fx(left + grid_w), fy(top + grid_h + lab_gap), cap, ha='right', va='top',
                 color=tc, fontproperties=cap_prop)
    return fig


def figure_to_array(spec: FigureSpec, dpi: float = 100) -> np.ndarray:
    """(H, W, 3) uint8 render, for previews."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    fig = render_figure(spec, dpi)
    canvas = FigureCanvasAgg(fig)
    canvas.draw()
    return np.asarray(canvas.buffer_rgba())[..., :3].copy()


def save_figure(spec: FigureSpec, path, dpi: float = 300) -> str:
    """Save as .png, .tif/.tiff, .pdf or .svg (chosen by the extension)."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    path = Path(path)
    ext = path.suffix.lower()
    fig = render_figure(spec, dpi)
    FigureCanvasAgg(fig)
    kw = dict(dpi=dpi, facecolor=spec.bg_color)
    if ext in ('.tif', '.tiff'):
        import tifffile

        canvas = fig.canvas
        canvas.draw()
        arr = np.asarray(canvas.buffer_rgba())[..., :3]
        tifffile.imwrite(path, arr, photometric='rgb', resolution=(dpi, dpi),
                         resolutionunit='INCH', compression='zlib')
    elif ext in ('.png', '.pdf', '.svg', '.eps', '.jpg', '.jpeg'):
        if ext == '.svg':
            from matplotlib import rcParams

            with _rc(rcParams, {'svg.fonttype': 'none'}):
                fig.savefig(path, format='svg', **kw)
        elif ext == '.pdf':
            from matplotlib import rcParams

            with _rc(rcParams, {'pdf.fonttype': 42}):
                fig.savefig(path, format='pdf', **kw)
        else:
            fig.savefig(path, **kw)
    else:
        raise ValueError(f'unsupported format {ext!r} (use .png, .tif, .pdf or .svg)')
    return str(path)


class _rc:
    """Temporarily set rcParams (matplotlib.rc_context without pyplot)."""

    def __init__(self, rc, values):
        self.rc, self.values, self.old = rc, values, {}

    def __enter__(self):
        for k, v in self.values.items():
            self.old[k] = self.rc[k]
            self.rc[k] = v

    def __exit__(self, *exc):
        self.rc.update(self.old)


def fill_row_by_channels(spec: FigureSpec, row: int, item, region=None, merged=True):
    """Put each channel of item in its own column of row, and the composite last.

    Adds columns when the row is too short; returns the number of cells set.
    """
    n_ch = len(item.channels)
    need = n_ch + (1 if merged else 0)
    while spec.ncols < need:
        spec.add_col()
    for k in range(n_ch):
        cell = spec.cells[row][k]
        cell.copy_from(FigureCell(item=item, region=region, channels=[k]), insets=False)
    if merged:
        cell = spec.cells[row][n_ch]
        cell.copy_from(FigureCell(item=item, region=region, channels=None), insets=False)
    return need


def color_label(item, index):
    """The channel's LUT color, brightened a little for text."""
    r, g, b = item.luts[index].color
    m = max(r, g, b, 1e-6)
    return (r / m, g / m, b / m)


__all__ = [
    'CORNERS', 'Label', 'Inset', 'FigureCell', 'FigureSpec', 'render_cell', 'render_figure',
    'figure_to_array', 'save_figure', 'fill_row_by_channels', 'color_label', 'parse_color',
]
