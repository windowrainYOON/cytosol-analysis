"""Line intensity profiles (ImageJ's line profile / RGB Profiler, on the raw channel values).

GUI-independent: the profile tab of the app and scripts both use this.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class Profile:
    distance: np.ndarray        # (N,) along the line, in µm (or px without calibration)
    values: np.ndarray          # (C, N) mean raw value across the line width
    channels: list[str]
    unit: str                   # 'µm' or 'px'
    line: tuple                 # (x0, y0, x1, y1) in image pixels
    width: int

    @property
    def length(self) -> float:
        """Length of the line (µm or px); samples are 1 px apart, so
        distance[-1] is that length rounded to whole pixels."""
        x0, y0, x1, y1 = self.line
        scale = float(self.distance[1] - self.distance[0]) if len(self.distance) > 1 else 1.0
        return float(np.hypot(x1 - x0, y1 - y0)) * scale


def _java_round(x: float) -> int:
    return int(math.floor(x + 0.5))


def interpolated_value(plane: np.ndarray, x, y) -> np.ndarray:
    """ImageProcessor.getInterpolatedValue: bilinear, pixel centers at integer
    coordinates, edge pixels repeated up to one pixel outside, 0 beyond."""
    h, w = plane.shape
    x = np.asarray(x, np.float64)
    y = np.asarray(y, np.float64)
    xb = np.trunc(x).astype(np.int64)  # Java (int): toward zero
    yb = np.trunc(y).astype(np.int64)
    fx = np.maximum(x - xb, 0.0)
    fy = np.maximum(y - yb, 0.0)
    x0, x1 = np.clip(xb, 0, w - 1), np.clip(xb + 1, 0, w - 1)
    y0, y1 = np.clip(yb, 0, h - 1), np.clip(yb + 1, 0, h - 1)
    p = plane.astype(np.float64, copy=False)
    ll, lr = p[y0, x0], p[y0, x1]
    ul, ur = p[y1, x0], p[y1, x1]
    upper = ul + fx * (ur - ul)
    lower = ll + fx * (lr - ll)
    v = lower + fy * (upper - lower)
    outside = (x < -1.0) | (x >= w) | (y < -1.0) | (y >= h)
    return np.where(outside, 0.0, v)


def _imagej_samples(shape, line, width):
    """Sample points of ImageJ's straight-line profile (ProfilePlot / Line.getPixels).

    width 1: ImageProcessor.getLine, round(length) + 1 points (the step is
    length / round(length)). Wider: Straightener.straightenLine, points 1 px
    apart along the line (round(length) + 1 of them) and, at each, ``width``
    points 1 px apart across it; their values are averaged.
    Returns (xs, ys) of shape (N,) or (N, width).
    """
    h, w = shape
    x1, y1, x2, y2 = line
    if width <= 1:
        dx, dy = x2 - x1, y2 - y1
        n = _java_round(math.sqrt(dx * dx + dy * dy))
        xinc = dx / n if n > 0 else 0.0
        yinc = dy / n if n > 0 else 0.0
        if not ((xinc == 0 and n == h) or (yinc == 0 and n == w)):
            n += 1
        # rx += xinc, accumulated like the Java loop
        xs = np.cumsum(np.r_[x1, np.full(max(n - 1, 0), xinc)])[:n]
        ys = np.cumsum(np.r_[y1, np.full(max(n - 1, 0), yinc)])[:n]
        return xs, ys
    # Line -> 2-point polyline (float coordinates) -> points 1 px apart
    fx1, fy1, fx2, fy2 = (float(np.float32(v)) for v in line)
    length = math.hypot(fx2 - fx1, fy2 - fy1)
    npts = _java_round(length) + 1
    step = length / (npts - 1) if npts > 1 else 0.0
    t = np.arange(npts) * step / length if length > 0 else np.zeros(npts)
    px = (fx1 + t * (fx2 - fx1)).astype(np.float32).astype(np.float64)
    py = (fy1 + t * (fy2 - fy1)).astype(np.float32).astype(np.float64)
    # the point before each one (the first extrapolated back one step)
    prev_x = np.r_[px[0] - (px[1] - px[0]) if npts > 1 else px[0], px[:-1]]
    prev_y = np.r_[py[0] - (py[1] - py[0]) if npts > 1 else py[0], py[:-1]]
    dx = px - prev_x
    dy = prev_y - py
    seg = np.sqrt(dx * dx + dy * dy).astype(np.float32).astype(np.float64)
    with np.errstate(all='ignore'):
        dx, dy = dx / seg, dy / seg
    j = np.arange(width)
    xs = (px - dy * (width - 1) / 2.0)[:, None] + dy[:, None] * j[None, :]
    ys = (py - dx * (width - 1) / 2.0)[:, None] + dx[:, None] * j[None, :]
    return xs, ys


def line_profile(planes: np.ndarray, line, width: int = 1, pixel_um: float | None = None,
                 channels=None) -> Profile:
    """Sample every channel of (C, Y, X) planes along line = (x0, y0, x1, y1).

    Same samples and values as ImageJ's line profile (Analyze > Plot Profile,
    the profile RGB Profiler draws per channel): bilinear interpolation with
    pixel centers at integer coordinates, round(length) + 1 points, and for
    width > 1 the mean of ``width`` points across the line at each position.
    Distances are i x pixel size, as on ImageJ's plot.
    """
    x0, y0, x1, y1 = (float(v) for v in line)
    width = max(int(width), 1)
    planes = np.asarray(planes)
    rows = []
    if len(planes):
        xs, ys = _imagej_samples(planes.shape[-2:], (x0, y0, x1, y1), width)
        for plane in planes:
            v = interpolated_value(np.asarray(plane, np.float32), xs, ys)
            if v.ndim == 2:
                with np.errstate(all='ignore'):
                    v = np.nanmean(v, axis=1)
            rows.append(v)
    values = np.stack(rows) if rows else np.zeros((0, 0), np.float64)
    n = values.shape[1] if values.ndim == 2 else 0
    scale = pixel_um if pixel_um else 1.0
    distance = np.arange(n) * scale
    names = list(channels) if channels is not None else [f'C{i}' for i in range(len(rows))]
    return Profile(distance, values, names, 'µm' if pixel_um else 'px',
                   (x0, y0, x1, y1), width)


def write_profile_csv(path, prof: Profile, extra: dict | None = None) -> str:
    """distance column plus one column per channel; a few '#' header lines."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    unit = 'um' if prof.unit == 'µm' else 'px'
    with path.open('w', newline='', encoding='utf-8') as f:
        x0, y0, x1, y1 = prof.line
        f.write(f'# line_px = ({x0:.1f}, {y0:.1f}) -> ({x1:.1f}, {y1:.1f}), '
                f'width_px = {prof.width}, length_{unit} = {prof.length:.4g}\n')
        for k, v in (extra or {}).items():
            f.write(f'# {k} = {v}\n')
        w = csv.writer(f)
        w.writerow([f'distance_{unit}'] + list(prof.channels))
        for j, d in enumerate(prof.distance):
            w.writerow([f'{d:.5g}'] + [f'{prof.values[c, j]:.6g}'
                                       for c in range(len(prof.channels))])
    return str(path)


