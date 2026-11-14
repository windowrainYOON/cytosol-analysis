"""화면 언어: 한국어 / English (owner request 2026-11-15; design system
`components/Language`).

The program's UI text is written in Korean in the code; this module shows it
in English when the language is English.  It does so in one place instead
of at every call: `install()` wraps the Qt setters that put text on screen
(labels, buttons, group titles, tool tips, menus, actions, pop-up items,
tabs, table / tree headers and items, status bar, message boxes, dialogs)
so that they pass the text through `tr()`.  The Korean source of every text
set this way is kept on the widget, so `set_language()` can change every
open window at once (`retranslate()`).

- The table of translations is `i18n_en.EN` (Korean -> English) and
  `i18n_en.TEMPLATES` (f-string templates with ``{}`` places, Korean ->
  English with ``{0}``, ``{1}`` …).  Text not in the tables stays as it is.
- User data (file, image, group, channel and ROI names), CSV column keys,
  file name rules and project / settings JSON keys are never translated:
  they are not in the tables, and code that reads a widget's text back as a
  key asks for its source (`source()`).
- The setting is `QSettings` ``ui/language`` = ``system`` / ``ko`` / ``en``;
  ``system`` follows the system language (Korean -> 한국어, else English).
"""
from __future__ import annotations

import re

HAN = re.compile('[가-힣]')
ROLE_SRC = 0x0100 + 771  # Qt.UserRole + 771: an item's Korean source text
LANGS = (('system', '시스템 설정 따르기 / Use System Setting'), ('ko', '한국어'), ('en', 'English'))

LANG = 'ko'
_installed = False
_cache: dict = {}
_templates = None


# ---- the language ------------------------------------------------------------------

def setting() -> str:
    from .settings import view_settings
    v = view_settings._store().value('ui/language', 'system')
    return v if v in ('system', 'ko', 'en') else 'system'


def resolve(value: str) -> str:
    if value in ('ko', 'en'):
        return value
    from PySide6.QtCore import QLocale
    return 'ko' if QLocale.system().language() == QLocale.Language.Korean else 'en'


def set_language(value: str, store=True, apply=True) -> str:
    """Store the setting and switch every open window (immediately)."""
    global LANG
    if store:
        from .settings import view_settings
        view_settings._store().setValue('ui/language', value)
    new = resolve(value)
    changed = new != LANG
    LANG = new
    _cache.clear()
    if changed and apply and _installed:
        retranslate()
    return LANG


def is_english() -> bool:
    return LANG == 'en'


# ---- translating text ----------------------------------------------------------------

def _load_templates():
    global _templates
    if _templates is not None:
        return _templates
    from .i18n_en import EN, TEMPLATES
    out = []
    both = dict((k, v) for k, v in EN.items() if '{}' in k)  # '…{}…'.format(…) texts
    both.update(TEMPLATES)
    for ko, en in both.items():
        parts = re.split(r'(\{\})', ko.replace('{{', '\x01').replace('}}', '\x02'))
        n = sum(1 for p in parts if p == '{}')
        lit = ''.join(p for p in parts if p != '{}')
        if not HAN.search(lit):
            continue
        rx = ''.join('(.*?)' if p == '{}' else re.escape(p.replace('\x01', '{').replace('\x02', '}'))
                     for p in parts)
        k = 0

        def number(_m):
            nonlocal k
            k += 1
            return '{%d}' % (k - 1)
        en_t = re.sub(r'\{\}', number, en.replace('{{', '\x01').replace('}}', '\x02'))
        out.append((len(lit), re.compile(rx, re.S), en_t, n))
    out.sort(key=lambda x: -x[0])
    _templates = out
    return out


_PLURAL = re.compile(r'(?<![\d.])1 (image|cell|row|file|track|particle|group|frame|column|band|point|'
                     r'fragment|ROI|table|graph|value|timepoint|nucleus|object|punct|step|channel|item)s\b')


