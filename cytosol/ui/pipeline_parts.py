"""Pipeline window parts: the stage list (Table variant reorder), ActionBar variant ``review`` (ReviewBand) and its picker window."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QAbstractItemView, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget
from .. import pipeline as P
from .. import theme


STAGE = Qt.ItemDataRole.UserRole          # stage index on stage rows


HEAD = Qt.ItemDataRole.UserRole + 1       # group key on heading rows


def _hint(text):
    lab = QLabel(text)
    lab.setWordWrap(True)
    return theme.hint(lab)


def _status_chip(text, kind='neutral'):
    return theme.StatusLabel(text, kind)


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
