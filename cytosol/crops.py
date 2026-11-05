"""Crop regions as ImageJ rectangle ROIs (<stem>_crops.zip), so a set of
crops can be saved with an image's exports and loaded back onto it.

A crop is a rectangle (x0, y0, x1, y1) in ``ImageItem.crops``; a crop whose
outline was changed with 점 편집 also has a polygon (N × 2 x, y points) at
the same index of ``ImageItem.crop_polys`` (None = the plain rectangle).
Its rectangle is then the polygon's bounding box: images of it are that
box with the outside of the polygon set to 0, and its ROI is a polygon."""

from __future__ import annotations

from pathlib import Path

CROP_PREFIX = 'crop'
CROP_KEY = 'crop_region'


def polys_of(item) -> list:
    """item.crop_polys kept as long as item.crops (missing = rectangles)."""
    polys = list(getattr(item, 'crop_polys', None) or [])
    n = len(item.crops)
    polys = (polys + [None] * n)[:n]
    item.crop_polys = polys
    return polys


def bbox(poly) -> tuple[int, int, int, int]:
    import numpy as np

    p = np.asarray(poly, float)
    return (int(np.floor(p[:, 0].min())), int(np.floor(p[:, 1].min())),
            int(np.ceil(p[:, 0].max())), int(np.ceil(p[:, 1].max())))


def rect_points(rect):
    x0, y0, x1, y1 = rect
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def poly_mask(poly, rect):
    """Boolean mask (h, w) of the polygon inside its rectangle."""
    import numpy as np
    from skimage.draw import polygon as fill

    x0, y0, x1, y1 = rect
    m = np.zeros((y1 - y0, x1 - x0), bool)
    p = np.asarray(poly, float)
    rr, cc = fill(p[:, 1] - y0, p[:, 0] - x0, m.shape)
    m[rr, cc] = True
    return m


def crop_rois(crops, properties=None, polys=None) -> list:
    import numpy as np
    import roifile

    out = []
    polys = list(polys or [])
    for k, (x0, y0, x1, y1) in enumerate(crops, 1):
        poly = polys[k - 1] if k - 1 < len(polys) else None
        if poly is not None:
            r = roifile.ImagejRoi.frompoints(np.asarray(poly, float))
            r.roitype = roifile.ROI_TYPE.POLYGON
        else:
            r = roifile.ImagejRoi()
            r.roitype = roifile.ROI_TYPE.RECT
            r.left, r.top, r.right, r.bottom = int(x0), int(y0), int(x1), int(y1)
        r.name = f'{CROP_PREFIX}{k}'
        r.properties = {**{str(a): str(b) for a, b in (properties or {}).items()},
                        CROP_KEY: str(k)}
        out.append(r)
    return out


def save_crop_rois(path, crops, properties=None, polys=None) -> str:
    """Write the crops of an image as one RoiSet (.zip) or a single .roi."""
    import roifile

    path = Path(path)
    rois = crop_rois(crops, properties, polys)
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


def load_crop_polys(path) -> list:
    """The polygon of each crop of a file (None for rectangles), in the
    order of load_crop_rois."""
    import roifile

    rois = _read(path)
    rois.sort(key=lambda r: int(str((r.properties or {}).get(CROP_KEY, 0)) or 0))
    out = []
    for r in rois:
        if r.roitype == roifile.ROI_TYPE.RECT:
            out.append(None)
        else:
            out.append([tuple(map(float, p)) for p in r.coordinates()])
    return out
