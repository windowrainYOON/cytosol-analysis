"""3D 투영 view on the canvas (v0.73): GPU ray marching with a CPU fallback.

``make_volume_view`` returns a ``GLVolumeView`` (offscreen GL context + FBO read back into a plain widget, a 3D
texture ray-marching shader: MIP / emission-absorption / surface) when an
OpenGL 3.3+ context can be made, else a ``CPUVolumeView`` that paints
``vol3d.render_cpu`` images (reduced while dragging, exact once released).
Both take the prepared uint8 volume from ``vol3d.VolumeCache`` and keep their
rotation in a ``vol3d.Trackball``; a new timepoint only uploads that volume.
"""

from __future__ import annotations

import os
import threading
import traceback

import numpy as np
from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QSurfaceFormat
from PySide6.QtWidgets import QWidget

from . import vol3d

_GL_OK: bool | None = None


def gl_available() -> bool:
    """True when an OpenGL 3.3 core context can be made (never offscreen)."""
    global _GL_OK
    if _GL_OK is not None:
        return _GL_OK
    _GL_OK = False
    if os.environ.get('CYTOSOL_NO_GL'):
        return False
    try:
        from PySide6.QtGui import QGuiApplication, QOffscreenSurface, QOpenGLContext

        if QGuiApplication.platformName() in ('offscreen', 'minimal'):
            return False
        import OpenGL.GL  # noqa: F401  (PyOpenGL)

        ctx = QOpenGLContext()
        ctx.setFormat(_format())
        if not ctx.create():
            return False
        surf = QOffscreenSurface()
        surf.setFormat(ctx.format())
        surf.create()
        ok = ctx.makeCurrent(surf)
        fmt = ctx.format()
        ok = ok and (fmt.majorVersion(), fmt.minorVersion()) >= (3, 3)
        ctx.doneCurrent()
        _GL_OK = bool(ok)
    except Exception:  # noqa: BLE001
        _GL_OK = False
    return _GL_OK


def _format() -> QSurfaceFormat:
    f = QSurfaceFormat()
    f.setVersion(4, 1)  # macOS core profile; Mesa / Windows give 4.1+ as well
    f.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    f.setDepthBufferSize(0)
    return f


VERT = """#version 410 core
out vec2 vPix;
uniform vec2 viewport;
void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
    vPix = vec2(p.x * viewport.x, (1.0 - p.y) * viewport.y);
}
"""

