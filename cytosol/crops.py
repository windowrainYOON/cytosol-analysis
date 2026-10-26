"""Crop regions as ImageJ rectangle ROIs (<stem>_crops.zip), so a set of
crops can be saved with an image's exports and loaded back onto it."""

from __future__ import annotations

from pathlib import Path

CROP_PREFIX = 'crop'
CROP_KEY = 'crop_region'


def crop_rois(crops, properties=None) -> list:
    import roifile

    out = []
    for k, (x0, y0, x1, y1) in enumerate(crops, 1):
        r = roifile.ImagejRoi()
        r.roitype = roifile.ROI_TYPE.RECT
        r.left, r.top, r.right, r.bottom = int(x0), int(y0), int(x1), int(y1)
        r.name = f'{CROP_PREFIX}{k}'
        r.properties = {**{str(a): str(b) for a, b in (properties or {}).items()},
                        CROP_KEY: str(k)}
        out.append(r)
    return out


def save_crop_rois(path, crops, properties=None) -> str:
    """Write the crops of an image as one RoiSet (.zip) or a single .roi."""
    import roifile

    path = Path(path)
    rois = crop_rois(crops, properties)
    if not rois:
        raise ValueError('저장할 Crop 영역이 없습니다.')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    if path.suffix.lower() == '.roi' and len(rois) == 1:
        rois[0].tofile(path)
    else:
        path = path.with_suffix('.zip')
        roifile.roiwrite(path, rois)
    return str(path)


def _read(path) -> list:
    import roifile

    try:
        r = roifile.roiread(path)
    except Exception:
        return []
    return r if isinstance(r, list) else [r]


def is_crop_file(path) -> bool:
    """A ROI file holding only crop rectangles saved by this app."""
    rois = _read(path)
    return bool(rois) and all(CROP_KEY in (r.properties or {}) for r in rois)


def load_crop_rois(path) -> list[tuple[int, int, int, int]]:
    """(x0, y0, x1, y1) of every rectangle, in the saved order."""
    rois = _read(path)
    rois.sort(key=lambda r: int(str((r.properties or {}).get(CROP_KEY, 0)) or 0))
    return [(int(r.left), int(r.top), int(r.right), int(r.bottom)) for r in rois]