def _fill(en_t, groups):
    out = en_t
    for i, g in enumerate(groups):
        out = out.replace('{%d}' % i, g)
    return out.replace('\x01', '{').replace('\x02', '}')


def _lookup(s: str):
    from .i18n_en import EN
    v = EN.get(s)
    if v is not None:
        return v
    st = s.strip()
    if st != s and st in EN:
        return s[:len(s) - len(s.lstrip())] + EN[st] + s[len(s.rstrip()):]
    for n, rx, en_t, _k in _load_templates():
        m = rx.fullmatch(s)
        if m:
            if n <= 4 and any(HAN.search(g) for g in m.groups()):
                continue  # '세포 {}' is 'Cell 3', not 'Cell 크기 최소'
            return _fill(en_t, [tr(g) for g in m.groups()])
    return None


_TAG = re.compile(r'(<[^>]+>|&[a-z]+;)')
_SENT = re.compile(r'(?<=[.!?:)])\s+(?=\S)')


def tr(s):
    """English for a Korean UI text (the text itself in Korean, or when it
    has no translation)."""
    if LANG == 'ko' or not isinstance(s, str) or not s or not HAN.search(s):
        return s
    v = _cache.get(s)
    if v is not None:
        return v
    v = _lookup(s)
    if v is None and '<' in s and _TAG.search(s):
        parts = _TAG.split(s)
        done = [p if (not p or _TAG.fullmatch(p)) else tr(p) for p in parts]
        if done != parts:
            v = ''.join(done)
    if v is None and '\n' not in s:
        parts = _SENT.split(s)
        if len(parts) > 1:
            done, i = [], 0
            while i < len(parts):
                for j in range(len(parts), i, -1):  # the longest run of sentences with a translation
                    chunk = ' '.join(parts[i:j])
                    t = _lookup(chunk) if j - i > 1 else tr(chunk)
                    if t is not None and (t != chunk or j - i == 1):
                        done.append(t)
                        i = j
                        break
            if done != parts:
                v = ' '.join(done)
    if v is None:
        # composed text: lines, then ' · ' / ' — ' parts, each on its own
        for sep in ('\n', ' — ', ' · ', ': ', ', '):
            if sep in s:
                parts = s.split(sep)
                done = [tr(p) for p in parts]
                if done != parts:
                    v = sep.join(done)
                    break
    if v is None:
        v = s
    v = _PLURAL.sub(lambda m: f'1 {m.group(1)}', v)
    if len(_cache) > 20000:
        _cache.clear()
    _cache[s] = v
    return v


def trs(seq):
    return [tr(x) for x in seq]


# ---- source text of widgets -----------------------------------------------------------

def _keep(obj, key, src):
    try:
        d = obj.__dict__.setdefault('_tr_src', {})
    except (AttributeError, TypeError):
        return
    if isinstance(src, str) and HAN.search(src):
        d[key] = src
    else:
        d.pop(key, None)


def source(obj, key='text'):
    """The Korean text a widget was given (its shown text when not translated)."""
    d = getattr(obj, '_tr_src', None) or {}
    if key in d:
        return d[key]
    getter = {'text': 'text', 'title': 'title', 'tooltip': 'toolTip'}.get(key, key)
    fn = getattr(obj, getter, None)
    return fn() if callable(fn) else ''


# ---- wrapping the Qt setters ------------------------------------------------------------

_ORIG = {}  # (class, name) -> original


def _wrap_setter(cls, name, key=None, arg=0):
    orig = getattr(cls, name)
    _ORIG[(cls, name)] = orig
    key = key or name

    def setter(self, *a, **k):
        lab = self.__dict__.get('_tr_label') if key == 'text' and hasattr(self, '__dict__') else None
        if lab is not None and a and isinstance(a[0], str):
            _keep(self, key, a[0])
            try:
                lab.setText(a[0])
                return None
            except RuntimeError:
                pass
        if len(a) > arg and isinstance(a[arg], str):
            _keep(self, key, a[arg])
            a = list(a)
            a[arg] = tr(a[arg])
        return orig(self, *a, **k)
    setter.__name__ = name
    setattr(cls, name, setter)


