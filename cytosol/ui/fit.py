"""FitScroll — a fixed-width box whose contents follow its width (design
system rule "고정 폭 상자 안은 반응형", owner rule 2026-11-25, v0.75.1).

A box of fixed width (the inspector, a fixed side pane of a window) never
clips or scrolls its contents sideways. Its page is always exactly as wide
as the box, and the controls inside give way in this order when the page
would be wider:

1. settings-card fields (``theme.SETTINGS_FIELD_W`` 140) shrink together,
   so their edges still line up, down to ``theme.NUMBER_MIN_W`` 80;
2. pop-ups (Select) show their value elided (fewer characters);
3. number fields beside a slider shrink to ``FIT_PLAIN_MIN_W``.

Button rows and long check boxes already wrap (``flow.reflow``,
``FlowLayout``, ``wrapped_check``); labels wrap. When the box gets wider
again every control returns to its own width.

``FitScroll`` is the vertical scroll area of such a box (horizontal scroll
bar always off); ``fit_width(page, width)`` is the step it runs on resize.
``overflow(page, width)`` lists what still does not fit (self-test).
"""
from __future__ import annotations

from .. import i18n

from PySide6.QtCore import QEvent, QTimer
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QAbstractSpinBox, QComboBox, QFormLayout, QFrame, QGroupBox, QLabel, QLineEdit, QScrollArea, QWidget)

FIT_PLAIN_MIN_W = 56  # number field beside a slider, narrowest
FIT_FIELD_MIN_W = 64  # any other field, narrowest (its text scrolls inside)
FIT_LABEL_MIN_W = 48  # a wrapping label, narrowest
FIT_TITLE_PAD = 16  # card title inset (hig_style.ROW_PAD)
FIT_SELECT_CHARS = (10, 7, 4)  # elided Select widths tried in turn


def _save(w: QWidget, what: str, value):
    """Remember a control's own value once, before the fit changes it."""
    saved = w.property('fit_saved') or {}
    if what not in saved:
        saved[what] = value
        w.setProperty('fit_saved', saved)


def _restore(page: QWidget):
    """Every control the fit changed gets its own values back."""
    for w in [page] + page.findChildren(QWidget):
        saved = w.property('fit_saved')
        if not saved:
            continue
        w.setProperty('fit_saved', None)
        if 'title' in saved:
            w.setToolTip(saved['tip'])
            _show_title(w, i18n.tr(w.title()))
        if 'wrap' in saved:
            w.setWordWrap(saved['wrap'])
        if 'policy' in saved:
            w.setSizeAdjustPolicy(saved['policy'])
            w.setMinimumContentsLength(saved['chars'])
        if 'min' in saved:
            w.setMinimumWidth(saved['min'])
        if 'max' in saved:
            w.setMaximumWidth(saved['max'])


def _in_view(w: QWidget, page: QWidget) -> bool:
    """Inside a list / table (cell widgets): the view owns those, the fit
    leaves them alone (moving one into another layout would let the view and
    the layout both delete it)."""
    from PySide6.QtWidgets import QAbstractItemView  # noqa: PLC0415

    p = w.parentWidget()
    while p is not None and p is not page:
        if isinstance(p, QAbstractItemView):
            return True
        p = p.parentWidget()
    return False


def _parts(page: QWidget, cls) -> list:
    """Visible widgets of `cls` in the page, outside lists / tables."""
    return [w for w in page.findChildren(QWidget)
            if isinstance(w, cls) and w.isVisibleTo(page) and not _in_view(w, page)]


def _controls(page: QWidget):
    """Settings fields (one shared width), other fields, pop-ups."""
    from .. import theme  # noqa: PLC0415

    fields, others, selects = [], [], []
    for w in _parts(page, QWidget):
        if isinstance(w, QLineEdit) and isinstance(w.parent(), (QAbstractSpinBox, QComboBox)):
            continue  # the text part of a spin box / editable pop-up
        if isinstance(w, (QAbstractSpinBox, QLineEdit)):
            fixed = w.minimumWidth() == w.maximumWidth() == theme.SETTINGS_FIELD_W
            (fields if fixed and not w.property('hig_plain') else others).append(w)
        elif isinstance(w, QComboBox) and not w.isEditable():
            selects.append(w)
    return fields, others, selects


