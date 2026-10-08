"""Per-channel display LUTs, cropping and TIFF export for a set of images.

GUI-independent: the desktop app (cytosol.app) and scripts both use this.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from .io import Image
from .render import ScaleBarStyle, TimeStampStyle, channel_colors, project


@dataclass
class ChannelLUT:
    """Linear display mapping of one channel: [vmin, vmax] -> [0, 1] -> color."""

    vmin: float
    vmax: float
    color: tuple[float, float, float] = (1.0, 1.0, 1.0)
    gamma: float = 1.0
    visible: bool = True

    def apply(self, plane: np.ndarray) -> np.ndarray:
        """Return the plane mapped to 0..1 (no color)."""
        span = max(self.vmax - self.vmin, 1e-12)
        n = np.clip((plane.astype(np.float32) - self.vmin) / span, 0.0, 1.0)
        if self.gamma != 1.0:
            n = n ** (1.0 / self.gamma)
        return n

    def to_dict(self) -> dict:
        d = asdict(self)
        d['color'] = list(self.color)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> 'ChannelLUT':
        d = dict(d)
        d['color'] = tuple(d.get('color', (1, 1, 1)))
        return cls(**d)


def auto_range(plane: np.ndarray, low=0.5, high=99.8) -> tuple[float, float]:
    """Percentile range, ignoring NaNs; falls back to min/max when flat."""
    lo, hi = np.nanpercentile(plane, [low, high])
    if hi <= lo:
        lo, hi = float(np.nanmin(plane)), float(np.nanmax(plane))
    if hi <= lo:
        hi = lo + 1.0
    return float(lo), float(hi)


@dataclass
class ImageItem:
    """One loaded image plus everything the user set on it."""

    path: Path
    image: Image
    label: str
    z: str | int = 'mip'
    luts: list[ChannelLUT] = field(default_factory=list)
    # crop regions as (x0, y0, x1, y1) in pixels, exclusive end; each one is
    # exported as its own image
    crops: list[tuple[int, int, int, int]] = field(default_factory=list)
    # cell ROIs (cytosol.cellroi.CellRois) and the channel roles used for them:
    # {'nuc': channel index or None, 'bg': channel index}
    cells: object = None
    roi_roles: dict = field(default_factory=dict)
    _planes: np.ndarray | None = field(default=None, repr=False)
    _planes_z: object = field(default=None, repr=False)

    @classmethod
    def load(cls, path, label=None, **read_kwargs) -> 'ImageItem':
        from .io import read_image

        path = Path(path)
        image = read_image(path, **read_kwargs)
        item = cls(path=path, image=image, label=label or path.name)
        item.reset_luts()
        return item

    @property
    def channels(self) -> list[str]:
        return self.image.channels

    @property
    def nz(self) -> int:
        return self.image.data.shape[1]

    @property
    def nt(self) -> int:
        return self.image.nt

    @property
    def t(self) -> int:
        return self.image.t

    def set_t(self, t: int):
        """Switch to another timepoint (loads it from the file if needed)."""
        self.image.load_time(t)

    @property
    def pixel_um(self) -> float | None:
        return self.image.voxel_size_um.get('X')

    def planes(self) -> np.ndarray:
        """(C, Y, X) for the current z and timepoint (cached)."""
        key = (self.z, self.image.t)
        if self._planes is None or self._planes_z != key:
            self._planes = project(self.image, self.z).astype(np.float32)
            self._planes_z = key
        return self._planes

    def decorate(self, rgb, scale: ScaleBarStyle | None = None,
                 time: TimeStampStyle | None = None, t: int | None = None) -> np.ndarray:
        """Burn the scale bar and (for time series) the time stamp into an RGB image."""
        if scale is not None:
            rgb = scale.draw(rgb, self.pixel_um)
        if time is not None and self.nt > 1:
            rgb = time.draw(rgb, self.image.times, self.t if t is None else t)
        return rgb

    def value_range(self, index: int) -> tuple[float, float, str]:
        """(min, max, note) the LUT sliders span for a channel.

        The range the file can hold (from its metadata, e.g. 0..4095 for
        12-bit data) widened to include the current plane's values; without
        metadata, 0 (or a negative minimum) to the plane's max.
        """
        plane = self.planes()[index]
        dlo, dhi = float(np.nanmin(plane)), float(np.nanmax(plane))
        ranges = self.image.ranges
        rng = ranges[index] if index < len(ranges) else None
        if rng is None:
            lo = min(0.0, dlo)
            return lo, (dhi if dhi > lo else lo + 1.0), ''
        note = self.image.range_notes[index] if index < len(self.image.range_notes) else ''
        lo, hi = min(rng[0], dlo), max(rng[1], dhi)
        return lo, (hi if hi > lo else lo + 1.0), note

    def reset_luts(self):
        colors = channel_colors(self.image)
        planes = self.planes()
        self.luts = [ChannelLUT(*auto_range(p), color=c) for p, c in zip(planes, colors)]

    def auto_lut(self, index: int, low=0.5, high=99.8):
        self.luts[index].vmin, self.luts[index].vmax = auto_range(self.planes()[index], low, high)

    def region_planes(self, region=None) -> np.ndarray:
        """(C, Y, X) planes of the current z inside region (None = whole image)."""
        p = self.planes()
        if region is None:
            return p
        x0, y0, x1, y1 = region
        return p[:, y0:y1, x0:x1]

    def region_stack(self, region=None) -> np.ndarray:
        """Raw (C, Z, Y, X) data inside region, all z."""
        d = self.image.data
        if region is None:
            return d
        x0, y0, x1, y1 = region
        return d[:, :, y0:y1, x0:x1]

    def composite(self, region=None, channels=None) -> np.ndarray:
        """(Y, X, 3) float RGB with the LUTs applied.

        channels: indices to include; None means every visible channel.
        """
        planes = self.region_planes(region)
        rgb = np.zeros(planes.shape[1:] + (3,), np.float32)
        for i, (plane, lut) in enumerate(zip(planes, self.luts)):
            if channels is not None and i not in channels:
                continue
            if channels is None and not lut.visible:
                continue
            rgb += lut.apply(plane)[..., None] * np.asarray(lut.color, np.float32)
        return np.clip(rgb, 0.0, 1.0)

    def clip_region(self, x0, y0, x1, y1):
        """Clamp a rectangle to the image; None if it is smaller than 2 px."""
        h, w = self.image.data.shape[-2:]
        x0, x1 = sorted((int(np.clip(round(x0), 0, w)), int(np.clip(round(x1), 0, w))))
        y0, y1 = sorted((int(np.clip(round(y0), 0, h)), int(np.clip(round(y1), 0, h))))
        return None if (x1 - x0 < 2 or y1 - y0 < 2) else (x0, y0, x1, y1)

    def add_crop(self, x0, y0, x1, y1):
        """Add a crop region; returns it, or None if too small."""
        region = self.clip_region(x0, y0, x1, y1)
        if region is not None:
            self.crops.append(region)
        return region


def match_channel(item: ImageItem, name: str, index: int, like: ImageItem | None = None):
    """Index of the 'same channel' in another image, or None.

    Matches by channel name. Without a name match it falls back to the channel
    index, but only when ``like`` (the source image) has the same file type
    and channel count, so e.g. a CZI LUT never lands on a TCF RI channel.
    """
    if name in item.channels:
        return item.channels.index(name)
    if (
        like is not None
        and item.path.suffix.lower() == like.path.suffix.lower()
        and len(item.channels) == len(like.channels)
        and index < len(item.channels)
    ):
        return index
    return None


def apply_lut_to_all(items, source: ImageItem, index: int, color=True) -> int:
    """Copy one channel's LUT from source to the same channel of every item.

    Returns how many images were changed.
    """
    lut = source.luts[index]
    name = source.channels[index]
    n = 0
    for item in items:
        if item is source:
            continue
        j = match_channel(item, name, index, like=source)
        if j is None:
            continue
        tgt = item.luts[j]
        tgt.vmin, tgt.vmax, tgt.gamma, tgt.visible = lut.vmin, lut.vmax, lut.gamma, lut.visible
        if color:
            tgt.color = tuple(lut.color)
        n += 1
    return n


# ---------------------------------------------------------------------------
# presets
# ---------------------------------------------------------------------------


def save_preset(item: ImageItem, path):
    data = {
        'channels': {name: lut.to_dict() for name, lut in zip(item.channels, item.luts)},
        'order': item.channels,
    }
    Path(path).write_text(json.dumps(data, indent=2))


def load_preset(items, path) -> int:
    """Apply a saved preset to every item (match by channel name, else index)."""
    data = json.loads(Path(path).read_text())
    order = data.get('order', list(data['channels']))
    n = 0
    for item in items:
        for idx, name in enumerate(order):
            j = match_channel(item, name, idx)
            if j is not None:
                item.luts[j] = ChannelLUT.from_dict(data['channels'][name])
                n += 1
    return n


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


def _safe(text: str) -> str:
    return ''.join(c if c.isalnum() or c in '-_.' else '_' for c in text)


def item_stem(item: ImageItem) -> str:
    """File-name stem for an image; also the name of its per-image folder."""
    return _safe(Path(item.label).stem if item.label == item.path.name else item.label)


def _imagej_luts(item: ImageItem) -> list[np.ndarray]:
    ramp = np.arange(256, dtype=np.float32) / 255.0
    return [
        (np.outer(np.asarray(lut.color, np.float32), ramp) * 255).astype(np.uint8)
        for lut in item.luts
    ]


def export_item(
    item: ImageItem,
    out_dir,
    full=True,
    crops=True,
    composite=True,
    per_channel=False,
    raw_stack=True,
    scale: ScaleBarStyle | None = None,
    time: TimeStampStyle | None = None,
    all_times: bool = True,
) -> list[str]:
    """Write TIFFs for one image; returns the written paths.

    full:  export the whole image  -> <name>_full_*.tif
    crops: export each crop region -> <name>_crop1_*.tif, <name>_crop2_*.tif, ...
    For each of those regions:
      composite:   RGB 8-bit TIFF of visible channels with the LUTs applied.
      per_channel: one RGB 8-bit TIFF per channel in its color.
      raw_stack:   ImageJ hyperstack of the original values (all z) carrying
                   the channel LUTs, display ranges and µm calibration.
    scale / time: scale bar and time stamp burned into the RGB TIFFs
    (default: automatic scale bar, time stamp in the upper left).
    all_times: for a time series, write every timepoint (RGB TIFFs become
    T-frame stacks, the raw stack a TZCYX hyperstack); otherwise only the
    current one.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    scale = ScaleBarStyle() if scale is None else scale
    time = TimeStampStyle() if time is None else time
    stem = item_stem(item)
    regions = []
    if full:
        regions.append(('full', None))
    if crops:
        regions += [(f'crop{k}', r) for k, r in enumerate(item.crops, 1)]
    times = list(range(item.nt)) if all_times and item.nt > 1 else [item.t]
    return _export_regions(item, [(r, out_dir / f'{stem}_{tag}') for tag, r in regions],
                           composite, per_channel, raw_stack, scale, time, times)


