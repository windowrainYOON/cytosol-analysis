"""Cell / cytosol ROIs from a nucleus channel and a dim "background" channel.

GUI-independent: the desktop app (cytosol.app) and scripts both use this.
Adapted from the mito-tracking project's cell_roi.py (nucleus-seeded watershed
over the saturated autofluorescence), with every size given in µm so it works
across pixel sizes.

Pipeline (segment_cells):
  1. background channel: smooth and saturate (a very bright LUT), so the dim
     signal fills the whole cytoplasm while the gaps between cells stay dark
  2. nuclei: Otsu on the nucleus channel (dim out-of-focus nuclei fall below
     it), or a manual threshold in nucleus-channel units; touching nuclei
     split by a distance-transform watershed
  3. merge: max(saturated background, nuclei) -> each cell is one solid blob;
     foreground = Otsu on that merged image, or a manual threshold given in
     background-channel units
  4. one nucleus = one cell: watershed from the nuclei over the dark
     cell-cell "valleys" (Sato filter) of the merged image. Without a nucleus
     channel, seeds come from the distance map and over-split regions whose
     shared border is not darker than their interiors are merged.
  4b. optional size range (`fit_size`): regions larger than the maximum are
     cut at the cell-cell valleys into as many pieces as fit the range
     (seeds at distance-map maxima, k-means where there are too few), and
     regions smaller than the minimum are merged with the neighbour across
     the weakest border when the result fits; cells (and nuclei) still
     outside [min, max] are then dropped
  5. cells cut by the image frame: by default the frame side is replaced by
     an inner border `edge_margin_um` inside the frame, so the ROI no longer
     runs along the frame ('trim'); 'exclude' drops them, 'keep' leaves them.

threshold_cells is the plain manual mode: every connected area at or above
a threshold in the background channel is a cell (holes filled), the nucleus
is the largest area at or above the nucleus threshold inside it; nothing
else. It stays available whatever the automatic pipeline becomes.

CellRois holds the result as a label image and supports the GUI edits
(add / subtract a drawn area, new cell, delete, undo) and ImageJ ROI I/O.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
from scipy import ndimage as ndi
from skimage import draw, feature, filters, measure, morphology, segmentation, transform

EDGE_MODES = ('trim', 'exclude', 'keep')


@dataclass
class RoiParams:
    saturation: float | None = None  # background value shown as full white; None = auto
    sat_percentile: float = 50.0     # auto saturation = this percentile of the smoothed channel
    smooth_um: float = 0.8           # Gaussian smoothing of the merged image
    fg_k: float = 1.0                # foreground threshold = Otsu * fg_k
    min_cell_um2: float = 80.0
    max_cell_um2: float = 0.0        # 0 = no upper limit
    min_nucleus_um2: float = 15.0
    max_nucleus_um2: float = 0.0     # 0 = no upper limit
    fit_size: bool = False           # merge / split touching regions to fit the size range
    nucleus_split_um: float = 6.0    # min distance between nucleus centers when splitting
    nucleus_neck_um: float = 1.0     # how much narrower the neck between two touching nuclei must be
    edge_mode: str = 'trim'
    edge_margin_um: float = 1.0
    work_px_um: float = 0.2          # computations run at about this pixel size
    # manual thresholds in raw channel values (None = Otsu): nucleus channel
    # (after light smoothing) and background channel (cell vs. gap)
    nuc_threshold: float | None = None
    cell_threshold: float | None = None


def _norm(img):
    lo, hi = np.percentile(img, [0.5, 99.5])
    return np.clip((img - lo) / max(hi - lo, 1e-9), 0, 1)


def auto_saturation(bg: np.ndarray, px_um: float, p: RoiParams = RoiParams()) -> float:
    s = filters.gaussian(bg.astype(np.float32), max(0.5 / px_um, 0.5), preserve_range=True)
    v = float(np.percentile(s, p.sat_percentile))
    return v if v > 0 else float(s.max() or 1.0)


def brighten(bg: np.ndarray, saturation: float) -> np.ndarray:
    """Background channel with a bright LUT: 0..saturation -> 0..1, clipped."""
    lo = float(np.percentile(bg, 0.5))
    return np.clip((bg.astype(np.float32) - lo) / max(saturation - lo, 1e-9), 0, 1)


def nucleus_signal(nuc: np.ndarray, px_um: float) -> np.ndarray:
    """The nucleus channel as thresholded: lightly smoothed, raw units."""
    return filters.gaussian(nuc.astype(np.float32), max(0.3 / px_um, 0.5), preserve_range=True)


def nucleus_threshold(s: np.ndarray, p: RoiParams) -> float:
    return float(p.nuc_threshold) if p.nuc_threshold is not None else float(filters.threshold_otsu(s))


def segment_nuclei(nuc: np.ndarray, px_um: float, p: RoiParams) -> np.ndarray:
    s = nucleus_signal(nuc, px_um)
    m = s > nucleus_threshold(s, p)
    m = ndi.binary_opening(m, morphology.disk(max(1, round(0.4 / px_um))))
    m = ndi.binary_fill_holes(m)
    m = morphology.remove_small_objects(m, max_size=int(p.min_nucleus_um2 / px_um ** 2))
    # split touching nuclei
    dist = ndi.distance_transform_edt(m)
    dist = filters.gaussian(dist, max(0.5 / px_um, 1))
    lab0 = measure.label(m)
    # a seed per distance maximum that stands out by `nucleus_neck_um` from the
    # neck joining it to its neighbour, so notched nuclei are not cut
    peaks = morphology.h_maxima(dist, p.nucleus_neck_um / px_um) & m
    pk = np.array([r.centroid for r in measure.regionprops(measure.label(peaks))], int).reshape(-1, 2)
    # seeds of one nucleus closer than nucleus_split_um: keep the deepest
    keep = []
    for y, x in sorted(pk.tolist(), key=lambda q: -dist[q[0], q[1]]):
        if all(lab0[y, x] != lab0[a, b] or np.hypot(y - a, x - b) * px_um >= p.nucleus_split_um
               for a, b in keep):
            keep.append((y, x))
    markers = np.zeros(m.shape, np.int32)
    for i, (y, x) in enumerate(keep, 1):
        markers[y, x] = i
    for r in measure.regionprops(lab0):  # every nucleus gets at least one seed
        if not markers[r.slice][r.image].any():
            cy, cx = map(int, r.coords[np.argmax(dist[tuple(r.coords.T)])])
            markers[cy, cx] = markers.max() + 1
    lab = segmentation.watershed(-dist, markers, mask=m)
    lo, hi = p.min_nucleus_um2 / px_um ** 2, p.max_nucleus_um2 / px_um ** 2
    if p.fit_size:
        lab = fit_sizes(lab, s, lo, hi, min_border=max(2, int(0.5 / px_um)))
    # drop fragments the split left too small (and nuclei above the maximum)
    out = [r.label for r in measure.regionprops(lab) if r.area < lo or (hi and r.area > hi)]
    if out:
        lab[np.isin(lab, out)] = 0
    return segmentation.relabel_sequential(lab)[0]


# ---------------------------------------------------------------------------
# size range: split regions above it, merge regions below it
# ---------------------------------------------------------------------------


def _size_penalty(a, lo, hi) -> float:
    """0 inside [lo, hi] (hi = 0: no maximum), else the log of how far outside."""
    if lo and a < lo:
        return float(np.log(lo / max(a, 1)))
    if hi and a > hi:
        return float(np.log(a / hi))
    return 0.0


def _split_seeds(m, dist, n, lo, method):
    """n seed points (row, col) inside mask m."""
    if method == 'peaks':
        md = max(1, int(0.7 * np.sqrt(lo / np.pi))) if lo else 1
        pk = feature.peak_local_max(dist, min_distance=md, num_peaks=n,
                                    labels=m.astype(np.int32), exclude_border=False)
        return pk if len(pk) == n else None
    from scipy.cluster.vq import kmeans2
    pts = np.argwhere(m).astype(float)
    if len(pts) < n:
        return None
    cen, _ = kmeans2(pts, n, minit='++', seed=0)
    # each center to its nearest pixel inside the mask
    idx = [int(np.argmin(((pts - c) ** 2).sum(1))) for c in cen]
    if len(set(idx)) < n:
        return None
    return pts[idx].astype(int)


def _split_region(m, ridge, lo, hi, keep=None):
    """Best split of one region (bool crop) into pieces fitting [lo, hi];
    returns a label crop (1..n) or None when splitting does not help.
    `keep` (bool crop, e.g. the nucleus) stays whole in piece 1."""
    area = int(m.sum())
    n_min = int(np.ceil(area / hi))
    n_max = max(n_min, int(area // lo)) if lo else n_min
    n_max = min(n_max, n_min + 3, 30)
    dist = ndi.distance_transform_edt(m)
    # compact watershed: pieces grow about evenly from their seeds (Voronoi-like)
    # and bend toward the bright cell-cell ridges where there are any
    cost = np.zeros(m.shape) if ridge is None else np.clip(ridge, 0, None) * m
    best, best_score = None, _size_penalty(area, lo, hi)
    for n in range(max(2, n_min), max(2, n_max) + 1):
        compact = 0.5 / max(np.sqrt(area / n / np.pi), 1.0)
        for method in ('peaks', 'kmeans'):
            seeds = _split_seeds(m, dist, n, lo, method)
            if seeds is None:
                continue
            markers = np.zeros(m.shape, np.int32)
            if keep is not None and keep.any():
                # the seed nearest the kept area is replaced by the area itself
                c = np.argwhere(keep).mean(0)
                seeds = np.delete(seeds, np.argmin(((seeds - c) ** 2).sum(1)), 0)
                markers[tuple(seeds.T)] = np.arange(2, n + 1)
                markers[keep] = 1
            else:
                markers[tuple(seeds.T)] = np.arange(1, n + 1)
            lab = segmentation.watershed(cost, markers, mask=m, compactness=compact)
            areas = np.bincount(lab.ravel(), minlength=n + 1)[1:]
            score = sum(_size_penalty(a, lo, hi) for a in areas)
            if score < best_score - 1e-6:
                best, best_score = lab, score
        if best is not None and best_score == 0:
            break  # fewest pieces that all fit
    return best


def fit_sizes(lab, img, lo, hi, ridge=None, min_border=3, nuclei=None):
    """Split labels larger than hi and merge labels smaller than lo with a
    neighbour (areas in pixels; hi = 0: no maximum).

    Splits follow `ridge` (bright = border between cells) when given, else the
    distance map. Merges take the pair whose shared border is least darker
    than their interiors in `img`, among those whose merged area fits better.
    `nuclei` (labelled like lab) is kept in step: a split cell keeps its
    nucleus in the piece holding most of it, merged cells' nuclei join.
    """
    lab = lab.copy()
    nxt = int(lab.max()) + 1
    if hi:
        for r in measure.regionprops(lab):
            if r.area <= hi:
                continue
            sl = tuple(slice(max(s.start - 1, 0), s.stop + 1) for s in r.slice)
            m = lab[sl] == r.label
            nm = None if nuclei is None else (nuclei[sl] == r.label) & m
            sub = _split_region(m, None if ridge is None else ridge[sl], lo, hi, keep=nm)
            if sub is None:
                continue
            keep = 1
            view = lab[sl]
            for k in range(1, int(sub.max()) + 1):
                if k != keep:
                    view[sub == k] = nxt
                    nxt += 1
            if nuclei is not None:
                nv = nuclei[sl]
                nv[(nv == r.label) & (view != r.label)] = 0
    if lo:
        area = dict(zip(*np.unique(lab[lab > 0], return_counts=True)))
        area = {int(k): int(v) for k, v in area.items()}
        med = {}
        while True:
            small = {l for l, a in area.items() if a < lo}
            if not small:
                break
            best = None
            for (a, b), (bmean, blen) in _border_stats(lab, img).items():
                if blen < min_border or (a not in small and b not in small):
                    continue
                gain = (_size_penalty(area[a], lo, hi) + _size_penalty(area[b], lo, hi)
                        - _size_penalty(area[a] + area[b], lo, hi))
                if gain <= 1e-6:
                    continue
                for l in (a, b):
                    if l not in med:
                        med[l] = float(np.median(img[lab == l]))
                contrast = min(med[a], med[b]) - bmean
                if best is None or contrast < best[0]:
                    best = (contrast, a, b)
            if best is None:
                break
            _, a, b = best
            if area[b] > area[a]:
                a, b = b, a  # the larger keeps its label
            lab[lab == b] = a
            area[a] += area.pop(b)
            med.pop(b, None)
            med.pop(a, None)
            if nuclei is not None:
                nuclei[nuclei == b] = a
    return lab


def _border_stats(lab, img):
    """{(a, b): (mean img along the shared border of labels a < b, border length)}."""
    keys, vals = [], []
    for a, b, ia, ib in ((lab[:, :-1], lab[:, 1:], img[:, :-1], img[:, 1:]),
                         (lab[:-1, :], lab[1:, :], img[:-1, :], img[1:, :])):
        m = (a != b) & (a > 0) & (b > 0)
        pa, pb = np.minimum(a[m], b[m]).astype(np.int64), np.maximum(a[m], b[m]).astype(np.int64)
        keys.append(pa * (int(lab.max()) + 1) + pb)
        vals.append((ia[m] + ib[m]) / 2)
    keys, vals = np.concatenate(keys), np.concatenate(vals)
    if not len(keys):
        return {}
    u, inv = np.unique(keys, return_inverse=True)
    n = np.bincount(inv)
    mean = np.bincount(inv, weights=vals) / n
    k = int(lab.max()) + 1
    return {(int(x // k), int(x % k)): (float(v), int(c)) for x, v, c in zip(u, mean, n)}


def _merge_regions(lab, img, contrast_tau, min_area, min_border):
    lab = lab.copy()
    # per-label area and median, updated only for the merged label
    fgl, fgv = lab[lab > 0], img[lab > 0]
    order = np.lexsort((fgv, fgl))
    fgl, fgv = fgl[order], fgv[order]
    ids, start, area = np.unique(fgl, return_index=True, return_counts=True)
    med = {int(i): float(np.median(fgv[s0:s0 + n])) for i, s0, n in zip(ids, start, area)}
    area = dict(zip(ids.tolist(), area.tolist()))
    while len(area) > 1:
        best = None
        for (a, b), (bmean, blen) in _border_stats(lab, img).items():
            if blen < min_border:
                continue
            contrast = min(med[a], med[b]) - bmean
            small = min(area[a], area[b]) < min_area
            if contrast < contrast_tau or small:
                key = (0 if small else 1, contrast)
                if best is None or key < best[0]:
                    best = (key, a, b)
        if best is None:
            break
        _, a, b = best
        lab[lab == b] = a
        area[a] += area.pop(b)
        med.pop(b)
        med[a] = float(np.median(img[lab == a]))
    return segmentation.relabel_sequential(lab)[0]


def _join_nuclei(nuclei, lab, radius):
    """Nuclei of a cell in several pieces become one (closed, filled, largest)."""
    out = nuclei * (nuclei == lab)
    se = morphology.disk(radius)
    for r in measure.regionprops(out):
        sl = tuple(slice(max(s.start - radius - 1, 0), s.stop + radius + 1) for s in r.slice)
        m = out[sl] == r.label
        if measure.label(m).max() <= 1:
            continue
        j = ndi.binary_fill_holes(ndi.binary_closing(np.pad(m, radius + 1), se))
        j = j[radius + 1:-radius - 1, radius + 1:-radius - 1] & (lab[sl] == r.label)
        view = out[sl]
        view[m] = 0
        view[_largest(j)] = r.label
    return out


def _largest(mask):
    cc = measure.label(mask)
    if cc.max() <= 1:
        return mask
    return cc == np.argmax(np.bincount(cc.ravel())[1:]) + 1


def _smooth_labels(lab, radius, keep=None):
    """Open each ROI, fill holes, keep its largest piece; `keep` pixels are never lost."""
    out = np.zeros_like(lab)
    se = morphology.disk(max(1, radius))
    for r in measure.regionprops(lab):
        sl = tuple(slice(max(s.start - radius - 1, 0), s.stop + radius + 1) for s in r.slice)
        m = ndi.binary_opening(lab[sl] == r.label, se)
        if keep is not None:
            m |= keep[sl] == r.label
        m = ndi.binary_fill_holes(m)
        if m.any():
            m = _largest(m)
            o = out[sl]
            o[m & (o == 0)] = r.label
    return out


def _bg_floor(bg) -> float:
    return float(np.percentile(bg, 0.5))  # the 0 of brighten()


def _cell_threshold(dens, bg, sat, p: RoiParams) -> tuple[float, float]:
    """(threshold on the merged 0..1 image, the same in background-channel units)."""
    lo = _bg_floor(bg)
    span = max(sat - lo, 1e-9)
    if p.cell_threshold is not None:
        return (float(p.cell_threshold) - lo) / span, float(p.cell_threshold)
    t01 = float(filters.threshold_otsu(dens)) * p.fg_k
    return t01, lo + t01 * span


class ThresholdPreview:
    """Masks and values of the two thresholds without segmenting, for a live preview.

    The expensive part (saturating, downsampling, smoothing the nucleus
    channel) runs once here; calling the object with new thresholds is cheap,
    so a slider can update the preview while it moves.
    """

    def __init__(self, bg: np.ndarray, nuc: np.ndarray | None, px_um: float | None,
                 p: RoiParams | None = None):
        self.p = p = p or RoiParams()
        px_um = px_um or 0.1
        self.shape = H, W = bg.shape
        self.k = k = max(1, int(round(p.work_px_um / px_um)))
        self.wpx = px_um * k

        def down(a):
            a = a.astype(np.float32)
            if k == 1:
                return a
            h, w = (H // k) * k, (W // k) * k
            return a[:h, :w].reshape(h // k, k, w // k, k).mean((1, 3))

        self.bg = bg
        self.saturation = p.saturation if p.saturation else auto_saturation(bg, px_um, p)
        self.merged = down(brighten(bg, self.saturation))
        self.nuc_signal = None if nuc is None else nucleus_signal(down(nuc), self.wpx)

    def _up(self, m):
        H, W = self.shape
        if self.k > 1:
            m = np.repeat(np.repeat(m, self.k, 0), self.k, 1)
        out = np.zeros((H, W), bool)
        out[:m.shape[0], :m.shape[1]] = m[:H, :W]
        return out

    def __call__(self, nuc_threshold: float | None = None,
                 cell_threshold: float | None = None) -> dict:
        """{'cell': bool (Y, X), 'nuc': bool (Y, X) or None,
            'cell_threshold', 'nuc_threshold' (raw units; Otsu where None),
            'saturation'}."""
        p = replace(self.p, nuc_threshold=nuc_threshold, cell_threshold=cell_threshold)
        merged, nmask, nuc_thr = self.merged, None, None
        if self.nuc_signal is not None:
            nuc_thr = nucleus_threshold(self.nuc_signal, p)
            nmask = self.nuc_signal > nuc_thr
            merged = np.maximum(merged, nmask.astype(np.float32))
        dens = filters.gaussian(merged, max(p.smooth_um / self.wpx, 0.5))
        t01, cell_thr = _cell_threshold(dens, self.bg, self.saturation, p)
        return {'cell': self._up(dens > t01), 'nuc': None if nmask is None else self._up(nmask),
                'cell_threshold': cell_thr, 'nuc_threshold': nuc_thr,
                'saturation': self.saturation}


def threshold_preview(bg: np.ndarray, nuc: np.ndarray | None, px_um: float | None,
                      p: RoiParams | None = None) -> dict:
    """ThresholdPreview evaluated once at p's thresholds."""
    p = p or RoiParams()
    return ThresholdPreview(bg, nuc, px_um, p)(p.nuc_threshold, p.cell_threshold)


