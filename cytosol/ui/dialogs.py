"""Window variants alert / prompt / progress (design system ``hig-window``).

Drop-in replacements for the Qt static dialogs, with the same arguments and
return values, drawn as the rounded hig-window:

* :func:`information`, :func:`warning`, :func:`critical`, :func:`question`
  — like ``QMessageBox.<name>(parent, title, text, buttons, defaultButton)``,
  return a ``QMessageBox.StandardButton``.
* :func:`get_text`, :func:`get_item`, :func:`get_int`, :func:`get_double`,
  :func:`get_multiline_text` — like ``QInputDialog.getText`` …, return
  ``(value, ok)``.
* :class:`Progress` — the ``QProgressDialog`` API (``setValue``,
  ``setLabelText``, ``wasCanceled``, ``canceled`` …, shown after
  ``minimumDuration``, closed at the maximum).
* :func:`confirm_destructive` / :func:`destructive_alert` — 취소 is the
  default and the Escape button, the action is red.

``HEADLESS`` (set by the ``cytosol.pipe`` command line) receives the alerts
instead of a window: ``HEADLESS(kind, title, text)`` returns the answer.
"""
from __future__ import annotations

from PySide6.QtCore import QElapsedTimer, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
)

from .window import RoundedDialog

SB = QMessageBox.StandardButton
HEADLESS = None  # callable(kind, title, text) -> answer, for the command line

LABELS = {
    SB.Ok: '확인', SB.Yes: '예', SB.No: '아니요', SB.Cancel: '취소', SB.Save: '저장',
    SB.Discard: '저장 안 함', SB.Close: '닫기', SB.Apply: '적용', SB.Retry: '다시 시도',
    SB.Ignore: '무시', SB.Abort: '중단', SB.YesToAll: '모두 예', SB.NoToAll: '모두 아니요',
    SB.Open: '열기', SB.Reset: '초기화', SB.RestoreDefaults: '기본값', SB.Help: '도움말',
    SB.SaveAll: '모두 저장',
}
_ORDER = list(LABELS)
_ESCAPE = (SB.Cancel, SB.No, SB.Close, SB.Abort, SB.Ignore, SB.Ok)
_DEFAULT = (SB.Yes, SB.Ok, SB.Save, SB.Open, SB.Apply, SB.Retry, SB.SaveAll, SB.Close)
STATUS = {'information': None, 'question': None, 'warning': 'warning', 'critical': 'error'}
LONG_LINES = 12  # longer messages go into a read-only text area


def _buttons(flags) -> list:
    flags = SB(flags) if not isinstance(flags, SB) else flags
    return [b for b in _ORDER if flags & b]


class Alert(RoundedDialog):
    """Window variant ``alert``: [status icon] title, text, buttons at the end
    (the default last and prominent, Escape = the cancel button)."""

    variant = 'alert'

    def __init__(self, parent=None, title: str = '', text: str = '', kind: str = 'information',
                 info: str = ''):
        from .. import theme  # noqa: PLC0415

        super().__init__(parent, title, '')
        self.kind = kind
        self._buttons: list[tuple[QPushButton, object]] = []
        self._default = self._escape = self._clicked = None
        self.setMinimumWidth(320)
        st = STATUS.get(kind)
        if st:
            icon = QLabel()
            icon.setPixmap(theme.status_icon(st, 16).pixmap(16, 16))
            icon.setObjectName('hig_alert_icon')
            self.body.insertWidget(0, icon)
        body = '\n'.join(t for t in (text, info) if t)
        if body.count('\n') >= LONG_LINES:
            from .fields import TextArea  # noqa: PLC0415

            area = TextArea(read_only=True)
            area.setPlainText(body)
            area.max_lines = 14
            self.body.insertWidget(self.body.indexOf(self.text), area)
            self.area = area
        else:
            self.text.setText(body)
            self.text.setVisible(bool(body))
            self.text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.text.setMaximumWidth(460)

    # the QMessageBox API the callers and the self-test use
    def add_button(self, text: str, value=None, role: str = 'other') -> QPushButton:
        b = QPushButton(text)
        b.setAutoDefault(False)
        b.clicked.connect(lambda _=False, b=b: self._click(b))
        if role == 'destructive':
            from .. import theme  # noqa: PLC0415
            theme.destructive(b)
        b.setProperty('hig_alert_role', role)
        self._buttons.append((b, value))
        return b

    def setDefaultButton(self, b):
        self._default = b

    def setEscapeButton(self, b):
        self._escape = b

    def defaultButton(self):
        return self._default

    def escapeButton(self):
        return self._escape

    def clickedButton(self):
        return self._clicked

    def value(self):
        for b, v in self._buttons:
            if b is self._clicked:
                return v
        return None

    def _click(self, b):
        self._clicked = b
        self.done(1)

    def reject(self):  # Escape
        self._clicked = self._escape
        super().reject()

    def finish(self):
        """Lay the buttons out: destructive leading, the rest in order, the default last."""
        lead = [b for b, _ in self._buttons if b.property('hig_alert_role') == 'destructive'
                and b is not self._default]
        rest = [b for b, _ in self._buttons if b not in lead and b is not self._default]
        rest.sort(key=lambda b: b.property('hig_alert_role') != 'cancel')  # 취소 first
        if self._default is not None:
            rest.append(self._default)
        self.button_row(*rest, default=self._default, leading=lead)
        if self._default is not None:
            self._default.setFocus()

    def exec(self):
        if not getattr(self, '_finished', False):
            self._finished = True
            self.finish()
        self.adjustSize()
        return super().exec()


