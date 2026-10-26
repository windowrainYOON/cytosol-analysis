"""Per-channel display LUTs, cropping and TIFF export for a set of images.

GUI-independent: the desktop app (cytosol.app) and scripts both use this.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from .io import Image
from .render import OutlineStyle, ScaleBarStyle, TimeStampStyle, channel_colors, project


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


def add_colored(rgb: np.ndarray, n: np.ndarray, color) -> None:
    """rgb += n * color, one color component at a time (no (Y, X, 3) temporary)."""
    for k, c in enumerate(color):
        if c:
            rgb[..., k] += n if c == 1 else n * np.float32(c)


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
    # set when one file gives several items (a TCF opened as HT and FL)
    id_suffix: str = ''
    # exported files found with this image when a folder was loaded
    linked: list[Path] = field(default_factory=list)
    # line for the intensity profile, (x0, y0, x1, y1) in pixels
    profile_line: tuple | None = None
    # Coloc 2 results (cytosol.coloc_panel.ColocRecord), newest run
    coloc: list = field(default_factory=list)
    # particle ROIs (cytosol.intensity): the settings that make them per cell
    # (None: none, or loaded as fixed outlines) and the current plane's particles
    particle_settings: object = None
    particles: object = None
    # user-named group of images (cytosol.groups); '' = none
    group: str = ''
    # cytosol.prefetch.TimeCache that reads this image's timepoints ahead
    time_cache: object = field(default=None, repr=False)
    _bleach: list | None = field(default=None, repr=False)  # overrides the file's bleach ROIs
    _planes: np.ndarray | None = field(default=None, repr=False)
    _planes_z: object = field(default=None, repr=False)
    _planes_preview: bool = field(default=False, repr=False)  # approximate, for drawing only

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
    def image_id(self) -> str:
        """Stable per-acquisition ID (cytosol.imageid), carried by every export."""
        base = self.image.metadata.get('image_id') or ''
        return f'{base}-{self.id_suffix}' if self.id_suffix else base

    @property
    def source_name(self) -> str:
        """File name of the original acquisition (kept through exported TIFFs)."""
        return self.image.metadata.get('source_name') or self.path.name

    def id_properties(self) -> dict:
        """Key/value pairs written into exported TIFFs and ROIs."""
        from .imageid import ID_KEY, SOURCE_KEY

        return {ID_KEY: self.image_id, SOURCE_KEY: self.source_name}

    def id_metadata(self) -> dict:
        """ImageJ metadata entries (Info text and Properties) carrying the ID."""
        props = self.id_properties()
        return {'Info': '\n'.join(f'{k} = {v}' for k, v in props.items()),
                'Properties': props}

    @property
    def nz(self) -> int:
        return self.image.shape[1]

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
            tc = self.time_cache
            cached = tc.get(self, self.image.t) if tc is not None else None
            if cached is not None:
                self._planes = cached.astype(np.float32)
            else:
                self._planes = project(self.image, self.z).astype(np.float32)
                if tc is not None:
                    tc.put(self, self.image.t, self.z, self._planes)
            self._planes_z = key
            self._planes_preview = False
        return self._planes

    def show_planes(self, planes: np.ndarray, exact: bool):
        """Use planes (of the current z and timepoint) for drawing; an
        approximate one is replaced by drop_preview() before analysis."""
        self._planes = planes.astype(np.float32)
        self._planes_z = (self.z, self.image.t)
        self._planes_preview = not exact

    def drop_preview(self):
        if self._planes_preview:
            self._planes = None
            self._planes_preview = False

    @property
    def bleach_rois(self) -> list:
        """Bleach regions (cytosol.imageinfo.BleachRoi) from the file, or
        loaded from a saved _bleach_rois.zip."""
        if self._bleach is not None:
            return self._bleach
        return self.image.metadata.get('bleach_rois') or []

    @bleach_rois.setter
    def bleach_rois(self, rois):
        self._bleach = list(rois) if rois is not None else None

    def decorate(self, rgb, scale: ScaleBarStyle | None = None,
                 time: TimeStampStyle | None = None, t: int | None = None,
                 outline: OutlineStyle | None = None, region=None) -> np.ndarray:
        """Burn the bleach-region outlines, the scale bar and (for time series)
        the time stamp into an RGB image; region: the crop the image shows."""
        if outline is not None:
            rgb = outline.draw(rgb, self.bleach_rois, region[:2] if region else (0, 0))
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
            add_colored(rgb, lut.apply(plane), lut.color)
        return np.clip(rgb, 0.0, 1.0, out=rgb)

    def clip_region(self, x0, y0, x1, y1):
        """Clamp a rectangle to the image; None if it is smaller than 2 px."""
        h, w = self.image.shape[-2:]
        x0, x1 = sorted((int(np.clip(round(x0), 0, w)), int(np.clip(round(x1), 0, w))))
        y0, y1 = sorted((int(np.clip(round(y0), 0, h)), int(np.clip(round(y1), 0, h))))
        return None if (x1 - x0 < 2 or y1 - y0 < 2) else (x0, y0, x1, y1)

    def add_crop(self, x0, y0, x1, y1):
        """Add a crop region; returns it, or None if too small."""
        region = self.clip_region(x0, y0, x1, y1)
        if region is not None:
            self.crops.append(region)
        return region

    def move_crop(self, index, dx, dy):
        """Shift crop ``index`` by (dx, dy) pixels, same size, kept inside the image."""
        x0, y0, x1, y1 = self.crops[index]
        h, w = self.image.shape[-2:]
        dx = int(np.clip(round(dx), -x0, w - x1))
        dy = int(np.clip(round(dy), -y0, h - y1))
        self.crops[index] = (x0 + dx, y0 + dy, x1 + dx, y1 + dy)
        return self.crops[index]


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
    """File-name stem for an image."""
    return _safe(Path(item.label).stem if item.label == item.path.name else item.label)


def item_folder(item: ImageItem) -> str:
    """Name of an image's per-image export folder: <stem>_<image ID>, so
    images that share a file name never write into the same folder."""
    iid = item.image_id
    return f'{item_stem(item)}_{_safe(iid)}' if iid else item_stem(item)


def unique_stems(items) -> dict[int, str]:
    """File-name stem per item (keyed by id(item)) for saving several images
    into one folder: images whose stems collide get their ID appended."""
    count: dict[str, int] = {}
    for it in items:
        count[item_stem(it)] = count.get(item_stem(it), 0) + 1
    return {id(it): item_folder(it) if count[item_stem(it)] > 1 else item_stem(it)
            for it in items}


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
    stem: str | None = None,
    rgb_format: str = 'tif',
    fps: float = 10.0,
    outline: OutlineStyle | None = None,
    bleach_file: bool = True,
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
    stem: file-name prefix (default item_stem(item)).
    rgb_format: for a series of timepoints, write the RGB outputs as 'tif'
    (T-frame stack), 'mp4' (H.264 movie at fps) or 'both'. A single
    timepoint always gives a TIFF; the raw stack is always a TIFF.
    outline: how the file's bleach regions are burned into the RGB outputs
    (None or disabled: not drawn). bleach_file: also write the bleach
    regions as ImageJ ROIs, <name>_bleach_rois.zip.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    scale = ScaleBarStyle() if scale is None else scale
    time = TimeStampStyle() if time is None else time
    stem = stem or item_stem(item)
    regions = []
    if full:
        regions.append(('full', None))
    if crops:
        regions += [(f'crop{k}', r) for k, r in enumerate(item.crops, 1)]
    times = list(range(item.nt)) if all_times and item.nt > 1 else [item.t]
    written = _export_regions(item, [(r, out_dir / f'{stem}_{tag}') for tag, r in regions],
                              composite, per_channel, raw_stack, scale, time, times,
                              rgb_format, fps, outline)
    if bleach_file and item.bleach_rois:
        from .imageinfo import save_bleach_rois

        written.append(save_bleach_rois(out_dir / f'{stem}_bleach_rois.zip', item.bleach_rois,
                                        item.id_properties()))
    return written


def _export_regions(item, regions, composite, per_channel, raw_stack,
                    scale, time, times, rgb_format='tif', fps=10.0, outline=None) -> list[str]:
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
                rgb = item.decorate(item.composite(region, channels=chans), scale, time, t,
                                    outline, region)
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

    from .movie import wants_mp4, wants_tif, write_mp4

    for path, region, chans, frames in rgb_jobs:
        if series and wants_mp4(rgb_format):
            written.append(write_mp4(path.with_suffix('.mp4'), frames, fps))
            if not wants_tif(rgb_format):
                continue
        rgb_meta = dict(meta_common)
        if series:
            rgb_meta['axes'] = 'TYXS'
            if interval:
                rgb_meta['finterval'] = interval
        rgb_meta.update(item.id_metadata())
        tifffile.imwrite(
            path, np.stack(frames) if series else frames[0], photometric='rgb',
            resolution=res, metadata=rgb_meta, imagej=True,
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
        **item.id_metadata(),
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
    stems = unique_stems(items)
    for item in items:
        files += export_item(item, out_dir, stem=stems[id(item)], **kwargs)
    return files
