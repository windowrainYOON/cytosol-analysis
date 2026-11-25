"""PageStack — pages of which one is shown, as tall as the page shown (자동 / 수동 detection pages, canvas view panes)."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import theme


class _ModePages(QWidget):
    """The 자동 / threshold만 pages, one shown at a time (QStackedWidget API).
    Unlike a QStackedWidget it is as tall as the page shown, whose rows come
    and go with 검출 자동화 and 세부 설정."""

    currentChanged = Signal(int)

    def __init__(self):
        super().__init__()
        self._pages = []
        self._cur = -1
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

    def addWidget(self, page):
        self._pages.append(page)
        self.layout().addWidget(page)
        if self._cur < 0:
            self._cur = 0
        page.setVisible(len(self._pages) - 1 == self._cur)
        return len(self._pages) - 1

    def count(self):
        return len(self._pages)

    def widget(self, i):
        return self._pages[i] if 0 <= i < len(self._pages) else None

    def currentIndex(self):
        return self._cur

    def currentWidget(self):
        return self.widget(self._cur)

    def indexOf(self, page):
        return self._pages.index(page) if page in self._pages else -1

    def setCurrentIndex(self, i):
        if not 0 <= i < len(self._pages) or i == self._cur:
            return
        self._cur = i
        for k, p in enumerate(self._pages):
            p.setVisible(k == i)
        self.currentChanged.emit(i)

    def setCurrentWidget(self, page):
        self.setCurrentIndex(self.indexOf(page))


class _ModePane(QWidget):
    """A view with a chip row above and a hint row below (as the mockups)."""

    def __init__(self, view: QWidget, hint: str, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.top = top = QHBoxLayout()
        self.status = theme.StatusLabel('', 'info')
        self.status.setWordWrap(False)
        self.right = theme.StatusLabel('', 'neutral')
        self.right.setWordWrap(False)
        top.addWidget(self.status)
        top.addStretch()
        top.addWidget(self.right)
        lay.addLayout(top)
        self.view = view
        lay.addWidget(view, 1)
        self.bottom = QHBoxLayout()
        self.hint = QLabel(hint)
        self.hint.setWordWrap(True)
        theme.hint(self.hint)
        self.bottom.addWidget(self.hint, 1)
        lay.addLayout(self.bottom)
