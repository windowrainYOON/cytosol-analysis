"""Field — text and number inputs (design system TextField / ``hig-textarea``).

Variants:

* ``FloatEdit`` (Field variant ``float``): a number field that keeps full
  precision (axis limits, tick spacing); ``valueChanged(float)`` on Enter.
* ``TextArea`` (``hig-textarea``): several lines, the TextField fill, at
  least 3 lines, grows with its content to ``max_lines`` then scrolls;
  Enter = new line, ⌘Enter / Ctrl+Enter = ``submitted``.
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLineEdit, QPlainTextEdit, QSizePolicy


class FloatEdit(QLineEdit):
    """A number field that keeps full precision (axis limits, tick spacing)."""

    valueChanged = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMaximumWidth(90)
        self.setProperty('hig_field', 'float')
        self.editingFinished.connect(self._done)

    def value(self) -> float:
        t = self.text().replace(',', '.').strip()
        try:
            if '/' in t:  # 1/60 for s -> min
                a, b = t.split('/', 1)
                return float(a) / float(b)
            return float(t)
        except (ValueError, ZeroDivisionError):
            return float('nan')

    def setValue(self, v: float):
        self.setText('' if v is None or not math.isfinite(v) else f'{v:.6g}')

    def _done(self):
        v = self.value()
        if math.isfinite(v):
            self.valueChanged.emit(v)


class TextArea(QPlainTextEdit):
    """hig-textarea: TextField fill, radius 8, padding 8, no border; 3 lines
    at least, grows to `max_lines`, then scrolls; ⌘Enter = ``submitted``."""

    submitted = Signal()
    min_lines = 3
    max_lines = 8

    def __init__(self, parent=None, read_only: bool = False, placeholder: str = ''):
        super().__init__(parent)
        self.setProperty('hig_field', 'textarea')
        self.setReadOnly(read_only)
        if placeholder:
            self.setPlaceholderText(placeholder)
        self.setTabChangesFocus(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.document().contentsChanged.connect(self._fit)
        self._fit()

    def _fit(self):
        fm = self.fontMetrics()
        lines = max(self.min_lines, min(self.max_lines, int(self.document().size().height()) or 1))
        m = self.contentsMargins()
        doc_m = self.document().documentMargin()
        self.setFixedHeight(int(lines * fm.lineSpacing() + 2 * doc_m + m.top() + m.bottom() + 8))

    def keyPressEvent(self, e):
        mods = e.modifiers()
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and mods & (
                Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier):
            self.submitted.emit()
            return
        super().keyPressEvent(e)