def plot_color(color) -> tuple:
    """A channel color that shows on a white plot (white/near-white -> dark gray)."""
    r, g, b = (float(c) for c in color)
    if 0.299 * r + 0.587 * g + 0.114 * b > 0.85:
        return (0.25, 0.25, 0.25)
    return (r, g, b)


def draw_profile(ax, prof: Profile, colors, visible=None, normalize=False):
    """Plot the profile on a matplotlib Axes (one line per channel, channel colors)."""
    ax.clear()
    for c, name in enumerate(prof.channels):
        if visible is not None and not visible[c]:
            continue
        y = prof.values[c]
        if normalize:
            lo, hi = float(np.nanmin(y)), float(np.nanmax(y))
            y = (y - lo) / (hi - lo) if hi > lo else y * 0
        ax.plot(prof.distance, y, color=plot_color(colors[c]), lw=1.2, label=name)
    ax.set_xlabel(f'Distance ({"microns" if prof.unit == "µm" else "pixels"})')
    ax.set_ylabel('Normalized intensity' if normalize else 'Intensity')
    if len(prof.distance):
        ax.set_xlim(0, prof.distance[-1])
    ax.grid(True, color='0.85', lw=0.6)
    if ax.lines:
        ax.legend(fontsize=8, frameon=False, loc='best')


