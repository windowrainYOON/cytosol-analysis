"""Figure window of Cytosol Viewer: build a labelled image table and export it."""

from __future__ import annotations

import traceback
from pathlib import Path

import numpy as np
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .figure import (
    CORNERS,
    FigureCell,
    FigureSpec,
    Inset,
    color_label,
    fill_row_by_channels,
    figure_to_array,
    inset_from_image,
    inset_to_image,
    installed_families,
    read_inset_rois,
    render_cell,
    save_figure,
    write_inset_rois,
)

THUMB = 110
EXPORT_FILTERS = {
    'PNG (*.png)': '.png',
    'TIFF (*.tif)': '.tif',
    'PDF (*.pdf)': '.pdf',
    'SVG (*.svg)': '.svg',
}


def _qimage(rgb) -> QImage:
    arr = np.ascontiguousarray(rgb if rgb.dtype == np.uint8
                               else (np.clip(rgb, 0, 1) * 255).astype(np.uint8))
    h, w = arr.shape[:2]
    return QImage(arr.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


def _qcolor(rgb) -> QColor:
    return QColor.fromRgbF(*[float(c) for c in rgb])


class LabelDialog(QDialog):
    """Edit a row / column label: text (several lines allowed) and color."""

    def __init__(self, parent, title, label, default_color):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.color = label.color
        self.default_color = default_color
        self.text = QPlainTextEdit(label.text)
        self.text.setMinimumHeight(70)
        self.color_btn = QPushButton('색상…')
        self.color_btn.clicked.connect(self._pick)
        reset = QPushButton('기본 색상')
        reset.clicked.connect(self._reset)
        row = QHBoxLayout()
        row.addWidget(self.color_btn)
        row.addWidget(reset)
        row.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel('이름 (Enter로 줄바꿈)'))
        lay.addWidget(self.text)
        lay.addLayout(row)
        lay.addWidget(buttons)
        self._show_color()

    def _show_color(self):
        c = _qcolor(self.color or self.default_color)
        self.color_btn.setStyleSheet(f'background-color: {c.name()}; color: '
                                     f"{'black' if c.lightness() > 128 else 'white'};")

    def _pick(self):
        c = QColorDialog.getColor(_qcolor(self.color or self.default_color), self, '글자 색상')
        if c.isValid():
            self.color = (c.redF(), c.greenF(), c.blueF())
            self._show_color()

    def _reset(self):
        self.color = None
        self._show_color()

    def value(self):
        return self.text.toPlainText().rstrip('\n'), self.color


