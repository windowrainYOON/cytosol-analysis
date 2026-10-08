"""Readers for Tomocube TCF, Zeiss CZI and Olympus OIR microscopy files.

Every reader returns an :class:`Image` holding the pixel arrays as numpy
arrays with axes ``(C, Z, Y, X)`` (singleton axes kept) plus a flat metadata
dictionary with voxel sizes in micrometers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

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


def read_tcf(path, modality: str = '3D', timepoint: int = 0) -> Image:
    """Read one modality of a TCF file.

    modality: '3D' or '2DMIP' (refractive index, returned as float RI),
    '3DFL' or '2DFLMIP' (fluorescence, raw counts per channel).
    """
    import h5py

    frame = f'{timepoint:06d}'
    with h5py.File(path, 'r') as f:
        grp = f['Data'][modality]
        ga = _attrs(grp)
        vx = {
            'Z': ga.get('ResolutionZ'),
            'Y': ga['ResolutionY'],
            'X': ga['ResolutionX'],
        }
        if 'FL' in modality:
            names = sorted(k for k in grp.keys() if k.startswith('CH'))
            planes = []
            channels = []
            colors = []
            for ch in names:
                arr = grp[ch][frame][()].astype(np.float32)
                planes.append(arr if arr.ndim == 3 else arr[None])
                ca = _attrs(grp[ch])
                colors.append(
                    tuple(ca.get(f'Color{k}', 255) / 255.0 for k in 'RGB')
                    if 'ColorR' in ca
                    else None
                )
                channels.append(
                    f"{ch} ex{ca.get('Excitation', 0) * 1000:.0f}/"
                    f"em{ca.get('Emission', 0) * 1000:.0f}"
                )
            data = np.stack(planes)
        else:
            arr = grp[frame][()].astype(np.float32) / TCF_RI_SCALE
            data = (arr if arr.ndim == 3 else arr[None])[None]
            channels = ['RI']
            colors = [(1.0, 1.0, 1.0)]
        meta = {
            'format': 'TCF',
            'modality': modality,
            'file': _attrs(f),
            'device': _attrs(f['Info/Device']) if 'Info/Device' in f else {},
            'group': ga,
        }
    return Image(data, channels, vx, meta, colors)


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
    extra = [d for d in x.dims if d not in ('C', 'Z', 'Y', 'X')]
    if extra:
        raise ValueError(f'unsupported CZI axes {extra}; select them first')
    x = x.transpose('C', 'Z', 'Y', 'X')
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
    return Image(np.asarray(x.values), names, vx, meta, colors)


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
    extra = [d for d in x.dims if d not in ('C', 'Z', 'Y', 'X') and x.sizes[d] > 1]
    if extra:
        raise ValueError(f'unsupported OIR axes {extra}; select them first')
    x = x.squeeze([d for d in x.dims if d not in ('C', 'Z', 'Y', 'X')])
    x = x.transpose('C', 'Z', 'Y', 'X')
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
    return Image(np.asarray(x.values), channels, vx, meta, colors)


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


def read_image(path, **kwargs) -> Image:
    """Dispatch on file extension."""
    ext = Path(path).suffix.lower()
    if ext == '.tcf':
        return read_tcf(path, **kwargs)
    if ext == '.czi':
        return read_czi(path, **kwargs)
    if ext == '.oir':
        return read_oir(path, **kwargs)
    raise ValueError(f'unsupported file extension: {ext}')
