"""SettingsCard variant ``channel``: one channel of the LUT tab (visible, colour, histogram, Min / Max / gamma) and the shared channel row."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QCheckBox, QColorDialog, QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget
from .. import theme
from .color_well import ColorWell
from ..lut import ImageItem
from .histogram import Histogram, qcolor


SLIDER_STEPS = 1000


class ChannelPanel(QGroupBox):
    """Visible / color / min / max / gamma for one channel."""

    changed = Signal()
    applyAll = Signal(int)

    def __init__(self, index: int):
        super().__init__()
        self.index = index
        self.item: ImageItem | None = None
        self._busy = False
        self.lo, self.hi = 0.0, 1.0
        self.steps = SLIDER_STEPS

        # placed in the shared row under the LUT section title (see visibility_row)
        self.visible = theme.chip(QCheckBox())
        self.visible.setToolTip('이 채널을 미리보기와 내보내기 합성 이미지에 표시')
        self.color_btn = ColorWell(None, variant='header', pick=False)
        self.auto_btn = QPushButton('Auto')
        self.reset_btn = QPushButton('Min/Max')
        self.reset_btn.setToolTip('현재 이미지 데이터의 최소값~최대값으로 설정')
        self.all_btn = QPushButton('전체 이미지에 적용')
        self.all_btn.setToolTip('이 채널의 LUT를 모든 이미지의 같은 채널에 적용')

        self.hist = Histogram('lut', editable=True)
        self.range_lo = QLabel()
        self.range_hi = QLabel()
        self.range_note = QLabel()
        for lab in (self.range_lo, self.range_hi, self.range_note):
            theme.hint(lab)
        self.range_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.min_slider = QSlider(Qt.Orientation.Horizontal)
        self.max_slider = QSlider(Qt.Orientation.Horizontal)
        for s in (self.min_slider, self.max_slider):
            s.setRange(0, SLIDER_STEPS)
        self.min_spin = QDoubleSpinBox()
        self.max_spin = QDoubleSpinBox()
        for s in (self.min_spin, self.max_spin):
            s.setDecimals(4)
            s.setRange(-1e9, 1e9)
            s.setKeyboardTracking(False)
        self.gamma = QDoubleSpinBox()
        self.gamma.setRange(0.1, 5.0)
        self.gamma.setSingleStep(0.1)
        self.gamma.setValue(1.0)

        top = QHBoxLayout()
        top.addWidget(self.color_btn)
        top.addStretch()
        top.addWidget(self.auto_btn)
        top.addWidget(self.reset_btn)

        form = QFormLayout()
        form.addRow('Min', theme.slider_field(self.min_slider, self.min_spin))
        form.addRow('Max', theme.slider_field(self.max_slider, self.max_spin))
        form.addRow('Gamma', self.gamma)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.hist)
        scale = QHBoxLayout()
        scale.setContentsMargins(0, 0, 0, 0)
        scale.addWidget(self.range_lo)
        scale.addWidget(self.range_note, 1)
        scale.addWidget(self.range_hi)
        lay.addLayout(scale)
        lay.addLayout(form)
        lay.addWidget(self.all_btn)

        self.visible.toggled.connect(self._from_widgets)
        self.min_slider.valueChanged.connect(lambda v: self._slider(self.min_spin, v))
        self.max_slider.valueChanged.connect(lambda v: self._slider(self.max_spin, v))
        self.min_spin.valueChanged.connect(self._from_widgets)
        self.max_spin.valueChanged.connect(self._from_widgets)
        self.gamma.valueChanged.connect(self._from_widgets)
        self.color_btn.clicked.connect(self._pick_color)
        self.auto_btn.clicked.connect(self._auto)
        self.reset_btn.clicked.connect(self._full)
        self.all_btn.clicked.connect(lambda: self.applyAll.emit(self.index))
        self.hist.rangeEdited.connect(self._from_hist)  # ▲ handles ↔ Min / Max rows

    def _from_hist(self, vmin: float, vmax: float):
        """A dragged ▲ handle sets the Min / Max rows (which update the LUT)."""
        if self.item is None:
            return
        if vmin != self.min_spin.value():
            self.min_spin.setValue(vmin)
        if vmax != self.max_spin.value():
            self.max_spin.setValue(vmax)

    @property
    def lut(self):
        return self.item.luts[self.index]

    def bind(self, item: ImageItem):
        self.item = item
        plane = item.planes()[self.index]
        self.lo, self.hi, note = item.value_range(self.index)
        # integer data: one slider step per count when that is a sane number
        integer = bool(note) and note != 'RI' and float(self.lo).is_integer() \
            and float(self.hi).is_integer()
        span = self.hi - self.lo
        self.steps = int(span) if integer and 0 < span <= 1_000_000 else SLIDER_STEPS
        self._busy = True
        for s in (self.min_slider, self.max_slider):
            s.setRange(0, self.steps)
        for s in (self.min_spin, self.max_spin):
            s.setDecimals(0 if integer else 4)
            s.setRange(self.lo, self.hi)
            s.setSingleStep(1 if integer else span / 100)
        self._busy = False
        fmt = (lambda v: f'{v:.0f}') if integer else (lambda v: f'{v:.4f}')
        self.range_lo.setText(fmt(self.lo))
        self.range_hi.setText(fmt(self.hi))
        self.range_note.setText(f'파일 범위 ({note})' if note else '데이터 범위')
        self.setTitle(item.channels[self.index])
        self.visible.setText(item.channels[self.index])
        self.hist.set_data(plane, self.lo, self.hi)
        self.refresh()

    def refresh(self):
        """Push the LUT values into the widgets."""
        self._busy = True
        lut = self.lut
        self.visible.setChecked(lut.visible)
        self.min_spin.setValue(lut.vmin)
        self.max_spin.setValue(lut.vmax)
        self.min_slider.setValue(self._to_slider(lut.vmin))
        self.max_slider.setValue(self._to_slider(lut.vmax))
        self.gamma.setValue(lut.gamma)
        color = qcolor(lut.color).name()
        self.color_btn.setColor(color)
        swatch = QPixmap(16, 16)
        swatch.fill(QColor(color))
        qp = QPainter(swatch)
        qp.setPen(QPen(QColor('gray'), 1))
        qp.drawRect(0, 0, 15, 15)  # white channels stay visible on a light background
        qp.end()
        self.visible.setIcon(QIcon(swatch))
        self.hist.set_lut(lut.vmin, lut.vmax, lut.color)
        self._busy = False

    def _to_slider(self, v):
        return int(round((v - self.lo) / (self.hi - self.lo) * self.steps))

    def _from_slider(self, s):
        return self.lo + s / self.steps * (self.hi - self.lo)

    def _slider(self, spin, value):
        if self._busy:
            return
        spin.setValue(self._from_slider(value))

    def _from_widgets(self, *_):
        if self._busy or self.item is None:
            return
        lut = self.lut
        lut.visible = self.visible.isChecked()
        lut.vmin = self.min_spin.value()
        lut.vmax = self.max_spin.value()
        lut.gamma = self.gamma.value()
        self._busy = True
        self.min_slider.setValue(self._to_slider(lut.vmin))
        self.max_slider.setValue(self._to_slider(lut.vmax))
        self._busy = False
        self.hist.set_lut(lut.vmin, lut.vmax, lut.color)
        self.changed.emit()

    def _pick_color(self):
        c = QColorDialog.getColor(qcolor(self.lut.color), self, '채널 색상')
        if c.isValid():
            self.lut.color = (c.redF(), c.greenF(), c.blueF())
            self.refresh()
            self.changed.emit()

    def _auto(self):
        self.item.auto_lut(self.index)
        self.refresh()
        self.changed.emit()

    def _full(self):
        plane = self.item.planes()[self.index]
        lo, hi = float(np.nanmin(plane)), float(np.nanmax(plane))
        self.lut.vmin, self.lut.vmax = lo, (hi if hi > lo else self.hi)
        self.refresh()
        self.changed.emit()


class VisibilityRow(QWidget):
    """The channel panels' 표시 checkboxes in one row, plus all on / all off."""

    COLUMNS = 2

    def __init__(self, boxed: bool = True):
        super().__init__()
        self.panels: list[ChannelPanel] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        if boxed:
            box = QGroupBox('채널 표시')
            outer.addWidget(box)
            lay = QVBoxLayout(box)
        else:  # inside another box: a section header, never a box in a box
            outer.addWidget(theme.section_header('채널 표시'))
            lay = outer
        self.boxes = QGridLayout()
        lay.addLayout(self.boxes)
        buttons = QHBoxLayout()
        buttons.addStretch()
        on = QPushButton('모두 켜기')
        off = QPushButton('모두 끄기')
        on.clicked.connect(lambda: self.set_all(True))
        off.clicked.connect(lambda: self.set_all(False))
        buttons.addWidget(on)
        buttons.addWidget(off)
        lay.addLayout(buttons)

    def set_panels(self, panels):
        for p in self.panels:
            p.visible.setParent(None)
            p.visible.deleteLater()
        self.panels = list(panels)
        for i, p in enumerate(self.panels):
            self.boxes.addWidget(p.visible, i // self.COLUMNS, i % self.COLUMNS)

    def set_all(self, on: bool):
        if not self.panels or self.panels[0].item is None:
            return
        for p in self.panels:
            p.lut.visible = on
            p.refresh()
        self.panels[0].changed.emit()  # one redraw for all channels
