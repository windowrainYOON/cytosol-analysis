"""Preferences kept between sessions (QSettings, the platform's own settings
store): loading options (TCF HT + FL alignment), how strongly mouse drags
and the wheel act on the image view, the initial values of the marker
settings and of every tab (applied at start-up and on 새 프로젝트), the
widths of the side panes and the recent project list."""

from __future__ import annotations

import json
import time

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from . import theme

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
# on / off preferences: key -> (label, tooltip, default)
FLAGS = {
    'align_tcf': ('TCF: HT와 FL을 정렬해 한 이미지로',
                  'FL을 HT 픽셀 격자에 맞춰 리샘플링합니다 (XY: 픽셀 크기와 자동 미세 보정, '
                  'Z: 3DFL OffsetZ). 끄면 HT와 FL이 따로 열립니다. 새로 추가하는 파일부터 적용됩니다.', True),
}


class ViewSettings:
    """Sensitivities (multipliers of the built-in rates) and recent projects."""

    def __init__(self):
        self._qs = None
        self._cache = {}

    def _store(self) -> QSettings:
        if self._qs is None:
            self._qs = QSettings('CytosolViewer', 'Cytosol Viewer')
        return self._qs

    def use_store(self, qs: QSettings):
        """Another store (the self-test keeps the user's preferences untouched)."""
        self._qs = qs
        self._cache = {}

    # ---- on / off preferences ----

    def flag(self, key: str) -> bool:
        v = self._store().value(f'prefs/{key}', FLAGS[key][2])
        if isinstance(v, str):
            return v.lower() in ('1', 'true', 'yes')
        return bool(v)

    def set_flag(self, key: str, on: bool):
        self._store().setValue(f'prefs/{key}', bool(on))

    # ---- initial values (markers, every tab) ----

    def defaults(self, kind: str) -> dict | None:
        """Stored initial values: 'markers' (marker widget state) or 'tabs'
        (panel states like a project's, plus when they were saved)."""
        raw = self._store().value(f'defaults/{kind}', '')
        if not raw:
            return None
        try:
            d = json.loads(str(raw))
        except ValueError:
            return None
        return d if isinstance(d, dict) else None

    def set_defaults(self, kind: str, data: dict | None):
        if data is None:
            self._store().remove(f'defaults/{kind}')
        else:
            self._store().setValue(f'defaults/{kind}', json.dumps({**data, 'saved': time.strftime('%Y-%m-%d %H:%M')}))

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


