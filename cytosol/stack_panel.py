"""Stack tab: settings for projecting a Z stack into one image (2D) or a
turned 3D view, plus its LUTs and saving. The main window shows the result
in its canvas while this tab is open (see MainWindow._stack_preview)."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .stack import METHODS_2D, METHODS_3D, StackView, z_ratio_from_metadata

PREVIEW_SIZES = [('빠름 (~256 px)', 256), ('보통 (~400 px)', 400), ('선명 (~600 px)', 600),
                 ('원본 해상도', 0)]


class StackPanel(QWidget):
    """``changed`` fires (debounced) whenever the projection must be redrawn;
    ``lutChanged`` when only the LUT link or source changed."""

    changed = Signal()
    refreshRequested = Signal()  # re-apply the LUT to the 3D structure

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view: StackView | None = None
        self._busy = False
        self._drag = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self.changed.emit)
        lay = QVBoxLayout(self)

        # mode
        mode_box = QGroupBox('Projection')
        ml = QVBoxLayout(mode_box)
        self.mode_2d = QRadioButton('2D projection (스택을 한 장으로)')
        self.mode_3d = QRadioButton('3D projection (돌려 보기)')
        self.mode_2d.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.mode_2d)
        grp.addButton(self.mode_3d)
        ml.addWidget(self.mode_2d)
        ml.addWidget(self.mode_3d)
        lay.addWidget(mode_box)

        # range
        rng = QGroupBox('범위')
        rf = QFormLayout(rng)
        self.z0 = QSpinBox()
        self.z1 = QSpinBox()
        for sp in (self.z0, self.z1):
            sp.setKeyboardTracking(False)
        all_z = QPushButton('전체')
        all_z.clicked.connect(self._all_z)
        row = QHBoxLayout()
        row.addWidget(self.z0)
        row.addWidget(QLabel('–'))
        row.addWidget(self.z1)
        row.addWidget(all_z)
        rf.addRow('Z 슬라이스', row)
        self.only_crop = QCheckBox('선택한 Crop 영역만 (빠름)')
        self.only_crop.setToolTip('Crop 탭의 목록에서 선택한 영역만 투영합니다.')
        rf.addRow(self.only_crop)
        lay.addWidget(rng)

        # 2D
        self.box_2d = QGroupBox('2D projection')
        f2 = QFormLayout(self.box_2d)
        self.method_2d = QComboBox()
        for key, name in METHODS_2D.items():
            self.method_2d.addItem(name, key)
        f2.addRow('방법', self.method_2d)
        lay.addWidget(self.box_2d)

        # 3D
        self.box_3d = QGroupBox('3D projection')
        f3 = QFormLayout(self.box_3d)
        self.method_3d = QComboBox()
        for key, name in METHODS_3D.items():
            self.method_3d.addItem(name, key)
        self.axis = QComboBox()
        self.axis.addItem('Y축 (좌우로 돌리기)', 'Y')
        self.axis.addItem('X축 (위아래로 기울이기)', 'X')
        self.angle = QSlider(Qt.Orientation.Horizontal)
        self.angle.setRange(-180, 180)
        self.angle_spin = QSpinBox()
        self.angle_spin.setRange(-180, 180)
        self.angle_spin.setSuffix('°')
        arow = QHBoxLayout()
        arow.addWidget(self.angle, 1)
        arow.addWidget(self.angle_spin)
        self.auto_sp = QRadioButton('자동')
        self.manual_sp = QRadioButton('수동')
        self.auto_sp.setChecked(True)
        sg = QButtonGroup(self)
        sg.addButton(self.auto_sp)
        sg.addButton(self.manual_sp)
        self.spacing = QDoubleSpinBox()
        self.spacing.setRange(0.001, 1000)
        self.spacing.setDecimals(3)
        self.spacing.setSingleStep(0.05)
        self.spacing.setSuffix(' µm')
        self.spacing.setKeyboardTracking(False)
        srow = QHBoxLayout()
        srow.addWidget(self.auto_sp)
        srow.addWidget(self.manual_sp)
        srow.addWidget(self.spacing, 1)
        self.spacing_note = QLabel()
        self.spacing_note.setStyleSheet('color: gray; font-size: 11px;')
        self.spacing_note.setWordWrap(True)
        self.preview = QComboBox()
        for name, size in PREVIEW_SIZES:
            self.preview.addItem(name, size)
        self.preview.setCurrentIndex(1)
        self.preview.setToolTip('돌려 볼 때의 해상도입니다. 저장은 원본 해상도로 할 수 있습니다.')
        f3.addRow('방법', self.method_3d)
        f3.addRow('회전축', self.axis)
        f3.addRow('각도', arow)
        f3.addRow('Z 간격', srow)
        f3.addRow(self.spacing_note)
        f3.addRow('미리보기', self.preview)
        self.refresh_btn = QPushButton('새로고침 (LUT 반영)')
        self.refresh_btn.setToolTip(
            '3D 구조는 이미지·Z 범위·미리보기 해상도마다 한 번만 만들고, 돌릴 때는 다시 읽지 않습니다.\n'
            'LUT의 Min/Max/Gamma를 바꾼 뒤 이 버튼을 누르면 3D에 반영됩니다 (색과 표시는 바로 반영).')
        self.refresh_btn.clicked.connect(self.refreshRequested.emit)
        f3.addRow(self.refresh_btn)
        hint = QLabel('이미지 위에서 왼쪽 드래그: 위치 이동 · 오른쪽 드래그: 회전 '
                      '(좌우 = Y축, 위아래 = X축)')
        hint.setStyleSheet('color: gray; font-size: 11px;')
        hint.setWordWrap(True)
        f3.addRow(hint)
        lay.addWidget(self.box_3d)

        # LUT
        lut_box = QGroupBox('LUT (투영 이미지)')
        ll = QVBoxLayout(lut_box)
        self.linked = QCheckBox('LUT 탭과 연동 (한쪽에서 바꾸면 양쪽에 반영)')
        self.linked.setChecked(True)
        self.linked.setToolTip('끄면 이 투영에만 쓰는 LUT를 따로 조절합니다. '
                               'Sum은 슬라이스 수만큼 범위를 곱해 적용합니다.')
        pull = QPushButton('LUT 탭에서 다시 가져오기')
        pull.clicked.connect(self._pull)
        ll.addWidget(self.linked)
        ll.addWidget(pull)
        from .app import VisibilityRow  # noqa: PLC0415  (app imports this module)

        self.visibility = VisibilityRow()
        ll.addWidget(self.visibility)
        self.lut_box = QVBoxLayout()
        ll.addLayout(self.lut_box)
        lay.addWidget(lut_box)

        # save
        save_box = QGroupBox('스택 투영 저장')
        sl = QVBoxLayout(save_box)
        self.save_full = QCheckBox('3D는 원본 해상도로 저장')
        self.save_full.setChecked(True)
        self.save_all_t = QCheckBox('타임시리즈는 모든 시점 저장')
        sl.addWidget(self.save_full)
        sl.addWidget(self.save_all_t)
        fps_row = QHBoxLayout()
        fps_row.addWidget(QLabel('MP4 프레임 속도'))
        self.fps = QSpinBox()
        self.fps.setRange(1, 60)
        self.fps.setValue(10)
        self.fps.setSuffix(' fps')
        self.fps.setToolTip('저장 창에서 형식을 MP4로 고르면 시점(또는 회전 각도)마다 한 프레임인 동영상으로 저장합니다.')
        fps_row.addWidget(self.fps)
        fps_row.addStretch()
        sl.addLayout(fps_row)
        rot = QHBoxLayout()
        self.rot_from = QSpinBox()
        self.rot_to = QSpinBox()
        self.rot_step = QSpinBox()
        for sp, v in ((self.rot_from, 0), (self.rot_to, 350), (self.rot_step, 10)):
            sp.setRange(-360, 360)
            sp.setSuffix('°')
            sp.setValue(v)
        self.rot_step.setRange(1, 180)
        rot.addWidget(QLabel('3D 회전 시리즈'))
        rot.addWidget(self.rot_from)
        rot.addWidget(QLabel('→'))
        rot.addWidget(self.rot_to)
        rot.addWidget(QLabel('간격'))
        rot.addWidget(self.rot_step)
        sl.addLayout(rot)
        # shown in the dialog of 스택 → 저장 (not in the tab)
        self.save_box = save_box

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet('color: gray; font-size: 11px;')
        lay.addWidget(self.status)
        lay.addStretch()

        for w in (self.mode_2d, self.mode_3d, self.only_crop, self.auto_sp):
            w.toggled.connect(self._edited)
        for w in (self.method_2d, self.method_3d, self.axis, self.preview):
            w.currentIndexChanged.connect(self._edited)
        for w in (self.z0, self.z1, self.spacing):
            w.valueChanged.connect(self._edited)
        self.angle.valueChanged.connect(self._angle_slider)
        self.angle_spin.valueChanged.connect(self._angle_spin)
        self.linked.toggled.connect(self._link_toggled)
        self._show_mode()

    # ---- binding ----------------------------------------------------------

    def bind(self, view: StackView | None):
        """Show the settings of a view (one per image)."""
        self.view = view
        self._busy = True
        try:
            if view is None:
                return
            st, it = view.settings, view.item
            nz = it.nz
            for sp in (self.z0, self.z1):
                sp.setRange(1, max(nz, 1))
            z0, z1 = st.z_range(nz)
            self.z0.setValue(z0 + 1)
            self.z1.setValue(z1 + 1)
            (self.mode_3d if st.mode == '3d' else self.mode_2d).setChecked(True)
            self.method_2d.setCurrentIndex(self.method_2d.findData(st.method_2d))
            self.method_3d.setCurrentIndex(self.method_3d.findData(st.method_3d))
            self.axis.setCurrentIndex(self.axis.findData(st.axis))
            self.angle.setValue(int(round(st.angle)))
            self.angle_spin.setValue(int(round(st.angle)))
            self.only_crop.setChecked(st.region is not None)
            (self.auto_sp if st.auto_spacing else self.manual_sp).setChecked(True)
            vz = it.image.voxel_size_um.get('Z')
            self.spacing.setValue(st.spacing_um if not st.auto_spacing or not vz else float(vz))
            self.linked.setChecked(view.linked)
            self._spacing_note()
            self.mode_3d.setEnabled(nz > 1)
        finally:
            self._busy = False
            self._show_mode()

    def read(self, region=None):
        """Copy the widgets into the view's settings."""
        v = self.view
        if v is None:
            return
        st = v.settings
        st.mode = '3d' if self.mode_3d.isChecked() else '2d'
        st.method_2d = self.method_2d.currentData()
        st.method_3d = self.method_3d.currentData()
        st.axis = self.axis.currentData()
        st.angle = float(self.angle_spin.value())
        z0, z1 = sorted((self.z0.value() - 1, self.z1.value() - 1))
        st.z0, st.z1 = z0, z1
        st.region = region if self.only_crop.isChecked() else None
        st.auto_spacing = self.auto_sp.isChecked()
        st.spacing_um = self.spacing.value()
        size = self.preview.currentData()
        h, w = v.item.image.shape[-2:]
        if st.region is not None:
            x0, y0, x1, y1 = st.region
            h, w = y1 - y0, x1 - x0
        st.step = max(1, -(-max(h, w) // size)) if size else 1

    # ---- internals --------------------------------------------------------

    def set_stale(self, stale: bool):
        """Highlight the refresh button when the LUT changed since the 3D build."""
        self.refresh_btn.setText('새로고침 (LUT 바뀜 · 눌러서 반영)' if stale else '새로고침 (LUT 반영)')
        self.refresh_btn.setStyleSheet('font-weight: bold; color: #e0a000;' if stale else '')

    def _show_mode(self):
        three = self.mode_3d.isChecked()
        self.box_2d.setVisible(not three)
        self.box_3d.setVisible(three)
        self.rot_from.setEnabled(three)
        self.spacing.setEnabled(self.manual_sp.isChecked())

    def _spacing_note(self):
        v = self.view
        if v is None:
            return
        vx = v.item.image.voxel_size_um
        zr = z_ratio_from_metadata(v.item.image)
        if zr:
            self.spacing_note.setText(
                f'자동: 메타데이터 Z {float(vx["Z"]):.3f} µm / XY {float(vx["X"]):.4f} µm '
                f'= 픽셀 {zr:.2f}개 간격')
        else:
            self.spacing_note.setText('메타데이터에 Z 간격이 없어 자동은 XY 픽셀 1개 간격으로 그립니다. '
                                      '실제 간격을 수동으로 넣으세요.')

    def _edited(self, *_):
        self._show_mode()
        if not self._busy:
            self._timer.start()

    def _angle_slider(self, v):
        if self.angle_spin.value() != v:
            self.angle_spin.setValue(v)

    def _angle_spin(self, v):
        if self.angle.value() != v:
            self.angle.blockSignals(True)
            self.angle.setValue(v)
            self.angle.blockSignals(False)
        self._edited()

    def begin_drag(self):
        """A right-drag on the 3D view starts (see drag_rotate)."""
        self._drag = None

    def drag_rotate(self, axis, pixels):
        """Turn the 3D view by a mouse drag: left-right about the Y axis,
        up-down about the X axis, 0.5 degree per screen pixel. Switching axis
        starts the new axis from the front view (one axis at a time)."""
        if not self.mode_3d.isChecked():
            return
        if self._drag is None or self._drag[0] != axis:
            if self.axis.currentData() != axis:
                self.axis.setCurrentIndex(self.axis.findData(axis))
                base = 0
            else:
                base = self.angle_spin.value()
            self._drag = (axis, base)
        a = (self._drag[1] + pixels * 0.5 + 180) % 360 - 180
        self.angle_spin.setValue(int(round(a)))

    def _all_z(self):
        self.z0.setValue(self.z0.minimum())
        self.z1.setValue(self.z1.maximum())

    def _link_toggled(self, on):
        if self.view is not None and not self._busy:
            self.view.linked = on
            if on:
                self._pull()

    def _pull(self):
        if self.view is not None:
            self.view.pull()
            self._timer.start()