def _wrap_init(cls, key='text', arg=0):
    orig = cls.__init__
    _ORIG[(cls, '__init__')] = orig

    def init(self, *a, **k):
        if len(a) > arg and isinstance(a[arg], str):
            src = a[arg]
            a = list(a)
            a[arg] = tr(src)
            orig(self, *a, **k)
            _keep(self, key, src)
            return
        if 'text' in k and isinstance(k['text'], str):
            src = k['text']
            k['text'] = tr(src)
            orig(self, *a, **k)
            _keep(self, key, src)
            return
        if 'title' in k and isinstance(k['title'], str):
            src = k['title']
            k['title'] = tr(src)
            orig(self, *a, **k)
            _keep(self, key, src)
            return
        orig(self, *a, **k)
    setattr(cls, '__init__', init)


def _wrap_items(cls):
    """QComboBox: item texts keep their source in ROLE_SRC."""
    add, ins, set_text, adds, inss = cls.addItem, cls.insertItem, cls.setItemText, cls.addItems, cls.insertItems

    def _src(self, i, src):
        m = self.model()
        it = m.index(i, 0)
        if isinstance(src, str) and HAN.search(src):
            m.setData(it, src, ROLE_SRC)
        elif m.data(it, ROLE_SRC):
            m.setData(it, None, ROLE_SRC)

    def addItem(self, *a, **k):
        a = list(a)
        i = 1 if a and not isinstance(a[0], str) and len(a) > 1 and isinstance(a[1], str) else 0
        src = a[i] if len(a) > i and isinstance(a[i], str) else None
        if src is not None:
            a[i] = tr(src)
        add(self, *a, **k)
        if src is not None:
            _src(self, self.count() - 1, src)

    def insertItem(self, index, *a, **k):
        a = list(a)
        i = 1 if a and not isinstance(a[0], str) and len(a) > 1 and isinstance(a[1], str) else 0
        src = a[i] if len(a) > i and isinstance(a[i], str) else None
        if src is not None:
            a[i] = tr(src)
        ins(self, index, *a, **k)
        if src is not None:
            _src(self, min(max(index, 0), self.count() - 1), src)

    def setItemText(self, index, text):
        _src(self, index, text)
        set_text(self, index, tr(text))

    def addItems(self, texts):
        n = self.count()
        texts = list(texts)
        adds(self, trs(texts))
        for j, t in enumerate(texts):
            _src(self, n + j, t)

    def insertItems(self, index, texts):
        texts = list(texts)
        inss(self, index, trs(texts))
        for j, t in enumerate(texts):
            _src(self, index + j, t)

    cls.addItem, cls.insertItem, cls.setItemText, cls.addItems, cls.insertItems = \
        addItem, insertItem, setItemText, addItems, insertItems


def _wrap_item_class(cls):
    """QTreeWidgetItem / QTableWidgetItem / QListWidgetItem: texts with their
    source in ROLE_SRC (per column)."""
    orig_init, orig_set = cls.__init__, cls.setText
    tree = cls.__name__ == 'QTreeWidgetItem'

    def init(self, *a, **k):
        a = list(a)
        srcs = None
        for i, x in enumerate(a):
            if isinstance(x, str):
                srcs = {0: x}
                a[i] = tr(x)
                break
            if isinstance(x, (list, tuple)) and x and all(isinstance(s, str) for s in x):
                srcs = dict(enumerate(x))
                a[i] = trs(x)
                break
        orig_init(self, *a, **k)
        if srcs:
            for col, s in srcs.items():
                if HAN.search(s):
                    if tree:
                        self.setData(col, ROLE_SRC, s)
                    else:
                        self.setData(ROLE_SRC, s)

    def setText(self, *a):
        if tree:
            col, text = a
            han = isinstance(text, str) and HAN.search(text)
            if han or self.data(col, ROLE_SRC):
                self.setData(col, ROLE_SRC, text if han else None)
            return orig_set(self, col, tr(text))
        (text,) = a
        han = isinstance(text, str) and HAN.search(text)
        if han or self.data(ROLE_SRC):
            self.setData(ROLE_SRC, text if han else None)
        return orig_set(self, tr(text))
    cls.__init__, cls.setText = init, setText


