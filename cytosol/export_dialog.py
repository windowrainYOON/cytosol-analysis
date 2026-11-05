"""파일 › 내보내기…: one window for every export of the app (images, crops,
ROIs, measurement tables, graphs, metadata, batch results).

Layout (design system: SettingsPane in a window of its own + Sidebar):
a toolbar on top (target images, destination, the one prominent 내보내기
button: never on the window's bottom edge), a sidebar of export kinds, each
with a check box (included) and how many of its outputs are on, and on the
right the settings cards of the picked kind."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QScrollArea, QSpinBox,
                               QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

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
            ('crop_images', 'Crop 영역마다 이미지 저장', '형태(합성 RGB · 채널별 · 원본값)와 형식은 ‘이미지’ 설정을 따릅니다. 점 편집으로 모양을 바꾼 영역은 '
             '바깥을 0으로 채운 사각형 이미지로 저장합니다.', True),
            ('crop_full', '전체 이미지도 함께 저장', '', True),
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
        ('등거리 띠', [
            ('bands_csv', '띠별 측정 CSV', '', False),
            ('bands_plot', '띠 그래프', '', False),
        ]),
    ]),
    'particle': ('입자 ROI', [
        ('ROI', [
            ('particles', '입자 ROI (.zip)', '', True),
            ('particles_contour', '윤곽 입자 ROI (_particles_contour.zip)', '', False),
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
    'coloc': ('Coloc 2', [
        ('결과', [
            ('coloc_csv', '결과 CSV (ROI마다 한 행)', '', True),
            ('coloc_plot', '그래프', '', False),
            ('coloc_pdf', 'PDF 리포트', '', False),
        ]),
    ]),
    'profile': ('라인 프로파일', [
        ('결과', [
            ('profile_csv', 'CSV', '', True),
            ('profile_plot', '그래프', '', True),
            ('line_roi', '선 ROI (.roi)', '', True),
            ('line_png', '선이 그려진 이미지 (.png)', '', False),
        ]),
    ]),
    'frap': ('FRAP', [
        ('요약', [
            ('frap_summary', '요약 CSV + 그룹 평균 그래프', 'frap_summary.csv, frap_group_curves.csv, '
             'frap_groups.png/.pdf, frap_summary.png', True),
        ]),
        ('이미지마다', [
            ('frap_csv', '곡선 CSV', '', True),
            ('frap_plot', '곡선 그래프', '', True),
            ('frap_rois', 'FRAP ROI (.zip)', '', True),
        ]),
    ]),
    'stack': ('스택 투영', [
        ('투영', [
            ('projection', '현재 투영 (TIFF / MP4)', '', True),
            ('rotation', '3D 회전 시리즈 (TIFF 스택 / MP4)', '스택 탭에서 3D projection이 켜져 있을 때', False),
        ]),
    ]),
    'graph': ('그래프 편집 창', [
        ('열린 그래프', [
            ('g_frap', 'FRAP', '', True),
            ('g_bands', '등거리 띠', '', True),
            ('g_free1', '새 그래프 1', '', False),
        ]),
        ('함께 저장', [
            ('g_data', '그린 데이터 CSV', '', True),
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
            ('batch_results', '고른 분석의 결과 + batch_summary.csv', '', True),
            ('batch_settings', '일괄 분석 설정 (batch_settings.json)', '', True),
        ]),
    ]),
    'project': ('프로젝트 · 작업 기록', [
        ('함께 저장', [
            ('project', '프로젝트 파일 (.cyproj)', '', True),
            ('log', '작업 기록 CSV', '', False),
        ]),
    ]),
}


class ExportDialog(QDialog):
    def __init__(self, parent=None, n_images=10, n_selected=3, kind='crop', on=None):
        super().__init__(parent)
        self.setWindowTitle('내보내기')
        self.resize(880, 600)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 20)
        outer.setSpacing(16)

        # ---- toolbar: target, destination, the one action ----
        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.addWidget(QLabel('대상'))
        self.target = QComboBox()
        self.target.addItems(['현재 이미지', f'선택한 이미지 ({n_selected}개)', f'모든 이미지 ({n_images}개)',
                              '그룹: PRD 24h (4개)'])
        self.target.setCurrentIndex(2)
        bar.addWidget(self.target)
        bar.addSpacing(16)
        bar.addWidget(QLabel('저장 위치'))
        self.dest = QLineEdit('~/Desktop/Cytosol export')
        self.dest.setMinimumWidth(220)
        bar.addWidget(self.dest, 1)
        pick = QPushButton('폴더 선택…')
        bar.addWidget(pick)
        bar.addSpacing(16)
        self.go = theme.prominent(QPushButton('내보내기'))
        self.go.setDefault(True)
        bar.addWidget(self.go)
        outer.addLayout(bar)
        bar2 = QHBoxLayout()
        bar2.addWidget(QCheckBox('이미지별 폴더에 나눠 저장 (<이름>_<이미지 ID>)', checked=True))
        bar2.addStretch()
        self.summary = QLabel('')
        theme.secondary(self.summary)
        bar2.addWidget(self.summary)
        outer.addLayout(bar2)

        body = QHBoxLayout()
        body.setSpacing(20)
        # ---- sidebar of kinds ----
        side = QWidget()
        side.setFixedWidth(230)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 0)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(2)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(0)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        hd = self.tree.header()
        hd.setStretchLastSection(False)
        from PySide6.QtWidgets import QHeaderView
        hd.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hd.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.tree.setColumnWidth(1, 44)
        sl.addWidget(self.tree)
        body.addWidget(side)

        self.pages = QStackedWidget()
        body.addWidget(self.pages, 1)
        outer.addLayout(body, 1)

        on = on or {}
        self.items = {}
        for key, (title, cards) in KINDS.items():
            it = QTreeWidgetItem([title, ''])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(0, Qt.CheckState.Checked if on.get(key, key in ('image', 'crop', 'roi',
                                                                                 'particle', 'graph'))
                             else Qt.CheckState.Unchecked)
            it.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tree.addTopLevelItem(it)
            self.items[key] = it
            self.pages.addWidget(self._page(key, title, cards))
        self.tree.currentItemChanged.connect(
            lambda cur, _p: self.pages.setCurrentIndex(self.tree.indexOfTopLevelItem(cur)))
        self.tree.setCurrentItem(self.items[kind])
        self.items[kind].setSelected(True)
        self.tree.setFocus()
        kinds = [k for k, it in self.items.items() if it.checkState(0) == Qt.CheckState.Checked]
        outs = sum(int(self.items[k].text(1).split('/')[0]) for k in kinds)
        self.summary.setText(f'{len(kinds)}가지 · 파일 종류 {outs}개 → 모든 이미지 {n_images}개')

    def _page(self, key, title, cards):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        page = QWidget()
        lay = QVBoxLayout(page)
        head = QLabel(title)
        theme.text_style(head, 'headline')
        lay.addWidget(head)
        n_on = n_all = 0
        for card_title, outs in cards:
            box = QGroupBox(card_title)
            form = QFormLayout(box)
            for _k, label, tip, default in outs:
                b = QCheckBox(label)
                b.setChecked(default)
                n_all += 1
                n_on += default
                form.addRow(b)
                if tip:
                    h = QLabel(tip)
                    h.setWordWrap(True)
                    theme.hint(h)
                    form.addRow(h)
                    theme.group_rows(b, h)
            if key == 'crop' and card_title == 'Crop 영역 이미지':
                c = QComboBox()
                c.addItems(['모든 Crop 영역', '선택한 Crop 영역만'])
                form.addRow('저장할 Crop', c)
            lay.addWidget(box)
        if key == 'image':
            lay.addWidget(self._image_format())
        if key == 'roi':
            lay.addWidget(self._roi_format())
        if key == 'graph':
            lay.addWidget(self._graph_format())
        lay.addStretch()
        theme.unify(page)
        scroll.setWidget(page)
        self.items[key].setText(1, f'{n_on}/{n_all}')
        return scroll

    def _image_format(self):
        box = QGroupBox('시간 · 형식')
        form = QFormLayout(box)
        form.addRow(QCheckBox('타임시리즈는 모든 시점 저장 (끄면 현재 시점만)', checked=True))
        fmt = QComboBox()
        fmt.addItems(['TIFF', 'MP4'])
        form.addRow('타임시리즈 RGB 형식', fmt)
        fps = QSpinBox()
        fps.setRange(1, 60)
        fps.setValue(10)
        fps.setSuffix(' fps')
        fps.setEnabled(False)
        form.addRow('MP4 속도', fps)
        form.addRow(QCheckBox('스케일 바 · 시간 표시 넣기 (마커 탭 설정)', checked=True))
        return box

    def _crop_pick(self):
        box = QGroupBox('저장할 Crop')
        form = QFormLayout(box)
        c = QComboBox()
        c.addItems(['모든 Crop 영역', '선택한 Crop 영역만'])
        form.addRow('Crop 영역', c)
        h = QLabel('이미지마다 crop1, crop2 … 순서로 저장합니다. 점 편집으로 모양을 바꾼 영역은 바깥을 0으로 '
                   '채운 사각형 이미지로 저장합니다.')
        h.setWordWrap(True)
        theme.hint(h)
        form.addRow(h)
        return box

    def _roi_format(self):
        box = QGroupBox('ROI 파일 형식')
        form = QFormLayout(box)
        c = QComboBox()
        c.addItems(['ImageJ RoiSet (.zip)', 'ROI마다 .roi 파일'])
        form.addRow('형식', c)
        return box

    def _graph_format(self):
        box = QGroupBox('그래프 형식')
        form = QFormLayout(box)
        c = QComboBox()
        c.addItems(['PNG', 'PDF', 'SVG', 'TIFF'])
        form.addRow('그래프 · 그림 형식', c)
        h = QLabel('세포질 ROI, Coloc 2, 라인 프로파일, FRAP의 그래프도 이 형식으로 저장합니다.')
        h.setWordWrap(True)
        theme.hint(h)
        form.addRow(h)
        return box

    def _folders(self):
        box = QGroupBox('폴더 구조 (모든 항목 공통)')
        form = QFormLayout(box)
        form.addRow(QCheckBox('이미지별 폴더에 나눠 저장 (<이름>_<이미지 ID>)', checked=True))
        return box
