"""Z-stack projections: one 2D image from a stack (max, mean, sum, ...) and a
3D projection seen from an angle (rotation about the Y or X axis).

GUI-independent; the app's Stack tab (cytosol.stack_panel) drives it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .lut import ChannelLUT, ImageItem, add_colored, auto_range
from .render import ScaleBarStyle, TimeStampStyle

METHODS_2D = {
    'max': 'Max intensity',
    'mean': 'Average intensity',
    'sum': 'Sum slices',
    'min': 'Min intensity',
    'std': 'Standard deviation',
    'median': 'Median',
}
METHODS_3D = {
    'max': 'Brightest point (max)',
    'mean': 'Mean value',
}


def project_2d(vol: np.ndarray, method: str = 'max') -> np.ndarray:
    """(C, Z, Y, X) -> (C, Y, X) float32 along Z."""
    vol = np.asarray(vol)
    if method == 'max':
        out = vol.max(axis=1)
    elif method == 'min':
        out = vol.min(axis=1)
    elif method == 'mean':
        out = vol.mean(axis=1, dtype=np.float64)
    elif method == 'sum':
        out = vol.sum(axis=1, dtype=np.float64)
    elif method == 'std':
        out = vol.std(axis=1, dtype=np.float64)
    elif method == 'median':
        out = np.median(vol, axis=1)
    else:
        raise ValueError(f'unknown projection {method!r}')
    return np.asarray(out, np.float32)


def _turntable(v: np.ndarray, theta: float, zr: float, method: str, width: int) -> np.ndarray:
    """One channel (Z, Y, X) seen after turning it by theta (rad) about the Y axis.

    Splatting: every voxel column x of every slice lands on screen column
    u = (x - xc) cos + (z zr - zc) sin; runs of x that share a column are
    reduced with np.maximum.reduceat (or summed for the mean), so nothing is
    skipped however steep the angle. Slices are linearly interpolated so that
    neighbours are at most one screen pixel apart (no gaps at 90 degrees).
    Returns (Y, width); columns no voxel reaches are NaN.
    """
    nz, ny, nx = v.shape
    c, s = math.cos(theta), math.sin(theta)
    zext = (nz - 1) * zr
    xc, zc, uc = (nx - 1) / 2, zext / 2, (width - 1) / 2
    n = nz if nz == 1 else max(nz, int(math.ceil(zext * abs(s))) + 1)
    zs = np.linspace(0, nz - 1, n)
    x = np.arange(nx)
    use_max = method == 'max'
    acc = np.full((ny, width), -np.inf if use_max else 0.0, np.float32)
    cnt = None if use_max else np.zeros(width, np.float32)
    flip = c < 0
    buf = np.empty((ny, nx), np.float32)
    for zf in zs:
        j0 = int(math.floor(zf))
        w = zf - j0
        if w < 1e-6 or j0 + 1 >= nz:
            plane = v[j0]
        else:
            np.multiply(v[j0], np.float32(1 - w), out=buf)
            buf += np.float32(w) * v[j0 + 1]
            plane = buf
        u = np.floor((x - xc) * c + (zf * zr - zc) * s + uc + 0.5).astype(np.int64)
        if flip:
            u, plane = u[::-1], plane[:, ::-1]
        starts = np.flatnonzero(np.r_[True, np.diff(u) != 0])
        # |cos| <= 1, so the runs land on consecutive columns u0, u0 + 1, ...
        # (always inside: width holds the volume at any angle)
        cols = slice(int(u[0]), int(u[0]) + len(starts))
        if use_max:
            vals = np.maximum.reduceat(plane, starts, axis=1)
            np.maximum(acc[:, cols], vals, out=acc[:, cols])
        else:
            acc[:, cols] += np.add.reduceat(plane, starts, axis=1, dtype=np.float32)
            cnt[cols] += np.diff(np.r_[starts, nx])
    if use_max:
        acc[np.isneginf(acc)] = np.nan
        return acc
    with np.errstate(invalid='ignore', divide='ignore'):
        out = acc / cnt
    out[:, cnt == 0] = np.nan
    return out


def _shear_warp(v: np.ndarray, theta: float, method: str, columns=None) -> np.ndarray:
    """Fast turntable projection of one channel (Z, Y, X) with cubic voxels.

    Shear-warp: the slices along the axis closest to the view are shifted by
    whole pixels into an intermediate image and combined with an elementwise
    max (or sum), which is one cheap vectorized step per slice; a single
    reduceat then squeezes that image onto the screen columns. Positions are
    within half a pixel of the exact turn (``_turntable``).
    columns: optional callable returning v as contiguous (X, Y, Z), used for
    the nearly edge-on case (much faster than strided column reads).
    Returns (Y, width) float32; columns no voxel reaches are 0.
    """
    nz, ny, nx = v.shape
    c, s = math.cos(theta), math.sin(theta)
    width = projection_width(nx, nz, 1.0)
    uc = (width - 1) / 2
    if abs(c) >= abs(s):  # walk the Z slices, X runs along the screen
        n, nfast, t, scale = nz, nx, s / c, c
        slow_c, fast_c = (nz - 1) / 2, (nx - 1) / 2

        def plane(k):
            return v[k]
    else:  # nearly edge-on: walk the X columns, Z runs along the screen
        n, nfast, t, scale = nx, nz, c / s, s
        slow_c, fast_c = (nx - 1) / 2, (nz - 1) / 2

        vt = columns() if columns is not None else None

        def plane(k):
            return vt[k] if vt is not None else v[:, :, k].T
    shifts = np.rint((np.arange(n) - slow_c) * t).astype(np.int64)
    lo = int(shifts.min())
    w_inter = nfast + int(shifts.max()) - lo
    use_max = method == 'max'
    inter = np.zeros((ny, w_inter), v.dtype if use_max else np.float32)
    cover = None if use_max else np.zeros(w_inter + 1, np.float32)
    for k in range(n):
        a = int(shifts[k]) - lo
        dst = inter[:, a:a + nfast]
        if use_max:
            np.maximum(dst, plane(k), out=dst)
        else:
            dst += plane(k)
            cover[a] += 1
            cover[a + nfast] -= 1
    u = np.floor(scale * (np.arange(w_inter) + lo - fast_c) + uc + 0.5).astype(np.int64)
    if scale < 0:
        u, inter = u[::-1], inter[:, ::-1]
        if cover is not None:
            cover = np.r_[np.cumsum(cover[:-1])[::-1]]
    elif cover is not None:
        cover = np.cumsum(cover[:-1])
    starts = np.flatnonzero(np.r_[True, np.diff(u) != 0])
    cols = slice(int(u[0]), int(u[0]) + len(starts))
    out = np.zeros((ny, width), np.float32)
    if use_max:
        out[:, cols] = np.maximum.reduceat(inter, starts, axis=1)
        return out
    sums = np.add.reduceat(inter, starts, axis=1)
    cnt = np.add.reduceat(cover, starts)
    with np.errstate(invalid='ignore', divide='ignore'):
        out[:, cols] = np.where(cnt > 0, sums / np.maximum(cnt, 1), 0)
    return out


def projection_width(nx: int, nz: int, zr: float) -> int:
    """Screen width that holds the volume at every angle."""
    return int(math.ceil(math.hypot(nx, nz * zr))) + 2


def project_3d(vol: np.ndarray, angle_deg: float = 0.0, axis: str = 'Y', z_ratio: float = 1.0,
               method: str = 'max', step: int = 1) -> np.ndarray:
    """(C, Z, Y, X) -> (C, H, W) float32: the volume turned by angle_deg about
    'Y' (left-right turn) or 'X' (up-down tilt) and projected along the view.

    z_ratio: Z slice spacing in XY pixels (voxel Z / pixel size), so the stack
    gets its true thickness. step: take every step-th XY pixel (fast preview).
    Pixels no voxel reaches are filled with the channel's minimum.
    At 0 degrees this equals the 2D projection with the same method.
    """
    vol = np.asarray(vol)
    if step > 1:
        vol = vol[:, :, ::step, ::step]
    zr = max(float(z_ratio), 1e-6) / step
    theta = math.radians(angle_deg)
    out = []
    for ch in vol:
        v = ch if axis == 'Y' else ch.transpose(0, 2, 1)  # X axis: turn the Y rows instead
        width = projection_width(v.shape[2], v.shape[0], zr)
        p = _turntable(v.astype(np.float32, copy=False), theta, zr, method, width)
        if axis != 'Y':
            p = p.T
        fill = float(np.nanmin(p)) if np.isfinite(p).any() else 0.0
        out.append(np.nan_to_num(p, nan=fill))
    return np.stack(out).astype(np.float32)


def z_ratio_from_metadata(image) -> float | None:
    """Z spacing in XY pixels from the voxel size, or None when unknown."""
    vz, vx = image.voxel_size_um.get('Z'), image.voxel_size_um.get('X')
    try:
        vz, vx = float(vz), float(vx)
    except (TypeError, ValueError):
        return None
    return vz / vx if vz > 0 and vx > 0 else None


@dataclass
class StackSettings:
    mode: str = '2d'  # '2d' or '3d'
    method_2d: str = 'max'
    method_3d: str = 'max'
    z0: int = 0  # first and last slice (inclusive) used
    z1: int = -1
    region: tuple | None = None  # (x0, y0, x1, y1) or None for the whole image
    angle: float = 0.0
    axis: str = 'Y'
    auto_spacing: bool = True
    spacing_um: float = 1.0  # manual Z spacing
    step: int = 1  # XY subsampling for the 3D preview

    def z_range(self, nz: int) -> tuple[int, int]:
        z1 = nz - 1 if self.z1 < 0 else min(self.z1, nz - 1)
        z0 = max(0, min(self.z0, z1))
        return z0, z1


class StackView:
    """A projection of one image with its own LUTs.

    Duck-types the parts of ImageItem the channel LUT panels use (channels,
    luts, planes(), value_range(), auto_lut()), so the same panels edit it.
    With ``linked`` its LUTs follow the image's LUTs (``pull``) and edits go
    back to them (``push``); a sum projection scales the range by the number
    of slices, a standard deviation keeps its own range.
    """

    def __init__(self, item: ImageItem):
        self.item = item
        self.settings = StackSettings()
        self.linked = True
        self.luts = [ChannelLUT(**vars(lut)) for lut in item.luts]
        self.result: np.ndarray | None = None
        self.result_key = None
        self.pixel_um = item.pixel_um
        self._synced = None
        # 3D preview structure, built once per image / Z range / crop / preview
        # size / timepoint (``build_3d``): the volume block-reduced to the
        # preview size, then (``refresh_3d``) LUT-mapped to uint8 and
        # interpolated to cubic voxels. Turning it only re-projects these few
        # MB; the full volume is released as soon as the structure exists.
        self.raw3d: np.ndarray | None = None  # (C, Z, Y', X') float32
        self.raw3d_key = None
        self.ref3d: np.ndarray | None = None  # (C, Y', X') max over Z, for the LUT panels
        self.iso3d: np.ndarray | None = None  # (C, Z', Y', X') uint8, LUT applied
        self.iso3d_key = None
        self.iso3d_luts = None  # (vmin, vmax, gamma) per channel baked into iso3d
        self._cols = {}  # (channel, axis) -> iso3d as contiguous (X, Y, Z) for steep angles

    @property
    def channels(self):
        return self.item.channels

    # ---- spacing ----------------------------------------------------------

    def z_ratio(self) -> float:
        st = self.settings
        if st.auto_spacing:
            return z_ratio_from_metadata(self.item.image) or 1.0
        px = self.item.pixel_um
        return st.spacing_um / px if px else st.spacing_um

    # ---- LUT link -----------------------------------------------------------

    def factor(self) -> float | None:
        """Projection value per raw value: n for a sum, None when unrelated (SD)."""
        st = self.settings
        if st.mode == '2d' and st.method_2d == 'sum':
            z0, z1 = st.z_range(self.item.nz)
            return float(z1 - z0 + 1)
        if st.mode == '2d' and st.method_2d == 'std':
            return None
        return 1.0

    def pull(self):
        """Copy the image's LUTs (scaled for a sum projection)."""
        f = self.factor()
        for i, src in enumerate(self.item.luts):
            dst = self.luts[i]
            dst.color, dst.gamma, dst.visible = tuple(src.color), src.gamma, src.visible
            if f is not None:
                dst.vmin, dst.vmax = src.vmin * f, src.vmax * f
            elif self.result is not None:
                dst.vmin, dst.vmax = auto_range(self.result[i])

    def sync(self) -> bool:
        """When linked, follow the image's LUTs; True if the LUTs were copied.

        A standard deviation has no matching range, so its LUT is only reset
        (auto) when the projection itself changes, not on every redraw.
        """
        if not self.linked:
            return False
        if self.factor() is None and self._synced == self.result_key:
            return False
        self.pull()
        self._synced = self.result_key
        return True

    def push(self):
        """Copy these LUTs back to the image (unscaled)."""
        f = self.factor()
        for src, dst in zip(self.luts, self.item.luts):
            dst.color, dst.gamma, dst.visible = tuple(src.color), src.gamma, src.visible
            if f:
                dst.vmin, dst.vmax = src.vmin / f, src.vmax / f

    # ---- computing --------------------------------------------------------

    def key(self):
        st = self.settings
        z0, z1 = st.z_range(self.item.nz)
        common = (self.item.t, z0, z1, st.region)
        if st.mode == '2d':
            return ('2d', st.method_2d) + common
        return ('3d', st.method_3d, round(st.angle, 3), st.axis, round(self.z_ratio(), 6),
                st.step) + common

    # ---- 3D structure -----------------------------------------------------

    def struct_key(self):
        st = self.settings
        z0, z1 = st.z_range(self.item.nz)
        return (self.item.t, z0, z1, st.region, st.step, st.method_3d)

    def build_3d(self):
        """Block-reduce the chosen stack to the preview size (max blocks for a
        brightest-point view, mean blocks for a mean view), then free the
        full volume of a lazy image."""
        st = self.settings
        vol = self.stack()
        s = st.step
        c, z, y, x = vol.shape
        sy, sx = min(s, y), min(s, x)
        yc, xc = y // sy * sy, x // sx * sx
        blocks = vol[:, :, :yc, :xc].reshape(c, z, yc // sy, sy, xc // sx, sx)
        if st.method_3d == 'max':
            raw = blocks.max(axis=(3, 5))
        else:
            raw = blocks.mean(axis=(3, 5), dtype=np.float32)
        self.raw3d = np.ascontiguousarray(raw, np.float32)
        self.ref3d = self.raw3d.max(axis=1)
        self.raw3d_key = self.struct_key()
        self.iso3d = None
        self.item.image.release()

    def lut_state(self):
        return [(lut.vmin, lut.vmax, lut.gamma) for lut in self.luts]

    def lut_stale(self) -> bool:
        """LUT range/gamma changed since the 3D structure was last refreshed."""
        return self.iso3d is not None and self.iso3d_luts != self.lut_state()

    def iso_key(self):
        return (self.raw3d_key, round(self.z_ratio() / self.settings.step, 6))

    def refresh_3d(self):
        """Apply the current LUTs (min, max, gamma) to the structure and
        interpolate its slices to the XY voxel size. Colors and visibility
        are applied when drawing, so they need no refresh."""
        raw = self.raw3d
        c, z, y, x = raw.shape
        zr = self.z_ratio() / self.settings.step
        nz = 1 if z == 1 else max(2, int(round((z - 1) * zr)) + 1)
        pos = np.linspace(0, z - 1, nz)
        iso = np.empty((c, nz, y, x), np.uint8)
        for i in range(c):
            n = self.luts[i].apply(raw[i]) * np.float32(255)  # (Z, Y', X') 0..255
            for k, p in enumerate(pos):
                j0 = int(p)
                w = p - j0
                sl = n[j0] if w < 1e-6 or j0 + 1 >= z else (1 - w) * n[j0] + w * n[j0 + 1]
                iso[i, k] = sl + np.float32(0.5)  # rounds on the cast to uint8
        self.iso3d = iso
        self._cols = {}
        self.iso3d_key = self.iso_key()
        self.iso3d_luts = self.lut_state()
        self.result_key = None

    def render_3d(self) -> np.ndarray:
        """(C, H, W) 0..1 (LUT already applied): the structure at the current angle."""
        st = self.settings
        theta = math.radians(st.angle)
        out = []
        for i, v in enumerate(self.iso3d):
            if st.axis != 'Y':
                v = v.transpose(0, 2, 1)

            def columns(i=i, v=v):
                key = (i, st.axis)
                if key not in self._cols:
                    self._cols[key] = np.ascontiguousarray(v.transpose(2, 1, 0))
                return self._cols[key]
            p = _shear_warp(v, theta, st.method_3d, columns)
            if st.axis != 'Y':
                p = p.T
            out.append(p / np.float32(255))
        return np.stack(out).astype(np.float32)

    def structure_mb(self) -> float:
        arrays = [self.raw3d, self.iso3d] + list(self._cols.values())
        return sum(a.nbytes for a in arrays if a is not None) / 1e6

    def stack(self) -> np.ndarray:
        """(C, Z, Y, X) of the chosen slices and region (loads the volume)."""
        st = self.settings
        z0, z1 = st.z_range(self.item.nz)
        vol = self.item.image.data[:, z0:z1 + 1]
        if st.region is not None:
            x0, y0, x1, y1 = st.region
            vol = vol[:, :, y0:y1, x0:x1]
        return vol

    def compute(self, step: int | None = None, angle: float | None = None) -> np.ndarray:
        """The projection for the current settings; cached when unchanged.

        step / angle override the settings (full-resolution export, rotation
        series) without touching the cache.
        """
        st = self.settings
        override = step is not None or angle is not None
        key = self.key()
        if not override and self.result is not None and key == self.result_key:
            return self.result
        px = self.item.pixel_um
        if st.mode == '3d' and not override:
            if self.raw3d_key != self.struct_key():
                self.build_3d()
            if self.iso3d is None or self.iso3d_key != self.iso_key():
                self.refresh_3d()
            res = self.render_3d()
            self.result, self.result_key = res, key
            self.pixel_um = px * st.step if px else None
            return res
        vol = self.stack()
        if st.mode == '2d':
            res, pix = project_2d(vol, st.method_2d), px
        else:
            s = st.step if step is None else step
            res = project_3d(vol, st.angle if angle is None else angle, st.axis,
                             self.z_ratio(), st.method_3d, s)
            pix = px * s if px else None
        if override:
            return res
        self.result, self.result_key, self.pixel_um = res, key, pix
        return res

    # ---- what the LUT panels use -----------------------------------------

    def planes(self) -> np.ndarray:
        if self.settings.mode == '3d' and self.ref3d is not None:
            return self.ref3d  # LUT panels show the raw values, not the LUT-mapped view
        return self.result if self.result is not None else self.item.planes()

    def value_range(self, index: int) -> tuple[float, float, str]:
        lo, hi, note = self.item.value_range(index)
        f = self.factor()
        if f is None:
            lo, hi, note = 0.0, 0.0, ''
        elif f != 1:
            lo, hi, note = lo * f, hi * f, f'{note} × {f:.0f}' if note else ''
        p = self.planes()[index]
        dlo, dhi = float(np.nanmin(p)), float(np.nanmax(p))
        lo, hi = min(lo, dlo), max(hi, dhi)
        return lo, (hi if hi > lo else lo + 1.0), note

    def auto_lut(self, index: int, low=0.5, high=99.8):
        self.luts[index].vmin, self.luts[index].vmax = auto_range(self.planes()[index], low, high)

    def composite(self, planes: np.ndarray | None = None, lut_applied: bool = False) -> np.ndarray:
        """RGB of raw projected values, or of a 3D preview whose LUT is
        already applied (``lut_applied``: only color and visibility)."""
        planes = self.planes() if planes is None else planes
        rgb = np.zeros(planes.shape[1:] + (3,), np.float32)
        for plane, lut in zip(planes, self.luts):
            if lut.visible:
                add_colored(rgb, plane if lut_applied else lut.apply(plane), lut.color)
        return np.clip(rgb, 0.0, 1.0, out=rgb)

    def preview_rgb(self) -> np.ndarray:
        """The current projection as RGB (3D: from the cached structure)."""
        res = self.compute()
        return self.composite(res, lut_applied=self.settings.mode == '3d')

    def decorate(self, rgb, scale: ScaleBarStyle | None, time: TimeStampStyle | None,
                 pixel_um: float | None = None, t: int | None = None) -> np.ndarray:
        if scale is not None:
            rgb = scale.draw(rgb, self.pixel_um if pixel_um is None else pixel_um)
        if time is not None and self.item.nt > 1:
            rgb = time.draw(rgb, self.item.image.times, self.item.t if t is None else t)
        return rgb

    def describe(self) -> str:
        st = self.settings
        z0, z1 = st.z_range(self.item.nz)
        if st.mode == '2d':
            return f'{METHODS_2D[st.method_2d]}, z {z0 + 1}–{z1 + 1}'
        return (f'3D {METHODS_3D[st.method_3d]}, {st.axis}축 {st.angle:.0f}°, '
                f'Z 간격 ×{self.z_ratio():.2f} px, z {z0 + 1}–{z1 + 1}')


def export_projection(view: StackView, path_stem, scale=None, time=None, all_times=False,
                      full_res=True, progress=None, movie_fps=None) -> list[str]:
    """Write <stem>_composite.tif (RGB with LUTs and markers) and <stem>_raw.tif
    (float32 ImageJ stack of the projected values, carrying the LUTs).

    all_times: one frame per timepoint. full_res: a 3D projection at full XY
    resolution instead of the preview step. progress(i, n) -> False cancels.
    movie_fps: write the frames as <stem>.mp4 at this frame rate instead
    (only when there are several frames; a single frame stays TIFF).
    """
    import tifffile

    from .lut import _imagej_luts

    item = view.item
    times = list(range(item.nt)) if all_times and item.nt > 1 else [item.t]
    step = 1 if full_res else view.settings.step  # always from the volume, raw values
    start_t = item.t
    rgb_frames, raw_frames = [], []
    pix = view.pixel_um
    try:
        for k, t in enumerate(times):
            if progress is not None and progress(k, len(times)) is False:
                break
            item.set_t(t)
            res = view.compute(step=step)
            if view.settings.mode == '3d':
                px = item.pixel_um
                pix = px * (step or view.settings.step) if px else None
            rgb = view.decorate(view.composite(res), scale, time, pixel_um=pix, t=t)
            rgb_frames.append((np.clip(rgb, 0, 1) * 255).astype(np.uint8))
            raw_frames.append(res)
    finally:
        item.set_t(start_t)
    return _write_projection(view, path_stem, rgb_frames, raw_frames, pix, len(times) > 1,
                             tifffile, _imagej_luts, movie_fps=movie_fps)


def export_rotation(view: StackView, path_stem, angles, scale=None, time=None, full_res=True,
                    progress=None, movie_fps=None) -> list[str]:
    """3D projection at every angle in ``angles`` as one RGB (and raw) stack."""
    import tifffile

    from .lut import _imagej_luts

    item = view.item
    step = 1 if full_res else view.settings.step
    px = item.pixel_um
    pix = px * step if px else None
    rgb_frames, raw_frames = [], []
    for k, a in enumerate(angles):
        if progress is not None and progress(k, len(angles)) is False:
            break
        res = view.compute(step=step, angle=float(a))
        rgb = view.decorate(view.composite(res), scale, time, pixel_um=pix)
        rgb_frames.append((np.clip(rgb, 0, 1) * 255).astype(np.uint8))
        raw_frames.append(res)
    return _write_projection(view, path_stem, rgb_frames, raw_frames, pix, len(rgb_frames) > 1,
                             tifffile, _imagej_luts, frame_axis='Z', movie_fps=movie_fps)


def _write_projection(view, path_stem, rgb_frames, raw_frames, pix, series, tifffile, luts_fn,
                      frame_axis='T', movie_fps=None):
    from pathlib import Path

    if not rgb_frames:
        return []
    item = view.item
    stem = str(path_stem)
    Path(stem).parent.mkdir(parents=True, exist_ok=True)
    if movie_fps and series:
        from .movie import write_mp4
        return [write_mp4(f'{stem}.mp4', rgb_frames, movie_fps)]
    res = (1.0 / pix, 1.0 / pix) if pix else None
    meta = {'unit': 'um'} if pix else {}
    meta.update(item.id_metadata())
    meta['Info'] += f'\nprojection = {view.describe()}'
    rgb_meta = dict(meta)
    if series:
        rgb_meta['axes'] = f'{frame_axis}YXS'
    rgb_path = f'{stem}_composite.tif'
    tifffile.imwrite(rgb_path, np.stack(rgb_frames) if series else rgb_frames[0],
                     photometric='rgb', resolution=res, metadata=rgb_meta, imagej=True)
    raw = np.stack(raw_frames) if series else raw_frames[0]  # (N, C, Y, X) or (C, Y, X)
    raw_meta = dict(meta, axes=f'{frame_axis}CYX' if series else 'CYX', mode='composite',
                    LUTs=luts_fn(view), Labels=list(item.channels),
                    Ranges=tuple(v for lut in view.luts for v in (lut.vmin, lut.vmax)))
    raw_path = f'{stem}_raw.tif'
    tifffile.imwrite(raw_path, raw.astype(np.float32), resolution=res, metadata=raw_meta,
                     imagej=True)
    return [rgb_path, raw_path]
