"""Colocalization analysis ported from Fiji's Coloc 2 plugin.

Source: https://github.com/fiji/Colocalisation_Analysis (sc.fiji.coloc).
Every algorithm here follows the Java code step by step, including its
quirks, so the numbers match what Coloc 2 reports for the same pixels:

- InputCheck: zero-zero / saturated pixel percentages, min/max/mean/sum.
- AutoThresholdRegression (Costes or Bisection stepper): the orthogonal
  regression line and the thresholds below which Pearson's r drops to <= 0.
- PearsonsCorrelation ("Fast" implementation, the one Coloc 2 uses): r with
  no threshold, below and above the thresholds.
- LiHistogram2D (ch1 / ch2), LiICQ, SpearmanRankCorrelation,
  MandersColocalization (M1, M2, tM1, tM2), KendallTauRankCorrelation (tau-b),
  Histogram2D (256 x 256 scatter plot) and CostesSignificanceTest
  (PSF-sized block shuffling, Gaussian smoothing, P-value from the normal CDF).

Images are numpy arrays (Y, X) or (Z, Y, X); a mask (same shape, or (Y, X)
repeated through Z like Coloc 2 does with a 2D ROI on a stack) selects the
pixels, exactly like a ROI Manager ROI in Coloc 2.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

import numpy as np

REGRESSIONS = ('Costes', 'Bisection')  # AutoThresholdRegression.Implementation order
FLOAT_MAX = float(np.finfo(np.float32).max)


@dataclass
class Coloc2Settings:
    """The options of the Coloc 2 dialog (same defaults)."""

    regression: str = 'Costes'
    li_ch1: bool = True
    li_ch2: bool = True
    li_icq: bool = True
    spearman: bool = True
    manders: bool = True
    kendall: bool = True
    histogram: bool = True
    costes: bool = True
    psf: int = 3
    costes_randomisations: int = 10
    display_shuffled: bool = False
    display_images: bool = False


@dataclass
class ValueType:
    """The ImageJ/imglib2 pixel type of the channels (min/max clamp thresholds;
    integer types round the smoothed Costes image back to integers)."""

    name: str
    lo: float
    hi: float
    integer: bool

    @classmethod
    def for_dtype(cls, dtype) -> 'ValueType':
        dtype = np.dtype(dtype)
        if dtype.kind in 'ui':
            info = np.iinfo(dtype)
            return cls(str(dtype), float(info.min), float(info.max), True)
        return cls('float32', -FLOAT_MAX, FLOAT_MAX, False)


@dataclass
class Histogram:
    """A 2D histogram as Coloc 2 builds it; counts[x, y] with y flipped
    (row 0 is the top, i.e. the highest y value)."""

    title: str
    counts: np.ndarray
    x_label: str
    y_label: str
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    x_bin_width: float
    y_bin_width: float
    regression: bool = False  # draw the regression line and thresholds


@dataclass
class Coloc2Result:
    values: list = field(default_factory=list)    # (name, value, decimals or None)
    warnings: list = field(default_factory=list)  # (short, long)
    histograms: list = field(default_factory=list)
    images: list = field(default_factory=list)    # (title, 2D array)
    slope: float = math.nan
    intercept: float = math.nan
    ch1_threshold: float = math.nan
    ch2_threshold: float = math.nan

    def value(self, name, default=math.nan):
        for n, v, _ in self.values:
            if n == name:
                return v
        return default

    def as_dict(self) -> dict:
        return {n: v for n, v, _ in self.values}


class MissingPrecondition(Exception):
    pass


# ---------------------------------------------------------------------------
# small Java helpers
# ---------------------------------------------------------------------------


def java_round(x) -> float:
    """Math.round(double): floor(x + 0.5); NaN -> 0; clipped to the long range."""
    x = float(x)
    if math.isnan(x):
        return 0.0
    if x >= 9.223372036854776e18:
        return 9.223372036854776e18
    if x <= -9.223372036854776e18:
        return -9.223372036854776e18
    return float(math.floor(x + 0.5))


def clamp(val, lo, hi):
    return lo if lo > val else hi if hi < val else val


def _store(value, vt: ValueType) -> float:
    """T.setReal(value): float types keep float precision, integer ones round."""
    if vt.integer:
        return float(int(value + 0.5 * np.sign(value)))
    return float(np.float32(value))


def d2s(v, decimals) -> str:
    if isinstance(v, str):
        return v
    if v is None:
        return ''
    if isinstance(v, (int, np.integer)) and decimals is None:
        return str(int(v))
    v = float(v)
    if math.isnan(v):
        return 'NaN'
    if math.isinf(v):
        return 'Infinity' if v > 0 else '-Infinity'
    return f'{v:.{3 if decimals is None else decimals}f}'


def erf(z):
    """Statistics.erf: the Numerical Recipes approximation Coloc 2 uses."""
    with np.errstate(all='ignore'):
        z = np.float64(z)
        t = 1.0 / (1.0 + 0.5 * abs(z))
        ans = 1 - t * np.exp(-z * z - 1.26551223 +
                             t * (1.00002368 +
                             t * (0.37409196 +
                             t * (0.09678418 +
                             t * (-0.18628806 +
                             t * (0.27886807 +
                             t * (-1.13520398 +
                             t * (1.48851587 +
                             t * (-0.82215223 +
                             t * (0.17087277))))))))))
        return ans if z >= 0 else -ans


def phi(z, mean, sd):
    with np.errstate(all='ignore'):
        z = (np.float64(z) - mean) / np.float64(sd)
        return 0.5 * (1.0 + erf(z * (1.0 / math.sqrt(2))))


# ---------------------------------------------------------------------------
# Pearson ("Fast" implementation) and the steppers
# ---------------------------------------------------------------------------


def fast_pearsons(x, y, sel=None) -> float:
    """PearsonsCorrelation.fastPearsons; raises MissingPrecondition on NaN/Inf."""
    if sel is not None:
        x, y = x[sel], y[sel]
    n = x.size
    with np.errstate(all='ignore'):
        sx, sy = x.sum(), y.sum()
        sxx, syy, sxy = np.dot(x, x), np.dot(y, y), np.dot(x, y)
        inv = np.float64(1.0) / np.float64(n)
        p1 = sxy - sx * sy * inv
        p2 = sxx - sx * sx * inv
        p3 = syy - sy * sy * inv
        r = p1 / np.sqrt(p2 * p3)
    if not np.isfinite(r):
        raise MissingPrecondition(
            'A numerical problem occured: the input data is unsuitable for this algorithm. '
            f'Possibly too few pixels (in range were: {n}).')
    return float(r)


class SimpleStepper:
    def __init__(self, threshold):
        self.threshold = float(threshold)
        self.current = 1.0
        self.last = 1.7976931348623157e308
        self.finished = False

    def update(self, value):
        if not self.finished:
            self.last = self.current
            self.current = value
            self.threshold = self.threshold - 1.0
            # (Double.NaN == value) is always false in Java; kept as is
            self.finished = (self.threshold < 1 or value < 0.0001 or value > self.last)

    def value(self):
        return self.threshold


class BisectionStepper:
    def __init__(self, threshold, last):
        self.t1 = float(threshold)
        self.t2 = float(last)
        self.diff = abs(self.t1 - self.t2)
        self.iterations = 0
        self.max_iterations = 100

    def update(self, value):
        self.t2 = self.t1
        if value < 0:  # (Double.NaN == value) is always false in Java
            self.t1 = self.t1 + self.diff * 0.5
        elif value > 0:
            self.t1 = self.t1 - self.diff * 0.5
        self.diff = abs(self.t1 - self.t2)
        self.iterations += 1

    def value(self):
        return self.t1

    @property
    def finished(self):
        return self.iterations > self.max_iterations or self.diff < 1.0


# ---------------------------------------------------------------------------
# the analysis
# ---------------------------------------------------------------------------


class Coloc2:
    """One Coloc 2 run (Coloc_2.colocalise) on two images and a mask."""

    def __init__(self, ch1, ch2, mask=None, settings: Coloc2Settings | None = None,
                 value_type: ValueType | None = None, names=('Channel 1', 'Channel 2'),
                 mask_id='', seed=None):
        ch1 = np.asarray(ch1)
        ch2 = np.asarray(ch2)
        if ch1.shape != ch2.shape:
            raise ValueError('두 채널의 크기가 다릅니다.')
        self.s = settings or Coloc2Settings()
        self.vt = value_type or ValueType.for_dtype(np.result_type(ch1.dtype, ch2.dtype))
        self.names = names
        self.shape = ch1.shape
        self.img1 = ch1.astype(np.float64)
        self.img2 = ch2.astype(np.float64)
        if self.vt.name == 'float32':
            # FloatType data: every value is a float
            self.img1 = self.img1.astype(np.float32).astype(np.float64)
            self.img2 = self.img2.astype(np.float32).astype(np.float64)
        if mask is None:
            self.mask = np.ones(self.shape, bool)
            self.mask_type = 'none'
            self.bb_offset = (0,) * ch1.ndim
            self.bb_size = tuple(self.shape)
        else:
            m0 = np.asarray(mask)
            m0 = m0 if m0.dtype == bool else m0 > 0.001
            if m0.shape != self.shape[-m0.ndim:] or m0.ndim > ch1.ndim:
                raise ValueError('마스크 크기가 이미지와 다릅니다.')
            if not m0.any():
                raise ValueError('마스크가 비어 있습니다.')
            self.mask = np.ascontiguousarray(np.broadcast_to(m0, self.shape))
            self.mask_type = 'mask image'
            # bounding box of the ROI; dimensions the ROI does not have (Z)
            # span the whole image (DataContainer.adjustRoiSize)
            idx = np.nonzero(m0)
            lo = [int(i.min()) for i in idx]
            hi = [int(i.max()) + 1 for i in idx]
            extra = ch1.ndim - m0.ndim
            self.bb_offset = tuple([0] * extra + lo)
            self.bb_size = tuple(list(self.shape[:extra]) + [h - l for l, h in zip(lo, hi)])
        self.mask_id = mask_id
        self.seed = seed
        self.x = self.img1[self.mask]
        self.y = self.img2[self.mask]
        self.r = Coloc2Result()

    # DataContainer.calculateStatistics
    def _statistics(self):
        x, y = self.x, self.y
        self.mean1, self.mean2 = float(x.sum() / x.size), float(y.sum() / y.size)
        self.min1, self.min2 = float(x.min()), float(y.min())
        self.max1, self.max2 = float(x.max()), float(y.max())
        self.sum1, self.sum2 = float(x.sum()), float(y.sum())

    def _value(self, name, value, decimals=None):
        self.r.values.append((name, value, decimals))

    def _warn(self, short, long=''):
        self.r.warnings.append((short, long))

    def run(self) -> Coloc2Result:
        self._statistics()
        jobs = [('input data check', self.input_check),
                ('auto threshold regression', self.auto_threshold),
                ('Pearson correlation', self.pearsons)]
        s = self.s
        if s.li_ch1:
            jobs.append(('Li - Ch1', lambda: self.li_histogram(True)))
        if s.li_ch2:
            jobs.append(('Li - Ch2', lambda: self.li_histogram(False)))
        if s.li_icq:
            jobs.append(('Li ICQ calculation', self.li_icq))
        if s.spearman:
            jobs.append(("Spearman's Rank Corelation calculation", self.spearman))
        if s.manders:
            jobs.append(('Manders correlation', self.manders))
        if s.kendall:
            jobs.append(("Kendall's Tau-b Rank Correlation", self.kendall))
        if s.histogram:
            jobs.append(('2D intensity histogram', self.histogram2d))
        if s.costes:
            jobs.append(('Costes significance test', self.costes))
        # Coloc_2 runs every job, then lets each one report its results in order
        self.thr1 = self.thr2 = None
        self.pearson = (math.nan, math.nan, math.nan)
        reports = []
        for name, job in jobs:
            self._partial = None
            try:
                rep = job()
            except MissingPrecondition as exc:
                self._warn('Probem with input data', f'{name}: {exc}')
                rep = self._partial
            reports.append(rep)
        warnings, self.r.warnings = self.r.warnings, []
        for rep in reports:
            if rep is not None:
                for w in rep.get('warnings', []):
                    self._warn(*w)
                for v in rep.get('values', []):
                    self._value(*v)
                for h in rep.get('hist', []):
                    self.r.histograms.append(h)
                for im in rep.get('images', []):
                    self.r.images.append(im)
        self.r.warnings = warnings + self.r.warnings
        if self.s.display_images:
            for i, img in enumerate((self.img1, self.img2)):
                self.r.images.append((f'Channel {i + 1} (Max Projection)', self._masked_mip(img)))
        return self.r

    def _masked_mip(self, img):
        sl = tuple(slice(o, o + n) for o, n in zip(self.bb_offset, self.bb_size))
        out = np.where(self.mask, img, 0)[sl]
        return out.max(axis=0) if out.ndim == 3 else out

    # ---- InputCheck -------------------------------------------------------

    def input_check(self):
        x, y = self.x, self.y
        n = x.size
        nzero = int((np.abs(x + y) < 0.00001).sum())
        nsat1 = int((np.abs(self.max1 - x) < 0.00001).sum())
        nsat2 = int((np.abs(self.max2 - y) < 0.00001).sum())
        zz = nzero / n
        sat1 = nsat1 / (n * 0.5)
        sat2 = nsat2 / (n * 0.5)
        w = []
        if self.min1 < 0 or self.min2 < 0:
            w.append(('Negative minimum pixel value found.',
                      'The minimum pixel value in at least one of the channels is negative. '
                      'Negative values might break the logic of some analysis methods by breaking '
                      'a basic basic assumption: The pixel value is assumed to be proportional to '
                      'the number of photons detected in a pixel. Negative photon counts make no '
                      'physical sense. Set negative pixel values to zero, or shift pixel '
                      'intensities higher so there are no negative pixel values.'))
        if abs(zz) > 0.1:
            w.append(('Zero-zero ratio too high',
                      'The ratio between zero-zero pixels and other pixels is large: '
                      f'{zz:.2f}. Maybe you should use a ROI.'))
        if abs(sat1) > 0.1:
            w.append(('Saturated ch1 ratio too high',
                      'The ratio between saturated pixels and other pixels in channel one is '
                      'large: 0.10. Maybe you should use a ROI.'))
        # Coloc 2 tests the channel 1 ratio again for its channel 2 warning
        if abs(sat1) > 0.1:
            w.append(('Saturated ch2 ratio too high',
                      'The ratio between saturated pixels and other pixels in channel two is '
                      'large: 0.10. Maybe you should use a ROI.'))
        job = f'Colocalization_of_{self.names[0]}_versus_{self.names[1]}_{self.mask_id}'
        return {'warnings': w, 'values': [
            ('Coloc_Job_Name', job, None),
            ('% zero-zero pixels', zz * 100.0, 2),
            ('% saturated ch1 pixels', sat1 * 100.0, 2),
            ('% saturated ch2 pixels', sat2 * 100.0, 2),
            ('Channel 1 Max', self.max1, 3),
            ('Channel 2 Max', self.max2, 3),
            ('Channel 1 Min', self.min1, 3),
            ('Channel 2 Min', self.min2, 3),
            ('Channel 1 Mean', self.mean1, 3),
            ('Channel 2 Mean', self.mean2, 3),
            ('Channel 1 Integrated (Sum) Intensity', self.sum1, 3),
            ('Channel 2 Integrated (Sum) Intensity', self.sum2, 3),
            ('Mask Type Used', self.mask_type, None),
            ('Mask ID Used', self.mask_id, None),
        ]}

    # ---- AutoThresholdRegression ------------------------------------------

    def auto_threshold(self):
        x, y = self.x, self.y
        vt = self.vt
        # Coloc 2 reads cursor.getFirst() for the pixel type before its loop,
        # which steps the cursor past the first masked pixel: the variances
        # below leave that pixel out (N is one less), the stepper uses all
        xs, ys = x[1:], y[1:]
        n = xs.size
        with np.errstate(all='ignore'):
            m1, m2 = np.float64(self.mean1), np.float64(self.mean2)
            comb = xs + ys
            var1 = ((xs - m1) ** 2).sum() / np.float64(n - 1)
            var2 = ((ys - m2) ** 2).sum() / np.float64(n - 1)
            varc = ((comb - (m1 + m2)) ** 2).sum() / (n - 1.0)
            cov = 0.5 * (varc - (var1 + var2))
            denom = 2 * cov
            num = var2 - var1 + np.sqrt((var2 - var1) * (var2 - var1) + (4 * cov * cov))
            m = num / denom
            b = m2 - m * m1
        m, b = float(m), float(b)

        if -1 < m < 1.0:
            def ch1_thr(t):
                return t

            def ch2_thr(t):
                return t * m + b
            if self.s.regression == 'Bisection':
                stepper = BisectionStepper(abs(self.max1 + self.min1) * 0.5, self.max1)
            else:
                stepper = SimpleStepper(self.max1)
        else:
            def ch1_thr(t):
                with np.errstate(all='ignore'):
                    return float((np.float64(t) - b) / np.float64(m))

            def ch2_thr(t):
                return t
            if self.s.regression == 'Bisection':
                stepper = BisectionStepper(abs(self.max2 + self.min2) * 0.5, self.max2)
            else:
                stepper = SimpleStepper(self.max2)

        t1max, t2max = self.max1, self.max2
        while not stepper.finished:
            t1max = java_round(ch1_thr(stepper.value()))
            t2max = java_round(ch2_thr(stepper.value()))
            th1 = _store(clamp(t1max, vt.lo, vt.hi), vt)
            th2 = _store(clamp(t2max, vt.lo, vt.hi), vt)
            try:
                r = fast_pearsons(x, y, (x < th1) | (y < th2))
            except MissingPrecondition:
                r = math.nan
            stepper.update(r)

        self.thr1 = _store(clamp(t1max, vt.lo, vt.hi), vt)
        self.thr2 = _store(clamp(t2max, vt.lo, vt.hi), vt)
        self.r.slope, self.r.intercept = m, b
        self.r.ch1_threshold, self.r.ch2_threshold = self.thr1, self.thr2
        with np.errstate(all='ignore'):
            b_ratio = float(np.float64(b) / np.float64(self.mean2))
        w = []
        if abs(b_ratio) > 0.01:
            w.append(('y-intercept far from zero',
                      'The ratio of the y-intercept of the auto threshold regression line to the '
                      'mean value of Channel 2 is high. This means the y-intercept is far from '
                      'zero, implying a significant positive or negative zero offset in the image '
                      'data intensities. Maybe you should use a ROI. Maybe do a background '
                      'subtraction in both channels. Make sure you didn\'t clip off the low '
                      'intensities to zero. This might not affect Pearson\'s correlation values '
                      'very much, but might harm other results.'))
        if t1max > self.mean1:
            w.append(('Threshold of ch. 1 too high',
                      'Too few pixels are taken into account for above-threshold calculations. '
                      'The threshold is above the channel\'s mean.'))
        if t2max > self.mean2:
            w.append(('Threshold of ch. 2 too high',
                      'Too few pixels are taken into account for above-threshold calculations. '
                      'The threshold is above the channel\'s mean.'))
        if t1max < self.min1 or t2max < self.min2:
            msg = ('The auto threshold method could not find a positive threshold, so '
                   'thresholded results are meaningless.')
            if self.s.regression != 'Costes':
                msg += ' Maybe you should try classic thresholding.'
            w.append(('thresholds too low', msg))
        return {'warnings': w, 'values': [
            ('m (slope)', m, 2),
            ('b (y-intercept)', b, 2),
            ('b to y-mean ratio', b_ratio, 2),
            ('Ch1 Max Threshold', self.thr1, 2),
            ('Ch2 Max Threshold', self.thr2, 2),
            ('Threshold regression', self.s.regression, None),
        ]}

    # ---- PearsonsCorrelation ----------------------------------------------

    def pearsons(self):
        x, y = self.x, self.y
        out, err = [], None
        for sel in (None, (x < self.thr1) | (y < self.thr2), (x > self.thr1) | (y > self.thr2)):
            try:
                out.append(fast_pearsons(x, y, sel))
            except MissingPrecondition as exc:
                out.append(math.nan)
                err = exc
        self.pearson = tuple(out)
        rep = {'values': [
            ("Pearson's R value (no threshold)", out[0], 2),
            ("Pearson's R value (below threshold)", out[1], 2),
            ("Pearson's R value (above threshold)", out[2], 2),
        ]}
        if err is not None:
            self._partial = rep
            raise err
        return rep

    # ---- Histogram2D / LiHistogram2D ---------------------------------------

    def _fill_histogram(self, title, xi, yi, nx, ny):
        counts = np.zeros((nx, ny), np.int64)
        ok = (xi >= 0) & (yi >= 0) & (xi < nx) & (yi < ny)
        np.add.at(counts, (xi[ok], yi[ok]), 1)
        ignored = int((~ok).sum())
        w = []
        if ignored > 0:
            w.append(('Ignored pixels while generating histogram.',
                      f'{ignored} pixels were ignored while generating the 2D histogram "{title}" '
                      'because the grey values were out of range.This may happen, if an image '
                      'contains negative pixel values.'))
        return counts, w

    @staticmethod
    def _int(a):
        """Java (int) cast: truncate toward zero."""
        with np.errstate(all='ignore'):
            a = np.trunc(a)
            a = np.nan_to_num(a, nan=0.0, posinf=2 ** 31 - 1, neginf=-2 ** 31)
        return np.clip(a, -2 ** 31, 2 ** 31 - 1).astype(np.int64)

    def histogram2d(self):
        bins = 256
        title = '2D intensity histogram'
        xw = 1.0 if self.max1 < bins else (bins - 0.50001) / self.max1
        yw = 1.0 if self.max2 < bins else (bins - 0.50001) / self.max2
        xi = self._int(self.x * xw + 0.5)
        yi = (bins - 1) - self._int(self.y * yw + 0.5)
        counts, w = self._fill_histogram(title, xi, yi, bins, bins)
        h = Histogram(title, counts, self.names[0], self.names[1], 0.0, self.max1, 0.0,
                      self.max2, xw, yw, regression=True)
        return {'warnings': w, 'hist': [h]}

    def li_histogram(self, use_ch1: bool):
        bins = 256
        title = 'Li - Ch1' if use_ch1 else 'Li - Ch2'
        x, y = self.x, self.y
        prod = (self.mean1 - x) * (self.mean2 - y)
        li_min = min(float(prod.min()), 1.7976931348623157e308)
        li_max = max(float(prod.max()), 5e-324)  # Double.MIN_VALUE start, as in Coloc 2
        li_diff = abs(li_max - li_min)
        xw = bins / (li_diff + 1)
        top = self.max1 if use_ch1 else self.max2
        yw = bins / (top + 1)
        xi = self._int((prod - li_min) * xw)
        yi = (bins - 1) - self._int((x if use_ch1 else y) * yw)
        counts, w = self._fill_histogram(title, xi, yi, bins, bins)
        lo = self.min1 if use_ch1 else self.min2
        h = Histogram(title, counts, '(Ch1 - Mean1)(Ch2 - Mean2)',
                      self.names[0] if use_ch1 else self.names[1],
                      li_min, li_max, lo, top, xw, yw)
        return {'warnings': w, 'hist': [h]}

    # ---- LiICQ ------------------------------------------------------------

    def li_icq(self):
        prod = (self.mean1 - self.x) * (self.mean2 - self.y)
        neg = int((prod < 0.0).sum())
        pos = prod.size - neg
        icq = pos / (neg + pos) - 0.5
        return {'values': [("Li's ICQ value", icq, None)]}

    # ---- SpearmanRankCorrelation ------------------------------------------

    def spearman(self):
        from scipy.stats import rankdata

        n = self.x.size
        rx = rankdata(self.x, method='average')
        ry = rankdata(self.y, method='average')
        with np.errstate(all='ignore'):
            dx, dy = rx - rx.sum() / n, ry - ry.sum() / n
            rho = float(np.dot(dx, dy) / np.sqrt(np.dot(dx, dx) * np.dot(dy, dy)))
            t = float(np.float64(rho) * np.sqrt(np.float64(n - 2) / (1 - np.float64(rho) ** 2)))
        return {'values': [
            ("Spearman's rank correlation value", rho, 8),
            ("Spearman's correlation t-statistic", t, 4),
            ('t-statistic degrees of freedom', n - 2, None),
        ]}

    # ---- MandersColocalization ----------------------------------------------

    def manders(self):
        x, y = self.x, self.y
        with np.errstate(all='ignore'):
            s1, s2 = np.float64(x.sum()), np.float64(y.sum())
            m1 = float(x[y > 0].sum() / s1)
            m2 = float(y[x > 0].sum() / s2)
            tm1 = float(x[(y > 0) & (y >= self.thr2)].sum() / s1)
            tm2 = float(y[(x > 0) & (x >= self.thr1)].sum() / s2)
        return {'values': [
            ("Manders' M1 (Above zero intensity of Ch2)", m1, None),
            ("Manders' M2 (Above zero intensity of Ch1)", m2, None),
            ("Manders' tM1 (Above autothreshold of Ch2)", tm1, None),
            ("Manders' tM2 (Above autothreshold of Ch1)", tm2, None),
        ]}

    # ---- KendallTauRankCorrelation -------------------------------------------

    def kendall(self):
        return {'values': [("Kendall's Tau-b rank correlation value",
                            kendall_tau_b(self.x, self.y), 4)]}

    # ---- CostesSignificanceTest ---------------------------------------------

    def costes(self):
        psf = int(self.s.psf)
        if psf < 1:
            raise MissingPrecondition('PSF must be at least 1 pixel.')
        img1, shape = self.img1, self.shape
        nd = img1.ndim
        if nd not in (2, 3):
            raise MissingPrecondition('Currently only 2D and 3D images are supported.')
        # block grid over the mask's bounding box: full blocks plus one more in
        # every dimension (generateBlocks always adds the "out of bounds" block)
        grid = [self.bb_size[d] // psf + 1 for d in range(nd)]
        starts = [self.bb_offset[d] + psf * np.arange(grid[d]) for d in range(nd)]
        # read blocks from the mirror-extended channel 1 (Views.extendMirrorSingle)
        idx = [_mirror(np.add.outer(starts[d], np.arange(psf)).ravel(), shape[d])
               for d in range(nd)]
        tiled = img1[np.ix_(*idx)]
        blocks = _to_blocks(tiled, grid, psf)
        order = list(range(len(blocks)))
        rnd = random.Random(self.seed)
        kernels = [_gauss_kernel(psf)] * nd
        out_sl = tuple(slice(self.bb_offset[d], min(self.bb_offset[d] + grid[d] * psf, shape[d]))
                       for d in range(nd))
        crop = tuple(slice(0, s.stop - s.start) for s in out_sl)
        # smooth only the shuffled region plus twice the kernel radius: same
        # values as smoothing the whole image wherever they can be nonzero (the
        # window ends at the image edge, mirrored as in Coloc 2, or where the
        # kernel only sees zeros)
        rad = [2 * (len(k) // 2) for k in kernels]
        win = tuple(slice(max(out_sl[d].start - rad[d], 0),
                          min(out_sl[d].stop + rad[d], shape[d]))
                    for d in range(nd))
        win_mask = self.mask[win]
        results, retries, n_rand = [], 0, int(self.s.costes_randomisations)
        smoothed = None
        i = 0
        while i < n_rand:
            rnd.shuffle(order)  # Collections.shuffle(inputBlocks)
            shuffled = np.zeros(shape, np.float64)
            shuffled[out_sl] = _from_blocks(blocks[order], grid, psf)[crop]
            smoothed = _gauss(shuffled[win], kernels)
            if self.vt.integer:
                smoothed = np.trunc(smoothed + 0.5 * np.sign(smoothed))
            else:
                smoothed = smoothed.astype(np.float32).astype(np.float64)
            try:
                results.append(fast_pearsons(smoothed[win_mask], self.y))
            except MissingPrecondition as exc:
                if retries < 3:
                    retries += 1
                    n_rand += 1
                else:
                    self._partial = {'values': [
                        ('Costes P-Value', 0.0, 2), ('Costes Shuffled Mean', 0.0, 2),
                        ('Costes Shuffled Std.D.', 0.0, 2),
                        ('Ratio of rand. Pearsons >= actual Pearsons value ', 0.0, 2)]}
                    raise MissingPrecondition(
                        f'Maximum retries have been made ({retries}), but errors keep on coming: '
                        f'{exc}')
            i += 1
        original = self.pearson[0]
        not_less = sum(1 for v in results if v - original > -0.00001)
        with np.errstate(all='ignore'):
            mean = np.float64(sum(results)) / len(results)
            sd = np.sqrt(np.float64(sum((v - mean) ** 2 for v in results)) / (len(results) - 1))
            p = phi(original, mean, sd)
        p = float(p)
        if p > 1.0:
            p = 1.0
        elif p < 0.0:
            p = 0.0
        ratio = len(results) / not_less if not_less > 0 else 0.0
        rep = {'values': [
            ('Costes P-Value', p, 2),
            ('Costes Shuffled Mean', float(mean), 2),
            ('Costes Shuffled Std.D.', float(sd), 2),
            ('Ratio of rand. Pearsons >= actual Pearsons value ', ratio, 2),
        ]}
        if self.s.display_shuffled and smoothed is not None:
            full = np.zeros(shape, smoothed.dtype)  # zero beyond the kernel's reach
            full[win] = smoothed
            img = full.max(axis=0) if full.ndim == 3 else full
            rep['images'] = [('Smoothed & shuffled channel 1', img)]
        return rep


def _mirror(i, n):
    """Index into an axis of length n with mirror-single extension."""
    if n == 1:
        return np.zeros_like(i)
    period = 2 * n - 2
    i = np.mod(i, period)
    return np.where(i >= n, period - i, i)


def _to_blocks(tiled, grid, psf):
    nd = len(grid)
    shp = []
    for g in grid:
        shp += [g, psf]
    a = tiled.reshape(shp)
    a = a.transpose(list(range(0, 2 * nd, 2)) + list(range(1, 2 * nd, 2)))
    return a.reshape((-1,) + (psf,) * nd)


def _from_blocks(blocks, grid, psf):
    nd = len(grid)
    a = blocks.reshape(tuple(grid) + (psf,) * nd)
    perm = []
    for d in range(nd):
        perm += [d, nd + d]
    return a.transpose(perm).reshape(tuple(g * psf for g in grid))


def _gauss_kernel(sigma):
    """imglib2 Util.createGaussianKernel1DDouble(sigma, true)."""
    if sigma <= 0:
        return np.array([0.0, 1.0, 0.0])
    size = max(3, 2 * int(3 * sigma + 0.5) + 1)
    x = np.arange(size) - size // 2
    k = np.exp(-(x * x) / (2.0 * sigma * sigma))
    return k / k.sum()


def _gauss(img, kernels):
    """Separable Gaussian with mirror-single borders (Gauss.inFloat)."""
    from scipy.ndimage import correlate1d

    out = img.astype(np.float32)
    for axis, k in enumerate(kernels):
        out = correlate1d(out, k, axis=axis, mode='mirror', output=np.float32)
    return out.astype(np.float64)


def kendall_tau_b(x, y) -> float:
    """Kendall's tau-b, (n0 - n1 - n2 + n3 - 2 S) / sqrt((n0 - n1)(n0 - n2)): the
    value KendallTauRankCorrelation.calculateMergeSort computes (scipy uses the
    same merge sort counting)."""
    from scipy.stats import kendalltau

    x = np.asarray(x, np.float64)
    y = np.asarray(y, np.float64)
    if x.size < 2:
        return math.nan
    with np.errstate(all='ignore'):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            return float(kendalltau(x, y, variant='b', method='asymptotic').statistic)


# ---------------------------------------------------------------------------
# convenience
# ---------------------------------------------------------------------------


def run_coloc2(ch1, ch2, mask=None, settings: Coloc2Settings | None = None,
               value_type: ValueType | None = None, names=('Channel 1', 'Channel 2'),
               mask_id='', seed=None) -> Coloc2Result:
    return Coloc2(ch1, ch2, mask, settings, value_type, names, mask_id, seed).run()