FRAG = """#version 410 core
in vec2 vPix;
out vec4 frag;
uniform sampler3D vol0;
uniform sampler3D vol1;
uniform int nch;
uniform vec3 colors[8];
uniform mat3 Rt;
uniform vec3 ext;
uniform vec2 viewport;
uniform float zoom;
uniform vec2 pan;
uniform int method;
uniform float level;
uniform float stepv;
uniform vec3 bg;

float chan(vec3 tc, int i) {
    vec4 a = texture(vol0, tc);
    if (i < 4) return a[i];
    vec4 b = texture(vol1, tc);
    return b[i - 4];
}

void main() {
    float diag = length(ext);
    float scale = diag / (min(viewport.x, viewport.y) * zoom);
    vec2 uv = (vPix - 0.5 * (viewport - 1.0) - pan) * scale;
    vec3 centre = 0.5 * (ext - 1.0);
    vec3 o = Rt * vec3(uv, 0.0) + centre;
    vec3 d = Rt * vec3(0.0, 0.0, 1.0);
    vec3 lo = vec3(-0.5), hi = ext - 0.5;
    vec3 dd = mix(d, vec3(1e-6), lessThan(abs(d), vec3(1e-6)));
    vec3 inv = 1.0 / dd;
    vec3 t0 = (lo - o) * inv, t1 = (hi - o) * inv;
    vec3 tmn = min(t0, t1), tmx = max(t0, t1);
    float tn = max(max(tmn.x, tmn.y), tmn.z);
    float tf = min(min(tmx.x, tmx.y), tmx.z);
    if (tf <= tn) { frag = vec4(bg, 1.0); return; }
    vec3 acc = vec3(0.0);
    float mx[8];
    for (int i = 0; i < 8; i++) mx[i] = 0.0;
    float trans = 1.0;
    bool hit = false;
    int n = int(ceil((tf - tn) / stepv));
    for (int k = 0; k < 4096; k++) {
        if (k >= n) break;
        float t = tn + (float(k) + 0.5) * stepv;
        vec3 p = o + d * t;
        vec3 tc = (p + 0.5) / ext;
        if (method == 0) {
            for (int i = 0; i < nch; i++) mx[i] = max(mx[i], chan(tc, i));
        } else if (method == 1) {
            vec3 c = vec3(0.0);
            float a = 0.0;
            for (int i = 0; i < nch; i++) {
                float v = chan(tc, i);
                c += colors[i] * v;
                a = max(a, v * dot(colors[i], vec3(1.0)) > 0.0 ? v : 0.0);
            }
            a = clamp(a * 0.08 * stepv * 2.0, 0.0, 1.0);
            acc += trans * a * c * 4.0;
            trans *= 1.0 - a;
            if (trans < 0.01) break;
        } else {
            float v = 0.0;
            vec3 c = vec3(0.0);
            for (int i = 0; i < nch; i++) {
                float vi = chan(tc, i);
                if (dot(colors[i], vec3(1.0)) > 0.0 && vi > v) { v = vi; c = colors[i]; }
            }
            if (v >= level) {
                float e = 1.0;
                vec3 g = vec3(
                    chan(tc + vec3(e, 0, 0) / ext, 0) - chan(tc - vec3(e, 0, 0) / ext, 0),
                    chan(tc + vec3(0, e, 0) / ext, 0) - chan(tc - vec3(0, e, 0) / ext, 0),
                    chan(tc + vec3(0, 0, e) / ext, 0) - chan(tc - vec3(0, 0, e) / ext, 0));
                float shade = 0.45;
                if (length(g) > 1e-4) shade = 0.3 + 0.7 * abs(dot(normalize(g), d));
                float depth = 1.0 - (t - tn) / max(tf - tn, 1e-3);
                acc = c * shade * (0.55 + 0.45 * depth);
                hit = true;
                break;
            }
        }
    }
    if (method == 0) {
        for (int i = 0; i < nch; i++) acc += colors[i] * mx[i];
    }
    float cover = method == 0 ? clamp(max(max(acc.r, acc.g), acc.b) * 4.0, 0.0, 1.0)
                : (method == 1 ? 1.0 - trans : (hit ? 1.0 : 0.0));
    frag = vec4(clamp(acc + bg * (1.0 - cover), 0.0, 1.0), 1.0);
}
"""

METHOD_INDEX = {'mip': 0, 'alpha': 1, 'surface': 2}


class _Interaction:
    """Mouse handling shared by both views (drag = trackball, Shift = screen
    axis, middle = pan, Cmd/Ctrl = zoom, double click = reset)."""

    def _init_interaction(self):
        self.ball = vol3d.Trackball()
        self._last = None
        self._mode = None
        self.setMouseTracking(False)

    def mousePressEvent(self, ev):
        self._last = ev.position()
        mods = ev.modifiers()
        if ev.button() == Qt.MouseButton.MiddleButton:
            self._mode = 'pan'
        elif mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier):
            self._mode = 'zoom'
        elif ev.button() == Qt.MouseButton.LeftButton:
            self._mode = 'screen' if mods & Qt.KeyboardModifier.ShiftModifier else 'turn'
        else:
            self._mode = None
        self._drag_begin()
        ev.accept()

    def mouseMoveEvent(self, ev):
        if self._last is None or self._mode is None:
            return
        p = ev.position()
        dx, dy = p.x() - self._last.x(), p.y() - self._last.y()
        self._last = p
        b = self.ball
        if self._mode == 'pan':
            b.pan = (b.pan[0] + dx, b.pan[1] + dy)
        elif self._mode == 'zoom':
            b.zoom = float(np.clip(b.zoom * (1.0 - dy * 0.01), 0.1, 20))
        else:
            b.drag(dx, dy, screen_axis=self._mode == 'screen')
        self.turned.emit()
        self._redraw(fast=True)
        ev.accept()

    def mouseReleaseEvent(self, ev):
        self._last, self._mode = None, None
        self._drag_end()
        ev.accept()

    def mouseDoubleClickEvent(self, ev):
        self.reset_view()

    def reset_view(self):
        self.ball.reset()
        self.turned.emit()
        self._redraw(fast=False)

    def _drag_begin(self):
        pass

    def _drag_end(self):
        self._redraw(fast=False)


