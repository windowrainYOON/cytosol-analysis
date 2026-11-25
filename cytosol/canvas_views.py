"""Canvas view modes (owner request 2026-11-24, pipeline design v3.10):
three exclusive icons at the canvas' top right, [라인 프로파일 · 단면 · 3D 투영].

* ``SectionView`` (단면): the XY plane of the current Z with the X section
  (XZ) below and the Y section (YZ) to the right, cut at the clicked point
  (Fiji Orthogonal Views); the three panels share one scale fitted to the
  canvas. White cut lines on XY, the current Z as a yellow dashed line on the
  sections; dragging the point moves the cuts, clicking a section moves Z.
* ``View3DPane`` (3D 투영): the whole canvas is the 3D view
  (``gl3d.make_volume_view``), with the pre-render chip (all timepoints of a
  series are prepared once, ``vol3d.VolumeCache``), the angle chip and ↺.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from . import gl3d, theme, vol3d
from .lut import add_colored

GAP = 10  # px between the three section panels
BLACK = QColor(0, 0, 0)
YELLOW = QColor(255, 214, 10)


def _rgb(planes, luts) -> np.ndarray:
    """(C, A, B) raw → (A, B, 3) uint8 with the LUTs (visible channels only)."""
    out = np.zeros(planes.shape[1:] + (3,), np.float32)
    for plane, lut in zip(planes, luts):
        if lut.visible:
            add_colored(out, lut.apply(plane), lut.color)
    return np.ascontiguousarray((np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8))


def _text(p: QPainter, pt: QPointF, text: str):
    """White text with a dark shadow, readable on bright and dark pixels."""
    pen = p.pen()
    p.setPen(QColor(0, 0, 0, 170))
    p.drawText(pt + QPointF(1, 1), text)
    p.setPen(pen)
    p.drawText(pt, text)


def _qimage(u8) -> QImage:
    h, w = u8.shape[:2]
    return QImage(u8.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


class SectionView(QWidget):
    """XY + X section (below) + Y section (right) of the current image."""
    zPicked = Signal(int)
    pointMoved = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.item = None
        self.stack = None  # (C, Z, Y, X) of the shown timepoint
        self._key = None
        self.point = None  # (x, y) image pixels
        self.zr = 1.0
        self.show_lines = True
        self._rects = None
        self._imgs = None
        self._drag = False
        self.mip = False  # XY panel = maximum over Z (the sections stay)
        self.scale_bars = True
        self.setMinimumSize(200, 160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(False)

    # ---- data ---------------------------------------------------------------

    def set_item(self, it, zr: float = 1.0):
        self.item = it
        self.zr = max(0.05, float(zr))
        if it is None:
            self.stack, self._key = None, None
            self.update()
            return
        key = (id(it), it.t)
        if key != self._key:
            self.stack = np.asarray(it.image.data)
            self._key = key
        _c, _nz, ny, nx = self.stack.shape
        if self.point is None or not (0 <= self.point[0] < nx and 0 <= self.point[1] < ny):
            self.point = (nx // 2, ny // 2)
        self.refresh()

    def set_point(self, x, y):
        if self.stack is None:
            return
        _c, _nz, ny, nx = self.stack.shape
        p = (int(np.clip(x, 0, nx - 1)), int(np.clip(y, 0, ny - 1)))
        if p != self.point:
            self.point = p
            self.pointMoved.emit(*p)
            self.refresh()

    def z(self) -> int:
        it = self.item
        nz = self.stack.shape[1] if self.stack is not None else 1
        z = it.z if it is not None and isinstance(getattr(it, 'z', None), int) else nz // 2
        return int(np.clip(z, 0, nz - 1))

    def planes(self):
        """(XY, XZ, YZ) raw planes: (C, Y, X), (C, Z, X), (C, Y, Z)."""
        s = self.stack
        x, y = self.point
        z = self.z()
        xy = s.max(axis=1) if self.mip else s[:, z]
        return xy, s[:, :, y, :], np.ascontiguousarray(s[:, :, :, x].transpose(0, 2, 1))

    def set_mip(self, on: bool):
        if bool(on) != self.mip:
            self.mip = bool(on)
            self.refresh()

    def pixel_um(self):
        try:
            v = float(self.item.pixel_um) if self.item is not None else 0.0
        except (TypeError, ValueError):
            return None
        return v if v > 0 else None

    def refresh(self):
        if self.stack is None or self.item is None:
            self._imgs = None
            self.update()
            return
        xy, xz, yz = self.planes()
        luts = self.item.luts
        self._imgs = (_qimage(_rgb(xy, luts)), _qimage(_rgb(xz, luts)), _qimage(_rgb(yz, luts)))
        self.update()

    # ---- geometry -----------------------------------------------------------

    def geometry_rects(self):
        """(xy, yz, xz) QRectF and the scale, the panels at one scale fitted to the view."""
        if self.stack is None:
            return None
        _c, nz, ny, nx = self.stack.shape
        dz = nz * self.zr
        w, h = self.width() - GAP, self.height() - GAP
        s = max(1e-3, min(w / (nx + dz), h / (ny + dz)))
        tw = (nx + dz) * s + GAP
        x0 = max(0.0, (self.width() - tw) / 2)
        xy = QRectF(x0, 0, nx * s, ny * s)
        yz = QRectF(x0 + nx * s + GAP, 0, dz * s, ny * s)
        xz = QRectF(x0, ny * s + GAP, nx * s, dz * s)
        return xy, yz, xz, s

    # ---- painting -------------------------------------------------------------

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        g = self.geometry_rects()
        if g is None or self._imgs is None:
            p.end()
            return
        xy, yz, xz, s = g
        self._rects = g
        nz = self.stack.shape[1]
        img_xy, img_xz, img_yz = self._imgs
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        for r, img in ((xy, img_xy), (yz, img_yz), (xz, img_xz)):
            p.fillRect(r, BLACK)
            p.drawImage(r, img)
        x, y = self.point
        z = self.z()
        px, py = xy.left() + (x + 0.5) * s, xy.top() + (y + 0.5) * s
        pz_yz = yz.left() + (z + 0.5) * self.zr * s
        pz_xz = xz.top() + (z + 0.5) * self.zr * s
        if self.show_lines:
            white = QPen(QColor(255, 255, 255, 220), 1)
            p.setPen(white)
            p.drawLine(QPointF(px, xy.top()), QPointF(px, xy.bottom()))
            p.drawLine(QPointF(xy.left(), py), QPointF(xy.right(), py))
            p.drawLine(QPointF(yz.left(), py), QPointF(yz.right(), py))
            p.drawLine(QPointF(px, xz.top()), QPointF(px, xz.bottom()))
        if not self.mip:  # the XY panel is no single Z in MIP
            dash = QPen(YELLOW, 1, Qt.PenStyle.DashLine)
            p.setPen(dash)
            p.drawLine(QPointF(pz_yz, yz.top()), QPointF(pz_yz, yz.bottom()))
            p.drawLine(QPointF(xz.left(), pz_xz), QPointF(xz.right(), pz_xz))
        p.setPen(QPen(QColor(40, 30, 0), 1))
        p.setBrush(YELLOW)
        p.drawEllipse(QPointF(px, py), 4.5, 4.5)
        # labels
        f = QFont(self.font())
        p.setFont(f)
        fm = p.fontMetrics()
        p.setPen(QColor(255, 255, 255))

        def label(r, title, sub):
            bold = QFont(f)
            bold.setBold(True)
            p.setFont(bold)
            _text(p, QPointF(r.left() + 8, r.top() + 6 + fm.ascent()), title)
            p.setFont(f)
            _text(p, QPointF(r.left() + 8, r.top() + 8 + fm.ascent() + fm.height()), sub)
        label(xy, 'XY', f'MIP · z 1–{nz}' if self.mip else f'z = {z + 1} / {nz}')
        label(yz, 'Y 단면', f'x = {x}')
        label(xz, 'X 단면', f'y = {y}')
        _text(p, QPointF(yz.right() - fm.horizontalAdvance('Z →') - 8, yz.bottom() - 8), 'Z →')
        _text(p, QPointF(xz.right() - fm.horizontalAdvance('Z ↓') - 8, xz.bottom() - 8), 'Z ↓')
        if self.scale_bars:
            um = self.pixel_um()
            if um:
                # µm per screen px is the same in every panel (one scale, Z in XY pixels)
                per_px = um / s
                self._scale_bar(p, xy, per_px, 0)
                self._scale_bar(p, yz, per_px, fm.horizontalAdvance('Z →') + 16)
                self._scale_bar(p, xz, per_px, fm.horizontalAdvance('Z ↓') + 16)
        p.end()

    def bar_length(self, r: QRectF, per_px: float, reserve: float = 0.0):
        """Scale bar of a panel: (µm, screen px), the largest nice length up to a
        third of the panel's free width, or None when nothing fits."""
        from .render import NICE_LENGTHS_UM
        nice = [0.1, 0.2] + list(NICE_LENGTHS_UM)
        room = min(r.width() / 3, r.width() - reserve - 16)
        fits = [v for v in nice if 6 <= v / per_px <= room]
        if not fits:
            return None
        return fits[-1], fits[-1] / per_px

    def _scale_bar(self, p: QPainter, r: QRectF, per_px: float, reserve: float):
        """White bar at the panel's lower left, its length above it (marker per panel)."""
        got = self.bar_length(r, per_px, reserve)
        if got is None:
            return
        um, w = got
        fm = p.fontMetrics()
        text = f'{um:g} µm'
        x0, y0 = r.left() + 8, r.bottom() - 8
        p.save()
        p.setPen(QPen(QColor(0, 0, 0, 160), 1))  # dark edge: visible on bright images too
        p.setBrush(QColor(255, 255, 255))
        p.drawRect(QRectF(x0, y0 - 3, w, 3))
        p.setPen(QColor(255, 255, 255))
        if r.height() >= fm.height() + 24:  # label above the bar
            tx = x0 + max(0.0, (w - fm.horizontalAdvance(text)) / 2)
            _text(p, QPointF(tx, y0 - 6), text)
        else:  # flat panel: label after the bar
            _text(p, QPointF(x0 + w + 6, y0), text)
        p.restore()

    # ---- mouse ----------------------------------------------------------------

    def _hit(self, pos):
        g = self._rects or self.geometry_rects()
        if g is None:
            return None, None
        xy, yz, xz, s = g
        if xy.contains(pos):
            return 'xy', ((pos.x() - xy.left()) / s, (pos.y() - xy.top()) / s)
        if yz.contains(pos):
            return 'yz', (pos.x() - yz.left()) / (s * self.zr)
        if xz.contains(pos):
            return 'xz', (pos.y() - xz.top()) / (s * self.zr)
        return None, None

    def mousePressEvent(self, ev):
        where, v = self._hit(ev.position())
        if where == 'xy':
            self._drag = True
            self.set_point(*v)
        elif where in ('yz', 'xz'):
            nz = self.stack.shape[1]
            self.zPicked.emit(int(np.clip(int(v), 0, nz - 1)))
        ev.accept()

    def mouseMoveEvent(self, ev):
        if not self._drag:
            return
        g = self._rects or self.geometry_rects()
        if g is None:
            return
        xy, _yz, _xz, s = g
        self.set_point((ev.position().x() - xy.left()) / s, (ev.position().y() - xy.top()) / s)

    def mouseReleaseEvent(self, ev):
        self._drag = False

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.update()


