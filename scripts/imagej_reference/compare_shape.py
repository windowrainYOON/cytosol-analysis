"""Compare cytosol.intensity.particle_shape with ImageJ Analyze Particles
(ShapeReference.java): area, centroid, perimeter, fitted ellipse, shape
descriptors and Feret values of every particle.

    python scripts/imagej_reference/compare_shape.py CLASSPATH [labels.npy]

Without a label image it runs random synthetic blobs."""

import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cytosol.intensity import particle_shape  # noqa: E402

COLS = ('Area', 'X', 'Y', 'Perim', 'Major', 'Minor', 'Angle', 'Circ', 'AR', 'Round',
        'Solidity', 'Feret', 'FeretAngle', 'MinFeret')
OURS = ('area', 'x', 'y', 'perim', 'major', 'minor', 'angle', 'circ', 'ar', 'round',
        'solidity', 'feret', 'feret_angle', 'min_feret')


def imagej(cp, labels):
    with tempfile.TemporaryDirectory() as d:
        labels.astype('<i4').tofile(f'{d}/l.raw')
        h, w = labels.shape
        out = subprocess.run(['java', '-Djava.awt.headless=true', '-cp', cp, 'ShapeReference',
                              f'{d}/l.raw', str(w), str(h)],
                             capture_output=True, text=True, check=True).stdout
    rows = {}
    for line in out.split()[1:]:
        v = line.split(',')
        if int(v[1]) != 1:
            print(f'label {v[0]}: ImageJ found {v[1]} particles, skipped')
            continue
        rows[int(v[0])] = dict(zip(COLS, map(float, v[2:])))
    return rows


def compare(cp, labels, name):
    from scipy import ndimage as ndi

    ref = imagej(cp, labels)
    worst = {c: 0.0 for c in COLS}
    where = {}
    for l, sl in enumerate(ndi.find_objects(labels), start=1):
        if sl is None or l not in ref:
            continue
        g = particle_shape(labels[sl] == l)
        g = {**g, 'x': g['x'] + sl[1].start, 'y': g['y'] + sl[0].start}
        for c, o in zip(COLS, OURS):
            r = ref[l][c]
            d = abs(g[o] - r)
            if c in ('Angle', 'FeretAngle'):
                d = min(d, 180 - d)
            else:
                d /= max(abs(r), 1e-9)
            if d > worst[c]:
                worst[c], where[c] = d, (l, g[o], r)
    print(f'{name}: {len(ref)} particles; max relative diff ' +
          ', '.join(f'{c} {worst[c]:.1e}' for c in COLS if c not in ('Angle', 'FeretAngle')) +
          f'; max angle diff ellipse {worst["Angle"]:.2g}°, Feret {worst["FeretAngle"]:.2g}°')
    for c, (l, o, r) in where.items():
        if worst[c] > 1e-4:
            print(f'  {c}: particle {l} ours {o:.6g} ImageJ {r:.6g}')
    return worst


def synthetic(seed=1):
    from skimage import measure
    rng = np.random.default_rng(seed)
    img = np.zeros((400, 400))
    yy, xx = np.mgrid[:400, :400]
    for _ in range(150):
        cy, cx = rng.uniform(10, 390, 2)
        a, b = rng.uniform(1, 9, 2)
        t = rng.uniform(0, np.pi)
        u = ((xx - cx) * np.cos(t) + (yy - cy) * np.sin(t)) / a
        v = (-(xx - cx) * np.sin(t) + (yy - cy) * np.cos(t)) / b
        img += np.exp(-(u * u + v * v) * rng.uniform(0.5, 2))
    img += rng.normal(0, 0.08, img.shape)
    return measure.label(img > 0.4, connectivity=2).astype(np.int32)


if __name__ == '__main__':
    cp = sys.argv[1]
    if len(sys.argv) > 2:
        compare(cp, np.load(sys.argv[2]).astype(np.int32), sys.argv[2])
    else:
        for s in (1, 2):
            compare(cp, synthetic(s), f'synthetic blobs {s}')
