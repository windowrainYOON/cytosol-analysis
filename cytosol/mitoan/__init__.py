"""Measurement code of Mito Analyzer 1.8.0 (windowrainYOON/mito-tracking,
develop, mito_app/: mina.py, mito_objects.py, green.py, green_cells.py),
copied unchanged apart from the imports so the mitoROI tab gives the same
numbers. ``normalize_green`` and the reference constants come from its
cell_roi.py."""

import numpy as np
from scipy import ndimage as ndi

REF_PX_UM = 0.0990       # pixel size of the reference data set the size parameters were tuned on
REF_GREEN_UNIT = 4.79    # 75th pct of the background-subtracted, sigma=4 smoothed green image in that set
REF_GREEN_OFFSET = 0.077  # 1st pct of the same smoothed image (dark gaps between cells)


def normalize_green(g, px_scale=1.0):
    """Rescale green so its cytoplasmic level matches the reference set (cell_roi.normalize_green)."""
    sm = ndi.gaussian_filter(g, 4 * px_scale)
    off = np.percentile(sm, 1)
    unit = np.percentile(sm, 75) - off
    if unit <= 0:
        raise ValueError('Green channel has no usable signal for cell segmentation')
    gain = REF_GREEN_UNIT / unit
    gn = np.clip((g - off) * gain + REF_GREEN_OFFSET, 0, None)
    return gn, dict(offset=float(off), gain=float(gain))
