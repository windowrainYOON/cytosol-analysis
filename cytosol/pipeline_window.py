"""파이프라인 창 (파일 › 파이프라인… ⇧⌘P), 보관함, and the review band of the
main window (design v3.x, /mnt/project-files/pipeline/; built in v0.73).

Window: toolbar (파이프라인 pop-up, 저장…, 데이터 folder, 실행), a line with
the stage / object / review count chip and the result folder, a sidebar of
stages under their group headings (drag within a group, ⌥↑ / ⌥↓, context
menu) and the selected stage's settings cards on the right. The run goes
through `pipeline.Runner`; at a 검토 stage the main window shows the
`ReviewBand` above the canvas until 검토 끝내고 계속."""

from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import pipeline as P
from . import theme
from .flow import FlowLayout

STAGE = Qt.ItemDataRole.UserRole          # stage index on stage rows
HEAD = Qt.ItemDataRole.UserRole + 1       # group key on heading rows
GROUP_NOTE = {'start': '데이터', 'detect': '이미지 → object', 'track': 'object → 트랙', 'op': 'object → object',
              'measure': 'object → 표', 'human': '검토', 'end': '그래프 · 저장'}
SOURCE_TEXT = ('이 단계에 저장된 설정', '탭의 지금 설정')
TAB_OF = {'roi': 'roi_tab', 'particle': 'particle_tab', 'mito': 'mito_tab', 'track': 'track_tab',
          'bands': 'bands_tab', 'coloc': 'coloc_tab', 'frap': 'frap_tab', 'cyto_track': 'cyto_track_tab'}
EXPORT_SKIP = ('integrated',)


def _card(title=None):
    box = QGroupBox(title or '')
    form = QFormLayout(box)
    return box, form


def _hint(text):
    lab = QLabel(text)
    lab.setWordWrap(True)
    return theme.hint(lab)


def _combo(items, current=None):
    c = QComboBox()
    for it in items:
        if isinstance(it, tuple):
            c.addItem(it[1], it[0])
        else:
            c.addItem(str(it), it)
    if current is not None:
        i = c.findData(current)
        if i >= 0:
            c.setCurrentIndex(i)
    return c


def _status_chip(text, kind='neutral'):
    return theme.StatusLabel(text, kind)


def _flow(widgets):
    w = QWidget()
    f = FlowLayout(w)
    f.setContentsMargins(0, 0, 0, 0)
    for x in widgets:
        f.addWidget(x)
    return w


def _chip_box(text, on):
    b = theme.chip(QCheckBox(text))
    b.setChecked(bool(on))
    return b