def _bg_rgb(widget) -> tuple[float, float, float]:
    """The view's background: black like the image letterbox of the mockups."""
    return tuple(getattr(widget, 'bg', (0.0, 0.0, 0.0)))


class CPUVolumeView(_Interaction, QWidget):
    """numpy fallback: reduced image while turning, exact image after."""
    turned = Signal()
    _exact_ready = Signal(int, object)
    backend = 'cpu'

    def __init__(self, parent=None):
        QWidget.__init__(self, parent)
        self._init_interaction()
        self.vol = None
        self.colors, self.visible = [], []
        self.method, self.level = 'mip', 0.35
        self.image: QImage | None = None
        self._gen = 0
        self._exact_ready.connect(self._got_exact)
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.setInterval(120)
        self._idle.timeout.connect(lambda: self._redraw(fast=False))
        self.last_ms = 0.0

    def set_volume(self, vol, colors, visible):
        self.vol, self.colors, self.visible = vol, list(colors), list(visible)
        self._redraw(fast=False)

    def set_method(self, method, level=0.35):
        self.method, self.level = method, level
        self._redraw(fast=False)

    def _render(self, fast):
        w, h = max(8, self.width()), max(8, self.height())
        if fast:
            f = max(1.0, max(w, h) / 220)
            w, h = int(w / f), int(h / f)
        b = self.ball
        rgb = vol3d.render_cpu(self.vol, b.R, (w, h), self.method, self.visible, self.colors,
                               b.zoom, (b.pan[0] * w / max(1, self.width()),
                                        b.pan[1] * h / max(1, self.height())),
                               level=self.level, fast=fast)
        return rgb

    def render_now(self) -> np.ndarray | None:
        """Exact RGB of the current view (self-test, exports)."""
        if self.vol is None:
            return None
        return self._render(False)

    def _redraw(self, fast=False):
        if self.vol is None:
            self.image = None
            self.update()
            return
        import time

        self._gen += 1
        if fast:
            t0 = time.perf_counter()
            self._set_rgb(self._render(True))
            self.last_ms = (time.perf_counter() - t0) * 1000
            self._idle.start()
            return
        gen = self._gen
        vol, R = self.vol, self.ball.R.copy()

        def work():
            try:
                rgb = self._render(False)
            except Exception:  # noqa: BLE001
                traceback.print_exc()
                return
            self._exact_ready.emit(gen, rgb)
        if self.image is None:
            work_rgb = self._render(True)
            self._set_rgb(work_rgb)
        del vol, R
        threading.Thread(target=work, daemon=True).start()

    def _got_exact(self, gen, rgb):
        if gen == self._gen:
            self._set_rgb(rgb)

    def _set_rgb(self, rgb):
        bg = np.array(_bg_rgb(self), np.float32)
        a = np.clip(rgb.max(axis=2, keepdims=True) * 4, 0, 1)
        rgb = rgb + bg * (1 - a)
        u8 = np.ascontiguousarray((np.clip(rgb, 0, 1) * 255 + 0.5).astype(np.uint8))
        h, w = u8.shape[:2]
        self._buf = u8
        self.image = QImage(u8.data, w, h, 3 * w, QImage.Format.Format_RGB888)
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor.fromRgbF(*_bg_rgb(self)))
        if self.image is not None:
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            p.drawImage(self.rect(), self.image)
        p.end()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self.vol is not None:
            self._idle.start()


