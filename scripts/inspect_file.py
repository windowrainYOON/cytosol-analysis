"""Print key metadata of a TCF/CZI/OIR file and save preview PNGs.

usage: python scripts/inspect_file.py FILE [--format tcf|czi|oir] [--out DIR]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cytosol.io import read_czi, read_oir, read_tcf, tcf_metadata  # noqa: E402


def _norm(img: np.ndarray, lo=0.5, hi=99.8) -> np.ndarray:
    a, b = np.percentile(img, [lo, hi])
    return np.clip((img - a) / max(b - a, 1e-12), 0, 1)


def _summary(image) -> dict:
    c, z, y, x = image.data.shape
    return {
        'shape_CZYX': [c, z, y, x],
        'dtype': str(image.data.dtype),
        'channels': image.channels,
        'voxel_size_um': {
            k: None if v is None else round(v, 5)
            for k, v in image.voxel_size_um.items()
        },
        'field_of_view_um': [
            round(x * image.voxel_size_um['X'], 2),
            round(y * image.voxel_size_um['Y'], 2),
        ],
        'per_channel_min_max': [
            [float(image.data[i].min()), float(image.data[i].max())] for i in range(c)
        ],
    }


def _save_panel(image, title: str, out: Path):
    import matplotlib

    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    c, z = image.data.shape[:2]
    cols = c + (1 if c > 1 else 0)
    fig, axes = plt.subplots(1, cols, figsize=(4.2 * cols, 4.6), squeeze=False)
    mips = [image.data[i].max(axis=0) for i in range(c)]
    for i, mip in enumerate(mips):
        ax = axes[0, i]
        ax.imshow(_norm(mip), cmap='gray')
        label = 'MIP' if z > 1 else 'plane'
        ax.set_title(f'{image.channels[i]} ({label})', fontsize=9)
        ax.axis('off')
    if c > 1:
        palette = [(1, 0, 1), (0, 1, 0), (0, 0.5, 1), (1, 0.6, 0), (1, 1, 1)]
        rgb = np.zeros(mips[0].shape + (3,))
        for i, mip in enumerate(mips):
            rgb += _norm(mip)[..., None] * np.array(palette[i % len(palette)])
        axes[0, -1].imshow(np.clip(rgb, 0, 1))
        axes[0, -1].set_title('composite', fontsize=9)
        axes[0, -1].axis('off')
    fig.suptitle(title, fontsize=10)
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    plt.close(fig)


def inspect_tcf(path: Path, outdir: Path) -> dict:
    import matplotlib

    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    meta = tcf_metadata(path)
    result = {
        'file': meta['file'],
        'device': meta['device'],
        'modalities': {},
    }
    for name, info in meta['modalities'].items():
        keep = {
            k: v
            for k, v in info.items()
            if k not in ('frames', 'channels')
        }
        keep['channels'] = {
            ch: {k: v for k, v in cinfo.items() if k != 'frames'}
            for ch, cinfo in info.get('channels', {}).items()
        }
        result['modalities'][name] = keep

    ht = read_tcf(path, '3D')
    result['3D_summary'] = _summary(ht)
    z = ht.data.shape[1]
    vol = ht.data[0]
    vx = ht.voxel_size_um
    fig, axes = plt.subplots(1, 3, figsize=(15, 5.4))
    vmin, vmax = np.percentile(vol, [0.5, 99.9])
    axes[0].imshow(vol[z // 2], cmap='gray', vmin=vmin, vmax=vmax)
    axes[0].set_title(f'HT RI, z={z // 2}/{z} ({z // 2 * vx["Z"]:.1f} um)')
    axes[1].imshow(vol.max(axis=0), cmap='gray', vmin=vmin, vmax=vmax)
    axes[1].set_title('HT RI MIP (Z)')
    xz = vol[:, vol.shape[1] // 2, :]
    im = axes[2].imshow(
        xz, cmap='gray', vmin=vmin, vmax=vmax, aspect=vx['Z'] / vx['X']
    )
    axes[2].set_title('HT RI XZ section (true aspect)')
    for ax in axes:
        ax.axis('off')
    fig.colorbar(im, ax=axes, shrink=0.7, label='refractive index')
    fig.suptitle(path.name, fontsize=10)
    fig.savefig(outdir / 'tcf_ht.png', dpi=110)
    plt.close(fig)

    if '3DFL' in meta['modalities']:
        fl = read_tcf(path, '3DFL')
        result['3DFL_summary'] = _summary(fl)
        _save_panel(fl, f'{path.name} 3D FL', outdir / 'tcf_fl.png')
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('file', type=Path)
    p.add_argument('--format', choices=['tcf', 'czi', 'oir'])
    p.add_argument('--out', type=Path, default=Path('format-check'))
    args = p.parse_args(argv)
    fmt = args.format or args.file.suffix.lower().lstrip('.')
    args.out.mkdir(parents=True, exist_ok=True)

    if fmt == 'tcf':
        result = inspect_tcf(args.file, args.out)
    elif fmt in ('czi', 'oir'):
        image = read_czi(args.file) if fmt == 'czi' else read_oir(args.file)
        result = {'format': fmt.upper(), **_summary(image)}
        for k in ('datetime', 'objective', 'channel_info', 'bitspersample', 'scanner'):
            if image.metadata.get(k) is not None:
                result[k] = image.metadata[k]
        _save_panel(image, f'{args.file.name} ({fmt.upper()})', args.out / f'{fmt}.png')
    else:
        p.error(f'unknown format {fmt}')

    text = json.dumps(result, indent=2, ensure_ascii=False, default=str)
    (args.out / f'{fmt}_metadata.json').write_text(text)
    print(text)


if __name__ == '__main__':
    main()
