"""FRAP (fluorescence recovery after photobleaching) measurement.

Three ROIs per image, measured on every timepoint of one channel:

- ``bleach``: the bleached area (taken from the file's bleach regions when it
  records them, else found as the strongest local drop between two frames);
- ``control``: a part of the same condensate that was not bleached (any size);
- ``background``: the bleach ROI's shape moved to the nearest place without
  condensate signal.

The recovery value of each frame is (bleach - background) / (control -
background), optionally divided by its value before bleaching (first frame,
or the mean of the frames before bleaching): the double normalization of
Phair et al. (2004), as in the ImageJ FRAP Profiler / easyFRAP. ROI means are
ImageJ Measure means (oval masks as ImageJ's OvalRoi, polygons by pixel
centre). The frames from the bleach on are fitted with ImageJ's "Exponential
recovery" y = a * (1 - exp(-b * x)) + c (x: s since the first post-bleach
frame), which gives the plateau, mobile / immobile fraction, k and t½.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

ROI_NAMES = ('bleach', 'control', 'background')
ROI_TITLES = {'bleach': 'Bleach', 'control': 'Control', 'background': 'Background'}
ROI_COLORS = {'bleach': (255, 60, 60), 'control': (60, 220, 90), 'background': (80, 170, 255)}
ROI_PREFIX = 'frap_'


# ---------------------------------------------------------------------------
# ROIs
# ---------------------------------------------------------------------------


@dataclass
class FrapRoi:
    """An oval or rectangle (integer bounds, as ImageJ) or a polygon (image px)."""

    kind: str  # 'oval', 'rect', 'polygon'
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0
    xy: np.ndarray | None = None

    @classmethod
    def oval(cls, cx, cy, d) -> 'FrapRoi':
        d = max(1, int(round(d)))
        return cls('oval', int(round(cx - d / 2)), int(round(cy - d / 2)), d, d)

    def bounds(self):
        """(x0, y0, x1, y1) in image pixels (float for polygons)."""
        if self.kind == 'polygon':
            return (float(self.xy[:, 0].min()), float(self.xy[:, 1].min()),
                    float(self.xy[:, 0].max()), float(self.xy[:, 1].max()))
        return self.x, self.y, self.x + self.w, self.y + self.h

    def center(self):
        x0, y0, x1, y1 = self.bounds()
        return (x0 + x1) / 2, (y0 + y1) / 2

    def size(self):
        x0, y0, x1, y1 = self.bounds()
        return x1 - x0, y1 - y0

    def moved(self, dx, dy) -> 'FrapRoi':
        dx, dy = int(round(dx)), int(round(dy))
        if self.kind == 'polygon':
            return FrapRoi('polygon', xy=self.xy + (dx, dy))
        return FrapRoi(self.kind, self.x + dx, self.y + dy, self.w, self.h)

    def at(self, cx, cy) -> 'FrapRoi':
        """The same shape centred on (cx, cy)."""
        ox, oy = self.center()
        return self.moved(round(cx - ox), round(cy - oy))

    def outline(self) -> np.ndarray:
        """(N, 2) outline for drawing."""
        if self.kind == 'polygon':
            return np.asarray(self.xy, float)
        x0, y0, x1, y1 = self.bounds()
        if self.kind == 'rect':
            return np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], float)
        a = np.linspace(0, 2 * np.pi, 72, endpoint=False)
        return np.c_[(x0 + x1) / 2 + self.w / 2 * np.cos(a), (y0 + y1) / 2 + self.h / 2 * np.sin(a)]

    def local_mask(self):
        """(x0, y0, mask) with mask covering the integer bounds, as ImageJ's getMask."""
        if self.kind == 'rect':
            return self.x, self.y, np.ones((self.h, self.w), bool)
        if self.kind == 'oval':
            # ij.gui.OvalRoi.getMask: pixel centres inside the ellipse
            a, b = self.w / 2, self.h / 2
            yy, xx = np.mgrid[0:self.h, 0:self.w].astype(float)
            m = (xx - (a - 0.5)) ** 2 / (a * a) + (yy - (b - 0.5)) ** 2 / (b * b) <= 1.0
            return self.x, self.y, m
        x0 = int(np.floor(self.xy[:, 0].min())) - 1
        y0 = int(np.floor(self.xy[:, 1].min())) - 1
        w = int(np.ceil(self.xy[:, 0].max())) - x0 + 2
        h = int(np.ceil(self.xy[:, 1].max())) - y0 + 2
        # ImageJ keeps sub-pixel polygon coordinates as float32
        xy = np.asarray(self.xy, np.float32).astype(float) - (x0, y0)
        return x0, y0, polygon_fill(xy, w, h)

    def mask(self, shape) -> np.ndarray:
        """Boolean mask of the whole image (pixels outside the image dropped)."""
        out = np.zeros(shape, bool)
        x0, y0, m = self.local_mask()
        H, W = shape
        ys, xs = slice(max(y0, 0), min(y0 + m.shape[0], H)), slice(max(x0, 0), min(x0 + m.shape[1], W))
        if ys.start < ys.stop and xs.start < xs.stop:
            out[ys, xs] = m[ys.start - y0:ys.stop - y0, xs.start - x0:xs.stop - x0]
        return out

    def area(self) -> int:
        return int(self.local_mask()[2].sum())

    def inside(self, shape) -> bool:
        x0, y0, x1, y1 = self.bounds()
        return x0 >= 0 and y0 >= 0 and x1 <= shape[1] and y1 <= shape[0]

    def contains(self, px, py) -> bool:
        x0, y0, m = self.local_mask()
        j, i = int(np.floor(px)) - x0, int(np.floor(py)) - y0
        return 0 <= i < m.shape[0] and 0 <= j < m.shape[1] and bool(m[i, j])

    def to_dict(self) -> dict:
        if self.kind == 'polygon':
            return {'kind': 'polygon', 'xy': np.round(self.xy, 3).tolist()}
        return {'kind': self.kind, 'x': self.x, 'y': self.y, 'w': self.w, 'h': self.h}

    @classmethod
    def from_dict(cls, d) -> 'FrapRoi':
        if d.get('kind') == 'polygon':
            return cls('polygon', xy=np.asarray(d['xy'], float))
        return cls(d.get('kind', 'oval'), int(d['x']), int(d['y']), int(d['w']), int(d['h']))

    def describe(self, px_um=None) -> str:
        w, h = self.size()
        cx, cy = self.center()
        size = f'{w:.0f}×{h:.0f} px'
        if px_um:
            size += f' ({w * px_um:.2f}×{h * px_um:.2f} µm)'
        kind = {'oval': '원', 'rect': '사각형', 'polygon': '다각형'}[self.kind]
        return f'{kind} {size}, 중심 ({cx:.0f}, {cy:.0f})'


