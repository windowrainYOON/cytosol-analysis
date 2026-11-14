"""입자 기준 잡기 (v0.65, owner proposal 2026-11-14, particle-tracking doc ch. 11).

A page shown in place of the 입자 ROI tab's settings: 1 밝기 (nine borderline
candidates, faint -> bright; the user picks the faintest one that is still a
particle), 2 크기 (nine candidates at least that bright, small -> large; the
smallest particle), 3 적용 (the new criterion, the count before / after and
the images it is used for). The candidates are drawn on the canvas as
numbered boxes while the page is open."""

from __future__ import annotations

import datetime

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFormLayout,
    QGraphicsRectItem,
    QGraphicsSimpleTextItem,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from . import particle_detect as pdt
from . import theme

TILE = 92        # tile size (logical px)
HALF = 12        # half the crop shown in a tile (image px)
BOX = 18         # half the box drawn on the canvas (image px)
SCOPES = [('all', '모든 이미지 (같은 채널 이름)'), ('group', '같은 그룹만'), ('image', '이 이미지만')]


def criterion_text(c: dict | None, k_stat: float | None = None) -> str:
    if not c:
        k = f' {k_stat:.1f}σ' if k_stat else ''
        return f'기본 기준 (통계): 밝기 ≥{k} · 직접 잡은 기준 없음'
    scope = dict(SCOPES).get(c.get('scope'), '').split(' (')[0]
    return (f'사용자 기준 ({c.get("date", "")}, {c.get("channel", "")}, {scope}): 밝기 ≥ '
            f'{c["k"]:.1f}σ · 크기 ≥ {c.get("area", 0):.2f} µm²')


class Tile(QLabel):
    clicked = Signal(int)

    def __init__(self, n):
        super().__init__()
        self.n = n
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f'{n + 1}번 · 클릭 = 이 후보부터 입자')

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.n)
        super().mousePressEvent(ev)


def tile_pixmap(crop, lo, hi, color, n, caption, state):
    """state: 'pick', 'in' (counted as a particle with that pick), 'out'."""
    dpr = 2
    g = np.clip((crop.astype(np.float32) - lo) / max(hi - lo, 1e-6), 0, 1)
    rgb = np.zeros(crop.shape + (4,), np.uint8)
    for i in range(3):
        rgb[..., i] = (g * color[i] * 255).astype(np.uint8)
    rgb[..., 3] = 255
    rgb = np.ascontiguousarray(rgb)
    qi = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGBA8888).copy()
    S = TILE
    pm = QPixmap(S * dpr, S * dpr)
    pm.fill(Qt.GlobalColor.transparent)
    pm.setDevicePixelRatio(dpr)
    q = QPainter(pm)
    q.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(1, 1, S - 2, S - 2), 10, 10)
    q.setClipPath(clip)
    q.drawImage(QRectF(1, 1, S - 2, S - 2), qi)
    if state == 'out':
        q.fillRect(QRectF(0, 0, S, S), QColor(0, 0, 0, 120))
    q.setClipping(False)
    f = QFont(QApplication.font())
    f.setPointSizeF(9)
    f.setBold(True)
    q.setFont(f)
    q.setPen(Qt.PenStyle.NoPen)
    q.setBrush(QColor(255, 220, 0) if state == 'pick' else QColor(0, 0, 0, 150))
    q.drawRoundedRect(QRectF(6, 6, 20, 18), 9, 9)
    q.setPen(QColor(0, 0, 0) if state == 'pick' else QColor(255, 255, 255))
    q.drawText(QRectF(6, 6, 20, 18), Qt.AlignmentFlag.AlignCenter, str(n + 1))
    if state in ('pick', 'in'):
        q.setBrush(QApplication.palette().highlight().color())
        q.setPen(Qt.PenStyle.NoPen)
        q.drawEllipse(QRectF(S - 24, 6, 18, 18))
        pen = QPen(QColor(255, 255, 255))
        pen.setWidthF(2)
        q.setPen(pen)
        q.drawPolyline([QPointF(S - 19.5, 15), QPointF(S - 16, 18.5), QPointF(S - 10.5, 11.5)])
    f.setBold(False)
    f.setPointSizeF(8.5)
    q.setFont(f)
    q.setPen(QColor(255, 255, 255, 230))
    q.drawText(QRectF(0, S - 22, S - 8, 18), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, caption)
    pen = QPen(QColor(255, 220, 0) if state == 'pick' else QColor(255, 255, 255, 40))
    pen.setWidthF(3 if state == 'pick' else 1)
    q.setPen(pen)
    q.setBrush(Qt.BrushStyle.NoBrush)
    q.drawRoundedRect(QRectF(1.5, 1.5, S - 3, S - 3), 10, 10)
    q.end()
    return pm


