"""Line profile tab: draw a line on the image, plot every channel's raw
intensity along it (ImageJ RGB Profiler style), save the plot and a CSV."""

from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .lineprofile import Profile, draw_profile, line_profile, write_profile_csv


class ProfilePanel(QWidget):
    """Owns the plot; the main window feeds it the current image and line."""

    changed = Signal()  # line width changed or line cleared: redraw the overlay

    def __init__(self, parent=None):
        super().__init__(parent)
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from matplotlib.figure import Figure

        self.item = None
        self.profile: Profile | None = None
        lay = QVBoxLayout(self)

        help_ = QLabel('‘선 그리기’를 켜고 이미지 위에서 드래그하면 그 선을 따라 채널별 강도'
                       '(원본값)를 그래프로 보여줍니다. 현재 Z(또는 MIP)와 시점의 값이며, '
                       'Z·시점·LUT 색을 바꾸면 그래프도 따라 바뀝니다.')
        help_.setWordWrap(True)
        help_.setStyleSheet('color: gray; font-size: 11px;')
        lay.addWidget(help_)

        line_box = QGroupBox('선')
        ll = QVBoxLayout(line_box)
        self.draw_btn = QPushButton('선 그리기 (드래그)')
        self.draw_btn.setCheckable(True)
        ll.addWidget(self.draw_btn)
        row = QHBoxLayout()
        row.addWidget(QLabel('선 두께'))
        self.width = QSpinBox()
        self.width.setRange(1, 200)
        self.width.setValue(1)
        self.width.setSuffix(' px')
        self.width.setToolTip('두께가 2 px 이상이면 선에 수직인 방향으로 그만큼의 픽셀을 평균합니다 (ImageJ의 선 두께와 같음).')
        self.width.valueChanged.connect(self._width_changed)
        row.addWidget(self.width)
        row.addStretch()
        clear = QPushButton('선 지우기')
        clear.clicked.connect(self.clear_line)
        row.addWidget(clear)
        ll.addLayout(row)
        lay.addWidget(line_box)

        plot_box = QGroupBox('채널별 강도')
        pl = QVBoxLayout(plot_box)
        self.fig = Figure(figsize=(4, 3), dpi=100, layout='constrained')
        self.ax = self.fig.add_subplot(111)
        self.plot = FigureCanvasQTAgg(self.fig)
        self.plot.setMinimumHeight(280)
        pl.addWidget(self.plot, 1)
        row = QHBoxLayout()
        self.only_visible = QCheckBox('LUT에서 숨긴 채널 제외')
        self.only_visible.setChecked(True)
        self.normalize = QCheckBox('채널별 0–1 정규화')
        for w in (self.only_visible, self.normalize):
            w.toggled.connect(self.schedule)
            row.addWidget(w)
        row.addStretch()
        pl.addLayout(row)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setStyleSheet('color: gray; font-size: 11px;')
        pl.addWidget(self.info)
        row = QHBoxLayout()
        csv_btn = QPushButton('CSV 저장…')
        csv_btn.clicked.connect(self.save_csv)
        png_btn = QPushButton('그래프 저장…')
        png_btn.clicked.connect(self.save_plot)
        row.addWidget(csv_btn)
        row.addWidget(png_btn)
        pl.addLayout(row)
        lay.addWidget(plot_box, 1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(60)  # coalesce LUT slider drags into one redraw
        self._timer.timeout.connect(self.refresh)
        self.refresh()

    # ---- data -----------------------------------------------------------

    def bind(self, item):
        self.item = item
        self.refresh()

    def set_line(self, line):
        if self.item is None:
            return
        self.item.profile_line = tuple(float(v) for v in line)
        self.refresh()

    def clear_line(self):
        if self.item is not None:
            self.item.profile_line = None
        self.refresh()
        self.changed.emit()

    def _width_changed(self, _):
        self.changed.emit()
        self.schedule()

    def schedule(self, *_):
        self._timer.start()

    def _z_text(self):
        it = self.item
        z = 'MIP' if it.z == 'mip' else f'z {int(it.z) + 1}/{it.nz}'
        return z + (f', t {it.t + 1}/{it.nt}' if it.nt > 1 else '')

    def refresh(self):
        it = self.item
        line = getattr(it, 'profile_line', None) if it is not None else None
        self.profile = None
        if line is None:
            self.ax.clear()
            self.ax.set_xlabel('Distance')
            self.ax.set_ylabel('Intensity')
            self.ax.grid(True, color='0.85', lw=0.6)
            self.plot.draw_idle()
            self.info.setText('선이 없습니다.' if it is not None else '이미지를 추가하세요.')
            return
        try:
            self.profile = line_profile(it.planes(), line, self.width.value(), it.pixel_um,
                                        it.channels)
        except Exception as exc:
            traceback.print_exc()
            self.info.setText(f'프로파일 계산 실패: {exc}')
            return
        draw_profile(self.ax, self.profile, self._colors(), self._visible(),
                     self.normalize.isChecked())
        self.plot.draw_idle()
        p = self.profile
        x0, y0, x1, y1 = p.line
        self.info.setText(
            f'길이 {p.length:.2f} {p.unit} · 두께 {p.width} px · {self._z_text()} · '
            f'({x0:.0f}, {y0:.0f}) → ({x1:.0f}, {y1:.0f}) px')

    def _colors(self):
        return [lut.color for lut in self.item.luts]

    def _visible(self):
        if not self.only_visible.isChecked():
            return None
        return [lut.visible for lut in self.item.luts]

    # ---- save -----------------------------------------------------------

    def _default(self, suffix):
        from .lut import item_stem

        it = self.item
        return str(it.path.with_name(f'{item_stem(it)}_profile{suffix}'))

    def save_csv(self):
        if self.profile is None:
            QMessageBox.information(self, '라인 프로파일', '먼저 이미지 위에 선을 그리세요.')
            return
        path, _ = QFileDialog.getSaveFileName(self, '프로파일 CSV 저장', self._default('.csv'),
                                              'CSV (*.csv)')
        if not path:
            return
        it = self.item
        extra = dict(it.id_properties(), plane=self._z_text())
        try:
            write_profile_csv(path, self.profile, extra)
        except Exception as exc:
            QMessageBox.warning(self, '저장 실패', str(exc))

    def save_plot(self):
        if self.profile is None:
            QMessageBox.information(self, '라인 프로파일', '먼저 이미지 위에 선을 그리세요.')
            return
        path, flt = QFileDialog.getSaveFileName(
            self, '그래프 저장', self._default('.png'),
            'PNG (*.png);;PDF (*.pdf);;SVG (*.svg);;TIFF (*.tif)')
        if not path:
            return
        if not Path(path).suffix:
            path += {'PDF': '.pdf', 'SVG': '.svg', 'TIF': '.tif'}.get(flt[:3], '.png')
        try:
            save_profile_figure(path, self.profile, self._colors(), self._visible(),
                                self.normalize.isChecked())
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, '저장 실패', str(exc))


def save_profile_figure(path, prof, colors, visible=None, normalize=False, size=(5, 3.5)):
    """Write the profile plot as PNG/TIFF (300 dpi), PDF or SVG."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    fig = Figure(figsize=size, dpi=300, layout='constrained')
    FigureCanvasAgg(fig)
    draw_profile(fig.add_subplot(111), prof, colors, visible, normalize)
    fig.savefig(path, dpi=300)
    return str(path)