def _message(kind, parent, title, text, buttons, default_button):
    if HEADLESS is not None:
        return HEADLESS(kind, title, text)
    std = _buttons(buttons)
    box = Alert(parent, title, text, kind)
    made = {}
    for s in std:
        made[s] = box.add_button(LABELS.get(s, str(s)), s,
                                 'destructive' if s == SB.Discard else 'other')
    d = default_button if default_button in made else next(
        (s for s in _DEFAULT if s in made), std[-1] if std else None)
    e = next((s for s in _ESCAPE if s in made), d)
    if d is not None:
        box.setDefaultButton(made[d])
    if e is not None:
        box.setEscapeButton(made[e])
    box.exec()
    v = box.value()
    box.deleteLater()
    return v if v is not None else (e if e is not None else SB.NoButton)


def information(parent, title, text, buttons=SB.Ok, defaultButton=SB.NoButton):  # noqa: N803
    return _message('information', parent, title, text, buttons, defaultButton)


def warning(parent, title, text, buttons=SB.Ok, defaultButton=SB.NoButton):  # noqa: N803
    return _message('warning', parent, title, text, buttons, defaultButton)


def critical(parent, title, text, buttons=SB.Ok, defaultButton=SB.NoButton):  # noqa: N803
    return _message('critical', parent, title, text, buttons, defaultButton)


def question(parent, title, text, buttons=SB.Yes | SB.No,
             defaultButton=SB.NoButton):  # noqa: N803
    return _message('question', parent, title, text, buttons, defaultButton)


def choose(parent, title: str, text: str, choices, default: int = -1, cancel: str | None = '취소',
           info: str = '', kind: str = 'question'):
    """An alert with own verb buttons: returns the index of the chosen one in
    `choices` (each a label or (label, 'destructive')), or None for 취소 / Escape."""
    if HEADLESS is not None:
        return HEADLESS('choose', title, text)
    box = Alert(parent, title, text, kind, info)
    made = []
    for i, c in enumerate(choices):
        label, role = (c, 'other') if isinstance(c, str) else c
        made.append(box.add_button(label, i, role))
    if cancel:
        cb = box.add_button(cancel, None, 'cancel')
        box.setEscapeButton(cb)
    if made:
        box.setDefaultButton(made[default])
    box.exec()
    v = box.value()
    box.deleteLater()
    return v


# ---- destructive confirmation ----------------------------------------------

def destructive_alert(parent, title: str, text: str, action: str, info: str = ''):
    """The confirmation alert of :func:`confirm_destructive` (not shown):
    (box, action button); 취소 is the default and the Escape button."""
    box = Alert(parent, title, text, 'warning', info or '이 작업은 되돌릴 수 없습니다.')
    cancel = box.add_button('취소', False, 'cancel')
    act = box.add_button(action, True, 'destructive')
    box.setDefaultButton(cancel)
    box.setEscapeButton(cancel)
    box._buttons = [(cancel, False), (act, True)]
    return box, act


