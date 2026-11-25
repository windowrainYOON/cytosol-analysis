"""Window — every window the app opens (design system ``hig-window``).

Variants (``Window`` component, component library v0.75):

============  ==========================================================
``alert``     :class:`Alert` — question / warning / error (``ui.dialogs``)
``prompt``    one field + verb button (``ui.dialogs.get_text`` …)
``progress``  :class:`ui.dialogs.Progress`
``task``      :class:`RoundedDialog` — a small work window (이미지 묶기,
              입자 기준 잡기, 라벨, 검토 고르기 …)
``settings``  :class:`SettingsWindow` — 환경설정, 내보내기 (system title bar)
``wizard``    :class:`WizardWindow` — 새 그래프 step flow
``results``   :class:`ResultsWindow` — 측정 현황, 파이프라인 보관함
``document``  :class:`DocumentWindow` — 그래프 편집 창, Figure 창
============  ==========================================================

The floating variants (alert, prompt, progress, task) are frameless with a
rounded panel (``theme.WINDOW_RADIUS`` 18) and one soft shadow; the large
variants keep the system title bar, whose corners and shadow the OS draws.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMainWindow

VARIANTS = ('alert', 'prompt', 'progress', 'task', 'settings', 'wizard', 'results', 'document')


def _offscreen() -> bool:
    return QApplication.platformName() in ('offscreen', 'minimal')


class RoundedDialog(QDialog):
    """A floating window (variant ``task`` and the base of alert / prompt /
    progress): a frameless window with a rounded panel (`WINDOW_RADIUS`) and
    one soft float shadow; drag anywhere on the panel's background to move it.
    Put the content into ``self.body`` (a QVBoxLayout with padding 20);
    ``self.title`` is the headline at the top."""

    variant = 'task'

    def __init__(self, parent=None, title: str = '', text: str = ''):
        from PySide6.QtGui import QColor as _QColor  # noqa: PLC0415
        from PySide6.QtWidgets import (  # noqa: PLC0415
            QFrame, QGraphicsDropShadowEffect, QVBoxLayout)

        from .. import theme  # noqa: PLC0415

        super().__init__(parent)
        self.setWindowTitle(title)
        self.setProperty('hig_float', True)
        self.setProperty('hig_window', self.variant)
        offscreen = _offscreen()
        if not offscreen:
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        outer = QVBoxLayout(self)
        m = 0 if offscreen else theme.WINDOW_SHADOW
        outer.setContentsMargins(m, m - 8 if m else 0, m, m + 8 if m else 0)
        self.panel = QFrame()
        self.panel.setObjectName('hig_window_panel')
        if not offscreen:
            fx = QGraphicsDropShadowEffect(self.panel)
            fx.setBlurRadius(32)
            fx.setOffset(0, 8)
            fx.setColor(_QColor(0, 0, 0, 46))
            self.panel.setGraphicsEffect(fx)
        outer.addWidget(self.panel)
        self.body = QVBoxLayout(self.panel)
        self.body.setContentsMargins(20, 20, 20, 20)
        self.body.setSpacing(8)
        self.title = QLabel(title)
        theme.text_style(self.title, 'headline')
        self.title.setWordWrap(True)
        self.body.addWidget(self.title)
        self.text = QLabel(text)
        self.text.setWordWrap(True)
        theme.text_style(self.text, 'callout', secondary=True)
        self.text.setVisible(bool(text))
        self.body.addWidget(self.text)
        self.body.addSpacing(4)
        self._drag = None

    def button_row(self, *buttons, default=None, leading=()):
        """Buttons at the end of one row: [leading …] ⟷ [secondary] [default] —
        the default last and prominent (Return); `leading` (a destructive
        『저장 안 함』) sits at the start, set apart."""
        from PySide6.QtWidgets import QHBoxLayout  # noqa: PLC0415

        from .. import theme  # noqa: PLC0415

        row = QHBoxLayout()
        for b in leading:
            row.addWidget(b)
        row.addStretch(1)
        for b in buttons:
            row.addWidget(b)
        if default is not None:
            theme.prominent(default)
            default.setDefault(True)
            default.setAutoDefault(True)
        self.body.addSpacing(8)
        self.body.addLayout(row)
        return row

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._drag is not None and ev.buttons() & Qt.MouseButton.LeftButton:
            self.move(ev.globalPosition().toPoint() - self._drag)
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        self._drag = None
        super().mouseReleaseEvent(ev)

    def place_on(self, widget, top: bool = True):
        """A short question sits at the top centre of `widget` (the canvas);
        a work window in the middle of the screen."""
        self.adjustSize()
        if widget is None:
            return
        g = widget.mapToGlobal(widget.rect().topLeft())
        x = g.x() + (widget.width() - self.width()) // 2
        y = g.y() + (40 if top else (widget.height() - self.height()) // 2)
        self.move(max(x, 0), max(y, 0))


def ask(parent, title: str, text: str, primary: str, secondary: str, near=None) -> bool:
    """A question window (variant ``alert``): True = the primary
    (recommended) action, False = the secondary one or Escape."""
    from PySide6.QtWidgets import QPushButton  # noqa: PLC0415

    dlg = RoundedDialog(parent, title, text)
    dlg.setProperty('hig_window', 'alert')
    a = QPushButton(secondary)
    b = QPushButton(primary)
    a.clicked.connect(dlg.reject)
    b.clicked.connect(dlg.accept)
    dlg.button_row(a, b, default=b)
    dlg.place_on(near)
    return dlg.exec() == 1


class _SystemWindow:
    """Large windows keep the system title bar; this only names the variant."""

    variant = 'settings'

    def _mark(self):
        self.setProperty('hig_window', self.variant)


class SettingsWindow(QDialog, _SystemWindow):
    """Window variant ``settings`` (환경설정, 내보내기)."""

    variant = 'settings'

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._mark()


class WizardWindow(QDialog, _SystemWindow):
    """Window variant ``wizard`` (새 그래프: 종류 → 축 배치 → 그룹)."""

    variant = 'wizard'

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._mark()


class ResultsWindow(QDialog, _SystemWindow):
    """Window variant ``results`` (측정 현황, 파이프라인, 보관함)."""

    variant = 'results'

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._mark()


class DocumentWindow(QMainWindow, _SystemWindow):
    """Window variant ``document`` (그래프 편집 창, Figure 창)."""

    variant = 'document'

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._mark()
