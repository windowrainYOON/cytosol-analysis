"""3D 투영 (canvas icon, v0.73): volumes prepared once, then turned in real time.

GUI-independent parts of the 3D view (owner request 2026-11-23/24, pipeline
design v3.10):

* ``frame_volume`` turns one timepoint's (C, Z, Y, X) stack into a LUT-applied
  uint8 volume at the render resolution with cubic voxels (Z interpolated by
  the Z spacing), the only thing the renderers read;
* ``VolumeCache`` prepares those volumes for every timepoint of a series in a
  background thread, the current one first and then outward on both sides,
  keeps them in RAM up to a budget and spills the rest to a disk cache;
* ``Trackball`` keeps the 3-axis rotation (drag = trackball, Shift = screen
  axis) and the X / Y / Z angles shown on the chip;
* ``render_cpu`` is the numpy ray caster used when OpenGL is missing
  (offscreen self-test, old GPUs): a reduced image while dragging, the exact
  one on release. ``gl3d.GLVolumeView`` draws the same volume on the GPU.
"""

from __future__ import annotations

import math
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field

import numpy as np

METHODS = {'mip': '최대 밝기 (MIP)', 'alpha': '반투명 (방출-흡수)', 'surface': '표면'}


@dataclass
class View3DSettings:
    """Preferences › 3D 스택 보기 (QSettings ``view3d/*``)."""
    method: str = 'mip'  # mip / alpha / surface
    prerender: str = 'on_open'  # on_open (when the icon is turned on) / on_load
    resolution: int = 2  # XY step of the prepared volume: 1 = full, 2 = half, 3 = third
    auto_spacing: bool = True
    spacing_um: float = 1.0
    rotation: str = 'free'  # free (trackball) / axis (one axis, Y)
    crop_only: bool = False  # unused since v0.75 (crop view from the sidebar); kept for old settings
    lut_link: bool = True
    memory_gb: float = 2.0
    surface_level: float = 0.35
    opacity: float = 1.0

    def to_dict(self) -> dict:
        return dict(vars(self))

    @classmethod
    def from_dict(cls, d: dict | None) -> 'View3DSettings':
        out = cls()
        for k, v in (d or {}).items():
            if hasattr(out, k):
                try:
                    setattr(out, k, type(getattr(out, k))(v))
                except (TypeError, ValueError):
                    pass
        return out


def z_ratio(image, settings: View3DSettings, pixel_um=None) -> float:
    """Z spacing in XY pixels (metadata when automatic)."""
    if settings.auto_spacing:
        vz, vx = image.voxel_size_um.get('Z'), image.voxel_size_um.get('X')
        try:
            vz, vx = float(vz), float(vx)
            if vz > 0 and vx > 0:
                return vz / vx
        except (TypeError, ValueError):
            pass
        return 1.0
    px = pixel_um or image.voxel_size_um.get('X')
    try:
        return float(settings.spacing_um) / float(px)
    except (TypeError, ValueError, ZeroDivisionError):
        return float(settings.spacing_um)


def read_stack(image, t: int) -> np.ndarray:
    """(C, Z, Y, X) of timepoint t without changing the image's current t."""
    if image.loader is None:
        return image.data
    if t == image.t and image.volume_loaded:
        return image.data
    return image.loader(int(t))  # never touches the image's own cached volume


