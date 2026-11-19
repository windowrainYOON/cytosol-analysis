"""Per-cell green / Cy5 with each cell's own local background (owner 2026-11-19).

usage: python scripts/cell_local_bg.py PROJECT.cyproj OUT
For every image tracked with the ParticleTracker method (TrackState.pt keeps the cell labels CID), every frame and
cell: cell mean of reference (Cy5) and measure (green), and the MEAN of a ring around that cell (2–6 µm outside its
edge, other cells left out) as that cell's background in that frame.  No field-wide value is subtracted, so a shift of
the background is followed cell by cell.  (ParticleTracker's cell_intensity subtracts the median of every pixel
outside the cells, which is 0 / 1 for 8-bit green.)
Outputs: cell_local_bg.csv (per cell × frame), graphs (all frames and the green-background-stable window).
"""
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import ndimage as ndi

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from cytosol import pt_engine  # noqa: E402
from cytosol.project import read_project  # noqa: E402
from cytosol.ptcore import registration  # noqa: E402

proj, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
RING_IN_UM, RING_OUT_UM, MIN_FRAMES = 2.0, 6.0, 20
data, files = read_project(proj)
images = data.get('images') or []
rows = []
for n, entry in enumerate(images):
    key = f'images/{n}/tracks.pkl'
    if key not in files:
        continue
    st = pickle.loads(files[key])
    pt = getattr(st, 'pt', None)
    if not pt:
        continue
    arr = pt_engine._unpack(pt['arrays'])
    CID, reg, S = arr['CID'], pt['reg'], float(pt['S'])
    src = pt['sources']
    tcf, ref_ch = src['reference'].rsplit('::', 1)
    mea_ch = src['measure'].rsplit('::', 1)[1]
    name = Path(tcf).stem.split('.A1.')[-1]
    A, B, _ = pt_engine.load(tcf, ref_ch, mea_ch)
    Bal = registration.align_b(B, reg)
    T, NF, NW = A.shape
    NH, NHW = CID.shape[1:]
    px = 0.1125   # Tomocube HTX fluorescence pixel (µm); ParticleTracker works in these pixels
    rin, rout = RING_IN_UM / px, RING_OUT_UM / px
    yy, xx = np.arange(NF), np.arange(NW)
    dt = float((pt.get('cfg') or {}).get('channel', {}).get('frame_interval_min', 20.0))
    for z in range(T):
        hy = np.clip(np.round((yy + .5) * S - .5 + reg.dy_ht.values[z]).astype(int), 0, NH - 1)
        hx = np.clip(np.round((xx + .5) * S - .5 + reg.dx_ht.values[z]).astype(int), 0, NHW - 1)
        lab = CID[z][np.ix_(hy, hx)]
        a, b = A[z].astype(float), Bal[z].astype(float)
        free = lab == 0
        for sl, c in zip(ndi.find_objects(lab), range(1, int(lab.max()) + 1)):
            if sl is None:
                continue
            pad = int(rout) + 2
            y0, y1 = max(sl[0].start - pad, 0), min(sl[0].stop + pad, NF)
            x0, x1 = max(sl[1].start - pad, 0), min(sl[1].stop + pad, NW)
            m = lab[y0:y1, x0:x1] == c
            d = ndi.distance_transform_edt(~m)
            ring = (d > rin) & (d <= rout) & free[y0:y1, x0:x1]
            if ring.sum() < 50:
                continue
            ca, cb = a[y0:y1, x0:x1], b[y0:y1, x0:x1]
            rows.append(dict(image=name, cell_id=c, frame=z + 1, time_min=z * dt, cell_area_flpx=int(m.sum()),
                             cy5_cell=float(ca[m].mean()), green_cell=float(cb[m].mean()),
                             cy5_ring=float(ca[ring].mean()), green_ring=float(cb[ring].mean()),
                             ring_px=int(ring.sum())))
    print(name, 'cells', len({r['cell_id'] for r in rows if r['image'] == name}), flush=True)
    del A, B, Bal
C = pd.DataFrame(rows)
C['t_h'] = C.time_min / 60
C['cell_uid'] = C.image + '::' + C.cell_id.astype(str)
C['green'] = C.green_cell - C.green_ring
C['cy5'] = C.cy5_cell - C.cy5_ring
C['ratio_raw'] = C.green_cell / C.cy5_cell
C['ratio'] = np.where(C.cy5 > 0, C.green / C.cy5, np.nan)
C['long_cell'] = C.groupby('cell_uid').frame.transform('size') >= MIN_FRAMES
C.round(5).to_csv(out / 'cell_local_bg.csv', index=False)
print('rows', len(C), 'cells', C.cell_uid.nunique(), 'long cells', C[C.long_cell].cell_uid.nunique())
