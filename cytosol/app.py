"""Cytosol Viewer: batch LUT adjustment, cropping and TIFF export.

Run with ``python -m cytosol.app`` (or the built app).
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QIcon,
    QImage,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .lut import (
    ImageItem,
    apply_lut_to_all,
    export_item,
    item_stem,
    load_preset,
    save_preset,
)
from .marker_panel import MarkerPanel
from .roi_panel import RoiPanel, write_csv

SUPPORTED = ('.tcf', '.czi', '.oir', '.tif', '.tiff')
SLIDER_STEPS = 1000


def to_qimage(rgb: np.ndarray) -> QImage:
    arr = np.ascontiguousarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8))
    h, w = arr.shape[:2]
    return QImage(arr.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


def qcolor(rgb) -> QColor:
    return QColor.fromRgbF(*[float(c) for c in rgb])


def load_items(path: Path, align_tcf: bool = True) -> list[ImageItem]:
    """One entry per file. With align_tcf off, a TCF gives two (HT and FL)."""
    if path.suffix.lower() == '.tcf':
        if align_tcf:
            return [ImageItem.load(path, label=path.stem, aligned=True)]
        from .io import tcf_metadata

        mods = tcf_metadata(path)['modalities']
        items = []
        for mod, tag in (('3D', 'HT'), ('3DFL', 'FL')):
            if mod in mods:
                items.append(ImageItem.load(path, label=f'{path.stem}_{tag}', modality=mod))
        if not items and '2DMIP' in mods:
            items.append(ImageItem.load(path, label=f'{path.stem}_HT', modality='2DMIP'))
        return items
    return [ImageItem.load(path)]


# ---------------------------------------------------------------------------
# preview canvas with crop selection
# ---------------------------------------------------------------------------


CELL_COLORS = [QColor(c) for c in (
    '#ff5050', '#50c8ff', '#ffb428', '#78ff78', '#ff78ff', '#ffff50', '#50ffd2', '#c896ff',
    '#ff9678', '#96b4ff',
)]
LASSO_COLORS = {'add': QColor(80, 255, 120), 'sub': QColor(255, 80, 80), 'new': QColor(80, 220, 255)}


def polygon_path(*polys) -> QPainterPath:
    path = QPainterPath()
    for xy in polys:
        if xy is None or len(xy) < 2:
            continue
        path.moveTo(QPointF(*xy[0]))
        for x, y in xy[1:]:
            path.lineTo(QPointF(x, y))
        path.closeSubpath()
    return path


class Canvas(QGraphicsView):
    """Image view: wheel to zoom, drag to pan, Crop mode to draw a rectangle.

    ROI tools: 'select' (click selects a cell, drag pans), 'add' / 'sub' / 'new'
    (drag draws a freehand area). The right or middle button always pans.
    """

    cropDrawn = Signal(float, float, float, float)
    cellClicked = Signal(float, float)
    lassoDrawn = Signal(str, object)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.pix = QGraphicsPixmapItem()
        self.pix.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.scene().addItem(self.pix)
        self.rect_item = QGraphicsRectItem()
        pen = QPen(QColor(255, 220, 0), 0)
        pen.setCosmetic(True)
        pen.setWidth(2)
        pen.setStyle(Qt.PenStyle.DashLine)
        self.rect_item.setPen(pen)
        self.rect_item.setZValue(10)
        self.rect_item.hide()
        self.scene().addItem(self.rect_item)
        self.setBackgroundBrush(QColor(30, 30, 30))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.crop_mode = False
        self.roi_tool = 'select'
        self._origin = None
        self._region_items = []
        self._cell_items = []
        self._fitted = False
        self._lasso = None
        self._lasso_item = QGraphicsPathItem()
        self._lasso_item.setZValue(20)
        self.scene().addItem(self._lasso_item)
        self._pan_from = None
        self._press_view = None

    def set_image(self, qimg: QImage, refit=False):
        self.pix.setPixmap(QPixmap.fromImage(qimg))
        self.scene().setSceneRect(QRectF(self.pix.pixmap().rect()))
        if refit or not self._fitted:
            self.fit()

    def fit(self):
        if not self.pix.pixmap().isNull():
            self.fitInView(self.pix, Qt.AspectRatioMode.KeepAspectRatio)
            self._fitted = True

    def show_crops(self, crops, selected=None):
        """Draw every crop region with its number; highlight the selected one."""
        for it in self._region_items:
            self.scene().removeItem(it)
        self._region_items = []
        self.rect_item.hide()
        for k, (x0, y0, x1, y1) in enumerate(crops):
            sel = k == selected
            pen = QPen(QColor(255, 220, 0) if sel else QColor(0, 220, 255))
            pen.setCosmetic(True)
            pen.setWidth(3 if sel else 2)
            pen.setStyle(Qt.PenStyle.SolidLine if sel else Qt.PenStyle.DashLine)
            r = QGraphicsRectItem(QRectF(x0, y0, x1 - x0, y1 - y0))
            r.setPen(pen)
            r.setZValue(10)
            t = QGraphicsSimpleTextItem(str(k + 1))
            t.setBrush(pen.color())
            t.setFlag(QGraphicsSimpleTextItem.GraphicsItemFlag.ItemIgnoresTransformations)
            font = t.font()
            font.setPointSize(14)
            font.setBold(True)
            t.setFont(font)
            t.setPos(x0 + 2, y0 + 2)
            t.setZValue(11)
            for it in (r, t):
                self.scene().addItem(it)
                self._region_items.append(it)

    def show_cells(self, shapes, selected=0):
        """shapes: (label, cell_xy, nucleus_xy or None, status, (cx, cy)) per cell."""
        for it in self._cell_items:
            self.scene().removeItem(it)
        self._cell_items = []
        for label, xy, nxy, status, (cx, cy) in shapes:
            sel = label == selected
            col = QColor(255, 255, 0) if sel else CELL_COLORS[label % len(CELL_COLORS)]
            pen = QPen(col)
            pen.setCosmetic(True)
            pen.setWidthF(3 if sel else 1.6)
            if status != 'ok':
                pen.setStyle(Qt.PenStyle.DashLine)
            item = QGraphicsPathItem(polygon_path(xy))
            item.setPen(pen)
            if sel:
                fill = QColor(col)
                fill.setAlpha(45)
                item.setBrush(fill)
            item.setZValue(12)
            items = [item]
            if nxy is not None:
                npen = QPen(QColor(255, 255, 255, 200 if sel else 140))
                npen.setCosmetic(True)
                npen.setWidthF(1.0)
                npen.setStyle(Qt.PenStyle.DotLine)
                n = QGraphicsPathItem(polygon_path(nxy))
                n.setPen(npen)
                n.setZValue(12)
                items.append(n)
            t = QGraphicsSimpleTextItem(str(label))
            t.setBrush(col)
            t.setFlag(QGraphicsSimpleTextItem.GraphicsItemFlag.ItemIgnoresTransformations)
            font = t.font()
            font.setPointSize(12)
            font.setBold(True)
            t.setFont(font)
            t.setPos(cx, cy)
            t.setZValue(13)
            items.append(t)
            for it in items:
                self.scene().addItem(it)
                self._cell_items.append(it)

    def _drawing(self):
        return self.crop_mode or self.roi_tool in LASSO_COLORS

    def _apply_mode(self):
        drawing = self._drawing()
        self.setDragMode(
            QGraphicsView.DragMode.NoDrag if drawing else QGraphicsView.DragMode.ScrollHandDrag
        )
        self.viewport().setCursor(
            Qt.CursorShape.CrossCursor if drawing else Qt.CursorShape.OpenHandCursor
        )

    def set_crop_mode(self, on: bool):
        self.crop_mode = on
        self._apply_mode()

    def set_roi_tool(self, tool: str):
        self.roi_tool = tool
        self._apply_mode()

    def wheelEvent(self, event):
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.scale(factor, factor)

    def mousePressEvent(self, event):
        btn = event.button()
        if btn in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
            self._pan_from = event.position()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        pos = self.mapToScene(event.position().toPoint())
        if self.crop_mode and btn == Qt.MouseButton.LeftButton:
            self._origin = pos
            self.rect_item.setRect(QRectF(self._origin, self._origin))
            self.rect_item.show()
            return
        if self.roi_tool in LASSO_COLORS and btn == Qt.MouseButton.LeftButton:
            self._lasso = [(pos.x(), pos.y())]
            col = LASSO_COLORS[self.roi_tool]
            pen = QPen(col)
            pen.setCosmetic(True)
            pen.setWidthF(2)
            fill = QColor(col)
            fill.setAlpha(60)
            self._lasso_item.setPen(pen)
            self._lasso_item.setBrush(fill)
            self._lasso_item.setPath(QPainterPath())
            self._lasso_item.show()
            return
        if btn == Qt.MouseButton.LeftButton:
            self._press_view = event.position()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pan_from is not None:
            d = event.position() - self._pan_from
            self._pan_from = event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(d.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(d.y()))
            return
        if self.crop_mode and self._origin is not None:
            p = self.mapToScene(event.position().toPoint())
            self.rect_item.setRect(QRectF(self._origin, p).normalized())
            return
        if self._lasso is not None:
            p = self.mapToScene(event.position().toPoint())
            self._lasso.append((p.x(), p.y()))
            self._lasso_item.setPath(polygon_path(np.asarray(self._lasso)))
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._pan_from is not None:
            self._pan_from = None
            self._apply_mode()
            return
        if self.crop_mode and self._origin is not None:
            r = self.rect_item.rect()
            self._origin = None
            self.cropDrawn.emit(r.left(), r.top(), r.right(), r.bottom())
            return
        if self._lasso is not None:
            pts = np.asarray(self._lasso, float)
            self._lasso = None
            self._lasso_item.hide()
            # a click (no real area drawn) selects the cell under the cursor
            span = pts.max(0) - pts.min(0)
            scale = self.transform().m11() or 1.0
            if len(pts) < 3 or max(span) * scale < 4:
                self.cellClicked.emit(*pts[-1])
            else:
                self.lassoDrawn.emit(self.roi_tool, pts)
            return
        if self._press_view is not None:
            moved = (event.position() - self._press_view).manhattanLength()
            self._press_view = None
            if moved < 4:
                p = self.mapToScene(event.position().toPoint())
                self.cellClicked.emit(p.x(), p.y())
        super().mouseReleaseEvent(event)


# ---------------------------------------------------------------------------
# histogram + channel controls
# ---------------------------------------------------------------------------


class Histogram(QWidget):
    """Log histogram of a channel with the current LUT range drawn on top."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(60)
        self.counts = None
        self.lo = self.hi = 0.0
        self.vmin = self.vmax = 0.0
        self.color = (1, 1, 1)

    def set_data(self, plane, lo, hi):
        self.lo, self.hi = lo, hi
        counts, _ = np.histogram(plane, bins=128, range=(lo, hi))
        self.counts = np.log1p(counts.astype(np.float64))
        self.update()

    def set_lut(self, vmin, vmax, color):
        self.vmin, self.vmax, self.color = vmin, vmax, color
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(20, 20, 20))
        if self.counts is None or self.counts.max() <= 0:
            return
        w, h = self.width(), self.height()
        c = self.counts / self.counts.max()
        path = QPainterPath(QPointF(0, h))
        for i, v in enumerate(c):
            path.lineTo(QPointF(i * w / len(c), h - v * (h - 4)))
        path.lineTo(QPointF(w, h))
        col = qcolor(self.color)
        col.setAlpha(150)
        p.fillPath(path, col)
        span = max(self.hi - self.lo, 1e-12)
        x0 = (self.vmin - self.lo) / span * w
        x1 = (self.vmax - self.lo) / span * w
        p.setPen(QPen(QColor(255, 255, 255), 1))
        p.drawLine(QPointF(x0, h), QPointF(x1, 0))
        p.setPen(QPen(QColor(255, 255, 255, 120), 1, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(x0, 0), QPointF(x0, h))
        p.drawLine(QPointF(x1, 0), QPointF(x1, h))


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

        self.visible = QCheckBox('표시')
        self.color_btn = QPushButton()
        self.color_btn.setFixedWidth(40)
        self.auto_btn = QPushButton('Auto')
        self.reset_btn = QPushButton('Min/Max')
        self.reset_btn.setToolTip('현재 이미지 데이터의 최소값~최대값으로 설정')
        self.all_btn = QPushButton('전체 이미지에 적용')
        self.all_btn.setToolTip('이 채널의 LUT를 모든 이미지의 같은 채널에 적용')

        self.hist = Histogram()
        self.range_lo = QLabel()
        self.range_hi = QLabel()
        self.range_note = QLabel()
        for lab in (self.range_lo, self.range_hi, self.range_note):
            lab.setStyleSheet('color: gray; font-size: 11px;')
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
        top.addWidget(self.visible)
        top.addWidget(self.color_btn)
        top.addStretch()
        top.addWidget(self.auto_btn)
        top.addWidget(self.reset_btn)

        form = QFormLayout()
        row = QHBoxLayout()
        row.addWidget(self.min_slider)
        row.addWidget(self.min_spin)
        form.addRow('Min', row)
        row = QHBoxLayout()
        row.addWidget(self.max_slider)
        row.addWidget(self.max_spin)
        form.addRow('Max', row)
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
        self.color_btn.setStyleSheet(f'background-color: {qcolor(lut.color).name()};')
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


# ---------------------------------------------------------------------------
# main window
# ---------------------------------------------------------------------------


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Cytosol Viewer')
        self.resize(1400, 900)
        self.setAcceptDrops(True)
        self.items: list[ImageItem] = []
        self.current: ImageItem | None = None
        self.panels: list[ChannelPanel] = []

        # left: file list
        self.file_list = QListWidget()
        self.file_list.currentRowChanged.connect(self._select)
        add_btn = QPushButton('파일 추가…')
        add_btn.clicked.connect(self.add_files_dialog)
        rm_btn = QPushButton('목록에서 제거')
        rm_btn.clicked.connect(self.remove_current)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel('이미지 (TCF / CZI / OIR / TIF, 끌어다 놓기 가능)'))
        ll.addWidget(self.file_list)
        self.align_tcf = QCheckBox('TCF: HT와 FL을 정렬해 한 이미지로')
        self.align_tcf.setChecked(True)
        self.align_tcf.setToolTip(
            'FL을 HT 픽셀 격자에 맞춰 리샘플링합니다 (XY: 픽셀 크기와 자동 미세 보정, '
            'Z: 3DFL OffsetZ). 끄면 HT와 FL이 따로 열립니다. 새로 추가하는 파일부터 적용됩니다.'
        )
        ll.addWidget(self.align_tcf)
        ll.addWidget(add_btn)
        ll.addWidget(rm_btn)

        # left, below files: crop regions of the current image
        self.crop_list = QListWidget()
        self.crop_list.setMaximumHeight(160)
        self.crop_list.currentRowChanged.connect(lambda _: self.update_preview(refit=True))
        self.crop_btn = QPushButton('Crop 추가 (드래그)')
        self.crop_btn.setCheckable(True)
        del_crop = QPushButton('선택 삭제')
        del_crop.clicked.connect(self.delete_crop)
        clear_crop = QPushButton('전체 삭제')
        clear_crop.clicked.connect(self.clear_crops)
        crop_all = QPushButton('같은 크기 이미지에 복사')
        crop_all.setToolTip('이 이미지의 crop 영역들을 크기가 같은 다른 이미지에 복사')
        crop_all.clicked.connect(self.crop_to_all)
        crop_box = QGroupBox('Crop 영역 (각각 따로 저장)')
        cbl = QVBoxLayout(crop_box)
        cbl.addWidget(self.crop_btn)
        cbl.addWidget(self.crop_list)
        row = QHBoxLayout()
        row.addWidget(del_crop)
        row.addWidget(clear_crop)
        cbl.addLayout(row)
        cbl.addWidget(crop_all)
        ll.addWidget(crop_box)
        fig_btn = QPushButton('Figure 만들기…')
        fig_btn.setToolTip('LUT/crop을 적용한 이미지로 행·열 표 형태의 figure 만들기')
        fig_btn.clicked.connect(self.open_figure)
        ll.addWidget(fig_btn)

        # center: canvas + view controls
        self.canvas = Canvas()
        self.canvas.cropDrawn.connect(self._crop_drawn)
        self.z_combo = QComboBox()
        self.z_combo.currentIndexChanged.connect(self._z_changed)
        self.crop_btn.toggled.connect(self.canvas.set_crop_mode)
        self.show_crop_btn = QCheckBox('선택한 Crop만 보기')
        self.show_crop_btn.toggled.connect(lambda _: self.update_preview(refit=True))
        fit_btn = QPushButton('화면 맞춤')
        fit_btn.clicked.connect(self.canvas.fit)
        self.t_slider = QSlider(Qt.Orientation.Horizontal)
        self.t_slider.setTracking(False)  # load a timepoint on release, not while dragging
        self.t_slider.valueChanged.connect(self._t_changed)
        self.t_slider.sliderMoved.connect(self._t_preview_label)
        self.t_label = QLabel()
        self.t_label.setMinimumWidth(130)
        self.markers = MarkerPanel()
        self.markers.changed.connect(self.update_preview)
        self.info = QLabel()

        bar1 = QHBoxLayout()
        bar1.addWidget(QLabel('Z'))
        bar1.addWidget(self.z_combo)
        bar1.addWidget(self.show_crop_btn)
        bar1.addStretch()
        bar1.addWidget(fit_btn)
        self.t_row = QWidget()
        tl = QHBoxLayout(self.t_row)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.addWidget(QLabel('T'))
        tl.addWidget(self.t_slider, 1)
        tl.addWidget(self.t_label)
        bar2 = QHBoxLayout()
        bar2.addStretch()
        bar2.addWidget(self.info)
        center = QWidget()
        cl = QVBoxLayout(center)
        cl.addLayout(bar1)
        cl.addWidget(self.canvas, 1)
        cl.addWidget(self.t_row)
        cl.addLayout(bar2)

        # right: channel panels + batch + export
        self.channel_box = QVBoxLayout()
        self.channel_box.addStretch()
        chan_widget = QWidget()
        chan_widget.setLayout(self.channel_box)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(chan_widget)

        all_luts = QPushButton('모든 채널 LUT를 전체 이미지에 적용')
        all_luts.clicked.connect(self.apply_all_channels)
        self.copy_color = QCheckBox('색상도 함께 적용')
        self.copy_color.setChecked(True)
        save_p = QPushButton('LUT 프리셋 저장…')
        save_p.clicked.connect(self.save_preset)
        load_p = QPushButton('LUT 프리셋 불러오기…')
        load_p.clicked.connect(self.load_preset)
        batch = QGroupBox('일괄 적용')
        bl = QVBoxLayout(batch)
        bl.addWidget(all_luts)
        bl.addWidget(self.copy_color)
        row = QHBoxLayout()
        row.addWidget(save_p)
        row.addWidget(load_p)
        bl.addLayout(row)

        self.exp_full = QCheckBox('전체 이미지')
        self.exp_full.setChecked(True)
        self.exp_crops = QCheckBox('Crop 영역 각각')
        self.exp_crops.setChecked(True)
        self.exp_composite = QCheckBox('합성 RGB (LUT 적용)')
        self.exp_composite.setChecked(True)
        self.exp_channels = QCheckBox('채널별 RGB')
        self.exp_raw = QCheckBox('원본값 스택 (ImageJ, 모든 Z)')
        self.exp_raw.setChecked(True)
        self.exp_all_t = QCheckBox('타임시리즈는 모든 시점 저장 (끄면 현재 시점만)')
        self.exp_all_t.setChecked(True)
        self.exp_per_image = QCheckBox('이미지별 폴더에 나눠 저장')
        self.exp_per_image.setChecked(True)
        self.exp_per_image.setToolTip('폴더 안에 이미지마다 하위 폴더를 만들어 그 이미지의 파일을 넣습니다.')
        exp_btn = QPushButton('모든 이미지 TIFF로 저장…')
        exp_btn.clicked.connect(self.export_all)
        exp_one = QPushButton('현재 이미지만 저장…')
        exp_one.clicked.connect(self.export_current)
        exp = QGroupBox('TIFF 일괄 저장')
        el = QVBoxLayout(exp)
        row = QHBoxLayout()
        row.addWidget(QLabel('범위:'))
        row.addWidget(self.exp_full)
        row.addWidget(self.exp_crops)
        el.addLayout(row)
        for w in (self.exp_composite, self.exp_channels, self.exp_raw, self.exp_all_t,
                  self.exp_per_image):
            el.addWidget(w)
        row = QHBoxLayout()
        row.addWidget(exp_one)
        row.addWidget(exp_btn)
        el.addLayout(row)
        all_btn = QPushButton('모든 데이터 일괄 저장 (TIFF + ROI, 이미지별 폴더)…')
        all_btn.setToolTip('이미지마다 폴더를 하나씩 만들어 그 이미지의 TIFF, ROI, 측정값 CSV를 모두 넣습니다.')
        all_btn.clicked.connect(self.export_everything)
        el.addWidget(all_btn)

        lut_tab = QWidget()
        rl = QVBoxLayout(lut_tab)
        rl.addWidget(QLabel('채널 LUT'))
        rl.addWidget(scroll, 1)
        rl.addWidget(batch)
        rl.addWidget(exp)
        self.roi_panel = RoiPanel(self)
        self.exp_per_image.toggled.connect(self.roi_panel.per_image.setChecked)
        self.roi_panel.per_image.toggled.connect(self.exp_per_image.setChecked)
        roi_scroll = QScrollArea()
        roi_scroll.setWidgetResizable(True)
        roi_scroll.setWidget(self.roi_panel)
        right = QTabWidget()
        right.addTab(lut_tab, 'LUT · 내보내기')
        right.addTab(roi_scroll, '세포질 ROI')
        marker_scroll = QScrollArea()
        marker_scroll.setWidgetResizable(True)
        marker_scroll.setWidget(self.markers)
        right.addTab(marker_scroll, '마커')
        right.setMinimumWidth(380)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(center)
        split.addWidget(right)
        split.setSizes([260, 800, 420])
        self.setCentralWidget(split)

        open_act = QAction('파일 열기…', self)
        open_act.setShortcut(QKeySequence.StandardKey.Open)
        open_act.triggered.connect(self.add_files_dialog)
        export_act = QAction('TIFF로 일괄 저장…', self)
        export_act.setShortcut(QKeySequence('Ctrl+E'))
        export_act.triggered.connect(self.export_all)
        menu = self.menuBar().addMenu('파일')
        menu.addAction(open_act)
        menu.addAction(export_act)
        everything_act = QAction('모든 데이터 일괄 저장 (이미지별 폴더)…', self)
        everything_act.setShortcut(QKeySequence('Ctrl+Shift+E'))
        everything_act.triggered.connect(self.export_everything)
        menu.addAction(everything_act)
        fig_act = QAction('Figure 만들기…', self)
        fig_act.setShortcut(QKeySequence('Ctrl+Shift+F'))
        fig_act.triggered.connect(self.open_figure)
        self.menuBar().addMenu('Figure').addAction(fig_act)
        self.figure_win = None
        self.statusBar().showMessage('파일을 추가하세요.')

    # ---- files ----------------------------------------------------------

    def add_files_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, '이미지 파일 선택', '',
            'Microscopy (*.tcf *.TCF *.czi *.oir *.tif *.tiff *.TIF *.TIFF);;All files (*)',
        )
        self.add_files([Path(f) for f in files])

    def add_files(self, paths):
        paths = [p for p in paths if p.suffix.lower() in SUPPORTED]
        if not paths:
            return
        prog = QProgressDialog('불러오는 중…', '취소', 0, len(paths), self)
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        errors = []
        for i, p in enumerate(paths):
            if prog.wasCanceled():
                break
            prog.setLabelText(f'불러오는 중: {p.name}')
            prog.setValue(i)
            QApplication.processEvents()
            try:
                for item in load_items(p, self.align_tcf.isChecked()):
                    self.items.append(item)
                    entry = QListWidgetItem(item.label)
                    entry.setToolTip(str(item.path))
                    self.file_list.addItem(entry)
            except Exception as exc:  # keep loading the rest
                errors.append(f'{p.name}: {exc}')
                traceback.print_exc()
        prog.setValue(len(paths))
        if errors:
            QMessageBox.warning(self, '불러오기 실패', '\n'.join(errors))
        if self.current is None and self.items:
            self.file_list.setCurrentRow(0)
        self.statusBar().showMessage(f'이미지 {len(self.items)}개')

    def remove_current(self):
        row = self.file_list.currentRow()
        if row < 0:
            return
        removed = self.items.pop(row)
        self.file_list.takeItem(row)
        if self.figure_win is not None:
            self.figure_win.spec.forget_item(removed)
            self.figure_win.refresh_sources()
        if not self.items:
            self.current = None
            self._build_panels()
            self.roi_panel.bind(None)
            self.roi_panel.draw_overlay(hidden=True)
            self.canvas.pix.setPixmap(QPixmap())

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = []
        for url in event.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.is_dir():
                paths += sorted(q for q in p.rglob('*') if q.suffix.lower() in SUPPORTED)
            else:
                paths.append(p)
        self.add_files(paths)

    # ---- selection ------------------------------------------------------

    def _select(self, row):
        if row < 0 or row >= len(self.items):
            return
        self.current = self.items[row]
        it = self.current
        self.z_combo.blockSignals(True)
        self.z_combo.clear()
        self.z_combo.addItem('MIP', 'mip')
        for z in range(it.nz):
            self.z_combo.addItem(f'z {z}', z)
        idx = self.z_combo.findData(it.z)
        self.z_combo.setCurrentIndex(max(idx, 0))
        self.z_combo.setEnabled(it.nz > 1)
        self.z_combo.blockSignals(False)
        self.t_slider.blockSignals(True)
        self.t_slider.setRange(0, max(it.nt - 1, 0))
        self.t_slider.setValue(it.t)
        self.t_slider.blockSignals(False)
        self.t_row.setVisible(it.nt > 1)
        self._t_preview_label(it.t)
        self._build_panels()
        self.roi_panel.bind(it)
        self._refresh_crop_list(select=0)
        c, z, h, w = it.image.data.shape
        px = it.pixel_um
        self.info.setText(
            f'{w}×{h} px, Z {z}, C {c}' + (f', T {it.nt}' if it.nt > 1 else '')
            + (f', {px:.4f} µm/px' if px else ', 픽셀 크기 없음')
        )
        self.update_preview(refit=True)

    def _build_panels(self):
        for p in self.panels:
            p.setParent(None)
            p.deleteLater()
        self.panels = []
        if self.current is None:
            return
        for i in range(len(self.current.channels)):
            panel = ChannelPanel(i)
            panel.bind(self.current)
            panel.changed.connect(self.update_preview)
            panel.applyAll.connect(self.apply_channel_to_all)
            self.channel_box.insertWidget(self.channel_box.count() - 1, panel)
            self.panels.append(panel)

    def _t_preview_label(self, t):
        it = self.current
        if it is None or it.nt < 2:
            self.t_label.setText('')
            return
        times = it.image.times
        t = max(0, min(int(t), it.nt - 1))
        text = self.markers.time_style().text(times[t], times[-1] - times[0], t)
        self.t_label.setText(f'{t + 1}/{it.nt}  ({text.strip()})')

    def _t_changed(self, t):
        it = self.current
        if it is None or t == it.t:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            it.set_t(t)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, '시점 불러오기 실패', str(exc))
        finally:
            QApplication.restoreOverrideCursor()
        self._t_preview_label(it.t)
        for p in self.panels:
            p.bind(it)
        self.update_preview()

    def _z_changed(self, _):
        if self.current is None:
            return
        self.current.z = self.z_combo.currentData()
        for p in self.panels:
            p.bind(self.current)
        self.update_preview()

    # ---- preview --------------------------------------------------------

    def _selected_crop(self):
        it = self.current
        row = self.crop_list.currentRow()
        if it is None or row < 0 or row >= len(it.crops):
            return None
        return row

    def update_preview(self, refit=False):
        it = self.current
        if it is None:
            return
        sel = self._selected_crop()
        only = self.show_crop_btn.isChecked() and sel is not None
        if self.roi_panel.input_view.isChecked() and not only:
            rgb = self.roi_panel.preview_rgb(it)
        else:
            rgb = it.composite(it.crops[sel] if only else None)
        rgb = it.decorate(rgb, self.markers.scale_style(), self.markers.time_style())
        self._t_preview_label(it.t)
        self.canvas.set_image(to_qimage(rgb), refit=refit and only)
        if refit and not only:
            self.canvas.fit()
        self.canvas.show_crops([] if only else it.crops, sel)
        self.roi_panel.draw_overlay(hidden=only)

    # ---- crop -----------------------------------------------------------

    def _refresh_crop_list(self, select=None):
        it = self.current
        self.crop_list.blockSignals(True)
        self.crop_list.clear()
        if it is not None:
            for k, (x0, y0, x1, y1) in enumerate(it.crops, 1):
                self.crop_list.addItem(f'{k}: x {x0}–{x1}, y {y0}–{y1}  ({x1 - x0}×{y1 - y0})')
            if it.crops:
                row = len(it.crops) - 1 if select is None else select
                self.crop_list.setCurrentRow(max(0, min(row, len(it.crops) - 1)))
        self.crop_list.blockSignals(False)

    def _crop_drawn(self, x0, y0, x1, y1):
        if self.current is None:
            return
        region = self.current.add_crop(x0, y0, x1, y1)
        self.crop_btn.setChecked(False)
        self._refresh_crop_list()
        if region:
            self.statusBar().showMessage(f'Crop {len(self.current.crops)} 추가')
        self.update_preview()

    def delete_crop(self):
        sel = self._selected_crop()
        if sel is None:
            return
        self.current.crops.pop(sel)
        self._refresh_crop_list(select=sel)
        self.update_preview(refit=True)

    def clear_crops(self):
        if self.current is not None:
            self.current.crops.clear()
            self._refresh_crop_list()
            self.update_preview(refit=True)

    def crop_to_all(self):
        it = self.current
        if it is None or not it.crops:
            return
        shape = it.image.data.shape[-2:]
        n = 0
        for other in self.items:
            if other is not it and other.image.data.shape[-2:] == shape:
                other.crops = list(it.crops)
                n += 1
        self.statusBar().showMessage(f'Crop 영역 {len(it.crops)}개를 이미지 {n}개에 복사했습니다.')

    # ---- batch LUT ------------------------------------------------------

    def apply_channel_to_all(self, index):
        n = apply_lut_to_all(self.items, self.current, index, color=self.copy_color.isChecked())
        self.statusBar().showMessage(
            f"'{self.current.channels[index]}' LUT를 이미지 {n}개에 적용했습니다."
        )

    def apply_all_channels(self):
        if self.current is None:
            return
        n = 0
        for i in range(len(self.current.channels)):
            n = max(n, apply_lut_to_all(
                self.items, self.current, i, color=self.copy_color.isChecked()
            ))
        self.statusBar().showMessage(f'모든 채널 LUT를 이미지 {n}개에 적용했습니다.')

    def save_preset(self):
        if self.current is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'LUT 프리셋 저장', 'lut_preset.json',
                                              'JSON (*.json)')
        if path:
            save_preset(self.current, path)

    def load_preset(self):
        path, _ = QFileDialog.getOpenFileName(self, 'LUT 프리셋 불러오기', '', 'JSON (*.json)')
        if path:
            load_preset(self.items, path)
            for p in self.panels:
                p.refresh()
            self.update_preview()

    # ---- figure ---------------------------------------------------------

    def open_figure(self):
        from .figure_window import FigureWindow

        if self.figure_win is None:
            self.figure_win = FigureWindow(self)
        else:
            self.figure_win.refresh_sources()
        self.figure_win.show()
        self.figure_win.raise_()
        self.figure_win.activateWindow()

    # ---- export ---------------------------------------------------------

    def export_current(self):
        if self.current is not None:
            self._export([self.current])

    def export_all(self):
        self._export(self.items)

    def _export_kwargs(self):
        return dict(
            full=self.exp_full.isChecked(),
            crops=self.exp_crops.isChecked(),
            composite=self.exp_composite.isChecked(),
            per_channel=self.exp_channels.isChecked(),
            raw_stack=self.exp_raw.isChecked(),
            scale=self.markers.scale_style(),
            time=self.markers.time_style(),
            all_times=self.exp_all_t.isChecked(),
        )

    def _export(self, items):
        if not items:
            return
        out = QFileDialog.getExistingDirectory(self, '저장할 폴더 선택')
        if not out:
            return
        kwargs = self._export_kwargs()
        per_image = self.exp_per_image.isChecked()
        prog = QProgressDialog('저장 중…', '취소', 0, len(items), self)
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        files, errors = [], []
        for i, it in enumerate(items):
            if prog.wasCanceled():
                break
            prog.setLabelText(f'저장 중: {it.label}')
            prog.setValue(i)
            QApplication.processEvents()
            try:
                folder = Path(out) / item_stem(it) if per_image else Path(out)
                files += export_item(it, folder, **kwargs)
            except Exception as exc:
                errors.append(f'{it.label}: {exc}')
                traceback.print_exc()
        prog.setValue(len(items))
        msg = f'TIFF {len(files)}개를 저장했습니다.\n{out}'
        if errors:
            msg += '\n\n실패:\n' + '\n'.join(errors)
        QMessageBox.information(self, '저장 완료', msg)

    def export_everything(self):
        """Save every image's TIFFs, ROIs and measurements into its own folder."""
        items = self.items
        if not items:
            return
        out = QFileDialog.getExistingDirectory(self, '저장할 폴더 선택')
        if not out:
            return
        kwargs = self._export_kwargs()
        prog = QProgressDialog('저장 중…', '취소', 0, len(items), self)
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        n_done, n_files, rows, errors = 0, 0, [], []
        for i, it in enumerate(items):
            if prog.wasCanceled():
                break
            prog.setLabelText(f'저장 중: {it.label}')
            prog.setValue(i)
            QApplication.processEvents()
            folder = Path(out) / item_stem(it)
            try:
                n_files += len(export_item(it, folder, **kwargs))
                if it.cells is not None and len(it.cells):
                    item_rows = self.roi_panel.save_item(it, folder)
                    write_csv(folder / f'{item_stem(it)}_cell_rois.csv', item_rows)
                    rows += item_rows
                n_done += 1
            except Exception as exc:
                errors.append(f'{it.label}: {exc}')
                traceback.print_exc()
        prog.setValue(len(items))
        write_csv(Path(out) / 'cell_rois.csv', rows)
        msg = f'이미지 {n_done}개를 이미지별 폴더에 저장했습니다 (TIFF {n_files}개'
        msg += f', ROI 측정 {len(rows)}행).' if rows else ').'
        msg += f'\n{out}'
        if errors:
            msg += '\n\n실패:\n' + '\n'.join(errors)
        QMessageBox.information(self, '저장 완료', msg)


def main(argv=None):
    argv = sys.argv if argv is None else argv
    app = QApplication(argv)
    app.setApplicationName('Cytosol Viewer')
    icon = Path(__file__).parent / 'assets' / 'icon.png'
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    win = MainWindow()
    win.show()
    files = [Path(a) for a in argv[1:] if Path(a).suffix.lower() in SUPPORTED]
    if files:
        win.add_files(files)
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