def _wrap_static(cls, name, idx):
    """Static dialogs (QMessageBox.information …): text arguments at idx."""
    orig = getattr(cls, name)

    def fn(*a, **k):
        a = list(a)
        for i in idx:
            if len(a) > i and isinstance(a[i], str):
                a[i] = tr(a[i])
        for kk in ('caption', 'title', 'text', 'label', 'filter'):
            if isinstance(k.get(kk), str):
                k[kk] = tr(k[kk])
        return orig(*a, **k)
    setattr(cls, name, staticmethod(fn))


def install():
    """Wrap the Qt setters once (in Korean they pass text through as it is)."""
    global _installed
    if _installed:
        return
    _installed = True
    from PySide6 import QtGui, QtWidgets as W

    for cls in (W.QLabel, W.QPushButton, W.QCheckBox, W.QRadioButton, W.QToolButton):
        _wrap_init(cls)
        _wrap_setter(cls, 'setText', 'text')
    _wrap_init(W.QGroupBox, 'title')
    _wrap_setter(W.QGroupBox, 'setTitle', 'title')
    _wrap_setter(W.QWidget, 'setToolTip', 'tooltip')
    _wrap_setter(W.QWidget, 'setWindowTitle', 'window')
    _wrap_setter(W.QWidget, 'setStatusTip', 'status')
    _wrap_setter(W.QLineEdit, 'setPlaceholderText', 'placeholder')
    for cls in (W.QSpinBox, W.QDoubleSpinBox):
        _wrap_setter(cls, 'setSuffix', 'suffix')
        _wrap_setter(cls, 'setPrefix', 'prefix')
        _wrap_setter(cls, 'setSpecialValueText', 'special')
    _wrap_items(W.QComboBox)
    _wrap_setter(W.QComboBox, 'setPlaceholderText', 'placeholder')
    # tabs: (page, label) / (index, page, label) / (index, label)
    tw = W.QTabWidget
    o_add, o_ins, o_set, o_tip = tw.addTab, tw.insertTab, tw.setTabText, tw.setTabToolTip

    def addTab(self, page, *a):
        a = list(a)
        if a and isinstance(a[-1], str):
            page.__dict__['_tr_tab'] = a[-1]
            a[-1] = tr(a[-1])
        return o_add(self, page, *a)

    def insertTab(self, index, page, *a):
        a = list(a)
        if a and isinstance(a[-1], str):
            page.__dict__['_tr_tab'] = a[-1]
            a[-1] = tr(a[-1])
        return o_ins(self, index, page, *a)

    def setTabText(self, index, text):
        page = self.widget(index)
        if page is not None and isinstance(text, str):
            page.__dict__['_tr_tab'] = text
        return o_set(self, index, tr(text))

    def setTabToolTip(self, index, text):
        return o_tip(self, index, tr(text))
    tw.addTab, tw.insertTab, tw.setTabText, tw.setTabToolTip = addTab, insertTab, setTabText, setTabToolTip
    # menus and actions
    _wrap_init(W.QMenu, 'title')
    _wrap_setter(W.QMenu, 'setTitle', 'title')
    for cls in (W.QMenu, W.QMenuBar):
        orig_am = cls.addMenu

        def addMenu(self, *a, _o=orig_am):
            a = list(a)
            for i, x in enumerate(a):
                if isinstance(x, str):
                    m = _o(self, *(a[:i] + [tr(x)] + a[i + 1:]))
                    _keep(m, 'title', x)
                    return m
            return _o(self, *a)
        cls.addMenu = addMenu
    for cls in (W.QMenu, W.QToolBar, W.QWidget):
        if 'addAction' not in cls.__dict__:
            continue
        orig_aa = cls.addAction

        def addAction(self, *a, _o=orig_aa, **k):
            a = list(a)
            for i, x in enumerate(a):
                if isinstance(x, str):
                    act = _o(self, *(a[:i] + [tr(x)] + a[i + 1:]), **k)
                    _keep(act, 'text', x)
                    return act
            return _o(self, *a, **k)
        cls.addAction = addAction
    act = QtGui.QAction
    _wrap_init(act)
    _wrap_setter(act, 'setText', 'text')
    _wrap_setter(act, 'setToolTip', 'tooltip')
    _wrap_setter(act, 'setStatusTip', 'status')
    _wrap_setter(act, 'setIconText', 'icontext')
    # form rows: the label made by the layout keeps its source
    for cls in (W.QFormLayout,):
        o_row, o_irow = cls.addRow, cls.insertRow

        def addRow(self, *a, _o=o_row):
            if len(a) >= 2 and isinstance(a[0], str):
                src = a[0]
                r = _o(self, tr(src), *a[1:])
                lab = self.itemAt(self.rowCount() - 1, W.QFormLayout.ItemRole.LabelRole)
                if lab is not None and lab.widget() is not None:
                    _keep(lab.widget(), 'text', src)
                return r
            return _o(self, *a)

        def insertRow(self, row, *a, _o=o_irow):
            if len(a) >= 2 and isinstance(a[0], str):
                src = a[0]
                r = _o(self, row, tr(src), *a[1:])
                i = row if 0 <= row < self.rowCount() else self.rowCount() - 1
                lab = self.itemAt(i, W.QFormLayout.ItemRole.LabelRole)
                if lab is not None and lab.widget() is not None:
                    _keep(lab.widget(), 'text', src)
                return r
            return _o(self, row, *a)
        cls.addRow, cls.insertRow = addRow, insertRow
    # headers
    for cls, name in ((W.QTableWidget, 'setHorizontalHeaderLabels'), (W.QTableWidget, 'setVerticalHeaderLabels'),
                      (W.QTreeWidget, 'setHeaderLabels')):
        orig = getattr(cls, name)

        def hdr(self, labels, _o=orig, _n=name):
            labels = list(labels)
            self.__dict__.setdefault('_tr_src', {})[_n] = labels
            return _o(self, trs(labels))
        setattr(cls, name, hdr)
    o_hl = W.QTreeWidget.setHeaderLabel
    W.QTreeWidget.setHeaderLabel = lambda self, s: o_hl(self, tr(s))
    for cls in (W.QTreeWidgetItem, W.QTableWidgetItem, W.QListWidgetItem):
        _wrap_item_class(cls)
    o_li, o_lis = W.QListWidget.addItem, W.QListWidget.addItems

    def list_addItem(self, x, *a):
        if isinstance(x, str):
            item = W.QListWidgetItem(x)
            return o_li(self, item)
        return o_li(self, x, *a)
    W.QListWidget.addItem = list_addItem
    W.QListWidget.addItems = lambda self, xs: [list_addItem(self, x) for x in xs] and None
    # status bar, dialogs
    _wrap_setter(W.QStatusBar, 'showMessage', 'message')
    for name in ('information', 'warning', 'critical', 'question', 'about'):
        _wrap_static(W.QMessageBox, name, (1, 2))
    _wrap_setter(W.QMessageBox, 'setText', 'text')
    _wrap_setter(W.QMessageBox, 'setInformativeText', 'informative')
    _wrap_setter(W.QMessageBox, 'setDetailedText', 'detailed')
    o_mb_add = W.QMessageBox.addButton

    def mb_add(self, *a):
        a = list(a)
        if a and isinstance(a[0], str):
            a[0] = tr(a[0])
        return o_mb_add(self, *a)
    W.QMessageBox.addButton = mb_add
    o_bb_add = W.QDialogButtonBox.addButton

    def bb_add(self, *a):
        a = list(a)
        if a and isinstance(a[0], str):
            a[0] = tr(a[0])
        return o_bb_add(self, *a)
    W.QDialogButtonBox.addButton = bb_add
    for name in ('getOpenFileName', 'getOpenFileNames', 'getSaveFileName', 'getExistingDirectory'):
        _wrap_static(W.QFileDialog, name, (1, 3))
    for name in ('getText', 'getItem', 'getInt', 'getDouble', 'getMultiLineText'):
        _wrap_static(W.QInputDialog, name, (1, 2))
    _wrap_init(W.QProgressDialog)
    _wrap_setter(W.QProgressDialog, 'setLabelText', 'label')
    _wrap_setter(W.QProgressDialog, 'setCancelButtonText', 'cancel')
    _wrap_getters()
    _install_wrapping()
    # custom-painted widgets (chips, step bars, empty-list glyph) draw their text themselves
    o_dt = QtGui.QPainter.drawText

    def drawText(self, *a):
        a = [tr(x) if isinstance(x, str) else x for x in a]
        return o_dt(self, *a)
    QtGui.QPainter.drawText = drawText
    _retranslate_hooks.clear()