def _need(page: QWidget) -> int:
    """The page's minimum width now, every layout measured again (inner
    widgets first; `activate` clears the caches of nested layouts in C++, no
    Python wrapper of a nested layout is made: such a wrapper can end up
    owning and deleting it)."""
    for w in reversed(page.findChildren(QWidget)):
        lay = w.layout()
        if lay is not None:
            lay.invalidate()
            lay.activate()
            w.updateGeometry()  # the cached size of its item in the parent layout
    lay = page.layout()
    if lay is not None:
        lay.invalidate()
        lay.activate()
    return page.minimumSizeHint().width()


def fit_width(page: QWidget, width: int) -> bool:
    """Make `page` fit `width` by letting its controls give way (see the
    module notes). Returns True when it fits."""
    from PySide6.QtCore import Qt  # noqa: PLC0415

    from .. import theme  # noqa: PLC0415

    _restore(page)  # the box may have grown: every control at its own width first
    page.setProperty('fit_changed', False)
    need = _need(page)
    if need <= width:
        return True
    page.setProperty('fit_changed', True)  # some controls give way now
    fields, others, selects = _controls(page)

    def narrower(w, to):
        _save(w, 'min', w.minimumWidth())
        _save(w, 'max', w.maximumWidth())
        # no set minimum = the size hint's minimum (a long text): set one
        w.setMinimumWidth(min(w.minimumWidth() or to, to))

    # 1. fields of every card shrink together (edges stay in line)
    if fields:
        fw = max(theme.NUMBER_MIN_W, theme.SETTINGS_FIELD_W - (need - width))
        for w in fields:
            narrower(w, fw)
            w.setMaximumWidth(fw)
        need = _need(page)
        if need <= width:
            return True
    # 2. pop-ups show their value elided
    for chars in FIT_SELECT_CHARS:
        for w in selects:
            _save(w, 'policy', w.sizeAdjustPolicy())
            _save(w, 'chars', w.minimumContentsLength())
            w.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            w.setMinimumContentsLength(chars)
            narrower(w, theme.SELECT_MIN_W)
        need = _need(page)
        if need <= width:
            return True
    # 3. the other fields (beside sliders, in [a – b] ranges, [value][자동])
    for w in others:
        narrower(w, FIT_PLAIN_MIN_W if w.property('hig_plain') else FIT_FIELD_MIN_W)
    need = _need(page)
    if need <= width:
        return True
    # 4. settings fields down to the narrowest field width
    for w in fields:
        narrower(w, FIT_FIELD_MIN_W)
        w.setMaximumWidth(FIT_FIELD_MIN_W)
    need = _need(page)
    if need <= width:
        return True
    # 5. long check boxes get their word-wrapping label (as i18n does for
    #    long texts when shown); then labels wrap (also inside long words: a set minimum width overrides
    #    the longest-word minimum of a wrapping label)
    from PySide6.QtWidgets import QCheckBox, QRadioButton  # noqa: PLC0415

    for w in _parts(page, (QCheckBox, QRadioButton)):
        if w.minimumSizeHint().width() > width // 2:
            try:
                i18n._maybe_wrap(w)
            except Exception:  # noqa: BLE001  (a box in an unusual layout stays as it is)
                pass
    titles = set()
    for f in page.findChildren(QFormLayout):
        for r in range(f.rowCount()):
            it = f.itemAt(r, QFormLayout.ItemRole.LabelRole)
            if it is not None and it.widget() is not None:
                titles.add(it.widget())
    labels = [w for w in _parts(page, QLabel)
              if w.minimumSizeHint().width() > FIT_LABEL_MIN_W and not w.minimumWidth()]
    # texts first, row titles only when that is not enough
    for group in ([w for w in labels if w not in titles], [w for w in labels if w in titles]):
        for w in group:
            _save(w, 'wrap', w.wordWrap())
            _save(w, 'min', 0)
            w.setWordWrap(True)
            w.setMinimumWidth(FIT_LABEL_MIN_W)
        need = _need(page)
        if need <= width:
            return True
    # 6. card titles (one line) end in … (the full title in the tool tip)
    for g in _parts(page, QGroupBox):
        if not g.title():
            continue
        full = i18n.tr(g.title())
        room = width - g.mapTo(page, g.rect().topLeft()).x() - 2 * FIT_TITLE_PAD
        f = g.font()
        f.setBold(True)
        fm = QFontMetrics(f)
        if fm.horizontalAdvance(full) > room > 0:
            _save(g, 'tip', g.toolTip())
            _save(g, 'title', True)
            g.setToolTip(full)
            _show_title(g, fm.elidedText(full, Qt.TextElideMode.ElideRight, room))
    return _need(page) <= width