class FigureWindow(QMainWindow):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.spec = FigureSpec()
        self.spec.cols[0].text = 'Column 1'
        self._busy = False
        self.setWindowTitle('Figure 만들기 - Cytosol Viewer')
        self.resize(1500, 950)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.update_preview)


        # ---- table ----------------------------------------------------
        self.table = QTableWidget()
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setIconSize(QSize(THUMB, THUMB))
        self.table.currentCellChanged.connect(lambda *_: self._cell_selected())
        for header, kind in ((self.table.horizontalHeader(), 'col'),
                             (self.table.verticalHeader(), 'row')):
            header.sectionDoubleClicked.connect(lambda i, k=kind: self.edit_label(k, i))
            header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            header.customContextMenuRequested.connect(
                lambda pos, h=header, k=kind: self._header_menu(k, h.logicalIndexAt(pos), h, pos))
        self.table.horizontalHeader().setDefaultSectionSize(THUMB + 70)
        self.table.verticalHeader().setDefaultSectionSize(THUMB + 12)

        tb = QHBoxLayout()
        for text, fn in (
            ('행 추가', lambda: self._add('row')),
            ('열 추가', lambda: self._add('col')),
            ('행 삭제', lambda: self._remove('row')),
            ('열 삭제', lambda: self._remove('col')),
            ('행 ▲', lambda: self._move('row', -1)),
            ('행 ▼', lambda: self._move('row', 1)),
            ('열 ◀', lambda: self._move('col', -1)),
            ('열 ▶', lambda: self._move('col', 1)),
        ):
            b = QPushButton(text)
            b.clicked.connect(fn)
            tb.addWidget(b)
        tb.addStretch()
        hint = QLabel('행/열 이름: 머리글 더블클릭 (우클릭 = 메뉴)')
        hint.setStyleSheet('color: gray;')
        tb.addWidget(hint)
        table_box = QWidget()
        tl = QVBoxLayout(table_box)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.addLayout(tb)
        tl.addWidget(self.table, 1)

        # ---- preview --------------------------------------------------
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet('background: #404040;')
        pscroll = QScrollArea()
        pscroll.setWidgetResizable(True)
        pscroll.setWidget(self.preview)
        self.preview_dpi = QComboBox()
        for d in (60, 80, 100, 150, 200):
            self.preview_dpi.addItem(f'{d} dpi', d)
        self.preview_dpi.setCurrentIndex(1)
        self.preview_dpi.currentIndexChanged.connect(lambda _: self.schedule())
        self.preview_info = QLabel()
        pbar = QHBoxLayout()
        pbar.addWidget(QLabel('미리보기'))
        pbar.addWidget(self.preview_dpi)
        pbar.addStretch()
        pbar.addWidget(self.preview_info)
        prev_box = QWidget()
        pl = QVBoxLayout(prev_box)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.addLayout(pbar)
        pl.addWidget(pscroll, 1)

        vsplit = QSplitter(Qt.Orientation.Vertical)
        vsplit.addWidget(table_box)
        vsplit.addWidget(prev_box)
        vsplit.setSizes([380, 520])

        # ---- right: cell editor, layout, export ------------------------
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.addWidget(self._cell_editor())
        rl.addWidget(self._inset_editor())
        rl.addWidget(self._layout_editor())
        rl.addWidget(self._export_box())
        rl.addStretch()
        rscroll = QScrollArea()
        rscroll.setWidgetResizable(True)
        rscroll.setWidget(right)
        rscroll.setMinimumWidth(420)

        split = QSplitter()
        split.addWidget(vsplit)
        split.addWidget(rscroll)
        split.setSizes([1050, 450])
        self.setCentralWidget(split)

        export_act = QAction('Figure 저장…', self)
        export_act.setShortcut('Ctrl+S')
        export_act.triggered.connect(self.export)
        self.menuBar().addMenu('Figure').addAction(export_act)

        self.rebuild_table()
        self.table.setCurrentCell(0, 0)

    # ------------------------------------------------------------------
    # panels
    # ------------------------------------------------------------------

    def _cell_editor(self):
        box = QGroupBox('선택한 칸')
        self.cell_title = QLabel()
        self.src_combo = QComboBox()
        self.src_combo.currentIndexChanged.connect(self._source_changed)
        file_btn = QPushButton('파일…')
        file_btn.setToolTip('PNG/TIFF 이미지 파일을 이 칸에 넣기 (이전에 저장한 LUT/crop TIFF 등)')
        file_btn.clicked.connect(self._load_file)
        self.region_combo = QComboBox()
        self.region_combo.currentIndexChanged.connect(self._region_changed)
        self.merged_chk = QCheckBox('메인 창 표시 채널 따르기')
        self.merged_chk.setToolTip('켜면 메인 창의 채널 표시 상태를 그대로 사용합니다.\n'
                                   '아래 채널 체크박스를 바꾸면 이 칸만의 조합으로 바뀝니다.')
        self.merged_chk.toggled.connect(self._channels_changed)
        # one checkbox per channel (color swatch + name), any combination per cell
        self.chan_box = QGroupBox('채널 조합')
        chan_lay = QVBoxLayout(self.chan_box)
        self.chan_grid = QGridLayout()
        chan_lay.addLayout(self.chan_grid)
        self.chan_checks: list[QCheckBox] = []
        chan_buttons = QHBoxLayout()
        chan_buttons.addWidget(self.merged_chk)
        chan_buttons.addStretch()
        all_on = QPushButton('모두 켜기')
        all_off = QPushButton('모두 끄기')
        all_on.clicked.connect(lambda: self._set_all_channels(True))
        all_off.clicked.connect(lambda: self._set_all_channels(False))
        chan_buttons.addWidget(all_on)
        chan_buttons.addWidget(all_off)
        chan_lay.addLayout(chan_buttons)

        fill_row = QPushButton('이 행을 채널별 + Merged로 채우기')
        fill_row.setToolTip('선택한 이미지/영역의 각 채널을 열마다 넣고 마지막 열에 합성 이미지')
        fill_row.clicked.connect(self.fill_row)
        name_cols = QPushButton('열 이름을 채널 이름/색으로')
        name_cols.clicked.connect(self.name_cols)
        same_src = QPushButton('이 행의 다른 칸도 같은 이미지/영역으로')
        same_src.setToolTip('채널 선택은 그대로 두고 이미지와 crop 영역만 바꿈')
        same_src.clicked.connect(self.source_to_row)
        clear = QPushButton('칸 비우기')
        clear.clicked.connect(self.clear_cell)

        src_row = QHBoxLayout()
        src_row.addWidget(self.src_combo, 1)
        src_row.addWidget(file_btn)
        form = QFormLayout()
        form.addRow('이미지', src_row)
        form.addRow('영역', self.region_combo)
        lay = QVBoxLayout(box)
        lay.addWidget(self.cell_title)
        lay.addLayout(form)
        lay.addWidget(self.chan_box)
        row = QHBoxLayout()
        row.addWidget(fill_row)
        row.addWidget(name_cols)
        lay.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(same_src)
        row.addWidget(clear)
        lay.addLayout(row)
        return box

    def _inset_editor(self):
        from .app import Canvas

        box = QGroupBox('확대 영역 (inset)')
        self.cell_canvas = Canvas()
        self.cell_canvas.setMinimumHeight(260)
        self.cell_canvas.cropDrawn.connect(self._inset_drawn)
        self.inset_btn = QPushButton('확대 영역 그리기 (드래그)')
        self.inset_btn.setCheckable(True)
        self.inset_btn.setToolTip('누른 뒤 이미지 위에서 드래그합니다. Shift + 드래그: 정사각형.')
        self.inset_btn.toggled.connect(self.cell_canvas.set_crop_mode)
        self.inset_list = QListWidget()
        self.inset_list.setMaximumHeight(70)
        self.inset_list.currentRowChanged.connect(self._inset_selected)
        self.placement = QComboBox()
        self.placement.addItem('이미지 안 (모서리에 겹쳐서)', 'inside')
        self.placement.addItem('다른 칸에 따로', 'cell')
        self.placement.currentIndexChanged.connect(self._placement_changed)
        self.target = QComboBox()
        self.target.setToolTip('확대본을 넣을 칸. 이미 이미지가 있는 칸을 고르면 덮어씁니다.')
        self.target.activated.connect(self._target_chosen)
        self.corner = QComboBox()
        for c, ko in zip(CORNERS, ['왼쪽 위', '오른쪽 위', '왼쪽 아래', '오른쪽 아래']):
            self.corner.addItem(ko, c)
        self.corner.currentIndexChanged.connect(self._inset_changed)
        self.inset_size = QSpinBox()
        self.inset_size.setRange(10, 100)
        self.inset_size.setValue(45)
        self.inset_size.setSuffix(' % (칸 너비 대비)')
        self.inset_size.valueChanged.connect(self._inset_changed)
        del_btn = QPushButton('삭제')
        del_btn.clicked.connect(self._delete_inset)
        row_btn = QPushButton('이 행 전체에 적용')
        row_btn.setToolTip('같은 위치의 확대 영역을 이 행의 모든 칸에 똑같이 넣기')
        row_btn.clicked.connect(lambda: self._insets_to('row'))
        col_btn = QPushButton('이 열 전체에 적용')
        col_btn.clicked.connect(lambda: self._insets_to('col'))
        save_roi = QPushButton('ROI 저장…')
        save_roi.setToolTip('선택한 확대 영역을 ImageJ .roi로 저장 (.zip을 고르면 이 칸의 모든 영역).\n'
                            '좌표는 원본 이미지 기준이라 ImageJ에서 그대로 열 수 있습니다.')
        save_roi.clicked.connect(self._save_inset_roi)
        load_roi = QPushButton('ROI 불러오기…')
        load_roi.setToolTip('ImageJ .roi / RoiSet .zip의 영역(사각형 범위)을 이 칸의 확대 영역으로 추가')
        load_roi.clicked.connect(self._load_inset_roi)
        copy_btn = QPushButton('영역 복사')
        copy_btn.setToolTip('선택한 확대 영역(위치, 크기, 표시 방식)을 복사')
        copy_btn.clicked.connect(self._copy_inset)
        self.paste_btn = QPushButton('붙여넣기')
        self.paste_btn.setToolTip('복사한 영역을 지금 선택한 칸에 붙여넣기 (원본 이미지의 같은 위치)')
        self.paste_btn.clicked.connect(self._paste_inset)
        self.paste_many_btn = QPushButton('여러 칸에 붙여넣기…')
        self.paste_many_btn.setToolTip('복사한 영역을 고른 여러 이미지 칸에 한꺼번에 붙여넣기')
        self.paste_many_btn.clicked.connect(self._paste_inset_many)
        self._inset_clip = None  # (rect in source-image pixels, Inset template)
        self._update_paste_buttons()

        form = QFormLayout()
        form.addRow('표시 방식', self.placement)
        form.addRow('넣을 칸', self.target)
        form.addRow('모서리', self.corner)
        form.addRow('크기', self.inset_size)
        lay = QVBoxLayout(box)
        lay.addWidget(self.cell_canvas, 1)
        lay.addWidget(self.inset_btn)
        lay.addWidget(self.inset_list)
        lay.addLayout(form)
        row = QHBoxLayout()
        row.addWidget(del_btn)
        row.addWidget(row_btn)
        row.addWidget(col_btn)
        lay.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(save_roi)
        row.addWidget(load_roi)
        lay.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(copy_btn)
        row.addWidget(self.paste_btn)
        row.addWidget(self.paste_many_btn)
        lay.addLayout(row)
        return box

    def _layout_editor(self):
        box = QGroupBox('레이아웃')
        s = self.spec
        self.bg_black = QRadioButton('검은 배경')
        self.bg_white = QRadioButton('흰 배경')
        self.bg_black.setChecked(True)
        grp = QButtonGroup(box)
        grp.addButton(self.bg_black)
        grp.addButton(self.bg_white)
        self.bg_black.toggled.connect(self._layout_changed)
        self.border = QCheckBox('칸 테두리')
        self.border.setChecked(s.border)
        self.cell_in = QDoubleSpinBox()
        self.cell_in.setRange(0.3, 10)
        self.cell_in.setSingleStep(0.1)
        self.cell_in.setValue(s.cell_in)
        self.cell_in.setSuffix(' inch')
        self.aspect = QDoubleSpinBox()
        self.aspect.setRange(0, 5)
        self.aspect.setSingleStep(0.05)
        self.aspect.setSpecialValueText('자동 (첫 이미지)')
        self.gap = QDoubleSpinBox()
        self.gap.setRange(0, 1)
        self.gap.setSingleStep(0.01)
        self.gap.setDecimals(3)
        self.gap.setValue(s.gap_in)
        self.gap.setSuffix(' inch')
        self.font = QComboBox()
        fams = installed_families()
        prefer = [f for f in ('Arial', 'Helvetica', 'Helvetica Neue', 'Apple SD Gothic Neo',
                              'DejaVu Sans') if f in fams]
        self.font.addItems(prefer + [f for f in fams if f not in prefer])
        self.font.setCurrentText(prefer[0] if prefer else s.font_family)
        self.font_pt = QDoubleSpinBox()
        self.font_pt.setRange(4, 40)
        self.font_pt.setValue(s.font_pt)
        self.font_pt.setSuffix(' pt')
        self.bold = QCheckBox('굵게')
        self.bold.setChecked(s.bold)

        self.sb = QCheckBox('Scale bar')
        self.sb.setChecked(s.scale_bar)
        self.sb_um = QDoubleSpinBox()
        self.sb_um.setRange(0, 10000)
        self.sb_um.setSpecialValueText('자동')
        self.sb_um.setSuffix(' µm')
        self.sb_pos = QComboBox()
        self.sb_pos.addItems(['lower right', 'lower left', 'upper right', 'upper left'])
        self.sb_label = QCheckBox('칸마다 길이 글자')
        self.caption = QCheckBox('아래에 "(Scale bar = … µm)"')
        self.caption.setChecked(s.caption)
        self.inset_sb = QCheckBox('Inset에도 scale bar')
        self.inset_sb.setChecked(s.inset_scale_bar)
        self.inset_um = QDoubleSpinBox()
        self.inset_um.setRange(0, 10000)
        self.inset_um.setSpecialValueText('자동')
        self.inset_um.setSuffix(' µm')
        self.inset_color = QPushButton()
        self.inset_color.setFixedWidth(40)
        self.inset_color.clicked.connect(self._pick_inset_color)

        for w in (self.border, self.bold, self.sb, self.sb_label, self.caption, self.inset_sb):
            w.toggled.connect(self._layout_changed)
        for w in (self.cell_in, self.aspect, self.gap, self.font_pt, self.sb_um, self.inset_um):
            w.valueChanged.connect(self._layout_changed)
        for w in (self.font, self.sb_pos):
            w.currentIndexChanged.connect(self._layout_changed)

        def hrow(*ws):
            r = QHBoxLayout()
            for w in ws:
                r.addWidget(w)
            r.addStretch()
            return r

        form = QFormLayout(box)
        form.addRow('배경', hrow(self.bg_black, self.bg_white, self.border))
        form.addRow('칸 너비', self.cell_in)
        form.addRow('세로/가로 비', self.aspect)
        form.addRow('칸 간격', self.gap)
        form.addRow('글꼴', self.font)
        form.addRow('글자 크기', hrow(self.font_pt, self.bold))
        form.addRow(hrow(self.sb, self.sb_um, self.sb_pos))
        form.addRow(hrow(self.sb_label, self.caption))
        form.addRow(hrow(self.inset_sb, self.inset_um, QLabel('상자 색'), self.inset_color))
        self._layout_changed()
        return box

    def _export_box(self):
        box = QGroupBox('내보내기')
        self.dpi = QSpinBox()
        self.dpi.setRange(72, 2400)
        self.dpi.setValue(300)
        self.dpi.setSuffix(' dpi')
        btn = QPushButton('Figure 저장… (PNG / TIFF / PDF / SVG)')
        btn.clicked.connect(self.export)
        lay = QHBoxLayout(box)
        lay.addWidget(QLabel('해상도'))
        lay.addWidget(self.dpi)
        lay.addWidget(btn, 1)
        return box

    # ------------------------------------------------------------------
    # table
    # ------------------------------------------------------------------

    def items(self):
        return self.main.items

    def current_rc(self):
        r, c = self.table.currentRow(), self.table.currentColumn()
        if r < 0 or c < 0:
            return 0, 0
        return min(r, self.spec.nrows - 1), min(c, self.spec.ncols - 1)

    def current_cell(self) -> FigureCell:
        r, c = self.current_rc()
        return self.spec.cells[r][c]

    def rebuild_table(self):
        s = self.spec
        r0, c0 = self.current_rc()
        self.table.blockSignals(True)
        self.table.setRowCount(s.nrows)
        self.table.setColumnCount(s.ncols)
        for i, lab in enumerate(s.cols):
            h = QTableWidgetItem(lab.text or ' ')
            if lab.color:
                h.setForeground(_qcolor(lab.color))
            self.table.setHorizontalHeaderItem(i, h)
        for i, lab in enumerate(s.rows):
            h = QTableWidgetItem(lab.text or ' ')
            if lab.color:
                h.setForeground(_qcolor(lab.color))
            self.table.setVerticalHeaderItem(i, h)
        for r in range(s.nrows):
            for c in range(s.ncols):
                self._refresh_cell(r, c)
        self.table.setCurrentCell(min(r0, s.nrows - 1), min(c0, s.ncols - 1))
        self.table.blockSignals(False)
        self._cell_selected()
        self.schedule()

    def _refresh_cell(self, r, c):
        cell = self.spec.cells[r][c]
        desc = cell.describe()
        it = QTableWidgetItem(desc.split('\n')[-1] if desc else '(비어 있음)')
        it.setToolTip(desc)
        if not cell.empty:
            try:
                h = max(1, round(THUMB * self.spec.cell_aspect()))
                it.setIcon(QIcon(QPixmap.fromImage(_qimage(
                    render_cell(cell, self.spec, THUMB, h, None, None)))))
            except Exception:
                traceback.print_exc()
        self.table.setItem(r, c, it)

    def _add(self, kind):
        r, c = self.current_rc()
        if kind == 'row':
            self.spec.add_row(r + 1)
            self.rebuild_table()
            self.table.setCurrentCell(r + 1, c)
        else:
            self.spec.add_col(c + 1)
            self.rebuild_table()
            self.table.setCurrentCell(r, c + 1)

    def _remove(self, kind, index=None):
        r, c = self.current_rc()
        if kind == 'row':
            self.spec.remove_row(r if index is None else index)
        else:
            self.spec.remove_col(c if index is None else index)
        self.rebuild_table()

    def _move(self, kind, step):
        r, c = self.current_rc()
        if kind == 'row':
            self.spec.move_row(r, step)
            r = max(0, min(self.spec.nrows - 1, r + step))
        else:
            self.spec.move_col(c, step)
            c = max(0, min(self.spec.ncols - 1, c + step))
        self.rebuild_table()
        self.table.setCurrentCell(r, c)

    def edit_label(self, kind, index):
        if index < 0:
            return
        labels = self.spec.rows if kind == 'row' else self.spec.cols
        lab = labels[index]
        dlg = LabelDialog(self, '행 이름' if kind == 'row' else '열 이름', lab, self.spec.text_color)
        if dlg.exec():
            lab.text, lab.color = dlg.value()
            self.rebuild_table()

    def _header_menu(self, kind, index, header, pos):
        if index < 0:
            return
        menu = QMenu(self)
        menu.addAction('이름/색상 수정…', lambda: self.edit_label(kind, index))
        if kind == 'row':
            menu.addAction('위에 행 삽입', lambda: (self.spec.add_row(index), self.rebuild_table()))
            menu.addAction('아래에 행 삽입',
                           lambda: (self.spec.add_row(index + 1), self.rebuild_table()))
            menu.addAction('행 삭제', lambda: self._remove('row', index))
        else:
            menu.addAction('왼쪽에 열 삽입', lambda: (self.spec.add_col(index), self.rebuild_table()))
            menu.addAction('오른쪽에 열 삽입',
                           lambda: (self.spec.add_col(index + 1), self.rebuild_table()))
            menu.addAction('열 삭제', lambda: self._remove('col', index))
        menu.exec(header.mapToGlobal(pos))

    # ------------------------------------------------------------------
    # cell editor
    # ------------------------------------------------------------------

    def refresh_sources(self):
        """Re-read the main window's image list (called when the window is shown)."""
        items = self.items()
        for row in self.spec.cells:
            for k, cell in enumerate(row):
                if cell.item is not None and cell.item not in items:
                    row[k] = FigureCell()
        self.rebuild_table()

    def _cell_selected(self):
        if self.table.rowCount() == 0:
            return
        r, c = self.current_rc()
        cell = self.current_cell()
        self._busy = True
        rl = self.spec.rows[r].text.replace('\n', ' ')
        cl = self.spec.cols[c].text.replace('\n', ' ')
        self.cell_title.setText(f'<b>{rl} / {cl}</b>  (행 {r + 1}, 열 {c + 1})')
        self.src_combo.clear()
        self.src_combo.addItem('(비어 있음)', None)
        for i, it in enumerate(self.items()):
            self.src_combo.addItem(it.label, i)
        if cell.is_zoom:
            self.src_combo.addItem('확대 칸 (원본 칸의 확대 영역)', 'zoom')
            self.src_combo.setCurrentIndex(self.src_combo.count() - 1)
        elif cell.rgb is not None:
            self.src_combo.addItem(f'파일: {cell.name}', 'file')
            self.src_combo.setCurrentIndex(self.src_combo.count() - 1)
        elif cell.item is not None and cell.item in self.items():
            self.src_combo.setCurrentIndex(self.items().index(cell.item) + 1)
        self._fill_region_and_channels(cell)
        self._busy = False
        self._show_cell_canvas(refit=True)

    def _fill_region_and_channels(self, cell):
        self.region_combo.clear()
        for chk in self.chan_checks:
            chk.setParent(None)
            chk.deleteLater()
        self.chan_checks = []
        has_item = cell.item is not None
        self.region_combo.setEnabled(has_item)
        self.chan_box.setEnabled(has_item)
        if not has_item:
            self.merged_chk.setChecked(False)
            return
        self.region_combo.addItem('전체 이미지', None)
        for k, reg in enumerate(cell.item.crops, 1):
            x0, y0, x1, y1 = reg
            self.region_combo.addItem(f'Crop {k} ({x1 - x0}×{y1 - y0})', reg)
        if cell.region is not None and cell.region not in cell.item.crops:
            self.region_combo.addItem('Crop (삭제된 영역)', cell.region)
        idx = self.region_combo.findData(cell.region) if cell.region is not None else 0
        self.region_combo.setCurrentIndex(max(idx, 0))
        self.merged_chk.setChecked(cell.channels is None)
        for i, name in enumerate(cell.item.channels):
            chk = QCheckBox(name)
            swatch = QPixmap(16, 16)
            swatch.fill(_qcolor(cell.item.luts[i].color))
            chk.setIcon(QIcon(swatch))
            on = cell.item.luts[i].visible if cell.channels is None else i in cell.channels
            chk.setChecked(on)
            chk.toggled.connect(self._channel_toggled)
            self.chan_grid.addWidget(chk, i // 2, i % 2)
            self.chan_checks.append(chk)

    def _checked_channels(self):
        return [i for i, chk in enumerate(self.chan_checks) if chk.isChecked()]

    def _channel_toggled(self, *_):
        if self._busy:
            return
        # picking channels by hand gives this cell its own combination
        self._busy = True
        self.merged_chk.setChecked(False)
        self._busy = False
        self._channels_changed()

    def _set_all_channels(self, on: bool):
        if not self.chan_checks:
            return
        self._busy = True
        for chk in self.chan_checks:
            chk.setChecked(on)
        self.merged_chk.setChecked(False)
        self._busy = False
        self._channels_changed()

    def _cell_changed(self, insets_valid=True):
        cell = self.current_cell()
        if not insets_valid:
            for ins in cell.insets:
                self.spec.unlink_inset(ins)
            cell.insets = []
        r, c = self.current_rc()
        self._refresh_cell(r, c)
        # zoom cells that show part of this one
        for rr, row in enumerate(self.spec.cells):
            for cc, other in enumerate(row):
                if other.zoom_src is cell:
                    self._refresh_cell(rr, cc)
        self._show_cell_canvas(refit=not insets_valid)
        self.schedule()

    def _source_changed(self, _):
        if self._busy:
            return
        data = self.src_combo.currentData()
        cell = self.current_cell()
        if data in ('file', 'zoom'):
            return
        if data is None:
            cell.copy_from(FigureCell())
        else:
            item = self.items()[data]
            if item is cell.item:
                return
            cell.copy_from(FigureCell(item=item), insets=False)
            cell.insets = []
        self._busy = True
        self._fill_region_and_channels(cell)
        self._busy = False
        self._cell_changed(insets_valid=False)

    def _region_changed(self, _):
        if self._busy:
            return
        cell = self.current_cell()
        cell.region = self.region_combo.currentData()
        self._cell_changed(insets_valid=False)

    def _channels_changed(self, *_):
        if self._busy:
            return
        cell = self.current_cell()
        if cell.item is None:
            return
        if self.merged_chk.isChecked():
            cell.channels = None
            # show what the main window displays now
            self._busy = True
            for i, chk in enumerate(self.chan_checks):
                chk.setChecked(cell.item.luts[i].visible)
            self._busy = False
        else:
            cell.channels = self._checked_channels()
        self._cell_changed()

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '이미지 파일', '', 'Images (*.tif *.tiff *.png *.jpg *.jpeg);;All files (*)')
        if not path:
            return
        try:
            rgb, px = load_rgb_file(path)
        except Exception as exc:
            QMessageBox.warning(self, '불러오기 실패', str(exc))
            return
        cell = self.current_cell()
        cell.copy_from(FigureCell(rgb=rgb, rgb_pixel_um=px, name=Path(path).name), insets=False)
        cell.insets = []
        self._cell_selected()
        self._cell_changed(insets_valid=False)

    def clear_cell(self):
        self.current_cell().copy_from(FigureCell())
        self._cell_selected()
        self._cell_changed(insets_valid=False)

    def fill_row(self):
        cell = self.current_cell()
        if cell.item is None:
            QMessageBox.information(self, 'Figure', '먼저 이 칸에 이미지를 선택하세요.')
            return
        r, _ = self.current_rc()
        fill_row_by_channels(self.spec, r, cell.item, cell.region)
        self.rebuild_table()

    def name_cols(self):
        """Column titles from the channels shown in the current row."""
        r, _ = self.current_rc()
        for c, cell in enumerate(self.spec.cells[r]):
            if cell.item is None:
                continue
            n_ch = len(cell.item.channels)
            if cell.channels is None or len(cell.channels) == n_ch:
                self.spec.cols[c].text, self.spec.cols[c].color = 'Merged', None
            elif len(cell.channels) > 1:
                names = [cell.item.channels[k] for k in cell.channels]
                self.spec.cols[c].text, self.spec.cols[c].color = ' + '.join(names), None
            elif len(cell.channels) == 1:
                k = cell.channels[0]
                self.spec.cols[c].text = cell.item.channels[k]
                self.spec.cols[c].color = color_label(cell.item, k)
        self.rebuild_table()

    def source_to_row(self):
        src = self.current_cell()
        r, c0 = self.current_rc()
        for c, cell in enumerate(self.spec.cells[r]):
            if c == c0:
                continue
            channels = cell.channels
            if cell.item is not None and src.item is not None and \
                    cell.item.channels != src.item.channels:
                channels = None
            cell.copy_from(src, insets=False)
            cell.channels = None if channels is None else list(channels)
            cell.insets = []
        self.rebuild_table()

    # ------------------------------------------------------------------
    # insets
    # ------------------------------------------------------------------

    def _show_cell_canvas(self, refit=False):
        cell = self.current_cell()
        if cell.empty:
            self.cell_canvas.pix.setPixmap(QPixmap())
            self.cell_canvas.show_crops([])
        else:
            self.cell_canvas.set_image(_qimage(cell.image()), refit=refit)
            if refit:
                self.cell_canvas.fit()
            sel = self.inset_list.currentRow()
            self.cell_canvas.show_crops([i.rect for i in cell.insets], sel if sel >= 0 else None)
        self._refresh_inset_list()

    def _refresh_inset_list(self, select=None):
        cell = self.current_cell()
        row = self.inset_list.currentRow() if select is None else select
        self.inset_list.blockSignals(True)
        self.inset_list.clear()
        for k, i in enumerate(cell.insets, 1):
            x0, y0, x1, y1 = i.rect
            where = '이미지 안'
            if i.placement == 'cell':
                pos = [self.spec.find(z) for z in self.spec.zoom_cells(i)]
                where = (f'행 {pos[0][0] + 1}, 열 {pos[0][1] + 1} 칸' if pos and pos[0]
                         else '연결된 칸 없음')
            self.inset_list.addItem(f'{k}: x {x0}–{x1}, y {y0}–{y1}  → {where}')
        if cell.insets:
            self.inset_list.setCurrentRow(max(0, min(row, len(cell.insets) - 1)))
        self.inset_list.blockSignals(False)
        self._inset_selected(self.inset_list.currentRow(), redraw=False)

    def _inset_selected(self, row, redraw=True):
        cell = self.current_cell()
        ins = cell.insets[row] if 0 <= row < len(cell.insets) else None
        self._busy = True
        if ins is not None:
            self.placement.setCurrentIndex(max(0, self.placement.findData(ins.placement)))
            self.corner.setCurrentIndex(max(0, self.corner.findData(ins.corner)))
            self.inset_size.setValue(round(ins.size * 100))
        self._fill_targets(ins)
        self._busy = False
        if redraw:
            self.cell_canvas.show_crops([i.rect for i in cell.insets], row if row >= 0 else None)

    def _inset_drawn(self, x0, y0, x1, y1):
        self.inset_btn.setChecked(False)
        cell = self.current_cell()
        if cell.empty:
            return
        H, W = cell.shape()
        x0, x1 = sorted((int(np.clip(round(x0), 0, W)), int(np.clip(round(x1), 0, W))))
        y0, y1 = sorted((int(np.clip(round(y0), 0, H)), int(np.clip(round(y1), 0, H))))
        if x1 - x0 < 3 or y1 - y0 < 3:
            return
        inset = Inset((x0, y0, x1, y1), self.corner.currentData(),
                      self.inset_size.value() / 100, self.placement.currentData())
        cell.insets.append(inset)
        if inset.placement == 'cell':
            self._link_default(cell, inset)
            self.rebuild_table()
        self._refresh_inset_list(select=len(cell.insets) - 1)
        self._cell_changed()

    # ---- .roi files and copy / paste ------------------------------------

    def _new_inset(self, rect, template=None):
        t = template
        return Inset(rect, t.corner if t else self.corner.currentData(),
                     t.size if t else self.inset_size.value() / 100,
                     t.placement if t else self.placement.currentData(),
                     t.offset if t else (0, 1))

    def _add_insets(self, cell, rects, template=None, current=True) -> tuple[int, int]:
        """Add insets for source-image rects to cell; (added, put inside instead of a cell)."""
        added, blocked = 0, 0
        for rect in rects:
            local = inset_from_image(cell, rect)
            if local is None:
                continue
            ins = self._new_inset(local, template)
            cell.insets.append(ins)
            added += 1
            if ins.placement != 'cell':
                continue
            if current:
                self._link_default(cell, ins)
            elif not self.spec.link_inset(cell, ins, overwrite=False):
                ins.placement = 'inside'
                blocked += 1
        return added, blocked

    def _save_inset_roi(self):
        cell = self.current_cell()
        ins = self._current_inset()
        if cell.empty or ins is None:
            QMessageBox.information(self, '확대 영역', '저장할 확대 영역을 먼저 그리거나 고르세요.')
            return
        base = Path(cell.item.label if cell.item is not None else (cell.name or 'inset')).stem
        k = self.inset_list.currentRow() + 1
        path, flt = QFileDialog.getSaveFileName(
            self, '확대 영역 ROI 저장', f'{base}_inset{k}.roi',
            'ImageJ ROI (*.roi);;이 칸의 모든 영역 RoiSet (*.zip)')
        if not path:
            return
        if Path(path).suffix.lower() not in ('.roi', '.zip'):
            path += '.zip' if 'zip' in flt else '.roi'
        if Path(path).suffix.lower() == '.zip':
            rects = [inset_to_image(cell, i.rect) for i in cell.insets]
            names = [f'{base}_inset{j}' for j in range(1, len(rects) + 1)]
        else:
            rects = [inset_to_image(cell, ins.rect)]
            names = [f'{base}_inset{k}']
        try:
            write_inset_rois(path, rects, names)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, '저장 실패', str(exc))
            return
        self.statusBar().showMessage(f'확대 영역 {len(rects)}개 저장: {path}')

    def _load_inset_roi(self):
        cell = self.current_cell()
        if cell.empty or cell.is_zoom:
            QMessageBox.information(self, '확대 영역', '먼저 이미지가 있는 칸을 고르세요.')
            return
        path, _ = QFileDialog.getOpenFileName(
            self, '확대 영역 ROI 불러오기', '', 'ImageJ ROI (*.roi *.zip);;All files (*)')
        if not path:
            return
        try:
            rects = read_inset_rois(path)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, '불러오기 실패', str(exc))
            return
        n, _ = self._add_insets(cell, rects)
        if not n:
            QMessageBox.information(self, '확대 영역', 'ROI 영역이 이 이미지 안에 없습니다.')
            return
        self.rebuild_table()
        self._refresh_inset_list(select=len(cell.insets) - 1)
        self._cell_changed()
        self.statusBar().showMessage(f'확대 영역 {n}개 불러옴: {path}')

    def _update_paste_buttons(self):
        on = self._inset_clip is not None
        self.paste_btn.setEnabled(on)
        self.paste_many_btn.setEnabled(on)

    def _copy_inset(self):
        cell = self.current_cell()
        ins = self._current_inset()
        if cell.empty or ins is None:
            QMessageBox.information(self, '확대 영역', '복사할 확대 영역을 먼저 고르세요.')
            return
        self._inset_clip = (inset_to_image(cell, ins.rect), ins.copy())
        self._update_paste_buttons()
        x0, y0, x1, y1 = self._inset_clip[0]
        self.statusBar().showMessage(f'확대 영역 복사: x {x0}–{x1}, y {y0}–{y1}')

    def _paste_inset(self):
        if self._inset_clip is None:
            return
        cell = self.current_cell()
        if cell.empty or cell.is_zoom:
            QMessageBox.information(self, '확대 영역', '붙여넣을 이미지 칸을 고르세요.')
            return
        rect, template = self._inset_clip
        n, _ = self._add_insets(cell, [rect], template)
        if not n:
            QMessageBox.information(self, '확대 영역', '복사한 영역이 이 이미지 안에 없습니다.')
            return
        self.rebuild_table()
        self._refresh_inset_list(select=len(cell.insets) - 1)
        self._cell_changed()
        self.statusBar().showMessage('확대 영역을 붙여넣었습니다.')

    def _paste_inset_many(self):
        if self._inset_clip is None:
            return
        cells = [(r, c, cell) for r, row in enumerate(self.spec.cells)
                 for c, cell in enumerate(row) if not cell.empty and not cell.is_zoom]
        if not cells:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle('여러 칸에 붙여넣기')
        lst = QListWidget()
        cur = self.current_cell()
        for r, c, cell in cells:
            desc = cell.describe().replace('\n', ' · ')
            it = QListWidgetItem(f'행 {r + 1}, 열 {c + 1}: {desc}')
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Unchecked if cell is cur else Qt.CheckState.Checked)
            lst.addItem(it)
        replace = QCheckBox('그 칸의 기존 확대 영역 지우고 넣기')
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel('복사한 영역을 넣을 칸 (원본 이미지의 같은 위치):'))
        lay.addWidget(lst)
        lay.addWidget(replace)
        lay.addWidget(buttons)
        dlg.resize(460, 360)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        rect, template = self._inset_clip
        n, missed, blocked = 0, 0, 0
        for k, (_, _, cell) in enumerate(cells):
            if lst.item(k).checkState() != Qt.CheckState.Checked:
                continue
            if replace.isChecked():
                for old in cell.insets:
                    olds = self.spec.zoom_cells(old)
                    self.spec.unlink_inset(old)
                    self._drop_empty_lines(olds)
                cell.insets = []
            added, b = self._add_insets(cell, [rect], template, current=False)
            n += added
            missed += 1 - added
            blocked += b
        self.rebuild_table()
        msg = f'확대 영역을 칸 {n}개에 붙여넣었습니다.'
        if missed:
            msg += f' {missed}개 칸은 영역이 이미지 밖이라 건너뛰었습니다.'
        if blocked:
            msg += f' 넣을 칸이 이미 차 있어서 {blocked}개는 이미지 안에 넣었습니다.'
        self.statusBar().showMessage(msg)

    # ---- inset in its own cell ------------------------------------------

    def _current_inset(self):
        cell = self.current_cell()
        row = self.inset_list.currentRow()
        return cell.insets[row] if 0 <= row < len(cell.insets) else None

    def _fill_targets(self, ins):
        """List the cells an inset can be shown in, plus 'insert a column/row'."""
        self.target.clear()
        cell_mode = ins is not None and ins.placement == 'cell'
        self.target.setEnabled(cell_mode)
        self.corner.setEnabled(not cell_mode)
        self.inset_size.setEnabled(not cell_mode)
        if not cell_mode:
            return
        r0, c0 = self.current_rc()
        self.target.addItem('오른쪽에 새 열 삽입', 'insert-col')
        self.target.addItem('아래에 새 행 삽입', 'insert-row')
        current = [self.spec.find(z) for z in self.spec.zoom_cells(ins)]
        for r in range(self.spec.nrows):
            for c in range(self.spec.ncols):
                if (r, c) == (r0, c0):
                    continue
                cell = self.spec.cells[r][c]
                rl = self.spec.rows[r].text.replace('\n', ' ')
                cl = self.spec.cols[c].text.replace('\n', ' ')
                state = '' if cell.empty else (' · 확대 칸' if cell.is_zoom else ' · 이미지 있음')
                self.target.addItem(f'행 {r + 1}, 열 {c + 1}  ({rl} / {cl}){state}', f'{r},{c}')
                if (r, c) in current:
                    self.target.setCurrentIndex(self.target.count() - 1)
        if not current:
            self.target.setCurrentIndex(-1)

    def _drop_empty_lines(self, cells):
        """Remove a row/column that held only the given (old zoom) cells and is now blank."""
        for cell in cells:
            pos = self.spec.find(cell)
            if pos is None or not cell.empty:
                continue
            r, c = pos
            if all(row[c].empty for row in self.spec.cells) and not self.spec.cols[c].text:
                self.spec.remove_col(c)
            elif all(x.empty for x in self.spec.cells[r]) and not self.spec.rows[r].text:
                self.spec.remove_row(r)

    def _link_to(self, src, inset, choice, ask=True) -> bool:
        pos = self.spec.find(src)
        if pos is None:
            return False
        old = self.spec.zoom_cells(inset)
        ok = self._link(src, inset, choice, pos, ask)
        if ok:
            self._drop_empty_lines([o for o in old if o.zoom_inset is not inset])
        return ok

    def _link(self, src, inset, choice, pos, ask) -> bool:
        r0, c0 = pos
        if choice == 'insert-col':
            self.spec.add_col(c0 + 1, text='')
            inset.offset = (0, 1)
        elif choice == 'insert-row':
            self.spec.add_row(r0 + 1, text='')
            inset.offset = (1, 0)
        else:
            r, c = (int(v) for v in choice.split(','))
            target = self.spec.cells[r][c]
            if ask and not target.empty and target.zoom_inset is not inset:
                ans = QMessageBox.question(
                    self, '확대 영역', f'행 {r + 1}, 열 {c + 1} 칸의 내용을 확대본으로 바꿀까요?')
                if ans != QMessageBox.StandardButton.Yes:
                    return False
            inset.offset = (r - r0, c - c0)
        return self.spec.link_inset(src, inset)

    def _link_default(self, src, inset):
        """Right-hand cell when it is free, else a new column inserted there."""
        r0, c0 = self.spec.find(src)
        if c0 + 1 < self.spec.ncols and self.spec.cells[r0][c0 + 1].empty:
            self._link_to(src, inset, f'{r0},{c0 + 1}', ask=False)
        else:
            self._link_to(src, inset, 'insert-col')

    def _placement_changed(self, *_):
        if self._busy:
            return
        ins = self._current_inset()
        if ins is None:
            return
        ins.placement = self.placement.currentData()
        if ins.placement == 'cell':
            if not self.spec.zoom_cells(ins):
                self._link_default(self.current_cell(), ins)
        else:
            old = self.spec.zoom_cells(ins)
            self.spec.unlink_inset(ins)
            self._drop_empty_lines(old)
        self.rebuild_table()

    def _target_chosen(self, index):
        ins = self._current_inset()
        if ins is None or index < 0:
            return
        if self._link_to(self.current_cell(), ins, self.target.itemData(index)):
            self.rebuild_table()
        else:
            self._inset_selected(self.inset_list.currentRow(), redraw=False)

    def _inset_changed(self, *_):
        if self._busy:
            return
        cell = self.current_cell()
        row = self.inset_list.currentRow()
        if 0 <= row < len(cell.insets):
            cell.insets[row].corner = self.corner.currentData()
            cell.insets[row].size = self.inset_size.value() / 100
            self._cell_changed()

    def _delete_inset(self):
        cell = self.current_cell()
        row = self.inset_list.currentRow()
        if 0 <= row < len(cell.insets):
            ins = cell.insets.pop(row)
            old = self.spec.zoom_cells(ins)
            self.spec.unlink_inset(ins)
            self._drop_empty_lines(old)
            self.rebuild_table()

    def _insets_to(self, kind):
        src = self.current_cell()
        r0, c0 = self.current_rc()
        if kind == 'row':
            targets = self.spec.cells[r0]
        else:
            targets = [row[c0] for row in self.spec.cells]
        H, W = src.shape() if not src.empty else (0, 0)
        n, blocked = 0, 0
        for cell in list(targets):
            if cell is src or cell.empty or cell.is_zoom:
                continue
            h, w = cell.shape()
            if (h, w) != (H, W):
                continue  # different size: the same pixel box would not match
            for old in cell.insets:
                self.spec.unlink_inset(old)
            cell.insets = [i.copy() for i in src.insets]
            for ins in cell.insets:
                # same offset as the source's zoom cell, e.g. the row below
                if ins.placement == 'cell' and not self.spec.link_inset(cell, ins, overwrite=False):
                    ins.placement = 'inside'
                    blocked += 1
            n += 1
        self.rebuild_table()
        msg = f'확대 영역을 칸 {n}개에 적용했습니다 (크기가 같은 이미지만).'
        if blocked:
            msg += f' 넣을 칸이 이미 차 있어서 {blocked}개는 이미지 안에 넣었습니다.'
        self.statusBar().showMessage(msg)

    # ------------------------------------------------------------------
    # layout + preview
    # ------------------------------------------------------------------

    def _pick_inset_color(self):
        c = QColorDialog.getColor(_qcolor(self.spec.inset_color), self, 'Inset 상자 색')
        if c.isValid():
            self.spec.inset_color = (c.redF(), c.greenF(), c.blueF())
            self._layout_changed()

    def _layout_changed(self, *_):
        s = self.spec
        s.background = 'black' if self.bg_black.isChecked() else 'white'
        s.border = self.border.isChecked()
        s.cell_in = self.cell_in.value()
        s.aspect = self.aspect.value() or None
        s.gap_in = self.gap.value()
        s.font_family = self.font.currentText()
        s.font_pt = self.font_pt.value()
        s.bold = self.bold.isChecked()
        s.scale_bar = self.sb.isChecked()
        s.scale_um = self.sb_um.value() or None
        s.scale_position = self.sb_pos.currentText()
        s.scale_label = self.sb_label.isChecked()
        s.caption = self.caption.isChecked()
        s.inset_scale_bar = self.inset_sb.isChecked()
        s.inset_scale_um = self.inset_um.value() or None
        self.inset_color.setStyleSheet(f'background-color: {_qcolor(s.inset_color).name()};')
        self.schedule()

    def schedule(self):
        self._timer.start()

    def update_preview(self):
        try:
            dpi = self.preview_dpi.currentData()
            arr = figure_to_array(self.spec, dpi)
        except Exception as exc:
            traceback.print_exc()
            self.preview_info.setText(f'미리보기 오류: {exc}')
            return
        self.preview.setPixmap(QPixmap.fromImage(_qimage(arr)))
        h, w = arr.shape[:2]
        out = self.dpi.value() / dpi
        self.preview_info.setText(
            f'{w / dpi:.2f} × {h / dpi:.2f} inch, {self.dpi.value()} dpi로 저장 시 '
            f'{round(w * out)} × {round(h * out)} px')

    def refresh_from_main(self):
        """LUTs or crops changed in the main window: redraw thumbnails and preview."""
        for r in range(self.spec.nrows):
            for c in range(self.spec.ncols):
                self._refresh_cell(r, c)
        self._show_cell_canvas()
        self.schedule()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == event.Type.ActivationChange and self.isActiveWindow():
            self.refresh_from_main()

    def export(self):
        path, flt = QFileDialog.getSaveFileName(self, 'Figure 저장', 'figure.png',
                                                ';;'.join(EXPORT_FILTERS))
        if not path:
            return
        if Path(path).suffix.lower() not in ('.png', '.tif', '.tiff', '.pdf', '.svg'):
            path += EXPORT_FILTERS.get(flt, '.png')
        try:
            save_figure(self.spec, path, self.dpi.value())
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, '저장 실패', str(exc))
            return
        self.statusBar().showMessage(f'저장: {path}')


def load_rgb_file(path):
    """(rgb float 0..1, pixel µm or None) from a PNG / JPEG / TIFF file."""
    path = Path(path)
    px = None
    if path.suffix.lower() in ('.tif', '.tiff'):
        import tifffile

        with tifffile.TiffFile(path) as tf:
            page = tf.pages[0]
            arr = page.asarray()
            try:
                xres = page.tags['XResolution'].value
                unit = tf.imagej_metadata.get('unit') if tf.imagej_metadata else None
                if xres and xres[0] and unit in ('um', 'micron', 'µm', '\\u00B5m'):
                    px = xres[1] / xres[0]
            except Exception:
                pass
    else:
        from PIL import Image as PILImage

        arr = np.asarray(PILImage.open(path).convert('RGB'))
    arr = np.asarray(arr)
    if arr.ndim == 3 and arr.shape[0] in (3, 4) and arr.shape[-1] not in (3, 4):
        arr = np.moveaxis(arr, 0, -1)
    if arr.ndim == 2:
        arr = np.repeat(arr[..., None], 3, axis=2)
    arr = arr[..., :3].astype(np.float32)
    top = 255.0 if arr.max() <= 255 else float(arr.max())
    return np.clip(arr / top, 0, 1), px