def polygon_fill(xy: np.ndarray, w: int, h: int) -> np.ndarray:
    """Mask of a sub-pixel polygon as ImageJ's PolygonFiller makes it
    (ij.process.PolygonFiller, float coordinates; xy inside [0, w) x [0, h))."""
    def jround(v):
        return int(math.floor(v + 0.5))

    edges = []
    n = len(xy)
    for i in range(n):
        x1f, y1f = xy[i]
        x2f, y2f = xy[(i + 1) % n]
        y1, y2 = jround(y1f), jround(y2f)
        if y1 == y2 or (y1 <= 0 and y2 <= 0):
            continue
        if y1 > y2:
            y1, y2, y1f, y2f, x1f, x2f = y2, y1, y2f, y1f, x2f, x1f
        slope = (x2f - x1f) / (y2f - y1f)
        edges.append((y1, y2, x1f + (y1 - y1f + 0.5) * slope + 1e-8, slope))
    m = np.zeros((h, w), bool)
    for y in range(max(0, min((e[0] for e in edges), default=0)), h):
        xs = sorted(ex + (y - y1) * sl for y1, y2, ex, sl in edges if y1 <= y < y2)
        for a, b in zip(xs[0::2], xs[1::2]):
            a, b = min(max(int(a + 0.5), 0), w), min(max(int(b + 0.5), 0), w)
            m[y, a:b] = True
    return m


def roi_from_bleach(b) -> FrapRoi:
    """FrapRoi of a cytosol.imageinfo.BleachRoi (bounds rounded as in its ImageJ export)."""
    x0, y0, x1, y1 = b.bounds()
    if b.shape in ('circle', 'ellipse', 'rectangle'):
        l, t, r, btm = (int(round(v)) for v in (x0, y0, x1, y1))
        return FrapRoi('oval' if b.shape != 'rectangle' else 'rect', l, t, max(1, r - l), max(1, btm - t))
    return FrapRoi('polygon', xy=np.asarray(b.xy, float))


# ---------------------------------------------------------------------------
# per-image state
# ---------------------------------------------------------------------------


@dataclass
class FrapState:
    """FRAP settings of one image: ROIs and which of them are placed automatically."""

    rois: dict = field(default_factory=dict)  # name -> FrapRoi
    auto: dict = field(default_factory=lambda: {n: True for n in ROI_NAMES})
    bleach_frame: int | None = None  # first frame after bleaching (0-based)
    bleach_frame_auto: bool = True
    threshold: float | None = None  # condensate threshold (pre-bleach image)
    threshold_auto: bool = True
    control_d: int | None = None  # control circle diameter (px)
    control_d_auto: bool = True
    bleach_d: int | None = None  # diameter of a detected / hand-placed bleach circle
    bleach_d_auto: bool = True
    file_roi: int = 0  # which bleach region of the file
    source: str = ''  # where the bleach ROI came from ('file', 'detected', 'manual')
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {'rois': {k: r.to_dict() for k, r in self.rois.items()},
                'auto': dict(self.auto), 'bleach_frame': self.bleach_frame,
                'bleach_frame_auto': self.bleach_frame_auto, 'threshold': self.threshold,
                'threshold_auto': self.threshold_auto, 'control_d': self.control_d,
                'control_d_auto': self.control_d_auto, 'bleach_d': self.bleach_d,
                'bleach_d_auto': self.bleach_d_auto, 'file_roi': self.file_roi,
                'source': self.source}

    @classmethod
    def from_dict(cls, d) -> 'FrapState':
        s = cls()
        for k, v in (d or {}).items():
            if k == 'rois':
                s.rois = {n: FrapRoi.from_dict(r) for n, r in v.items()}
            elif k == 'auto':
                s.auto.update({n: bool(x) for n, x in v.items()})
            elif hasattr(s, k):
                setattr(s, k, v)
        return s


# ---------------------------------------------------------------------------
# image analysis
# ---------------------------------------------------------------------------


def roi_means(stack: np.ndarray, roi: FrapRoi) -> np.ndarray:
    """Mean of the ROI on every frame of a (T, Y, X) stack (ImageJ Measure mean)."""
    x0, y0, m = roi.local_mask()
    T, H, W = stack.shape
    ys, xs = slice(max(y0, 0), min(y0 + m.shape[0], H)), slice(max(x0, 0), min(x0 + m.shape[1], W))
    if ys.start >= ys.stop or xs.start >= xs.stop:
        return np.full(T, np.nan)
    sub = m[ys.start - y0:ys.stop - y0, xs.start - x0:xs.stop - x0]
    if not sub.any():
        return np.full(T, np.nan)
    return stack[:, ys, xs][:, sub].astype(np.float64).mean(axis=1)