def segment_cells(bg: np.ndarray, nuc: np.ndarray | None, px_um: float | None,
                  p: RoiParams | None = None) -> 'CellRois':
    """Cell ROIs from a background-signal plane and an optional nucleus plane."""
    p = p or RoiParams()
    px_um = px_um or 0.1
    H, W = bg.shape
    k = max(1, int(round(p.work_px_um / px_um)))
    wpx = px_um * k

    def down(a):
        a = a.astype(np.float32)
        if k == 1:
            return a
        h, w = (H // k) * k, (W // k) * k
        a = a[:h, :w].reshape(h // k, k, w // k, k).mean((1, 3))
        return a

    sat = p.saturation if p.saturation else auto_saturation(bg, px_um, p)
    b = down(brighten(bg, sat))
    nuclei = None
    nuc_thr = None
    if nuc is not None:
        dn_ = down(nuc)
        nuc_thr = nucleus_threshold(nucleus_signal(dn_, wpx), p)
        nuclei = segment_nuclei(dn_, wpx, p)
        merged = np.maximum(b, (nuclei > 0).astype(np.float32))
    else:
        merged = b
    sig = max(p.smooth_um / wpx, 0.5)
    dens = filters.gaussian(merged, sig)
    t01, cell_thr = _cell_threshold(dens, bg, sat, p)
    fg = dens > t01
    r_open = max(1, round(1.0 / wpx))
    fg = ndi.binary_opening(fg, morphology.disk(r_open))
    min_cell = p.min_cell_um2 / wpx ** 2
    fg = morphology.remove_small_objects(fg, max_size=int(min_cell * 0.3))
    fg = morphology.remove_small_holes(fg, max_size=int(min_cell * 0.3))

    d4 = filters.gaussian(merged, max(0.4 / wpx, 0.5))
    sig_v = [max(0.8 / wpx, 1), max(1.4 / wpx, 1.5)]
    v = filters.sato(d4, sigmas=sig_v, black_ridges=True)
    vn = v / max(np.percentile(v, 99.5), 1e-9)

    if nuclei is not None and nuclei.max() > 0:
        fg |= nuclei > 0
        dn = dens / max(np.percentile(dens[fg], 99), 1e-9)
        lab = segmentation.watershed(vn + 0.5 * (1 - np.clip(dn, 0, 1)), nuclei, mask=fg)
        lab = _smooth_labels(lab, max(1, round(0.6 / wpx)), keep=nuclei)
    else:
        valley = vn > np.percentile(vn[fg], 88) if fg.any() else np.zeros_like(fg)
        dist = filters.gaussian(ndi.distance_transform_edt(fg & ~valley), 1.5)
        pk = feature.peak_local_max(dist, min_distance=max(2, int(4 / wpx)),
                                    threshold_abs=max(1.0, 1.0 / wpx),
                                    labels=measure.label(fg), exclude_border=False)
        markers = np.zeros(fg.shape, np.int32)
        markers[tuple(pk.T)] = np.arange(1, len(pk) + 1)
        lab = segmentation.watershed(vn - 0.5 * dist / max(dist.max(), 1e-9), markers, mask=fg)
        lab = _merge_regions(lab, dens, 0.08, min_cell, max(3, int(1.5 / wpx)))
        lab = _smooth_labels(lab, max(1, round(0.6 / wpx)))
        nuclei = None

    max_cell = p.max_cell_um2 / wpx ** 2
    if p.fit_size:
        if nuclei is not None:
            nuclei = nuclei * (lab == nuclei)
        lab = fit_sizes(lab, dens, min_cell, max_cell, ridge=vn,
                        min_border=max(3, int(1.5 / wpx)), nuclei=nuclei)
        if nuclei is not None:  # merged cells: one nucleus from the joined pieces
            nuclei = _join_nuclei(nuclei, lab, max(1, round(1.0 / wpx)))
    # drop cells outside the size range (and their nuclei)
    for r in measure.regionprops(lab):
        if r.area < min_cell or (max_cell and r.area > max_cell):
            lab[lab == r.label] = 0
    if nuclei is not None:
        nuclei = nuclei * (lab == nuclei)
    lab, fw, _ = segmentation.relabel_sequential(lab)
    if nuclei is not None:
        nuclei = np.asarray(fw[nuclei])

    def up(a):
        if a is None:
            return None
        if k > 1:
            a = np.repeat(np.repeat(a, k, 0), k, 1)
        out = np.zeros((H, W), np.int32)
        h, w = min(H, a.shape[0]), min(W, a.shape[1])
        out[:h, :w] = a[:h, :w]
        if h < H:
            out[h:, :w] = out[h - 1:h, :w]
        if w < W:
            out[:, w:] = out[:, w - 1:w]
        return out

    lab, nuclei = up(lab), up(nuclei)
    if k > 1:  # smooth the blocky upsampled borders
        lab = _smooth_labels(lab, max(1, k // 2 + 1), keep=nuclei)

    rois = CellRois(lab.astype(np.int32), nuclei, px_um)
    rois.saturation = sat
    rois.nuc_threshold, rois.cell_threshold = nuc_thr, cell_thr
    rois.apply_edge_mode(p.edge_mode, p.edge_margin_um, p.min_cell_um2)
    return rois


def size_range(areas, fence=1.5) -> tuple[float, float] | None:
    """(smallest, largest) of the areas once outliers are set aside: Tukey
    fences on log area, so debris and clumps of touching cells do not set the
    range. None without areas."""
    a = np.asarray([x for x in areas if x and x > 0], float)
    if not len(a):
        return None
    if len(a) >= 4:
        la = np.log(a)
        q1, q3 = np.percentile(la, [25, 75])
        keep = (la >= q1 - fence * (q3 - q1)) & (la <= q3 + fence * (q3 - q1))
        if keep.any():
            a = a[keep]
    return float(a.min()), float(a.max())


def image_size_range(areas, below=4.0, above=3.0) -> tuple[float, float] | None:
    """Size range for one image: the typical (median) area / `below` to
    × `above`, widened to the areas size_range keeps. One image holds only a
    few whole cells, so the smallest – largest of them alone is far too
    narrow (one cell gives a single value). None without areas."""
    a = np.asarray([x for x in areas if x and x > 0], float)
    if not len(a):
        return None
    lo, hi = size_range(a)
    m = float(np.exp(np.median(np.log(a))))
    return max(1.0, min(lo, m / below)), max(hi, m * above)


def threshold_cells(bg: np.ndarray, nuc: np.ndarray | None, px_um: float | None,
                    cell_threshold: float, nuc_threshold: float | None = None,
                    p: RoiParams | None = None) -> 'CellRois':
    """Manual mode: cells = connected areas with bg >= cell_threshold (holes
    filled, since ImageJ polygons hold none); nucleus = the largest area with
    nuc >= nuc_threshold inside each cell. Only p's size ranges and frame
    handling apply; no smoothing, no splitting."""
    p = p or RoiParams()
    px = px_um or 0.1
    fg = ndi.binary_fill_holes(bg >= cell_threshold)
    lab = measure.label(fg, connectivity=1).astype(np.int32)
    lo, hi = p.min_cell_um2 / px ** 2, p.max_cell_um2 / px ** 2
    out = [r.label for r in measure.regionprops(lab) if r.area < lo or (hi and r.area > hi)]
    if out:
        lab[np.isin(lab, out)] = 0
    lab = segmentation.relabel_sequential(lab)[0].astype(np.int32)
    nuclei = None
    if nuc is not None and nuc_threshold is not None:
        nlo, nhi = p.min_nucleus_um2 / px ** 2, p.max_nucleus_um2 / px ** 2
        cand = measure.label((nuc >= nuc_threshold) & (lab > 0), connectivity=1)
        nuclei = np.zeros_like(lab)
        best = {}
        for r in measure.regionprops(cand):
            if r.area < nlo or (nhi and r.area > nhi):
                continue
            l = int(lab[tuple(r.coords[0])])
            if r.area > best.get(l, (0, None))[0]:
                best[l] = (r.area, r)
        for l, (_, r) in best.items():
            m = ndi.binary_fill_holes(r.image) & (lab[r.slice] == l)
            nuclei[r.slice][m] = l
    rois = CellRois(lab, nuclei, px_um)
    rois.cell_threshold, rois.nuc_threshold = float(cell_threshold), (
        None if nuclei is None else float(nuc_threshold))
    rois.apply_edge_mode(p.edge_mode, p.edge_margin_um, p.min_cell_um2)
    return rois


# ---------------------------------------------------------------------------
# ROI set: labels + editing + ImageJ I/O
# ---------------------------------------------------------------------------


@dataclass
class CellRois:
    labels: np.ndarray                    # (H, W) int32, 0 = background, k = cell k
    nuclei: np.ndarray | None = None      # (H, W) int32, nucleus of cell k labelled k
    px_um: float | None = None
    status: dict = field(default_factory=dict)  # label -> 'ok' | 'edge-trimmed' | 'edge'
    saturation: float | None = None
    # thresholds the detection used, in raw channel values
    nuc_threshold: float | None = None
    cell_threshold: float | None = None
    _undo: list = field(default_factory=list, repr=False)
    _redo: list = field(default_factory=list, repr=False)
    max_undo: int = 30

    @property
    def shape(self):
        return self.labels.shape

    def ids(self) -> list[int]:
        return [int(i) for i in np.unique(self.labels) if i > 0]

    def __len__(self):
        return len(self.ids())

    # ---- edge cells ----------------------------------------------------

    def touches_frame(self, label, margin_px=1) -> bool:
        m = self.labels == label
        e = margin_px
        return bool(m[:e].any() or m[-e:].any() or m[:, :e].any() or m[:, -e:].any())

    def apply_edge_mode(self, mode='trim', margin_um=1.0, min_cell_um2=0.0):
        """Handle cells cut by the image frame (see module docstring)."""
        if mode not in EDGE_MODES:
            raise ValueError(f'edge mode must be one of {EDGE_MODES}')
        H, W = self.shape
        px = self.px_um or 0.1
        m_px = max(2, int(round(margin_um / px)))
        yy, xx = np.ogrid[:H, :W]
        inner = (yy >= m_px) & (yy < H - m_px) & (xx >= m_px) & (xx < W - m_px)
        for l in self.ids():
            if not self.touches_frame(l):
                self.status[l] = 'ok'
                continue
            if mode == 'keep':
                self.status[l] = 'edge'
            elif mode == 'exclude':
                self._erase(l)
            else:
                cell = (self.labels == l) & inner
                nuc = self.nuclei == l if self.nuclei is not None else None
                cc = measure.label(cell)
                if cc.max() == 0:
                    self._erase(l)
                    continue
                # keep the piece holding most of the nucleus, else the largest
                if nuc is not None and (nuc & cell).any():
                    keep = np.argmax(np.bincount(cc[nuc & cell], minlength=cc.max() + 1)[1:]) + 1
                else:
                    keep = np.argmax(np.bincount(cc.ravel())[1:]) + 1
                new = cc == keep
                if new.sum() * px ** 2 < min_cell_um2:
                    self._erase(l)
                    continue
                self.labels[(self.labels == l) & ~new] = 0
                if self.nuclei is not None:
                    self.nuclei[(self.nuclei == l) & ~new] = 0
                self.status[l] = 'edge-trimmed'

    def _erase(self, l):
        self.labels[self.labels == l] = 0
        if self.nuclei is not None:
            self.nuclei[self.nuclei == l] = 0
        self.status.pop(l, None)

    # ---- editing -------------------------------------------------------

    def _push(self):
        nuc = None if self.nuclei is None else self.nuclei.copy()
        self._undo.append((self.labels.copy(), nuc, dict(self.status)))
        del self._undo[:-self.max_undo]
        self._redo.clear()

    def undo(self) -> bool:
        if not self._undo:
            return False
        nuc = None if self.nuclei is None else self.nuclei.copy()
        self._redo.append((self.labels.copy(), nuc, dict(self.status)))
        self.labels, self.nuclei, self.status = self._undo.pop()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        nuc = None if self.nuclei is None else self.nuclei.copy()
        self._undo.append((self.labels.copy(), nuc, dict(self.status)))
        self.labels, self.nuclei, self.status = self._redo.pop()
        return True

    def polygon_mask(self, xy) -> np.ndarray:
        """Boolean mask of a polygon given as (N, 2) x, y image coordinates.

        Pixel (i, j) covers [j, j+1) x [i, i+1) and is inside when its center
        is, as in ImageJ.
        """
        xy = np.asarray(xy, float) - 0.5
        rr, cc = draw.polygon(xy[:, 1], xy[:, 0], self.shape)
        m = np.zeros(self.shape, bool)
        m[rr, cc] = True
        return m

    def _tidy(self, l, prefer=None):
        """A cell is one filled piece (an ImageJ polygon cannot hold holes).

        When it falls apart, the piece overlapping `prefer` (the cell before an
        edit) is kept, else the one with the nucleus, else the largest.
        """
        m = self.labels == l
        if not m.any():
            self._erase(l)
            return
        cc = measure.label(m)
        keep = _largest(m)
        for ref in (prefer, None if self.nuclei is None else self.nuclei == l):
            if cc.max() > 1 and ref is not None and (ref & m).any():
                votes = np.bincount(cc[ref & m], minlength=cc.max() + 1)
                votes[0] = 0
                keep = cc == np.argmax(votes)
                break
        filled = ndi.binary_fill_holes(keep)
        self.labels[m & ~keep] = 0
        self.labels[filled & (self.labels == 0)] = l

    def add(self, l: int, mask: np.ndarray):
        """Add the drawn area to cell l (taking it from other cells)."""
        self._push()
        before = self.labels == l
        others = set(np.unique(self.labels[mask]).tolist()) - {0, l}
        self.labels[mask] = l
        for o in others:
            self._tidy(o)
        self._tidy(l, prefer=before)
        self.status.setdefault(l, 'ok')

    def subtract(self, l: int | None, mask: np.ndarray):
        """Remove the drawn area from cell l (from every cell if l is None)."""
        self._push()
        targets = [l] if l else [int(i) for i in np.unique(self.labels[mask]) if i > 0]
        for t in targets:
            self.labels[mask & (self.labels == t)] = 0
            self._tidy(t)

    def new_cell(self, mask: np.ndarray) -> int:
        """Drawn area becomes a new cell (only where no other cell is)."""
        m = mask & (self.labels == 0)
        if not m.any():
            return 0
        self._push()
        l = int(self.labels.max()) + 1
        self.labels[_largest(m)] = l
        self.status[l] = 'ok'
        return l

    def find_nucleus(self, l: int, nuc: np.ndarray, threshold: float | None = None,
                     min_nucleus_um2: float = RoiParams.min_nucleus_um2) -> bool:
        """Detect the nucleus of cell l in a nucleus-channel plane (no undo step).

        The lightly smoothed channel is thresholded inside the cell (Otsu over
        the whole plane when threshold is None, as the detection does); the
        largest piece that is big enough becomes the cell's nucleus.
        """
        cell = self.labels == l
        if not cell.any():
            return False
        px = self.px_um or 0.1
        ys, xs = np.nonzero(cell)
        pad = max(4, int(round(2 / px)))
        y0, x0 = max(ys.min() - pad, 0), max(xs.min() - pad, 0)
        y1, x1 = ys.max() + pad + 1, xs.max() + pad + 1
        s = nucleus_signal(nuc[y0:y1, x0:x1], px)
        if threshold is None:
            threshold = float(filters.threshold_otsu(nucleus_signal(nuc, px)))
        m = (s > threshold) & cell[y0:y1, x0:x1]
        m = ndi.binary_opening(m, morphology.disk(max(1, round(0.4 / px))))
        m = ndi.binary_fill_holes(m) & cell[y0:y1, x0:x1]
        if self.nuclei is None:
            self.nuclei = np.zeros(self.shape, np.int32)
        self.nuclei[self.nuclei == l] = 0
        if not m.any():
            return False
        m = _largest(m)
        if m.sum() * px ** 2 < min_nucleus_um2:
            return False
        self.nuclei[y0:y1, x0:x1][m] = l
        return True

    def delete(self, l: int):
        self._push()
        self._erase(l)

    def label_at(self, x, y) -> int:
        H, W = self.shape
        xi, yi = int(x), int(y)
        if 0 <= xi < W and 0 <= yi < H:
            return int(self.labels[yi, xi])
        return 0

    def renumber(self):
        """Labels 1..n ordered top-to-bottom, left-to-right."""
        ids = self.ids()
        cy = {l: np.argwhere(self.labels == l).mean(0) for l in ids}
        order = sorted(ids, key=lambda l: (round(cy[l][0] / 50), cy[l][1]))
        lut = np.zeros(int(self.labels.max()) + 1, np.int32)
        for new, old in enumerate(order, 1):
            lut[old] = new
        self.labels = lut[self.labels]
        if self.nuclei is not None:
            self.nuclei = lut[np.clip(self.nuclei, 0, len(lut) - 1)] * (self.nuclei > 0)
        self.status = {int(lut[o]): s for o, s in self.status.items() if o < len(lut) and lut[o]}

    # ---- geometry ------------------------------------------------------

    def contour(self, l, mask=None, tolerance=0.5) -> np.ndarray | None:
        """Outer boundary of cell l as (N, 2) x, y polygon (pixel-edge coordinates)."""
        m = self.labels == l if mask is None else mask
        if not m.any():
            return None
        ys, xs = np.nonzero(m)
        y0, x0 = ys.min(), xs.min()
        sub = np.pad(m[y0:ys.max() + 1, x0:xs.max() + 1], 1).astype(float)
        cs = measure.find_contours(sub, 0.5)
        if not cs:
            return None
        c = max(cs, key=len)
        if tolerance:
            c = measure.approximate_polygon(c, tolerance)
        # find_contours gives pixel-center coords; +0.5 puts the line on the
        # pixel edges so ImageJ's mask matches ours
        xy = np.c_[c[:, 1] + x0 - 1 + 0.5, c[:, 0] + y0 - 1 + 0.5]
        if len(xy) > 1 and np.allclose(xy[0], xy[-1]):
            xy = xy[:-1]
        return xy

    def nucleus_contour(self, l, tolerance=0.5):
        if self.nuclei is None:
            return None
        m = (self.nuclei == l) & (self.labels == l)
        return self.contour(l, _largest(m), tolerance) if m.any() else None

    def centroid(self, l):
        ys, xs = np.nonzero(self.labels == l)
        return (float(xs.mean()), float(ys.mean())) if len(xs) else (0.0, 0.0)

    def measurements(self) -> list[dict]:
        px = self.px_um
        rows = []
        for l in self.ids():
            cell = self.labels == l
            nuc = (self.nuclei == l) & cell if self.nuclei is not None else np.zeros_like(cell)
            cx, cy = self.centroid(l)
            a, an = int(cell.sum()), int(nuc.sum())
            rows.append(dict(
                roi=f'cell{l:03d}', status=self.status.get(l, 'ok'),
                cell_area_px=a, nucleus_area_px=an, cytosol_area_px=a - an,
                cell_area_um2=round(a * px ** 2, 2) if px else None,
                cytosol_area_um2=round((a - an) * px ** 2, 2) if px else None,
                centroid_x=round(cx, 1), centroid_y=round(cy, 1),
            ))
        return rows

    # ---- ImageJ ROI I/O -------------------------------------------------

    def to_imagej(self, cells=True, nuclei=True, cytosol=True) -> list:
        """roifile.ImagejRoi list: cellNNN (polygon), nucNNN (polygon),
        cytoNNN (cell minus nucleus, composite shape ROI)."""
        import roifile

        out = []
        for l in self.ids():
            c = self.contour(l)
            if c is None or len(c) < 3:
                continue
            n = self.nucleus_contour(l)
            if cells:
                out.append(_polygon_roi(c, f'cell{l:03d}'))
            if nuclei and n is not None and len(n) >= 3:
                out.append(_polygon_roi(n, f'nuc{l:03d}'))
            if cytosol:
                if n is not None and len(n) >= 3:
                    out.append(_composite_roi([c, n[::-1]], f'cyto{l:03d}'))
                elif not cells:
                    out.append(_polygon_roi(c, f'cyto{l:03d}'))
        return out

    def save(self, path, cells=True, nuclei=True, cytosol=True, properties=None) -> list[str]:
        """Write ROIs. ``*.zip``: one ImageJ RoiSet (ROI Manager > Open);
        ``*.roi``: one .roi file per ROI, named ``<stem>_<roi>.roi`` in that folder.
        properties: key/value pairs stored in every ROI (the image ID)."""
        import roifile

        path = Path(path)
        rois = self.to_imagej(cells, nuclei, cytosol)
        if not rois:
            raise ValueError('저장할 ROI가 없습니다.')
        for r in rois:
            r.properties = dict(properties or {})
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() == '.zip':
            if path.exists():
                path.unlink()
            roifile.roiwrite(path, rois)
            return [str(path)]
        written = []
        for r in rois:
            f = path.with_name(f'{path.stem}_{r.name}.roi')
            r.tofile(f)
            written.append(str(f))
        return written

    @classmethod
    def load(cls, paths, shape, px_um=None) -> 'CellRois':
        """Read ImageJ .roi / RoiSet .zip files back into a label image.

        cell*/other polygons become cells, nuc* become nuclei (matched by
        number, else by overlap); cyto* composites are used only when there is
        no cell ROI of the same number.
        """
        import roifile

        if isinstance(paths, (str, Path)):
            paths = [paths]
        rois = []
        for p in paths:
            p = Path(p)
            if p.suffix.lower() == '.zip' or zipfile.is_zipfile(p):
                r = roifile.roiread(p)
            else:
                r = roifile.ImagejRoi.fromfile(p)
            rois += r if isinstance(r, list) else [r]
        labels = np.zeros(shape, np.int32)
        nuclei = np.zeros(shape, np.int32)
        tmp = cls(labels, nuclei, px_um)
        cells, nucs, cytos = [], [], []
        for r in rois:
            name = (r.name or '').lower()
            if name.startswith(('part', 'rgn', 'crop')):  # particle / logic-region ROIs, crop boxes
                continue
            if name.startswith('nuc'):
                nucs.append(r)
            elif name.startswith('cyto'):
                cytos.append(r)
            else:
                cells.append(r)

        def num(r):
            d = ''.join(ch for ch in (r.name or '') if ch.isdigit())
            return int(d) if d else None

        cell_nums = set()
        nxt = 1
        for r in cells + [c for c in cytos if num(c) not in {num(x) for x in cells}]:
            parts = _roi_polygons(r)
            if not parts:
                continue
            m = tmp.polygon_mask(parts[0])  # outer boundary
            l = num(r) if num(r) and num(r) not in cell_nums else None
            if l is None:
                l = max(cell_nums | {nxt - 1}) + 1
            cell_nums.add(l)
            nxt = max(nxt, l + 1)
            labels[m & (labels == 0)] = l
            if r in cytos and len(parts) > 1:  # holes of the cytosol ROI = nucleus
                for hole in parts[1:]:
                    nuclei[tmp.polygon_mask(hole) & (labels == l)] = l
        for r in nucs:
            parts = _roi_polygons(r)
            if not parts:
                continue
            m = tmp.polygon_mask(parts[0])
            l = num(r)
            if l not in cell_nums:
                ov = labels[m]
                ov = ov[ov > 0]
                l = int(np.bincount(ov).argmax()) if len(ov) else None
            if l:
                nuclei[m] = l
        out = cls(labels, nuclei if nuclei.any() else None, px_um)
        out.status = {l: ('edge' if out.touches_frame(l) else 'ok') for l in out.ids()}
        return out


def _polygon_roi(xy, name):
    import roifile

    roi = roifile.ImagejRoi.frompoints(np.asarray(xy, np.float32), name=name)
    roi.roitype = roifile.ROI_TYPE.POLYGON
    return roi


def _composite_roi(polys, name):
    """ImageJ ShapeRoi (cell with nucleus hole). Path ops: 0 MOVETO, 1 LINETO, 4 CLOSE."""
    import roifile

    path = []
    for xy in polys:
        xy = np.asarray(xy, np.float32)
        path += [0, float(xy[0, 0]), float(xy[0, 1])]
        for x, y in xy[1:]:
            path += [1, float(x), float(y)]
        path.append(4)
    allxy = np.concatenate([np.asarray(p) for p in polys])
    roi = roifile.ImagejRoi()
    roi.roitype = roifile.ROI_TYPE.RECT
    roi.version = 228
    roi.name = name
    roi.left, roi.top = int(np.floor(allxy[:, 0].min())), int(np.floor(allxy[:, 1].min()))
    roi.right, roi.bottom = int(np.ceil(allxy[:, 0].max())), int(np.ceil(allxy[:, 1].max()))
    roi.multi_coordinates = np.asarray(path, np.float32)
    roi.shape_roi_size = len(path)
    return roi


def _roi_polygons(r) -> list[np.ndarray]:
    """Polygons of an ImageJ ROI in image coordinates (outer first)."""
    import roifile

    if r.roitype == roifile.ROI_TYPE.RECT and not r.composite:
        x0, y0, x1, y1 = r.left, r.top, r.right, r.bottom
        return [np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], float)]
    if r.roitype == roifile.ROI_TYPE.OVAL and not r.composite:
        cx, cy = (r.left + r.right) / 2, (r.top + r.bottom) / 2
        rx, ry = (r.right - r.left) / 2, (r.bottom - r.top) / 2
        t = np.linspace(0, 2 * np.pi, 64, endpoint=False)
        return [np.c_[cx + rx * np.cos(t), cy + ry * np.sin(t)]]
    c = r.coordinates(multi=True) if r.composite else [r.coordinates()]
    polys = [np.asarray(p, float) for p in c if p is not None and len(p) >= 3]
    polys.sort(key=lambda p: -_area(p))
    return polys


def _area(xy):
    x, y = xy[:, 0], xy[:, 1]
    return abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1))) / 2


# ---------------------------------------------------------------------------
# preview image of the merged input
# ---------------------------------------------------------------------------


def merged_preview(bg, nuc, saturation, nuc_color=(0.2, 0.5, 1.0), bg_color=(1.0, 1.0, 1.0)):
    """RGB (Y, X, 3) float: bright-LUT background + nucleus, as the detector sees it."""
    b = brighten(filters.gaussian(bg.astype(np.float32), 1.0, preserve_range=True), saturation)
    rgb = b[..., None] * np.asarray(bg_color, np.float32) * 0.8
    if nuc is not None:
        n = _norm(nuc.astype(np.float32))
        rgb = np.maximum(rgb, n[..., None] * np.asarray(nuc_color, np.float32))
    return np.clip(rgb, 0, 1)