def _row(*ws, end=True):
    w = QWidget()
    w.setProperty('hig_no_reflow', True)
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(8)
    if end:
        h.addStretch(1)
    for x in ws:
        h.addWidget(x)
    if not end:
        h.addStretch(1)
    return w


class CalibPage(QWidget):
    """The three steps; ``finished(criterion or None)`` when it closes."""

    finished = Signal(object)

    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.win = panel.win
        self.item = None
        self.c = None
        self.cands = []
        self.step = 0
        self.shown = []
        self.pick_b = None
        self.pick_s = None
        self.shift = {0: 0, 1: 0}
        self._scene = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.chips = []
        steps = QWidget()
        steps.setProperty('hig_no_reflow', True)
        sl = QHBoxLayout(steps)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(6)
        for t in ('1 밝기', '2 크기', '3 적용'):
            b = theme.chip(QCheckBox(t))
            b.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.chips.append(b)
            sl.addWidget(b)
        sl.addStretch(1)
        lay.addWidget(steps)
        # 1 / 2: the candidate grid
        self.box = QGroupBox()
        v = QVBoxLayout(self.box)
        self.ask = QLabel()
        self.ask.setWordWrap(True)
        theme.text_style(self.ask, 'headline')
        v.addWidget(self.ask)
        self.grid = QGridLayout()
        self.grid.setSpacing(8)
        self.tiles = []
        for i in range(9):
            t = Tile(i)
            t.clicked.connect(self.choose)
            self.tiles.append(t)
            self.grid.addWidget(t, i // 3, i % 3)
        gw = QWidget()
        gw.setProperty('hig_no_reflow', True)
        gw.setLayout(self.grid)
        v.addWidget(gw)
        self.chosen = theme.StatusLabel(kind='info')
        self.chosen.setWordWrap(True)
        v.addWidget(self.chosen)
        lay.addWidget(self.box)
        self.more = QGroupBox('후보가 맞지 않으면')
        mf = QVBoxLayout(self.more)
        self.brighter = QPushButton('더 밝은 후보')
        self.fainter = QPushButton('더 흐린 후보')
        self.brighter.clicked.connect(lambda: self._shift(1))
        self.fainter.clicked.connect(lambda: self._shift(-1))
        mf.addWidget(_row(self.brighter, self.fainter, end=False))
        h = QLabel('9개가 모두 입자가 아니면 더 밝은(큰) 후보, 모두 입자면 더 흐린(작은) 후보로 다시 '
                   '뽑습니다. 후보는 캔버스에 번호 상자로 보입니다.')
        h.setWordWrap(True)
        theme.hint(h)
        mf.addWidget(h)
        lay.addWidget(self.more)
        # 3: the new criterion
        self.apply_box = QGroupBox('새 기준')
        f = QFormLayout(self.apply_box)
        self.k_lab = QLabel()
        self.a_lab = QLabel()
        self.n_lab = QLabel()
        for w in (self.k_lab, self.a_lab, self.n_lab):
            w.setWordWrap(True)
        f.addRow('밝기', self.k_lab)
        f.addRow('크기', self.a_lab)
        f.addRow('이 이미지', self.n_lab)
        h = QLabel('자동 검출의 시작 문턱 = 밝기 기준, 입자 경계는 그 절반 높이까지, 반치 면적이 크기 '
                   '기준보다 작으면 버립니다. 밝기는 배경 잡음(σ) 단위라 노출이 다른 이미지에도 같은 '
                   '뜻으로 쓰입니다.')
        h.setWordWrap(True)
        theme.hint(h)
        f.addRow(h)
        lay.addWidget(self.apply_box)
        self.use_box = QGroupBox('다른 이미지의 자동 검출에도 이 기준을 쓸까요?')
        u = QVBoxLayout(self.use_box)
        self.scope = {}
        grp = QButtonGroup(self)
        for key, text in SCOPES:
            r = QRadioButton(text)
            grp.addButton(r)
            self.scope[key] = r
            u.addWidget(r)
        self.scope['all'].setChecked(True)
        h = QLabel('기준은 프로젝트에 채널 이름별로 저장됩니다. 수동 threshold로 찾는 이미지는 바꾸지 않습니다.')
        h.setWordWrap(True)
        theme.hint(h)
        u.addWidget(h)
        lay.addWidget(self.use_box)
        self.cancel_btn = QPushButton('취소')
        self.back_btn = QPushButton('이전')
        self.next_btn = theme.prominent(QPushButton('다음'))
        self.cancel_btn.clicked.connect(lambda: self.close_page(None))
        self.back_btn.clicked.connect(self.back)
        self.next_btn.clicked.connect(self.next)
        lay.addWidget(_row(self.cancel_btn, self.back_btn, self.next_btn))
        lay.addStretch(1)

    # ---- flow ---------------------------------------------------------------

    def start(self, item, c: int) -> bool:
        """Find the candidates of the item's current plane in channel c."""
        self.item, self.c = item, c
        cells = self.panel.cells_for(item)
        s = self.panel.settings()
        plane = item.planes()[c]
        if cells is not None and len(cells) and s.within != 'image':
            from .intensity import base_masks
            region = base_masks(cells)['cyto' if s.within == 'cyto' else 'cell'] > 0
        else:
            region = np.ones(plane.shape, bool)
        self.plane = plane
        self.cands, _, self.sigma = pdt.candidates(plane, region, item.pixel_um)
        if len(self.cands) < 3:
            return False
        self.region = region
        self.n_before = self._count(s)
        self.shift = {0: 0, 1: 0}
        self.pick_b = self.pick_s = None
        lut = item.luts[c] if c < len(item.luts) else None
        self.lo = float(lut.vmin) if lut is not None else float(np.percentile(plane, 1))
        self.color = tuple(getattr(lut, 'color', None) or (0.25, 1.0, 0.35))
        self.show_step(0)
        return True

    def _count(self, s):
        from .intensity import detect_particles
        cells = self.panel.cells_for(self.item)
        p = detect_particles(cells, self.plane, s, 16, self.item.pixel_um)
        return int(p.labels.max()) if p.labels is not None else 0

    def _shift(self, d):
        self.shift[self.step] += d
        if self.step == 0:
            self.pick_b = None
        else:
            self.pick_s = None
        self.show_step(self.step)

    def _pool(self):
        if self.step == 0:
            f = 1.6 ** self.shift[0]
            return pdt.pick(self.cands, 'snr', pdt.brightness_targets(3.0 * f, 15.0 * f))
        k = self.shown_b[self.pick_b]['snr']
        pool = [c for c in self.cands if c['snr'] >= k]
        f = 1.5 ** self.shift[1]
        tg = [t * f for t in pdt.size_targets(self.item.pixel_um)]
        return pdt.pick(pool, 'area', tg)

    def show_step(self, step):
        self.step = step
        for i, ch in enumerate(self.chips):
            ch.setChecked(i == step)
        grid = step < 2
        for w in (self.box, self.more):
            w.setVisible(grid)
        for w in (self.apply_box, self.use_box):
            w.setVisible(not grid)
        self.back_btn.setVisible(step > 0)
        self.next_btn.setText('기준 적용' if step == 2 else '다음')
        if grid:
            self.shown = self._pool()
            if step == 0:
                self.shown_b = self.shown
            self.box.setTitle('밝기 · 후보 (흐림 → 밝음)' if step == 0 else '크기 · 후보 (작음 → 큼)')
            self.ask.setText('어디부터 입자인가요? 입자로 볼 수 있는 가장 '
                             + ('흐린' if step == 0 else '작은') + ' 후보를 고르세요.')
            self._fill_tiles()
        else:
            self._apply_page()
        self._draw_boxes()
        msg = {0: f'입자 기준 잡기 1/3: 밝기 후보 {len(self.shown)}개를 캔버스에 번호 상자로 표시했습니다',
               1: f'입자 기준 잡기 2/3: 크기 후보 {len(self.shown)}개',
               2: '입자 기준 잡기 3/3: 새 기준과 적용 범위를 확인하세요'}[step]
        self.win.statusBar().showMessage(msg, 8000)

    def _caption(self, c):
        if self.step == 0:
            return f'{c["snr"]:.1f}σ'
        px = self.item.pixel_um or pdt.DEFAULT_PX_UM
        return f'{c["area"] * px * px:.2f} µm²'

    def _fill_tiles(self):
        pick = self.pick_b if self.step == 0 else self.pick_s
        hi = max([float(self.plane[c['y'], c['x']]) for c in self.shown] + [self.lo + 1]) * 0.9
        for i, t in enumerate(self.tiles):
            if i >= len(self.shown):
                t.hide()
                continue
            c = self.shown[i]
            crop = self.plane[c['y'] - HALF:c['y'] + HALF + 1, c['x'] - HALF:c['x'] + HALF + 1]
            st = None if pick is None else ('pick' if i == pick else ('in' if i > pick else 'out'))
            t.setPixmap(tile_pixmap(crop, self.lo, hi, self.color, i, self._caption(c), st))
            t.show()
        n = len(self.shown)
        if pick is None:
            self.chosen.set_kind('info')
            self.chosen.setText('후보를 눌러 고르세요.')
        elif self.step == 0:
            self.chosen.set_kind('success')
            k = self.shown[pick]['snr']
            self.chosen.setText(f'{pick + 1}번부터 입자 → 밝기 기준 {k * 0.98:.1f}σ (배경 잡음의 {k * 0.98:.1f}배). '
                                f'{pick + 1}–{n}번이 검출되고' + (f' 1–{pick}번은 버립니다.' if pick else '니다.'))
        else:
            self.chosen.set_kind('success')
            px = self.item.pixel_um or pdt.DEFAULT_PX_UM
            a = self.shown[pick]['area']
            self.chosen.setText(f'{pick + 1}번부터 입자 → 크기 기준 {a * px * px:.2f} µm² ({a} px, 반치 면적).')
        self.next_btn.setEnabled(pick is not None)
        self.brighter.setText('더 밝은 후보' if self.step == 0 else '더 큰 후보')
        self.fainter.setText('더 흐린 후보' if self.step == 0 else '더 작은 후보')

    def choose(self, i):
        if i >= len(self.shown):
            return
        if self.step == 0:
            self.pick_b = i
        else:
            self.pick_s = i
        self._fill_tiles()
        self._draw_boxes()

    def criterion(self) -> dict:
        px = self.item.pixel_um or pdt.DEFAULT_PX_UM
        k = self.shown_b[self.pick_b]['snr'] * 0.98
        area = self.shown_s[self.pick_s]['area'] * px * px if self.pick_s is not None else 0.0
        scope = next(k_ for k_, r in self.scope.items() if r.isChecked())
        return dict(k=round(float(k), 3), area=round(float(area), 4), scope=scope,
                    channel=self.item.channels[self.c], group=self.item.group or '',
                    image=self.item.image_id, date=datetime.date.today().isoformat())

    def _apply_page(self):
        from dataclasses import replace
        crit = self.criterion()
        px = self.item.pixel_um or pdt.DEFAULT_PX_UM
        b = self.shown_b[self.pick_b]
        self.k_lab.setText(f'≥ {crit["k"]:.1f}σ  (고른 {self.pick_b + 1}번 {b["snr"]:.1f}σ를 겨우 잡는 값)')
        self.a_lab.setText(f'≥ {crit["area"]:.2f} µm²  ({crit["area"] / (px * px):.0f} px)')
        s = replace(self.panel.settings(), method='auto', crit_k=crit['k'], crit_area=crit['area'])
        self.n_after = self._count(s)
        self.n_lab.setText(f'입자 {self.n_before}개 → {self.n_after}개')
        ch = self.item.channels[self.c]
        same = [o for o in self.win.items if ch in o.channels]
        grp = [o for o in same if (o.group or '') == (self.item.group or '')]
        self.scope['all'].setText(f'모든 이미지 (같은 채널 이름 {ch}, {len(same)}개)')
        self.scope['group'].setText(f'같은 그룹만 ({self.item.group or "그룹 없음"}, {len(grp)}개)')
        self.scope['group'].setEnabled(bool(self.item.group))

    def next(self):
        if self.step == 0 and self.pick_b is not None:
            self.show_step(1)
        elif self.step == 1 and self.pick_s is not None:
            self.shown_s = self.shown
            self.show_step(2)
        elif self.step == 2:
            self.close_page(self.criterion())

    def back(self):
        if self.step > 0:
            self.show_step(self.step - 1)

    def close_page(self, crit):
        self._clear_boxes()
        self.finished.emit(crit)

    # ---- canvas boxes -------------------------------------------------------

    def _clear_boxes(self):
        sc = self.win.canvas.scene()
        for it in self._scene:
            sc.removeItem(it)
        self._scene = []

    def _draw_boxes(self):
        self._clear_boxes()
        if self.step >= 2:
            return
        sc = self.win.canvas.scene()
        pick = self.pick_b if self.step == 0 else self.pick_s
        for i, c in enumerate(self.shown):
            sel = i == pick
            pen = QPen(QColor(255, 220, 0) if sel else QColor(0, 220, 255))
            pen.setCosmetic(True)
            pen.setWidth(3 if sel else 2)
            pen.setStyle(Qt.PenStyle.SolidLine if sel else Qt.PenStyle.DashLine)
            r = QGraphicsRectItem(QRectF(c['x'] - BOX, c['y'] - BOX, 2 * BOX + 1, 2 * BOX + 1))
            r.setPen(pen)
            r.setZValue(12)
            t = QGraphicsSimpleTextItem(str(i + 1))
            t.setBrush(pen.color())
            t.setFlag(QGraphicsSimpleTextItem.GraphicsItemFlag.ItemIgnoresTransformations)
            font = t.font()
            font.setPointSize(14)
            font.setBold(True)
            t.setFont(font)
            t.setPos(c['x'] - BOX + 2, c['y'] - BOX + 2)
            t.setZValue(13)
            for it in (r, t):
                sc.addItem(it)
                self._scene.append(it)