def detect_bleach_frame(curve) -> int | None:
    """First frame after bleaching: the largest drop of the bleach ROI mean."""
    c = np.asarray(curve, float)
    if len(c) < 2 or not np.isfinite(c).all():
        return None
    drop = c[:-1] - c[1:]
    k = int(np.argmax(drop))
    return k + 1 if drop[k] > 0 else None


def detect_bleach(stack: np.ndarray, frame: int | None = None, sigma=1.0, after=4):
    """(first post-bleach frame, (cx, cy), diameter px) of the strongest
    lasting local drop, for files that do not record the bleach region.

    A pixel's drop at frame k is its lowest value over the (up to 3) frames
    before minus its highest value over the next `after` frames, so a
    condensate that only moves in or out does not count, weighted by the
    relative drop; the outer 4 % of the image is left out."""
    from scipy import ndimage as ndi

    T = stack.shape[0]
    if T < 2:
        return None
    sm = np.stack([ndi.gaussian_filter(f.astype(np.float32), sigma) for f in stack])
    best = None
    for k in ([frame] if frame else range(1, T)):
        pre = sm[max(0, k - 3):k].min(axis=0)
        post = sm[k:min(T, k + after)].max(axis=0)
        drop = pre - post
        with np.errstate(divide='ignore', invalid='ignore'):
            score = drop * np.clip(np.nan_to_num(drop / np.maximum(pre, 1e-6)), 0, 1)
        # condensates drift out of the field at its edges; bleach regions sit inside
        m = max(2, int(0.04 * min(score.shape)))
        score[:m], score[-m:], score[:, :m], score[:, -m:] = 0, 0, 0, 0
        v = float(score.max())
        if best is None or v > best[0]:
            best = (v, k, score)
    v, k, score = best
    if v <= 0:
        return None
    cy, cx = np.unravel_index(int(np.argmax(score)), score.shape)
    lab, _ = ndi.label(score >= v / 2)
    area = float((lab == lab[cy, cx]).sum())
    diam = max(3.0, 2 * math.sqrt(area / math.pi))
    return k, (float(cx), float(cy)), diam


def otsu(values) -> float:
    from skimage.filters import threshold_otsu

    v = np.asarray(values, float)
    v = v[np.isfinite(v)]
    if v.size == 0 or v.min() == v.max():
        return float(v.max()) if v.size else 0.0
    return float(threshold_otsu(v))


def _window(roi: FrapRoi, shape, scale=8, minimum=64):
    """Square around the ROI where the condensate threshold is set."""
    w, h = roi.size()
    half = max(minimum, scale * max(w, h)) / 2
    cx, cy = roi.center()
    H, W = shape
    return (int(max(0, cx - half)), int(max(0, cy - half)),
            int(min(W, cx + half)), int(min(H, cy + half)))


def condensate_mask(pre: np.ndarray, bleach: FrapRoi, threshold=None, sigma=1.0):
    """(mask, threshold): condensate signal in the pre-bleach image (smoothed,
    at or above the threshold; automatic: Otsu in a window around the bleach ROI)."""
    from scipy import ndimage as ndi

    sm = ndi.gaussian_filter(pre.astype(np.float32), sigma)
    if threshold is None:
        x0, y0, x1, y1 = _window(bleach, pre.shape)
        threshold = otsu(sm[y0:y1, x0:x1])
    return sm >= threshold, float(threshold)


def place_control(mask: np.ndarray, bleach: FrapRoi, diameter=None, stack=None, frame=None,
                  keep=0.7):
    """(control ROI, note): a circle in the unbleached part of the condensate
    under the bleach ROI (its deepest point), else in the nearest other one.
    With the stack and the first post-bleach frame, a place that lost more
    than 1 - keep of its signal at the bleach is skipped (a condensate that
    was bleached as a whole has no unbleached part)."""
    from scipy import ndimage as ndi

    bm = bleach.mask(mask.shape)
    away = ndi.binary_dilation(bm, iterations=2)
    lab, n = ndi.label(mask)
    if n == 0:
        return None, '응집체 신호가 없습니다 (threshold를 낮추세요).'
    hit = np.unique(lab[bm & mask])
    hit = hit[hit > 0]
    bw, bh = bleach.size()
    want = diameter or max(3, int(round(min(bw, bh))))
    cands = []
    if hit.size:
        cands.append((np.isin(lab, hit) & ~away, 'same'))
    # other condensates, nearest first
    cx, cy = bleach.center()
    others = [l for l in range(1, n + 1) if l not in set(hit.tolist())]
    if others:
        com = ndi.center_of_mass(mask, lab, others)
        order = np.argsort([math.hypot(x - cx, y - cy) for y, x in com])
        cands += [(lab == others[i], 'other') for i in order[:25]]
    first = None
    same_bleached = False
    for region, kind in cands:
        if region.sum() < 5:
            continue
        dist = ndi.distance_transform_edt(region)
        r = float(dist.max())
        if 2 * r < 3 and kind == 'same':
            continue
        yy, xx = np.nonzero(dist >= min(r, want / 2) - 1e-9)
        # deepest enough points; nearest to the bleach ROI
        k = int(np.argmin((xx - cx) ** 2 + (yy - cy) ** 2))
        d = diameter or max(3, min(want, int(math.floor(2 * r))))
        roi = FrapRoi.oval(xx[k] + 0.5, yy[k] + 0.5, d)
        first = first or roi
        if stack is not None and frame:
            m = roi_means(stack[max(0, frame - 3):frame + 1], roi)
            if not (np.isfinite(m).all() and m[-1] >= keep * m[:-1].mean()):
                same_bleached |= kind == 'same'
                continue  # bleached too
        if kind == 'same':
            return roi, ''
        if same_bleached:
            return roi, ('응집체 전체가 bleach되어 bleach되지 않은 가장 가까운 다른 응집체에 두었습니다 '
                         '(촬영 중 bleaching 보정용).')
        return roi, '가장 가까운 다른 응집체에 두었습니다 (같은 응집체에 bleach되지 않은 부분이 부족함).'
    if first is not None:
        return first, 'bleach되지 않은 응집체를 찾지 못했습니다. Control ROI를 직접 옮기세요.'
    return None, '대조 위치를 찾지 못했습니다. Control ROI를 직접 옮기세요.'