def _show_title(g, text):
    """Shows `text` as the card title, keeping the title the code reads."""
    setter = i18n._ORIG.get((QGroupBox, 'setTitle'), QGroupBox.setTitle)
    setter(g, text)


def overflow(page: QWidget, width: int) -> list[str]:
    """Visible controls whose right edge passes `width` (for the self-test)."""
    out = []
    for w in page.findChildren(QWidget):
        if not w.isVisibleTo(page) or w.width() <= 0 or w.isWindow():
            continue
        if type(w).__name__ == 'RowLines':  # the hairline overlay spans the card
            continue
        right = w.mapTo(page, w.rect().topRight()).x()
        if right > width + 1 and not any(
                c.isVisibleTo(page) for c in w.findChildren(QWidget)):
            text = w.text() if hasattr(w, 'text') and callable(w.text) else ''
            out.append(f'{type(w).__name__} {str(text)[:24]!r} right {right} > {width}')
    return out


class FitScroll(QScrollArea):
    """Vertical scroll area of a fixed-width box: its page always as wide as
    the box, the controls inside give way (``fit_width``)."""

    def __init__(self, page: QWidget | None = None, parent=None):
        super().__init__(parent)
        from PySide6.QtCore import Qt  # noqa: PLC0415

        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._pending = False
        self._last = None  # (width, need) after the last fit
        if page is not None:
            self.setWidget(page)

    def setWidget(self, page: QWidget):  # noqa: N802 (Qt API)
        super().setWidget(page)
        page.installEventFilter(self)
        self.refit()

    def refit(self):
        """Fit the page to the box soon (after the current layout pass)."""
        if not self._pending:
            self._pending = True
            QTimer.singleShot(0, self._refit_now)

    def _refit_now(self):
        self._pending = False
        page = self.widget()
        if page is None or not page.isVisible():
            return  # fitted when shown (its controls polished, their own widths set)
        width = self.viewport().width()
        try:
            fit_width(page, width)
        except RuntimeError:  # deleted while queued
            return
        # fit again only when the width or the contents change
        self._last = (width, page.minimumSizeHint().width())
        # the scroll area sizes its page again on the page's layout request
        from PySide6.QtWidgets import QApplication  # noqa: PLC0415

        QApplication.postEvent(page, QEvent(QEvent.Type.LayoutRequest))

    def resizeEvent(self, ev):  # noqa: N802 (Qt API)
        super().resizeEvent(ev)
        self.refit()

    def eventFilter(self, obj, ev):  # noqa: N802 (Qt API)
        # rows shown / hidden or texts changed: fit again
        if obj is self.widget() and ev.type() == QEvent.Type.Show:
            self.refit()
        elif obj is self.widget() and ev.type() == QEvent.Type.LayoutRequest:
            width = self.viewport().width()
            need = obj.minimumSizeHint().width()
            if (width, need) != self._last and (need > width or obj.property('fit_changed')):
                self.refit()
        return False