def confirm_destructive(parent, title: str, text: str, action: str, info: str = '') -> bool:
    """Alert for an action that cannot be undone: the title names the object,
    the default (Return) and Escape button is 취소, the action is red."""
    if HEADLESS is not None:
        return bool(HEADLESS('destructive', title, text))
    box, act = destructive_alert(parent, title, text, action, info)
    # [취소] [action] at the end: 취소 is the default (Return / Escape) but not
    # filled, the action the red hig-delete squircle
    box._finished = True
    cancel = box._default
    box.button_row(cancel, act)
    cancel.setDefault(True)
    cancel.setFocus()
    box.exec()
    ok = box.clickedButton() is act
    box.deleteLater()
    return ok


# ---- prompt ----------------------------------------------------------------

class Prompt(RoundedDialog):
    """Window variant ``prompt``: title = verb + object, one line of text,
    one input, [취소] [verb]. The verb button is off while the input is not
    accepted (`check(value) -> reason or ''`)."""

    variant = 'prompt'

    def __init__(self, parent, title: str, label: str, field, action: str = '확인',
                 check=None):
        from .. import theme  # noqa: PLC0415

        super().__init__(parent, title, label)
        self.setMinimumWidth(340)
        self.field = field
        self.check = check
        self.body.addWidget(field)
        self.reason = QLabel('')
        theme.hint(self.reason)
        self.reason.setVisible(False)
        self.body.addWidget(self.reason)
        self.cancel_btn = QPushButton('취소')
        self.ok_btn = QPushButton(action)
        self.cancel_btn.clicked.connect(self.reject)
        self.ok_btn.clicked.connect(self.accept)
        self.button_row(self.cancel_btn, self.ok_btn, default=self.ok_btn)
        field.setFocus()

    def validate(self, value):
        why = self.check(value) if self.check else ''
        self.ok_btn.setEnabled(not why)
        self.reason.setText(why or '')
        self.reason.setVisible(bool(why))


def _prompt_result(dlg, getter):
    ok = dlg.exec() == 1
    v = getter()
    dlg.deleteLater()
    return v, ok


def get_text(parent, title, label, echo=QLineEdit.EchoMode.Normal, text='', *,
             action: str = '확인', check=None, allow_empty: bool = True, **_):
    """QInputDialog.getText: (text, ok)."""
    if HEADLESS is not None:
        return text, False
    field = QLineEdit(text)
    field.setEchoMode(echo)
    field.selectAll()
    if check is None and not allow_empty:
        def check(v):
            return '이름을 입력하세요.' if not v.strip() else ''
    dlg = Prompt(parent, title, label, field, action, check)
    field.textChanged.connect(dlg.validate)
    dlg.validate(text)
    return _prompt_result(dlg, field.text)


def get_multiline_text(parent, title, label, text='', *, action: str = '확인', **_):
    """QInputDialog.getMultiLineText: (text, ok); ⌘Enter = the verb."""
    if HEADLESS is not None:
        return text, False
    from .fields import TextArea  # noqa: PLC0415

    area = TextArea()
    area.setPlainText(text)
    area.selectAll()
    dlg = Prompt(parent, title, label, area, action)
    area.submitted.connect(dlg.accept)
    return _prompt_result(dlg, area.toPlainText)


def get_item(parent, title, label, items, current=0, editable=True, *,
             action: str = '확인', **_):
    """QInputDialog.getItem: (text, ok)."""
    items = list(items)
    if HEADLESS is not None:
        return (items[current] if items else ''), False
    box = QComboBox()
    box.addItems(items)
    box.setEditable(bool(editable))
    if items:
        box.setCurrentIndex(max(0, min(current, len(items) - 1)))
    dlg = Prompt(parent, title, label, box, action)
    return _prompt_result(dlg, box.currentText)


def get_int(parent, title, label, value=0, minValue=-2147483647, maxValue=2147483647,  # noqa: N803
            step=1, *, action: str = '확인', **_):
    if HEADLESS is not None:
        return value, False
    box = QSpinBox()
    box.setRange(minValue, maxValue)
    box.setSingleStep(step)
    box.setValue(value)
    dlg = Prompt(parent, title, label, box, action)
    return _prompt_result(dlg, box.value)


def get_double(parent, title, label, value=0.0, minValue=-2147483647.0,  # noqa: N803
               maxValue=2147483647.0, decimals=1, *, action: str = '확인', **_):
    if HEADLESS is not None:
        return value, False
    box = QDoubleSpinBox()
    box.setDecimals(decimals)
    box.setRange(minValue, maxValue)
    box.setValue(value)
    dlg = Prompt(parent, title, label, box, action)
    return _prompt_result(dlg, box.value)


# ---- progress --------------------------------------------------------------

