"""Graph window parts: PickerTile variant ``kind`` (KindCard / KindPicker), Segmented (RoleSwitch), PreviewBox, Steps (StepBar) and the group tree (Table variant tree)."""
from __future__ import annotations

from .graph_kinds import KINDS, _THUMBS

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QAbstractButton, QFrame, QGridLayout, QHBoxLayout, QTreeWidget, QVBoxLayout, QWidget
from .. import graph as G
from .. import theme


def thumb(kind) -> QIcon:
    """A small picture of the chart kind (same sample data for all)."""
    if kind in _THUMBS:
        return _THUMBS[kind]
    import numpy as np
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    fig = Figure(figsize=(1.5, 1.0), dpi=160)
    fig.patch.set_alpha(0)
    FigureCanvasAgg(fig)
    ax = fig.add_axes([0.08, 0.1, 0.88, 0.85])
    ax.set_facecolor('none')
    r = np.random.default_rng(1)
    data = [r.normal(m, 1.0, 12) for m in (4, 6, 4.6)]
    cs = ['#000000', '#d62728', '#1f77b4']
    if kind == 'xy':
        t = np.linspace(0, 10, 12)
        for c, a in zip(cs, (0.5, 0.75, 0.9)):
            ax.plot(t, a * (1 - np.exp(-t / 2.5)), '-o', color=c, ms=2.2, lw=1)
    elif kind == 'bar':
        ax.bar(range(3), [d.mean() for d in data], 0.6, color=cs, alpha=0.4, edgecolor=cs)
        for k, d in enumerate(data):
            ax.errorbar(k, d.mean(), d.std(), fmt='none', ecolor=cs[k], capsize=2, lw=0.8)
    elif kind == 'strip':
        for k, d in enumerate(data):
            ax.plot(k + r.uniform(-.2, .2, d.size), d, 'o', ms=2.2, color=cs[k])
            ax.hlines(d.mean(), k - .25, k + .25, color=cs[k], lw=1.4)
    elif kind == 'box':
        bp = ax.boxplot(data, widths=0.55, patch_artist=True, showfliers=False)
        for b, c in zip(bp['boxes'], cs):
            b.set(facecolor=c, alpha=0.35, edgecolor=c)
        for k in ('whiskers', 'caps', 'medians'):
            for ln in bp[k]:
                ln.set(color='#333', lw=0.8)
    elif kind == 'violin':
        vp = ax.violinplot(data, showextrema=False, showmedians=True)
        for b, c in zip(vp['bodies'], cs):
            b.set(facecolor=c, alpha=0.4, edgecolor=c)
        vp['cmedians'].set(color='#333', lw=0.8)
    elif kind == 'hist':
        for d, c in zip(data, cs):
            ax.hist(d, bins=8, color=c, alpha=0.4, histtype='stepfilled', edgecolor=c)
    else:
        ax.imshow(r.random((6, 9)) + np.linspace(0, 1, 9), cmap='magma', aspect='auto')
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    for s in ('left', 'bottom'):
        ax.spines[s].set_color('#888')
    fig.canvas.draw()
    buf = fig.canvas.buffer_rgba()
    from PySide6.QtGui import QImage

    h, w = int(fig.bbox.height), int(fig.bbox.width)
    img = QImage(bytes(buf), w, h, QImage.Format.Format_RGBA8888)
    _THUMBS[kind] = QIcon(QPixmap.fromImage(img.copy()))
    return _THUMBS[kind]