def _wrap_getters():
    """Code reads texts back as keys ('자동 …', a table name, a combo value):
    the Python getters return the Korean source, whatever is shown.  (Qt
    itself paints the shown text; `shown()` gives that.)"""
    from PySide6 import QtGui, QtWidgets as W

    def getter(cls, name, key):
        orig = getattr(cls, name)
        _ORIG[(cls, name)] = orig

        def get(self, *a):
            d = getattr(self, '_tr_src', None)
            if d and key in d and not a:
                return d[key]
            return orig(self, *a)
        get.__name__ = name
        setattr(cls, name, get)
    getter(W.QLabel, 'text', 'text')
    getter(W.QAbstractButton, 'text', 'text')
    getter(W.QGroupBox, 'title', 'title')
    getter(W.QMenu, 'title', 'title')
    getter(W.QWidget, 'toolTip', 'tooltip')
    getter(W.QWidget, 'windowTitle', 'window')
    getter(QtGui.QAction, 'text', 'text')
    getter(QtGui.QAction, 'toolTip', 'tooltip')
    for cls in (W.QSpinBox, W.QDoubleSpinBox):
        getter(cls, 'suffix', 'suffix')
        getter(cls, 'prefix', 'prefix')
        getter(cls, 'specialValueText', 'special')
    cb = W.QComboBox
    o_ct, o_it, o_ft = cb.currentText, cb.itemText, cb.findText
    _ORIG[(cb, 'currentText')] = o_ct
    _ORIG[(cb, 'itemText')] = o_it

    def _src(self, i):
        if i < 0:
            return None
        m = self.model()
        return m.data(m.index(i, 0), ROLE_SRC)

    def itemText(self, i):
        return _src(self, i) or o_it(self, i)

    def currentText(self):
        i = self.currentIndex()
        src = _src(self, i)
        if src and (not self.isEditable() or o_ct(self) == o_it(self, i)):
            return src
        return o_ct(self)

    def findText(self, text, *a):
        if not a:
            for i in range(self.count()):
                if (_src(self, i) or o_it(self, i)) == text:
                    return i
        return o_ft(self, tr(text), *a)
    cb.itemText, cb.currentText, cb.findText = itemText, currentText, findText
    tw = W.QTabWidget
    o_tt = tw.tabText
    _ORIG[(tw, 'tabText')] = o_tt

    def tabText(self, i):
        page = self.widget(i)
        return getattr(page, '_tr_tab', None) or o_tt(self, i)
    tw.tabText = tabText
    for cls in (W.QTreeWidgetItem, W.QTableWidgetItem, W.QListWidgetItem):
        o = cls.text
        _ORIG[(cls, 'text')] = o
        if cls is W.QTreeWidgetItem:
            def text(self, col, _o=o):
                return self.data(col, ROLE_SRC) or _o(self, col)
        else:
            def text(self, _o=o):
                return self.data(ROLE_SRC) or _o(self)
        cls.text = text