def line_roi(prof: Profile, name: str = 'profile', properties: dict | None = None):
    """The profile line as an ImageJ straight-line ROI (subpixel coordinates,
    stroke width = line width), so File > Open in ImageJ gives the same profile."""
    import roifile

    x0, y0, x1, y1 = (float(v) for v in prof.line)
    roi = roifile.ImagejRoi()
    roi.roitype = roifile.ROI_TYPE.LINE
    roi.options |= roifile.ROI_OPTIONS.SUB_PIXEL_RESOLUTION
    roi.x1, roi.y1, roi.x2, roi.y2 = x0, y0, x1, y1
    roi.left, roi.top = int(math.floor(min(x0, x1))), int(math.floor(min(y0, y1)))
    roi.right = int(math.floor(max(x0, x1))) + 1
    roi.bottom = int(math.floor(max(y0, y1))) + 1
    roi.stroke_width = int(prof.width) if prof.width > 1 else 0
    roi.name = name
    if properties:
        roi.properties = {str(k): str(v) for k, v in properties.items()}
    return roi


def write_line_roi(path, prof: Profile, name: str = 'profile',
                   properties: dict | None = None) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line_roi(prof, name, properties).tofile(path)
    return str(path)


def read_line_roi(path):
    """(x0, y0, x1, y1), width of a .roi file holding one straight line; None otherwise."""
    import roifile

    path = Path(path)
    if path.suffix.lower() != '.roi':
        return None
    try:
        r = roifile.ImagejRoi.fromfile(path)
    except Exception:
        return None
    if isinstance(r, list) or r.roitype != roifile.ROI_TYPE.LINE:
        return None
    return (float(r.x1), float(r.y1), float(r.x2), float(r.y2)), max(int(r.stroke_width), 1)


def line_overlay(rgb: np.ndarray, line, width: int = 1, color=(255, 220, 0),
                 min_size: int = 1000) -> np.ndarray:
    """uint8 RGB image (0..1 float or uint8 in) with the profile line drawn on it.

    Small images are enlarged (nearest neighbour, whole factor) so the long side
    is at least ``min_size`` px and the line stays thin; a width > 1 line also
    gets its band outline, as on the canvas.
    """
    from PIL import Image, ImageDraw

    a = np.asarray(rgb)
    if a.dtype != np.uint8:
        a = (np.clip(a, 0.0, 1.0) * 255 + 0.5).astype(np.uint8)
    h, w = a.shape[:2]
    s = max(1, -(-min_size // max(h, w)))  # ceil
    im = Image.fromarray(a, 'RGB')
    if s > 1:
        im = im.resize((w * s, h * s), Image.NEAREST)
    draw = ImageDraw.Draw(im)
    lw = max(2, round(max(im.size) / 600))
    x0, y0, x1, y1 = (float(v) * s for v in line)
    length = math.hypot(x1 - x0, y1 - y0)
    if width > 1 and length > 0:
        half = width * s / 2
        nx, ny = -(y1 - y0) / length * half, (x1 - x0) / length * half
        band = [(x0 + nx, y0 + ny), (x1 + nx, y1 + ny), (x1 - nx, y1 - ny), (x0 - nx, y0 - ny)]
        draw.line(band + band[:1], fill=color, width=max(1, lw // 2))
    draw.line([(x0, y0), (x1, y1)], fill=color, width=lw)
    return np.asarray(im)