def _export_regions(item, regions, composite, per_channel, raw_stack,
                    scale, time, times) -> list[str]:
    """Write every output of every region in one pass over the timepoints.

    Loading a timepoint (and, for TCF, aligning HT and FL) is the slow part,
    so each one is loaded once and fed to all outputs: RGB frames are
    collected in memory (8-bit, small) and the raw stacks are written straight
    into memory-mapped ImageJ TIFFs.
    """
    import tifffile

    px = item.pixel_um
    res = (1.0 / px, 1.0 / px) if px else None
    meta_common = {'unit': 'um'} if px else {}
    series = len(times) > 1
    interval = None
    if series:
        dt = np.diff([item.image.times[t] for t in times])
        interval = float(np.median(dt)) if len(dt) and np.median(dt) > 0 else None

    # (path, region, channels or None) -> list of uint8 frames
    rgb_jobs = []
    raw_jobs = []  # (path, region, memmap)
    for region, base in regions:
        if composite:
            rgb_jobs.append((Path(f'{base}_composite.tif'), region, None, []))
        if per_channel:
            for i, name in enumerate(item.channels):
                rgb_jobs.append((Path(f'{base}_C{i}_{_safe(name)}.tif'), region, [i], []))
    written = []
    start_t = item.t
    try:
        for k, t in enumerate(times):
            item.set_t(t)
            for path, region, chans, frames in rgb_jobs:
                rgb = item.decorate(item.composite(region, channels=chans), scale, time, t)
                frames.append((np.clip(rgb, 0, 1) * 255).astype(np.uint8))
            if raw_stack:
                if k == 0:
                    raw_jobs = [(Path(f'{base}_raw.tif'), region,
                                 _open_raw(item, region, Path(f'{base}_raw.tif'), len(times) if series else 0,
                                           res, meta_common, interval))
                                for region, base in regions]
                for _, region, mm in raw_jobs:
                    stack = item.region_stack(region)  # C, Z, Y, X
                    (mm[k] if series else mm)[:] = np.moveaxis(stack, 0, 1)
    finally:
        item.set_t(start_t)
        for path, _, mm in raw_jobs:
            mm.flush()
            del mm
    raw_jobs = [(path, region) for path, region, _ in raw_jobs]

    for path, region, chans, frames in rgb_jobs:
        rgb_meta = dict(meta_common)
        if series:
            rgb_meta['axes'] = 'TYXS'
            if interval:
                rgb_meta['finterval'] = interval
        tifffile.imwrite(
            path, np.stack(frames) if series else frames[0], photometric='rgb',
            resolution=res, metadata=rgb_meta or None, imagej=bool(px) or series,
        )
        written.append(str(path))
    written += [str(path) for path, _ in raw_jobs]
    return written


def _open_raw(item, region, path: Path, nt: int, res, meta_common, interval):
    """Create an uncompressed ImageJ hyperstack on disk and return it memory-mapped."""
    import tifffile

    first = item.region_stack(region)
    dtype = np.float32 if first.dtype == np.float64 else first.dtype
    c, z, h, w = first.shape
    meta = {
        'axes': 'TZCYX' if nt else 'ZCYX',
        'mode': 'composite',
        'LUTs': _imagej_luts(item),
        'Ranges': tuple(v for lut in item.luts for v in (lut.vmin, lut.vmax)),
        'Labels': list(item.channels),
        **meta_common,
    }
    vz = item.image.voxel_size_um.get('Z')
    if vz:
        meta['spacing'] = vz
    if interval:
        meta['finterval'] = interval
    shape = ((nt,) if nt else ()) + (z, c, h, w)
    return tifffile.memmap(path, shape=shape, dtype=dtype, imagej=True,
                           resolution=res, metadata=meta)


def export_all(items, out_dir, **kwargs) -> list[str]:
    files = []
    for item in items:
        files += export_item(item, out_dir, **kwargs)
    return files