WRAP_W = 250  # px: a check box with a longer text gets a word-wrapping label


def _install_wrapping():
    """A QCheckBox / QRadioButton never wraps its text, so a long one (often
    in English) would hold a panel wide.  When such a box is first shown, its
    text moves into a word-wrapping label beside it (like `wrapped_check`)."""
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QApplication

    class Wrapper(QObject):
        def eventFilter(self, obj, ev):
            if ev.type() == QEvent.Type.Show:
                try:
                    _maybe_wrap(obj)
                except Exception:  # noqa: BLE001
                    pass
            return False
    app = QApplication.instance()
    if app is not None:
        global _wrapper
        _wrapper = Wrapper(app)
        app.installEventFilter(_wrapper)


_wrapper = None


def _maybe_wrap(box):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (QBoxLayout, QCheckBox, QFormLayout, QHBoxLayout, QLabel, QRadioButton,
                                   QWidget)
    if not isinstance(box, (QCheckBox, QRadioButton)) or '_tr_label' in box.__dict__ \
            or box.property('hig_chip') or box.property('hig_switch') or box.__dict__.get('_tr_nowrap'):
        return
    text = shown(box, 'text')
    if not text or box.fontMetrics().horizontalAdvance(text) <= WRAP_W:
        return
    par = box.parentWidget()
    lay = par.layout() if par is not None else None
    host = _find_layout(lay, box) if lay is not None else None
    if host is None:
        return
    src = source(box)
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    label = QLabel(src)
    label.setWordWrap(True)
    label.setToolTip(box.toolTip())
    label.setEnabled(box.isEnabled())
    label.mousePressEvent = lambda _e, b=box: b.isEnabled() and b.click()
    box.__dict__['_tr_label'] = label
    if isinstance(host, QFormLayout):
        r, role = host.getWidgetPosition(box)
        host.removeWidget(box)
        row.addWidget(box, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(label, 1)
        host.setLayout(r, role, row)
    elif isinstance(host, QBoxLayout):
        i = host.indexOf(box)
        st = host.stretch(i)
        host.takeAt(i)
        row.addWidget(box, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(label, 1)
        host.insertLayout(i, row, st)
    else:
        del box.__dict__['_tr_label']
        return
    for cls in type(box).__mro__:
        f = _ORIG.get((cls, 'setText'))
        if f is not None:
            f(box, '')
            break
    from PySide6.QtWidgets import QSizePolicy
    box.setSizePolicy(QSizePolicy.Policy.Fixed, box.sizePolicy().verticalPolicy())
    # follow visibility / enabled state of the box
    from PySide6.QtCore import QObject, QEvent

    class Follow(QObject):
        def eventFilter(self, o, ev):
            t = ev.type()
            try:
                if t == QEvent.Type.Show:
                    label.show()
                elif t == QEvent.Type.Hide:
                    label.hide()
                elif t == QEvent.Type.EnabledChange:
                    label.setEnabled(o.isEnabled())
            except RuntimeError:
                pass
            return False
    f = Follow(box)
    box.installEventFilter(f)


def _find_layout(lay, w):
    from PySide6.QtWidgets import QLayout
    if lay is None:
        return None
    if lay.indexOf(w) >= 0:
        return lay
    for i in range(lay.count()):
        sub = lay.itemAt(i).layout()
        if isinstance(sub, QLayout):
            r = _find_layout(sub, w)
            if r is not None:
                return r
    return None


def shown(obj, name='text', *a):
    """The text Qt shows (translated), for checks."""
    for cls in type(obj).__mro__:
        f = _ORIG.get((cls, name))
        if f is not None:
            return f(obj, *a)
    return getattr(obj, name)(*a)


# ---- switching open windows ----------------------------------------------------------------

_retranslate_hooks: list = []


def on_change(fn):
    """fn() runs after every language change (widgets that build text themselves)."""
    _retranslate_hooks.append(fn)


_APPLY = {
    'text': 'setText', 'title': 'setTitle', 'tooltip': 'setToolTip', 'window': 'setWindowTitle',
    'status': 'setStatusTip', 'placeholder': 'setPlaceholderText', 'suffix': 'setSuffix', 'prefix': 'setPrefix',
    'special': 'setSpecialValueText', 'label': 'setLabelText', 'cancel': 'setCancelButtonText',
    'icontext': 'setIconText',
}


def _reapply(obj):
    d = getattr(obj, '_tr_src', None)
    if not d:
        return
    for key, src in list(d.items()):
        if key == 'text' and '_tr_label' in obj.__dict__:
            continue  # its word-wrapping label is retranslated on its own
        name = _APPLY.get(key)
        if name and hasattr(obj, name):
            try:
                getattr(obj, name)(src)
            except Exception:  # noqa: BLE001
                pass
        elif key in ('setHorizontalHeaderLabels', 'setVerticalHeaderLabels', 'setHeaderLabels'):
            try:
                getattr(obj, key)(src)
            except Exception:  # noqa: BLE001
                pass


def retranslate():
    """Every open window in the current language (texts set through the
    wrapped setters; widgets that compose text themselves use on_change)."""
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import (QApplication, QComboBox, QListWidget, QMenu, QTableWidget, QTabWidget,
                                   QTreeWidget, QTreeWidgetItemIterator)
    app = QApplication.instance()
    if app is None:
        return
    seen = set()
    for w in app.allWidgets():
        _reapply(w)
        for a in w.actions():
            if id(a) not in seen:
                seen.add(id(a))
                _reapply(a)
        if isinstance(w, QMenu):
            _reapply(w.menuAction())
        if isinstance(w, QComboBox):
            m = w.model()
            for i in range(w.count()):
                src = m.data(m.index(i, 0), ROLE_SRC)
                if src:
                    _ORIG_COMBO_SET(w, i, tr(src))
        elif isinstance(w, QTabWidget):
            for i in range(w.count()):
                src = getattr(w.widget(i), '_tr_tab', None) if w.widget(i) is not None else None
                if src:
                    w.setTabText(i, src)
        elif isinstance(w, QTreeWidget):
            it = QTreeWidgetItemIterator(w)
            while it.value():
                item = it.value()
                for c in range(item.columnCount()):
                    src = item.data(c, ROLE_SRC)
                    if src:
                        item.setText(c, src)
                it += 1
        elif isinstance(w, QTableWidget):
            for r in range(w.rowCount()):
                for c in range(w.columnCount()):
                    item = w.item(r, c)
                    if item is not None and item.data(ROLE_SRC):
                        item.setText(item.data(ROLE_SRC))
        elif isinstance(w, QListWidget):
            for r in range(w.count()):
                item = w.item(r)
                if item.data(ROLE_SRC):
                    item.setText(item.data(ROLE_SRC))
    for a in app.findChildren(QAction) if hasattr(app, 'findChildren') else []:
        _reapply(a)
    from PySide6.QtWidgets import QAbstractButton
    for w in app.allWidgets():
        if isinstance(w, QAbstractButton) and w.isVisible():
            try:
                _maybe_wrap(w)  # a text that grew longer in this language
            except Exception:  # noqa: BLE001
                pass
        w.updateGeometry()
        w.update()
    for fn in list(_retranslate_hooks):
        try:
            fn()
        except Exception:  # noqa: BLE001
            import traceback
            traceback.print_exc()


def _ORIG_COMBO_SET(w, i, text):
    from PySide6.QtCore import Qt
    w.model().setData(w.model().index(i, 0), text, Qt.ItemDataRole.DisplayRole)