class StageList(QListWidget):
    """Stages under group headings; a stage moves only inside its group."""

    moved = Signal(int, int)      # from index, to index (in spec.stages)
    menuAsked = Signal(int, object)

    def __init__(self):
        super().__init__()
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setWordWrap(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.setObjectName('hig_sidebar_list')

    def _menu(self, pos):
        it = self.itemAt(pos)
        if it is not None and it.data(STAGE) is not None:
            self.menuAsked.emit(it.data(STAGE), self.viewport().mapToGlobal(pos))

    def dropEvent(self, ev):
        src = self.currentItem()
        if src is None or src.data(STAGE) is None:
            ev.ignore()
            return
        frm = src.data(STAGE)
        target = self.itemAt(ev.position().toPoint())
        ev.setDropAction(Qt.DropAction.IgnoreAction)
        ev.accept()
        if target is None or target is src:
            return
        to = target.data(STAGE)
        if to is None:   # dropped on a heading: first stage of that group
            k = self.row(target) + 1
            nxt = self.item(k) if k < self.count() else None
            to = nxt.data(STAGE) if nxt is not None and nxt.data(STAGE) is not None else None
        if to is not None and to != frm:
            QTimer.singleShot(0, lambda: self.moved.emit(frm, to))


class PipelineWindow(QDialog):
    def __init__(self, win, spec: P.PipelineSpec | None = None, path=None):
        super().__init__(win)
        self.win = win
        self.setWindowTitle('파이프라인')
        self.resize(1100, 760)
        self.spec = spec or P.find_preset('세포질 + 입자 · 띠')
        self.path = Path(path) if path else None
        self.runner: P.Runner | None = None
        self.sel = 0
        self._dirty = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 20)
        outer.setSpacing(10)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.addWidget(QLabel('파이프라인'))
        self.pick = QComboBox()
        self.pick.setMinimumWidth(200)
        self.pick.activated.connect(self._picked)
        bar.addWidget(self.pick)
        self.save_btn = QPushButton('저장…')
        m = QMenu(self.save_btn)
        m.addAction('저장', self.save)
        m.addAction('다른 이름으로 저장…', lambda: self.save(ask=True))
        m.addAction('파일에서 불러오기…', self.load_dialog)
        m.addAction('복제', self.duplicate)
        m.addSeparator()
        m.addAction('보관함…', self.show_library)
        self.save_btn.setMenu(m)
        bar.addWidget(self.save_btn)
        bar.addSpacing(16)
        bar.addWidget(QLabel('데이터'))
        self.folder = QLineEdit(self.spec.input.get('folder', ''))
        self.folder.setPlaceholderText('비우면 지금 열린 이미지')
        self.folder.setMinimumWidth(220)
        self.folder.editingFinished.connect(self._folder_changed)
        bar.addWidget(self.folder, 1)
        fb = QPushButton('폴더 선택…')
        fb.clicked.connect(self._pick_folder)
        bar.addWidget(fb)
        bar.addSpacing(16)
        self.run_btn = theme.prominent(QPushButton('실행'))
        self.run_btn.clicked.connect(self.run)
        bar.addWidget(self.run_btn)
        outer.addLayout(bar)

        line = QHBoxLayout()
        self.count_chip = _status_chip('', 'neutral')
        self.count_chip.setWordWrap(False)
        line.addWidget(self.count_chip)
        self.out_label = QLabel('')
        theme.secondary(self.out_label)
        line.addWidget(self.out_label, 1)
        outer.addLayout(line)

        # progress / done row (hidden until a run)
        self.prog_row = QWidget()
        pr = QHBoxLayout(self.prog_row)
        pr.setContentsMargins(0, 0, 0, 0)
        self.prog = QProgressBar()
        self.prog.setTextVisible(False)
        self.prog_text = QLabel('')
        pr.addWidget(self.prog_text)
        pr.addWidget(self.prog, 1)
        self.prog_row.setVisible(False)
        outer.addWidget(self.prog_row)

        body = QHBoxLayout()
        body.setSpacing(20)
        left = QVBoxLayout()
        self.add_btn = QPushButton('＋ 단계 추가')
        self.add_menu = QMenu(self.add_btn)
        for g, title in P.GROUPS:
            sub = self.add_menu.addMenu(title)
            for k, v in P.STAGES.items():
                if v['group'] == g:
                    a = sub.addAction(v['title'])
                    a.setToolTip(v['desc'])
                    a.triggered.connect(lambda _c=False, k=k: self.add_stage(k))
        self.add_btn.setMenu(self.add_menu)
        left.addWidget(self.add_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.list = StageList()
        self.list.setFixedWidth(300)
        self.list.currentItemChanged.connect(self._row_changed)
        self.list.moved.connect(self.move_stage)
        self.list.menuAsked.connect(self._stage_menu)
        left.addWidget(self.list, 1)
        body.addLayout(left)
        self.pages = QStackedWidget()
        self.editor = QScrollArea()
        self.editor.setWidgetResizable(True)
        self.editor.setFrameShape(QScrollArea.Shape.NoFrame)
        self.pages.addWidget(self.editor)
        self.done_page = QWidget()
        self.pages.addWidget(self.done_page)
        body.addWidget(self.pages, 1)
        outer.addLayout(body, 1)

        QShortcut(QKeySequence('Alt+Up'), self, lambda: self._nudge(-1))
        QShortcut(QKeySequence('Alt+Down'), self, lambda: self._nudge(1))
        self._fill_pick()
        self.rebuild()

    # ---- spec / library ----
    def _fill_pick(self):
        self.pick.blockSignals(True)
        self.pick.clear()
        self.lib = P.library()
        names = [n for n, _p, _s in self.lib]
        if self.spec.name not in names:
            self.pick.addItem(self.spec.name, None)
        for n, p, _s in self.lib:
            self.pick.addItem(n + ('' if p else ' (기본)'), n)
        i = max(self.pick.findText(self.spec.name), self.pick.findData(self.spec.name), 0)
        self.pick.setCurrentIndex(i)
        self.pick.blockSignals(False)

    def _picked(self, i):
        name = self.pick.itemData(i)
        if name is None:
            return
        for n, p, s in self.lib:
            if n == name:
                self.set_spec(s.copy(), p)
                return

    def set_spec(self, spec, path=None):
        folder = self.folder.text()
        self.spec = spec
        self.path = Path(path) if path else None
        if folder and not spec.input.get('folder'):
            spec.input['folder'] = folder
        self.folder.setText(spec.input.get('folder', ''))
        self.sel = 0
        self._fill_pick()
        self.rebuild()

    def save(self, ask=False):
        path = self.path
        if ask or path is None:
            d = P.library_dir()
            d.mkdir(parents=True, exist_ok=True)
            fn, _ = QFileDialog.getSaveFileName(self, '파이프라인 저장', str(d / f'{self.spec.name}{P.EXT}'),
                                                f'파이프라인 (*{P.EXT})')
            if not fn:
                return None
            path = Path(fn)
            if ask or self.spec.name in ('새 파이프라인',) or path.stem != self.spec.name:
                self.spec.name = path.stem
        self.path = self.spec.save(path)
        self.win.statusBar().showMessage(f'파이프라인 저장: {self.path}')
        self._fill_pick()
        return self.path

    def load_dialog(self):
        fn, _ = QFileDialog.getOpenFileName(self, '파이프라인 불러오기', str(P.library_dir()),
                                            f'파이프라인 · 일괄 분석 설정 (*{P.EXT} *.json);;All files (*)')
        if fn:
            self.load_file(fn)

    def load_file(self, fn):
        try:
            self.set_spec(P.PipelineSpec.load(fn), fn if fn.endswith(P.EXT) else None)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, '파이프라인', f'불러오지 못했습니다: {exc}')

    def duplicate(self):
        s = self.spec.copy()
        s.name = f'{s.name} 복사본'
        self.set_spec(s)

    def show_library(self):
        dlg = LibraryDialog(self.win, self)
        dlg.exec()

    def _pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, '데이터 폴더', self.folder.text() or str(Path.home()))
        if d:
            self.folder.setText(d)
            self._folder_changed()

    def _folder_changed(self):
        self.spec.input['folder'] = self.folder.text().strip()
        self._update_line()

    # ---- sidebar ----
    def rebuild(self):
        self.list.blockSignals(True)
        self.list.clear()
        order = sorted(range(len(self.spec.stages)), key=lambda i: (P.stage_rank(self.spec.stages, i), i))
        if order != list(range(len(order))):
            self.spec.stages = [self.spec.stages[i] for i in order]
        errs = P.validate(self.spec)
        bad = {int(e.split('단계')[0]) - 1 for e in errs if e.split('단계')[0].isdigit()}
        last = None
        for i, st in enumerate(self.spec.stages):
            g = P.STAGES[st['kind']]['group']
            if g == 'human' and last is not None:
                g = last           # a 검토 stage sits under the group it follows
            if g != last:
                h = QListWidgetItem(f'{dict(P.GROUPS)[g]}   {GROUP_NOTE[g]}')
                h.setFlags(Qt.ItemFlag.NoItemFlags | Qt.ItemFlag.ItemIsEnabled)
                h.setData(HEAD, g)
                f = h.font()
                f.setBold(True)
                h.setFont(f)
                self.list.addItem(h)
                last = g
            title = P.stage_title(st) if st['kind'] != 'op' else (st['settings'].get('out') or '연산')
            sub = P.stage_summary(st)
            tags = []
            if st['kind'] == 'human.review':
                tags.append('● 검토')
            if not st.get('enabled', True):
                tags.append('꺼짐')
            if i in bad:
                tags.append('⚠ object 없음')
            it = QListWidgetItem(f'{i + 1}  {title}{"   " + " · ".join(tags) if tags else ""}\n     {sub}')
            it.setData(STAGE, i)
            it.setSizeHint(QSize(280, 46))
            if not st.get('enabled', True):
                it.setForeground(self.palette().color(self.palette().ColorRole.PlaceholderText))
            if i in bad:
                it.setToolTip('\n'.join(e for e in errs if e.startswith(f'{i + 1}단계')))
            self.list.addItem(it)
            if i == self.sel:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)
        self._update_line()
        self.show_stage(self.sel)

    def _update_line(self):
        n = len(self.spec.stages)
        objs = len(self.spec.objects_before(n))
        rv = sum(1 for s in self.spec.stages if s['kind'] == 'human.review' and s.get('enabled', True))
        errs = P.validate(self.spec)
        self.count_chip.setText(f'{n}단계 · object {objs}개 · 검토 {rv}번' + (f' · 문제 {len(errs)}' if errs else ''))
        self.count_chip.set_kind('warning' if errs else 'neutral')
        items = self._items_for_name()
        try:
            out = P.result_folder(self.spec, items) if items else None
        except Exception:  # noqa: BLE001
            out = None
        exp = next((s['settings'] for s in self.spec.stages if s['kind'] == 'end.export'), None)
        if exp is not None and exp.get('dest') not in ('processed', '', None):
            out = Path(exp['dest']) / '…'
        self.out_label.setText(f'결과: {out}' if out else '결과: 데이터 폴더의 상위 › Processed/')
        self.run_btn.setToolTip('\n'.join(errs) if errs else '파이프라인을 처음부터 실행합니다.')

    def _items_for_name(self):
        f = self.folder.text().strip()
        if f:
            class _I:
                path = Path(f) / 'x'
            return [_I]
        return [it for it in self.win.items if getattr(it, 'path', None)]

    def _row_changed(self, cur, _prev):
        if cur is not None and cur.data(STAGE) is not None:
            self.sel = cur.data(STAGE)
            self.show_stage(self.sel)

    def _nudge(self, d):
        i = self.sel
        j = i + d
        if 0 <= j < len(self.spec.stages) and self._same_group(i, j):
            self.move_stage(i, j)

    def _same_group(self, i, j):
        g = lambda k: P.STAGES[self.spec.stages[k]['kind']]['group']  # noqa: E731
        return g(i) == g(j) or 'human' in (g(i), g(j))

    def move_stage(self, frm, to):
        if not self._same_group(frm, to):
            self.win.statusBar().showMessage('단계는 자기 묶음 안에서만 옮길 수 있습니다.', 4000)
            return
        st = self.spec.stages.pop(frm)
        self.spec.stages.insert(to, st)
        errs = [e for e in P.validate(self.spec) if 'object' in e]
        if errs:
            self.spec.stages.pop(to)
            self.spec.stages.insert(frm, st)
            self.win.statusBar().showMessage('그 자리에서는 쓸 object가 아직 없어 옮기지 않았습니다: ' + errs[0], 6000)
            return
        self.sel = to
        self.rebuild()

    def add_stage(self, kind):
        st = P.default_stage(kind)
        g = P.GROUP_ORDER[P.STAGES[kind]['group']]
        have = self.spec.objects_before(len(self.spec.stages))
        if kind == 'op':
            st['settings']['input'] = have[-1] if have else '세포'
            st['settings']['out'] = f'{st["settings"]["input"]} (연산)'
        if kind == 'measure.intensity' and have:
            st['settings']['targets'] = [{'object': have[-1], 'channels': []}]
        if STAGES_PANEL(kind):
            st['settings'][self._settings_key(kind)] = P.capture_settings(self.win, kind)
        at = len(self.spec.stages)
        if kind == 'human.review':     # right after the selected stage
            at = min(self.sel + 1, len(self.spec.stages))
        else:
            for i, s in enumerate(self.spec.stages):
                if P.GROUP_ORDER[P.STAGES[s['kind']]['group']] > g and P.STAGES[s['kind']]['group'] != 'human':
                    at = i
                    break
        self.spec.stages.insert(at, st)
        self.sel = at
        self.rebuild()

    @staticmethod
    def _settings_key(kind):
        return 'cell_track' if kind == 'track.cytosol' else 'panel'

    def _stage_menu(self, i, pos):
        m = QMenu(self)
        st = self.spec.stages[i]
        m.addAction('위로 (⌥↑)', lambda: self._nudge_at(i, -1))
        m.addAction('아래로 (⌥↓)', lambda: self._nudge_at(i, 1))
        m.addAction('복제', lambda: self._dup(i))
        m.addAction('켜기' if not st.get('enabled', True) else '끄기 (건너뛰기)', lambda: self._toggle(i))
        m.addSeparator()
        m.addAction('단계 삭제…', lambda: self._remove(i))
        m.exec(pos)

    def _nudge_at(self, i, d):
        self.sel = i
        self._nudge(d)

    def _dup(self, i):
        self.spec.stages.insert(i + 1, copy.deepcopy(self.spec.stages[i]))
        self.sel = i + 1
        self.rebuild()

    def _toggle(self, i):
        st = self.spec.stages[i]
        st['enabled'] = not st.get('enabled', True)
        self.rebuild()

    def _remove(self, i):
        if not theme.confirm_destructive(self, '단계 삭제', f'{i + 1}단계 「{P.stage_title(self.spec.stages[i])}」를 '
                                         '지울까요?', '삭제'):
            return
        self.remove_stage(i)

    def remove_stage(self, i):
        self.spec.stages.pop(i)
        self.sel = max(0, min(i, len(self.spec.stages) - 1))
        self.rebuild()

    # ---- editors ----
    def show_stage(self, i):
        self.pages.setCurrentWidget(self.editor)
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(12)
        if not self.spec.stages:
            lay.addWidget(_hint('단계가 없습니다. ＋ 단계 추가로 시작하세요.'))
            lay.addStretch()
            self.editor.setWidget(page)
            return
        i = max(0, min(i, len(self.spec.stages) - 1))
        st = self.spec.stages[i]
        meta = P.STAGES[st['kind']]
        head = QLabel(P.stage_title(st) if st['kind'] != 'op' else
                      f'{st["settings"].get("out") or "연산"}')
        theme.text_style(head, 'title-3')
        lay.addWidget(head)
        lay.addWidget(_hint(meta['desc']))
        build = getattr(self, '_ed_' + st['kind'].replace('.', '_'), None)
        if build is None:
            build = self._ed_panel if meta['panel'] else self._ed_plain
        build(lay, st, i)
        # name
        box, form = _card('이름')
        name = QLineEdit(st.get('name', ''))
        name.setPlaceholderText(meta['title'])
        name.editingFinished.connect(lambda: (st.__setitem__('name', name.text().strip()), self._refresh_row()))
        form.addRow('단계 이름', name)
        lay.addWidget(box)
        lay.addStretch()
        theme.unify(page)
        self.editor.setWidget(page)

    def _refresh_row(self):
        QTimer.singleShot(0, self.rebuild)

    def _ed_plain(self, lay, st, i):
        if st['out']:
            lay.addWidget(_hint('만드는 object: ' + ', '.join(st['out'])))

    def _ed_start_load(self, lay, st, i):
        s = st['settings']
        box, form = _card('불러오기')
        folder = QLineEdit(s.get('folder', ''))
        folder.setPlaceholderText('비우면 위 「데이터」 폴더 (또는 지금 열린 이미지)')
        folder.editingFinished.connect(lambda: s.__setitem__('folder', folder.text().strip()))
        form.addRow('폴더', folder)
        glob = QLineEdit(s.get('glob', '*'))
        glob.editingFinished.connect(lambda: s.__setitem__('glob', glob.text().strip() or '*'))
        form.addRow('파일 이름 패턴', glob)
        rec = QCheckBox('하위 폴더 포함')
        rec.setChecked(s.get('recursive', True))
        rec.toggled.connect(lambda v: s.__setitem__('recursive', v))
        form.addRow(rec)
        lay.addWidget(box)

    def _ed_panel(self, lay, st, i):
        """Detection / tracking / tab measurements: the tab's settings, stored in the stage."""
        k = st['kind']
        key = self._settings_key(k)
        s = st['settings']
        box, form = _card('설정')
        src = _combo([(0, SOURCE_TEXT[0]), (1, SOURCE_TEXT[1])], 0 if s.get(key) else 1)
        form.addRow('설정 출처', src)
        note = _hint('')
        form.addRow(note)

        def upd():
            stored = bool(s.get(key))
            note.setText('이 단계는 설정을 따로 저장합니다. 탭에서 다른 이미지를 만져도 파이프라인 결과는 바뀌지 않습니다.'
                         if stored else '실행할 때 탭의 지금 설정을 씁니다 (지금의 일괄 분석처럼).')

        def chose(ix):
            if src.itemData(ix) == 0 and not s.get(key):
                s[key] = P.capture_settings(self.win, k)
            elif src.itemData(ix) == 1:
                s[key] = None
            upd()
        src.currentIndexChanged.connect(chose)
        upd()
        row = QHBoxLayout()
        row.addStretch()
        take = QPushButton('탭 설정 가져오기')
        take.clicked.connect(lambda: (s.__setitem__(key, P.capture_settings(self.win, k)),
                                      src.setCurrentIndex(0), upd(),
                                      self.win.statusBar().showMessage(f'{i + 1}단계에 탭 설정을 가져왔습니다.', 4000)))
        row.addWidget(take)
        edit = QPushButton('탭에서 열어 고치기…')
        edit.clicked.connect(lambda: self.edit_in_tab(i))
        row.addWidget(edit)
        holder = QWidget()
        holder.setLayout(row)
        form.addRow(holder)
        lay.addWidget(box)
        if k.startswith(('detect', 'track')):
            box2, f2 = _card('대상')
            redo = _combo([(True, '다시 찾기'), (False, '그대로 두기')], bool(s.get('redo', True)))
            redo.currentIndexChanged.connect(lambda _x: s.__setitem__('redo', redo.currentData()))
            f2.addRow('이미 결과가 있으면', redo)
            f2.addRow(_hint('검토에서 고친 ROI를 지키려면 「그대로 두기」.'))
            lay.addWidget(box2)
        if st['out']:
            lay.addWidget(_hint('만드는 object: ' + ', '.join(st['out'])))

    def edit_in_tab(self, i):
        st = self.spec.stages[i]
        k = st['kind']
        key = self._settings_key(k)
        panel = P.STAGES[k]['panel']
        tab = TAB_OF.get(panel)
        before = P.capture_settings(self.win, k)
        if st['settings'].get(key):
            self._apply_tab(k, st['settings'][key])
        if tab:
            self.win.show_tab(tab)

        def apply():
            st['settings'][key] = P.capture_settings(self.win, k)
            self._apply_tab(k, before)
            self.show()
            self.raise_()
            self.rebuild()

        def cancel():
            self._apply_tab(k, before)
            self.show()
            self.raise_()
        self.win.pipeline_band().edit_mode(f'파이프라인 {i + 1}단계 「{P.stage_title(st)}」 설정 편집 중', apply, cancel)
        self.hide()

    def _apply_tab(self, kind, d):
        from .project import restore_widgets
        if d is None:
            return
        if kind == 'track.cytosol':
            self.win.cell_track_panel.set_settings(d)
        else:
            o = P._panel_obj(self.win, P.STAGES[kind]['panel'])
            if o is not None:
                restore_widgets(o, d)

    def _objects(self, i):
        return self.spec.objects_before(i) or ['세포']

    def _ed_op(self, lay, st, i):
        s = st['settings']
        objs = self._objects(i)
        # 1 input
        b1, f1 = _card('1  입력 object')
        inp = _combo(objs, s.get('input'))
        inp.setEditable(True)
        inp.currentTextChanged.connect(lambda t: (s.__setitem__('input', t), self._preview_later()))
        f1.addRow('object', inp)
        lay.addWidget(b1)
        # 2 where
        b2, f2 = _card('2  기준')
        where = s.setdefault('where', {'mode': 'all', 'conds': []})
        which = _combo([(0, '모두'), (1, '조건에 맞는 것만')], 1 if where.get('conds') else 0)
        f2.addRow('어느 것에', which)
        mode = _combo([('all', '모든 조건'), ('any', '하나라도')], where.get('mode', 'all'))
        mode.currentIndexChanged.connect(lambda _x: where.__setitem__('mode', mode.currentData()))
        f2.addRow('조건 묶기', mode)
        rows = QWidget()
        rl = QVBoxLayout(rows)
        rl.setContentsMargins(0, 0, 0, 0)
        f2.addRow(rows)
        addc = QPushButton('＋ 조건 추가')
        f2.addRow(addc)

        def fill_conds():
            while rl.count():
                w = rl.takeAt(0).widget()
                if w is not None:
                    w.deleteLater()
            for ci, c in enumerate(where.get('conds', [])):
                rl.addWidget(self._cond_row(where, ci, c, objs, fill_conds))
            on = which.currentData() == 1
            for w in (rows, addc, mode):
                w.setVisible(on)
                lab = f2.labelForField(w)
                if lab is not None:
                    lab.setVisible(on)

        def add_cond():
            where.setdefault('conds', []).append(['Area', '>=', 0])
            fill_conds()
            self._preview_later()
        addc.clicked.connect(add_cond)

        def which_changed(_x):
            if which.currentData() == 0:
                where['conds'] = []
            elif not where.get('conds'):
                where['conds'] = [['Area', '>=', 0]]
            fill_conds()
            self._preview_later()
        which.currentIndexChanged.connect(which_changed)
        fill_conds()
        lay.addWidget(b2)
        # 3 action
        b3, f3 = _card('3  동작')
        a = s.setdefault('action', {'do': 'keep'})
        grp = QButtonGroup(b3)
        radios = []
        for key, text in P.ACTIONS:
            r = QRadioButton(text)
            r.setChecked(a.get('do') == key)
            grp.addButton(r)
            r.toggled.connect(lambda on, key=key: on and (a.__setitem__('do', key), show_params(), self._preview_later()))
            radios.append(r)
        f3.addRow(_flow(radios))
        other = _combo(objs, a.get('with') or None)
        other.setEditable(True)
        other.currentTextChanged.connect(lambda t: (a.__setitem__('with', t), self._preview_later()))
        f3.addRow('상대 object', other)
        pair = _combo(P.PAIRS, a.get('pair', 'cell'))
        pair.currentIndexChanged.connect(lambda _x: (a.__setitem__('pair', pair.currentData()), self._preview_later()))
        f3.addRow('짝 맞추기', pair)
        um = QDoubleSpinBox()
        um.setRange(0, 100)
        um.setSuffix(' µm')
        um.setValue(float(a.get('um', 1.0)))
        um.valueChanged.connect(lambda v: (a.__setitem__('um', v), self._preview_later()))
        f3.addRow('거리', um)
        inner = QDoubleSpinBox()
        inner.setRange(0, 100)
        inner.setSuffix(' µm')
        inner.setValue(float(a.get('inner', 2.0)))
        inner.valueChanged.connect(lambda v: (a.__setitem__('inner', v), self._preview_later()))
        outer = QDoubleSpinBox()
        outer.setRange(0, 200)
        outer.setSuffix(' µm')
        outer.setValue(float(a.get('outer', 6.0)))
        outer.valueChanged.connect(lambda v: (a.__setitem__('outer', v), self._preview_later()))
        f3.addRow('고리 안쪽', inner)
        f3.addRow('고리 바깥쪽', outer)
        nb = QSpinBox()
        nb.setRange(1, 50)
        nb.setValue(int(a.get('n', 4)))
        nb.valueChanged.connect(lambda v: (a.__setitem__('n', v), self._preview_later()))
        f3.addRow('띠 개수', nb)
        note = _hint('')
        f3.addRow(note)
        rest = QLineEdit(s.get('rest', ''))
        rest.setPlaceholderText('비우면 버림')

        def show_params():
            do = a.get('do')
            vis = {other: do in ('subtract', 'add', 'intersect'), pair: do in ('subtract', 'add', 'intersect'),
                   um: do in ('dilate', 'erode'), inner: do == 'ring', outer: do == 'ring', nb: do == 'bands',
                   rest: True}
            theme.show_rows(f3, [w for w, v in vis.items() if v and w is not rest], True)
            theme.show_rows(f3, [w for w, v in vis.items() if not v and w is not rest], False)
            note.setText({'subtract': '세포마다 그 세포의 상대 object를 뺍니다 (강도 측정 영역식 cyto = cell − nuc 와 같은 계산).',
                          'add': '상대 object를 더합니다 (다른 영역과 겹치지 않는 부분만).',
                          'intersect': '상대 object와 겹친 부분만 남깁니다.',
                          'merge': '같은 부모(세포) 안의 조각을 하나로 합칩니다.',
                          'ring': '바깥 고리 (배경). 세포를 둘러싼 고리는 다른 세포를 피합니다.',
                          'bands': '핵 → 세포막 상대 거리로 n개 띠 (핵이 없으면 세포 가장자리 → 가운데).',
                          'keep': '기준에 맞는 것만 남깁니다.', 'drop': '기준에 맞는 것을 버립니다.'}.get(do, ''))
            theme.show_rows(f4, [rest], do in ('keep', 'drop') or bool(where.get('conds')))
        lay.addWidget(b3)
        # 4 result
        b4, f4 = _card('4  결과')
        out = QLineEdit(s.get('out', ''))
        out.editingFinished.connect(lambda: (s.__setitem__('out', out.text().strip()), self._refresh_row()))
        f4.addRow('결과 이름', out)
        rest.editingFinished.connect(lambda: (s.__setitem__('rest', rest.text().strip()), self._refresh_row()))
        f4.addRow('안 맞는 것 이름', rest)
        f4.addRow(_hint('결과 object는 세포 번호를 그대로 물려받고, 다음 단계의 기준 · 측정에 이름으로 씁니다.'))
        lay.addWidget(b4)
        show_params()
        # preview
        b5 = QGroupBox(f'미리 보기 · 현재 이미지 ({self.win.current.label if self.win.current else "없음"})')
        v5 = QVBoxLayout(b5)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(220)
        v5.addWidget(self.preview)
        self.preview_chips = QHBoxLayout()
        v5.addLayout(self.preview_chips)
        lay.addWidget(b5)
        self._preview_i = i
        self._preview_later()

    def _cond_row(self, where, ci, c, objs, refill):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        chs = list(self.win.current.channels) if self.win.current is not None else ['GFP']
        fields = ['Area', 'Perimeter', 'Circularity', 'Solidity', 'Feret', 'AR'] + \
            [f'Mean:{c}' for c in chs] + [f'IntDen:{c}' for c in chs] + \
            [f'overlap:{o}' for o in objs] + [f'inside:{o}' for o in objs] + \
            ['edge', 'frames', 'divided', 'change:thr', 'class']
        f = _combo(fields, c[0])
        f.setEditable(True)
        if f.currentText() != c[0]:
            f.setEditText(str(c[0]))
        op = _combo([('>=', '≥'), ('<=', '≤'), ('>', '>'), ('<', '<'), ('=', '='), ('between', '범위'),
                     ('yes', '예'), ('no', '아니오')], c[1])
        val = QLineEdit('' if len(c) < 3 or c[2] is None else
                        (f'{c[2][0]} – {c[2][1]}' if isinstance(c[2], list) else str(c[2])))
        val.setPlaceholderText('값 (배경 배수: bg*1.5)')
        unit = QLabel('')
        theme.secondary(unit)

        def upd():
            fld = f.currentText()
            c[0] = fld
            c[1] = op.currentData()
            t = val.text().strip()
            if c[1] in ('yes', 'no'):
                c[2:] = []
            elif c[1] == 'between':
                parts = [x for x in t.replace('–', ' ').replace('-', ' ').split() if x]
                try:
                    c[2:] = [[float(parts[0]), float(parts[1])]]
                except (IndexError, ValueError):
                    c[2:] = [[0, 0]]
            else:
                try:
                    c[2:] = [float(t)]
                except ValueError:
                    c[2:] = [t]
            val.setVisible(c[1] not in ('yes', 'no'))
            unit.setText('µm²' if fld == 'Area' else 'µm' if fld in ('Perimeter', 'Feret') else
                         '%' if fld.startswith('overlap') else '프레임' if fld == 'frames' else
                         '×' if fld.startswith('change') else '')
            self._preview_later()
        f.currentTextChanged.connect(lambda _t: upd())
        op.currentIndexChanged.connect(lambda _x: upd())
        val.editingFinished.connect(upd)
        rm = QToolButton()
        rm.setText('−')
        rm.setToolTip('조건 빼기')
        rm.clicked.connect(lambda: (where['conds'].pop(ci), refill(), self._preview_later()))
        for x in (f, op, val, unit, rm):
            h.addWidget(x)
        h.setStretch(0, 2)
        h.setStretch(2, 1)
        val.setVisible(c[1] not in ('yes', 'no'))
        return w

    def _preview_later(self):
        if not hasattr(self, '_pv_timer'):
            self._pv_timer = QTimer(self)
            self._pv_timer.setSingleShot(True)
            self._pv_timer.setInterval(250)
            self._pv_timer.timeout.connect(self.update_preview)
        self._pv_timer.start()

    def preview_objects(self, i, it=None):
        """Objects of the current image after the 연산 stages up to stage i."""
        it = it or self.win.current
        if it is None:
            return None, None
        objs = P.base_objects(it)
        made = None
        for k, st in enumerate(self.spec.stages[:i + 1]):
            if st['kind'] == 'op' and st.get('enabled', True):
                new = P.apply_op(it, st['settings'], objs)
                objs.update(new)
                if k == i:
                    made = new
        return objs, made

    def update_preview(self):
        lab = getattr(self, 'preview', None)
        if lab is None:
            return
        try:
            lab.isVisible()
        except RuntimeError:
            return
        while self.preview_chips.count():
            w = self.preview_chips.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        it = self.win.current
        try:
            objs, made = self.preview_objects(self._preview_i, it)
        except Exception as exc:  # noqa: BLE001
            lab.setText(f'미리 보기를 만들 수 없습니다: {exc}')
            return
        if it is None or not made:
            lab.setText('이미지를 열고 검출 단계를 한 번 돌리면 미리 볼 수 있습니다.')
            return
        name = self.spec.stages[self._preview_i]['settings'].get('out')
        obj = made.get(name) or next(iter(made.values()))
        if obj.labels is None:
            lab.setText(f'{obj.name}: 트랙 {len(obj.ids())}개')
        else:
            lab.setPixmap(overlay_pixmap(it, obj.labels, 520))
        self.preview_chips.addWidget(_status_chip(f'{obj.name} {len(obj.ids())}개', 'info'))
        for n, o in made.items():
            if o is not obj:
                self.preview_chips.addWidget(_status_chip(f'{n} {len(o.ids())}개', 'neutral'))
        self.preview_chips.addWidget(_status_chip('세포 번호 물려받음', 'neutral'))
        self.preview_chips.addStretch()

    def _ed_measure_intensity(self, lay, st, i):
        s = st['settings']
        objs = self._objects(i)
        chs = list(self.win.current.channels) if self.win.current is not None else []
        b1, f1 = _card('대상 (object × 채널)')
        rows = QWidget()
        rl = QVBoxLayout(rows)
        rl.setContentsMargins(0, 0, 0, 0)
        f1.addRow(rows)

        def fill():
            while rl.count():
                w = rl.takeAt(0).widget()
                if w is not None:
                    w.deleteLater()
            for ti, t in enumerate(s.setdefault('targets', [])):
                w = QWidget()
                h = QHBoxLayout(w)
                h.setContentsMargins(0, 0, 0, 0)
                o = _combo(objs, t.get('object'))
                o.setEditable(True)
                if o.currentText() != t.get('object'):
                    o.setEditText(t.get('object', ''))
                o.currentTextChanged.connect(lambda x, t=t: t.__setitem__('object', x))
                h.addWidget(o)
                boxes = []
                for ch in chs:
                    b = _chip_box(ch, not t.get('channels') or ch in t['channels'])
                    boxes.append(b)

                def ch_changed(_v=None, t=t, boxes=boxes):
                    on = [b.text() for b in boxes if b.isChecked()]
                    t['channels'] = [] if len(on) == len(boxes) else on
                for b in boxes:
                    b.toggled.connect(ch_changed)
                h.addWidget(_flow(boxes) if boxes else _hint('모든 채널'), 1)
                rm = QToolButton()
                rm.setText('−')
                rm.setToolTip('대상 빼기')
                rm.clicked.connect(lambda _c=False, ti=ti: (s['targets'].pop(ti), fill(), self._refresh_row()))
                h.addWidget(rm)
                rl.addWidget(w)
        fill()
        add = QPushButton('＋ 대상 추가')
        add.clicked.connect(lambda: (s['targets'].append({'object': objs[-1], 'channels': []}), fill(),
                                     self._refresh_row()))
        f1.addRow(add)
        lay.addWidget(b1)
        b2, f2 = _card('측정 항목')
        boxes = []
        for name in P.STATS:
            b = _chip_box(name, name in (s.get('stats') or []))
            b.toggled.connect(lambda _v: s.__setitem__('stats', [x.text() for x in boxes if x.isChecked()]))
            boxes.append(b)
        f2.addRow(_flow(boxes))
        bg = _combo([('none', '안 함'), ('outside', '세포 밖 중앙값')] + [(f'ring:{o}', f'고리 object의 중앙값: {o}')
                                                                      for o in objs], s.get('bg', 'none'))
        bg.currentIndexChanged.connect(lambda _x: s.__setitem__('bg', bg.currentData()))
        f2.addRow('배경 빼기', bg)
        name = QLineEdit(s.get('name', ''))
        name.setPlaceholderText('비우면 「측정 · <object>」')
        name.editingFinished.connect(lambda: s.__setitem__('name', name.text().strip()))
        f2.addRow('표 이름', name)
        f2.addRow(_hint('행 하나 = object 하나 (트랙은 시점 하나). 결과 표는 그래프 단계와 1_통합데이터에 들어갑니다.'))
        lay.addWidget(b2)

    def _ed_measure_count(self, lay, st, i):
        s = st['settings']
        objs = self._objects(i)
        b, f = _card('개수 · 밀도')
        for key, title in (('object', '셀 object'), ('parent', '부모 (세포마다)')):
            c = _combo(objs, s.get(key))
            c.setEditable(True)
            c.currentTextChanged.connect(lambda t, key=key: s.__setitem__(key, t))
            f.addRow(title, c)
        lay.addWidget(b)

    def _ed_human_review(self, lay, st, i):
        s = st['settings']
        b, f = _card('이 단계 뒤 검토')
        im = s.get('images') or []
        how = _combo([('pick', '직접 고르기'), ('chips', '특이 사항 칩이 붙은 이미지'), ('*', '모든 이미지'),
                      ('none', '멈추지 않음 (칩만 표시)')],
                     'chips' if im == ['chips'] else '*' if im == ['*'] else 'pick' if im else 'none')
        f.addRow('검토할 이미지', how)
        picked = _status_chip('', 'info')
        pick_btn = QPushButton('고르기…')
        row = QWidget()
        rh = QHBoxLayout(row)
        rh.setContentsMargins(0, 0, 0, 0)
        rh.addStretch()
        rh.addWidget(picked)
        rh.addWidget(pick_btn)
        f.addRow(row)
        f.addRow(_hint('열려 있는 이미지 중에서 직접 고릅니다. 실행하는 동안 검토 화면에서도 더하거나 뺄 수 있습니다. '
                       '고른 이미지가 없으면 멈추지 않습니다.'))

        def upd():
            k = how.currentData()
            if k == 'pick':
                s['images'] = [x for x in (s.get('images') or []) if x not in ('*', 'chips')]
            elif k == 'none':
                s['images'] = []
            else:
                s['images'] = [k]
            picked.setText(f'{len(s["images"])}개 골랐음')
            row.setVisible(k == 'pick')
            self._refresh_row_soft()
        how.currentIndexChanged.connect(lambda _x: upd())

        def pick():
            dlg = ReviewPicker(self.win, s, self.runner)
            if dlg.exec():
                s['images'] = dlg.picked()
                upd()
        pick_btn.clicked.connect(pick)
        upd()
        lay.addWidget(b)
        b2, f2 = _card('특이 사항 칩으로 표시')
        chips = s.setdefault('chips', {})
        boxes = []
        for key, text in P.CHIP_TEXT.items():
            bx = _chip_box(text, chips.get(key))
            bx.toggled.connect(lambda v, key=key: chips.__setitem__(key, v))
            boxes.append(bx)
        f2.addRow(_flow(boxes))
        lo, hi = (s.get('cells') or [3, 40])[:2]
        a, z = QSpinBox(), QSpinBox()
        for w, v in ((a, lo), (z, hi)):
            w.setRange(0, 9999)
            w.setSuffix(' 개')
            w.setValue(int(v))
        a.valueChanged.connect(lambda v: s.__setitem__('cells', [v, z.value()]))
        z.valueChanged.connect(lambda v: s.__setitem__('cells', [a.value(), v]))
        rr = QWidget()
        rrl = QHBoxLayout(rr)
        rrl.setContentsMargins(0, 0, 0, 0)
        rrl.addWidget(a)
        rrl.addWidget(QLabel('–'))
        rrl.addWidget(z)
        f2.addRow('세포 수 범위', rr)
        ns = _combo([('normal', '보통: 구멍 있음 또는 볼록도 < 0.85'), ('strict', '엄격: 볼록도 < 0.90'),
                     ('loose', '느슨: 볼록도 < 0.80')], s.get('nuc_shape', 'normal'))
        ns.currentIndexChanged.connect(lambda _x: s.__setitem__('nuc_shape', ns.currentData()))
        f2.addRow('핵 모양 이상 기준', ns)
        f2.addRow(_hint('핵 안에 구멍이 있거나, 크게 오목하게 들어간 곳(볼록 껍질에서 핵 지름의 15 % 넘게 파인 곳)이 '
                        '있는 핵. 세포 수와 함께 「핵 모양 이상 2」처럼 붙습니다. 칩은 고를 때 참고용이며 자동으로 '
                        '대상에 넣지 않습니다.'))
        lay.addWidget(b2)

    def _refresh_row_soft(self):
        it = self.list.currentItem()
        if it is not None and it.data(STAGE) is not None:
            st = self.spec.stages[it.data(STAGE)]
            first = it.text().split('\n')[0]
            it.setText(f'{first}\n     {P.stage_summary(st)}')

    def _ed_end_graph(self, lay, st, i):
        s = st['settings']
        b, f = _card('그래프')
        lst = QListWidget()
        for gd in s.get('graphs') or []:
            lst.addItem(gd.get('title') or '(제목 없음)')
        lst.setMaximumHeight(140)
        f.addRow(lst)
        row = QHBoxLayout()
        add = QPushButton('＋ 그래프 편집 창의 지금 그래프 넣기')

        def take():
            gw = getattr(self.win, 'graph_win', None)
            spec = getattr(gw, 'spec', None) if gw is not None else None
            if spec is None:
                QMessageBox.information(self, '그래프', '그래프 편집 창에서 그래프를 먼저 만드세요 (그래프 › 새 그래프).')
                return
            d = spec.to_dict()
            d.setdefault('title', getattr(spec, 'title', '') or f'그래프 {len(s.get("graphs") or []) + 1}')
            s.setdefault('graphs', []).append(d)
            lst.addItem(d.get('title') or '그래프')
            self._refresh_row_soft()
        add.clicked.connect(take)
        rm = QPushButton('빼기')
        rm.clicked.connect(lambda: lst.currentRow() >= 0 and (s['graphs'].pop(lst.currentRow()),
                                                              lst.takeItem(lst.currentRow())))
        row.addWidget(add)
        row.addStretch()
        row.addWidget(rm)
        h = QWidget()
        h.setLayout(row)
        f.addRow(h)
        f.addRow(_hint('그래프는 열 이름으로 저장되어 새 데이터에도 같은 모양으로 그려집니다. 가리키는 표가 없으면 '
                       '그 그래프만 건너뛰고 README.txt에 이유를 적습니다.'))
        lay.addWidget(b)
        b2, f2 = _card('저장 형식')
        boxes = []
        for fmt in ('png', 'pdf', 'svg'):
            bx = _chip_box(fmt.upper(), fmt in (s.get('formats') or ['png']))
            boxes.append(bx)
            bx.toggled.connect(lambda _v: s.__setitem__('formats', [x.text().lower() for x in boxes if x.isChecked()]))
        f2.addRow(_flow(boxes))
        csv_on = QCheckBox('그래프에 쓴 표 CSV')
        csv_on.setChecked(s.get('csv', True))
        csv_on.toggled.connect(lambda v: s.__setitem__('csv', v))
        f2.addRow(csv_on)
        lay.addWidget(b2)

    def _ed_end_export(self, lay, st, i):
        from .export_dialog import KINDS
        s = st['settings']
        b, f = _card('결과 폴더')
        dest = _combo([('processed', '데이터 폴더의 상위 › Processed/'), ('custom', '직접 지정')],
                      'processed' if s.get('dest', 'processed') == 'processed' else 'custom')
        f.addRow('저장 위치', dest)
        folder = QLineEdit('' if s.get('dest') == 'processed' else s.get('dest', ''))
        f.addRow('폴더', folder)
        name = QLineEdit(s.get('name') or '<데이터 폴더>_<파이프라인>_<날짜>_<시각>')
        name.editingFinished.connect(lambda: s.__setitem__('name', name.text().strip()))
        f.addRow('폴더 이름 틀', name)

        def upd():
            custom = dest.currentData() == 'custom'
            theme.show_rows(f, [folder], custom)
            s['dest'] = folder.text().strip() if custom and folder.text().strip() else 'processed'
            self._update_line()
        dest.currentIndexChanged.connect(lambda _x: upd())
        folder.editingFinished.connect(upd)
        upd()
        f.addRow(_hint('pipeline.json · project.cyproj · README.txt · review_log.csv · work_log.csv, '
                       '1_통합데이터/, 2_그래프/, 3_이미지/를 씁니다. 같은 이름이 있으면 번호를 붙입니다.'))
        lay.addWidget(b)
        b2, f2 = _card('내보내기 종류 (이미지별)')
        opts = s.setdefault('opts', {})
        boxes = {}
        for key, (title, _cards) in KINDS.items():
            if key in EXPORT_SKIP:
                continue
            on = any(opts.get(o) for o in kind_options(key))
            boxes[key] = _chip_box(title, on)

        def kinds_changed(_v=None):
            new = {}
            for key, bx in boxes.items():
                if bx.isChecked():
                    new.update(kind_options(key))
            opts.clear()
            opts.update(new)
        for bx in boxes.values():
            bx.toggled.connect(kinds_changed)
        f2.addRow(_flow(list(boxes.values())))
        integ = QCheckBox('통합 데이터 CSV (1_통합데이터)')
        integ.setChecked(s.get('integrated', True))
        integ.toggled.connect(lambda v: s.__setitem__('integrated', v))
        f2.addRow(integ)
        proj = QCheckBox('프로젝트 파일 (project.cyproj)')
        proj.setChecked(s.get('project', True))
        proj.toggled.connect(lambda v: s.__setitem__('project', v))
        f2.addRow(proj)
        lay.addWidget(b2)

    # ---- run ----
    def _items(self):
        f = self.folder.text().strip()
        if f:
            files = P.find_images(f)
            have = {str(Path(getattr(it, 'path', ''))) for it in self.win.items}
            new = [x for x in files if str(x) not in have]
            if new:
                self.win.import_paths(new)
            keep = {str(x) for x in files}
            return [it for it in self.win.items if str(Path(getattr(it, 'path', ''))) in keep]
        return list(self.win.items)

    def run(self):
        errs = P.validate(self.spec, sorted({c for it in self.win.items for c in it.channels}) or None)
        if errs and QMessageBox.question(self, '파이프라인', '문제가 있습니다:\n' + '\n'.join(errs[:8]) +
                                         '\n\n그대로 실행할까요?') != QMessageBox.StandardButton.Yes:
            return None
        spec = self.spec.copy()
        for st in spec.stages:
            if st['kind'] == 'start.load':
                st['enabled'] = False      # the window opens the images itself
        items = self._items()
        if not items:
            QMessageBox.information(self, '파이프라인', '실행할 이미지가 없습니다. 데이터 폴더를 고르거나 이미지를 여세요.')
            return None
        return self.start(spec, items)

    def start(self, spec, items, out=None):
        self.runner = P.Runner(self.win, spec, items, out=out, interactive=True, progress=self._progress)
        self.win.pipeline_runner = self.runner
        self.prog_row.setVisible(True)
        self.prog.setRange(0, len(spec.stages))
        self.run_btn.setEnabled(False)
        return self._go(self.runner.run)

    def _progress(self, d):
        ev = d.get('event')
        if ev == 'stage':
            self.prog.setValue(d['index'] - 1)
            self.prog_text.setText(f'{d["index"]} / {len(self.runner.spec.stages)} · {d["title"]}')
        elif ev == 'error':
            self.prog_text.setText(f'경고: {d["message"]}')
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()

    def _go(self, fn):
        try:
            res = fn()
        finally:
            self.run_btn.setEnabled(True)
        self.win.file_list.chips = {}
        self.win.update_pipeline_chips()
        if res == 'review':
            self.hide()
            self.win.pipeline_band().review_mode(self, self.runner)
        else:
            self.finish()
        return res

    def resume(self):
        self.show()
        return self._go(self.runner.resume)

    def finish(self):
        r = self.runner
        self.prog.setValue(self.prog.maximum())
        self.prog_text.setText('끝')
        self.win.statusBar().showMessage(f'파이프라인 「{r.spec.name}」 끝: {r.state.out} (경고 {len(r.state.errors)}개)')
        self.win.pipeline_band().hide()
        self.show_done()
        self.show()
        self.raise_()

    def show_done(self):
        r = self.runner
        page = QWidget()
        lay = QVBoxLayout(page)
        head = QLabel(f'완료 · {r.spec.name}')
        theme.text_style(head, 'title-2')
        lay.addWidget(head)
        chips = [_status_chip(f'이미지 {len(r.active_items())}개', 'success'),
                 _status_chip(f'표 {len(r.state.tables)}개', 'info'),
                 _status_chip(f'경고 {len(r.state.errors)}개', 'warning' if r.state.errors else 'neutral')]
        lay.addWidget(_flow(chips))
        lay.addWidget(_hint(f'결과 폴더: {r.state.out}'))
        if r.state.errors:
            box, form = _card('경고')
            for e in r.state.errors[:30]:
                form.addRow(_hint(e))
            lay.addWidget(box)
        if r.state.tables:
            box, form = _card('표')
            for n, rows in r.state.tables.items():
                form.addRow(n, QLabel(f'{len(rows)}행'))
            lay.addWidget(box)
        row = QHBoxLayout()
        open_b = theme.prominent(QPushButton('결과 폴더 열기'))
        open_b.clicked.connect(lambda: open_folder(r.state.out))
        row.addWidget(open_b)
        g = QPushButton('그래프 편집 창에서 보기')
        g.clicked.connect(lambda: self.win.open_graph(None) if hasattr(self.win, 'open_graph') else None)
        row.addWidget(g)
        st = QPushButton('측정 현황 보기')
        st.clicked.connect(self.win.show_batch_results)
        row.addWidget(st)
        again = QPushButton('다른 폴더에 같은 파이프라인 실행…')
        again.clicked.connect(self._again)
        row.addWidget(again)
        back = QPushButton('단계로 돌아가기')
        back.clicked.connect(lambda: self.pages.setCurrentWidget(self.editor))
        row.addStretch()
        row.addWidget(back)
        lay.addLayout(row)
        lay.addStretch()
        theme.unify(page)
        self.pages.removeWidget(self.done_page)
        self.done_page.deleteLater()
        self.done_page = page
        self.pages.addWidget(page)
        self.pages.setCurrentWidget(page)

    def _again(self):
        self._pick_folder()
        if self.folder.text():
            self.pages.setCurrentWidget(self.editor)
            self.run()