def place_background(mask: np.ndarray, bleach: FrapRoi, pre: np.ndarray):
    """(background ROI, note): the bleach ROI's shape at the nearest place
    without condensate signal (lowest mean of the closest free ring)."""
    from scipy import ndimage as ndi

    H, W = mask.shape
    bw, bh = bleach.size()
    grow = max(2, int(round(max(bw, bh) / 4)))
    busy = ndi.binary_dilation(mask, iterations=grow)
    cx, cy = bleach.center()
    r0 = max(bw, bh)
    step = max(2.0, r0 / 2)
    for ring in range(1, 60):
        r = r0 * 0.75 + ring * step
        found = []
        for a in np.linspace(0, 2 * np.pi, 24, endpoint=False):
            cand = bleach.at(cx + r * math.cos(a), cy + r * math.sin(a))
            if not cand.inside((H, W)):
                continue
            x0, y0, m = cand.local_mask()
            if busy[y0:y0 + m.shape[0], x0:x0 + m.shape[1]][m].any():
                continue
            found.append((float(pre[y0:y0 + m.shape[0], x0:x0 + m.shape[1]][m].mean()), cand))
        if found:
            return min(found, key=lambda f: f[0])[1], ''
        if r > max(H, W):
            break
    # nowhere free: the darkest place of the same size
    sm = ndi.uniform_filter(pre.astype(np.float32), max(3, int(r0)))
    y, x = np.unravel_index(int(np.argmin(sm)), sm.shape)
    return bleach.at(x, y), '신호 없는 빈 곳이 없어 가장 어두운 곳에 두었습니다.'


def file_bleach_frame(info, nt) -> int | None:
    """First frame after the first bleach recorded in the file (cytosol.imageinfo.czi_bleach_info)."""
    for f in (info or {}).get('frames_after') or []:
        if 0 < int(f) < nt:
            return int(f)
    return None


def auto_place(st: FrapState, stack: np.ndarray, file_rois=(), file_frame=None) -> FrapState:
    """Fill in every ROI and value of st that is set to automatic."""
    T, H, W = stack.shape
    st.notes = []
    if st.auto.get('bleach', True) or 'bleach' not in st.rois:
        if file_rois:
            st.file_roi = int(np.clip(st.file_roi, 0, len(file_rois) - 1))
            st.rois['bleach'] = roi_from_bleach(file_rois[st.file_roi])
            st.source = 'file'
        else:
            want = None if st.bleach_frame_auto else st.bleach_frame
            det = detect_bleach(stack, want) if T > 1 else None
            if det is not None:
                _, (cx, cy), d = det
                if st.bleach_d_auto or not st.bleach_d:
                    st.bleach_d = int(round(d))
                st.rois['bleach'] = FrapRoi.oval(cx + 0.5, cy + 0.5, st.bleach_d)
                st.source = 'detected'
            else:
                st.bleach_d = st.bleach_d or 10
                st.rois['bleach'] = FrapRoi.oval(W / 2, H / 2, st.bleach_d)
                st.source = 'manual'
                st.notes.append('bleach 영역을 찾지 못해 가운데에 두었습니다. 직접 옮기세요.')
    bleach = st.rois['bleach']
    if st.bleach_frame_auto or st.bleach_frame is None:
        bf = file_frame if file_frame is not None else None
        if bf is None:
            bf = detect_bleach_frame(roi_means(stack, bleach))
        st.bleach_frame = int(bf) if bf is not None else min(1, T - 1)
    st.bleach_frame = int(np.clip(st.bleach_frame, 0, max(T - 1, 0)))
    pre = stack[:max(st.bleach_frame, 1)].mean(axis=0)
    mask, thr = condensate_mask(pre, bleach, None if st.threshold_auto else st.threshold)
    st.threshold = thr
    if st.auto.get('control', True) or 'control' not in st.rois:
        roi, note = place_control(mask, bleach, None if st.control_d_auto else st.control_d,
                                  stack, st.bleach_frame)
        if roi is not None:
            st.rois['control'] = roi
            if st.control_d_auto:
                st.control_d = roi.w
        elif 'control' not in st.rois:
            st.rois['control'] = FrapRoi.oval(min(W - 6, bleach.center()[0] + 2 * bleach.size()[0]),
                                              bleach.center()[1], st.control_d or 6)
        if note:
            st.notes.append('Control: ' + note)
    elif not st.control_d_auto and st.control_d:
        c = st.rois['control']
        if c.kind != 'polygon' and (c.w, c.h) != (st.control_d, st.control_d):
            st.rois['control'] = FrapRoi.oval(*c.center(), st.control_d)
    if st.auto.get('background', True) or 'background' not in st.rois:
        roi, note = place_background(mask, bleach, pre)
        st.rois['background'] = roi
        if note:
            st.notes.append('Background: ' + note)
    else:  # moved by hand: keeps the bleach ROI's shape and size
        st.rois['background'] = bleach.at(*st.rois['background'].center())
    return st


