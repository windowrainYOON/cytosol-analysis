"""Record which signals of every button / control are connected, to check that
a refactor of the UI components did not change what the controls do
(owner rule 2026-11-25: "각 버튼이나 컴포넌트의 신호 전달이 이전과 동일하면 돼").

    QT_QPA_PLATFORM=offscreen python3 scripts/signal_map.py snap OUT.json
    python3 scripts/signal_map.py diff BEFORE.json AFTER.json

A control is named by the attribute path that holds it (``MainWindow.roi_panel.detect_btn``,
``GraphWindow.docs_list``) when it has one, else by its window, kind and text. For each
control the snapshot keeps the connected signals with their receiver count.
QActions are recorded the same way (text, shortcut, triggered / toggled receivers).
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# signals that Qt / the style connect by themselves and refactors may move freely
IGNORE = {'destroyed', 'objectNameChanged', 'windowTitleChanged', 'windowIconChanged',
          'windowIconTextChanged'}
# QAction.changed is connected by the menus / tool buttons that show the action
ACTION_IGNORE = {'changed'}
# widget kinds whose own signals matter (containers only matter through attribute names)
KINDS = ('QAbstractButton', 'QAbstractSlider', 'QAbstractSpinBox', 'QComboBox', 'QLineEdit',
         'QTextEdit', 'QPlainTextEdit', 'QAbstractItemView', 'QTabWidget', 'QTabBar', 'QAction',
         'QGroupBox', 'QDialog', 'QMenu', 'QSplitter', 'QShortcut', 'QGraphicsView',
         'QStackedWidget', 'QTimer')


def _kind(obj):
    mo = obj.metaObject()
    while mo is not None:
        name = mo.className()
        if name in KINDS:
            return name
        mo = mo.superClass()
    return None


def _signals(obj) -> dict:
    from PySide6.QtCore import QMetaMethod, SIGNAL
    from PySide6.QtGui import QAction
    skip = IGNORE | (ACTION_IGNORE if isinstance(obj, QAction) else set())
    out = {}
    mo = obj.metaObject()
    for i in range(mo.methodCount()):
        m = mo.method(i)
        if m.methodType() != QMetaMethod.MethodType.Signal:
            continue
        sig = m.methodSignature().data().decode()
        name = sig.split('(')[0]
        if name in skip:
            continue
        try:
            n = obj.receivers(SIGNAL(sig))
        except Exception:  # noqa: BLE001
            continue
        if n > 0:
            out[sig] = out.get(sig, 0) + n
    return out


def _attr_names(root, top) -> dict:
    """id(QObject) -> 'Top.attr.attr' for the QObjects held in attributes of the
    window and of the app's own objects (panels, editors) reachable from it."""
    from PySide6.QtCore import QObject
    names = {}
    seen = set()
    stack = [(root, top, 0)]
    while stack:
        obj, path, depth = stack.pop()
        if id(obj) in seen or depth > 4:
            continue
        seen.add(id(obj))
        try:
            d = vars(obj)
        except TypeError:
            continue
        for k, v in list(d.items()):
            if k.startswith('__'):
                continue
            vals = []
            if isinstance(v, QObject):
                vals = [(f'{path}.{k}', v)]
            elif isinstance(v, (list, tuple)) and len(v) < 400:
                vals = [(f'{path}.{k}[{i}]', x) for i, x in enumerate(v) if isinstance(x, QObject)]
            elif isinstance(v, dict) and len(v) < 400:
                vals = [(f'{path}.{k}[{kk!r}]', x) for kk, x in v.items()
                        if isinstance(x, QObject) and isinstance(kk, (str, int))]
            for p, x in vals:
                try:
                    if id(x) not in names:
                        names[id(x)] = p
                except RuntimeError:
                    continue
                if type(x).__module__.startswith('cytosol'):
                    stack.append((x, p, depth + 1))
            if (not isinstance(v, QObject) and type(v).__module__.startswith('cytosol')
                    and hasattr(v, '__dict__')):
                stack.append((v, f'{path}.{k}', depth + 1))
    return names


def _text(obj):
    for getter in ('text', 'title', 'windowTitle', 'toolTip', 'objectName', 'placeholderText'):
        f = getattr(obj, getter, None)
        if callable(f):
            try:
                t = f()
            except Exception:  # noqa: BLE001
                continue
            if isinstance(t, str) and t.strip():
                return t.strip().replace('\n', ' ')[:60]
    return ''


def snapshot_window(w, top: str) -> dict:
    from PySide6.QtCore import QObject
    from PySide6.QtGui import QAction
    names = _attr_names(w, top)
    named, anon = {}, Counter()
    objs = [w] + w.findChildren(QObject)
    for o in objs:
        kind = _kind(o)
        if kind is None and id(o) not in names:
            continue
        sigs = _signals(o)
        extra = ''
        if isinstance(o, QAction):
            sc = o.shortcut().toString() if o.shortcut() else ''
            extra = f' sc={sc}' if sc else ''
        if id(o) in names:
            if sigs or kind:
                named[names[id(o)]] = {'sigs': sigs, 'kind': kind or type(o).__name__,
                                       'text': _text(o) + extra}
        elif sigs:
            key = f'{top} | {kind} | {_text(o)}{extra} | ' + ','.join(
                f'{s}={n}' for s, n in sorted(sigs.items()))
            anon[key] += 1
    return {'named': named, 'anon': dict(anon)}