from .ui.page_stack import _ModePane  # noqa: E402,F401  (component library)


class SectionPane(_ModePane):
    def __init__(self, parent=None):
        super().__init__(SectionView(), '클릭: 그 점에서 자른 X 단면(아래) · Y 단면(오른쪽) · 점 끌기: 단면 위치 '
                         '옮기기 · Z 슬라이더 · 휠: XY 평면의 Z · 단면을 클릭하면 그 자리로 Z 이동', parent)
        self.view.pointMoved.connect(lambda *_: self._chips())
        # owner request (2026-11-24): the XY panel as MIP, the sections unchanged
        self.mip_check = QCheckBox('MIP')
        self.mip_check.setToolTip('XY 패널을 Z 최대 투영(MIP)으로 보기 · 오른쪽 · 아래 단면은 그대로')
        self.mip_check.toggled.connect(self._mip_toggled)
        # in the top row (design system: no controls on the bottom edge)
        self.top.insertWidget(1, self.mip_check)

    def _mip_toggled(self, on):
        self.view.set_mip(on)
        self._chips()

    def show_item(self, it, zr, auto_spacing, show_lines=True):
        self.view.show_lines = show_lines
        self.view.set_item(it, zr)
        self._chips(zr, auto_spacing)

    def _chips(self, zr=None, auto=None):
        v = self.view
        if v.point is None:
            return
        if zr is not None:
            self._zr_text = f'Z 간격 {zr:.3g} ({"자동" if auto else "수동"})'
        x, y = v.point
        z = 'MIP' if v.mip else v.z() + 1
        self.status.setText(f'단면 보기 · 클릭한 점 x {x} · y {y} · z {z}')
        self.right.setText(getattr(self, '_zr_text', ''))


