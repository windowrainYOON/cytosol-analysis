"""Render a TCF/CZI/OIR file as colored PNGs with a scale bar.

Colors come from the file's own channel metadata; the scale bar length comes
from its pixel size. Both can be overridden.

examples:
  python scripts/render_image.py sample.czi --out figures/
  python scripts/render_image.py sample.TCF --modality 3DFL --z mid
  python scripts/render_image.py sample.oir --scale-um 20 --color CH2=gray --color 0=magenta
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cytosol.io import read_image  # noqa: E402
from cytosol.render import render  # noqa: E402


def _parse_colors(items):
    out = {}
    for item in items or []:
        key, _, value = item.partition('=')
        if not value:
            raise SystemExit(f'--color expects CHANNEL=COLOR, got {item!r}')
        out[int(key) if key.isdigit() else key] = value
    return out


def main(argv=None):
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument('file', type=Path)
    p.add_argument('--out', type=Path, default=Path('figures'))
    p.add_argument(
        '--modality', action='append',
        help="TCF only: 3D, 2DMIP, 3DFL, 2DFLMIP (repeatable; default 3D and 3DFL)",
    )
    p.add_argument('--z', default='mip', help="'mip' (default), 'mid' or a z index")
    p.add_argument('--scale-um', type=float, help='scale bar length in µm (default: auto)')
    p.add_argument(
        '--scale-position', default='lower right',
        choices=['lower right', 'lower left', 'upper right', 'upper left'],
    )
    p.add_argument(
        '--color', action='append', metavar='CHANNEL=COLOR',
        help='override a channel color by index or name, e.g. 0=magenta or DAPI-T3=#00A0FF',
    )
    p.add_argument('--no-labels', action='store_true', help='do not write channel names')
    p.add_argument('--low', type=float, default=0.5, help='lower contrast percentile')
    p.add_argument('--high', type=float, default=99.8, help='upper contrast percentile')
    args = p.parse_args(argv)

    z = args.z if args.z in ('mip', 'mid') else int(args.z)
    colors = _parse_colors(args.color)
    ext = args.file.suffix.lower()
    jobs = (
        [{'modality': m} for m in (args.modality or ['3D', '3DFL'])]
        if ext == '.tcf'
        else [{}]
    )

    results = {}
    for kwargs in jobs:
        image = read_image(args.file, **kwargs)
        prefix = args.file.stem + (f"_{kwargs['modality']}" if kwargs else '')
        res = render(
            image, args.out, prefix=prefix, z=z, colors=colors,
            scale_um=args.scale_um, scale_position=args.scale_position,
            labels=not args.no_labels, low=args.low, high=args.high,
        )
        results[prefix] = res
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