def snapshot() -> dict:
    import numpy as np  # noqa: F401
    from PySide6.QtWidgets import QApplication

    from cytosol import i18n, theme
    from cytosol.settings import view_settings
    from PySide6.QtCore import QSettings
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    view_settings.use_store(QSettings(str(tmp / 'p.ini'), QSettings.Format.IniFormat))
    i18n.install()
    i18n.set_language('ko')
    app = QApplication.instance() or QApplication([sys.argv[0]])
    theme.apply(app)
    from cytosol.app import MainWindow
    from cytosol.selftest import _synthetic_item
    win = MainWindow()
    win.show()
    item = _synthetic_item()
    win._add_item(item)
    try:
        win._select(0)
    except Exception:  # noqa: BLE001
        pass
    for name in list(getattr(win, 'tab_pages', {})):
        try:
            win.show_tab(name)
        except Exception:  # noqa: BLE001
            pass
    app.processEvents()
    out = {'MainWindow': snapshot_window(win, 'MainWindow')}

    def add(name, make):
        try:
            w = make()
            app.processEvents()
            out[name] = snapshot_window(w, name)
        except Exception as e:  # noqa: BLE001
            out[name] = {'error': repr(e)}

    from cytosol.settings import PreferencesDialog
    from cytosol.export_dialog import ExportDialog
    from cytosol.pipeline_window import LibraryDialog
    add('GraphWindow', win.graph_window)
    add('FigureWindow', lambda: (win.open_figure(), win.figure_win)[1])
    add('PreferencesDialog', lambda: PreferencesDialog(win))
    add('ExportDialog', lambda: ExportDialog(win, None))
    add('PipelineWindow', win.pipeline_window)
    add('LibraryDialog', lambda: LibraryDialog(win, getattr(win, '_pipe_win', None)))
    add('LogWindow', lambda: (win.open_log(), win.log_win)[1])
    add('BatchResults', lambda: (win.show_batch_results(), win.batch_win)[1])

    def wizard():
        from cytosol.graph_editors import GraphWizard
        from cytosol import graph as G
        t = G.Table('t', ['group', 'value'], [['a', 1.0], ['a', 2.0], ['b', 3.0]])
        data = G.GraphData('t', [t], G.GraphSpec())
        return GraphWizard('새 그래프', data, win)
    add('GraphWizard', wizard)
    return out


def diff(a: dict, b: dict) -> int:
    bad = 0
    for top in sorted(set(a) | set(b)):
        wa, wb = a.get(top, {}), b.get(top, {})
        if 'error' in wa or 'error' in wb:
            print(f'[{top}] snapshot error: before={wa.get("error")} after={wb.get("error")}')
            continue
        na, nb = wa.get('named', {}), wb.get('named', {})
        for k in sorted(set(na) | set(nb)):
            sa = na.get(k, {}).get('sigs')
            sb = nb.get(k, {}).get('sigs')
            if sa is None:
                if sb:
                    print(f'+ {k}: {sb}')
                continue
            if sb is None:
                if sa:
                    print(f'- {k}: {sa}')
                    bad += 1
                continue
            if sa != sb:
                print(f'~ {k}: {sa} -> {sb}')
                bad += 1
        aa, ab = Counter(wa.get('anon', {})), Counter(wb.get('anon', {}))

        def by_wiring(c):  # (window, kind, signals) without the text: a new label is no lost wire
            out = Counter()
            for k, n in c.items():
                top, kind, _text, sigs = k.split(' | ', 3)
                out[(top, kind, sigs)] += n
            return out
        wa_, wb_ = by_wiring(aa), by_wiring(ab)
        for k in sorted(set(aa) | set(ab)):
            if aa[k] != ab[k]:
                top, kind, _t, sigs = k.split(' | ', 3)
                same = wa_[(top, kind, sigs)] == wb_[(top, kind, sigs)]
                tag = '=' if same else ('-' if aa[k] > ab[k] else '+')
                print(f'{tag} anon {k}: {aa[k]} -> {ab[k]}' + ('  (text only)' if same else ''))
        for k in sorted(set(wa_) | set(wb_)):
            if wa_[k] > wb_[k]:
                print(f'- wiring {" | ".join(k)}: {wa_[k]} -> {wb_[k]}')
                bad += 1
    print(f'{bad} lost / changed connections')
    return bad


if __name__ == '__main__':
    if sys.argv[1] == 'snap':
        data = snapshot()
        Path(sys.argv[2]).write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True))
        n = sum(len(v.get('named', {})) for v in data.values())
        m = sum(sum(v.get('anon', {}).values()) for v in data.values())
        print(f'{n} named, {m} unnamed controls; errors:',
              [k for k, v in data.items() if 'error' in v])
        import os
        os._exit(0)
    else:
        sys.exit(1 if diff(json.loads(Path(sys.argv[2]).read_text()),
                           json.loads(Path(sys.argv[3]).read_text())) else 0)