class PreferencesDialog(QDialog):
    """Preferences (macOS: app menu, ⌘,): loading options, mouse
    sensitivities and the initial values of markers and tabs; every change
    is stored at once."""

    def __init__(self, win=None, parent=None):
        super().__init__(parent if parent is not None else win)
        self.win = win
        self.setWindowTitle('Preferences')
        self.resize(560, 720)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        page = QWidget()
        lay = QVBoxLayout(page)

        # ---- loading ----
        load = QGroupBox('이미지 불러오기')
        lf = QFormLayout(load)
        self.flags = {}
        for key, (label, tip, _default) in FLAGS.items():
            b = QCheckBox(label)
            b.setToolTip(tip)
            b.setChecked(view_settings.flag(key))
            b.toggled.connect(lambda on, k=key: view_settings.set_flag(k, on))
            lf.addRow(b)
            self.flags[key] = b
        lay.addWidget(load)

        # ---- mouse ----
        mouse = QGroupBox('마우스 민감도 (1.0 = 기본 빠르기의 배수)')
        form = QFormLayout(mouse)
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
            form.addRow(label, theme.slider_field(slider, spin, reset))
            self.spins[key] = spin
        note = QLabel('확대/축소: Cmd(Windows는 Ctrl) + 드래그, [ 축소, ] 확대. '
                      'Cmd 없이 휠을 굴리면 타임시리즈에서는 시점을 옮기고, 아니면 화면을 움직입니다.')
        note.setWordWrap(True)
        theme.hint(note)
        form.addRow(note)
        lay.addWidget(mouse)

        # ---- initial values of every tab ----
        tabs = QGroupBox('탭 설정 초기값')
        tl = QVBoxLayout(tabs)
        tnote = QLabel('지금 열린 창의 모든 탭 설정(세포질 ROI, 입자 ROI, 강도 측정, Coloc 2, 라인 '
                       '프로파일, FRAP, 스택, 내보내기 옵션 …)을 초기값으로 저장합니다. 앱을 켤 때와 '
                       '새 프로젝트를 만들 때 이 값으로 시작합니다. 프로젝트를 열면 프로젝트의 설정이 '
                       '우선합니다.')
        tnote.setWordWrap(True)
        theme.hint(tnote)
        tl.addWidget(tnote)
        self.tabs_state = theme.StatusLabel()
        self.tabs_state.setWordWrap(True)
        tl.addWidget(self.tabs_state)
        row = QHBoxLayout()
        self.save_tabs_btn = QPushButton('지금 탭 설정을 초기값으로 저장')
        self.save_tabs_btn.clicked.connect(self.save_tab_defaults)
        self.save_tabs_btn.setEnabled(win is not None)
        self.clear_tabs_btn = theme.destructive(QPushButton('저장한 탭 초기값 지우기…'))
        self.clear_tabs_btn.clicked.connect(self._confirm_clear_tabs)
        row.addWidget(self.save_tabs_btn)
        row.addStretch()
        row.addWidget(self.clear_tabs_btn)
        tl.addLayout(row)
        lay.addWidget(tabs)

        # ---- initial values of the markers (their own cards) ----
        from .marker_panel import MarkerPanel
        lay.addWidget(theme.section_header('마커 초기값'))
        mnote = QLabel('스케일 바, 타임 스탬프, bleach ROI 표시의 초기값 (자동 값 포함). 바꾸면 바로 '
                       '저장되고, 앱을 켤 때와 새 프로젝트를 만들 때 마커 탭이 이 값으로 시작합니다.')
        mnote.setWordWrap(True)
        theme.hint(mnote)
        lay.addWidget(mnote)
        mrow = QHBoxLayout()
        take = QPushButton('지금 마커 탭 설정 가져오기')
        take.setEnabled(win is not None)
        take.clicked.connect(self.take_markers)
        reset_m = QPushButton('프로그램 기본값으로')
        reset_m.clicked.connect(self.reset_markers)
        apply_m = QPushButton('지금 창에 적용')
        apply_m.setEnabled(win is not None)
        apply_m.clicked.connect(self.apply_markers)
        for b in (take, apply_m):
            mrow.addWidget(b)
        mrow.addStretch()
        mrow.addWidget(reset_m)
        lay.addLayout(mrow)
        self.markers = MarkerPanel()
        self.markers.layout().setContentsMargins(0, 0, 0, 0)
        self.markers.bl_status.setVisible(False)  # about the current image: not an initial value
        from .project import restore_widgets, widget_state
        self._marker_blank = widget_state(self.markers)
        stored = view_settings.defaults('markers')
        if stored:
            restore_widgets(self.markers, stored.get('state') or {})
        self.markers.changed.connect(self._markers_changed)
        lay.addWidget(self.markers)
        lay.addStretch()
        theme.unify(page)
        scroll.setWidget(page)
        outer.addWidget(scroll, 1)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(self.reject)
        box.accepted.connect(self.accept)
        outer.addWidget(box)
        self._show_tabs_state()

    def _changed(self, key, v, slider):
        slider.blockSignals(True)
        slider.setValue(int(round(v * 100)))
        slider.blockSignals(False)
        view_settings.set_value(key, v)

    # ---- tabs ----

    def _show_tabs_state(self):
        d = view_settings.defaults('tabs')
        if d:
            self.tabs_state.setText(f'저장한 탭 초기값 사용 중 ({d.get("saved", "")})')
            self.tabs_state.set_kind('success')
        else:
            self.tabs_state.setText('저장한 탭 초기값 없음: 프로그램 기본값으로 시작합니다.')
            self.tabs_state.set_kind(None)
        self.clear_tabs_btn.setEnabled(bool(d))

    def save_tab_defaults(self):
        if self.win is None:
            return
        view_settings.set_defaults('tabs', self.win.tab_defaults())
        self._show_tabs_state()
        self.win.statusBar().showMessage('탭 설정을 초기값으로 저장했습니다 (Preferences).')

    def _confirm_clear_tabs(self):
        if theme.confirm_destructive(self, '저장한 탭 초기값을 지울까요?',
                                     '다음에 앱을 켤 때부터 프로그램 기본값으로 시작합니다. 지금 열린 '
                                     '탭의 설정은 바뀌지 않습니다.', '지우기'):
            self.clear_tab_defaults()

    def clear_tab_defaults(self):
        view_settings.set_defaults('tabs', None)
        self._show_tabs_state()

    # ---- markers ----

    def _markers_changed(self):
        from .project import widget_state
        view_settings.set_defaults('markers', {'state': widget_state(self.markers)})

    def _set_markers(self, state):
        from .project import restore_widgets
        self.markers.blockSignals(True)
        try:
            restore_widgets(self.markers, state)
        finally:
            self.markers.blockSignals(False)
        self._markers_changed()

    def take_markers(self):
        from .project import widget_state
        if self.win is not None:
            self._set_markers(widget_state(self.win.markers))

    def reset_markers(self):
        self._set_markers(self._marker_blank or {})
        view_settings.set_defaults('markers', None)

    def apply_markers(self):
        from .project import restore_widgets, widget_state
        if self.win is not None:
            restore_widgets(self.win.markers, widget_state(self.markers))
            self.win.markers.changed.emit()


SettingsDialog = PreferencesDialog  # the old name
