"""Settings for the markers burned into the preview and exported images:
the size marker (scale bar) and the time-series marker (time stamp)."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .render import TIME_UNITS, ScaleBarStyle, TimeStampStyle

POSITIONS = ['lower right', 'lower left', 'upper right', 'upper left']


def _auto_spin(maximum=1000, suffix=' px') -> QSpinBox:
    """Spin box where 0 means 'automatic' (size relative to the image)."""
    sp = QSpinBox()
    sp.setRange(0, maximum)
    sp.setSpecialValueText('자동')
    sp.setSuffix(suffix)
    return sp


class ColorButton(QPushButton):
    changed = Signal()

    def __init__(self, rgb=(1.0, 1.0, 1.0)):
        super().__init__()
        self.setFixedWidth(48)
        self.set_rgb(rgb)
        self.clicked.connect(self._pick)

    def set_rgb(self, rgb):
        self.rgb = tuple(float(c) for c in rgb)
        self.setStyleSheet(f'background-color: {QColor.fromRgbF(*self.rgb).name()};')

    def _pick(self):
        c = QColorDialog.getColor(QColor.fromRgbF(*self.rgb), self, '마커 색')
        if c.isValid():
            self.set_rgb((c.redF(), c.greenF(), c.blueF()))
            self.changed.emit()


class MarkerPanel(QWidget):
    """Two groups of controls; ``changed`` fires on every edit."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)

        # size marker
        self.sb = QGroupBox('Size marker (scale bar)')
        self.sb.setCheckable(True)
        self.sb.setChecked(True)
        f = QFormLayout(self.sb)
        self.sb_len = QDoubleSpinBox()
        self.sb_len.setRange(0, 10000)
        self.sb_len.setDecimals(2)
        self.sb_len.setSpecialValueText('자동')
        self.sb_len.setSuffix(' µm')
        self.sb_pos = QComboBox()
        self.sb_pos.addItems(POSITIONS)
        self.sb_label = QCheckBox('글자 표시 (예: 10 µm)')
        self.sb_label.setChecked(True)
        self.sb_font = _auto_spin(400)
        self.sb_thick = _auto_spin(200)
        self.sb_margin = _auto_spin(2000)
        self.sb_gap = _auto_spin(400)
        self.sb_color = ColorButton()
        f.addRow('마커 길이', self.sb_len)
        f.addRow('위치', self.sb_pos)
        f.addRow(self.sb_label)
        f.addRow('글자 크기', self.sb_font)
        f.addRow('마커 두께', self.sb_thick)
        f.addRow('글자-마커 간격', self.sb_gap)
        f.addRow('가장자리 여백', self.sb_margin)
        f.addRow('색', self.sb_color)
        lay.addWidget(self.sb)

        # time-series marker
        self.ts = QGroupBox('Time-series marker (타임 스탬프)')
        self.ts.setCheckable(True)
        self.ts.setChecked(True)
        f = QFormLayout(self.ts)
        self.ts_pos = QComboBox()
        self.ts_pos.addItems(POSITIONS)
        self.ts_pos.setCurrentText('upper left')
        self.ts_label = QCheckBox('글자 표시')
        self.ts_label.setChecked(True)
        self.ts_unit = QComboBox()
        self.ts_unit.addItems(TIME_UNITS)
        self.ts_dec = QSpinBox()
        self.ts_dec.setRange(0, 3)
        self.ts_prefix = QLineEdit()
        self.ts_prefix.setPlaceholderText('예: t = ')
        self.ts_offset = QDoubleSpinBox()
        self.ts_offset.setRange(-1e6, 1e6)
        self.ts_offset.setSuffix(' s')
        self.ts_offset.setToolTip('모든 시간에 더할 값 (예: 처리 전 시간을 음수로 표시)')
        self.ts_font = _auto_spin(400)
        self.ts_margin = _auto_spin(2000)
        self.ts_bar = QCheckBox('진행 막대 표시')
        self.ts_bar_len = QDoubleSpinBox()
        self.ts_bar_len.setRange(1, 100)
        self.ts_bar_len.setValue(25)
        self.ts_bar_len.setSuffix(' % (이미지 폭)')
        self.ts_bar_thick = _auto_spin(200)
        self.ts_gap = _auto_spin(400)
        self.ts_color = ColorButton()
        f.addRow('위치', self.ts_pos)
        f.addRow(self.ts_label)
        f.addRow('단위', self.ts_unit)
        f.addRow('소수점 자리', self.ts_dec)
        f.addRow('앞 글자', self.ts_prefix)
        f.addRow('시간 보정', self.ts_offset)
        f.addRow('글자 크기', self.ts_font)
        f.addRow(self.ts_bar)
        f.addRow('막대 길이', self.ts_bar_len)
        f.addRow('막대 두께', self.ts_bar_thick)
        f.addRow('글자-막대 간격', self.ts_gap)
        f.addRow('가장자리 여백', self.ts_margin)
        f.addRow('색', self.ts_color)
        lay.addWidget(self.ts)
        note = QLabel('Time-series marker는 시점이 2개 이상인 이미지에만 그려집니다. '
                      '숫자 칸의 "자동"은 이미지 크기에 맞춘 값입니다.')
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addStretch()

        for w in (self.sb, self.ts, self.sb_label, self.ts_label, self.ts_bar):
            w.toggled.connect(self._emit)
        for w in (self.sb_pos, self.ts_pos, self.ts_unit):
            w.currentIndexChanged.connect(self._emit)
        for w in (self.sb_len, self.sb_font, self.sb_thick, self.sb_margin, self.sb_gap,
                  self.ts_dec, self.ts_offset, self.ts_font, self.ts_margin, self.ts_bar_len,
                  self.ts_bar_thick, self.ts_gap):
            w.valueChanged.connect(self._emit)
        self.ts_prefix.textChanged.connect(self._emit)
        self.sb_color.changed.connect(self._emit)
        self.ts_color.changed.connect(self._emit)

    def _emit(self, *_):
        self.changed.emit()

    def scale_style(self) -> ScaleBarStyle:
        return ScaleBarStyle(
            enabled=self.sb.isChecked(),
            length_um=self.sb_len.value() or None,
            position=self.sb_pos.currentText(),
            label=self.sb_label.isChecked(),
            font_px=self.sb_font.value() or None,
            thickness_px=self.sb_thick.value() or None,
            margin_px=self.sb_margin.value() or None,
            gap_px=self.sb_gap.value() or None,
            color=self.sb_color.rgb,
        )

    def time_style(self) -> TimeStampStyle:
        return TimeStampStyle(
            enabled=self.ts.isChecked(),
            position=self.ts_pos.currentText(),
            label=self.ts_label.isChecked(),
            unit=self.ts_unit.currentText(),
            decimals=self.ts_dec.value(),
            prefix=self.ts_prefix.text(),
            offset_s=self.ts_offset.value(),
            font_px=self.ts_font.value() or None,
            margin_px=self.ts_margin.value() or None,
            color=self.ts_color.rgb,
            bar=self.ts_bar.isChecked(),
            bar_length_pct=self.ts_bar_len.value(),
            bar_thickness_px=self.ts_bar_thick.value() or None,
            gap_px=self.ts_gap.value() or None,
        )
