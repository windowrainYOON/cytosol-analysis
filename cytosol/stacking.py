"""이미지 묶기 (owner request 2026-11-13, v0.62): several image files shown
as one stack image along channels (C), focal planes (Z) or time (T).

Nothing is written to disk: a stack is a `StackSpec` (the source files, their
order, the channel each one gives, names and colours) kept in the project,
and `build_image` makes a lazy `io.Image` whose planes are read from the
sources when they are needed.  Every tab, the Figure window, exports and
batch analysis see an ordinary image.

`find_rgb_sets` finds ImageJ RGB splits (``…_Ch1_Red / _Ch2_Green /
_Ch3_Blue``) among loaded files, the rule of Mito Analyzer's
``find_siblings``; `same_pattern_sets` finds the other files named like a
picked set (Control_01_… → Control_02_…)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

AXES = {'C': '채널', 'Z': 'Z', 'T': '시간'}
MISMATCH = {'refuse': '묶지 않고 알림', 'crop': '가운데 맞춰 자르기', 'pad': '빈 곳을 0으로 채우기'}
CHANNEL_RX = re.compile(r'(ch\d+[_\- ]*)?(red|green|blue)', re.I)
COLOR_RGB = {'red': (1.0, 0.0, 0.0), 'green': (0.0, 1.0, 0.0), 'blue': (0.0, 0.0, 1.0)}
COLOR_INDEX = {'red': 0, 'green': 1, 'blue': 2}


@dataclass
class StackSource:
    path: str
    channel: int = -1          # channel of the file used (-1 = all of them)
    name: str = ''             # channel name in the stack ('' = the file's)
    color: list | None = None  # (r, g, b) 0..1, None = the file's
    load: dict = field(default_factory=dict)  # read_image keywords


@dataclass
class StackSpec:
    axis: str = 'C'
    sources: list = field(default_factory=list)
    name: str = ''
    interval_s: float = 0.0    # T: time between files (0 = 1 s steps)
    z_step_um: float = 0.0     # Z: distance between files (0 = unknown)
    mismatch: str = 'refuse'
    fold: bool = True          # originals shown (greyed) under the stack only

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> 'StackSpec':
        d = dict(d or {})
        srcs = [StackSource(**s) for s in d.pop('sources', [])]
        keep = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(sources=srcs, **keep)


class StackError(ValueError):
    pass


# ---------------------------------------------------------------------------
# names
# ---------------------------------------------------------------------------

def color_of_name(name: str) -> str | None:
    m = CHANNEL_RX.search(Path(name).stem)
    return m.group(2).lower() if m else None


def sort_key(path) -> tuple:
    """Ch number, else colour order, else the numbers in the name."""
    stem = Path(path).stem
    m = re.search(r'ch[_\- ]?(\d+)', stem, re.I)
    if m:
        return (0, int(m.group(1)), stem)
    c = color_of_name(stem)
    if c:
        return (1, COLOR_INDEX[c], stem)
    nums = [int(x) for x in re.findall(r'\d+', stem)]
    return (2, nums[-1] if nums else 0, stem)


def sample_name(paths) -> str:
    """Common start of the file names without the channel tag:
    Control_01_Ch1_Red.tif + … → Control_01."""
    stems = [Path(p).stem for p in paths]
    if not stems:
        return ''
    pre = stems[0]
    for s in stems[1:]:
        while not s.startswith(pre):
            pre = pre[:-1]
    pre = re.sub(r'[_\- ]*(ch)?[_\- ]*$', '', pre, flags=re.I)
    if not pre:
        pre = CHANNEL_RX.sub('', stems[0]).strip('_- ') or stems[0]
    return pre


def find_rgb_sets(paths) -> list[list[Path]]:
    """Complete …Red / …Green / …Blue triplets (TIFF) among `paths`, each in
    red, green, blue order."""
    by_key = {}
    for p in paths:
        p = Path(p)
        if p.suffix.lower() not in ('.tif', '.tiff'):
            continue
        m = None
        for m in CHANNEL_RX.finditer(p.name):
            pass
        if m is None:
            continue
        key = (str(p.parent), p.name[:m.start()].lower(), p.name[m.end():].lower())
        by_key.setdefault(key, {})[m.group(2).lower()] = p
    sets = []
    for key in sorted(by_key):
        d = by_key[key]
        if len(d) == 3:
            sets.append([d['red'], d['green'], d['blue']])
    return sets


def same_pattern_sets(picked, others) -> list[tuple[str, list[Path]]]:
    """Other files named like the picked set: the picked names share a start
    (Control_01_Ch); each one's rest (1_Red.tif …) is looked for after another
    start.  Returns [(name, paths in the picked order)] for complete sets."""
    names = [Path(p).name for p in picked]
    if len(names) < 2:
        return []
    pre = names[0]
    for n in names[1:]:
        while not n.startswith(pre):
            pre = pre[:-1]
    rests = [n[len(pre):] for n in names]
    if not all(rests):
        return []
    found = {}
    for o in others:
        o = Path(o)
        for i, r in enumerate(rests):
            if o.name.endswith(r) and len(o.name) > len(r):
                start = o.name[:-len(r)]
                if start != pre:
                    found.setdefault(start, {})[i] = o
    out = []
    for start in sorted(found):
        d = found[start]
        if len(d) == len(rests):
            paths = [d[i] for i in range(len(rests))]
            nm = re.sub(r'[_\- ]*(ch)?[_\- ]*$', '', start, flags=re.I) or start
            out.append((nm, paths))
    return out


def count_text(spec: StackSpec, image=None) -> str:
    if spec.axis == 'C':
        n = len(image.channels) if image is not None else len(spec.sources)
        return f'{n}채널'
    return f'{spec.axis} {len(spec.sources)}'


# ---------------------------------------------------------------------------
# building the image
# ---------------------------------------------------------------------------

def _src_plane(img, t, z):
    """(C, Y, X) of one source at timepoint t and z ('mip', 'mid' or index)."""
    t = int(min(t, img.nt - 1))
    if img.lazy:
        return np.asarray(img.plane_loader(t, z))
    img.load_time(t)
    return np.asarray(img.plane(z))


def _fit(a: np.ndarray, hw, how: str) -> np.ndarray:
    h, w = hw
    if a.shape[-2:] == (h, w):
        return a
    out = np.zeros(a.shape[:-2] + (h, w), a.dtype)
    ah, aw = a.shape[-2:]
    # centred: crop what is larger, pad what is smaller
    sy, sx = max((ah - h) // 2, 0), max((aw - w) // 2, 0)
    dy, dx = max((h - ah) // 2, 0), max((w - aw) // 2, 0)
    ch, cw = min(ah, h), min(aw, w)
    out[..., dy:dy + ch, dx:dx + cw] = a[..., sy:sy + ch, sx:sx + cw]
    return out


def check(images, spec: StackSpec) -> tuple[bool, str]:
    """(all the same, one line saying so) for size, pixel size and type."""
    sizes = {tuple(im.shape[-2:]) for im in images}
    pxs = {round(float(im.voxel_size_um.get('X') or 0), 4) for im in images}
    dts = set()
    for im in images:
        try:
            dts.add(str(_src_plane(im, 0, 'mid').dtype))
        except Exception:  # noqa: BLE001
            pass
    if not images:
        return False, '파일이 없습니다'
    h, w = images[0].shape[-2:]
    px = images[0].voxel_size_um.get('X')
    bits = ', '.join(sorted(dts)) or '?'
    desc = f'{w} × {h} px · {px:.4f} µm/px · {bits}' if px else f'{w} × {h} px · {bits}'
    if len(sizes) == 1 and len(pxs) <= 1 and len(dts) <= 1:
        return True, f'{desc} — 모두 같습니다'
    parts = []
    if len(sizes) > 1:
        parts.append('크기 ' + ' / '.join(f'{b}×{a}' for a, b in sorted(sizes)))
    if len(pxs) > 1:
        parts.append('픽셀 크기 ' + ' / '.join(f'{p:g}' for p in sorted(pxs)))
    if len(dts) > 1:
        parts.append('형식 ' + ' / '.join(sorted(dts)))
    return False, '다름: ' + ', '.join(parts)


def _indices(img, src: StackSource) -> list[int]:
    if src.channel is not None and 0 <= src.channel < len(img.channels):
        return [src.channel]
    return list(range(len(img.channels)))


def default_channel(img, path) -> int:
    """An RGB file named …Red / …Green / …Blue gives that channel; else all."""
    c = color_of_name(Path(path).name)
    if c and len(img.channels) == 3:
        return COLOR_INDEX[c]
    return -1


def build_image(spec: StackSpec, images=None):
    """The stack as a lazy io.Image.  `images` = the sources already read."""
    from .imageid import short_id
    from .io import Image, read_image

    if not spec.sources:
        raise StackError('묶을 파일이 없습니다')
    if images is None:
        images = [read_image(s.path, **(s.load or {})) for s in spec.sources]
    same, line = check(images, spec)
    if not same and spec.mismatch == 'refuse':
        raise StackError(f'크기가 달라 묶지 않았습니다 ({line})')
    sizes = [im.shape[-2:] for im in images]
    if spec.mismatch == 'pad':
        hw = (max(s[0] for s in sizes), max(s[1] for s in sizes))
    else:
        hw = (min(s[0] for s in sizes), min(s[1] for s in sizes))
    idx = [_indices(im, s) for im, s in zip(images, spec.sources)]
    first = images[0]

    def names_colors(im, src, ii):
        names, cols = [], []
        for k in ii:
            nm = im.channels[k]
            if src.name:
                nm = src.name if len(ii) == 1 else f'{src.name} {nm}'
            names.append(nm)
            col = src.color if src.color else (im.colors[k] if k < len(im.colors) else None)
            cols.append(tuple(col) if col else None)
        return names, cols

    times = [0.0]
    if spec.axis == 'C':
        channels, colors, ranges = [], [], []
        for im, src, ii in zip(images, spec.sources, idx):
            n, c = names_colors(im, src, ii)
            channels += n
            colors += c
            ranges += [im.ranges[k] if k < len(im.ranges) else None for k in ii]
        nz = min(im.shape[1] for im in images)
        nt = min(im.nt for im in images)
        times = list(first.times[:nt])

        def plane(t, z):
            if isinstance(z, int) and z >= nz:
                z = nz - 1
            return np.concatenate([_fit(_src_plane(im, t, z)[ii], hw, spec.mismatch)
                                   for im, ii in zip(images, idx)], axis=0)
    elif spec.axis == 'Z':
        channels, colors = names_colors(first, spec.sources[0], idx[0])
        ranges = [first.ranges[k] if k < len(first.ranges) else None for k in idx[0]]
        nz = len(images)
        nt = min(im.nt for im in images)
        times = list(first.times[:nt])

        def one(i, t):
            im = images[i]
            return _fit(_src_plane(im, t, 'mip')[idx[i]], hw, spec.mismatch)

        def plane(t, z):
            if z == 'mip':
                return np.max(np.stack([one(i, t) for i in range(nz)]), axis=0)
            if z == 'mid':
                z = nz // 2
            return one(int(min(z, nz - 1)), t)
    elif spec.axis == 'T':
        channels, colors = names_colors(first, spec.sources[0], idx[0])
        ranges = [first.ranges[k] if k < len(first.ranges) else None for k in idx[0]]
        nz = min(im.shape[1] for im in images)
        nt = len(images)
        step = spec.interval_s or 1.0
        times = [i * step for i in range(nt)]

        def plane(t, z):
            if isinstance(z, int) and z >= nz:
                z = nz - 1
            i = int(min(max(t, 0), nt - 1))
            return _fit(_src_plane(images[i], 0, z)[idx[i]], hw, spec.mismatch)
    else:
        raise StackError(f'알 수 없는 방향: {spec.axis}')

    def loader(t):
        return np.stack([plane(t, z) for z in range(nz)], axis=1)

    vox = dict(first.voxel_size_um)
    if spec.axis == 'Z':
        vox['Z'] = spec.z_step_um or None
    ids = '|'.join(im.metadata.get('image_id', '') for im in images)
    meta = {
        'format': 'STACK',
        'image_id': short_id(f'STACK|{spec.axis}|{ids}'),
        'image_id_source': f'묶음 ({len(images)}개 파일)',
        'source_name': spec.name,
        'stack': {'axis': spec.axis, 'files': [Path(s.path).name for s in spec.sources]},
    }
    if not colors or not any(colors):
        colors = []
    return Image(data=None, channels=channels, voxel_size_um=vox, metadata=meta, colors=colors,
                 times=times, t=0, loader=loader, ranges=ranges,
                 range_notes=[''] * len(ranges), plane_loader=plane,
                 shape=(len(channels), nz, hw[0], hw[1]))


def load_item(spec: StackSpec, images=None):
    from .lut import ImageItem

    image = build_image(spec, images)
    item = ImageItem(path=Path(spec.sources[0].path), image=image,
                     label=spec.name or sample_name([s.path for s in spec.sources]))
    item.stack = spec
    item.reset_luts()
    return item


def spec_for(paths, axis='C', name='', images=None) -> StackSpec:
    """A stack of `paths` in sort order with the default channel per file."""
    from .io import read_image

    paths = sorted((Path(p) for p in paths), key=sort_key)
    if images is None:
        images = [read_image(p) for p in paths]
    srcs = []
    for p, im in zip(paths, images):
        c = default_channel(im, p)
        col = color_of_name(p.name)
        srcs.append(StackSource(str(p), c, col.capitalize() if col else '',
                                list(COLOR_RGB[col]) if col else None))
    return StackSpec(axis=axis, sources=srcs, name=name or sample_name(paths))


def rel_sources(spec: StackSpec, base: Path) -> list[dict]:
    """Source entries for a project: relative and absolute paths."""
    import os

    out = []
    for s in spec.sources:
        p = Path(s.path).resolve()
        try:
            rel = os.path.relpath(p, base)
        except ValueError:
            rel = str(p)
        out.append({'path': rel, 'abs_path': str(p), 'name': p.name})
    return out


def resolve_sources(spec: StackSpec, entries, base: Path, search_dirs=()) -> list[str]:
    """Point the sources at where the files are now; returns the missing names."""
    from .project import resolve_image

    missing = []
    for s, e in zip(spec.sources, entries or []):
        f = resolve_image(e, base, search_dirs)
        if f is None:
            missing.append(e.get('name', s.path))
        else:
            s.path = str(f)
    return missing
