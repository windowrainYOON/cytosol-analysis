"""Distance bands from the nucleus to the cell edge (강도 측정 tab).

Every cytosol pixel of a cell with a nucleus gets its distance from the
nucleus ROI: either in µm from the nucleus edge ('absolute'), or relative,
d_nuc / (d_nuc + d_edge) with d_edge the distance to the cell edge, so 0 is
the nucleus edge and 1 the cell edge whatever the cell's size ('relative').
The chosen distance range is cut into n equal bands; each band is measured
like an ImageJ ROI (raw values, cytosol.intensity.STATS), together with the
particles whose centre lies in it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import ndimage as ndi

from .intensity import STATS, _fmt

MODES = (('relative', '상대 거리 (0 = 핵 경계, 1 = 세포 경계)'),
         ('absolute', '핵 경계에서의 거리 (µm)'))


@dataclass
class BandSettings:
    mode: str = 'relative'
    start: float = 0.0
    stop: float = 1.0
    n: int = 10

    def edges(self) -> np.ndarray:
        return np.linspace(self.start, self.stop, max(1, int(self.n)) + 1)

    def unit(self, px_um) -> str:
        if self.mode == 'relative':
            return ''
        return 'µm' if px_um else 'px'


def distance_map(cells, px_um, mode='relative') -> np.ndarray:
    """Distance of every cytosol pixel from its cell's nucleus (NaN elsewhere
    and in cells without a nucleus)."""
    out = np.full(cells.labels.shape, np.nan)
    if cells.nuclei is None:
        return out
    scale = px_um or 1.0
    for l, sl in enumerate(ndi.find_objects(cells.labels), start=1):
        if sl is None:
            continue
        sl = tuple(slice(max(s.start - 1, 0), s.stop + 1) for s in sl)
        cell = cells.labels[sl] == l
        nuc = (cells.nuclei[sl] == l) & cell
        cyto = cell & ~nuc
        if not nuc.any() or not cyto.any():
            continue
        d_nuc = ndi.distance_transform_edt(~nuc)
        if mode == 'relative':
            d_edge = ndi.distance_transform_edt(cell)
            d = d_nuc / np.maximum(d_nuc + d_edge, 1e-9)
        else:
            d = (d_nuc - 0.5) * scale  # from the nucleus outline (pixel edges)
        view = out[sl]
        view[cyto] = d[cyto]
    return out


def band_labels(cells, px_um, s: BandSettings, dist=None) -> np.ndarray:
    """Band number (1..n) of every cytosol pixel inside the range, else 0."""
    d = distance_map(cells, px_um, s.mode) if dist is None else dist
    e = s.edges()
    b = np.zeros(d.shape, np.int32)
    ok = np.isfinite(d) & (d >= e[0]) & (d <= e[-1])
    b[ok] = np.clip(np.searchsorted(e, d[ok], side='right'), 1, len(e) - 1)
    return b


def measure_bands(planes, cells, channels, px_um, s: BandSettings, particles=None,
                  channel_index=None, stats=('Mean',)) -> list[dict]:
    """One row per cell (with a nucleus) and band."""
    bands = band_labels(cells, px_um, s)
    e = s.edges()
    unit = s.unit(px_um)
    dname = 'distance' + (f'_{unit}' if unit else '_rel')
    chans = list(range(len(channels))) if channel_index is None else list(channel_index)
    px2 = px_um ** 2 if px_um else 1.0
    pmask = particles.mask if particles is not None else None
    centres = None
    if particles is not None:
        comp = particles.components(cells)
        if comp.max():
            idx = np.arange(1, comp.max() + 1)
            cy = np.round(ndi.mean(np.indices(comp.shape)[0], comp, idx)).astype(int)
            cx = np.round(ndi.mean(np.indices(comp.shape)[1], comp, idx)).astype(int)
            centres = (cy, cx)
    rows = []
    for l in cells.ids():
        cell_b = np.where(cells.labels == l, bands, 0)
        if not cell_b.any():
            continue
        if centres is not None:
            cb = cell_b[centres]
            n_part = np.bincount(cb, minlength=len(e))
        for k in range(1, len(e)):
            m = cell_b == k
            a = int(m.sum())
            row = {'roi': f'cell{l:03d}', 'status': cells.status.get(l, 'ok'), 'band': k,
                   dname: round(float((e[k - 1] + e[k]) / 2), 4),
                   f'{dname}_from': round(float(e[k - 1]), 4), f'{dname}_to': round(float(e[k]), 4),
                   'area_px': a, 'area_um2': round(a * px2, 4) if px_um else ''}
            pm = None
            if pmask is not None:
                pm = m & pmask
                row['n_particles'] = int(n_part[k]) if centres is not None else 0
                row['particle_area_um2'] = round(int(pm.sum()) * px2, 4) if px_um else int(pm.sum())
                row['particle_area_fraction'] = _fmt(pm.sum() / a if a else math.nan)
            for c in chans:
                v = planes[c][m].astype(np.float64)
                for k_, val in _stats(v, px2, stats).items():
                    row[f'{channels[c]}_{k_}'] = _fmt(val)
                if pm is not None:
                    vp = planes[c][pm].astype(np.float64)
                    row[f'{channels[c]}_particle_Mean'] = _fmt(vp.mean() if vp.size else math.nan)
            rows.append(row)
    return rows


def _stats(v, px2, stats) -> dict:
    a = v.size
    mean = v.mean() if a else math.nan
    out = {'Mean': mean, 'StdDev': v.std(ddof=1) if a > 1 else (0.0 if a else math.nan),
           'Min': v.min() if a else math.nan, 'Max': v.max() if a else math.nan,
           'IntDen': a * px2 * mean if a else math.nan, 'RawIntDen': v.sum() if a else math.nan}
    return {k: out[k] for k in STATS if k in stats}


def band_outlines(cells, px_um, s: BandSettings) -> list[np.ndarray]:
    """Pixel-edge outlines of every band of every cell (for the overlay)."""
    from .intensity import trace_outlines

    b = band_labels(cells, px_um, s)
    loops = []
    for l, sl in enumerate(ndi.find_objects(cells.labels), start=1):
        if sl is None:
            continue
        cb = np.where(cells.labels[sl] == l, b[sl], 0)
        for k in np.unique(cb):
            if k:
                loops += trace_outlines(cb == k, sl[1].start, sl[0].start)
    return loops


def numeric_columns(rows) -> list[str]:
    cols = []
    for r in rows:
        for k, v in r.items():
            if k not in cols and isinstance(v, (int, float)) and not isinstance(v, bool):
                cols.append(k)
    return cols


def draw_bands(ax, rows, x, y):
    """Thin line per cell (and image), mean ± SD over cells per band in bold."""
    ax.clear()
    groups = {}
    for r in rows:
        if isinstance(r.get(x), (int, float)) and isinstance(r.get(y), (int, float)):
            groups.setdefault((r.get('image_id', ''), r.get('timepoint', ''), r['roi']), []).append(r)
    for g in groups.values():
        g = sorted(g, key=lambda r: r[x])
        ax.plot([r[x] for r in g], [r[y] for r in g], color='0.6', lw=0.7, alpha=0.6)
    by_band = {}
    for g in groups.values():
        for r in g:
            if not (isinstance(r[y], float) and math.isnan(r[y])):
                by_band.setdefault(r['band'], []).append((r[x], r[y]))
    if by_band and len(groups) > 1:
        ks = sorted(by_band)
        mx = [float(np.mean([p[0] for p in by_band[k]])) for k in ks]
        my = np.array([float(np.mean([p[1] for p in by_band[k]])) for k in ks])
        sd = np.array([float(np.std([p[1] for p in by_band[k]])) for k in ks])
        ax.fill_between(mx, my - sd, my + sd, color='tab:red', alpha=0.15, lw=0)
        ax.plot(mx, my, color='tab:red', lw=2, label=f'mean ± SD ({len(groups)} cells)')
        ax.legend(fontsize=8, frameon=False, loc='best')
    ax.set_xlabel(x)
    ax.set_ylabel(y)
    ax.grid(True, color='0.85', lw=0.6)