# ---------------------------------------------------------------------------
# curve and fit
# ---------------------------------------------------------------------------


@dataclass
class FrapFit:
    """y = a * (1 - exp(-b * x)) + c over the frames from the bleach on."""

    a: float
    b: float
    c: float
    r2: float
    pre: float  # value before bleaching (1 when normalized)
    span: float = float('inf')  # s observed after the bleach

    @property
    def problem(self) -> str:
        """Why the fit says nothing about recovery ('' when it does)."""
        if not (self.a > 0 and self.b > 0) or self.pre - self.c <= 0:
            return 'no recovery'
        if self.half_time > self.span:
            return 't½ longer than the observation'
        return ''

    @property
    def ok(self) -> bool:
        return not self.problem

    @property
    def plateau(self) -> float:
        return self.a + self.c

    @property
    def half_time(self) -> float:
        return math.log(2) / self.b if self.b > 0 else float('nan')

    @property
    def tau(self) -> float:
        return 1 / self.b if self.b > 0 else float('nan')

    @property
    def mobile(self) -> float:
        """(plateau - post-bleach) / (pre-bleach - post-bleach)."""
        span = self.pre - self.c
        return self.a / span if span != 0 else float('nan')

    def value(self, x):
        x = np.asarray(x, float)
        return self.a * (1 - np.exp(-self.b * x)) + self.c


