"""Pseudo-color microscopy channels and burn in a scale bar.

All drawing happens at the image's native pixel grid, so the scale bar length
in pixels is exactly ``length_um / pixel_size_um``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .io import Image

# used for channels whose file stores no color
FALLBACK_COLORS = [
    (0.0, 1.0, 0.0),  # green
    (1.0, 0.0, 1.0),  # magenta
    (0.0, 0.6, 1.0),  # azure
    (1.0, 0.6, 0.0),  # orange
    (1.0, 1.0, 1.0),  # gray
]

NAMED_COLORS = {
    'gray': (1.0, 1.0, 1.0),
    'grey': (1.0, 1.0, 1.0),
    'white': (1.0, 1.0, 1.0),
    'red': (1.0, 0.0, 0.0),
    'green': (0.0, 1.0, 0.0),
    'blue': (0.0, 0.0, 1.0),
    'cyan': (0.0, 1.0, 1.0),
    'magenta': (1.0, 0.0, 1.0),
    'yellow': (1.0, 1.0, 0.0),
    'orange': (1.0, 0.6, 0.0),
}

NICE_LENGTHS_UM = [0.5, 1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000]


def parse_color(value) -> tuple[float, float, float]:
    """Accept a name ('green'), '#RRGGBB' or an (r, g, b) tuple in 0..1 or 0..255."""
    if isinstance(value, str):
        v = value.strip().lower()
        if v in NAMED_COLORS:
            return NAMED_COLORS[v]
        if v.startswith('#') and len(v) in (7, 9):
            v = v[-6:]
            return tuple(int(v[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
        raise ValueError(f'unknown color {value!r}')
    rgb = tuple(float(c) for c in value)
    if max(rgb) > 1:
        rgb = tuple(c / 255.0 for c in rgb)
    return rgb


def channel_colors(image: Image, overrides: dict | None = None) -> list:
    """Per-channel colors: user override > file metadata > fallback palette.

    overrides maps channel index or channel name to a color.
    """
    overrides = overrides or {}
    colors = []
    for i, name in enumerate(image.channels):
        if i in overrides or name in overrides:
            colors.append(parse_color(overrides.get(i, overrides.get(name))))
        elif i < len(image.colors) and image.colors[i] is not None:
            colors.append(tuple(image.colors[i]))
        else:
            colors.append(FALLBACK_COLORS[i % len(FALLBACK_COLORS)])
    return colors


def project(image: Image, z='mip') -> np.ndarray:
    """Return a (C, Y, X) plane: 'mip' (max projection), 'mid' or a z index."""
    data = image.data
    if z == 'mip':
        return data.max(axis=1)
    if z == 'mid':
        return data[:, data.shape[1] // 2]
    return data[:, int(z)]


def normalize(plane: np.ndarray, low=0.5, high=99.8) -> np.ndarray:
    """Percentile contrast stretch to 0..1."""
    lo, hi = np.percentile(plane, [low, high])
    return np.clip((plane - lo) / max(hi - lo, 1e-12), 0.0, 1.0)


def colorize(planes: np.ndarray, colors, low=0.5, high=99.8, gamma=1.0) -> np.ndarray:
    """Additively blend (C, Y, X) planes into one (Y, X, 3) float RGB image."""
    rgb = np.zeros(planes.shape[1:] + (3,), np.float32)
    for plane, color in zip(planes, colors):
        n = normalize(plane, low, high)
        if gamma != 1.0:
            n = n ** gamma
        rgb += n[..., None] * np.asarray(color, np.float32)
    return np.clip(rgb, 0.0, 1.0)


def nice_scale_length(width_px: int, pixel_um: float, fraction=0.2) -> float:
    """Largest 'nice' length (µm) not exceeding fraction of the image width."""
    target = width_px * pixel_um * fraction
    fits = [v for v in NICE_LENGTHS_UM if v <= target]
    return fits[-1] if fits else NICE_LENGTHS_UM[0]


def _font(size: int):
    """A TrueType font with a µ glyph (DejaVu Sans ships with matplotlib)."""
    from PIL import ImageFont

    try:
        from matplotlib import font_manager

        path = font_manager.findfont('DejaVu Sans', fallback_to_default=True)
        return ImageFont.truetype(path, size), True
    except Exception:
        return ImageFont.load_default(size=size), False


def _format_um(length_um: float, has_mu: bool = True) -> str:
    return f"{length_um:g} {'µm' if has_mu else 'um'}"


def add_scale_bar(
    rgb: np.ndarray,
    pixel_um: float,
    length_um: float | None = None,
    position: str = 'lower right',
    color=(1.0, 1.0, 1.0),
    label: bool = True,
    thickness_px: int | None = None,
    margin_px: int | None = None,
    font_px: int | None = None,
) -> tuple[np.ndarray, float]:
    """Draw a scale bar onto an (Y, X, 3) float RGB image.

    Returns the new image and the bar length in µm actually drawn.
    """
    from PIL import Image as PILImage
    from PIL import ImageDraw

    h, w = rgb.shape[:2]
    if length_um is None:
        length_um = nice_scale_length(w, pixel_um)
    bar_px = int(round(length_um / pixel_um))
    thickness_px = thickness_px or max(2, round(h * 0.012))
    margin_px = margin_px or max(4, round(w * 0.03))
    font_px = font_px or max(10, round(h * 0.04))

    img = PILImage.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8))
    draw = ImageDraw.Draw(img)
    fill = tuple(int(round(c * 255)) for c in parse_color(color))

    right = 'right' in position
    bottom = 'lower' in position or 'bottom' in position
    x0 = w - margin_px - bar_px if right else margin_px
    y0 = h - margin_px - thickness_px if bottom else margin_px
    draw.rectangle([x0, y0, x0 + bar_px - 1, y0 + thickness_px - 1], fill=fill)

    if label:
        font, has_mu = _font(font_px)
        text = _format_um(length_um, has_mu)
        tw = draw.textlength(text, font=font)
        tx = x0 + (bar_px - tw) / 2
        gap = max(2, thickness_px // 2)
        if bottom:
            ty = y0 - gap - font_px
        else:
            ty = y0 + thickness_px + gap
        draw.text((tx, ty), text, fill=fill, font=font)

    return np.asarray(img, np.float32) / 255.0, length_um


def add_label(rgb: np.ndarray, text: str, color=(1.0, 1.0, 1.0), font_px=None,
              position: str = 'upper left') -> np.ndarray:
    """Write a channel name in a corner."""
    from PIL import Image as PILImage
    from PIL import ImageDraw

    h, w = rgb.shape[:2]
    font_px = font_px or max(10, round(h * 0.04))
    margin = max(4, round(w * 0.03))
    img = PILImage.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8))
    draw = ImageDraw.Draw(img)
    font, _ = _font(font_px)
    tw = draw.textlength(text, font=font)
    x = w - margin - tw if 'right' in position else margin
    y = h - margin - font_px if 'lower' in position else margin
    draw.text((x, y), text, fill=tuple(int(c * 255) for c in parse_color(color)), font=font)
    return np.asarray(img, np.float32) / 255.0


def render(
    image: Image,
    out_dir,
    prefix: str = 'image',
    z='mip',
    colors: dict | None = None,
    scale_um: float | None = None,
    scale_position: str = 'lower right',
    labels: bool = True,
    low: float = 0.5,
    high: float = 99.8,
) -> dict:
    """Save a colored composite and one colored PNG per channel, with scale bars.

    Returns {'files': [...], 'colors': {...}, 'scale_um': float}.
    """
    from PIL import Image as PILImage

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pixel_um = image.voxel_size_um.get('X')
    if not pixel_um:
        raise ValueError('pixel size unknown; cannot draw a scale bar')

    cols = channel_colors(image, colors)
    planes = project(image, z)
    files = []

    def save(rgb, name, label_text=None, label_color=(1, 1, 1)):
        if labels and label_text:
            rgb = add_label(rgb, label_text, label_color)
        rgb, used = add_scale_bar(rgb, pixel_um, scale_um, scale_position)
        path = out_dir / f'{prefix}_{name}.png'
        PILImage.fromarray((rgb * 255).astype(np.uint8)).save(path)
        files.append(str(path))
        return used

    used = scale_um
    for i, (plane, color) in enumerate(zip(planes, cols)):
        rgb = colorize(plane[None], [color], low, high)
        safe = ''.join(ch if ch.isalnum() or ch in '-_' else '_' for ch in image.channels[i])
        used = save(rgb, f'C{i}_{safe}', image.channels[i], color)
    if len(cols) > 1:
        rgb = colorize(planes, cols, low, high)
        used = save(rgb, 'composite')

    return {
        'files': files,
        'colors': dict(zip(image.channels, cols)),
        'scale_um': used,
        'pixel_um': pixel_um,
    }
