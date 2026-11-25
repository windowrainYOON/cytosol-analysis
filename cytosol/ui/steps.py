"""Steps — the step chips of a step flow (design system ``hig-steps``).

A row of capsule chips joined by ›: a passed step = accent tint + ✓ (click
to go back to it, ``stepClicked(i)``), the current step = accent fill with
white text, the steps to come = grey. Used by 새 그래프 (종류 → 축 배치 → 그룹).
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFont, QPainter, QPainterPath
from PySide6.QtWidgets import QSizePolicy, QWidget

CHIP_H = 28
GAP = 22  # room for the › between chips
PAD = 12


class Steps(QWidget):
    """hig-steps: ``set_step(i)``; ``stepClicked(i)`` for a passed step."""

    stepClicked = Signal(int)

    def __init__(self, steps, parent=None):
        super().__init__(parent)
        self.steps, self.cur = list(steps), 0
        self.setFixedHeight(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self._hover = -1

    def set_step(self, i):
        self.cur = i
        self.update()

    def _label(self, i, name) -> str:
        return ('✓ ' if i < self.cur else f'{i + 1} ') + name

    def _font(self, now: bool) -> QFont:
        f = QFont(self.font())
        f.setWeight(QFont.Weight.DemiBold if now else QFont.Weight.Medium)
        return f

    def _rects(self) -> list[QRectF]:
        out, x = [], 0.0
        y = (self.height() - CHIP_H) / 2
        for i, name in enumerate(self.steps):
            from PySide6.QtGui import QFontMetrics  # noqa: PLC0415
            w = QFontMetrics(self._font(i == self.cur)).horizontalAdvance(self._label(i, name)) + 2 * PAD
            out.append(QRectF(x, y, w, CHIP_H))
            x += w + GAP
        return out

    def sizeHint(self) -> QSize:
        r = self._rects()
        return QSize(int(r[-1].right()) + 2 if r else 100, 40)

    def paintEvent(self, _e):
        from .. import theme  # noqa: PLC0415

        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        accent = theme.color('accent')
        for i, (name, r) in enumerate(zip(self.steps, self._rects())):
            done, now = i < self.cur, i == self.cur
            path = QPainterPath()
            path.addRoundedRect(r, CHIP_H / 2, CHIP_H / 2)
            if now:
                qp.fillPath(path, accent)
                fg = theme.color('on-accent')
            elif done:
                tint = theme.color('accent')
                tint.setAlphaF(0.20 if i == self._hover else 0.12)
                qp.fillPath(path, tint)
                fg = accent
            else:
                qp.fillPath(path, theme.color('fill-tertiary'))
                fg = theme.color('label-secondary')
            qp.setFont(self._font(now))
            qp.setPen(fg)
            qp.drawText(r, int(Qt.AlignmentFlag.AlignCenter), self._label(i, name))
            if i < len(self.steps) - 1:
                qp.setPen(theme.color('label-tertiary'))
                qp.setFont(self._font(False))
                qp.drawText(QRectF(r.right(), r.top(), GAP, CHIP_H), int(Qt.AlignmentFlag.AlignCenter), '›')
        qp.end()

    def _at(self, pos) -> int:
        for i, r in enumerate(self._rects()):
            if r.contains(pos):
                return i
        return -1

    def mouseMoveEvent(self, e):
        i = self._at(e.position())
        i = i if 0 <= i < self.cur else -1
        if i != self._hover:
            self._hover = i
            self.setCursor(Qt.CursorShape.PointingHandCursor if i >= 0 else Qt.CursorShape.ArrowCursor)
            self.update()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        self._hover = -1
        self.update()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        i = self._at(e.position())
        if 0 <= i < self.cur and e.button() == Qt.MouseButton.LeftButton:
            self.stepClicked.emit(i)
        super().mouseReleaseEvent(e)


StepBar = Steps  # the name the graph window used before v0.75