def kind_options(kind) -> dict:
    """The export window's default on / off options of one kind."""
    from .export_dialog import KINDS
    opts = {}
    for sec in KINDS[kind][1]:
        rows = sec[1] if isinstance(sec, tuple) and len(sec) > 1 and isinstance(sec[1], list) else [sec]
        for o in rows:
            if isinstance(o, tuple) and isinstance(o[0], str):
                opts[o[0]] = bool(o[-1])
    return {k: v for k, v in opts.items() if v} or dict.fromkeys(list(opts)[:1], True)


def STAGES_PANEL(kind) -> bool:  # noqa: N802
    return bool(P.STAGES[kind]['panel'])


def open_folder(path):
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def overlay_pixmap(it, labels, size=520) -> QPixmap:
    """The image's first channels as grey + the object's regions tinted."""
    planes = np.asarray(it.planes(), float)
    g = planes[min(1, len(planes) - 1)]
    lo, hi = np.percentile(g, (1, 99.5))
    g = np.clip((g - lo) / max(hi - lo, 1e-9), 0, 1)
    rgb = np.stack([g * 0.6] * 3, -1)
    m = labels > 0
    rng = np.random.default_rng(3)
    cols = rng.uniform(0.35, 1.0, (int(labels.max()) + 1, 3))
    cols[:, 2] *= 0.4
    rgb[m] = rgb[m] * 0.35 + cols[labels[m]] * 0.65
    edge = m & ~(np.roll(labels, 1, 0) == labels) | m & ~(np.roll(labels, 1, 1) == labels)
    rgb[edge] = 1.0
    a = np.ascontiguousarray((rgb * 255).astype(np.uint8))
    h, w = a.shape[:2]
    img = QImage(a.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(img).scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation)


