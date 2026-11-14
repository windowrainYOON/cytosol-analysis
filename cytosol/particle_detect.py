"""Automatic particles by significance (v0.65; 입자 ROI 자동, ParticleTracker-style).

The plane is smoothed (Gaussian 1 px) minus its background (Gaussian 2.8 µm),
the noise σ comes from the lower half of that image inside the region (the
particles only add to the upper half), and a seed must stand k σ above the
median. k follows the image size and the noise's own smoothness: the
expected number of noise peaks taken for particles in one image is ``noise``
(default 0.5; Euler characteristic of a Gaussian field), so a larger image
gets a larger k. Particles reach down to k / 2 σ, touching ones are split only
where the valley between two peaks is 3 σ deep (h-maxima), pieces smaller
than half a diffraction spot are dropped.

입자 기준 잡기 (calibration): ``candidates`` finds every peak of a
permissive run with its brightness (peak SNR) and size (half-max area); the
user picks the faintest and the smallest one that is still a particle, which
gives ``crit_k`` (seeds) and ``crit_area`` (µm², half-max area) used in
place of the statistical k.
"""

from __future__ import annotations

import math

import numpy as np

BG_UM = 2.8          # background scale
SPOT_UM = 0.25       # radius of a diffraction-limited spot
SPLIT_SIGMA = 3.0    # valley depth that splits two touching particles
DEFAULT_PX_UM = 0.1


def _filled(plane, region):
    """The plane with the pixels outside the region set to the nearest region
    pixel, so the background filter does not answer to the region's edge."""
    from scipy import ndimage as ndi
    p = plane.astype(np.float32)
    if region.any() and not region.all():
        near = ndi.distance_transform_edt(~region, return_distances=False, return_indices=True)
        p = p[tuple(near)]
    return p


def noise_model(plane, region, px_um=None):
    """(smoothed − background image, raw-ish image for half-max areas, median, σ)."""
    from scipy import ndimage as ndi
    px = px_um or DEFAULT_PX_UM
    p = _filled(plane, region)
    bg = ndi.gaussian_filter(p, BG_UM / px)
    sm = ndi.gaussian_filter(p, 1.0) - bg
    raw = ndi.gaussian_filter(p, 0.5) - bg
    v = sm[region] if region.any() else sm.ravel()
    med = float(np.median(v))
    low = v[v <= med] - med
    sigma = float(np.sqrt(np.mean(low ** 2))) if low.size else 0.0
    return sm, raw, med, max(sigma, 1e-6)


def spot_px(px_um=None) -> float:
    px = px_um or DEFAULT_PX_UM
    return math.pi * (SPOT_UM / px) ** 2


def smoothness(snr, region) -> float:
    """Λ of the unit-variance noise field: the mean squared difference between
    neighbouring background pixels (|z| < 2), per direction."""
    v = []
    for ax in (0, 1):
        d = np.diff(snr, axis=ax)
        a = np.abs(snr) < 2
        both = (a[1:] & a[:-1]) if ax == 0 else (a[:, 1:] & a[:, :-1])
        if region is not None:
            both &= (region[1:] & region[:-1]) if ax == 0 else (region[:, 1:] & region[:, :-1])
        if both.any():
            v.append(float(np.mean(d[both] ** 2)))
    return float(np.mean(v)) if v else 0.0


def significance_k(n_px: int, px_um=None, noise: float = 0.5, lam: float | None = None) -> float:
    """Seed threshold in σ so that about ``noise`` noise peaks pass in an area
    of n_px: the expected number of peaks of a smooth Gaussian noise field
    above u (Euler characteristic, 2D) is n_px · Λ · (2π)^-3/2 · u · e^(−u²/2),
    Λ = ``smoothness`` of the image's own noise; without Λ, one trial per
    diffraction spot."""
    noise = max(noise, 1e-6)
    if lam:
        c = n_px * lam * (2 * math.pi) ** -1.5

        def f(u):
            return c * u * math.exp(-u * u / 2) - noise
        lo, hi = 1.0, 40.0
        if f(lo) <= 0:
            return lo
        for _ in range(80):
            mid = (lo + hi) / 2
            if f(mid) > 0:
                lo = mid
            else:
                hi = mid
        return lo
    from scipy.stats import norm
    trials = max(n_px / max(spot_px(px_um), 1.0), 1.0)
    return float(norm.isf(min(noise, trials * 0.5) / trials))


def _half_max_areas(lab, raw):
    """Half-max area (px) of every label: pixels at or above half its peak."""
    from scipy import ndimage as ndi
    n = int(lab.max())
    if not n:
        return np.zeros(1)
    peak = np.asarray(ndi.maximum(raw, lab, np.arange(1, n + 1)), np.float32)
    top = np.zeros(n + 1, np.float32)
    top[1:] = peak
    above = (lab > 0) & (raw >= 0.5 * top[lab])
    return np.bincount(lab[above], minlength=n + 1)


