"""ColorWell — colour swatch (design system ``hig-color-well``).

One class for every colour button of the app (LUT channel colour, marker
colours, Figure label / inset colours, graph series colours). A swatch
22 × 22 (radius 6, 1 px separator edge) and a 10 px chevron; while the
colour panel is open the swatch gets a 2 px accent ring. The tool tip names
the colour (name + hex), so the colour is never the only cue.

Variants (``variant=``): ``row`` (end of a settings row, default),
``header`` (beside a channel name), ``inline`` (in a table / series list,
shows the hex value or 자동).

``pick=True`` opens the system colour panel on click and emits ``changed``;
``pick=False`` leaves the click to the caller (which keeps its own handler).
``allow_empty``: right-click = '' (자동). ``RgbColorWell`` is the same well
holding an (r, g, b) tuple 0–1 and emitting ``changed()`` without value.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QColorDialog, QPushButton

SWATCH = 22
RADIUS = 6
CHEVRON = 10
VARIANTS = ('row', 'header', 'inline')
_NAMES = {'#ff0000': '빨강', '#00ff00': '초록', '#0000ff': '파랑', '#ffff00': '노랑',
          '#ff00ff': '자홍', '#00ffff': '청록', '#ffffff': '흰색', '#000000': '검정',
          '#808080': '회색'}


def color_name(hex_: str) -> str:
    """Name + hex for the tool tip (accessibility: colour is never the only cue)."""
    if not hex_:
        return '자동'
    return f'{_NAMES.get(hex_.lower(), "색")} {hex_}'


class ColorWell(QPushButton):
    """Colour swatch button; ``changed(str)`` with the new hex ('' = 자동)."""

    changed = Signal(str)

    def __init__(self, color: str | None = '#000000', parent=None, *, variant: str = 'row',
                 pick: bool = True, allow_empty: bool = False, title: str = '색 고르기'):
        super().__init__(parent)
        self.variant = variant if variant in VARIANTS else 'row'
        self.allow_empty = allow_empty
        self.title = title
        self._color = color or ''
        self._open = False
        self.setProperty('hig_color_well', self.variant)
        self.setFlat(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        if pick:
            self.clicked.connect(self._pick)
        self._update()

    # -- API ---------------------------------------------------------------
    def color(self) -> str:
        return self._color

    def setColor(self, c: str):  # noqa: N802
        self._color = c or ''
        self._update()

    def qcolor(self) -> QColor:
        return QColor(self._color or '#000000')

    def set_open(self, on: bool):
        """The colour panel is open for this well (accent ring)."""
        self._open = on
        self.update()

    # -- look --------------------------------------------------------------
    def _update(self):
        tip = color_name(self._color)
        if self.allow_empty:
            tip += ' · 클릭: 색 고르기 · 오른쪽 클릭: 자동 (시리즈 색)'
        self.setToolTip(tip)
        self.setAccessibleName(tip)
        self.updateGeometry()
        self.update()

    def _text(self) -> str:
        if self.variant != 'inline':
            return '' if self._color else '자동'
        return self._color or '자동'

    def sizeHint(self) -> QSize:
        t = self._text()
        w = SWATCH + 4 + CHEVRON + 8
        if t:
            w += self.fontMetrics().horizontalAdvance(t) + 6
        return QSize(w, max(SWATCH + 6, 28))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, _e):
        from .. import theme  # noqa: PLC0415

        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self.height()
        x = 3.0
        r = QRectF(x, (h - SWATCH) / 2, SWATCH, SWATCH)
        if self._open or self.hasFocus() and self.isDown():
            ring = QPen(theme.color('accent'), 2)
            qp.setPen(ring)
            qp.setBrush(Qt.BrushStyle.NoBrush)
            qp.drawRoundedRect(r.adjusted(-2.5, -2.5, 2.5, 2.5), RADIUS + 2, RADIUS + 2)
        path = QPainterPath()
        path.addRoundedRect(r, RADIUS, RADIUS)
        if self._color:
            qp.fillPath(path, QColor(self._color))
        else:  # 자동: an empty well with a diagonal
            qp.fillPath(path, theme.color('fill-tertiary'))
            qp.setPen(QPen(theme.color('label-tertiary'), 1.2))
            qp.drawLine(r.bottomLeft() + QRectF(2, -2, 0, 0).topLeft(),
                        r.topRight() + QRectF(-2, 2, 0, 0).topLeft())
        qp.setPen(QPen(theme.color('separator-opaque'), 1))
        qp.setBrush(Qt.BrushStyle.NoBrush)
        qp.drawPath(path)
        x = r.right() + 6
        t = self._text()
        fg = theme.color('label' if self.isEnabled() else 'label-tertiary')
        if t:
            qp.setPen(fg)
            w = self.fontMetrics().horizontalAdvance(t)
            qp.drawText(QRectF(x, 0, w + 2, h), int(Qt.AlignmentFlag.AlignVCenter), t)
            x += w + 6
        # chevron.down, 10 px
        qp.setPen(QPen(theme.color('label-secondary'), 1.5, Qt.PenStyle.SolidLine,
                       Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        cy = h / 2
        qp.drawPolyline([QRectF(x, cy - 2, 0, 0).topLeft(), QRectF(x + 4, cy + 2, 0, 0).topLeft(),
                         QRectF(x + 8, cy - 2, 0, 0).topLeft()])
        qp.end()

    # -- picking -------------------------------------------------------------
    def _pick(self):
        self.set_open(True)
        try:
            c = QColorDialog.getColor(self.qcolor(), self, self.title)
        finally:
            self.set_open(False)
        if c.isValid():
            self._accept(c)

    def _accept(self, c: QColor):
        self.setColor(c.name())
        self._emit()

    def _emit(self):
        self.changed.emit(self._color)

    def mousePressEvent(self, e):
        if self.allow_empty and e.button() == Qt.MouseButton.RightButton:
            self.setColor('')
            self._emit()
            return
        super().mousePressEvent(e)


class RgbColorWell(ColorWell):
    """The colour well holding an (r, g, b) tuple 0–1; ``changed()``."""

    changed = Signal()

    def __init__(self, rgb=(1.0, 1.0, 1.0), parent=None, **kw):
        super().__init__('#ffffff', parent, **kw)
        self.set_rgb(rgb)

    def set_rgb(self, rgb):
        self.rgb = tuple(float(c) for c in rgb)
        self.setColor(QColor.fromRgbF(*self.rgb).name())

    def _accept(self, c: QColor):
        self.set_rgb((c.redF(), c.greenF(), c.blueF()))
        self._emit()

    def _emit(self):
        self.changed.emit()
