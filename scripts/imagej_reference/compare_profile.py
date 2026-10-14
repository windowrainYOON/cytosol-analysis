"""Compare cytosol.lineprofile with ImageJ's line profile (ProfilePlot, the
profile RGB Profiler plots per channel) on a random image.

    python scripts/imagej_reference/compare_profile.py CLASSPATH
"""

import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from cytosol.lineprofile import line_profile  # noqa: E402


def main():
    cp = sys.argv[1]
    rng = np.random.default_rng(3)
    h, w = 150, 170
    img = rng.random((h, w)).astype('<f4') * 1000
    raw = Path(tempfile.mkdtemp()) / 'img.raw'
    img.tofile(raw)
    lines = [(10.5, 20.5, 160.5, 120.5), (5.2, 140.7, 150.3, 3.9), (30, 75, 140, 75),
             (85, 5, 85, 145), (0.5, 0.5, 169.5, 149.5), (40.3, 60.8, 41.1, 100.2),
             (2, 10, 60, 12)]
    worst = 0.0
    for width in (1, 2, 3, 5, 10, 25):
        for line in lines:
            out = subprocess.run(['java', '-Djava.awt.headless=true', '-cp', cp, 'ProfileReference',
                                  str(raw), str(w), str(h), *map(str, line), str(width)],
                                 capture_output=True, text=True, check=True).stdout
            ij = np.array(out.split(), float)
            ours = line_profile(img[None], line, width).values[0].astype(float)
            if len(ij) != len(ours):
                print(f'width {width:2d} line {line}: {len(ij)} vs {len(ours)} points')
                worst = max(worst, 1.0)
                continue
            d = np.abs(ij - ours) / np.maximum(np.abs(ij), 1e-9)
            worst = max(worst, float(d.max()))
            print(f'width {width:2d} line {line}: {len(ij)} points, max rel. diff {d.max():.2e}, '
                  f'mean {d.mean():.2e}')
    print(f'largest relative difference: {worst:.2e}')


if __name__ == '__main__':
    main()