def fit_recovery(x, y, pre=1.0) -> FrapFit | None:
    """Least-squares fit of ImageJ's "Exponential recovery" (CurveFitter EXP_RECOVERY)."""
    from scipy.optimize import curve_fit

    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    if len(x) < 4 or np.ptp(x) <= 0:
        return None
    f = lambda t, a, b, c: a * (1 - np.exp(-b * t)) + c  # noqa: E731
    c0 = y[0]
    a0 = y[-max(1, len(y) // 5):].mean() - c0
    # starting rate: where half the recovery is reached
    half = c0 + a0 / 2
    idx = np.nonzero((y - half) * np.sign(a0 or 1) >= 0)[0]
    th = x[idx[0]] - x[0] if idx.size and x[idx[0]] > x[0] else np.ptp(x) / 3
    best = None
    for b0 in (math.log(2) / max(th, 1e-9), 1 / np.ptp(x), 10 / np.ptp(x)):
        try:
            p, _ = curve_fit(f, x, y, p0=(a0, b0, c0), maxfev=20000)
        except (RuntimeError, ValueError):
            continue
        ss = float(((y - f(x, *p)) ** 2).sum())
        if best is None or ss < best[1]:
            best = (p, ss)
    if best is None:
        return None
    p, ss = best
    tot = float(((y - y.mean()) ** 2).sum())
    return FrapFit(float(p[0]), float(p[1]), float(p[2]), 1 - ss / tot if tot > 0 else float('nan'),
                   float(pre), float(np.ptp(x)))


@dataclass
class FrapCurve:
    """Measured curve of one image."""

    label: str
    group: str
    times: np.ndarray  # s from the first frame
    bleach_frame: int
    means: dict  # roi name -> (T,) means
    normalize: str = 'first'  # 'first', 'pre' or '' (none)
    channel: str = ''
    roi_text: dict = field(default_factory=dict)
    bleach_radius_um: float | None = None  # circular bleach ROI: for the D estimate
    properties: dict = field(default_factory=dict)
    fit: FrapFit | None = None

    @property
    def ratio(self) -> np.ndarray:
        b, c, g = (self.means[n] for n in ROI_NAMES)
        with np.errstate(divide='ignore', invalid='ignore'):
            return (b - g) / (c - g)

    @property
    def pre_value(self) -> float:
        r = self.ratio
        if self.normalize == 'pre' and self.bleach_frame > 0:
            return float(np.nanmean(r[:self.bleach_frame]))
        return float(r[0])

    @property
    def values(self) -> np.ndarray:
        """The plotted recovery value: ratio, divided by the pre-bleach value when normalized."""
        r = self.ratio
        if not self.normalize:
            return r
        pre = self.pre_value
        return r / pre if pre else r * np.nan

    @property
    def t_rel(self) -> np.ndarray:
        """s since the first post-bleach frame."""
        return self.times - self.times[self.bleach_frame]

    def do_fit(self):
        bf = self.bleach_frame
        pre = 1.0 if self.normalize else self.pre_value
        self.fit = fit_recovery(self.t_rel[bf:], self.values[bf:], pre)
        return self.fit

    def summary(self) -> dict:
        """The usual FRAP numbers (NaN where the fit failed)."""
        return summary_values(self.values, self.bleach_frame, self.fit, self.t_rel,
                              1.0 if self.normalize else self.pre_value, self.bleach_radius_um)


SUMMARY_KEYS = [
    ('pre_bleach', 'bleach 전 값'),
    ('post_bleach', 'bleach 직후 값 (첫 프레임)'),
    ('bleach_depth', 'bleach 깊이 (1 - 직후/전)'),
    ('final', '마지막 프레임 값'),
    ('final_recovery', '최종 회복률 (마지막, (값-직후)/(전-직후))'),
    ('plateau', '피팅 plateau (a + c)'),
    ('mobile_fraction', 'Mobile fraction (a / (전 - c))'),
    ('immobile_fraction', 'Immobile fraction (1 - mobile)'),
    ('k_per_s', '회복 속도 상수 k (1/s)'),
    ('tau_s', '시간 상수 τ = 1/k (s)'),
    ('half_time_s', '반감기 t½ = ln2/k (s)'),
    ('initial_rate_per_s', '초기 회복 속도 a·k (1/s)'),
    ('fit_r2', '피팅 R²'),
    ('fit_ok', '피팅 사용 가능 (1) / 회복 없음·t½가 관찰 시간보다 김 (0: 피팅값 비움)'),
    ('D_um2_per_s', '확산계수 D ≈ 0.224·r²/t½ (µm²/s, 원형 bleach, Soumpasis)'),
]


def summary_values(values, bf, fit, t_rel, pre, radius_um=None) -> dict:
    v = np.asarray(values, float)
    nan = float('nan')
    post = float(v[bf]) if bf < len(v) else nan
    final = float(v[-1])
    span = pre - post
    out = {'pre_bleach': pre, 'post_bleach': post,
           'bleach_depth': 1 - post / pre if pre else nan,
           'final': final, 'final_recovery': (final - post) / span if span else nan}
    if fit is not None:
        out['fit_ok'] = 1.0 if fit.ok else 0.0
        out['fit_r2'] = fit.r2
    if fit is not None and fit.ok:
        out.update(plateau=fit.plateau, mobile_fraction=fit.mobile,
                   immobile_fraction=1 - fit.mobile, k_per_s=fit.b, tau_s=fit.tau,
                   half_time_s=fit.half_time, initial_rate_per_s=fit.a * fit.b, fit_r2=fit.r2)
        out['D_um2_per_s'] = (0.224 * radius_um ** 2 / fit.half_time
                              if radius_um and fit.half_time > 0 else nan)
    for k, _ in SUMMARY_KEYS:
        out.setdefault(k, nan)
    return out


# ---------------------------------------------------------------------------
# groups
# ---------------------------------------------------------------------------


@dataclass
class GroupCurve:
    name: str
    offset: np.ndarray  # frames from the bleach frame
    t: np.ndarray  # mean s since the first post-bleach frame
    mean: np.ndarray
    sd: np.ndarray
    sem: np.ndarray
    n: np.ndarray
    members: list  # FrapCurve
    fit: FrapFit | None = None


def group_curve(name, curves: list[FrapCurve]) -> GroupCurve | None:
    """Mean ± SD / SEM of the curves, frames aligned on the bleach frame."""
    if not curves:
        return None
    lo = -min(c.bleach_frame for c in curves)
    hi = max(len(c.times) - c.bleach_frame for c in curves)
    off = np.arange(lo, hi)
    vals = np.full((len(curves), len(off)), np.nan)
    ts = np.full_like(vals, np.nan)
    for i, c in enumerate(curves):
        j = np.arange(len(c.times)) - c.bleach_frame - lo
        vals[i, j] = c.values
        ts[i, j] = c.t_rel
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        n = np.isfinite(vals).sum(0)
        mean = np.nanmean(vals, 0)
        sd = np.nanstd(vals, 0, ddof=1) if len(curves) > 1 else np.full(len(off), np.nan)
        sd = np.where(n > 1, sd, np.nan)
        sem = sd / np.sqrt(np.maximum(n, 1))
        t = np.nanmean(ts, 0)
    g = GroupCurve(name, off, t, mean, sd, sem, n, list(curves))
    post = off >= 0
    pre = 1.0 if curves[0].normalize else float(np.nanmean(mean[~post])) if (~post).any() else float(mean[0])
    g.fit = fit_recovery(t[post], mean[post], pre)
    return g


def group_summary(g: GroupCurve) -> dict:
    """Mean, SD, SEM over the images of each summary number, and the numbers
    of the fit to the mean curve."""
    per = [c.summary() for c in g.members]
    out = {}
    for k, _ in SUMMARY_KEYS:
        v = np.array([p[k] for p in per], float)
        v = v[np.isfinite(v)]
        out[k] = (float(v.mean()) if v.size else float('nan'),
                  float(v.std(ddof=1)) if v.size > 1 else float('nan'),
                  float(v.std(ddof=1) / math.sqrt(v.size)) if v.size > 1 else float('nan'),
                  int(v.size))
    return out


# ---------------------------------------------------------------------------
# plots
# ---------------------------------------------------------------------------

def _korean_fallback():
    """Let plot text fall back to a Korean font (group / image names)."""
    import matplotlib
    from matplotlib import font_manager

    have = {f.name for f in font_manager.fontManager.ttflist}
    extra = [f for f in ('Apple SD Gothic Neo', 'AppleGothic', 'Malgun Gothic', 'NanumGothic',
                         'Noto Sans CJK KR') if f in have]
    fams = list(matplotlib.rcParams['font.sans-serif'])
    matplotlib.rcParams['font.sans-serif'] = fams + [f for f in extra if f not in fams]
    if extra and matplotlib.rcParams['font.family'] == ['sans-serif']:
        matplotlib.rcParams['font.family'] = ['sans-serif'] + extra[:1]


_korean_fallback()

GROUP_COLORS = ['#d62728', '#1f77b4', '#2ca02c', '#9467bd', '#ff7f0e', '#8c564b', '#e377c2',
                '#17becf', '#7f7f7f', '#bcbd22']


def _ylabel(normalize):
    return ('Normalized recovery' if normalize else '(Bleach − Bg) / (Control − Bg)')


def draw_curve(ax, curve: FrapCurve, show_fit=True, raw=False):
    """One image: recovery (or the raw ROI means) against time."""
    ax.clear()
    t = curve.t_rel
    if raw:
        for n in ROI_NAMES:
            ax.plot(t, curve.means[n], '-o', ms=3, lw=1.2, color=np.array(ROI_COLORS[n]) / 255,
                    label=ROI_TITLES[n])
        ax.set_ylabel('Mean intensity')
    else:
        ax.plot(t, curve.values, 'o', ms=4, color='#d62728', label=curve.label)
        if show_fit and curve.fit is not None and not curve.fit.ok:
            ax.plot([], [], ' ', label=f'fit: {curve.fit.problem}')
        elif show_fit and curve.fit is not None:
            x = np.linspace(0, t[-1], 200)
            ax.plot(x, curve.fit.value(x), '-', lw=1.4, color='0.2',
                    label=f'fit: t½ {curve.fit.half_time:.3g} s, Mf {curve.fit.mobile:.2f}')
        ax.set_ylabel(_ylabel(curve.normalize))
    ax.axvline(0, color='0.6', lw=0.8, ls='--')
    ax.set_xlabel('Time after bleach (s)')
    ax.grid(True, color='0.88', lw=0.6)
    ax.legend(fontsize=7, frameon=False)


def draw_groups(ax, groups: list[GroupCurve], error='sem', show_fit=True, members=False):
    """Mean curve of each group with error bars (SD or SEM)."""
    ax.clear()
    for i, g in enumerate(groups):
        col = GROUP_COLORS[i % len(GROUP_COLORS)]
        if members:
            for c in g.members:
                ax.plot(c.t_rel, c.values, '-', lw=0.6, color=col, alpha=0.3)
        err = g.sem if error == 'sem' else g.sd
        ax.errorbar(g.t, g.mean, yerr=np.nan_to_num(err), fmt='o', ms=3.5, capsize=2, lw=1,
                    color=col, label=f'{g.name} (n={len(g.members)})')
        if show_fit and g.fit is not None and g.fit.ok:
            x = np.linspace(0, np.nanmax(g.t), 200)
            ax.plot(x, g.fit.value(x), '-', lw=1.3, color=col, alpha=0.8)
    ax.axvline(0, color='0.6', lw=0.8, ls='--')
    ax.set_xlabel('Time after bleach (s)')
    norm = groups[0].members[0].normalize if groups and groups[0].members else 'first'
    ax.set_ylabel(_ylabel(norm) + f' (mean ± {error.upper()})')
    ax.grid(True, color='0.88', lw=0.6)
    if groups:
        ax.legend(fontsize=7, frameon=False)


def save_figure(path, draw, size=(5, 3.5)) -> str:
    """draw(ax) on a new figure saved as PNG/TIFF (300 dpi), PDF or SVG."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    fig = Figure(figsize=size, dpi=300, layout='constrained')
    FigureCanvasAgg(fig)
    draw(fig.add_subplot(111))
    fig.savefig(path, dpi=300)
    return str(path)


def save_summary_figure(path, groups: list[GroupCurve], error='sem') -> str:
    """Mobile fraction, t½ and final recovery per group: bars (mean ± error)
    with one dot per image."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    panels = [('mobile_fraction', 'Mobile fraction', 1), ('half_time_s', 't½ (s)', 1),
              ('final_recovery', 'Final recovery (%)', 100)]
    fig = Figure(figsize=(2.2 * len(panels) + 0.6, 3.2), dpi=300, layout='constrained')
    FigureCanvasAgg(fig)
    rng = np.random.default_rng(0)
    for j, (key, title, scale) in enumerate(panels):
        ax = fig.add_subplot(1, len(panels), j + 1)
        for i, g in enumerate(groups):
            col = GROUP_COLORS[i % len(GROUP_COLORS)]
            v = np.array([c.summary()[key] for c in g.members], float) * scale
            v = v[np.isfinite(v)]
            if not v.size:
                continue
            e = (v.std(ddof=1) / (np.sqrt(v.size) if error == 'sem' else 1)) if v.size > 1 else 0
            ax.bar(i, v.mean(), 0.6, yerr=e, color=col, alpha=0.35, capsize=3, edgecolor=col)
            ax.plot(i + rng.uniform(-0.15, 0.15, v.size), v, 'o', ms=3, color=col)
        ax.set_xticks(range(len(groups)))
        ax.set_xticklabels([f'{g.name}\n(n={len(g.members)})' for g in groups], fontsize=7,
                           rotation=30 if len(groups) > 3 else 0)
        ax.set_title(title, fontsize=9)
        ax.tick_params(labelsize=7)
        ax.grid(True, axis='y', color='0.88', lw=0.6)
    fig.suptitle(f'FRAP summary (mean ± {error.upper()})', fontsize=9)
    fig.savefig(path, dpi=300)
    return str(path)


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


def _f(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    return '' if not np.isfinite(v) else f'{v:.6g}'


def write_curve_csv(path, curve: FrapCurve) -> str:
    """Per frame: time, ROI means, ratio, recovery value and fit; '#' header lines."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as f:
        for k, v in curve.properties.items():
            f.write(f'# {k} = {v}\n')
        f.write(f'# channel = {curve.channel}\n# bleach_frame = {curve.bleach_frame + 1}\n')
        f.write(f'# value = (bleach - background) / (control - background)'
                + {'first': ', / first frame', 'pre': ', / mean of pre-bleach frames'}.get(curve.normalize, '')
                + '\n')
        for n in ROI_NAMES:
            f.write(f'# {n}_roi = {curve.roi_text.get(n, "")}\n')
        w = csv.writer(f)
        w.writerow(['frame', 'time_s', 'time_after_bleach_s', 'bleach_mean', 'control_mean',
                    'background_mean', 'ratio', 'recovery', 'fit'])
        fit = curve.fit
        for i, t in enumerate(curve.times):
            tr = curve.t_rel[i]
            w.writerow([i + 1, _f(t), _f(tr)] + [_f(curve.means[n][i]) for n in ROI_NAMES]
                       + [_f(curve.ratio[i]), _f(curve.values[i]),
                          _f(fit.value(tr)) if fit is not None and i >= curve.bleach_frame else ''])
    return str(path)


def write_summary_csv(path, curves: list[FrapCurve], groups: list[GroupCurve] = ()) -> str:
    """One row per image with the FRAP numbers, then per group mean / SD / SEM / n
    and the fit of the group's mean curve."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = [k for k, _ in SUMMARY_KEYS]
    with path.open('w', newline='', encoding='utf-8') as f:
        f.write('# value = (bleach - background) / (control - background); fit y = a*(1-exp(-k*t)) + c '
                'over the frames from the bleach on (t: s after the first post-bleach frame)\n')
        w = csv.writer(f)
        w.writerow(['row', 'group', 'image', 'n', 'stat', 'channel', 'bleach_frame', 'frames'] + keys)
        for c in curves:
            s = c.summary()
            w.writerow(['image', c.group, c.label, 1, 'value', c.channel, c.bleach_frame + 1,
                        len(c.times)] + [_f(s[k]) for k in keys])
        for g in groups:
            gs = group_summary(g)
            for j, stat in enumerate(('mean', 'sd', 'sem')):
                w.writerow(['group', g.name, '', len(g.members), stat, '', '', '']
                           + [_f(gs[k][j]) for k in keys])
            pre = 1.0 if g.members and g.members[0].normalize else g.fit.pre if g.fit else float('nan')
            r_um = [c.bleach_radius_um for c in g.members if c.bleach_radius_um]
            fs = summary_values(g.mean, int(np.argmax(g.offset >= 0)), g.fit, g.t, pre,
                                float(np.mean(r_um)) if r_um else None)
            w.writerow(['group', g.name, '', len(g.members), 'fit of mean curve', '', '', '']
                       + [_f(fs[k]) for k in keys])
        w.writerow([])
        w.writerow(['column', 'meaning'])
        for k, text in SUMMARY_KEYS:
            w.writerow([k, text])
    return str(path)


def write_group_curves_csv(path, groups: list[GroupCurve], error='sem') -> str:
    """Mean curve of each group: time, mean, SD, SEM, n per frame offset."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['group', 'frame_from_bleach', 'time_after_bleach_s', 'mean', 'sd', 'sem', 'n', 'fit'])
        for g in groups:
            for i, o in enumerate(g.offset):
                fit = g.fit.value(g.t[i]) if g.fit is not None and o >= 0 else ''
                w.writerow([g.name, int(o), _f(g.t[i]), _f(g.mean[i]), _f(g.sd[i]), _f(g.sem[i]),
                            int(g.n[i]), _f(fit)])
    return str(path)


# ---------------------------------------------------------------------------
# ImageJ ROIs
# ---------------------------------------------------------------------------


def imagej_rois(rois: dict, properties=None) -> list:
    import roifile

    out = []
    for n in ROI_NAMES:
        r = rois.get(n)
        if r is None:
            continue
        if r.kind == 'polygon':
            roi = roifile.ImagejRoi.frompoints(np.asarray(r.xy, np.float32), name=ROI_PREFIX + n)
            roi.roitype = roifile.ROI_TYPE.POLYGON
        else:
            roi = roifile.ImagejRoi()
            roi.roitype = roifile.ROI_TYPE.OVAL if r.kind == 'oval' else roifile.ROI_TYPE.RECT
            roi.version = 228
            roi.left, roi.top, roi.right, roi.bottom = r.x, r.y, r.x + r.w, r.y + r.h
        roi.name = ROI_PREFIX + n
        roi.properties = dict(properties or {}, frap_roi=n)
        out.append(roi)
    return out


def save_rois(path, rois: dict, properties=None) -> str:
    import roifile

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    roifile.roiwrite(path, imagej_rois(rois, properties))
    return str(path)


def _read(path) -> list:
    import roifile

    try:
        r = roifile.roiread(path)
    except Exception:
        return []
    return r if isinstance(r, list) else [r]


def is_frap_file(path) -> bool:
    rois = _read(path)
    return bool(rois) and all((r.name or '').startswith(ROI_PREFIX) for r in rois)


def load_rois(path) -> dict:
    import roifile

    out = {}
    for r in _read(path):
        name = (r.properties or {}).get('frap_roi') or (r.name or '')[len(ROI_PREFIX):]
        if name not in ROI_NAMES:
            continue
        if r.roitype in (roifile.ROI_TYPE.OVAL, roifile.ROI_TYPE.RECT) and not r.composite:
            kind = 'oval' if r.roitype == roifile.ROI_TYPE.OVAL else 'rect'
            out[name] = FrapRoi(kind, int(r.left), int(r.top), int(r.right - r.left), int(r.bottom - r.top))
        else:
            xy = r.coordinates()
            if xy is not None and len(xy) >= 3:
                out[name] = FrapRoi('polygon', xy=np.asarray(xy, float))
    return out
