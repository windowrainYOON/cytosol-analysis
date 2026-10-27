"""View preferences kept between sessions (QSettings): how strongly mouse
drags and the wheel act on the image view, the widths of the side panes and
the recent project list."""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

# key -> (label, tooltip, default multiplier)
SENSITIVITIES = {
    'zoom_drag': ('확대/축소 드래그 (Cmd/Ctrl + 드래그)',
                  '위로 드래그하면 확대, 아래로 드래그하면 축소. 값이 작을수록 천천히 바뀝니다.', 0.6),
    'scrub_drag': ('T · Z 이동 (오른쪽 버튼 드래그)',
                   '오른쪽 버튼 드래그로 시점(좌우)과 Z(상하)를 옮길 때의 빠르기.', 1.0),
    'wheel_t': ('휠 시간 이동 (타임시리즈)',
                '휠 한 칸(트랙패드는 그만큼의 스크롤)에 몇 시점을 옮길지.', 1.0),
}
RANGE = (0.1, 3.0)
MAX_RECENT = 10


class ViewSettings:
    """Sensitivities (multipliers of the built-in rates) and recent projects."""

    def __init__(self):
        self._qs = None
        self._cache = {}

    def _store(self) -> QSettings:
        if self._qs is None:
            self._qs = QSettings('CytosolViewer', 'Cytosol Viewer')
        return self._qs

    def value(self, key: str) -> float:
        if key not in self._cache:
            default = SENSITIVITIES[key][2]
            try:
                v = float(self._store().value(f'view/{key}', default))
            except (TypeError, ValueError):
                v = default
            self._cache[key] = min(max(v, RANGE[0]), RANGE[1])
        return self._cache[key]

    def set_value(self, key: str, v: float):
        self._cache[key] = float(v)
        self._store().setValue(f'view/{key}', float(v))

    def pane_widths(self, left: int, right: int) -> tuple[int, int]:
        """Remembered widths of the image list and the tools pane."""
        out = []
        for key, default in (('left', left), ('right', right)):
            try:
                out.append(int(self._store().value(f'layout/{key}_width', default)))
            except (TypeError, ValueError):
                out.append(default)
        return out[0], out[1]

    def set_pane_widths(self, left: int, right: int):
        self._store().setValue('layout/left_width', int(left))
        self._store().setValue('layout/right_width', int(right))

    def recent(self) -> list[str]:
        v = self._store().value('recent_projects', [])
        if isinstance(v, str):
            v = [v]
        return [str(x) for x in (v or [])]

    def add_recent(self, path: str):
        items = [path] + [p for p in self.recent() if p != path]
        self._store().setValue('recent_projects', items[:MAX_RECENT])

    def clear_recent(self):
        self._store().setValue('recent_projects', [])


view_settings = ViewSettings()


class SettingsDialog(QDialog):
    """Sliders for the drag / wheel sensitivities; changes apply at once."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('설정')
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel('마우스 민감도 (1.0 = 기본 빠르기의 배수)'))
        form = QFormLayout()
        self.spins = {}
        for key, (label, tip, default) in SENSITIVITIES.items():
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(int(RANGE[0] * 100), int(RANGE[1] * 100))
            spin = QDoubleSpinBox()
            spin.setRange(*RANGE)
            spin.setSingleStep(0.1)
            spin.setDecimals(2)
            spin.setSuffix(' ×')
            for w in (slider, spin):
                w.setToolTip(tip)
            spin.setValue(view_settings.value(key))
            slider.setValue(int(round(spin.value() * 100)))
            slider.valueChanged.connect(lambda v, s=spin: s.setValue(v / 100))
            spin.valueChanged.connect(lambda v, k=key, sl=slider: self._changed(k, v, sl))
            reset = QPushButton('기본값')
            reset.clicked.connect(lambda _=False, s=spin, d=default: s.setValue(d))
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.addWidget(slider, 1)
            rl.addWidget(spin)
            rl.addWidget(reset)
            form.addRow(label, row)
            self.spins[key] = spin
        lay.addLayout(form)
        note = QLabel('확대/축소: Cmd(Windows는 Ctrl) + 드래그, [ 축소, ] 확대. '
                      'Cmd 없이 휠을 굴리면 타임시리즈에서는 시점을 옮기고, 아니면 화면을 움직입니다.')
        note.setWordWrap(True)
        note.setStyleSheet('color: gray; font-size: 11px;')
        lay.addWidget(note)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(self.reject)
        box.accepted.connect(self.accept)
        lay.addWidget(box)

    def _changed(self, key, v, slider):
        slider.blockSignals(True)
        slider.setValue(int(round(v * 100)))
        slider.blockSignals(False)
        view_settings.set_value(key, v)
