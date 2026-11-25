"""Stage editors of the pipeline window for the named-ROI stages (design v4,
owner approval 2026-11-25). Every editor flows top to bottom in the user's
order (§0.1): the input card first (what to work on), then what to do, the
details, and the result-name card last. ROI and channel inputs are separate
cards (§6). Mixed into `pipeline_window.PipelineWindow`."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import pipeline as P
from . import pipeline_roi as R
from . import theme
from .ui.pipeline_parts import _hint, _status_chip


def card(n, title):
    box = QGroupBox(f'{n}  {title}' if n else title)
    form = QFormLayout(box)
    return box, form


def combo(items, current=None):
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


def radios(parent, options, current, on_pick, per_row=2):
    """Radio buttons for one of several (design system: QRadioButton), in a grid."""
    w = QWidget()
    g = QGridLayout(w)
    g.setContentsMargins(0, 0, 0, 0)
    g.setHorizontalSpacing(16)
    grp = QButtonGroup(parent)
    out = {}
    for k, (key, text) in enumerate(options):
        r = QRadioButton(text)
        r.setChecked(key == current)
        grp.addButton(r)
        r.toggled.connect(lambda on, key=key: on and on_pick(key))
        g.addWidget(r, k // per_row, k % per_row)
        out[key] = r
    return w, out


def chips_grid(items, on, changed, per_row=3, tips=None, enabled=None):
    """Multi-select chips in a grid (inside a settings card a flow collapses)."""
    w = QWidget()
    g = QGridLayout(w)
    g.setContentsMargins(0, 0, 0, 0)
    g.setHorizontalSpacing(8)
    g.setVerticalSpacing(6)
    boxes = {}
    for k, (key, text) in enumerate(items):
        b = theme.chip(QCheckBox(text))
        b.setChecked(key in on)
        if tips and tips.get(key):
            b.setToolTip(tips[key])
        if enabled is not None and not enabled.get(key, True):
            b.setEnabled(False)
        b.toggled.connect(lambda _v: changed([k2 for k2, bx in boxes.items() if bx.isChecked()]))
        g.addWidget(b, k // per_row, k % per_row, Qt.AlignmentFlag.AlignLeft)
        boxes[key] = b
    g.setColumnStretch(per_row, 1)
    return w, boxes


def um_box(value, lo=0.0, hi=200.0, suffix=' µm'):
    b = QDoubleSpinBox()
    b.setRange(lo, hi)
    b.setDecimals(2)
    b.setSuffix(suffix)
    b.setValue(float(value))
    return b


class RoiEditors:
    """Editors of detect.roi, roi.op, roi.filter, roi.track, measure.roi, calc.values."""

    # ---- shared ----
    def _channels(self, s=None):
        it = self.win.current
        if it is not None:
            return list(it.channels)
        have = sorted({c for it in self.win.items for c in it.channels})
        return have or list((s or {}).get('channels') or [])

    def _rois(self, i):
        """name -> kind of the ROIs before stage i."""
        return P.roi_kinds_before(self.spec, i)

    def _roi_combo(self, i, current, kinds=None, empty=None):
        """ROI names before stage i (kind after the name); names of the wrong kind greyed."""
        rois = self._rois(i)
        c = QComboBox()
        if empty:
            c.addItem(empty, '')
        for n, k in rois.items():
            c.addItem(f'{n}   · {R.KIND_TEXT.get(k, k)}', n)
            if kinds is not None and k not in kinds:
                item = c.model().item(c.count() - 1)
                item.setEnabled(False)
                item.setToolTip('이 단계에 쓸 수 없는 종류입니다.')
        if current and c.findData(current) < 0:
            c.addItem(f'{current}   · 앞 단계에 없음', current)
        c.setCurrentIndex(max(0, c.findData(current)) if current is not None else 0)
        return c

    def _result_card(self, lay, n, rows, note=''):
        """The last card: result names (owner 2026-11-25: 결과 이름 상자는 맨 아래).
        rows: [(label, value, on_change, kind text or None, placeholder)]."""
        box, form = card(n, '결과 이름')
        for label, value, fn, kind, ph in rows:
            e = QLineEdit(value or '')
            if ph:
                e.setPlaceholderText(ph)
            e.editingFinished.connect(lambda e=e, fn=fn: (fn(e.text().strip()), self._refresh_row()))
            if kind:
                w = QWidget()
                h = QHBoxLayout(w)
                h.setContentsMargins(0, 0, 0, 0)
                h.addWidget(e, 1)
                chip = _status_chip(kind, 'neutral')
                chip.setWordWrap(False)
                h.addWidget(chip)
                form.addRow(label, w)
            else:
                form.addRow(label, e)
        errs = [x for x in P.validate(self.spec) if x.startswith(f'{self.sel + 1}단계') and '이름' in x]
        if errs:
            form.addRow(_status_chip(errs[0].split(': ', 1)[-1], 'warning'))
        form.addRow(_hint(note or '이름은 영문으로, 한 번만 씁니다. 뒤 단계는 이 이름으로 고릅니다.'))
        lay.addWidget(box)
        return form

    def _source_rows(self, form, st, i, key='panel'):
        """설정 출처 (this stage's stored settings / the tab's current ones) + tab buttons."""
        s = st['settings']
        src = combo([(0, '이 단계에 저장된 설정'), (1, '탭의 지금 설정')], 0 if s.get(key) else 1)
        form.addRow('설정 출처', src)
        note = _hint('')
        form.addRow(note)

        def upd():
            note.setText('이 단계는 설정을 따로 저장합니다. 탭에서 다른 이미지를 만져도 파이프라인 결과는 바뀌지 않습니다.'
                         if s.get(key) else '실행할 때 탭의 지금 설정을 씁니다.')

        def chose(ix):
            if src.itemData(ix) == 0 and not s.get(key):
                s[key] = P.capture_settings(self.win, st)
            elif src.itemData(ix) == 1:
                s[key] = None
            upd()
        src.currentIndexChanged.connect(chose)
        upd()
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 6)
        row.addStretch()
        take = QPushButton('탭 설정 가져오기')
        take.clicked.connect(lambda: (s.__setitem__(key, P.capture_settings(self.win, st)), src.setCurrentIndex(0),
                                      upd(), self.win.statusBar().showMessage(f'{i + 1}단계에 탭 설정을 가져왔습니다.',
                                                                              4000)))
        row.addWidget(take)
        edit = QPushButton('탭에서 열어 고치기…')
        edit.clicked.connect(lambda: self.edit_in_tab(i))
        row.addWidget(edit)
        form.addRow(holder)
        theme.group_rows(form.labelForField(src), src, note, holder)
        return src

    # ---- 검출 ----
    def _ed_detect_roi(self, lay, st, i):
        s = st['settings']
        method = s.get('method', 'cells')
        m = R.METHODS[method]
        chs = self._channels()
        # 1 input: image, channels, time
        b1, f1 = card(1, '입력')
        f1.addRow('이미지', QLabel('데이터 폴더의 이미지 (비우면 지금 열린 이미지)'))
        over = s.setdefault('channels', {})
        for label, attr in m[4]:
            c = combo([('', '탭 설정 그대로')] + [(ch, ch) for ch in chs], over.get(attr, ''))
            c.currentIndexChanged.connect(lambda _x, c=c, attr=attr: over.__setitem__(attr, c.currentData()))
            f1.addRow(label, c)
        if method == 'mito':
            cells = self._roi_combo(i, s.get('cells'), kinds=('region',))
            cells.currentIndexChanged.connect(lambda _x: (s.__setitem__('cells', cells.currentData()),
                                                          self._refresh_row()))
            f1.addRow('세포 ROI', cells)
        f1.addRow('시점', QLabel('보고 있는 시점 (시점마다 따로는 ROI 추적)'))
        lay.addWidget(b1)
        # 2 method
        b2, f2 = card(2, '검출 방법')

        def pick(key):
            if key == s.get('method'):
                return
            s['method'] = key
            s['names'] = {r: n for r, n, _k, _t in R.METHODS[key][1]}
            s['channels'] = {}
            s['panel'] = None
            if key == 'mito':
                rois = self._rois(i)
                s['cells'] = next((n for n, k in rois.items() if k == 'region'), 'Cell')
            self._refresh_row()
        w, _r = radios(b2, [(k, f'{v[0]}') for k, v in R.METHODS.items()], method, pick, per_row=3)
        f2.addRow('알고리즘', w)
        self._source_rows(f2, st, i)
        redo = combo([(True, '다시 찾기'), (False, '그대로 두기')], bool(s.get('redo', True)))
        redo.currentIndexChanged.connect(lambda _x: s.__setitem__('redo', redo.currentData()))
        f2.addRow('이미 결과가 있으면', redo)
        lay.addWidget(b2)
        # 3 result names
        names = s.setdefault('names', {})
        rows = []
        for role, default, kind, text in m[1]:
            rows.append((text, names.get(role, default), lambda v, role=role: names.__setitem__(role, v),
                         R.KIND_TEXT[kind], default))
        self._result_card(lay, 3, rows)

    # ---- ROI 연산 ----
    def _ed_roi_op(self, lay, st, i):
        s = st['settings']
        b1, f1 = card(1, '입력 ROI')
        a = self._roi_combo(i, s.get('a'), kinds=('region', 'spot'))
        a.currentIndexChanged.connect(lambda _x: (s.__setitem__('a', a.currentData()), self._preview_later(),
                                                  self._refresh_row()))
        f1.addRow('A', a)
        b = self._roi_combo(i, s.get('b'), kinds=('region', 'spot'))
        b.currentIndexChanged.connect(lambda _x: (s.__setitem__('b', b.currentData()), self._preview_later(),
                                                  self._refresh_row()))
        f1.addRow('B', b)
        lay.addWidget(b1)
        b2, f2 = card(2, '연산')
        pair = combo(R.PAIRS, s.get('pair', 'cell'))
        pair.currentIndexChanged.connect(lambda _x: (s.__setitem__('pair', pair.currentData()), self._preview_later()))
        um = um_box(s.get('um', 1.0), 0, 100)
        um.valueChanged.connect(lambda v: (s.__setitem__('um', v), self._preview_later()))
        inner, outer = um_box(s.get('inner', 2.0), 0, 100), um_box(s.get('outer', 6.0), 0, 200)
        inner.valueChanged.connect(lambda v: (s.__setitem__('inner', v), self._preview_later()))
        outer.valueChanged.connect(lambda v: (s.__setitem__('outer', v), self._preview_later()))
        avoid = self._roi_combo(i, s.get('avoid'), kinds=('region',), empty='피하지 않음')
        avoid.currentIndexChanged.connect(lambda _x: (s.__setitem__('avoid', avoid.currentData()),
                                                      self._preview_later()))
        nb = QSpinBox()
        nb.setRange(1, 50)
        nb.setValue(int(s.get('n', 4)))
        nb.valueChanged.connect(lambda v: (s.__setitem__('n', v), self._preview_later()))
        note = _hint('')

        def show(do):
            vis = {pair: do in R.NEEDS_B, um: do in ('dilate', 'erode'), inner: do == 'ring', outer: do == 'ring',
                   avoid: do == 'ring', nb: do == 'bands'}
            theme.show_rows(f2, [w for w, v in vis.items() if v], True)
            theme.show_rows(f2, [w for w, v in vis.items() if not v], False)
            theme.show_rows(f1, [b], do in R.NEEDS_B + ('bands',))
            lab = f1.labelForField(b)
            if lab is not None:
                lab.setText('B (기준 핵)' if do == 'bands' else 'B')
            note.setText({'subtract': 'A마다 짝이 되는 B를 뺍니다 (예: Cyto − Spot, 같은 세포 번호끼리).',
                          'intersect': 'A에서 B와 겹친 부분만 남깁니다.',
                          'add': 'A에 B를 더합니다 (다른 A와 겹치지 않는 부분만).',
                          'merge': '같은 부모 (세포) 안의 조각을 하나로 합칩니다.',
                          'dilate': 'A를 바깥으로 넓힙니다.', 'erode': 'A를 안쪽으로 줄입니다.',
                          'ring': 'A 둘레의 고리 (배경). 고른 ROI (예: Cell)는 피합니다.',
                          'bands': 'B (핵) → A 경계 상대 거리로 n개 띠 (B가 없으면 가장자리 → 가운데).'}.get(do, ''))

        def pick(do):
            s['do'] = do
            show(do)
            self._preview_later()
            self._refresh_row_soft()
        w, _r = radios(b2, R.ROI_OPS, s.get('do', 'subtract'), pick)
        f2.addRow(w)
        f2.addRow('짝 짓기', pair)
        f2.addRow('거리', um)
        f2.addRow('고리 안쪽', inner)
        f2.addRow('고리 바깥쪽', outer)
        f2.addRow('피할 ROI', avoid)
        f2.addRow('띠 개수', nb)
        f2.addRow(note)
        lay.addWidget(b2)
        show(s.get('do', 'subtract'))
        self._result_card(lay, 3, [('결과', s.get('out', ''), lambda v: s.__setitem__('out', v), None, 'Cyto_noSpot')],
                          '결과 ROI는 A의 부모 (세포) 번호를 물려받습니다.')
        self._preview_box(lay, i)

    # ---- ROI 필터 ----
    def _value_fields(self, i, name):
        """Parameters measured on ROI ``name`` before stage i (and the native ones)."""
        rois = self._rois(i)
        kind = rois.get(name, 'region')
        chs = self._channels()
        out = []
        if kind == 'track':
            out += [('frames', '길이 (프레임)'), ('divided', '분열한 세포'), ('edge', '가장자리에 닿음'),
                    ('class', '트랙 분류'), ('change:thr', '변화 (끝 ÷ 처음)')]
        else:
            out += [('Area', 'Area'), ('Perimeter', 'Perimeter'), ('Circularity', 'Circularity'),
                    ('Solidity', 'Solidity'), ('Feret', 'Feret'), ('AR', 'AR'), ('edge', '가장자리에 닿음')]
            out += [(f'Mean:{c}', f'{c} Mean') for c in chs] + [(f'IntDen:{c}', f'{c} IntDen') for c in chs]
        for st in self.spec.stages[:i]:
            if st['kind'] in ('measure.roi', 'calc.values') and st.get('enabled', True):
                ss = st['settings']
                if st['kind'] == 'measure.roi' and ss.get('a') != name and ss.get('b') != name:
                    continue
                for c in R.predicted_columns(st, chs):
                    out.append((c, c))
        return out

    def _ed_roi_filter(self, lay, st, i):
        s = st['settings']
        rois = self._rois(i)
        b1, f1 = card(1, '입력 ROI')
        inp = self._roi_combo(i, s.get('input'))
        f1.addRow('ROI', inp)
        lay.addWidget(b1)
        b2, f2 = card(2, '기준')
        holder = QWidget()
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)
        mode = combo([('all', '모두 맞아야 (그리고)'), ('any', '하나라도 (또는)')], s.get('mode', 'all'))
        mode.currentIndexChanged.connect(lambda _x: (s.__setitem__('mode', mode.currentData()), self._preview_later()))
        addc = QPushButton('＋ 조건 추가')

        def fill():
            while hl.count():
                w = hl.takeAt(0).widget()
                if w is not None:
                    w.deleteLater()
            for ci, c in enumerate(s.setdefault('conds', [])):
                hl.addWidget(self._filter_row(s, ci, c, i, fill))
            if not s['conds']:
                hl.addWidget(_hint('조건이 없으면 모두 통과합니다.'))

        def add():
            if s.get('by') == 'value':
                fld = self._value_fields(i, s.get('input'))
                s['conds'].append([fld[0][0] if fld else 'Area', '>=', 0])
            else:
                other = next((n for n in rois if n != s.get('input')), '')
                s['conds'].append([f'overlap:{other}', '>', 0])
            fill()
            self._preview_later()
        addc.clicked.connect(add)

        def by(key):
            if key == s.get('by'):
                return
            s['by'] = key
            s['conds'] = []
            fill()
            self._refresh_row()
        w, _r = radios(b2, [('relation', '다른 ROI와의 관계'), ('value', '측정값')], s.get('by', 'relation'), by)
        f2.addRow('기준 종류', w)
        f2.addRow(holder)
        f2.addRow('조건 묶기', mode)
        f2.addRow(addc)
        inp.currentIndexChanged.connect(lambda _x: (s.__setitem__('input', inp.currentData()), fill(),
                                                    self._preview_later(), self._refresh_row_soft()))
        fill()
        lay.addWidget(b2)
        self._result_card(lay, 3, [
            ('맞는 ROI', s.get('out', ''), lambda v: s.__setitem__('out', v), None, f'{s.get("input") or "ROI"}_in'),
            ('나머지 (선택)', s.get('rest', ''), lambda v: s.__setitem__('rest', v), None, '비우면 버림')])
        self._preview_box(lay, i)

    def _filter_row(self, s, ci, c, i, refill):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        val = QLineEdit('' if len(c) < 3 or c[2] is None else
                        (f'{c[2][0]} – {c[2][1]}' if isinstance(c[2], list) else str(c[2])))
        if s.get('by') == 'value':
            fields = self._value_fields(i, s.get('input'))
            f = combo(fields, c[0])
            if f.findData(c[0]) < 0:
                f.addItem(str(c[0]), c[0])
                f.setCurrentIndex(f.count() - 1)
            op = combo(R.CMP, c[1])
            h.addWidget(f)
            h.addWidget(op)

            def upd():
                c[0] = f.currentData()
                c[1] = op.currentData()
                self._set_value(c, val.text())
                val.setVisible(c[1] not in ('yes', 'no'))
                self._preview_later()
            f.currentIndexChanged.connect(lambda _x: upd())
            op.currentIndexChanged.connect(lambda _x: upd())
        else:
            head, _, other = str(c[0]).partition(':')
            rel = next((k for k, _t, tpl, o in R.RELATIONS if tpl.split(':')[0] == head and o == c[1]),
                       'overlaps')
            r = combo([(k, t) for k, t, _f, _o in R.RELATIONS], rel)
            o = self._roi_combo(i, other)
            h.addWidget(r)
            h.addWidget(o)

            def upd():
                key = r.currentData()
                _k, _t, tpl, op_ = next(x for x in R.RELATIONS if x[0] == key)
                c[:] = [tpl.format(o.currentData()), op_] + ([0] if op_ in ('>', '<=') and key != 'near' else [])
                if key == 'near':
                    self._set_value(c, val.text() or '1')
                val.setVisible(key == 'near')
                self._preview_later()
                self._refresh_row_soft()
            r.currentIndexChanged.connect(lambda _x: upd())
            o.currentIndexChanged.connect(lambda _x: upd())
            val.setPlaceholderText('µm')
        h.addWidget(val)
        val.editingFinished.connect(lambda: (self._set_value(c, val.text()), self._preview_later()))
        val.setVisible(c[1] not in ('yes', 'no') and (s.get('by') == 'value' or str(c[0]).startswith('dist:')))
        h.addStretch(1)   # item · op · value leading, the remove button at the row end
        rm = QToolButton()
        rm.setText('−')
        rm.setToolTip('조건 빼기')
        rm.clicked.connect(lambda: (s['conds'].pop(ci), refill(), self._preview_later()))
        h.addWidget(rm)
        return w

    @staticmethod
    def _set_value(c, text):
        t = (text or '').strip()
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

    # ---- ROI 추적 ----
    def _ed_roi_track(self, lay, st, i):
        s = st['settings']
        alg = s.get('algorithm', 'particle')
        b1, f1 = card(1, '입력 ROI')
        inp = self._roi_combo(i, s.get('input', ''), kinds=('region', 'spot'), empty='시점마다 탭 설정으로 검출')
        inp.currentIndexChanged.connect(lambda _x: (s.__setitem__('input', inp.currentData()), self._refresh_row()))
        f1.addRow('ROI', inp)
        kind = self._rois(i).get(s.get('input'), '')
        rec = 'particle' if kind == 'spot' else 'cytosol' if kind == 'region' else ''
        if rec:
            chip = _status_chip(f'추천: {R.TRACKERS[rec][0]} 알고리즘 ({R.KIND_TEXT[kind]})', 'info')
            f1.addRow(chip)
        f1.addRow(_hint('입자 추적은 시점마다 입자 ROI 설정 (또는 ParticleTracker 방식)으로, 세포질 추적은 고른 세포 '
                        '검출 방식으로 시점마다 찾고 잇습니다.'))
        lay.addWidget(b1)
        b2, f2 = card(2, '추적 알고리즘')

        def pick(key):
            if key == s.get('algorithm'):
                return
            s['algorithm'] = key
            s['out'] = R.TRACKERS[key][2] if s.get('out') in (None, '', 'Spot_track', 'Cell_track') else s['out']
            s['panel'] = s['cell_track'] = None
            self._refresh_row()
        w, _r = radios(b2, [('particle', '입자 추적 (LAP, ParticleTracker와 같은 방식)'),
                            ('cytosol', '세포질 추적 (광학 흐름 + 겹침, 분열 · 가장자리 제외)')], alg, pick, per_row=1)
        f2.addRow(w)
        lay.addWidget(b2)
        b3, f3 = card(3, '알고리즘 설정')
        self._source_rows(f3, st, i, 'cell_track' if alg == 'cytosol' else 'panel')
        if alg == 'particle':
            thr = QDoubleSpinBox()
            thr.setRange(-1, 1e6)
            thr.setSpecialValueText('LUT Min 그대로')
            thr.setValue(float(s['signal_thr']) if s.get('signal_thr') is not None else -1)
            thr.valueChanged.connect(lambda v: s.__setitem__('signal_thr', None if v < 0 else v))
            f3.addRow('5 신호 기준 값', thr)
        redo = combo([(True, '다시 추적'), (False, '그대로 두기')], bool(s.get('redo', True)))
        redo.currentIndexChanged.connect(lambda _x: s.__setitem__('redo', redo.currentData()))
        f3.addRow('이미 결과가 있으면', redo)
        lay.addWidget(b3)
        self._result_card(lay, 4, [('트랙 집합', s.get('out', ''), lambda v: s.__setitem__('out', v), R.KIND_TEXT['track'],
                                    R.TRACKERS[alg][2])])

    # ---- 측정 ----
    def _ed_measure_roi(self, lay, st, i):
        s = st['settings']
        t = s.get('type', 'signal')
        rois = self._rois(i)
        kind_a = rois.get(s.get('a'), 'region')
        chs = self._channels(s)
        # 1 input ROI
        b1, f1 = card(1, '입력 ROI')
        a = self._roi_combo(i, s.get('a'))
        a.currentIndexChanged.connect(lambda _x: (s.__setitem__('a', a.currentData()), self._refresh_row()))
        f1.addRow('A (바깥 · 부모)' if t == 'relation' else 'ROI', a)
        if t == 'relation':
            b = self._roi_combo(i, s.get('b'), empty='없음 (Coloc 2)')
            b.currentIndexChanged.connect(lambda _x: (s.__setitem__('b', b.currentData()), self._refresh_row()))
            f1.addRow('B (안 · 대상)', b)
        lay.addWidget(b1)
        # 2 channels (separate from the ROI, owner 2026-11-25)
        b2, f2 = card(2, '입력 채널')
        need = {'shape': 0, 'signal': 1, 'relation': 0}[t]
        sel = s.get('channels') or []
        w, boxes = chips_grid([(c, c) for c in chs], sel or (chs if t == 'signal' else []),
                              lambda on: (s.__setitem__('channels', [] if t == 'signal' and len(on) == len(chs)
                                                        else on), self._refresh_row_soft()), per_row=4)
        if t == 'shape':
            for bx in boxes.values():
                bx.setEnabled(False)
            f2.addRow(w)
            h2 = _hint('형태는 채널을 받지 않습니다.')
            f2.addRow(h2)
            theme.group_rows(w, h2)
        else:
            f2.addRow(w)
            h2 = _hint('고른 채널마다 따로 잽니다.' if t == 'signal' else
                       '채널 없음 = 개수 · 겹침 · 거리, 하나 = 분배 · 농축, 둘 = Coloc 2.')
            f2.addRow(h2)
            theme.group_rows(w, h2)
        z = combo([('', '보는 Z'), ('mip', 'MIP (최대 투영)'), ('mean', '평균 투영'), ('sum', '합 투영')], s.get('z', ''))
        z.currentIndexChanged.connect(lambda _x: s.__setitem__('z', z.currentData()))
        f2.addRow('Z', z)
        if t == 'shape':
            theme.show_rows(f2, [z], False)
        del need
        lay.addWidget(b2)
        # 3 type
        b3, f3 = card(3, '측정 종류')

        def pick(key):
            if key == s.get('type'):
                return
            s['type'] = key
            s['params'] = {'shape': ['Area', 'Perimeter', 'Circularity'], 'signal': ['Area', 'Mean', 'IntDen'],
                           'relation': ['Count', 'Density']}[key]
            if key != 'relation':
                s['b'] = ''
            s['name'] = ''
            self._refresh_row()
        w, _r = radios(b3, R.MEASURE_TYPES, t, pick, per_row=3)
        f3.addRow(w)
        lay.addWidget(b3)
        # 4 params, grouped; groups that don't fit the input greyed with the reason
        b4, f4 = card(4, '파라미터')
        on = set(s.get('params') or [])
        nch = len(s.get('channels') or (chs if t == 'signal' else []))
        all_boxes = {}

        def changed(_x=None):
            s['params'] = [p for p, bx in all_boxes.items() if bx.isChecked()]
            self._refresh_row_soft()
        for group, ps, applies, need_ch in R.PARAMS[t]:
            ok, why = True, ''
            if applies == 'track' and kind_a != 'track' and (t != 'relation' or rois.get(s.get('b')) != 'track'):
                ok, why = False, '트랙 ROI에만 씁니다.'
            elif applies == 'region' and kind_a == 'track' and t != 'relation':
                ok, why = False, '트랙에는 시간 · 트랙 파라미터를 씁니다.'
            elif applies == 'mito' and not str(s.get('a', '')).lower().startswith('mito'):
                ok, why = False, '미토 ROI (mitoROI 검출)에만 씁니다.'
            elif t == 'relation' and need_ch and nch != need_ch:
                ok, why = False, f'채널 {need_ch}개가 필요합니다 (지금 {nch}개).'
            lab = QLabel(group)
            theme.secondary(lab)
            if not ok:
                lab.setToolTip(why)
            f4.addRow(lab)
            w, boxes = chips_grid(ps, on, changed, per_row=3, tips={p: why for p, _t in ps} if not ok else None,
                                  enabled={p: ok for p, _t in ps})
            f4.addRow(w)
            theme.group_rows(lab, w)   # a group's title and its chips are one row group
            all_boxes.update(boxes)
        lay.addWidget(b4)
        # 5 settings
        b5, f5 = card(5, '설정')
        if t == 'signal':
            bg = combo(R.BG, s.get('bg', 'none'))
            f5.addRow('배경', bg)
            ring = s.setdefault('ring', [0.5, 2.0])
            r_in, r_out = um_box(ring[0], 0, 50), um_box(ring[1], 0, 100)
            r_in.valueChanged.connect(lambda v: ring.__setitem__(0, v))
            r_out.valueChanged.connect(lambda v: ring.__setitem__(1, v))
            f5.addRow('고리 안쪽', r_in)
            f5.addRow('고리 바깥쪽', r_out)
            other = self._roi_combo(i, s.get('bg_roi', ''), kinds=('region',))
            other.currentIndexChanged.connect(lambda _x: (s.__setitem__('bg_roi', other.currentData()),
                                                          self._refresh_row_soft()))
            f5.addRow('배경 ROI (같은 부모의 중앙값)', other)
            low = QSpinBox()
            low.setRange(1, 50)
            low.setSuffix(' %')
            low.setValue(int(s.get('low_pct', 10)))
            low.valueChanged.connect(lambda v: s.__setitem__('low_pct', v))
            f5.addRow('하위', low)

            def bg_rows(_x=None):
                k = bg.currentData()
                s['bg'] = k
                theme.show_rows(f5, [r_in, r_out], k == 'ring')
                theme.show_rows(f5, [other], k == 'roi')
                theme.show_rows(f5, [low], k == 'low')
                if k == 'roi' and not s.get('bg_roi'):
                    s['bg_roi'] = other.currentData()
            bg.currentIndexChanged.connect(bg_rows)
            bg_rows()
            top = QSpinBox()
            top.setRange(1, 100)
            top.setSuffix(' %')
            top.setValue(int(s.get('top_pct', 10)))
            top.valueChanged.connect(lambda v: s.__setitem__('top_pct', v))
            f5.addRow('상위 n %', top)
            onb = combo([('lut', '채널의 LUT Min'), ('value', '값 직접')], 'lut' if s.get('on', 'lut') == 'lut' else 'value')
            onv = QDoubleSpinBox()
            onv.setRange(-1e9, 1e9)
            onv.setValue(float(s['on']) if s.get('on') not in (None, 'lut') else 0.0)
            f5.addRow('켜짐 기준', onb)
            f5.addRow('기준 값', onv)

            def on_rows(_x=None):
                s['on'] = 'lut' if onb.currentData() == 'lut' else onv.value()
                theme.show_rows(f5, [onv], onb.currentData() != 'lut')
            onb.currentIndexChanged.connect(on_rows)
            onv.valueChanged.connect(on_rows)
            on_rows()
        elif t == 'shape':
            cont = combo([('pixel', '픽셀'), ('contour', '등치선 (sub-pixel, 입자 ROI 설정)')], s.get('contour', 'pixel'))
            cont.currentIndexChanged.connect(lambda _x: s.__setitem__('contour', cont.currentData()))
            f5.addRow('윤곽', cont)
            par = self._roi_combo(i, s.get('parent_roi', ''), kinds=('region',), empty='세포 (자동)')
            par.currentIndexChanged.connect(lambda _x: s.__setitem__('parent_roi', par.currentData()))
            f5.addRow('부모 ROI (위치)', par)
        else:
            row = combo(R.ROW_UNITS, s.get('row', 'a'))
            row.currentIndexChanged.connect(lambda _x: s.__setitem__('row', row.currentData()))
            f5.addRow('행 하나', row)
            ref = self._roi_combo(i, s.get('ref_roi', ''), kinds=('region',), empty='없음 (A 가운데)')
            ref.currentIndexChanged.connect(lambda _x: s.__setitem__('ref_roi', ref.currentData()))
            f5.addRow('상대 위치 기준 ROI', ref)
            if any(p in (s.get('params') or []) for p in ('Bands', 'Coloc')):
                self._source_rows(f5, st, i)
        lay.addWidget(b5)
        self._result_card(lay, 6, [('측정 이름', s.get('name', ''), lambda v: s.__setitem__('name', v), None,
                                    R.measure_name({**s, 'name': ''}))],
                          '파라미터 이름 = 「측정 이름 › 채널 파라미터」 (예: 신호 · Cyto › GFP Mean). 같은 이름의 측정은 한 표에 '
                          '이어 붙습니다.')

    # ---- 측정값 연산 ----
    def _ed_calc_values(self, lay, st, i):
        s = st['settings']
        chs = self._channels()
        tables = P.tables_before(self.spec, i)
        cols = {}
        for x in self.spec.stages[:i]:
            if x.get('enabled', True) and x['kind'] in ('measure.roi', 'calc.values'):
                tn = R.measure_name(x['settings']) if x['kind'] == 'measure.roi' else x['settings'].get('table')
                cols.setdefault(tn, []).extend(R.predicted_columns(x, chs))
        if not s.get('table') and tables:
            s['table'] = tables[-1]
        b1, f1 = card(1, '입력 값')
        tab = combo(tables or ['(앞에 측정 단계가 없습니다)'], s.get('table'))
        f1.addRow('측정 결과', tab)
        ca, cb = QComboBox(), QComboBox()
        ca.setEditable(True)
        cb.setEditable(True)

        def fill_cols():
            for c, key in ((ca, 'a'), (cb, 'b')):
                c.blockSignals(True)
                c.clear()
                for x in cols.get(s.get('table'), []):
                    c.addItem(x, x)
                c.setEditText(str(s.get(key) or ''))
                c.blockSignals(False)
        tab.currentIndexChanged.connect(lambda _x: (s.__setitem__('table', tab.currentData()), fill_cols(),
                                                    self._refresh_row_soft()))
        ca.currentTextChanged.connect(lambda t: s.__setitem__('a', t))
        cb.currentTextChanged.connect(lambda t: s.__setitem__('b', t))
        fill_cols()
        f1.addRow('A', ca)
        f1.addRow('B (열 또는 숫자)', cb)
        pr = combo(R.PAIR_ROWS, s.get('pair', 'same'))
        pr.currentIndexChanged.connect(lambda _x: s.__setitem__('pair', pr.currentData()))
        f1.addRow('B 짝', pr)
        lay.addWidget(b1)
        b2, f2 = card(2, '계산')
        expr = QLineEdit(s.get('expr', 'A / B'))
        expr.editingFinished.connect(lambda: s.__setitem__('expr', expr.text().strip() or 'A'))

        def pick(op):
            s['op'] = op
            theme.show_rows(f2, [expr], op == 'expr')
            theme.show_rows(f1, [cb, pr], op not in ('log2',))
            self._refresh_row_soft()
        w, _r = radios(b2, R.CALC_OPS, s.get('op', '/'), pick, per_row=3)
        f2.addRow(w)
        f2.addRow('식', expr)
        f2.addRow(_hint('식에는 A, B, log2, log10, sqrt, abs, exp를 씁니다 (예: (A − B) / B).'))
        lay.addWidget(b2)
        pick(s.get('op', '/'))
        b3, f3 = card(3, '정규화')
        norm = combo(R.NORMS, s.get('norm', 'none'))
        n = QSpinBox()
        n.setRange(1, 100)
        n.setValue(int(s.get('n', 3)))
        n.valueChanged.connect(lambda v: s.__setitem__('n', v))
        groups = sorted({it.group for it in self.win.items if it.group})
        ctrl = combo(groups or [''], s.get('control', ''))
        ctrl.setEditable(True)
        ctrl.currentTextChanged.connect(lambda t: s.__setitem__('control', t))
        scope = combo(R.SCOPES, s.get('scope', 'track'))
        scope.currentIndexChanged.connect(lambda _x: s.__setitem__('scope', scope.currentData()))
        f3.addRow('방법', norm)
        f3.addRow('처음 n 시점', n)
        f3.addRow('대조군 그룹', ctrl)
        f3.addRow('기준 범위', scope)

        def norm_rows(_x=None):
            k = norm.currentData()
            s['norm'] = k
            theme.show_rows(f3, [n], k == 'firstn')
            theme.show_rows(f3, [ctrl], k == 'control')
            theme.show_rows(f3, [scope], k not in ('none', 'control'))
            self._refresh_row_soft()
        norm.currentIndexChanged.connect(norm_rows)
        norm_rows()
        lay.addWidget(b3)
        self._result_card(lay, 4, [('파라미터', s.get('out', ''), lambda v: s.__setitem__('out', v), None,
                                    '계산 › GFP ÷ RFP')],
                          '결과 파라미터는 같은 표의 열이 되고, ROI 필터 (측정값) · 측정값 연산 · 그래프에서 씁니다.')

    # ---- preview (ROI 연산 / 필터) ----
    def _preview_box(self, lay, i):
        b5 = QGroupBox(f'미리 보기 · 현재 이미지 ({self.win.current.label if self.win.current else "없음"})')
        v5 = QVBoxLayout(b5)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(220)
        v5.addWidget(self.preview)
        from .ui.empty import EmptyState
        self.preview_empty = EmptyState('미리 볼 ROI가 없습니다', '이미지를 열고 검출 단계를 한 번 돌리면 미리 볼 수 있습니다.')
        self.preview_empty.setMinimumHeight(220)
        self.preview.hide()
        v5.addWidget(self.preview_empty)
        self.preview_chips = QHBoxLayout()
        v5.addLayout(self.preview_chips)
        lay.addWidget(b5)
        self._preview_i = i
        self._preview_later()
