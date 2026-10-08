"""Readers for Tomocube TCF, Zeiss CZI, Olympus OIR and TIFF microscopy files.

Every reader returns an :class:`Image` holding the pixel arrays as numpy
arrays with axes ``(C, Z, Y, X)`` (singleton axes kept) plus a flat metadata
dictionary with voxel sizes in micrometers, and per channel the value range
the file can hold (0 to the detector's maximum, e.g. 4095 for 12-bit data),
read from the file's metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np


@dataclass
class Image:
    """One image volume and its metadata."""

    data: np.ndarray  # (C, Z, Y, X)
    channels: list[str]
    voxel_size_um: dict[str, float | None]  # keys: 'Z', 'Y', 'X'; None if unknown
    metadata: dict = field(default_factory=dict)
    # display color per channel as (r, g, b) in 0..1, taken from the file when
    # it stores one; None where the file has no color for that channel
    colors: list[tuple[float, float, float] | None] = field(default_factory=list)
    # time series: acquisition time of every timepoint in seconds from the
    # first one; ``data`` holds the timepoint ``t`` only and ``loader(t)``
    # returns the (C, Z, Y, X) array of any other timepoint
    times: list[float] = field(default_factory=lambda: [0.0])
    t: int = 0
    loader: Callable[[int], np.ndarray] | None = field(default=None, repr=False)
    # value range per channel as (min, max) from the file metadata (bit depth,
    # stored type, or the RI range of a TCF), with a short note on where it
    # came from ('12-bit', 'uint16', ...); None where the file says nothing
    ranges: list[tuple[float, float] | None] = field(default_factory=list)
    range_notes: list[str] = field(default_factory=list)

    @property
    def nt(self) -> int:
        return len(self.times)

    def load_time(self, t: int):
        """Make ``data`` hold timepoint t."""
        t = int(np.clip(t, 0, self.nt - 1))
        if t != self.t and self.loader is not None:
            self.data = self.loader(t)
            self.t = t


def _decode(value):
    """Turn an HDF5 attribute (often a 1-element array of bytes) into Python."""
    if isinstance(value, np.ndarray):
        value = value.tolist()
        if isinstance(value, list) and len(value) == 1:
            value = value[0]
    if isinstance(value, bytes):
        value = value.decode('utf-8', 'replace')
    return value


def _attrs(obj) -> dict:
    return {k: _decode(v) for k, v in obj.attrs.items()}


def _bits_range(bits) -> tuple[tuple[float, float], str] | None:
    """(0, 2**bits - 1) and its note for an integer bit depth."""
    try:
        bits = int(bits)
    except (TypeError, ValueError):
        return None
    if not 1 <= bits <= 32:
        return None
    return (0.0, float(2 ** bits - 1)), f'{bits}-bit'


def _dtype_range(dtype) -> tuple[tuple[float, float], str] | None:
    """Full range of an integer dtype (uint8 -> 0..255); None for floats."""
    dtype = np.dtype(dtype)
    if dtype.kind not in 'ui':
        return None
    info = np.iinfo(dtype)
    return (float(min(info.min, 0)), float(info.max)), str(dtype)


def _set_ranges(image: 'Image', ranges) -> 'Image':
    """Store a list of _bits_range/_dtype_range results (or None) on the image."""
    image.ranges = [r[0] if r else None for r in ranges]
    image.range_notes = [r[1] if r else '' for r in ranges]
    return image


# ---------------------------------------------------------------------------
# Tomocube TCF (HDF5)
# ---------------------------------------------------------------------------

TCF_RI_SCALE = 10000.0  # 3D/2DMIP refractive index is stored as uint16 RI*1e4


def tcf_metadata(path) -> dict:
    """Return the TCF file tree: root, per-modality and per-channel attributes."""
    import h5py

    with h5py.File(path, 'r') as f:
        meta = {'file': _attrs(f), 'device': {}, 'modalities': {}}
        if 'Info/Device' in f:
            meta['device'] = _attrs(f['Info/Device'])
        for name, grp in f['Data'].items():
            info = _attrs(grp)
            info['channels'] = {}
            for key, item in grp.items():
                if hasattr(item, 'shape'):  # dataset directly under modality
                    info.setdefault('frames', {})[key] = {
                        'shape': item.shape,
                        'dtype': str(item.dtype),
                        **_attrs(item),
                    }
                else:  # channel group (FL)
                    info['channels'][key] = _attrs(item)
                    info['channels'][key]['frames'] = {
                        k: {'shape': d.shape, 'dtype': str(d.dtype), **_attrs(d)}
                        for k, d in item.items()
                    }
            meta['modalities'][name] = info
    return meta


def _frames(grp) -> list[str]:
    """Timepoint dataset names ('000000', '000001', ...) of a modality/channel group."""
    return sorted(k for k in grp.keys() if k.isdigit())


def _frame_times(grp) -> list[float]:
    """Acquisition time (s) of each timepoint, from the per-frame 'Time' attribute."""
    times = []
    for i, k in enumerate(_frames(grp)):
        t = _decode(grp[k].attrs.get('Time', i))
        times.append(float(t) if isinstance(t, (int, float)) else float(i))
    return times


def _tcf_fl_channels(grp) -> list[str]:
    return sorted(k for k in grp.keys() if k.startswith('CH'))


def _tcf_fl_info(grp):
    """Channel names, colors and timepoint list of an FL modality group."""
    names, colors = [], []
    for ch in _tcf_fl_channels(grp):
        ca = _attrs(grp[ch])
        colors.append(
            tuple(ca.get(f'Color{k}', 255) / 255.0 for k in 'RGB') if 'ColorR' in ca else None
        )
        names.append(
            f"{ch} ex{ca.get('Excitation', 0) * 1000:.0f}/"
            f"em{ca.get('Emission', 0) * 1000:.0f}"
        )
    first = grp[_tcf_fl_channels(grp)[0]]
    return names, colors, _frames(first), _frame_times(first)


def _tcf_ranges(grp, modality: str) -> list:
    """Per channel value range of a TCF modality group.

    HT: the RIMin..RIMax the file records (RI is not a detector count, so 0 is
    meaningless there). FL: the full range of the stored integer type.
    """
    if 'FL' not in modality:
        ga = _attrs(grp)
        if 'RIMin' in ga and 'RIMax' in ga and float(ga['RIMax']) > float(ga['RIMin']):
            return [((float(ga['RIMin']), float(ga['RIMax'])), 'RI')]
        return [None]
    out = []
    for ch in _tcf_fl_channels(grp):
        frames = _frames(grp[ch])
        out.append(_dtype_range(grp[ch][frames[0]].dtype) if frames else None)
    return out


def _tcf_read_frame(f, modality: str, frame: str) -> np.ndarray:
    """(C, Z, Y, X) float32 of one timepoint; RI as float, FL as raw counts."""
    grp = f['Data'][modality]
    if 'FL' in modality:
        planes = []
        for ch in _tcf_fl_channels(grp):
            if frame in grp[ch]:
                arr = grp[ch][frame][()].astype(np.float32)
            else:  # a channel not acquired at this timepoint
                ref = next(grp[c][frame] for c in _tcf_fl_channels(grp) if frame in grp[c])
                arr = np.zeros(ref.shape, np.float32)
            planes.append(arr if arr.ndim == 3 else arr[None])
        return np.stack(planes)
    arr = grp[frame][()].astype(np.float32) / TCF_RI_SCALE
    return (arr if arr.ndim == 3 else arr[None])[None]


def read_tcf(path, modality: str = '3D', timepoint: int = 0) -> Image:
    """Read one modality of a TCF file.

    modality: '3D' or '2DMIP' (refractive index, returned as float RI),
    '3DFL' or '2DFLMIP' (fluorescence, raw counts per channel).
    Every timepoint of a time-lapse file is reachable through
    ``Image.load_time``; ``timepoint`` picks the one loaded first.
    """
    import h5py

    path = str(path)
    with h5py.File(path, 'r') as f:
        grp = f['Data'][modality]
        ga = _attrs(grp)
        vx = {
            'Z': ga.get('ResolutionZ'),
            'Y': ga['ResolutionY'],
            'X': ga['ResolutionX'],
        }
        if 'FL' in modality:
            channels, colors, frames, times = _tcf_fl_info(grp)
        else:
            channels, colors = ['RI'], [(1.0, 1.0, 1.0)]
            frames, times = _frames(grp), _frame_times(grp)
        timepoint = int(np.clip(timepoint, 0, len(frames) - 1))
        data = _tcf_read_frame(f, modality, frames[timepoint])
        ranges = _tcf_ranges(grp, modality)
        meta = {
            'format': 'TCF',
            'modality': modality,
            'file': _attrs(f),
            'device': _attrs(f['Info/Device']) if 'Info/Device' in f else {},
            'group': ga,
        }

    def loader(t):
        with h5py.File(path, 'r') as f:
            return _tcf_read_frame(f, modality, frames[t])

    t0 = times[0] if times else 0.0
    return _set_ranges(Image(data, channels, vx, meta, colors,
                             times=[t - t0 for t in times], t=timepoint, loader=loader), ranges)


# ---- HT + FL on one pixel grid ---------------------------------------------

MAX_FL_SHIFT_UM = 2.0  # largest XY correction accepted from image registration


def _grid(ga) -> dict:
    return {
        'nx': int(ga['SizeX']), 'ny': int(ga['SizeY']), 'nz': int(ga.get('SizeZ', 1) or 1),
        'rx': float(ga['ResolutionX']), 'ry': float(ga['ResolutionY']),
        'rz': float(ga.get('ResolutionZ') or 0.0),
    }


def _resample_fl(fl: np.ndarray, ht_grid: dict, fl_grid: dict, fl_z0_um: float | None,
                 shift_px=(0.0, 0.0)) -> np.ndarray:
    """Resample a (C, Zf, Yf, Xf) FL volume onto the HT grid (C, Zh, Yh, Xh).

    XY: both images share the optical axis, so the pixel centers are aligned
    at the image center and scaled by the pixel size ratio; ``shift_px`` adds a
    residual (dy, dx) offset in FL pixels. Z: HT slice k sits at (k + 0.5) * dz
    from the bottom of the HT volume and FL slice j at fl_z0_um + (j + 0.5) * dz;
    HT slices outside the FL range are 0. With fl_z0_um None (a 2D HT image)
    the FL volume is max-projected.
    """
    from scipy import ndimage as ndi

    h, f = ht_grid, fl_grid
    sy, sx = h['ry'] / f['ry'], h['rx'] / f['rx']
    oy = (f['ny'] - 1) / 2 - sy * (h['ny'] - 1) / 2 + shift_px[0]
    ox = (f['nx'] - 1) / 2 - sx * (h['nx'] - 1) / 2 + shift_px[1]

    def xy(plane):
        return ndi.affine_transform(plane, [sy, sx], offset=[oy, ox],
                                    output_shape=(h['ny'], h['nx']), order=1)

    c, zf = fl.shape[:2]
    if fl_z0_um is None or h['nz'] == 1 or zf == 1:
        return np.stack([xy(fl[i].max(axis=0))[None] for i in range(c)]).astype(np.float32)
    out = np.zeros((c, h['nz'], h['ny'], h['nx']), np.float32)
    # fractional FL slice index of every HT slice
    zpos = (np.arange(h['nz']) + 0.5) * h['rz']
    jf = (zpos - fl_z0_um) / f['rz'] - 0.5
    need = sorted({j for v in jf if -0.5 <= v <= zf - 0.5
                   for j in (int(np.floor(v)), int(np.ceil(v))) if 0 <= j < zf})
    for i in range(c):
        cache = {j: xy(fl[i, j]) for j in need}
        for k, v in enumerate(jf):
            if v < -0.5 or v > zf - 0.5:
                continue
            v = float(np.clip(v, 0, zf - 1))
            j0, j1 = int(np.floor(v)), int(np.ceil(v))
            w = v - j0
            out[i, k] = cache[j0] if j1 == j0 else (1 - w) * cache[j0] + w * cache[j1]
    return out


def _fl_shift(ht: np.ndarray, fl: np.ndarray, ht_grid, fl_grid) -> tuple[float, float]:
    """Residual (dy, dx) of FL against HT in FL pixels, from the projections.

    Each FL channel is registered to the HT max projection by phase
    correlation; shifts larger than MAX_FL_SHIFT_UM (a failed match, e.g. a
    channel with no structure shared with RI) are discarded. Returns the
    accepted shift with the smallest error, or (0, 0).
    """
    from scipy import ndimage as ndi
    from skimage.registration import phase_cross_correlation

    def norm(a):
        a = ndi.gaussian_filter(a, 2)
        lo, hi = np.percentile(a, [1, 99.8])
        return np.clip((a - lo) / max(hi - lo, 1e-12), 0, 1)

    import warnings

    ref = norm(ht[0].max(axis=0))
    if not ref.std() > 0:
        return 0.0, 0.0
    flp = _resample_fl(fl, ht_grid, fl_grid, None)
    best = None
    for i in range(flp.shape[0]):
        mov = norm(flp[i, 0])
        if not mov.std() > 0:
            continue
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                shift, err, _ = phase_cross_correlation(ref, mov, upsample_factor=10,
                                                        normalization=None)
        except Exception:
            continue
        um = float(np.hypot(*shift)) * ht_grid['rx']
        if not np.isfinite(err):
            continue
        if um <= MAX_FL_SHIFT_UM and (best is None or err < best[1]):
            best = (shift, err)
    if best is None:
        return 0.0, 0.0
    # shift moves the FL image (HT pixels) onto HT; the sampling offset is the opposite
    dy, dx = best[0]
    return (-float(dy) * ht_grid['ry'] / fl_grid['ry'], -float(dx) * ht_grid['rx'] / fl_grid['rx'])


def read_tcf_aligned(path, timepoint: int = 0, refine: bool = True) -> Image:
    """HT (RI) and fluorescence of a TCF file as one image on the HT grid.

    Channels: RI first, then every FL channel resampled into the HT voxels
    (XY by pixel size around the shared image center, plus a small automatic
    registration when ``refine``; Z from the 3DFL ``OffsetZ``, which is the
    center of the FL stack measured from the bottom of the HT volume).
    Uses 3D/3DFL when present, else 2DMIP/2DFLMIP. Falls back to a single
    modality when the file has only HT or only FL. Time series: HT timepoints
    drive the time axis and each one gets the FL timepoint nearest in time.
    """
    import h5py

    path = str(path)
    with h5py.File(path, 'r') as f:
        mods = set(f['Data'].keys())
    ht_mod = '3D' if '3D' in mods else ('2DMIP' if '2DMIP' in mods else None)
    fl_mod = '3DFL' if '3DFL' in mods else ('2DFLMIP' if '2DFLMIP' in mods else None)
    if ht_mod is None or fl_mod is None:
        return read_tcf(path, ht_mod or fl_mod, timepoint)

    with h5py.File(path, 'r') as f:
        hg, fg = f['Data'][ht_mod], f['Data'][fl_mod]
        ha, fa = _attrs(hg), _attrs(fg)
        ht_frames, ht_times = _frames(hg), _frame_times(hg)
        fl_names, fl_colors, fl_frames, fl_times = _tcf_fl_info(fg)
        ranges = _tcf_ranges(hg, ht_mod) + _tcf_ranges(fg, fl_mod)
        meta = {
            'format': 'TCF',
            'modality': f'{ht_mod}+{fl_mod}',
            'file': _attrs(f),
            'device': _attrs(f['Info/Device']) if 'Info/Device' in f else {},
            'group': ha,
            'fl_group': fa,
        }
    ht_grid, fl_grid = _grid(ha), _grid(fa)
    if ht_mod == '3D' and fl_mod == '3DFL' and 'OffsetZ' in fa:
        center = float(fa['OffsetZ']) + float(fa.get('OffsetZCompensation', 0) or 0)
        fl_z0 = center - fl_grid['nz'] * fl_grid['rz'] / 2
    else:
        fl_z0 = None  # no Z registration possible: project FL onto every HT slice
        if ht_grid['nz'] > 1 and fl_grid['nz'] > 1:
            fl_z0 = (ht_grid['nz'] * ht_grid['rz'] - fl_grid['nz'] * fl_grid['rz']) / 2
    # FL timepoint for each HT timepoint
    if len(fl_frames) == len(ht_frames):
        fl_for = list(range(len(ht_frames)))
    else:
        fl_for = [int(np.argmin([abs(ft - t) for ft in fl_times])) for t in ht_times]
    state = {'shift': None}

    def loader(t):
        with h5py.File(path, 'r') as f:
            ht = _tcf_read_frame(f, ht_mod, ht_frames[t])
            fl = _tcf_read_frame(f, fl_mod, fl_frames[fl_for[t]])
        if state['shift'] is None:
            state['shift'] = _fl_shift(ht, fl, ht_grid, fl_grid) if refine else (0.0, 0.0)
            meta['fl_shift_um'] = (state['shift'][0] * fl_grid['ry'],
                                   state['shift'][1] * fl_grid['rx'])
        flr = _resample_fl(fl, ht_grid, fl_grid, fl_z0, state['shift'])
        out = np.empty((1 + flr.shape[0],) + ht.shape[1:], np.float32)
        out[:1] = ht
        out[1:] = flr  # broadcasts a projected FL over every slice of a 2D HT
        return out

    timepoint = int(np.clip(timepoint, 0, len(ht_frames) - 1))
    data = loader(timepoint)
    meta['fl_z0_um'] = fl_z0
    vx = {'Z': ha.get('ResolutionZ'), 'Y': ha['ResolutionY'], 'X': ha['ResolutionX']}
    t0 = ht_times[0] if ht_times else 0.0
    return _set_ranges(Image(data, ['RI'] + fl_names, vx, meta, [(1.0, 1.0, 1.0)] + fl_colors,
                             times=[t - t0 for t in ht_times], t=timepoint, loader=loader),
                       ranges)


# ---------------------------------------------------------------------------
# Zeiss CZI
# ---------------------------------------------------------------------------


def read_czi(path, scene: int | None = None) -> Image:
    """Read a CZI file (all channels, all Z) via czifile."""
    import czifile

    with czifile.CziFile(path) as czi:
        img = czi.scenes[scene] if scene is not None else czi
        x = img.asxarray()
        xml = czi.metadata()
    x = x.squeeze()
    for ax in ('C', 'Z'):
        if ax not in x.dims:
            x = x.expand_dims(ax)
    extra = [d for d in x.dims if d not in ('T', 'C', 'Z', 'Y', 'X')]
    if extra:
        raise ValueError(f'unsupported CZI axes {extra}; select them first')
    x, times, loader = _split_time(x)
    scales = dict(x.attrs.get('coord_scales', {}))
    to_um = {'meter': 1e6, 'micrometer': 1.0}
    units = x.attrs.get('coord_units', {})
    vx = {
        ax: float(scales[ax]) * to_um.get(units.get(ax, 'meter'), 1e6)
        if ax in scales
        else None
        for ax in ('Z', 'Y', 'X')
    }
    meta = {
        'format': 'CZI',
        'datetime': x.attrs.get('datetime'),
        'objective': x.attrs.get('objective'),
        'channel_info': x.attrs.get('channels'),
        'xml': xml,
    }
    names = [str(c) for c in x.coords['C'].values]
    info = x.attrs.get('channels') or {}
    colors = [_argb_to_rgb(info.get(n, {}).get('Color')) for n in names]
    image = Image(np.asarray(x.values), names, vx, meta, colors, times=times, loader=loader)
    return _set_ranges(image, [_czi_range(xml, image.data.dtype)] * len(names))


def _czi_range(xml: str, dtype):
    """Value range from the CZI ComponentBitCount (e.g. 12 or 14 in a uint16 image)."""
    import re

    m = re.search(r'<ComponentBitCount>\s*(\d+)', xml or '')
    return (_bits_range(m.group(1)) if m else None) or _dtype_range(dtype)


def _split_time(x):
    """Pull a time axis off an xarray image: (C, Z, Y, X) of t=0, times, loader."""
    if 'T' not in x.dims:
        return x.transpose('C', 'Z', 'Y', 'X'), [0.0], None
    x = x.transpose('T', 'C', 'Z', 'Y', 'X')
    full = np.asarray(x.values)
    try:
        times = [float(v) for v in x.coords['T'].values]
    except (KeyError, TypeError, ValueError):
        times = []
    if len(times) != full.shape[0] or len(set(times)) != len(times):
        times = [float(i) for i in range(full.shape[0])]
    times = [t - times[0] for t in times]
    return x.isel(T=0), times, lambda t: full[t]


def _argb_to_rgb(value):
    """Convert a ZEN color string '#AARRGGBB' (or '#RRGGBB') to (r, g, b)."""
    if not value or not str(value).startswith('#'):
        return None
    hexstr = str(value)[1:]
    if len(hexstr) == 8:
        hexstr = hexstr[2:]
    if len(hexstr) != 6:
        return None
    return tuple(int(hexstr[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


# ---------------------------------------------------------------------------
# Olympus / Evident OIR
# ---------------------------------------------------------------------------


def read_oir(path) -> Image:
    """Read an OIR file via oirfile."""
    import oirfile

    with oirfile.OirFile(path) as oir:
        x = oir.asxarray()
        oir_channels = list(oir.channels)
        meta = {
            'format': 'OIR',
            'datetime': oir.datetime,
            'bitspersample': oir.bitspersample,
            'scanner': oir.scanner,
            'channel_info': oir.channels,
            'xml': dict(oir.xml_metadata),
        }
    for ax in ('C', 'Z'):
        if ax not in x.dims:
            x = x.expand_dims(ax)
    extra = [d for d in x.dims if d not in ('T', 'C', 'Z', 'Y', 'X') and x.sizes[d] > 1]
    if extra:
        raise ValueError(f'unsupported OIR axes {extra}; select them first')
    x = x.squeeze([d for d in x.dims if d not in ('T', 'C', 'Z', 'Y', 'X')])
    if 'T' in x.dims and x.sizes['T'] == 1:
        x = x.squeeze('T')
    x, times, loader = _split_time(x)
    scales = x.attrs.get('coord_scales', {})
    vx = {ax: float(scales[ax]) if ax in scales else None for ax in ('Z', 'Y', 'X')}
    channels = [str(c) for c in x.coords['C'].values] if 'C' in x.coords else [
        f'CH{i + 1}' for i in range(x.sizes['C'])
    ]
    luts = _oir_luts(path)
    colors = []
    for name in channels:
        cands = [c for c in oir_channels if c.name == name]
        # FluoView can list a channel name twice (e.g. once for a reference
        # image); the acquisition channel is the one with a detection range
        cands = [c for c in cands if c.start_wavelength is not None] or cands
        colors.append(luts.get(cands[-1].id) if cands else None)
    image = Image(np.asarray(x.values), channels, vx, meta, colors, times=times, loader=loader)
    rng = _bits_range(meta['bitspersample']) or _dtype_range(image.data.dtype)
    return _set_ranges(image, [rng] * len(channels))


_OIR_LUT_COLORS = {
    'gray': (1.0, 1.0, 1.0),
    'grey': (1.0, 1.0, 1.0),
    'red': (1.0, 0.0, 0.0),
    'green': (0.0, 1.0, 0.0),
    'blue': (0.0, 0.0, 1.0),
    'cyan': (0.0, 1.0, 1.0),
    'magenta': (1.0, 0.0, 1.0),
    'yellow': (1.0, 1.0, 0.0),
}


def _oir_luts(path) -> dict:
    """Map OIR channel id -> display color from the LUT blocks in the file.

    FluoView stores each channel's LUT as an XML document preceded by that
    channel's UUID; oirfile exposes the XML but not the UUID, so scan the raw
    bytes. The color comes from the LUT name, falling back to which of the
    red/green/blue components are switched on (contrast 1).
    """
    import re

    raw = Path(path).read_bytes()
    pattern = re.compile(
        rb'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})'
        rb'.{0,16}?<\?xml[^>]*>\s*<lut:LUT',
        re.S,
    )
    luts = {}
    for m in pattern.finditer(raw):
        end = raw.find(b'</lut:LUT>', m.end())
        block = raw[m.end():end if end > 0 else m.end() + 4096]
        block = re.sub(rb'<lut:data>.*?</lut:data>', b'', block, flags=re.S)
        name = re.search(rb'<lut:name>([^<]*)', block)
        color = _OIR_LUT_COLORS.get(name.group(1).decode().strip().lower()) if name else None
        if color is None:
            comps = []
            for comp in (b'red', b'green', b'blue'):
                c = re.search(rb'<lut:' + comp + rb'>.*?<lut:contrast>([^<]*)', block, re.S)
                comps.append(1.0 if c and float(c.group(1)) > 0 else 0.0)
            color = tuple(comps) if any(comps) else None
        if color is not None:
            luts[m.group(1).decode()] = color
    return luts


# ---------------------------------------------------------------------------
# TIFF (plain, ImageJ hyperstack, OME-TIFF)
# ---------------------------------------------------------------------------

_TIFF_UNITS_UM = {'micron': 1.0, 'um': 1.0, '\u00b5m': 1.0, '\\u00B5m': 1.0,
                  'nm': 1e-3, 'mm': 1e3, 'cm': 1e4, 'm': 1e6}


def read_tiff(path) -> Image:
    """Read a TIFF via tifffile: ImageJ hyperstacks and OME-TIFF keep their
    T/Z/C axes, pixel size, channel names and colors; a plain multi-page TIFF
    is read as a Z stack and an RGB TIFF as three channels.
    """
    import tifffile

    with tifffile.TiffFile(path) as tif:
        series = tif.series[0]
        axes = series.axes.upper()
        data = series.asarray()
        page = series.pages[0] if series.pages else tif.pages[0]
        ij = tif.imagej_metadata or {}
        ome = tif.ome_metadata if tif.is_ome else None
        tags = {t.name: t.value for t in page.tags.values()}
        bits = tags.get('BitsPerSample')

    rgb = 'S' in axes and 'C' not in axes
    data, _ = _tiff_to_tczyx(data, axes)
    nt, nc = data.shape[:2]
    names = [f'CH{i + 1}' for i in range(nc)]
    colors: list = [None] * nc
    vx = {'Z': None, 'Y': None, 'X': None}
    times = [float(i) for i in range(nt)]
    sig_bits = None

    if ome:
        o = _ome_info(ome)
        vx.update({k: v for k, v in o['voxel'].items() if v})
        names = [n or names[i] for i, n in enumerate(o['names'][:nc])] + names[len(o['names']):]
        colors = (o['colors'] + colors)[:nc] if o['colors'] else colors
        sig_bits = o['bits']
        if o['dt']:
            times = [i * o['dt'] for i in range(nt)]
    else:
        x = _tiff_pixel_um(tags, ij)
        if x:
            vx['X'] = vx['Y'] = x
        if ij.get('spacing') and data.shape[2] > 1:
            vx['Z'] = float(ij['spacing']) * _TIFF_UNITS_UM.get(str(ij.get('unit', 'micron')), 1.0)
        if ij.get('finterval'):
            times = [i * float(ij['finterval']) for i in range(nt)]
        luts = ij.get('LUTs') or []
        for i, lut in enumerate(luts[:nc]):
            lut = np.asarray(lut)
            if lut.ndim == 2 and lut.shape[0] == 3:
                top = lut[:, -1].astype(np.float64) / 255.0
                if top.max() > 0:
                    colors[i] = tuple(float(c) for c in top)
        labels = ij.get('Labels')
        if isinstance(labels, (list, tuple)) and len(labels) == nc and all(labels):
            names = [str(n) for n in labels]
        if rgb and nc == 3 and not any(colors):
            names = ['R', 'G', 'B']
            colors = [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)]

    if isinstance(bits, tuple):
        bits = bits[0]
    rng = (_bits_range(sig_bits) if sig_bits and data.dtype.kind in 'ui' else None)
    if rng is None and data.dtype.kind in 'ui':
        rng = _bits_range(bits) if bits and int(bits) < data.dtype.itemsize * 8 else None
        rng = rng or _dtype_range(data.dtype)
    meta = {'format': 'TIFF', 'axes': axes, 'imagej': {k: v for k, v in ij.items()
                                                        if k not in ('LUTs', 'Ranges')},
            'ome': ome is not None, 'bits': bits}
    image = Image(data[0], names, vx, meta, colors, times=times,
                  loader=(lambda t: data[t]) if nt > 1 else None)
    return _set_ranges(image, [rng] * nc)


def _tiff_to_tczyx(data: np.ndarray, axes: str):
    """Reorder a tifffile series to (T, C, Z, Y, X).

    S (RGB samples) becomes C when there is no C axis; any other unknown axis
    (I, Q, ...: an unlabelled page stack) becomes Z, or T when Z is taken.
    """
    axes = list(axes)
    if 'S' in axes:
        if 'C' in axes:
            i = axes.index('S')
            data = data.take(0, axis=i) if data.shape[i] == 1 else data
            if data.ndim < len(axes):
                axes.pop(i)
            else:
                raise ValueError('TIFF with both C and RGB samples is not supported')
        else:
            axes[axes.index('S')] = 'C'
    for i, a in enumerate(axes):
        if a not in 'TCZYX':
            axes[i] = 'Z' if 'Z' not in axes else ('T' if 'T' not in axes else a)
    extra = [i for i, a in enumerate(axes) if a not in 'TCZYX']
    for i in reversed(extra):  # anything still unknown: keep the first plane
        data = data.take(0, axis=i)
        axes.pop(i)
    for a in 'TCZ':
        if a not in axes:
            data = data[np.newaxis]
            axes.insert(0, a)
    order = [axes.index(a) for a in 'TCZYX']
    return np.ascontiguousarray(data.transpose(order)), 'TCZYX'


def _tiff_pixel_um(tags: dict, ij: dict) -> float | None:
    """Pixel size in um from the XResolution tag (ImageJ stores pixels per unit)."""
    res = tags.get('XResolution')
    if not res:
        return None
    num, den = res if isinstance(res, tuple) else (res, 1)
    if not num or not den:
        return None
    per_unit = num / den
    unit = str(ij.get('unit', '')).strip()
    # without an ImageJ unit the resolution is a print setting (dpi), not a pixel size
    scale = (_TIFF_UNITS_UM.get(unit) or _TIFF_UNITS_UM.get(unit.lower())) if unit else None
    if scale is None or per_unit <= 0:
        return None
    return float(scale / per_unit)


def _ome_info(xml: str) -> dict:
    """Voxel size, channel names/colors, significant bits and time step from OME-XML."""
    import xml.etree.ElementTree as ET

    out = {'voxel': {}, 'names': [], 'colors': [], 'bits': None, 'dt': None}
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return out
    pix = next((e for e in root.iter() if e.tag.endswith('}Pixels') or e.tag == 'Pixels'), None)
    if pix is None:
        return out
    for ax in 'XYZ':
        v = pix.get(f'PhysicalSize{ax}')
        if v:
            unit = pix.get(f'PhysicalSize{ax}Unit', '\u00b5m')
            out['voxel'][ax] = float(v) * _TIFF_UNITS_UM.get(unit, 1.0)
    out['bits'] = pix.get('SignificantBits')
    if pix.get('TimeIncrement'):
        out['dt'] = float(pix.get('TimeIncrement'))
    for ch in (e for e in pix if e.tag.endswith('Channel')):
        out['names'].append(ch.get('Name'))
        c = ch.get('Color')
        if c is not None:
            v = int(c) & 0xFFFFFFFF  # signed RGBA
            out['colors'].append(((v >> 24 & 255) / 255, (v >> 16 & 255) / 255, (v >> 8 & 255) / 255))
        else:
            out['colors'].append(None)
    if not any(out['colors']):
        out['colors'] = []
    return out


def read_image(path, **kwargs) -> Image:
    """Dispatch on file extension."""
    ext = Path(path).suffix.lower()
    if ext == '.tcf':
        if kwargs.pop('aligned', False):
            return read_tcf_aligned(path, **kwargs)
        return read_tcf(path, **kwargs)
    if ext == '.czi':
        return read_czi(path, **kwargs)
    if ext == '.oir':
        return read_oir(path, **kwargs)
    if ext in ('.tif', '.tiff'):
        return read_tiff(path, **kwargs)
    raise ValueError(f'unsupported file extension: {ext}')