class KindCard(QAbstractButton):
    """One chart kind: thumbnail + name (+ description); checked = accent ring."""

    def __init__(self, key, name, desc, big=True, parent=None):
        super().__init__(parent)
        self.key, self.big, self.desc = key, big, desc
        self.recommended = False
        self.setCheckable(True)
        self.setAutoExclusive(True)
        self.setText(name)
        self.setToolTip(f'{name}: {desc}')
        self.isz = QSize(120, 80) if big else QSize(60, 40)
        self.setFixedSize(QSize(150, 158) if big else QSize(78, 70))
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, _e):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(1, 1, -1, -1)
        on = self.isChecked()
        if on:
            c = QColor(theme.color('blue'))
            c.setAlphaF(0.10)
            qp.setPen(QPen(theme.color('blue'), 2))
            qp.setBrush(c)
        else:
            qp.setPen(Qt.PenStyle.NoPen)
            qp.setBrush(theme.color('fill-tertiary'))
        qp.drawRoundedRect(r, 12, 12)
        isz = self.isz
        y = 10 if self.big else 5
        thumb(self.key).paint(qp, (self.width() - isz.width()) // 2, y, isz.width(), isz.height())
        f = QFont(self.font())
        f.setWeight(QFont.Weight.DemiBold if on else QFont.Weight.Medium)
        if not self.big:
            f.setPixelSize(10)
        qp.setFont(f)
        qp.setPen(theme.color('label'))
        ty = y + isz.height() + (6 if self.big else 2)
        qp.drawText(0, ty, self.width(), 20 if self.big else 16, Qt.AlignmentFlag.AlignHCenter, self.text())
        if self.big:
            f2 = QFont(self.font())
            f2.setPixelSize(11)
            qp.setFont(f2)
            qp.setPen(theme.color('label-secondary'))
            qp.drawText(6, ty + 20, self.width() - 12, 30,
                        Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap, self.desc)
            if self.recommended:
                f3 = QFont(self.font())
                f3.setPixelSize(10)
                f3.setWeight(QFont.Weight.DemiBold)
                qp.setFont(f3)
                qp.setPen(Qt.PenStyle.NoPen)
                qp.setBrush(theme.color('green'))
                qp.drawRoundedRect(self.width() - 42, 8, 34, 17, 8.5, 8.5)
                qp.setPen(QColor('white'))
                qp.drawText(self.width() - 42, 8, 34, 17, Qt.AlignmentFlag.AlignCenter, '추천')
        qp.end()


class KindPicker(QWidget):
    picked = Signal(str)

    def __init__(self, cols=4, big=True, parent=None):
        super().__init__(parent)
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(10 if big else 6)
        self.cards = {}
        for i, (k, n, d) in enumerate(KINDS):
            c = KindCard(k, n, d, big)
            c.clicked.connect(lambda _=False, k=k: self.picked.emit(k))
            g.addWidget(c, i // cols, i % cols)
            self.cards[k] = c
        g.setColumnStretch(cols, 1)

    def set_kind(self, k):
        c = self.cards.get(k)
        if c is not None and not c.isChecked():
            c.setChecked(True)

    def set_recommended(self, keys):
        for k, c in self.cards.items():
            c.recommended = k in keys
            c.update()


class RoleSwitch(QWidget):
    """범주 | 값 for one axis."""

    toggled = Signal(bool)  # True = 범주

    def __init__(self, parent=None):
        from ..hig_widgets import Chip

        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        h.addStretch()
        self.cat, self.val = Chip('범주', False), Chip('값', False)
        for c in (self.cat, self.val):
            c.setAutoExclusive(True)
            h.addWidget(c)
        self.cat.clicked.connect(lambda: self.toggled.emit(True))
        self.val.clicked.connect(lambda: self.toggled.emit(False))
        self.setToolTip('범주: 같은 값끼리 한 자리에 모읍니다 · 값: 숫자 눈금 위에 놓습니다')

    def set(self, cat: bool, value_ok=True):
        self.val.setEnabled(value_ok)
        self.val.setToolTip('' if value_ok else '글자 열은 범주로만 쓸 수 있습니다.')
        (self.cat if cat or not value_ok else self.val).setChecked(True)


class _GroupTree(QTreeWidget):
    reordered = Signal()

    def dropEvent(self, e):
        super().dropEvent(e)
        self.reordered.emit()


class Preview(QFrame):
    """A small drawing of a spec."""

    def __init__(self, w=3.2, h=2.6, parent=None):
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from matplotlib.figure import Figure

        super().__init__(parent)
        self.setObjectName('hig_content')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        self.fig = Figure(figsize=(w, h), dpi=100, layout='constrained')
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.canvas.setMinimumSize(int(w * 90), int(h * 90))
        lay.addWidget(self.canvas)

    def show_spec(self, spec, tables):
        try:
            sp = spec.copy()
            sp.plot_auto = True
            G.draw(self.fig, sp, tables)
        except Exception as exc:  # noqa: BLE001
            self.fig.clear()
            self.fig.text(0.5, 0.5, f'그릴 수 없습니다: {exc}', ha='center', va='center', wrap=True)
        self.canvas.draw_idle()


from .steps import StepBar  # noqa: E402,F401  (Steps, hig-steps)