class ReviewPicker(QDialog):
    """고르기 창: the open images by group with check boxes and chips."""

    def __init__(self, win, settings, runner=None):
        super().__init__(win)
        self.win = win
        self.setWindowTitle('검토할 이미지 고르기')
        self.resize(520, 560)
        lay = QVBoxLayout(self)
        quick = QHBoxLayout()
        for text, fn in (('모두', lambda: self._set(lambda it: True)), ('없음', lambda: self._set(lambda it: False)),
                         ('특이 사항 있는 것', lambda: self._set(lambda it: bool(self.chips.get(it.image_id)))),
                         ('그룹마다 한 장', self._one_per_group)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            quick.addWidget(b)
        quick.addStretch()
        lay.addLayout(quick)
        self.list = QListWidget()
        lay.addWidget(self.list, 1)
        self.chips = dict(runner.state.chips) if runner is not None else {}
        for it in win.items:
            if it.image_id not in self.chips and it.cells is not None:
                self.chips[it.image_id] = P.review_chips(it, settings)
        sel = set(settings.get('images') or [])
        for it in sorted(win.items, key=lambda x: (x.group or '~', x.label)):
            c = self.chips.get(it.image_id) or {}
            tail = '   ' + ' · '.join(f'{P.CHIP_TEXT[k]} {v}' for k, v in c.items()) if c else ''
            row = QListWidgetItem(f'{(it.group + " › ") if it.group else ""}{it.label}{tail}')
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(Qt.CheckState.Checked if it.image_id in sel else Qt.CheckState.Unchecked)
            row.setData(STAGE, it.image_id)
            row.setData(HEAD, it.group or '')
            self.list.addItem(row)
        bar = QHBoxLayout()
        bar.addStretch()
        no = QPushButton('취소')
        no.clicked.connect(self.reject)
        ok = theme.prominent(QPushButton('고르기'))
        ok.clicked.connect(self.accept)
        bar.addWidget(no)
        bar.addWidget(ok)
        lay.addLayout(bar)

    def _rows(self):
        return [self.list.item(i) for i in range(self.list.count())]

    def _set(self, pred):
        by = {it.image_id: it for it in self.win.items}
        for r in self._rows():
            it = by.get(r.data(STAGE))
            r.setCheckState(Qt.CheckState.Checked if it is not None and pred(it) else Qt.CheckState.Unchecked)

    def _one_per_group(self):
        seen = set()
        for r in self._rows():
            g = r.data(HEAD)
            r.setCheckState(Qt.CheckState.Checked if g not in seen else Qt.CheckState.Unchecked)
            seen.add(g)

    def picked(self):
        return [r.data(STAGE) for r in self._rows() if r.checkState() == Qt.CheckState.Checked]


class ReviewBand(QWidget):
    """The band above the canvas while a pipeline waits for review (or while
    a stage's settings are edited in their tab)."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setObjectName('hig_pipeline_band')
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(6)
        top = QHBoxLayout()
        self.title = QLabel('')
        theme.text_style(self.title, 'headline')
        top.addWidget(self.title)
        self.chip_row = QHBoxLayout()
        top.addLayout(self.chip_row)
        top.addStretch()
        self.pick_btn = QPushButton('대상 고르기…')
        self.prev_btn = QPushButton('이전')
        self.next_btn = QPushButton('다음')
        self.prev_btn.setToolTip('이전 검토 대상 (⌘[)')
        self.next_btn.setToolTip('다음 검토 대상 (⌘])')
        for b in (self.pick_btn, self.prev_btn, self.next_btn):
            top.addWidget(b)
        v.addLayout(top)
        bottom = QHBoxLayout()
        self.help = _hint('')
        bottom.addWidget(self.help, 1)
        self.ok_btn = QPushButton('이 이미지 확인')
        self.ok_btn.setToolTip('⌘↩')
        self.go_btn = theme.prominent(QPushButton('검토 끝내고 계속'))
        self.cancel_btn = QPushButton('취소')
        bottom.addWidget(self.ok_btn)
        bottom.addWidget(self.cancel_btn)
        bottom.addWidget(self.go_btn)
        v.addLayout(bottom)
        self.pick_btn.clicked.connect(self._pick)
        self.prev_btn.clicked.connect(lambda: self.step(-1))
        self.next_btn.clicked.connect(lambda: self.step(1))
        self.ok_btn.clicked.connect(self.confirm)
        self.go_btn.clicked.connect(self._go)
        self.cancel_btn.clicked.connect(self._cancel)
        for key, fn in (('Ctrl+[', lambda: self.step(-1)), ('Ctrl+]', lambda: self.step(1)),
                        ('Ctrl+Return', self.confirm)):
            sc = QShortcut(QKeySequence(key), win)
            sc.activated.connect(lambda fn=fn: self.isVisible() and self.mode == 'review' and fn())
        self.mode = ''
        self.window = None
        self.runner = None
        self._apply = self._cancel_fn = None
        self.setVisible(False)

    # ---- edit a stage's settings in its tab ----
    def edit_mode(self, title, apply, cancel):
        self.mode = 'edit'
        self._apply, self._cancel_fn = apply, cancel
        self.title.setText(title)
        self._clear_chips()
        self.help.setText('탭의 모든 기능(미리보기, 실시간 검출 …)으로 맞춘 뒤 「단계에 반영」을 누르세요. '
                          '탭은 원래 설정으로 돌아갑니다.')
        for b in (self.pick_btn, self.prev_btn, self.next_btn, self.ok_btn):
            b.setVisible(False)
        self.cancel_btn.setVisible(True)
        self.go_btn.setText('단계에 반영')
        self.setVisible(True)

    # ---- review ----
    def review_mode(self, window, runner):
        self.mode = 'review'
        self.window, self.runner = window, runner
        st = runner.spec.stages[runner.state.review_stage]
        prev = next((s for s in reversed(runner.spec.stages[:runner.state.review_stage])
                     if s.get('enabled', True)), None)
        self.title.setText(f'검토: {P.stage_title(prev) if prev else P.stage_title(st)}')
        self.help.setText('세포질 ROI 탭의 도구(합치기 M, 자르기 C, 지우기, 그리기)로 고칩니다. 고친 내용은 '
                          'review_log.csv에 남습니다. 뺄 이미지는 목록 오른쪽 클릭 › 이번 분석에서 제외.')
        for b in (self.pick_btn, self.prev_btn, self.next_btn, self.ok_btn):
            b.setVisible(True)
        self.cancel_btn.setVisible(False)
        self.go_btn.setText('검토 끝내고 계속')
        self.setVisible(True)
        self.win.measure_bar.setVisible(False)
        self.k = 0
        self.win.show_tab('roi_tab')
        self.goto(0)

    def _clear_chips(self):
        while self.chip_row.count():
            w = self.chip_row.takeAt(0).widget()
            if w is not None:
                w.deleteLater()

    def targets(self):
        ids = self.runner.state.review_images
        return [it for i in ids for it in self.win.items if it.image_id == i]

    def goto(self, k):
        t = self.targets()
        if not t:
            self.refresh()
            return
        self.k = max(0, min(k, len(t) - 1))
        it = t[self.k]
        if it in self.win.items:
            self.win.file_list.setCurrentRow(self.win.items.index(it))
        self.refresh()

    def step(self, d):
        self.goto(self.k + d)

    def refresh(self):
        self._clear_chips()
        r = self.runner
        n = len(r.spec.stages)
        t = self.targets()
        self.chip_row.addWidget(_status_chip(f'파이프라인 {r.state.review_stage + 1} / {n}', 'neutral'))
        self.chip_row.addWidget(_status_chip(f'검토 대상 {min(self.k + 1, len(t))} / {len(t)}', 'info'))
        cur = self.win.current
        if cur is not None:
            for key, v in (r.state.chips.get(cur.image_id) or {}).items():
                self.chip_row.addWidget(_status_chip(f'{P.CHIP_TEXT[key]} {v}', P.CHIP_KIND[key]))
        self.win.update_pipeline_chips()

    def confirm(self):
        cur = self.win.current
        if cur is None or self.runner is None:
            return
        if cur.image_id not in self.runner.state.confirmed:
            self.runner.state.confirmed.append(cur.image_id)
            self.runner.note_review(cur, '확인')
        if cur.cells is not None:
            st = self.runner.spec.stages[self.runner.state.review_stage]['settings']
            self.runner.state.chips[cur.image_id] = P.review_chips(cur, st)
        self.step(1)
        self.refresh()

    def _pick(self):
        st = self.runner.spec.stages[self.runner.state.review_stage]['settings']
        dlg = ReviewPicker(self.win, dict(st, images=self.runner.state.review_images), self.runner)
        if dlg.exec():
            self.runner.state.review_images = dlg.picked()
            self.goto(0)

    def _go(self):
        if self.mode == 'edit':
            self.setVisible(False)
            fn, self._apply = self._apply, None
            if fn:
                fn()
            return
        r = self.runner
        left = [i for i in r.state.review_images if i not in r.state.confirmed]
        if left and not theme.ask(self.win, '검토', f'{len(left)}개를 확인하지 않았습니다.', '그대로 계속', '돌아가기'):
            return
        self.setVisible(False)
        self.win.measure_bar.setVisible(True)
        self.window.resume()

    def _cancel(self):
        self.setVisible(False)
        fn, self._cancel_fn = self._cancel_fn, None
        if fn:
            fn()


class LibraryDialog(QDialog):
    """보관함: pipelines as cards (group chips), 열기 · 복제 · 파일에서 · 새로."""

    def __init__(self, win, pwin=None):
        super().__init__(win)
        self.win, self.pwin = win, pwin
        self.setWindowTitle('파이프라인 보관함')
        self.resize(760, 620)
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        new = QPushButton('새 파이프라인')
        new.clicked.connect(lambda: self._open(P.PipelineSpec(stages=[P.default_stage('end.export')])))
        load = QPushButton('파일에서 불러오기…')
        load.clicked.connect(self._load)
        bar.addWidget(new)
        bar.addWidget(load)
        bar.addStretch()
        hint = QLabel(str(P.library_dir()))
        theme.secondary(hint)
        bar.addWidget(hint)
        lay.addLayout(bar)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        page = QWidget()
        v = QVBoxLayout(page)
        for name, path, spec in P.library():
            box = QGroupBox(name + ('' if path else '  · 기본'))
            bl = QVBoxLayout(box)
            if spec.note:
                bl.addWidget(_hint(spec.note))
            chips = []
            for g, titles in P.chip_summary(spec).items():
                chips.append(_status_chip(f'{g}: {" · ".join(titles)}', 'neutral'))
            bl.addWidget(_flow(chips))
            row = QHBoxLayout()
            row.addStretch()
            dup = QPushButton('복제')
            dup.clicked.connect(lambda _c=False, s=spec: self._dup(s))
            op = QPushButton('열기')
            op.clicked.connect(lambda _c=False, s=spec, p=path: self._open(s.copy(), p))
            row.addWidget(dup)
            row.addWidget(op)
            bl.addLayout(row)
            v.addWidget(box)
        v.addStretch()
        theme.unify(page)
        area.setWidget(page)
        lay.addWidget(area, 1)

    def _target(self):
        if self.pwin is None:
            self.pwin = self.win.pipeline_window()
        return self.pwin

    def _open(self, spec, path=None):
        w = self._target()
        w.set_spec(spec, path)
        w.show()
        w.raise_()
        self.accept()

    def _dup(self, spec):
        s = spec.copy()
        s.name = f'{s.name} 복사본'
        self._open(s)

    def _load(self):
        fn, _ = QFileDialog.getOpenFileName(self, '파이프라인 불러오기', str(P.library_dir()),
                                            f'파이프라인 · 일괄 분석 설정 (*{P.EXT} *.json);;All files (*)')
        if fn:
            self._target().load_file(fn)
            self._target().show()
            self.accept()