def _gl_view_class():
    from OpenGL import GL
    from PySide6.QtGui import QOffscreenSurface, QOpenGLContext
    from PySide6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat

    class GLVolumeView(_Interaction, QWidget):
        """GPU ray marching of the prepared volume (one upload per timepoint).

        v0.74 (owner report 2026-11-24: the 3D view showed a shrunken, mirrored
        copy of the whole window): it no longer is a QOpenGLWidget. On macOS the
        window's compositor context could not share with the widget's 4.1 core
        context ("Could not create NSOpenGLContext with shared context"), so the
        compositor drew whatever texture had the widget's texture name: the
        window's own backing store. Now the view renders in its own offscreen
        context into a framebuffer object, reads the pixels back and paints them
        as an image in a plain widget: no context sharing, no GL composition of
        the window (Liquid Glass and the other widgets stay as they are)."""
        turned = Signal()
        failed = Signal(str)
        backend = 'gl'

        def __init__(self, parent=None):
            QWidget.__init__(self, parent)
            self._init_interaction()
            self.vol = None
            self.colors, self.visible = [], []
            self.method, self.level = 'mip', 0.35
            self.prog = None
            self.tex = []
            self.vao = None
            self._pending = None
            self._fast = False
            self.error = None
            self.image: QImage | None = None
            self.last_ms = 0.0
            self._fbo = None
            self.ctx = QOpenGLContext()
            self.ctx.setFormat(_format())
            if not self.ctx.create():
                raise RuntimeError('OpenGL context')
            self.surf = QOffscreenSurface()
            self.surf.setFormat(self.ctx.format())
            self.surf.create()
            if not self.ctx.makeCurrent(self.surf):
                raise RuntimeError('OpenGL makeCurrent')
            try:
                self.prog = self._program()
                self.vao = GL.glGenVertexArrays(1)
            finally:
                self.ctx.doneCurrent()
            self._timer = QTimer(self)
            self._timer.setSingleShot(True)
            self._timer.setInterval(0)
            self._timer.timeout.connect(self._render_now_cb)
            self._idle = QTimer(self)
            self._idle.setSingleShot(True)
            self._idle.setInterval(150)
            self._idle.timeout.connect(lambda: self._redraw(fast=False))

        # --- data ------------------------------------------------------------

        def set_volume(self, vol, colors, visible):
            same = vol is self.vol
            self.vol, self.colors, self.visible = vol, list(colors), list(visible)
            if not same:
                self._pending = vol
            self._redraw(fast=False)

        def set_method(self, method, level=0.35):
            self.method, self.level = method, level
            self._redraw(fast=False)

        def _redraw(self, fast=False):
            self._fast = fast
            if self.vol is None:
                self.image = None
                self.update()
                return
            self._timer.start()  # coalesce several moves into one frame
            if fast:
                self._idle.start()

        def _render_now_cb(self):
            img = self._render(self._fast)
            if img is not None:
                self.image = img
            self.update()

        # --- GL --------------------------------------------------------------

        def _program(self):
            def sh(kind, src):
                s = GL.glCreateShader(kind)
                GL.glShaderSource(s, src)
                GL.glCompileShader(s)
                if not GL.glGetShaderiv(s, GL.GL_COMPILE_STATUS):
                    raise RuntimeError(GL.glGetShaderInfoLog(s).decode(errors='replace'))
                return s
            p = GL.glCreateProgram()
            GL.glAttachShader(p, sh(GL.GL_VERTEX_SHADER, VERT))
            GL.glAttachShader(p, sh(GL.GL_FRAGMENT_SHADER, FRAG))
            GL.glLinkProgram(p)
            if not GL.glGetProgramiv(p, GL.GL_LINK_STATUS):
                raise RuntimeError(GL.glGetProgramInfoLog(p).decode(errors='replace'))
            return p

        def _upload(self, vol):
            if self.tex:
                GL.glDeleteTextures(self.tex)
            self.tex = []
            c, nz, ny, nx = vol.shape
            GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
            for k in range(2 if c > 4 else 1):
                pack = np.zeros((nz, ny, nx, 4), np.uint8)
                for j in range(4):
                    if 4 * k + j < c:
                        pack[..., j] = vol[4 * k + j]
                tid = GL.glGenTextures(1)
                GL.glBindTexture(GL.GL_TEXTURE_3D, tid)
                for p in (GL.GL_TEXTURE_WRAP_S, GL.GL_TEXTURE_WRAP_T, GL.GL_TEXTURE_WRAP_R):
                    GL.glTexParameteri(GL.GL_TEXTURE_3D, p, GL.GL_CLAMP_TO_EDGE)
                GL.glTexParameteri(GL.GL_TEXTURE_3D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
                GL.glTexParameteri(GL.GL_TEXTURE_3D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
                GL.glTexImage3D(GL.GL_TEXTURE_3D, 0, GL.GL_RGBA8, nx, ny, nz, 0, GL.GL_RGBA,
                                GL.GL_UNSIGNED_BYTE, np.ascontiguousarray(pack))
                self.tex.append(tid)

        def _size(self, fast):
            dpr = self.devicePixelRatioF() or 1.0
            w, h = max(8, self.width()), max(8, self.height())
            f = dpr
            if fast:  # while turning: a lighter frame, the exact one follows
                f = min(dpr, max(0.35, 700 / max(w, h)))
            return max(8, int(w * f)), max(8, int(h * f)), f

        def _render(self, fast) -> QImage | None:
            if self.prog is None or self.vol is None:
                return None
            import time

            t0 = time.perf_counter()
            w, h, scale = self._size(fast)
            if not self.ctx.makeCurrent(self.surf):
                self._fail('OpenGL makeCurrent')
                return None
            try:
                if self._fbo is None or self._fbo.width() != w or self._fbo.height() != h:
                    fmt = QOpenGLFramebufferObjectFormat()
                    fmt.setAttachment(QOpenGLFramebufferObject.Attachment.NoAttachment)
                    self._fbo = QOpenGLFramebufferObject(w, h, fmt)
                if self._pending is not None:
                    self._upload(self._pending)
                    self._pending = None
                self._fbo.bind()
                bg = _bg_rgb(self)
                GL.glViewport(0, 0, w, h)
                GL.glClearColor(bg[0], bg[1], bg[2], 1.0)
                GL.glClear(GL.GL_COLOR_BUFFER_BIT)
                self._draw(bg, w, h, scale)
                GL.glFinish()
                img = self._fbo.toImage().convertToFormat(QImage.Format.Format_RGB888)
                self._fbo.release()
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                self.ctx.doneCurrent()
                self._fail(str(exc))
                return None
            self.ctx.doneCurrent()
            self.last_ms = (time.perf_counter() - t0) * 1000
            return img

        def _fail(self, msg):
            self.error = msg
            self.prog = None
            QTimer.singleShot(0, lambda: self.failed.emit(self.error))

        def _draw(self, bg, w, h, scale):
            c, nz, ny, nx = self.vol.shape
            p = self.prog
            GL.glUseProgram(p)
            u = lambda n: GL.glGetUniformLocation(p, n)  # noqa: E731
            GL.glUniform2f(u('viewport'), w, h)
            GL.glUniform1i(u('nch'), min(c, 8))
            cols = []
            for i in range(8):
                on = i < c and i < len(self.visible) and self.visible[i]
                cols += list(self.colors[i]) if on else [0.0, 0.0, 0.0]
            GL.glUniform3fv(u('colors'), 8, np.array(cols, np.float32))
            Rt = np.asarray(self.ball.R, np.float32).T
            GL.glUniformMatrix3fv(u('Rt'), 1, GL.GL_TRUE, np.ascontiguousarray(Rt))
            GL.glUniform3f(u('ext'), nx, ny, nz)
            GL.glUniform1f(u('zoom'), self.ball.zoom)
            GL.glUniform2f(u('pan'), self.ball.pan[0] * scale, self.ball.pan[1] * scale)
            GL.glUniform1i(u('method'), METHOD_INDEX.get(self.method, 0))
            GL.glUniform1f(u('level'), self.level)
            GL.glUniform1f(u('stepv'), 1.0 if self._fast else 0.5)
            GL.glUniform3f(u('bg'), *bg)
            for k, tid in enumerate(self.tex):
                GL.glActiveTexture(GL.GL_TEXTURE0 + k)
                GL.glBindTexture(GL.GL_TEXTURE_3D, tid)
            GL.glUniform1i(u('vol0'), 0)
            GL.glUniform1i(u('vol1'), 1 if len(self.tex) > 1 else 0)
            GL.glBindVertexArray(self.vao)
            GL.glDrawArrays(GL.GL_TRIANGLES, 0, 3)
            GL.glBindVertexArray(0)
            GL.glActiveTexture(GL.GL_TEXTURE0)
            GL.glUseProgram(0)

        def render_now(self) -> np.ndarray | None:
            """Exact RGB of the current view, read back from the GPU."""
            if self.vol is None:
                return None
            self._fast = False
            img = self._render(False)
            if img is None:
                return None
            self.image = img
            w, h = img.width(), img.height()
            arr = np.frombuffer(img.constBits(), np.uint8, img.bytesPerLine() * h)
            arr = arr.reshape(h, img.bytesPerLine())[:, :3 * w].reshape(h, w, 3)
            return arr.astype(np.float32) / 255

        def paintEvent(self, _ev):
            p = QPainter(self)
            p.fillRect(self.rect(), QColor.fromRgbF(*_bg_rgb(self)))
            if self.image is not None:
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
                p.drawImage(self.rect(), self.image)
            p.end()

        def resizeEvent(self, ev):
            super().resizeEvent(ev)
            if self.vol is not None:
                self._redraw(fast=False)

        def _drag_end(self):
            self._idle.stop()
            self._redraw(fast=False)

        def closeEvent(self, ev):
            self._release_gl()
            super().closeEvent(ev)

        def _release_gl(self):
            try:
                if self.ctx.makeCurrent(self.surf):
                    if self.tex:
                        GL.glDeleteTextures(self.tex)
                    self.tex = []
                    self._fbo = None
                    self.ctx.doneCurrent()
            except Exception:  # noqa: BLE001
                pass

    return GLVolumeView


def make_volume_view(parent=None, prefer_gl: bool = True):
    if prefer_gl and gl_available():
        try:
            return _gl_view_class()(parent)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
    return CPUVolumeView(parent)


class Chip(QWidget):
    """Small capsule label drawn over the view (progress, angles)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.text = ''
        self.frac = None
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set(self, text, frac=None):
        self.text, self.frac = text, frac
        fm = self.fontMetrics()
        w = fm.horizontalAdvance(text) + 24
        self.setFixedSize(w, fm.height() + 10 + (4 if frac is not None else 0))
        self.setVisible(bool(text))
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pal = self.palette()
        base = QColor(pal.window().color())
        base.setAlpha(225)
        r = self.rect().adjusted(0, 0, -1, -1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(base)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.setPen(pal.windowText().color())
        fm = self.fontMetrics()
        p.drawText(QPointF(12, 5 + fm.ascent()), self.text)
        if self.frac is not None:
            y = r.bottom() - 4
            p.setPen(Qt.PenStyle.NoPen)
            track = QColor(pal.windowText().color())
            track.setAlpha(40)
            p.setBrush(track)
            p.drawRoundedRect(12, y, r.width() - 24, 3, 1.5, 1.5)
            p.setBrush(pal.highlight())
            p.drawRoundedRect(12, y, int((r.width() - 24) * max(0.0, min(1.0, self.frac))), 3, 1.5, 1.5)
        p.end()
