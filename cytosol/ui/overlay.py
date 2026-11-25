"""CanvasOverlay — one pen table for everything drawn over the image
(design system ``hig-canvas-overlay``, measurement-plots).

The colours are data colours (measurement-plots: not UI tokens); the table
fixes colour, width and dash per kind and state so every module draws the
same: ``pen(kind, state)``. States: ``normal``, ``hover``, ``selected``,
``edit``. The name label over a hovered ROI is a capsule (white 92 %,
radius 10, headline 11) — :func:`label_capsule`; edit handles are white
8 px squares (resize) or 6 px dots (points) with the selection colour edge.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainterPath, QPen

YELLOW = (255, 220, 0)
SELECT = (255, 255, 0)
DASH = {'solid': None, 'dash': [5, 4], 'dot': [1, 3], 'nucleus': [4, 3]}

# kind: (rgba, width, dash) for the normal state; None colour = the caller's
# own data colour (per-cell colours, FRAP roles, track classes)
PENS = {
    'cell': (None, 1.6, 'solid'),
    'cell-unsure': (None, 1.6, 'dash'),
    'nucleus': ((255, 255, 255, 140), 1.0, 'nucleus'),
    'particle': ((255, 0, 255, 255), 1.2, 'solid'),
    'contour': ((255, 150, 0, 255), 1.2, 'solid'),
    'region': ((0, 255, 255, 255), 1.0, 'solid'),
    'crop': ((255, 255, 255, 230), 2.0, 'dash'),
    'crop-draw': (YELLOW + (255,), 2.0, 'dash'),
    'zoom': ((255, 255, 255, 255), 1.0, 'dash'),
    'line': (YELLOW + (255,), 2.0, 'solid'),
    'line-band': (YELLOW + (160,), 1.0, 'solid'),
    'frap': (None, 2.0, 'solid'),
    'track': (None, 1.2, 'solid'),
    'track-selected': (None, 2.6, 'solid'),
    'signal-ring': ((255, 214, 0, 255), 1.8, 'solid'),
    'signal-ring-off': ((255, 214, 0, 255), 1.8, 'dash'),
    'change-ring': ((60, 220, 90, 255), 2.0, 'solid'),
    'change-ring-off': ((255, 255, 255, 255), 2.0, 'dash'),
    'lasso': (None, 2.0, 'solid'),
    'handle': (YELLOW + (255,), 1.5, 'solid'),
}
# state overrides: (rgba or None = keep, width or None = keep, dash or None = keep)
STATES = {
    'normal': (None, None, None),
    'hover': (None, None, None),
    'selected': (SELECT + (255,), 2.0, 'solid'),
    'edit': (YELLOW + (255,), 2.0, 'solid'),
}
SELECTED_NUCLEUS_ALPHA = 200
HANDLE_RESIZE = 8
HANDLE_POINT = 6


def pen(kind: str, state: str = 'normal', color=None) -> QPen:
    """The cosmetic pen of `kind` in `state` (`color` = the data colour for
    kinds without their own)."""
    rgba, width, dash = PENS[kind]
    s_rgba, s_width, s_dash = STATES.get(state, STATES['normal'])
    if kind == 'nucleus' and state == 'selected':
        s_rgba, s_width, s_dash = (255, 255, 255, SELECTED_NUCLEUS_ALPHA), None, None
    if kind in ('crop', 'crop-draw') and state == 'selected':
        s_rgba = YELLOW + (255,)
    if kind == 'handle':
        s_rgba = s_width = s_dash = None
    c = s_rgba or rgba
    q = QColor(*c) if c is not None else QColor(color if color is not None else QColor(255, 255, 255))
    p = QPen(q)
    p.setCosmetic(True)
    p.setWidthF(s_width or width)
    d = DASH[s_dash or dash]
    if d is None:
        p.setStyle(Qt.PenStyle.SolidLine)
    else:
        p.setDashPattern(d)
    return p


def handle_brush(points: bool) -> QColor:
    return QColor(30, 30, 30) if points else QColor(255, 255, 255)


LABEL_FILL = (255, 255, 255, 235)  # white 92 %
LABEL_TEXT = (29, 29, 31)
LABEL_RADIUS = 10
LABEL_PAD = (8, 3)


def label_font(base: QFont) -> QFont:
    f = QFont(base)
    f.setPixelSize(11)
    f.setWeight(QFont.Weight.DemiBold)
    return f


def label_capsule(text_rect: QRectF) -> QPainterPath:
    """The capsule path around a label's text rectangle."""
    px, py = LABEL_PAD
    r = text_rect.adjusted(-px, -py, px, py)
    path = QPainterPath()
    path.addRoundedRect(r, min(LABEL_RADIUS, r.height() / 2), min(LABEL_RADIUS, r.height() / 2))
    return path