class Progress(RoundedDialog):
    """Window variant ``progress`` with the QProgressDialog API: title (the
    task), one line (what it does now), a bar, [취소] at the end. Shown only
    when the work takes longer than ``minimumDuration`` (Qt's rule), closed
    and reset at the maximum; Escape = 취소."""

    variant = 'progress'
    canceled = Signal()
    MIN_WAIT_MS = 50

    def __init__(self, label: str = '', cancel: str | None = '취소', minimum: int = 0,
                 maximum: int = 100, parent=None, title: str | None = None):
        super().__init__(parent, title if title is not None else label, '')
        self.setFixedWidth(360 + (0 if self.layout().contentsMargins().left() == 0
                                  else 2 * self.layout().contentsMargins().left()))
        self.text.setVisible(True)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(minimum, maximum)
        self.bar.setValue(minimum)
        self.body.addWidget(self.bar)
        self.cancel_btn = QPushButton(cancel or '취소')
        self.cancel_btn.clicked.connect(self.cancel)
        self._row = self.button_row(self.cancel_btn)
        self.cancel_btn.setVisible(cancel is not None)
        self._canceled = False
        self._shown_once = False
        self._set_called = False
        self._auto_close = True
        self._auto_reset = True
        self._min_duration = 4000
        self._start = QElapsedTimer()
        self._start.start()
        self._force = QTimer(self)
        self._force.setSingleShot(True)
        self._force.timeout.connect(self._force_show)
        self._force.start(self._min_duration)

    # QProgressDialog API ------------------------------------------------------
    def setLabelText(self, text: str):
        self.text.setText(text)

    def labelText(self) -> str:
        return self.text.text()

    def setCancelButtonText(self, text: str | None):
        if text is None:
            self.cancel_btn.setVisible(False)
        else:
            self.cancel_btn.setText(text)
            self.cancel_btn.setVisible(True)

    def setCancelButton(self, button):
        self.cancel_btn.setVisible(button is not None)

    def setMinimumDuration(self, ms: int):
        self._min_duration = ms
        if self.value() == self.minimum():
            self._force.stop()
            self._force.start(ms)

    def minimumDuration(self) -> int:
        return self._min_duration

    def setAutoClose(self, on: bool):
        self._auto_close = on

    def setAutoReset(self, on: bool):
        self._auto_reset = on

    def autoClose(self) -> bool:
        return self._auto_close

    def autoReset(self) -> bool:
        return self._auto_reset

    def setRange(self, lo: int, hi: int):
        self.bar.setRange(lo, hi)

    def setMinimum(self, v: int):
        self.bar.setMinimum(v)

    def setMaximum(self, v: int):
        self.bar.setMaximum(v)

    def minimum(self) -> int:
        return self.bar.minimum()

    def maximum(self) -> int:
        return self.bar.maximum()

    def value(self) -> int:
        return self.bar.value()

    def wasCanceled(self) -> bool:  # noqa: N802
        return self._canceled

    def cancel(self):
        self._force.stop()
        self._canceled = True
        self.canceled.emit()
        if self._auto_close:
            self.hide()

    def reject(self):  # Escape = 취소
        self.cancel()

    def reset(self):
        if self._auto_close:
            self.hide()
        self.bar.reset()
        self._canceled = False
        self._shown_once = False
        self._set_called = False
        self._force.stop()

    def _force_show(self):
        self._force.stop()
        if self._shown_once or self._canceled:
            return
        self.adjustSize()
        self.show()
        self._shown_once = True

    def setValue(self, progress: int):  # noqa: N802
        if self._set_called and progress == self.bar.value():
            return
        self.bar.setValue(progress)
        if self._shown_once:
            if self.windowModality() != Qt.WindowModality.NonModal:
                QApplication.processEvents()
        else:
            if (not self._set_called and progress == 0) or progress == self.minimum():
                self._start.start()
                self._force.start(self._min_duration)
                self._set_called = True
                return
            self._set_called = True
            elapsed = self._start.elapsed()
            if elapsed >= self.MIN_WAIT_MS:
                done = progress - self.minimum()
                total = self.maximum() - self.minimum()
                need = (elapsed > self._min_duration) or (
                    done > 0 and elapsed * total / done >= self._min_duration)
                if total <= 0:
                    need = elapsed > self._min_duration
                if need:
                    self.adjustSize()
                    self.show()
                    self._shown_once = True
        if progress == self.maximum() and self._auto_reset:
            self.reset()