def frame_volume(stack: np.ndarray, luts, step: int = 2, zr: float = 1.0,
                 region=None, max_z: int = 512) -> np.ndarray:
    """LUT-applied uint8 volume (C, Z', Y', X') with cubic voxels.

    XY is block-averaged by ``step``; Z is resampled so one voxel step along Z
    equals one along X (``zr`` = Z spacing in XY pixels). Colours and
    visibility are applied when drawing, so only min / max / gamma are baked in.
    """
    vol = np.asarray(stack)
    if region is not None:
        x0, y0, x1, y1 = (int(v) for v in region)
        vol = vol[:, :, y0:y1, x0:x1]
    c, nz, ny, nx = vol.shape
    s = max(1, int(step))
    sy, sx = min(s, ny), min(s, nx)
    yc, xc = ny // sy * sy, nx // sx * sx
    out_z = 1 if nz == 1 else int(min(max_z, max(2, round((nz - 1) * zr / s) + 1)))
    pos = np.linspace(0, nz - 1, out_z)
    res = np.empty((c, out_z, yc // sy, xc // sx), np.uint8)
    for i in range(c):
        blk = vol[i, :, :yc, :xc].astype(np.float32, copy=False)
        if s > 1:
            blk = blk.reshape(nz, yc // sy, sy, xc // sx, sx).mean(axis=(2, 4), dtype=np.float32)
        n = luts[i].apply(blk) * np.float32(255)
        for k, p in enumerate(pos):
            j0 = int(p)
            w = p - j0
            sl = n[j0] if w < 1e-6 or j0 + 1 >= nz else (1 - w) * n[j0] + w * n[j0 + 1]
            res[i, k] = sl + np.float32(0.5)
    return res


def lut_key(luts) -> tuple:
    return tuple((round(float(lut.vmin), 6), round(float(lut.vmax), 6), round(float(lut.gamma), 4))
                 for lut in luts)


# ---------------------------------------------------------------------------
# rotation
# ---------------------------------------------------------------------------

def _axis_angle(axis, ang) -> np.ndarray:
    x, y, z = np.asarray(axis, float) / (np.linalg.norm(axis) or 1.0)
    c, s = math.cos(ang), math.sin(ang)
    C = 1 - c
    return np.array([[c + x * x * C, x * y * C - z * s, x * z * C + y * s],
                     [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
                     [z * x * C - y * s, z * y * C + x * s, c + z * z * C]])


def euler_xyz(R: np.ndarray) -> tuple[float, float, float]:
    """Angles (deg) of R = Rz · Ry · Rx, for the angle chip."""
    sy = -R[2, 0]
    y = math.asin(max(-1.0, min(1.0, sy)))
    if abs(sy) < 0.9999:
        x = math.atan2(R[2, 1], R[2, 2])
        z = math.atan2(R[1, 0], R[0, 0])
    else:
        x = math.atan2(-R[1, 2], R[1, 1])
        z = 0.0
    return math.degrees(x), math.degrees(y), math.degrees(z)


def from_euler(x, y, z) -> np.ndarray:
    return (_axis_angle((0, 0, 1), math.radians(z)) @ _axis_angle((0, 1, 0), math.radians(y))
            @ _axis_angle((1, 0, 0), math.radians(x)))


@dataclass
class Trackball:
    """View rotation (volume → screen). Drag = trackball about the axis
    perpendicular to the drag in the screen plane, so every direction turns
    all three axes together; ``screen_axis`` turns about the view axis only;
    ``one_axis`` (Preferences › 회전 = 한 축) turns about the screen Y only."""
    R: np.ndarray = field(default_factory=lambda: np.eye(3))
    zoom: float = 1.0
    pan: tuple = (0.0, 0.0)
    one_axis: bool = False
    deg_per_px: float = 0.5

    def drag(self, dx: float, dy: float, screen_axis: bool = False):
        if not dx and not dy:
            return
        if screen_axis:
            rot = _axis_angle((0, 0, 1), math.radians(-dx * self.deg_per_px))
        elif self.one_axis:
            rot = _axis_angle((0, 1, 0), math.radians(dx * self.deg_per_px))
        else:
            ang = math.radians(math.hypot(dx, dy) * self.deg_per_px)
            rot = _axis_angle((dy, dx, 0.0), ang)  # screen y points down
        self.R = rot @ self.R
        # keep it orthonormal over many small turns
        u, _s, vt = np.linalg.svd(self.R)
        self.R = u @ vt

    def reset(self):
        self.R = np.eye(3)
        self.zoom = 1.0
        self.pan = (0.0, 0.0)

    def angles(self) -> tuple[float, float, float]:
        return euler_xyz(self.R)

    def chip(self) -> str:
        x, y, z = self.angles()
        return f'X {x:.0f}° Y {y:.0f}° Z {z:.0f}°'.replace('-', '−')


# ---------------------------------------------------------------------------
# CPU ray caster
# ---------------------------------------------------------------------------

def render_cpu(vol: np.ndarray, R: np.ndarray, size: tuple[int, int], method: str = 'mip',
               visible=None, colors=None, zoom: float = 1.0, pan=(0.0, 0.0), samples: int | None = None,
               level: float = 0.35, fast: bool = False) -> np.ndarray:
    """(H, W, 3) float32 RGB of the uint8 volume (C, Z, Y, X) seen through R.

    Orthographic rays along the screen Z; the volume fits the shorter side at
    zoom 1. ``fast`` uses nearest samples and fewer of them (while dragging).
    """
    from scipy.ndimage import map_coordinates

    c, nz, ny, nx = vol.shape
    w, h = int(size[0]), int(size[1])
    ext = np.array([nx, ny, nz], float)  # volume x, y, z
    diag = float(np.linalg.norm(ext))
    scale = diag / (min(w, h) * zoom)  # voxels per screen pixel
    if samples is None:
        samples = int(min(diag, 384 if not fast else 96))
    samples = max(8, samples)
    us = (np.arange(w) - (w - 1) / 2 - pan[0]) * scale
    vs = (np.arange(h) - (h - 1) / 2 - pan[1]) * scale
    ws = np.linspace(-diag / 2, diag / 2, samples)
    Rt = np.asarray(R, float).T  # screen → volume
    # screen (u right, v down, w into the screen) → volume axes (x, y, z)
    U, V = np.meshgrid(us, vs)
    base = (Rt[:, 0:1] * U.ravel() + Rt[:, 1:2] * V.ravel())  # (3, H*W)
    centre = (ext - 1) / 2
    out = np.zeros((h, w, 3), np.float32)
    visible = [True] * c if visible is None else visible
    colors = [(1, 1, 1)] * c if colors is None else colors
    order = 0 if fast else 1
    for i in range(c):
        if not visible[i]:
            continue
        v = vol[i]
        acc = np.zeros(h * w, np.float32)
        trans = np.ones(h * w, np.float32) if method == 'alpha' else None
        hit = np.zeros(h * w, bool) if method == 'surface' else None
        # step along the ray in chunks (bounded memory)
        chunk = max(1, int(4e6 // (h * w)))
        for k0 in range(0, samples, chunk):
            wk = ws[k0:k0 + chunk]
            pts = base[:, None, :] + Rt[:, 2:3, None] * wk[None, :, None]  # (3, k, HW)
            coords = np.stack([pts[2] + centre[2], pts[1] + centre[1], pts[0] + centre[0]])
            vals = map_coordinates(v, coords.reshape(3, -1), order=order, mode='constant',
                                   cval=0, prefilter=False).reshape(len(wk), -1)
            vals = vals.astype(np.float32) / np.float32(255)
            if method == 'mip':
                np.maximum(acc, vals.max(axis=0), out=acc)
            elif method == 'alpha':
                for row in vals:  # front (w = -diag/2) to back
                    a = row * np.float32(0.08 * diag / samples)
                    a = np.minimum(a, 1)
                    acc += trans * a * row * 4
                    trans *= 1 - a
            else:  # surface: first sample above the level, shaded by depth
                for j, row in enumerate(vals):
                    new = (row >= level) & ~hit
                    if new.any():
                        depth = 1 - (k0 + j) / samples
                        acc[new] = 0.35 + 0.65 * depth
                        hit |= new
        acc = np.clip(acc, 0, 1).reshape(h, w)
        col = colors[i]
        for k in range(3):
            if col[k]:
                out[..., k] += acc * np.float32(col[k])
    return np.clip(out, 0, 1, out=out)


# ---------------------------------------------------------------------------
# every timepoint prepared once
# ---------------------------------------------------------------------------

def frame_order(t: int, nt: int) -> list[int]:
    """Current timepoint first, then outward on both sides."""
    order = [t]
    for d in range(1, nt):
        for k in (t + d, t - d):
            if 0 <= k < nt:
                order.append(k)
    return order


class VolumeCache:
    """Prepared volumes of one image (all timepoints), built in the background.

    ``key`` = everything baked into a volume (LUTs, step, Z spacing, region);
    a new key drops the old volumes and starts again from ``t``. Volumes over
    ``memory_gb`` are written to ``cache_dir`` (``.cycache``) and read back as
    memory maps.
    """

    def __init__(self, image, cache_dir: str | None = None):
        self.image = image
        self.frames: dict[int, np.ndarray] = {}
        self.key = None
        self.nt = max(1, image.nt)
        self.done = 0
        self.error = None
        self.cache_dir = cache_dir
        self._disk: dict[int, str] = {}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.started = 0.0
        self.finished = 0.0
        self.bytes = 0
        self.memory = 2e9
        self._gen = 0

    # --- state -----------------------------------------------------------

    def get(self, t: int) -> np.ndarray | None:
        with self._lock:
            v = self.frames.get(t)
            if v is None and t in self._disk:
                v = np.load(self._disk[t], mmap_mode='r')
            return v

    def frame_shape(self):
        for t in range(self.nt):
            v = self.get(t)
            if v is not None:
                return v.shape
        return None

    def progress(self) -> tuple[int, int]:
        return self.done, self.nt

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def chip(self) -> str:
        d, n = self.progress()
        if self.error:
            return f'렌더 실패: {self.error}'
        if d >= n:
            return '고화질 렌더 완료' if n == 1 else f'모든 시점 준비 완료 · 프레임 {n}'
        pct = int(round(100 * d / n)) if n else 0
        if n == 1:
            return '고화질 렌더 중'
        return f'모든 시점 미리 렌더 중 · 프레임 {d} / {n} ({pct} %)'

    # --- building --------------------------------------------------------

    def stop(self):
        """Stop the background build (does not wait: a frame still being built
        by the old thread is dropped by its generation)."""
        self._stop.set()
        self._gen = getattr(self, '_gen', 0) + 1
        self._thread = None

    def start(self, t: int, luts, step: int, zr: float, region=None, memory_gb: float = 2.0,
              sync_first: bool = True):
        """Prepare every timepoint for these settings; the current one
        synchronously when ``sync_first`` (so it can be shown at once)."""
        key = (lut_key(luts), int(step), round(float(zr), 5), tuple(region) if region else None)
        if key == self.key and (self.running() or self.done >= self.nt):
            if sync_first and self.get(t) is None:
                self._build(t, luts, step, zr, region, self._gen)
            return
        self.stop()
        with self._lock:
            self.frames = {}
            self._disk = {}
            self.bytes = 0
        self.key = key
        self.done = 0
        self.error = None
        self.memory = float(memory_gb) * 1e9
        self._stop = threading.Event()
        self.started = time.perf_counter()
        luts = [type(lut)(**vars(lut)) for lut in luts]  # frozen copy for the thread
        order = frame_order(int(t), self.nt)
        gen = self._gen
        if sync_first:
            try:
                self._build(order[0], luts, step, zr, region, gen)
            except Exception as exc:  # noqa: BLE001
                self.error = str(exc)
                return
            order = order[1:]
        if not order:
            self.finished = time.perf_counter()
            return
        stop = self._stop

        def work():
            for k in order:
                if stop.is_set():
                    return
                try:
                    self._build(k, luts, step, zr, region, gen)
                except Exception as exc:  # noqa: BLE001
                    self.error = str(exc)
                    return
            self.finished = time.perf_counter()

        self._thread = threading.Thread(target=work, name='vol3d-prerender', daemon=True)
        self._thread.start()

    def _build(self, t, luts, step, zr, region, gen=None):
        if gen is None:
            gen = getattr(self, '_gen', 0)
        if self.get(t) is not None:
            return
        stack = read_stack(self.image, t)
        v = frame_volume(stack, luts, step, zr, region)
        del stack
        with self._lock:
            if gen != getattr(self, '_gen', 0):
                return  # settings changed while this frame was built
            if self.bytes + v.nbytes > self.memory and self.nt > 1:
                d = self.cache_dir or os.path.join(tempfile.gettempdir(), 'cytosol.cycache')
                os.makedirs(d, exist_ok=True)
                path = os.path.join(d, f'vol_{id(self)}_{t}.npy')
                np.save(path, v)
                self._disk[t] = path
            else:
                self.frames[t] = v
                self.bytes += v.nbytes
            self.done += 1

    def wait(self, timeout: float = 600):
        th = self._thread
        if th is not None:
            th.join(timeout)

    def clear(self):
        self.stop()
        with self._lock:
            for p in self._disk.values():
                try:
                    os.remove(p)
                except OSError:
                    pass
            self.frames, self._disk = {}, {}
            self.bytes = 0
        self.key = None
        self.done = 0
