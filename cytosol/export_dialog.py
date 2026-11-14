"""파일 › 내보내기… (owner request 2026-11-05): one window for every export
of the app (images, crops, ROIs, measurement tables, graphs, metadata,
batch results, the project). Nothing else in the app saves results.

Layout (design system: a window of its own with a toolbar + Sidebar +
SettingsPane): a toolbar on top (target images, destination, the one
prominent 내보내기 button: never on the window's bottom edge), a sidebar of
export kinds, each with a check box (included) and how many of its outputs
are on, and on the right the settings cards of the picked kind. The choices
are kept between sessions (QSettings ``defaults/export``); the image
options also go to the main window's exp_* widgets (saved in projects).
``exporter.run`` writes the files."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QProgressDialog,
                               QPushButton, QScrollArea, QSpinBox, QStackedWidget, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from . import theme

# kind key -> (sidebar title, [(card title, [(output key, label, tip, default on)])])
KINDS: dict = {
    'image': ('이미지 (TIFF / MP4)', [
        ('저장할 형태', [
            ('composite', '합성 RGB (LUT 적용)', '', True),
            ('channels', '채널별 RGB', '', False),
            ('raw', '원본값 스택 (ImageJ, 모든 Z)', '', True),
        ]),
    ]),
    'crop': ('Crop 영역', [
        ('Crop 영역 이미지', [
            ('crop_images', 'Crop 영역마다 이미지 저장', '형태(합성 RGB · 채널별 · 원본값)와 시간 · 형식은 ‘이미지’ '
             '설정을 따릅니다. 점 편집으로 모양을 바꾼 영역은 바깥을 0으로 채운 사각형 이미지로 저장합니다.', True),
        ]),
        ('Crop 영역 ROI', [
            ('crop_rois', 'Crop 영역 ROI (ImageJ RoiSet .zip)', '', True),
        ]),
    ]),
    'roi': ('세포질 ROI', [
        ('ROI', [
            ('cell', '세포 전체', '', True),
            ('nuc', '핵', '', True),
            ('cyto', '세포질 (핵 제외)', '', True),
        ]),
        ('측정', [
            ('roi_csv', '측정 CSV', '', True),
            ('roi_png', 'ROI가 그려진 이미지 (.png)', '', False),
        ]),
    ]),
    'particle': ('입자 ROI', [
        ('ROI', [
            ('particles', '입자 ROI (.zip, 윤곽 ROI 포함)', '', True),
        ]),
        ('측정', [
            ('particle_csv', '측정 CSV (입자마다, 세포마다)', '', True),
            ('particle_summary', '이미지별 · 그룹별 요약 CSV', '', True),
        ]),
    ]),
    'intensity': ('강도 측정', [
        ('측정', [
            ('intensity_csv', '측정 CSV', '', True),
            ('regions', '논리 영역 ROI (.zip)', '', False),
        ]),
    ]),
    'bands': ('등거리 띠', [
        ('측정', [
            ('bands_csv', '띠별 측정 CSV', '', True),
            ('bands_plot', '띠 그래프 (현재 이미지)', '', True),
        ]),
    ]),
    'coloc': ('Coloc 2', [
        ('결과', [
            ('coloc_csv', '결과 CSV (ROI마다 한 행)', '', True),
            ('coloc_pdf', 'PDF 리포트 (ROI마다)', '', False),
        ]),
    ]),
    'profile': ('라인 프로파일', [
        ('현재 이미지의 선', [
            ('profile_csv', 'CSV', '', True),
            ('profile_plot', '그래프', '', True),
            ('line_roi', '선 ROI (.roi) + 선이 그려진 이미지 (.png)', '', True),
        ]),
    ]),
    'frap': ('FRAP', [
        ('요약', [
            ('frap_summary', '요약 CSV + 그룹 평균 그래프', 'frap_summary.csv, frap_group_curves.csv, '
             'frap_groups.png/.pdf, frap_summary.png, frap_formulas.txt', True),
        ]),
        ('이미지마다', [
            ('frap_csv', '곡선 CSV', '', True),
            ('frap_plot', '곡선 그래프', '', True),
            ('frap_rois', 'FRAP ROI (.zip)', '', True),
        ]),
    ]),
    'track': ('입자 추적', [
        ('이미지마다', [
            ('track_csv', '트랙 시점 CSV + 트랙 요약 CSV', '<이름>_tracks_points.csv, <이름>_tracks_summary.csv', True),
            ('track_rois', '트랙 ROI (.zip: 프레임마다 입자 + 트랙 경로)', '', True),
            ('track_pt', 'ParticleTracker 열 이름으로 (x_fl, y_fl, roi_label, ratio_BA …)', '', False),
        ]),
        ('모든 이미지', [
            ('track_all', 'tracks_points.csv · tracks_summary.csv · tracks_cells.csv', '', True),
        ]),
    ]),
    'mito': ('mitoROI', [
        ('이미지마다 (Mito Analyzer 파일 이름)', [
            ('mito_csv', '세포 · 미토 조각 · 점 · 상관 CSV', '<이름>_per_cell.csv, _per_mito.csv, _green_puncta.csv, '
             '_correlations.csv', True),
            ('mito_rois', '미토 조각 ROI (_mito_RoiSet.zip)', '', True),
        ]),
        ('모든 이미지', [
            ('mito_all', 'mito_per_cell.csv · mito_per_mito.csv · mito_green_puncta.csv', '', True),
        ]),
    ]),
    'stack': ('스택 투영', [
        ('현재 이미지의 투영', [
            ('projection', '현재 투영 (스택 탭 설정)', '', True),
            ('rotation', '3D 회전 시리즈', '스택 탭에서 3D projection이 켜져 있을 때 저장합니다.', False),
            ('stack_mp4', 'MP4 동영상으로 (끄면 TIFF)', '', False),
        ]),
    ]),
    'graph': ('그래프', [
        ('함께 저장', [
            ('g_data', '그래프마다 데이터 표 (CSV)', '', True),
            ('g_spec', '그래프 설정 (.json)', '', False),
        ]),
    ]),
    'info': ('이미지 정보', [
        ('메타데이터', [
            ('info_csv', '획득 정보 CSV', '', True),
            ('info_raw', '원본 메타데이터 (XML / TCF 속성)', '', False),
        ]),
    ]),
    'batch': ('일괄 분석 결과', [
        ('결과', [
            ('batch_results', '고른 분석의 결과 + batch_summary.csv (batch 폴더)', '', True),
            ('batch_settings', '일괄 분석 설정 (batch_settings.json)', '', True),
        ]),
    ]),
    'project': ('프로젝트 · 작업 기록', [
        ('함께 저장', [
            ('project', '프로젝트 파일 (project.cyproj)', '', True),
            ('log', '작업 기록 CSV', '', False),
        ]),
    ]),
}
DEFAULT_KINDS = ('image', 'crop', 'roi', 'particle')
# image options that live on the main window (exp_*, saved in projects)
RGB_FORMATS = (('tif', 'TIFF 스택'), ('mp4', 'MP4 동영상'), ('both', 'TIFF + MP4'))


class ExportDialog(QDialog):
    def __init__(self, win, kind=None):
        super().__init__(win)
        from .settings import view_settings

        self.win = win
        self.setWindowTitle('내보내기')
        self.resize(940, 640)
        saved = view_settings.defaults('export') or {}
        self.saved = saved
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 20)
        outer.setSpacing(12)

        # ---- toolbar: target, destination, the one action ----
        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.addWidget(QLabel('대상'))
        self.target = QComboBox()
        n = len(win.items)
        rows = win.file_list.selected_rows() if n else []
        if win.current is not None:
            self.target.addItem('현재 이미지', 'current')
        if len(rows) > 1:
            self.target.addItem(f'선택한 이미지 ({len(rows)}개)', 'selected')
        if n:
            self.target.addItem(f'모든 이미지 ({n}개)', 'all')
        groups = {}
        for it in win.items:
            if it.group:
                groups[it.group] = groups.get(it.group, 0) + 1
        for g, k in groups.items():
            self.target.addItem(f'그룹: {g} ({k}개)', f'group:{g}')
        if not n:
            self.target.addItem('이미지 없음', 'none')
        i = self.target.findData(saved.get('target', 'all'))
        self.target.setCurrentIndex(i if i >= 0 else max(self.target.findData('all'), 0))
        self.target.currentIndexChanged.connect(lambda _: self._summary())
        bar.addWidget(self.target)
        bar.addSpacing(16)
        bar.addWidget(QLabel('저장 위치'))
        self.dest = QLineEdit(saved.get('dest') or str(Path.home() / 'Desktop' / 'Cytosol export'))
        self.dest.setMinimumWidth(220)
        bar.addWidget(self.dest, 1)
        pick = QPushButton('폴더 선택…')
        pick.clicked.connect(self._pick)
        bar.addWidget(pick)
        bar.addSpacing(16)
        self.go = theme.prominent(QPushButton('내보내기'))
        self.go.setDefault(True)
        self.go.clicked.connect(self.run)
        bar.addWidget(self.go)
        outer.addLayout(bar)
        bar2 = QHBoxLayout()
        self.per_image = QCheckBox('이미지별 폴더에 나눠 저장 (<이름>_<이미지 ID>)')
        self.per_image.setChecked(win.opt_per_image.isChecked())
        self.per_image.toggled.connect(lambda _: self._summary())
        bar2.addWidget(self.per_image)
        bar2.addStretch()
        self.summary = QLabel('')
        theme.secondary(self.summary)
        bar2.addWidget(self.summary)
        outer.addLayout(bar2)

        body = QHBoxLayout()
        body.setSpacing(20)
        # ---- sidebar of kinds ----
        self.tree = QTreeWidget()
        self.tree.setFixedWidth(240)
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(2)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(0)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        hd = self.tree.header()
        hd.setStretchLastSection(False)
        hd.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hd.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.tree.setColumnWidth(1, 44)
        body.addWidget(self.tree)
        self.pages = QStackedWidget()
        body.addWidget(self.pages, 1)
        outer.addLayout(body, 1)

        self.items = {}  # kind -> sidebar row
        self.checks = {}  # output key -> QCheckBox
        self.kind_of = {}  # output key -> kind
        on_kinds = set(saved.get('kinds', DEFAULT_KINDS))
        for key, (title, cards) in KINDS.items():
            it = QTreeWidgetItem([title, ''])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(0, Qt.CheckState.Checked if key in on_kinds else Qt.CheckState.Unchecked)
            it.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tree.addTopLevelItem(it)
            self.items[key] = it
            self.pages.addWidget(self._page(key, title, cards))
        self.tree.currentItemChanged.connect(
            lambda cur, _p: cur is not None and self.pages.setCurrentIndex(self.tree.indexOfTopLevelItem(cur)))
        self.tree.itemChanged.connect(lambda *_: self._summary())
        if kind in self.items:  # opened for one kind (e.g. from the graph window): only that one on
            for k, it in self.items.items():
                it.setCheckState(0, Qt.CheckState.Checked if k == kind else Qt.CheckState.Unchecked)
        first = kind if kind in self.items else next(iter(self.items))
        self.tree.setCurrentItem(self.items[first])
        self.items[first].setSelected(True)
        self.tree.setFocus()
        self._summary()

    # ---- building ----

    def _check(self, key, kind, label, default):
        b = QCheckBox(label)
        b.setChecked(bool(self.saved.get('outputs', {}).get(key, default)))
        b.toggled.connect(lambda _: self._summary())
        self.checks[key] = b
        self.kind_of[key] = kind
        return b

    def _page(self, key, title, cards):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        page = QWidget()
        lay = QVBoxLayout(page)
        head = QLabel(title)
        theme.text_style(head, 'headline')
        lay.addWidget(head)
        if key == 'graph':
            lay.addWidget(self._graph_list())
        for card_title, outs in cards:
            box = QGroupBox(card_title)
            form = QFormLayout(box)
            for k, label, tip, default in outs:
                b = self._check(k, key, label, default)
                form.addRow(b)
                if tip:
                    h = QLabel(tip)
                    h.setWordWrap(True)
                    theme.hint(h)
                    form.addRow(h)
                    theme.group_rows(b, h)
            if key == 'crop' and card_title == 'Crop 영역 이미지':
                self.crop_which = QComboBox()
                self.crop_which.addItem('모든 Crop 영역', 'all')
                self.crop_which.addItem('선택한 Crop 영역만 (현재 이미지)', 'selected')
                self.crop_which.setCurrentIndex(max(self.crop_which.findData(self.saved.get('crop_which', 'all')), 0))
                form.addRow('저장할 Crop', self.crop_which)
            lay.addWidget(box)
        if key == 'image':
            lay.addWidget(self._image_format())
        if key == 'roi':
            lay.addWidget(self._roi_format())
        if key == 'graph':
            lay.addWidget(self._graph_format())
        if key == 'stack':
            h = QLabel('투영 방식, 회전 각도, 3D 해상도와 MP4 속도는 스택 탭과 그 설정을 따릅니다.')
            h.setWordWrap(True)
            theme.hint(h)
            lay.addWidget(h)
        if key in ('profile', 'stack', 'bands'):
            h = QLabel('그래프 · 라인 프로파일 · 스택 투영은 현재 이미지가 대상에 들어 있을 때 그 이미지의 것을 '
                       '저장합니다.' if key != 'bands' else '띠 그래프는 현재 이미지의 것을 저장합니다.')
            h.setWordWrap(True)
            theme.hint(h)
            lay.addWidget(h)
        lay.addStretch()
        theme.unify(page)
        scroll.setWidget(page)
        return scroll

    def _graph_list(self):
        box = QGroupBox('저장할 그래프')
        form = QFormLayout(box)
        self.graph_checks = {}
        docs = self.win.graph_docs()
        for d in docs:
            b = QCheckBox(d.title)
            b.setChecked(bool(d.data and d.data.tables))
            b.setEnabled(bool(d.data and d.data.tables))
            b.toggled.connect(lambda _: self._summary())
            self.graph_checks[d.key] = b
            form.addRow(b)
        if not docs:
            h = QLabel('그래프 편집 창에 그래프가 없습니다 (메뉴 막대의 그래프 메뉴에서 엽니다).')
            h.setWordWrap(True)
            theme.hint(h)
            form.addRow(h)
        return box

    def _image_format(self):
        w = self.win
        box = QGroupBox('시간 · 형식')
        form = QFormLayout(box)
        self.all_times = QCheckBox('타임시리즈는 모든 시점 저장 (끄면 현재 시점만)')
        self.all_times.setChecked(w.exp_all_t.isChecked())
        form.addRow(self.all_times)
        self.rgb_format = QComboBox()
        for k, text in RGB_FORMATS:
            self.rgb_format.addItem(text, k)
        self.rgb_format.setCurrentIndex(max(self.rgb_format.findData(w.exp_format.currentData()), 0))
        form.addRow('타임시리즈 RGB 형식', self.rgb_format)
        self.fps = QSpinBox()
        self.fps.setRange(1, 120)
        self.fps.setValue(int(w.exp_fps.value()))
        self.fps.setSuffix(' fps')
        self.rgb_format.currentIndexChanged.connect(
            lambda _: self.fps.setEnabled(self.rgb_format.currentData() != 'tif'))
        self.fps.setEnabled(self.rgb_format.currentData() != 'tif')
        form.addRow('MP4 속도', self.fps)
        self.markers = QCheckBox('스케일 바 · 시간 표시 넣기 (마커 탭 설정)')
        self.markers.setChecked(bool(self.saved.get('markers', True)))
        form.addRow(self.markers)
        self.checks['composite'].setChecked(w.exp_composite.isChecked())
        self.checks['channels'].setChecked(w.exp_channels.isChecked())
        self.checks['raw'].setChecked(w.exp_raw.isChecked())
        return box

    def _roi_format(self):
        box = QGroupBox('ROI 파일 형식')
        form = QFormLayout(box)
        self.roi_format = QComboBox()
        self.roi_format.addItem('ImageJ RoiSet (.zip)', 'zip')
        self.roi_format.addItem('ROI마다 .roi 파일', 'roi')
        self.roi_format.setCurrentIndex(max(self.roi_format.findData(self.saved.get('roi_format', 'zip')), 0))
        form.addRow('형식', self.roi_format)
        return box

    def _graph_format(self):
        box = QGroupBox('그래프 형식')
        form = QFormLayout(box)
        self.graph_format = QComboBox()
        for k in ('png', 'pdf', 'svg', 'tif'):
            self.graph_format.addItem(k.upper() if k != 'tif' else 'TIFF', k)
        self.graph_format.setCurrentIndex(max(self.graph_format.findData(self.saved.get('graph_format', 'png')), 0))
        form.addRow('그래프 · 그림 형식', self.graph_format)
        h = QLabel('그래프 편집 창의 그래프, 등거리 띠, 라인 프로파일 그래프를 이 형식으로 저장합니다.')
        h.setWordWrap(True)
        theme.hint(h)
        form.addRow(h)
        return box

    # ---- state ----

    def kinds_on(self) -> list[str]:
        return [k for k, it in self.items.items() if it.checkState(0) == Qt.CheckState.Checked]

    def target_items(self) -> list:
        w, t = self.win, self.target.currentData()
        if t == 'current':
            return [w.current] if w.current is not None else []
        if t == 'selected':
            return [w.items[r] for r in w.file_list.selected_rows() if 0 <= r < len(w.items)]
        if t == 'all':
            return list(w.items)
        if isinstance(t, str) and t.startswith('group:'):
            return [it for it in w.items if it.group == t[6:]]
        return []

    def options(self) -> dict:
        kinds = set(self.kinds_on())
        o = {k: (b.isChecked() and self.kind_of[k] in kinds) for k, b in self.checks.items()}
        o.update(per_image=self.per_image.isChecked(), all_times=self.all_times.isChecked(),
                 rgb_format=self.rgb_format.currentData(), fps=self.fps.value(),
                 markers=self.markers.isChecked(), crop_which=self.crop_which.currentData(),
                 roi_format=self.roi_format.currentData(), graph_format=self.graph_format.currentData())
        o['graphs'] = [k for k, b in self.graph_checks.items() if b.isChecked() and b.isEnabled()] \
            if 'graph' in kinds else []
        return o

    def _summary(self):
        for key, it in self.items.items():
            outs = [k for k, kk in self.kind_of.items() if kk == key]
            n_on = sum(self.checks[k].isChecked() for k in outs)
            if key == 'graph':
                n_on = sum(b.isChecked() for b in self.graph_checks.values())
                outs = list(self.graph_checks)
            self.tree.blockSignals(True)
            it.setText(1, f'{n_on}/{len(outs)}')
            self.tree.blockSignals(False)
        kinds = self.kinds_on()
        n = len(self.target_items())
        self.summary.setText(f'{len(kinds)}가지 → {self.target.currentText()}' if n else f'{len(kinds)}가지')
        self.go.setEnabled(bool(kinds))

    def _pick(self):
        d = QFileDialog.getExistingDirectory(self, '저장할 폴더 선택', self.dest.text())
        if d:
            self.dest.setText(d)

    def _remember(self):
        from .settings import view_settings

        w = self.win
        w.opt_per_image.setChecked(self.per_image.isChecked())
        w.exp_composite.setChecked(self.checks['composite'].isChecked())
        w.exp_channels.setChecked(self.checks['channels'].isChecked())
        w.exp_raw.setChecked(self.checks['raw'].isChecked())
        w.exp_all_t.setChecked(self.all_times.isChecked())
        i = w.exp_format.findData(self.rgb_format.currentData())
        if i >= 0:
            w.exp_format.setCurrentIndex(i)
        w.exp_fps.setValue(self.fps.value())
        view_settings.set_defaults('export', {
            'target': self.target.currentData(), 'dest': self.dest.text(), 'kinds': self.kinds_on(),
            'outputs': {k: b.isChecked() for k, b in self.checks.items()}, 'markers': self.markers.isChecked(),
            'crop_which': self.crop_which.currentData(), 'roi_format': self.roi_format.currentData(),
            'graph_format': self.graph_format.currentData()})

    def run(self, ask=True):
        """Write the outputs; returns exporter.Result (None when nothing ran)."""
        from . import exporter

        out = self.dest.text().strip()
        if not out:
            QMessageBox.information(self, '내보내기', '저장 위치를 고르세요.')
            return None
        out = str(Path(out).expanduser())
        items = self.target_items()
        opts = self.options()
        self._remember()
        prog = QProgressDialog('내보내는 중…', '취소', 0, max(len(items), 1), self)
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(300)

        def progress(i, n, label):
            prog.setLabelText(f'내보내는 중: {label}')
            prog.setValue(i)
            QApplication.processEvents()
            return not prog.wasCanceled()

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            res = exporter.run(self.win, items, out, opts, progress)
        finally:
            QApplication.restoreOverrideCursor()
            prog.setValue(prog.maximum())
        self.win.statusBar().showMessage(f'내보내기: 이미지 {len(items)}개, 파일 {len(res.files)}개 → {out}')
        if ask:
            msg = f'파일 {len(res.files)}개를 저장했습니다.\n{out}'
            if res.skipped:
                msg += '\n\n' + '\n'.join(res.skipped)
            if res.errors:
                msg += '\n\n실패:\n' + '\n'.join(res.errors[:20])
            QMessageBox.information(self, '내보내기 완료', msg)
            self.accept()
        return res
