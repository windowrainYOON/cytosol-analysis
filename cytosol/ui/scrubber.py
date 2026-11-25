"""Scrubber — the canvas Z / T capsule (design system ``hig-scrubber``).

A capsule (height 36, radius 18, floating surface) holding the axis name,
the axis slider and the position text (``current / total · time``); the T
capsule also has a play button (▶ / ❚❚) that steps through the time points.
The sliders and labels are the window's own (their signals are unchanged);
the capsule only lays them out. Z is the same capsule standing upright at
the canvas' left edge, its position text under the name. Hidden when the
axis has one plane.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

HEIGHT = 36
PLAY_MS = 200  # one time point per 0.2 s while playing


class Scrubber(QWidget):
    """``Scrubber('T', slider, label, play=True)`` / ``Scrubber('Z', slider,
    label, vertical=True, extra=[mip])``; ``playToggled(bool)``, ``step``
    every ``PLAY_MS`` while playing."""

    playToggled = Signal(bool)
    step = Signal()

    def __init__(self, axis: str, slider, label, *, vertical: bool = False, play: bool = False,
                 extra=(), parent=None):
        from ..hig_widgets import IconButton  # noqa: PLC0415

        super().__init__(parent)
        self.setObjectName('hig_scrubber')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty('hig_scrubber', 'z' if vertical else 't')
        self.axis = QLabel(axis)
        self.axis.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = self.axis.font()
        f.setBold(True)
        self.axis.setFont(f)
        self.slider, self.label = slider, label
        self.play_btn = None
        if play:
            self.play_btn = IconButton('play', '재생 / 멈춤 (T)', checkable=True)
            self.play_btn.toggled.connect(self._play)
            self.timer = QTimer(self)
            self.timer.setInterval(PLAY_MS)
            self.timer.timeout.connect(self.step)
        if vertical:
            lay = QVBoxLayout(self)
            lay.setContentsMargins(4, 10, 4, 10)
            lay.setSpacing(4)
            lay.addWidget(self.axis)
            lay.addWidget(label)
            lay.addWidget(slider, 1, Qt.AlignmentFlag.AlignHCenter)
            for w in extra:
                lay.addWidget(w, 0, Qt.AlignmentFlag.AlignHCenter)
        else:
            self.setFixedHeight(HEIGHT)
            lay = QHBoxLayout(self)
            lay.setContentsMargins(4 if play else 14, 0, 14, 0)
            lay.setSpacing(8)
            if self.play_btn is not None:
                lay.addWidget(self.play_btn)
            lay.addWidget(self.axis)
            lay.addWidget(slider, 1)
            lay.addWidget(label)
            for w in extra:
                lay.addWidget(w)

    def playing(self) -> bool:
        return self.play_btn is not None and self.play_btn.isChecked()

    def stop(self):
        if self.playing():
            self.play_btn.setChecked(False)

    def _play(self, on: bool):
        self.play_btn.setProperty('hig_icon', 'pause' if on else 'play')
        self.play_btn.refresh_icon()
        if on:
            self.timer.start()
        else:
            self.timer.stop()
        self.playToggled.emit(on)
