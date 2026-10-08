"""Draw the Cytosol Viewer app icon: cytosol/assets/icon.png and icon.icns.

    python scripts/make_icon.py
"""

from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

S = 2048  # drawn at 2x, saved at 1024
OUT = Path(__file__).resolve().parent.parent / 'cytosol' / 'assets'


def blob(cx, cy, r, wobble, n=720, seed=3):
    rng = np.random.default_rng(seed)
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    rad = np.full(n, float(r))
    for k, a in zip((2, 3, 5), wobble):
        rad += r * a * np.sin(k * t + rng.uniform(0, 2 * np.pi))
    return [(cx + x, cy + y) for x, y in zip(rad * np.cos(t), rad * 0.86 * np.sin(t))]


def layer(draw_fn, blur=0):
    im = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(im))
    return im.filter(ImageFilter.GaussianBlur(blur)) if blur else im


def main():
    # macOS icon grid: 824/1024 rounded square centered
    m = int(S * 100 / 1024)
    rad = int(S * 185 / 1024)
    mask = Image.new('L', (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([m, m, S - m, S - m], rad, fill=255)

    # background: dark navy radial gradient
    yy, xx = np.mgrid[0:S, 0:S] / S
    d = np.sqrt((xx - 0.45) ** 2 + (yy - 0.4) ** 2)
    base = np.stack([12 + 30 * (1 - d), 16 + 34 * (1 - d), 34 + 60 * (1 - d)], -1)
    bg = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8)).convert('RGBA')

    cell = blob(S * 0.5, S * 0.52, S * 0.29, (0.05, 0.04, 0.025))
    nuc = blob(S * 0.47, S * 0.53, S * 0.10, (0.06, 0.03, 0.02), seed=9)

    # cytosol: soft green fill
    cyto = layer(lambda d: d.polygon(cell, fill=(40, 200, 110, 150)), blur=S * 0.02)
    # puncta in the cytosol
    rng = np.random.default_rng(5)

    def puncta(d):
        for _ in range(70):
            a = rng.uniform(0, 2 * np.pi)
            rr = rng.uniform(0.45, 0.9) * S * 0.25
            x, y = S * 0.5 + rr * np.cos(a), S * 0.52 + rr * 0.8 * np.sin(a)
            if np.hypot(x - S * 0.47, (y - S * 0.53) / 0.86) < S * 0.12:
                continue
            r = rng.uniform(0.006, 0.012) * S
            d.ellipse([x - r, y - r, x + r, y + r], fill=(170, 255, 170, 230))
    dots = layer(puncta, blur=S * 0.003)
    # membrane: red/magenta outline with glow
    fill = Image.new('L', (S, S), 0)
    ImageDraw.Draw(fill).polygon(cell, fill=255)
    fill = fill.filter(ImageFilter.GaussianBlur(2))
    k = int(S * 0.006) | 1
    ring = ImageChops.subtract(fill.filter(ImageFilter.MaxFilter(k)),
                               fill.filter(ImageFilter.MinFilter(k)))
    ring = ring.point(lambda v: 255 if v > 90 else int(v * 2.8))

    def colored(alpha, rgb):
        im = Image.new('RGBA', (S, S), rgb + (0,))
        im.putalpha(alpha)
        return im

    mem_glow = colored(ring.filter(ImageFilter.MaxFilter(k)).filter(
        ImageFilter.GaussianBlur(S * 0.012)), (255, 40, 90))
    mem = colored(ring, (255, 90, 120))
    # nucleus: blue
    nuc_l = layer(lambda d: d.polygon(nuc, fill=(50, 110, 255, 235)), blur=S * 0.006)

    # zoom inset motif: white box on the cytosol + magnified square in a corner
    bx, by, bs = S * 0.60, S * 0.36, S * 0.09
    lw = int(S * 0.008)

    img = bg.copy()
    for l in (cyto, dots, mem_glow, mem, nuc_l):
        img = Image.alpha_composite(img, l)
    zoom_src = img.crop((int(bx), int(by), int(bx + bs), int(by + bs)))
    zs = int(S * 0.24)
    zx, zy = int(S * 0.62), int(S * 0.60)
    zoom = zoom_src.resize((zs, zs), Image.Resampling.LANCZOS)
    img.paste(zoom, (zx, zy))
    dr = ImageDraw.Draw(img)
    dr.rectangle([bx, by, bx + bs, by + bs], outline=(255, 255, 255, 255), width=lw)
    dr.rectangle([zx, zy, zx + zs, zy + zs], outline=(255, 255, 255, 255), width=lw)
    # scale bar
    dr.rectangle([zx + zs * 0.55, zy + zs * 0.84, zx + zs * 0.88, zy + zs * 0.88],
                 fill=(255, 255, 255, 255))

    # subtle top highlight
    hl = Image.fromarray((np.clip(0.10 - yy * 0.25, 0, 1) * 255).astype(np.uint8))
    white = Image.new('RGBA', (S, S), (255, 255, 255, 0))
    white.putalpha(hl)
    img = Image.alpha_composite(img, white)

    img.putalpha(ImageChops.multiply(img.getchannel('A'), mask))
    # drop shadow under the rounded square
    shadow = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    sh = mask.filter(ImageFilter.GaussianBlur(S * 0.012)).point(lambda v: int(v * 0.45))
    shadow.putalpha(ImageChops.offset(sh, 0, int(S * 0.008)))
    final = Image.alpha_composite(shadow, img).resize((1024, 1024), Image.Resampling.LANCZOS)

    OUT.mkdir(parents=True, exist_ok=True)
    final.save(OUT / 'icon.png')
    final.save(OUT / 'icon.icns', sizes=[(16, 16), (32, 32), (64, 64), (128, 128),
                                         (256, 256), (512, 512), (1024, 1024)])
    print('wrote', OUT / 'icon.png', OUT / 'icon.icns')


if __name__ == '__main__':
    main()
