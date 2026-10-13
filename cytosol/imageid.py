"""A stable ID per acquired image, and pairing files by it.

The ID comes from what the microscope wrote into the file, so it survives
renaming and copying:

- TCF:  the file's ``UniqueID`` attribute (else ``DataID``)
- CZI:  the file GUID in the CZI header (plus the scene, when one is picked)
- OIR:  system name + acquisition time + the channel UUIDs
- TIFF: the ID this app embedded on export, else the OME ``UUID``
- otherwise: a hash of the file content (size, first and last MiB)

It is shortened to ``XXXX-XXXX-XXXX`` (12 hex digits of a SHA-1). Exports
carry it: TIFFs in their ImageJ ``Info``/``Properties``, ROIs in each ROI's
properties, measurement CSVs in an ``image_id`` column. Loading a folder then
puts each original image, its exported TIFFs and its RoiSet back together.
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path

ID_KEY = 'CytosolImageID'
SOURCE_KEY = 'CytosolSource'
IMAGE_EXT = ('.tcf', '.czi', '.oir', '.tif', '.tiff')
ROI_EXT = ('.zip', '.roi')


def short_id(key: str) -> str:
    h = hashlib.sha1(key.encode('utf-8')).hexdigest()[:12].upper()
    return f'{h[:4]}-{h[4:8]}-{h[8:]}'


def content_key(path) -> str:
    """Size plus the first and last MiB of the file."""
    path = Path(path)
    size = path.stat().st_size
    h = hashlib.sha1(str(size).encode())
    with open(path, 'rb') as f:
        h.update(f.read(1 << 20))
        if size > 2 << 20:
            f.seek(-(1 << 20), 2)
            h.update(f.read())
    return h.hexdigest()


def source_key(meta: dict, path) -> tuple[str, str]:
    """(key the ID is hashed from, where it came from) for a read image's metadata."""
    fmt = meta.get('format')
    if fmt == 'TCF':
        f = meta.get('file') or {}
        for k in ('UniqueID', 'DataID'):
            if f.get(k):
                return f'TCF|{f[k]}', f'TCF {k}'
    elif fmt == 'CZI':
        if meta.get('file_guid'):
            scene = meta.get('scene')
            return (f'CZI|{meta["file_guid"]}' + (f'|S{scene}' if scene is not None else ''),
                    'CZI file GUID')
    elif fmt == 'OIR':
        if meta.get('datetime') and meta.get('channel_ids'):
            return (f'OIR|{meta.get("system", "")}|{meta["datetime"]}|'
                    + ','.join(sorted(meta['channel_ids'])), 'OIR 획득 시각 + 채널 UUID')
    elif fmt == 'TIFF':
        if meta.get('ome_uuid'):
            return f'OME|{meta["ome_uuid"]}', 'OME UUID'
    return f'FILE|{content_key(path)}', '파일 내용 해시'


def assign_id(image, path):
    """Set image.metadata['image_id'] (and where it came from) unless it is embedded."""
    meta = image.metadata
    if meta.get('image_id'):
        meta.setdefault('image_id_source', '저장된 ID')
        return image
    key, how = source_key(meta, path)
    meta['image_id'] = short_id(key)
    meta['image_id_source'] = how
    return image


# ---------------------------------------------------------------------------
# reading the ID back from exported files without loading pixels
# ---------------------------------------------------------------------------


def ids_from_imagej(ij: dict) -> tuple[str | None, str | None]:
    """(ID, source file name) from ImageJ metadata written by this app."""
    props = ij.get('Properties') or {}
    iid, src = props.get(ID_KEY), props.get(SOURCE_KEY)
    if not iid:
        m = re.search(ID_KEY + r'\s*[=:]\s*(\S+)', str(ij.get('Info') or ''))
        iid = m.group(1) if m else None
    return iid, src


def tiff_id(path) -> tuple[str | None, str | None]:
    """(ID, source name) embedded in a TIFF this app exported; (None, None) otherwise."""
    import tifffile

    try:
        with tifffile.TiffFile(path) as tif:
            return ids_from_imagej(tif.imagej_metadata or {})
    except Exception:
        return None, None


def roi_id(path) -> str | None:
    """ID stored in the properties of an ImageJ .roi / RoiSet.zip; None if absent."""
    import roifile

    path = Path(path)
    try:
        if path.suffix.lower() == '.zip':
            if not zipfile.is_zipfile(path):
                return None
            rois = roifile.roiread(path)
        else:
            rois = roifile.ImagejRoi.fromfile(path)
    except Exception:
        return None
    for r in rois if isinstance(rois, list) else [rois]:
        props = getattr(r, 'properties', None) or {}
        if isinstance(props, dict) and props.get(ID_KEY):
            return str(props[ID_KEY])
    return None


def is_roi_file(path) -> bool:
    """A .roi file, or a .zip that holds .roi entries."""
    path = Path(path)
    if path.suffix.lower() == '.roi':
        return True
    if path.suffix.lower() != '.zip':
        return False
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
    except Exception:
        return False
    return bool(names) and all(n.lower().endswith('.roi') or n.endswith('/') for n in names)


# ---------------------------------------------------------------------------
# pairing
# ---------------------------------------------------------------------------


def export_rank(path) -> int:
    """Which exported TIFF of an image to open when the original is missing
    (lower is better): the full-size raw stack keeps every channel and value
    and matches the ROI coordinates; crops come last."""
    name = Path(path).stem.lower()
    kind = 0 if name.endswith('_raw') else 1 if name.endswith('_composite') else 2
    return kind + (4 if re.search(r'_crop\d+_', name) else 0)


def plan_pairing(paths) -> dict:
    """Sort a set of files into what to open and what belongs to what.

    Returns {'open': [image paths to load as images],
             'exports': {id: [exported TIFF paths]},
             'rois': [ROI file paths]}.
    TIFFs carrying an embedded ID are 'exports'; the caller decides whether
    an original with that ID is loaded or one export has to stand in for it.
    """
    opened, exports, rois = [], {}, []
    for p in map(Path, paths):
        ext = p.suffix.lower()
        if ext in ROI_EXT:
            if is_roi_file(p):
                rois.append(p)
        elif ext in ('.tif', '.tiff'):
            iid, _ = tiff_id(p)
            if iid:
                exports.setdefault(iid, []).append(p)
            else:
                opened.append(p)
        elif ext in IMAGE_EXT:
            opened.append(p)
    for iid in exports:
        exports[iid].sort(key=lambda q: (export_rank(q), str(q)))
    return {'open': opened, 'exports': exports, 'rois': rois}


def match_roi(path, items, stem_of) -> tuple[object | None, str]:
    """Item a ROI file belongs to: by the ID inside it, else by file name
    (``<image name>_RoiSet.zip`` / ``<image name>_<roi>.roi``). Returns (item, how)."""
    iid = roi_id(path)
    if iid:
        for it in items:
            if it.image_id == iid:
                return it, 'ID'
        return None, f'ID {iid} 이미지 없음'
    name = Path(path).stem
    best = None
    for it in items:
        stem = stem_of(it)
        if name == f'{stem}_RoiSet' or name.startswith(stem + '_'):
            if best is None or len(stem) > len(stem_of(best)):
                best = it
    return (best, '파일 이름') if best is not None else (None, '짝 없음')