def significance_particles(plane, lab, region, s, px_um=None):
    """Particle number image, per-cell lowest raw intensity of a particle, and
    info (k, sigma, k_source)."""
    from scipy import ndimage as ndi
    from skimage import measure, morphology, segmentation

    out = np.zeros(lab.shape, np.int32)
    info = {}
    if not region.any():
        return out, {}, info
    sm, raw, med, sigma = noise_model(plane, region, px_um)
    snr = (sm - med) / sigma
    if getattr(s, 'crit_k', 0) > 0:
        k, source = float(s.crit_k), 'user'
    else:
        k = significance_k(int(region.sum()), px_um, getattr(s, 'noise', 0.5), smoothness(snr, region))
        source = 'stat'
    info = dict(k=k, sigma=sigma, median=med, source=source)
    mask = region & (snr > 0.5 * k)
    core = region & (snr > k)
    if not core.any():
        return out, {}, info
    sp = spot_px(px_um)
    lab0 = measure.label(mask, connectivity=2)
    good = np.unique(lab0[core])
    mask = np.isin(lab0, good[good > 0])
    hm = morphology.h_maxima(ndi.gaussian_filter(sm, 1.0), SPLIT_SIGMA * sigma)
    seeds = measure.label(hm & core & mask, connectivity=2)
    # a component whose maximum plateau missed the h-maxima still gets a seed
    miss = np.setdiff1d(np.unique(lab0[mask]), np.unique(lab0[seeds > 0]))
    if len(miss):
        nxt = int(seeds.max())
        for l in miss[miss > 0]:
            m = lab0 == l
            y, x = np.unravel_index(np.argmax(np.where(m, sm, -np.inf)), m.shape)
            nxt += 1
            seeds[y, x] = nxt
    ws = segmentation.watershed(-sm, seeds, mask=mask)
    # one particle never spans two cells: the cell of its seed
    n = int(ws.max())
    owner = np.zeros(n + 1, lab.dtype)
    sl = np.flatnonzero(seeds.ravel())
    owner[ws.ravel()[sl]] = lab.ravel()[sl]
    ws[(ws > 0) & (owner[ws] != lab)] = 0
    size = np.bincount(ws.ravel(), minlength=n + 1)
    drop = size < max(1, int(0.5 * sp))
    min_area = getattr(s, 'crit_area', 0) or 0
    if min_area > 0:
        px = px_um or DEFAULT_PX_UM
        drop |= _half_max_areas(ws, raw) < min_area / (px * px)
    drop[0] = False
    ws[drop[ws]] = 0
    out = segmentation.relabel_sequential(ws)[0].astype(np.int32)
    # per cell: about the lowest raw intensity a particle reaches
    p = plane.astype(np.float32)
    cutoff = {}
    for l in np.unique(lab[region]):
        if l:
            m = region & (lab == l)
            cutoff[int(l)] = float(np.median(p[m]) + 0.5 * k * sigma)
    return out, cutoff, info


# ---------------------------------------------------------------------------
# 입자 기준 잡기
# ---------------------------------------------------------------------------

def candidates(plane, region, px_um=None, margin=12):
    """Every peak of a permissive run (seeds ≥ 2σ, h-maxima 1.5σ, extent ≥ 1.5σ)
    that has nothing brighter around it: dicts with snr, area (half-max, px),
    y, x, label; plus (snr image, σ)."""
    from scipy import ndimage as ndi
    from skimage import measure, morphology, segmentation
    sm, raw, med, sig = noise_model(plane, region, px_um)
    snr = (sm - med) / sig
    seeds = measure.label(morphology.h_maxima(ndi.gaussian_filter(sm, 1.0), 1.5 * sig)
                          & (snr > 2.0) & region)
    lab = segmentation.watershed(-sm, seeds, mask=(snr > 1.5) & region)
    h, w = lab.shape
    yy, xx = np.mgrid[-margin:margin + 1, -margin:margin + 1]
    ring = (yy ** 2 + xx ** 2) > (margin * 0.42) ** 2
    out = []
    for r in measure.regionprops(lab):
        sub = np.where(lab[r.slice] == r.label, snr[r.slice], -np.inf)
        y, x = np.unravel_index(np.argmax(sub), sub.shape)
        y, x = int(y + r.slice[0].start), int(x + r.slice[1].start)
        if not (margin <= y < h - margin and margin <= x < w - margin):
            continue
        s = float(snr[y, x])
        win = snr[y - margin:y + margin + 1, x - margin:x + margin + 1]
        if win[ring].max() > 0.6 * s + 1.5:
            continue
        v = raw[r.slice][r.image]
        out.append(dict(label=int(r.label), snr=s, area=int((v >= 0.5 * v.max()).sum()), y=y, x=x))
    return out, snr, sig


def pick(pool, key, targets, used=(), apart=34):
    """For each target value the nearest candidate (log scale), none twice,
    none within ``apart`` px of another one picked; sorted by the key."""
    used = set(used)
    out = []
    for t in targets:
        best = None
        for c in pool:
            if c['label'] in used or any(abs(c['y'] - o['y']) < apart and abs(c['x'] - o['x']) < apart
                                         for o in out):
                continue
            d = abs(math.log(max(c[key], 1e-6)) - math.log(t))
            if best is None or d < best[0]:
                best = (d, c)
        if best is not None:
            out.append(best[1])
            used.add(best[1]['label'])
    out.sort(key=lambda c: c[key])
    return out


def brightness_targets(lo=3.0, hi=15.0, n=9):
    return list(np.geomspace(lo, hi, n))


def size_targets(px_um=None, n=9):
    """Half-max areas (px) from about a third to twice a diffraction spot."""
    sp = spot_px(px_um)
    return list(np.geomspace(max(2.0, 0.35 * sp), max(4.0, 2.2 * sp), n))
