"""EmptyState — what an empty area shows (design system ``hig-empty``).

Icon 32 (label-tertiary), title (headline), one line (callout,
label-secondary), centred at 40 % of the area's height; at most one grey
button for the next action, placed by the caller. ``paint_empty`` draws it
into a view's viewport (image list, data lists); ``EmptyState`` is the
same as a widget (graph window, data card, pipeline library).
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QFont, QPainter
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

ICON = 32


def paint_empty(qp: QPainter, rect, font: QFont, title: str, text: str = '',
                icon: str = 'tray.and.arrow.down'):
    """Draw the empty state into `rect` (a viewport's rect)."""
    from .. import hig_widgets, theme  # noqa: PLC0415

    qp.setRenderHint(QPainter.RenderHint.Antialiasing)
    cy = rect.top() + rect.height() * 0.40
    qp.drawPixmap(round(rect.left() + (rect.width() - ICON) / 2), round(cy - ICON),
                  hig_widgets.pixmap(icon, ICON, 'label-tertiary'))
    f = QFont(font)
    f.setWeight(QFont.Weight.DemiBold)
    qp.setFont(f)
    qp.setPen(theme.color('label'))
    w = rect.width() - 24
    flags = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap
    qp.drawText(QRectF(rect.left() + 12, cy + 10, w, 40), flags, title)
    if text:
        f.setWeight(QFont.Weight.Normal)
        f.setPixelSize(max(10, round(font.pixelSize() * 12 / 13)) if font.pixelSize() > 0 else 12)
        qp.setFont(f)
        qp.setPen(theme.color('label-secondary'))
        qp.drawText(QRectF(rect.left() + 12, cy + 34, w, 60), flags, text)


class EmptyState(QWidget):
    """hig-empty as a widget: icon, title, one line, optional grey button."""

    def __init__(self, title: str, text: str = '', icon: str = 'tray.and.arrow.down',
                 action: str | None = None, parent=None):
        from .. import hig_widgets, theme  # noqa: PLC0415

        super().__init__(parent)
        self.setProperty('hig_empty', True)
        lay = QVBoxLayout(self)
        lay.addStretch(4)
        pic = QLabel()
        pic.setPixmap(hig_widgets.pixmap(icon, ICON, 'label-tertiary'))
        pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(pic)
        self.title = QLabel(title)
        theme.text_style(self.title, 'headline')
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setWordWrap(True)
        lay.addWidget(self.title)
        self.text = QLabel(text)
        theme.text_style(self.text, 'callout', secondary=True)
        self.text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text.setWordWrap(True)
        self.text.setVisible(bool(text))
        lay.addWidget(self.text)
        self.button = None
        if action:
            self.button = QPushButton(action)
            lay.addWidget(self.button, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addStretch(6)