class View3DPane(_ModePane):
    """3D 투영: pre-rendered volumes turned in real time."""
    gl_failed = Signal(str)

    def __init__(self, parent=None):
        view = gl3d.make_volume_view()
        super().__init__(view, '드래그: 3축 자유 회전 (트랙볼) · Shift+드래그: 화면 축(Z)만 · 가운데 드래그: 이동 · '
                         'Cmd/Ctrl+드래그: 확대 · 더블클릭: 처음 시점', parent)
        from .hig_widgets import IconButton
        self.reset_btn = IconButton('arrow.counterclockwise', '처음 시점으로 (더블클릭)')
        self.reset_btn.clicked.connect(lambda: self.view.reset_view())
        self.bottom.addWidget(self.reset_btn)
        self._wire(view)
        self.caches: dict[int, vol3d.VolumeCache] = {}
        self.item = None
        self.settings = vol3d.View3DSettings()
        self._shown = None
        self._timer = QTimer(self)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._poll)

    def _wire(self, view):
        view.turned.connect(self._angle_chip)
        if hasattr(view, 'failed'):
            view.failed.connect(self._fallback)

    def _fallback(self, msg):
        """The GPU path failed (driver, shader): the numpy renderer takes over."""
        old = self.view
        new = gl3d.CPUVolumeView()
        new.ball = old.ball
        lay = self.layout()
        lay.replaceWidget(old, new)
        old.setParent(None)
        old.deleteLater()
        self.view = new
        self._wire(new)
        self._shown = None
        self.gl_failed.emit(msg)
        self._poll()

    def backend(self) -> str:
        return getattr(self.view, 'backend', 'cpu')

    def cache(self, it) -> vol3d.VolumeCache:
        c = self.caches.get(id(it))
        if c is None or c.image is not it.image:
            c = self.caches[id(it)] = vol3d.VolumeCache(it.image)
        return c

    def forget(self, it):
        c = self.caches.pop(id(it), None)
        if c is not None:
            c.clear()

    def stop_all(self):
        for c in self.caches.values():
            c.stop()
        self._timer.stop()

    def show_item(self, it, settings: vol3d.View3DSettings, region=None, pixel_um=None):
        """Prepare (or reuse) the volumes of ``it`` and show its current timepoint."""
        self.item, self.settings = it, settings
        self.view.ball.one_axis = settings.rotation == 'axis'
        self.view.set_method(settings.method, settings.surface_level)
        if it is None:
            self.view.set_volume(None, [], [])
            return
        zr = vol3d.z_ratio(it.image, settings, pixel_um)
        self._zr = zr
        c = self.cache(it)
        c.start(it.t, it.luts, settings.resolution, zr, region,
                settings.memory_gb, sync_first=False)
        self._shown = None
        self._timer.start()
        self._poll()
        self._angle_chip()

    def colors(self):
        it = self.item
        return [tuple(lut.color) for lut in it.luts], [bool(lut.visible) for lut in it.luts]

    def _poll(self):
        it = self.item
        if it is None:
            self._timer.stop()
            return
        c = self.cache(it)
        vol = c.get(it.t)
        cols, vis = self.colors()
        key = (id(vol) if vol is not None else None, tuple(cols), tuple(vis))
        if vol is not None and key != self._shown:
            self.view.set_volume(np.asarray(vol), cols, vis)
            self._shown = key
        d, n = c.progress()
        done = d >= n and not c.running()
        self.status.set_kind('error' if c.error else ('success' if done else 'info'))
        text = c.chip()
        if done and not c.error:
            text += ' · 드래그하면 실시간 회전'
        if vol is None and not c.error:
            text = ('고화질 렌더 중 · 이 시점 준비하는 중…' if n == 1 else text + ' · 이 시점 준비하는 중…')
        self.status.setText(text)
        if done or c.error:
            if vol is not None or c.error:
                self._timer.stop()

    def colors_changed(self):
        self._poll()

    def _angle_chip(self):
        self.right.setText(self.view.ball.chip())

    def wait(self, timeout=120.0):
        """Block until the current item is fully prepared (self-test)."""
        import time
        from PySide6.QtWidgets import QApplication
        it = self.item
        if it is None:
            return
        c = self.cache(it)
        end = time.time() + timeout
        while (c.running() or c.get(it.t) is None) and time.time() < end and not c.error:
            QApplication.processEvents()
            time.sleep(0.02)
        self._poll()
