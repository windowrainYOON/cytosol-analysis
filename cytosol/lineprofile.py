"""Line intensity profiles (like ImageJ's RGB Profiler, on the raw channel values).

GUI-independent: the profile tab of the app and scripts both use this.
"""

from __future__ import annotations

import csv
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
        return float(self.distance[-1]) if len(self.distance) else 0.0


def line_profile(planes: np.ndarray, line, width: int = 1, pixel_um: float | None = None,
                 channels=None) -> Profile:
    """Sample every channel of (C, Y, X) planes along line = (x0, y0, x1, y1).

    One sample per pixel of length (end points included), bilinear
    interpolation; width > 1 averages that many pixels perpendicular to the
    line, as ImageJ does for a wide line.
    """
    from skimage.measure import profile_line

    x0, y0, x1, y1 = (float(v) for v in line)
    width = max(int(width), 1)
    rows = []
    for plane in planes:
        rows.append(profile_line(np.asarray(plane, np.float32), (y0, x0), (y1, x1),
                                 linewidth=width, order=1, mode='reflect',
                                 reduce_func=np.mean))
    values = np.stack(rows) if rows else np.zeros((0, 0), np.float32)
    n = values.shape[1] if values.ndim == 2 else 0
    length_px = float(np.hypot(x1 - x0, y1 - y0))
    scale = pixel_um if pixel_um else 1.0
    distance = np.linspace(0.0, length_px * scale, n) if n else np.zeros(0)
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
