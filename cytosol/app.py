"""Cytosol Viewer: batch LUT adjustment, cropping and TIFF export.

Run with ``python -m cytosol.app`` (or the built app).
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
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
    QShortcut,
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
    QGridLayout,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QTabBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .lut import (
    ImageItem,
    apply_lut_to_all,
    export_item,
    item_folder,
    item_stem,
    load_preset,
    save_preset,
    unique_stems,
)
from .coloc_panel import ColocPanel, write_coloc_csv
from .intensity import is_contour_file, is_particle_file, is_region_file, write_rows
from .groups import GROUP_FILE, apply_groups, auto_groups, read_groups, suggest_name, write_groups
from .flow import reflow
from .image_tree import ImageTree
from .intensity_panel import IntensityPanel
from .imageid import ROI_EXT, match_roi, plan_pairing
from .crops import is_crop_file, load_crop_rois, save_crop_rois
from .imageinfo import is_bleach_file, load_bleach_rois, summarize
from .info_panel import InfoPanel
from .marker_panel import MarkerPanel
from .lineprofile import read_line_roi
from .prefetch import TimeCache
from .profile_panel import ProfilePanel
from .movie import RGB_FORMATS, wants_mp4
from .particle_panel import ParticlePanel
from .roi_panel import RoiPanel, write_csv
from .stack import StackView, export_projection, export_rotation
from .stack_panel import StackPanel
from .settings import SettingsDialog, view_settings
from .worklog import LoggingStatusBar, LogWindow, WorkLog
from .version import __version__

SUPPORTED = ('.tcf', '.czi', '.oir', '.tif', '.tiff')
SLIDER_STEPS = 1000
# Cmd/Ctrl + drag zoom: e^(rate × pixels) at sensitivity 1 (×2 per ~170 px)
ZOOM_DRAG_RATE = 0.004
ZOOM_KEY_STEP = 1.25  # '[' / ']'
# default widths of the side panes (the preview takes the rest) and the
# narrowest tools pane; the image list stops at its buttons' width
LEFT_W = 250
RIGHT_W, RIGHT_MIN_W = 430, 320
MARKER_FORMAT = 'cytosol-viewer-markers'
# what each feature menu's 불러오기 offers: (name, file dialog filter)
IMPORT_KINDS = {
    'lut': ('LUT 프리셋', 'LUT 프리셋 (*.json)'),
    'marker': ('마커 설정', '마커 설정 (*.json)'),
    'crop': ('Crop 영역 ROI', 'Crop 영역 ROI (*_crops.zip *.zip *.roi)'),
    'cell': ('세포질 ROI', 'ImageJ ROI (*.zip *.roi)'),
    'particle': ('입자 ROI', '입자 ROI (*_particles.zip *.zip)'),
    'line': ('라인 프로파일 선 ROI', '선 ROI (*_line.roi *.roi)'),
}


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
        if len(items) > 1:
            for it in items:
                it.id_suffix = it.label.rsplit('_', 1)[-1]
        return items
    return [ImageItem.load(path)]


# ---------------------------------------------------------------------------
# preview canvas with crop selection
# ---------------------------------------------------------------------------


CELL_COLORS = [QColor(c) for c in (
    '#ff5050', '#50c8ff', '#ffb428', '#78ff78', '#ff78ff', '#ffff50', '#50ffd2', '#c896ff',
    '#ff9678', '#96b4ff',
)]
LASSO_COLORS = {'add': QColor(80, 255, 120), 'sub': QColor(255, 80, 80), 'new': QColor(80, 220, 255),
                'cut': QColor(255, 220, 60)}
OPEN_LASSO = {'cut'}  # tools drawn as an open line, not an area


def wrapped_check(box: QCheckBox, text: str, tip: str = '') -> QHBoxLayout:
    """`box` with its text in a word-wrapping label beside it (a QCheckBox
    never wraps, so a long one would hold the panel wide)."""
    label = QLabel(text)
    label.setWordWrap(True)
    label.setToolTip(tip)
    label.mousePressEvent = lambda _e: box.toggle()
    row = QHBoxLayout()
    row.addWidget(box, 0, Qt.AlignmentFlag.AlignTop)
    row.addWidget(label, 1)
    return row


def write_csv_rows(path: Path, rows):
    import csv

    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        csv.writer(f).writerows(rows)


def folder_files(folder: Path) -> list[Path]:
    """Images and ROI files anywhere under folder (hidden files skipped)."""
    return sorted(q for q in folder.rglob('*')
                  if q.is_file() and not q.name.startswith('.')
                  and (q.suffix.lower() in SUPPORTED + ROI_EXT or q.name == GROUP_FILE))


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
    """Image view: Cmd/Ctrl + drag up/down (or ``zoom_by``) zooms, drag pans,
    Crop mode draws a rectangle. The wheel goes to ``wheel_handler`` (the main
    window moves through time with it) and otherwise scrolls the view.

    ROI tools: 'select' (click selects a cell, drag pans), 'add' / 'sub' / 'new'
    (drag draws a freehand area). The middle button always pans; the right
    button pans too, except on an image with T or Z, where right-drag moves
    through them (left/right = T, up/down = Z, ``scrubDragged``).
    Dragging inside a crop region moves it. Zoom mode (or Shift + drag) zooms
    into the dragged rectangle. In the 3D view the image can be dragged
    anywhere and the right button turns it (``rotateDragged``).
    """

    cropDrawn = Signal(float, float, float, float)
    cropMoved = Signal(int, int, int)  # index, dx, dy (image pixels)
    cropPicked = Signal(int)
    zoomDone = Signal()
    rotateStarted = Signal()
    rotateDragged = Signal(str, float)  # axis 'Y' / 'X', screen pixels from the press
    lineDrawn = Signal(float, float, float, float)
    cellClicked = Signal(float, float)
    cellShiftClicked = Signal(float, float)  # Shift+click: add to / remove from the selection
    lassoDrawn = Signal(str, object)
    scrubStarted = Signal()
    scrubDragged = Signal(float, float)  # screen pixels from the press (x right, y down)
    scrubEnded = Signal()

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
        # (w, h) image pixels: Crop mode places a box of this size under the cursor
        self.crop_size = None
        self.roi_tool = 'select'
        self._lasso_tool = None  # tool of the line / area being drawn
        self.roi_edit_active = None  # callable: whether ROI editing (세포질 ROI tab) is shown
        self._zoom_shift = False  # rectangle zoom started by Shift (a click selects)
        self._origin = None
        self._region_items = []
        self._cell_items = []
        self._particle_item = None
        self._contour_item = None
        self._logic_item = None
        self._fitted = False
        self._lasso = None
        self._lasso_item = QGraphicsPathItem()
        self._lasso_item.setZValue(20)
        self.scene().addItem(self._lasso_item)
        self._pan_from = None
        self._press_view = None
        # line profile: the line being drawn and the one shown
        self.line_mode = False
        self._line_origin = None
        self._line_items = []
        self._line = None  # (x0, y0, x1, y1, width) in scene coordinates
        # crop regions shown (dragging one moves it)
        self._crops = []
        self._crop_sel = None
        self._crop_shapes = {}  # index -> (rect item, text item, text origin)
        self._crop_drag = None  # [index, press scene pos, moved]
        # rectangle zoom
        self.zoom_mode = False
        self._zoom_origin = None
        self.zoom_item = QGraphicsRectItem()
        zpen = QPen(QColor(255, 255, 255), 0)
        zpen.setCosmetic(True)
        zpen.setWidth(1)
        zpen.setStyle(Qt.PenStyle.DashLine)
        self.zoom_item.setPen(zpen)
        self.zoom_item.setBrush(QColor(255, 255, 255, 30))
        self.zoom_item.setZValue(30)
        self.zoom_item.hide()
        self.scene().addItem(self.zoom_item)
        # 3D view: free panning, right-drag turns
        self.view3d = False
        self._rot = None  # (press position, locked axis or None)
        # right-drag through T / Z: can_scrub() says whether the image has them
        self.can_scrub = lambda: False
        self._scrub = None  # press position
        # Cmd/Ctrl + drag zoom: (press position, scale at press, scene point under it)
        self._zoom_drag = None
        # wheel_handler(steps) -> True when it used the wheel (steps may be 0)
        self.wheel_handler = None
        self._wheel_acc = 0.0
        # hover_info(x, y) -> (text, (x, y) scene point to show it above) or None:
        # a label over the ROI under the mouse (name and area)
        self.hover_info = None
        self._hover_key = None
        self._hover_box = QGraphicsRectItem()
        self._hover_box.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self._hover_box.setBrush(QColor(0, 0, 0, 190))
        self._hover_box.setPen(QPen(Qt.PenStyle.NoPen))
        self._hover_box.setZValue(40)
        self._hover_text = QGraphicsSimpleTextItem(self._hover_box)
        self._hover_text.setBrush(QColor(255, 255, 255))
        self._hover_box.hide()
        self.scene().addItem(self._hover_box)
        self.viewport().setMouseTracking(True)

    def set_image(self, qimg: QImage, refit=False):
        self.pix.setPixmap(QPixmap.fromImage(qimg))
        self._scene_rect()
        if refit or not self._fitted:
            self.fit()

    def _scene_rect(self):
        r = QRectF(self.pix.pixmap().rect())
        if self.view3d:  # room around the image so it can be dragged anywhere
            m = max(r.width(), r.height()) * 2
            r = r.adjusted(-m, -m, m, m)
        self.scene().setSceneRect(r)

    def set_view3d(self, on: bool):
        """3D projection view: left-drag moves the image freely, right-drag turns it."""
        if on == self.view3d:
            return
        self.view3d = on
        policy = (Qt.ScrollBarPolicy.ScrollBarAlwaysOff if on
                  else Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(policy)
        self.setVerticalScrollBarPolicy(policy)
        self._scene_rect()
        self.fit()

    def set_zoom_mode(self, on: bool):
        self.zoom_mode = on
        self._apply_mode()

    def fit(self):
        if not self.pix.pixmap().isNull():
            self.fitInView(self.pix, Qt.AspectRatioMode.KeepAspectRatio)
            self._fitted = True

    def show_crops(self, crops, selected=None):
        """Draw every crop region with its number; highlight the selected one."""
        for it in self._region_items:
            self.scene().removeItem(it)
        self._region_items = []
        self._crops = list(crops)
        self._crop_sel = selected
        self._crop_shapes = {}
        self._crop_drag = None
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
            self._crop_shapes[k] = (r, t, QPointF(x0 + 2, y0 + 2))
            for it in (r, t):
                self.scene().addItem(it)
                self._region_items.append(it)

    def show_cells(self, shapes, selected=0):
        """shapes: (label, cell_xy, nucleus_xy or None, status, (cx, cy)) per cell;
        selected: a label or a set of labels."""
        selected = set(selected) if isinstance(selected, (set, list, tuple)) else {selected}
        for it in self._cell_items:
            self.scene().removeItem(it)
        self._cell_items = []
        for label, xy, nxy, status, (cx, cy) in shapes:
            sel = label in selected
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

    def show_particles(self, loops):
        """Outline the particle ROIs (pixel-edge polygons) in magenta."""
        if self._particle_item is not None:
            self.scene().removeItem(self._particle_item)
            self._particle_item = None
        if not len(loops):
            return
        pen = QPen(QColor(255, 0, 255))
        pen.setCosmetic(True)
        pen.setWidthF(1.2)
        self._particle_item = QGraphicsPathItem(polygon_path(*loops))
        self._particle_item.setPen(pen)
        self._particle_item.setZValue(12.5)
        self.scene().addItem(self._particle_item)

    def show_particle_contours(self, loops):
        """Outline the particles' sub-pixel iso-intensity contours (shape) in orange."""
        if self._contour_item is not None:
            self.scene().removeItem(self._contour_item)
            self._contour_item = None
        if not len(loops):
            return
        pen = QPen(QColor(255, 150, 0))
        pen.setCosmetic(True)
        pen.setWidthF(1.2)
        self._contour_item = QGraphicsPathItem(polygon_path(*loops))
        self._contour_item.setPen(pen)
        self._contour_item.setZValue(12.6)
        self.scene().addItem(self._contour_item)

    def show_regions(self, loops):
        """Fill the logic regions of the 강도 측정 tab in translucent cyan."""
        if self._logic_item is not None:
            self.scene().removeItem(self._logic_item)
            self._logic_item = None
        if not len(loops):
            return
        pen = QPen(QColor(0, 255, 255))
        pen.setCosmetic(True)
        pen.setWidthF(1.0)
        path = polygon_path(*loops)
        path.setFillRule(Qt.FillRule.OddEvenFill)
        self._logic_item = QGraphicsPathItem(path)
        self._logic_item.setPen(pen)
        self._logic_item.setBrush(QColor(0, 255, 255, 60))
        self._logic_item.setZValue(12.4)
        self.scene().addItem(self._logic_item)

    def show_line(self, line=None, width=1):
        """Draw the profile line (scene coordinates); width > 1 also shows its band."""
        for it in self._line_items:
            self.scene().removeItem(it)
        self._line_items = []
        self._line = None if line is None else (*line, width)
        if line is None:
            return
        x0, y0, x1, y1 = line
        items = []
        length = float(np.hypot(x1 - x0, y1 - y0))
        if width > 1 and length > 0:
            nx, ny = -(y1 - y0) / length * width / 2, (x1 - x0) / length * width / 2
            band = QPainterPath(QPointF(x0 + nx, y0 + ny))
            for px, py in ((x1 + nx, y1 + ny), (x1 - nx, y1 - ny), (x0 - nx, y0 - ny)):
                band.lineTo(px, py)
            band.closeSubpath()
            b = QGraphicsPathItem(band)
            pen = QPen(QColor(255, 220, 0, 160))
            pen.setCosmetic(True)
            pen.setWidthF(1)
            b.setPen(pen)
            b.setBrush(QColor(255, 220, 0, 40))
            items.append(b)
        path = QPainterPath(QPointF(x0, y0))
        path.lineTo(x1, y1)
        ln = QGraphicsPathItem(path)
        pen = QPen(QColor(255, 220, 0))
        pen.setCosmetic(True)
        pen.setWidthF(2)
        ln.setPen(pen)
        items.append(ln)
        for it in items:
            it.setZValue(25)
            self.scene().addItem(it)
            self._line_items.append(it)

    def set_line_mode(self, on: bool):
        self.line_mode = on
        self._apply_mode()

    def _fixed_rect(self, pos):
        """crop_size box centred on pos, in whole pixels, kept inside the image."""
        size = self.pix.pixmap().size()
        W, H = size.width(), size.height()
        w, h = min(self.crop_size[0], W), min(self.crop_size[1], H)
        x = int(np.clip(round(pos.x() - w / 2), 0, max(0, W - w)))
        y = int(np.clip(round(pos.y() - h / 2), 0, max(0, H - h)))
        return QRectF(x, y, w, h)

    def _drawing(self):
        return (self.zoom_mode or self.crop_mode or self.line_mode
                or self.roi_tool in LASSO_COLORS)

    def _crop_at(self, pos):
        """Index of the crop region under a scene point (the selected one first)."""
        order = list(range(len(self._crops) - 1, -1, -1))
        if self._crop_sel is not None and self._crop_sel in order:
            order.remove(self._crop_sel)
            order.insert(0, self._crop_sel)
        for k in order:
            x0, y0, x1, y1 = self._crops[k]
            if x0 <= pos.x() <= x1 and y0 <= pos.y() <= y1:
                return k
        return None

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
        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            event.accept()  # zooming is Cmd/Ctrl + drag, not the wheel
            return
        if self.wheel_handler is not None:
            d = event.angleDelta()
            delta = d.y() if abs(d.y()) >= abs(d.x()) else d.x()
            # one step per wheel notch (120); trackpads send many small deltas
            self._wheel_acc -= delta * view_settings.value('wheel_t') / 120.0
            steps = int(self._wheel_acc)
            self._wheel_acc -= steps
            if self.wheel_handler(steps):
                event.accept()
                return
            self._wheel_acc = 0.0
        super().wheelEvent(event)

    def zoom_by(self, factor: float, anchor=None):
        """Zoom by factor around a viewport point (default: the view centre)."""
        anchor = self.viewport().rect().center() if anchor is None else anchor
        self._set_scale(self.transform().m11() * factor, anchor,
                        self.mapToScene(anchor))

    def _set_scale(self, scale, view_pos, scene_pos):
        """Scale the view, keeping scene_pos under view_pos."""
        from PySide6.QtGui import QTransform

        scale = float(np.clip(scale, 0.01, 400.0))
        old = self.transformationAnchor()
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setTransform(QTransform.fromScale(scale, scale))
        self.setTransformationAnchor(old)
        off = self.mapToScene(view_pos) - scene_pos
        self.centerOn(self.mapToScene(self.viewport().rect().center()) - off)
        self._fitted = True

    def mousePressEvent(self, event):
        btn = event.button()
        if btn == Qt.MouseButton.LeftButton and \
                event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            p = event.position().toPoint()
            self._zoom_drag = (p, self.transform().m11() or 1.0, self.mapToScene(p))
            self.viewport().setCursor(Qt.CursorShape.SizeVerCursor)
            return
        if btn == Qt.MouseButton.RightButton and self.view3d:
            self._rot = (event.position(), None)
            self.viewport().setCursor(Qt.CursorShape.SizeAllCursor)
            self.rotateStarted.emit()
            return
        if btn == Qt.MouseButton.RightButton and self.can_scrub():
            self._scrub = event.position()
            self.viewport().setCursor(Qt.CursorShape.SizeAllCursor)
            self.scrubStarted.emit()
            return
        if btn in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
            self._pan_from = event.position()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        pos = self.mapToScene(event.position().toPoint())
        shift = event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        if btn == Qt.MouseButton.LeftButton and (
                self.zoom_mode or (shift and not self._drawing())):
            self._zoom_origin = pos
            self._zoom_shift = not self.zoom_mode
            self.zoom_item.setRect(QRectF(pos, pos))
            self.zoom_item.show()
            return
        if self.crop_mode and btn == Qt.MouseButton.LeftButton:
            self._origin = pos
            self.rect_item.setRect(self._fixed_rect(pos) if self.crop_size
                                   else QRectF(self._origin, self._origin))
            self.rect_item.show()
            return
        if self.line_mode and btn == Qt.MouseButton.LeftButton:
            self._line_origin = (pos.x(), pos.y())
            width = self._line[4] if self._line else 1
            self.show_line((*self._line_origin, pos.x(), pos.y()), width)
            return
        alt_cut = (self.roi_tool == 'select' and self.roi_edit_active is not None
                   and self.roi_edit_active()
                   and event.modifiers() & Qt.KeyboardModifier.AltModifier)
        if (self.roi_tool in LASSO_COLORS or alt_cut) and btn == Qt.MouseButton.LeftButton:
            # Alt (Option)+drag with 선택: a cut line without switching tools
            self._lasso_tool = 'cut' if alt_cut else self.roi_tool
            self._lasso = [(pos.x(), pos.y())]
            col = LASSO_COLORS[self._lasso_tool]
            pen = QPen(col)
            pen.setCosmetic(True)
            pen.setWidthF(2)
            fill = QColor(col)
            fill.setAlpha(0 if self._lasso_tool in OPEN_LASSO else 60)
            self._lasso_item.setPen(pen)
            self._lasso_item.setBrush(fill)
            self._lasso_item.setPath(QPainterPath())
            self._lasso_item.show()
            return
        if btn == Qt.MouseButton.LeftButton and not self._drawing():
            k = self._crop_at(pos)
            if k is not None:
                self._crop_drag = [k, pos, False]
                self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
                return
        if btn == Qt.MouseButton.LeftButton:
            self._press_view = event.position()
        super().mousePressEvent(event)

    def _update_hover(self, event):
        info = None
        if self.hover_info is not None and not event.buttons() and self._lasso is None:
            p = self.mapToScene(event.position().toPoint())
            info = self.hover_info(p.x(), p.y())
        key = info and (info[0], tuple(info[1]))
        if key == self._hover_key:
            return
        self._hover_key = key
        if info is None:
            self._hover_box.hide()
            return
        text, (x, y) = info
        self._hover_text.setText(text)
        r = self._hover_text.boundingRect()
        pad = 4
        # centred above the anchor (screen pixels, the label does not scale)
        self._hover_box.setRect(QRectF(-r.width() / 2 - pad, -r.height() - 2 * pad - 6,
                                       r.width() + 2 * pad, r.height() + 2 * pad))
        self._hover_text.setPos(-r.width() / 2, -r.height() - pad - 6)
        self._hover_box.setPos(x, y)
        self._hover_box.show()

    def hide_hover(self):
        self._hover_key = None
        self._hover_box.hide()

    def leaveEvent(self, event):
        self.hide_hover()
        super().leaveEvent(event)

    def mouseMoveEvent(self, event):
        self._update_hover(event)
        if self._zoom_drag is not None:
            p, s0, anchor = self._zoom_drag
            dy = p.y() - event.position().y()  # up = zoom in
            rate = ZOOM_DRAG_RATE * view_settings.value('zoom_drag')
            self._set_scale(s0 * float(np.exp(dy * rate)), p, anchor)
            return
        if self._scrub is not None:
            d = event.position() - self._scrub
            self.scrubDragged.emit(d.x(), d.y())
            return
        if self._rot is not None:
            start, axis = self._rot
            d = event.position() - start
            if axis is None and d.manhattanLength() >= 4:
                # the first clear direction picks the axis for this drag
                axis = 'Y' if abs(d.x()) >= abs(d.y()) else 'X'
                self._rot = (start, axis)
            if axis is not None:
                self.rotateDragged.emit(axis, d.x() if axis == 'Y' else d.y())
            return
        if self._zoom_origin is not None:
            p = self.mapToScene(event.position().toPoint())
            self.zoom_item.setRect(QRectF(self._zoom_origin, p).normalized())
            return
        if self._crop_drag is not None:
            k, start, _ = self._crop_drag
            p = self.mapToScene(event.position().toPoint())
            dx, dy = round(p.x() - start.x()), round(p.y() - start.y())
            self._crop_drag[2] = self._crop_drag[2] or dx != 0 or dy != 0
            r, t, origin = self._crop_shapes[k]
            r.setPos(dx, dy)
            t.setPos(origin + QPointF(dx, dy))
            return
        if (not event.buttons() and not self._drawing() and self._crops
                and self._pan_from is None):
            p = self.mapToScene(event.position().toPoint())
            over = self._crop_at(p) is not None
            self.viewport().setCursor(Qt.CursorShape.SizeAllCursor if over
                                      else Qt.CursorShape.OpenHandCursor)
        if self._pan_from is not None:
            d = event.position() - self._pan_from
            self._pan_from = event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(d.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(d.y()))
            return
        if self.crop_mode and self._origin is not None:
            p = self.mapToScene(event.position().toPoint())
            if self.crop_size:
                self.rect_item.setRect(self._fixed_rect(p))
            elif event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                # Shift: a square, as in ImageJ (whole pixels so it stays square)
                o = QPointF(round(self._origin.x()), round(self._origin.y()))
                dx, dy = p.x() - o.x(), p.y() - o.y()
                side = round(max(abs(dx), abs(dy)))
                p = o + QPointF(side if dx >= 0 else -side, side if dy >= 0 else -side)
                self.rect_item.setRect(QRectF(o, p).normalized())
            else:
                self.rect_item.setRect(QRectF(self._origin, p).normalized())
            return
        if self.line_mode and self._line_origin is not None:
            p = self.mapToScene(event.position().toPoint())
            x0, y0 = self._line_origin
            x1, y1 = p.x(), p.y()
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                # Shift: horizontal, vertical or 45°, as in ImageJ
                dx, dy = x1 - x0, y1 - y0
                ang = round(np.degrees(np.arctan2(dy, dx)) / 45) * 45
                r = float(np.hypot(dx, dy))
                x1, y1 = x0 + r * np.cos(np.radians(ang)), y0 + r * np.sin(np.radians(ang))
            self.show_line((x0, y0, x1, y1), self._line[4] if self._line else 1)
            return
        if self._lasso is not None:
            p = self.mapToScene(event.position().toPoint())
            self._lasso.append((p.x(), p.y()))
            if self._lasso_tool in OPEN_LASSO:
                path = QPainterPath(QPointF(*self._lasso[0]))
                for x, y in self._lasso[1:]:
                    path.lineTo(QPointF(x, y))
            else:
                path = polygon_path(np.asarray(self._lasso))
            self._lasso_item.setPath(path)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._zoom_drag is not None:
            self._zoom_drag = None
            self._apply_mode()
            return
        if self._scrub is not None:
            self._scrub = None
            self._apply_mode()
            self.scrubEnded.emit()
            return
        if self._rot is not None:
            self._rot = None
            self._apply_mode()
            return
        if self._zoom_origin is not None:
            r = self.zoom_item.rect()
            self._zoom_origin = None
            self.zoom_item.hide()
            scale = self.transform().m11() or 1.0
            if min(r.width(), r.height()) * scale >= 4:
                self.fitInView(r, Qt.AspectRatioMode.KeepAspectRatio)
                self._fitted = True
            elif self._zoom_shift and max(r.width(), r.height()) * scale < 4:
                self.cellShiftClicked.emit(r.center().x(), r.center().y())  # Shift+click
                return
            self.zoomDone.emit()
            return
        if self._crop_drag is not None:
            k, start, moved = self._crop_drag
            self._crop_drag = None
            self._apply_mode()
            p = self.mapToScene(event.position().toPoint())
            if moved:
                self.cropMoved.emit(k, round(p.x() - start.x()), round(p.y() - start.y()))
            else:  # a click: select this crop (and a cell under it in the ROI tab)
                self.cropPicked.emit(k)
                self.cellClicked.emit(p.x(), p.y())
            return
        if self._pan_from is not None:
            self._pan_from = None
            self._apply_mode()
            return
        if self.crop_mode and self._origin is not None:
            r = self.rect_item.rect()
            self._origin = None
            self.cropDrawn.emit(r.left(), r.top(), r.right(), r.bottom())
            return
        if self.line_mode and self._line_origin is not None:
            self._line_origin = None
            if self._line is not None:
                x0, y0, x1, y1, _ = self._line
                scale = self.transform().m11() or 1.0
                if np.hypot(x1 - x0, y1 - y0) * scale >= 3:
                    self.lineDrawn.emit(x0, y0, x1, y1)
                    return
            self.lineDrawn.emit(-1, -1, -1, -1)  # a click: no line
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
                self.lassoDrawn.emit(self._lasso_tool, pts)
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
        if plane.size > 1_000_000:  # a quarter of the pixels draws the same curve
            plane = plane[::2, ::2]
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

        # placed in the shared row under the LUT section title (see visibility_row)
        self.visible = QCheckBox()
        self.visible.setToolTip('이 채널을 미리보기와 내보내기 합성 이미지에 표시')
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
        self.visible.setText(item.channels[self.index])
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
        color = qcolor(lut.color).name()
        self.color_btn.setStyleSheet(f'background-color: {color};')
        swatch = QPixmap(16, 16)
        swatch.fill(QColor(color))
        qp = QPainter(swatch)
        qp.setPen(QPen(QColor('gray'), 1))
        qp.drawRect(0, 0, 15, 15)  # white channels stay visible on a light background
        qp.end()
        self.visible.setIcon(QIcon(swatch))
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


class VisibilityRow(QWidget):
    """The channel panels' 표시 checkboxes in one row, plus all on / all off."""

    COLUMNS = 2

    def __init__(self):
        super().__init__()
        self.panels: list[ChannelPanel] = []
        box = QGroupBox('채널 표시')
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(box)
        lay = QVBoxLayout(box)
        self.boxes = QGridLayout()
        lay.addLayout(self.boxes)
        buttons = QHBoxLayout()
        buttons.addStretch()
        on = QPushButton('모두 켜기')
        off = QPushButton('모두 끄기')
        on.clicked.connect(lambda: self.set_all(True))
        off.clicked.connect(lambda: self.set_all(False))
        buttons.addWidget(on)
        buttons.addWidget(off)
        lay.addLayout(buttons)

    def set_panels(self, panels):
        for p in self.panels:
            p.visible.setParent(None)
            p.visible.deleteLater()
        self.panels = list(panels)
        for i, p in enumerate(self.panels):
            self.boxes.addWidget(p.visible, i // self.COLUMNS, i % self.COLUMNS)

    def set_all(self, on: bool):
        if not self.panels or self.panels[0].item is None:
            return
        for p in self.panels:
            p.lut.visible = on
            p.refresh()
        self.panels[0].changed.emit()  # one redraw for all channels


# ---------------------------------------------------------------------------
# main window
# ---------------------------------------------------------------------------


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f'Cytosol Viewer {__version__}')
        self.resize(1400, 900)
        self.setAcceptDrops(True)
        self.items: list[ImageItem] = []
        self.current: ImageItem | None = None
        self.panels: list[ChannelPanel] = []
        # project file, unsaved changes and the work log (every status message)
        self.project_path: Path | None = None
        self.dirty = False
        self.worklog = WorkLog()
        self.setStatusBar(LoggingStatusBar(self))
        # export options shared by every folder save (in the 파일 menu)
        self.opt_per_image = QAction('이미지별 폴더에 나눠 저장', self, checkable=True)
        self.opt_per_image.setChecked(True)
        self.opt_per_image.setToolTip('폴더에 저장할 때 이미지마다 하위 폴더(이미지 이름_이미지 ID)를 '
                                      '만들어 그 이미지의 파일을 넣습니다.')
        self.opt_with_roi = QAction('측정·프로파일 저장 시 ROI와 ROI가 그려진 이미지(.png)도 함께',
                                    self, checkable=True)
        self.opt_with_roi.setChecked(True)

        # left: file list
        self.file_list = ImageTree()
        self.file_list.setToolTip('Shift/Ctrl(⌘)+클릭으로 여러 개 선택, Delete 키로 목록에서 제거.\n'
                                  '그룹은 폴더처럼 펼치거나 접을 수 있고, 그룹을 고르면 그 안의 이미지가 모두 선택됩니다.')
        self.file_list.currentRowChanged.connect(self._select)
        for key in (QKeySequence.StandardKey.Delete, QKeySequence(Qt.Key.Key_Backspace)):
            sc = QShortcut(key, self.file_list)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(self.remove_selected)
        add_btn = QPushButton('파일 추가…')
        add_btn.clicked.connect(self.add_files_dialog)
        folder_btn = QPushButton('폴더 불러오기…')
        folder_btn.setToolTip(
            '폴더 안의 원본 이미지, 내보낸 TIFF, ROI(.zip/.roi)를 이미지 ID로 짝지어 불러옵니다.\n'
            '원본이 없으면 내보낸 TIFF(raw 스택 우선)로 열고, ROI는 해당 이미지에 자동으로 붙입니다.')
        folder_btn.clicked.connect(self.add_folder_dialog)
        rm_btn = QPushButton('목록에서 제거')
        rm_btn.setToolTip('선택한 이미지를 모두 목록에서 제거합니다 (파일은 지우지 않습니다).')
        rm_btn.clicked.connect(self.remove_selected)
        group_btn = QPushButton('그룹 지정…')
        group_btn.setToolTip('선택한 이미지들을 한 그룹으로 묶습니다 (새 이름을 쓰거나 있는 그룹을 고르세요).\n'
                             '입자 ROI 측정 결과에 group 열과 그룹별 요약이 붙고, 저장할 때 '
                             f'{GROUP_FILE}에 기록돼 폴더를 다시 불러오면 복원됩니다.')
        group_btn.clicked.connect(self.assign_group)
        auto_btn = QPushButton('자동 그룹')
        auto_btn.setToolTip('이름이 끝의 번호만 다른 이미지끼리 묶습니다 (abc, abc_0001, abc_0002 → abc).\n'
                            '2개 이상 선택하면 선택한 이미지만, 아니면 모든 이미지를 대상으로 합니다.')
        auto_btn.clicked.connect(self.auto_group)
        rename_btn = QPushButton('그룹 이름 변경…')
        rename_btn.clicked.connect(self.rename_group)
        ungroup_btn = QPushButton('그룹 해제')
        ungroup_btn.setToolTip('선택한 이미지를 그룹에서 뺍니다.')
        ungroup_btn.clicked.connect(lambda: self.set_group(self._selected_items(), ''))
        left = QWidget()
        ll = QVBoxLayout(left)
        title = QLabel('이미지 (TCF / CZI / OIR / TIF, 끌어다 놓기 가능)')
        title.setWordWrap(True)
        ll.addWidget(title)
        ll.addWidget(self.file_list)
        grid = QGridLayout()  # two per row so the list can stay narrow
        for i, b in enumerate((group_btn, auto_btn, rename_btn, ungroup_btn)):
            grid.addWidget(b, i // 2, i % 2)
        ll.addLayout(grid)
        self.align_tcf = QCheckBox()
        self.align_tcf.setChecked(True)
        tip = ('FL을 HT 픽셀 격자에 맞춰 리샘플링합니다 (XY: 픽셀 크기와 자동 미세 보정, '
               'Z: 3DFL OffsetZ). 끄면 HT와 FL이 따로 열립니다. 새로 추가하는 파일부터 적용됩니다.')
        self.align_tcf.setToolTip(tip)
        ll.addLayout(wrapped_check(self.align_tcf, 'TCF: HT와 FL을 정렬해 한 이미지로', tip))
        ll.addWidget(add_btn)
        ll.addWidget(folder_btn)
        ll.addWidget(rm_btn)

        # crop regions of the current image (Crop menu > Crop 탭)
        self.crop_list = QListWidget()
        self.crop_list.setMinimumHeight(160)
        self.crop_list.currentRowChanged.connect(
            lambda _: self.update_preview(refit=self.show_crop_btn.isChecked()))
        self.crop_btn = QPushButton('Crop 추가 (드래그)')
        self.crop_btn.setCheckable(True)
        self.crop_btn.setToolTip('누른 뒤 이미지 위에서 드래그해 Crop 영역을 그립니다. '
                                 'Shift + 드래그: 정사각형.')
        del_crop = QPushButton('선택 삭제')
        del_crop.clicked.connect(self.delete_crop)
        clear_crop = QPushButton('전체 삭제')
        clear_crop.clicked.connect(self.clear_crops)
        crop_all = QPushButton('같은 크기 이미지에 복사')
        crop_all.setToolTip('이 이미지의 crop 영역들을 크기가 같은 다른 이미지에 복사.\n'
                            '복사한 뒤 각 이미지에서 영역 안을 드래그하면 위치를 옮길 수 있습니다.')
        crop_all.clicked.connect(self.crop_to_all)
        self.show_crop_btn = QCheckBox('선택한 Crop만 보기')
        self.show_crop_btn.toggled.connect(lambda _: self.update_preview(refit=True))
        crop_page = QWidget()
        cbl = QVBoxLayout(crop_page)
        help_ = QLabel('Crop 영역은 내보낼 때 각각 따로 저장되고, Figure 칸의 영역으로도 고를 수 있습니다. '
                       '영역 안을 드래그하면 옮겨집니다. 저장·불러오기: 메뉴 막대의 Crop.')
        help_.setWordWrap(True)
        help_.setStyleSheet('color: gray; font-size: 11px;')
        cbl.addWidget(help_)
        cbl.addWidget(self.crop_btn)
        cbl.addWidget(self.crop_list, 1)
        row = QHBoxLayout()
        row.addWidget(del_crop)
        row.addWidget(clear_crop)
        cbl.addLayout(row)
        cbl.addWidget(crop_all)
        cbl.addWidget(self.show_crop_btn)
        cbl.addStretch()

        # center: canvas + view controls
        self.canvas = Canvas()
        self.canvas.cropDrawn.connect(self._crop_drawn)
        self.canvas.cropMoved.connect(self._crop_moved)
        self.canvas.cropPicked.connect(self._crop_picked)
        self.canvas.wheel_handler = self._wheel_t
        for key, f in (('[', 1 / ZOOM_KEY_STEP), (']', ZOOM_KEY_STEP)):
            QShortcut(QKeySequence(key), self, activated=lambda f=f: self.canvas.zoom_by(f))
        # Z: vertical slider left of the image (bottom = first slice)
        self.z_slider = QSlider(Qt.Orientation.Vertical)
        self.z_slider.setMinimum(1)
        self.z_slider.setToolTip('Z 슬라이스 (아래 = 첫 슬라이스). 휠이나 ↑↓ / PageUp·PageDown으로도 움직입니다.')
        self.z_slider.valueChanged.connect(self._z_slider_moved)
        self.z_mip = QCheckBox('MIP')
        self.z_mip.setToolTip('모든 Z의 최대값 투영으로 보기 (슬라이더를 움직이면 해당 슬라이스로 전환)')
        self.z_mip.toggled.connect(self._z_mip_toggled)
        self.z_label = QLabel()
        self.z_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.z_label.setMinimumWidth(56)
        self._z_timer = QTimer(self)
        self._z_timer.setSingleShot(True)
        self._z_timer.setInterval(10)  # coalesce fast slider moves into one redraw
        self._z_timer.timeout.connect(self._z_changed)
        self.crop_btn.toggled.connect(self.canvas.set_crop_mode)
        # line drawing is switched from the 라인 프로파일 tab (draw_btn mirrors this)
        self.line_btn = QPushButton('라인 프로파일 (선 그리기)')
        self.line_btn.setCheckable(True)
        fit_btn = QPushButton('화면 맞춤')
        fit_btn.setToolTip('확대/축소: Cmd(Windows는 Ctrl) + 위/아래 드래그, [ 축소, ] 확대.\n'
                           '민감도는 파일 → 설정…에서 바꿉니다.')
        fit_btn.clicked.connect(self.canvas.fit)
        self.zoom_btn = QPushButton('영역 확대')
        self.zoom_btn.setCheckable(True)
        self.zoom_btn.setToolTip('누른 뒤 이미지 위에서 사각형을 드래그하면 그 영역을 확대합니다.\n'
                                 '버튼 없이 Shift + 드래그로도 됩니다. 원래대로: 화면 맞춤.')
        self.zoom_btn.toggled.connect(self.canvas.set_zoom_mode)
        self.canvas.zoomDone.connect(lambda: self.zoom_btn.setChecked(False))
        self.t_slider = QSlider(Qt.Orientation.Horizontal)
        # while dragging, timepoints are read in a thread (TimeCache) and drawn
        # as they arrive (Z-stack series are also read ahead); histograms and
        # the line profile follow when it stops
        self.t_slider.valueChanged.connect(self._t_value)
        self.t_slider.sliderReleased.connect(lambda: self._t_changed(self.t_slider.value()))
        self.tcache = TimeCache(parent=self)
        self.tcache.ready.connect(self._t_ready)
        self._t_want = None  # timepoint the drag waits for
        self._t_full = QTimer(self)
        self._t_full.setSingleShot(True)
        self._t_full.setInterval(150)
        self._t_full.timeout.connect(self._t_refresh)
        self.t_label = QLabel()
        self.t_label.setMinimumWidth(130)
        self.markers = MarkerPanel()
        self.markers.changed.connect(self.update_preview)
        self.info = QLabel()

        bar1 = QHBoxLayout()
        hint = QLabel('Cmd/Ctrl+드래그: 확대·축소 · [ ]: 축소·확대')
        hint.setStyleSheet('color: gray; font-size: 11px;')
        bar1.addWidget(hint)
        bar1.addStretch()
        bar1.addWidget(self.zoom_btn)
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
        self.z_col = QWidget()
        zl = QVBoxLayout(self.z_col)
        zl.setContentsMargins(0, 0, 0, 0)
        ztitle = QLabel('Z')
        ztitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        zl.addWidget(ztitle)
        zl.addWidget(self.z_label)
        zl.addWidget(self.z_slider, 1, Qt.AlignmentFlag.AlignHCenter)
        zl.addWidget(self.z_mip)
        view_row = QHBoxLayout()
        view_row.addWidget(self.z_col)
        view_row.addWidget(self.canvas, 1)
        cl.addLayout(view_row, 1)
        cl.addWidget(self.t_row)
        cl.addLayout(bar2)

        # right: channel panels + batch LUT
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
        batch = QGroupBox('일괄 적용')
        bl = QVBoxLayout(batch)
        bl.addWidget(all_luts)
        bl.addWidget(self.copy_color)
        note = QLabel('LUT 프리셋 저장·불러오기와 이미지 내보내기: 메뉴 막대의 LUT')
        note.setWordWrap(True)
        note.setStyleSheet('color: gray; font-size: 11px;')
        bl.addWidget(note)

        # image export options: shown in the dialog of LUT → 이미지 내보내기
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
        self.exp_format = QComboBox()
        for key, name in RGB_FORMATS.items():
            self.exp_format.addItem(name, key)
        self.exp_format.setToolTip(
            '타임시리즈(모든 시점 저장)의 합성·채널별 RGB를 TIFF 스택, MP4 동영상, 또는 둘 다로 저장합니다.\n'
            '시점이 하나인 이미지는 항상 TIFF로, 원본값 스택은 항상 TIFF로 저장됩니다.')
        self.exp_fps = QSpinBox()
        self.exp_fps.setRange(1, 60)
        self.exp_fps.setValue(10)
        self.exp_fps.setSuffix(' fps')
        self.exp_fps.setToolTip('MP4 동영상의 초당 프레임 수 (프레임 = 시점)')
        self.exp_format.currentIndexChanged.connect(
            lambda _: self.exp_fps.setEnabled(wants_mp4(self.exp_format.currentData())))
        self.exp_fps.setEnabled(False)
        self.exp_all_t.toggled.connect(self.exp_format.setEnabled)
        self.exp_box = QGroupBox('이미지 내보내기 (TIFF / MP4)')
        el = QVBoxLayout(self.exp_box)
        row = QHBoxLayout()
        row.addWidget(QLabel('범위:'))
        row.addWidget(self.exp_full)
        row.addWidget(self.exp_crops)
        el.addLayout(row)
        for w in (self.exp_composite, self.exp_channels, self.exp_raw, self.exp_all_t):
            el.addWidget(w)
        row = QHBoxLayout()
        row.addWidget(QLabel('타임시리즈 RGB 형식:'))
        row.addWidget(self.exp_format, 1)
        row.addWidget(self.exp_fps)
        el.addLayout(row)

        def scrolled(w):
            s = QScrollArea()
            s.setWidgetResizable(True)
            s.setWidget(w)
            return s

        # LUT tab: channel LUTs on top, the markers (always used) fixed below
        lut_top = QWidget()
        rl = QVBoxLayout(lut_top)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(QLabel('채널 LUT'))
        self.visibility = VisibilityRow()
        rl.addWidget(self.visibility)
        rl.addWidget(scroll, 1)
        rl.addWidget(batch)
        marker_box = QGroupBox('마커 (scale bar · 시간 · bleach ROI)')
        ml = QVBoxLayout(marker_box)
        ml.setContentsMargins(4, 4, 4, 4)
        ml.addWidget(scrolled(self.markers))
        lut_tab = QSplitter(Qt.Orientation.Vertical)
        lut_tab.addWidget(lut_top)
        lut_tab.addWidget(marker_box)
        lut_tab.setStretchFactor(0, 3)
        lut_tab.setStretchFactor(1, 2)
        lut_tab.setChildrenCollapsible(False)

        self.roi_panel = RoiPanel(self)
        self.particle_panel = ParticlePanel(self)
        self.stack_panel = StackPanel()
        self.stack_panel.changed.connect(self.update_preview)
        self.stack_panel.refreshRequested.connect(self._refresh_3d)
        self.canvas.rotateStarted.connect(self.stack_panel.begin_drag)
        self.canvas.rotateDragged.connect(self.stack_panel.drag_rotate)
        self.canvas.can_scrub = self._can_scrub
        self.canvas.scrubStarted.connect(self._scrub_start)
        self.canvas.scrubDragged.connect(self._scrub_drag)
        self.canvas.scrubEnded.connect(self._scrub_end)
        self._scrub0 = None  # (t, z) when a right-drag through T / Z started
        self.stack_panels: list[ChannelPanel] = []
        self.stack_views: dict[int, StackView] = {}
        self.profile_panel = ProfilePanel()
        self.profile_panel.with_roi = self.opt_with_roi
        self.profile_panel.changed.connect(self._draw_profile_line)
        self.coloc_panel = ColocPanel(self)
        self.intensity_panel = IntensityPanel(self)
        self.info_panel = InfoPanel()
        right = QTabWidget()
        self.right_tabs = right
        right.setTabsClosable(True)
        right.tabCloseRequested.connect(lambda i: self.hide_tab(self._tab_name(right.widget(i))))
        right.addTab(lut_tab, 'LUT')
        right.addTab(self.info_panel, '이미지 정보')
        for i in range(right.count()):  # the two base tabs stay
            for side in (QTabBar.ButtonPosition.LeftSide, QTabBar.ButtonPosition.RightSide):
                right.tabBar().setTabButton(i, side, None)
        # feature tabs, opened from each feature's menu (in this order)
        self.tab_pages = {
            'crop_tab': (crop_page, 'Crop'),
            'roi_tab': (scrolled(self.roi_panel), '세포질 ROI'),
            'particle_tab': (scrolled(self.particle_panel), '입자 ROI'),
            'intensity_tab': (scrolled(self.intensity_panel), '강도 측정'),
            'coloc_tab': (scrolled(self.coloc_panel), 'Coloc 2'),
            'profile_tab': (self.profile_panel, '라인 프로파일'),
            'stack_tab': (scrolled(self.stack_panel), '스택'),
        }
        self.canvas.lineDrawn.connect(self._line_drawn)
        self.line_btn.toggled.connect(self._line_mode)
        self.profile_panel.draw_btn.toggled.connect(self.line_btn.setChecked)
        self.crop_btn.toggled.connect(lambda on: on and self.line_btn.setChecked(False))
        right.currentChanged.connect(self._tab_changed)
        self._last_shape = None
        for page, _title in self.tab_pages.values():
            reflow(page)
        reflow(lut_tab)
        right.setMinimumWidth(RIGHT_MIN_W)

        # the file list and the tools keep their widths; only the preview
        # grows or shrinks with the window.  Dragged widths are remembered.
        split = QSplitter()
        self.main_split = split
        split.addWidget(left)
        split.addWidget(center)
        split.addWidget(right)
        split.setChildrenCollapsible(False)
        for i, f in enumerate((0, 1, 0)):
            split.setStretchFactor(i, f)
        split.setSizes([LEFT_W, 800, RIGHT_W])
        split.splitterMoved.connect(lambda *_: self._remember_panes())
        self.setCentralWidget(split)
        self._restore_panes()

        self.figure_win = None
        self.log_win = None
        self._build_menus()
        self.statusBar().showMessage('파일을 추가하세요.', 5000)

    # ---- menus ------------------------------------------------------------

    def _act(self, menu, text, fn, shortcut=None, tip=None) -> QAction:
        a = QAction(text, self)
        if shortcut is not None:
            a.setShortcut(QKeySequence(shortcut))
        if tip:
            a.setToolTip(tip)
            a.setStatusTip(tip)
        a.triggered.connect(lambda _=False: fn())
        menu.addAction(a)
        return a

    def _build_menus(self):
        """파일 holds projects, loading by kind, the work log, settings and
        saving everything at once; every feature has its own menu next to it
        with its tab and its own saves and loads."""
        mb = self.menuBar()
        act = self._act
        self.tool_actions = {}  # feature tab name -> its checkable "탭 열기" action

        def tab_action(menu, name):
            title = self.tab_pages[name][1]
            a = QAction(f'{title} 탭 열기', self, checkable=True)
            a.setToolTip(f'‘{title}’ 탭을 오른쪽에 열거나 닫습니다.')
            a.toggled.connect(lambda on, n=name: self.show_tab(n) if on else self.hide_tab(n))
            menu.addAction(a)
            menu.addSeparator()
            self.tool_actions[name] = a

        def load_action(menu, text, kind):
            act(menu, text, lambda: self.import_kind_dialog(kind),
                tip=f'{IMPORT_KINDS[kind][0]} 파일을 골라 불러옵니다. 이미지 ID가 맞는 열린 이미지에, '
                    '없으면 현재 이미지에 붙습니다.')

        m = mb.addMenu('파일')
        act(m, '새 프로젝트', self.new_project, QKeySequence.StandardKey.New)
        act(m, '불러오기 (자동 인식)…', self.import_files_dialog, QKeySequence.StandardKey.Open,
            '프로젝트(.cyproj), 이미지, ROI(세포·입자·Crop·라인, .zip/.roi), LUT 프리셋·마커 설정(.json), '
            '그룹(image_groups.csv)을 골라 불러옵니다. 종류는 자동으로 알아봅니다.')
        act(m, '불러오기 (폴더)…', self.import_folder_dialog, 'Ctrl+Shift+O',
            '폴더 안의 원본 이미지, 내보낸 TIFF, ROI를 이미지 ID로 짝지어 불러옵니다. '
            '이미 열린 이미지에는 ROI·Crop·라인을 붙입니다.')
        self.recent_menu = m.addMenu('최근 프로젝트')
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        m.addSeparator()
        act(m, '프로젝트 저장', self.save_project, QKeySequence.StandardKey.Save)
        act(m, '프로젝트 다른 이름으로 저장…', lambda: self.save_project(ask=True), 'Ctrl+Shift+S')
        m.addSeparator()
        act(m, '모든 분석 결과 통합 저장 (이미지별 폴더)…', self.export_everything, 'Ctrl+Shift+E',
            '이미지마다 폴더를 하나씩 만들어 그 이미지의 TIFF, Crop·세포·입자·논리 영역 ROI, '
            '측정값 CSV, 이미지 정보, Coloc 2 결과를 모두 넣고, 프로젝트 파일도 함께 저장합니다.')
        m.addAction(self.opt_per_image)
        m.addAction(self.opt_with_roi)
        m.addSeparator()
        act(m, '작업 기록 보기…', self.open_log, 'Ctrl+Shift+L')
        act(m, '작업 기록 저장 (CSV)…', self.save_log_csv)
        s = act(m, '설정…', self.open_settings, QKeySequence.StandardKey.Preferences)
        s.setMenuRole(QAction.MenuRole.PreferencesRole)
        m.addSeparator()
        q = act(m, '종료', self.close, QKeySequence.StandardKey.Quit)
        q.setMenuRole(QAction.MenuRole.QuitRole)

        rp, pp, ip, cp = self.roi_panel, self.particle_panel, self.intensity_panel, self.coloc_panel

        sub = mb.addMenu('LUT')
        act(sub, '이미지 내보내기 (TIFF / MP4)…', self.export_images_dialog, 'Ctrl+E')
        sub.addSeparator()
        act(sub, 'LUT 프리셋 저장…', self.save_preset,
            tip='현재 이미지의 채널 LUT를 JSON 파일로 저장합니다.')
        load_action(sub, 'LUT 프리셋 불러오기…', 'lut')

        sub = mb.addMenu('마커')
        act(sub, '마커 설정 저장…', self.save_marker_settings,
            tip='scale bar, 시간 표시, bleach ROI 표시 설정을 JSON 파일로 저장합니다.')
        load_action(sub, '마커 설정 불러오기…', 'marker')

        sub = mb.addMenu('Crop')
        tab_action(sub, 'crop_tab')
        act(sub, 'Crop 영역 ROI 저장 (현재 이미지)…', self.save_crops_current)
        act(sub, 'Crop 영역 ROI 저장 (모든 이미지, 폴더)…', self.save_crops_all)
        load_action(sub, 'Crop 영역 ROI 불러오기…', 'crop')

        sub = mb.addMenu('세포질 ROI')
        tab_action(sub, 'roi_tab')
        for a in (rp.save_cell, rp.save_nuc, rp.save_cyto):
            sub.addAction(a)
        act(sub, 'ROI 저장 (현재 이미지)…', rp.save_current,
            tip='.zip: ImageJ RoiSet 하나로, .roi: ROI마다 .roi 파일 하나씩')
        act(sub, '모든 이미지 ROI 저장 (폴더)…', rp.save_all)
        load_action(sub, 'ROI 불러오기…', 'cell')
        sub.addSeparator()
        self._measure_menu(sub, rp.measure)

        sub = mb.addMenu('입자 ROI')
        tab_action(sub, 'particle_tab')
        act(sub, '입자 ROI 저장 (현재 이미지)…', pp.save_particles_current)
        load_action(sub, '입자 ROI 불러오기…', 'particle')
        sub.addSeparator()
        self._measure_menu(sub, pp.measure)

        sub = mb.addMenu('강도 측정')
        tab_action(sub, 'intensity_tab')
        self._measure_menu(sub, ip.measure)
        sub.addSeparator()
        act(sub, '등거리 띠 CSV 저장 (현재 이미지)…', ip.bands_measure.save_current)
        act(sub, '등거리 띠: 모든 이미지 측정 + 저장 (폴더)…', ip.bands_measure.save_all,
            tip=ip.bands_measure.save_tip)
        act(sub, '등거리 띠 그래프 저장 (PNG / PDF / SVG / TIFF)…', ip.save_plot)

        sub = mb.addMenu('Coloc 2')
        tab_action(sub, 'coloc_tab')
        act(sub, 'CSV 저장 (현재 이미지)…', cp.save_csv,
            tip='현재 이미지의 결과 (ROI마다 한 행, 열 이름은 Coloc 2와 같음)')
        act(sub, '모든 이미지 CSV 저장 (폴더)…', cp.save_all)
        act(sub, '그래프 저장…', cp.save_plot)
        act(sub, 'PDF 리포트 저장…', cp.save_pdf,
            tip='선택한 ROI의 히스토그램과 모든 값 (Coloc 2의 PDF와 같은 내용)')

        sub = mb.addMenu('라인 프로파일')
        tab_action(sub, 'profile_tab')
        act(sub, 'CSV 저장…', self.profile_panel.save_csv)
        act(sub, '그래프 저장 (PNG / PDF / SVG / TIFF)…', self.profile_panel.save_plot)
        load_action(sub, '선 ROI 불러오기…', 'line')

        sub = mb.addMenu('스택')
        tab_action(sub, 'stack_tab')
        act(sub, '현재 투영 저장 (TIFF / MP4)…', lambda: self.stack_export_dialog('current'))
        act(sub, '3D 회전 시리즈 저장 (TIFF 스택 / MP4)…', lambda: self.stack_export_dialog('rotation'))

        sub = mb.addMenu('이미지 정보')
        act(sub, 'CSV 저장…', self.info_panel.save_csv)
        act(sub, '원본 메타데이터 저장…', self.info_panel.save_raw,
            tip='파일에 들어 있는 메타데이터 전체(CZI/OIR XML, TCF 속성)를 그대로 저장합니다.')

        sub = mb.addMenu('Figure')
        act(sub, 'Figure 창 열기…', self.open_figure, 'Ctrl+Shift+F',
            'LUT/crop을 적용한 이미지로 행·열 표 형태의 figure 만들기 (저장은 Figure 창 안에서)')

    def _measure_menu(self, menu, box):
        self._act(menu, '측정 CSV 저장 (현재 이미지)…', box.save_current)
        self._act(menu, '모든 이미지 측정 + 저장 (폴더)…', box.save_all, tip=box.save_tip)

    def _fill_recent(self):
        self.recent_menu.clear()
        files = [p for p in view_settings.recent() if Path(p).exists()]
        for p in files:
            self.recent_menu.addAction(Path(p).name, lambda p=p: self.open_project(Path(p)))
        if not files:
            self.recent_menu.addAction('(없음)').setEnabled(False)
        else:
            self.recent_menu.addSeparator()
            self.recent_menu.addAction('목록 지우기', view_settings.clear_recent)

    def open_settings(self):
        SettingsDialog(self).exec()

    def open_log(self):
        if self.log_win is None:
            self.log_win = LogWindow(self.worklog, self)
        self.log_win.show()
        self.log_win.raise_()
        self.log_win.activateWindow()

    # ---- feature tabs (each feature's menu) ----------------------------------------------------

    def _tab_name(self, widget):
        for name, (w, _) in self.tab_pages.items():
            if w is widget:
                return name
        return None

    def tab_current(self, name) -> bool:
        tabs = getattr(self, 'right_tabs', None)
        page = getattr(self, 'tab_pages', {}).get(name)
        return tabs is not None and page is not None and tabs.currentWidget() is page[0]

    def tab_open(self, name) -> bool:
        return self.right_tabs.indexOf(self.tab_pages[name][0]) >= 0

    def open_tabs(self) -> list[str]:
        return [n for n in self.tab_pages if self.tab_open(n)]

    def show_tab(self, name, focus=True):
        """Add a feature tab next to LUT / 이미지 정보 (menu order) and show it."""
        page, title = self.tab_pages[name]
        tabs = self.right_tabs
        if tabs.indexOf(page) < 0:
            order = list(self.tab_pages)
            pos = 2
            for other in order[:order.index(name)]:
                i = tabs.indexOf(self.tab_pages[other][0])
                if i >= 0:
                    pos = i + 1
            tabs.insertTab(pos, page, title)
        if focus:
            tabs.setCurrentWidget(page)
        act = getattr(self, 'tool_actions', {}).get(name)
        if act is not None and not act.isChecked():
            act.blockSignals(True)
            act.setChecked(True)
            act.blockSignals(False)

    def hide_tab(self, name):
        if name is None:
            return
        page, _ = self.tab_pages[name]
        i = self.right_tabs.indexOf(page)
        if i >= 0:
            self.right_tabs.removeTab(i)
        act = getattr(self, 'tool_actions', {}).get(name)
        if act is not None and act.isChecked():
            act.blockSignals(True)
            act.setChecked(False)
            act.blockSignals(False)
        if name == 'crop_tab':
            self.crop_btn.setChecked(False)
        elif name == 'profile_tab':
            self.line_btn.setChecked(False)
        elif name == 'roi_tab':
            self.roi_panel.tool_btns['select'].setChecked(True)

    # ---- work log / changes -------------------------------------------------

    def log(self, text):
        self.worklog.add(text, self.current)
        self.set_dirty()

    def set_dirty(self, on=True):
        if on and not self.items and self.project_path is None:
            on = False  # nothing to lose yet
        self.dirty = on
        self._update_title()

    def _update_title(self):
        name = self.project_path.stem if self.project_path is not None else ''
        title = f'Cytosol Viewer {__version__}' + (f' — {name}' if name else '')
        self.setWindowTitle(title + (' *' if self.dirty else ''))

    def _maybe_save(self) -> bool:
        """Before closing the work: True to go on (saved, or not wanted)."""
        if not self.dirty or not self.items:
            return True
        r = QMessageBox.question(
            self, '저장하지 않은 변경', '프로젝트에 저장하지 않은 변경이 있습니다. 저장할까요?',
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save)
        if r == QMessageBox.StandardButton.Cancel:
            return False
        if r == QMessageBox.StandardButton.Save:
            return self.save_project()
        return True

    def _remember_panes(self):
        sizes = self.main_split.sizes()
        view_settings.set_pane_widths(sizes[0], sizes[2])

    def _restore_panes(self):
        """Side panes at their remembered (or default) widths, the preview
        taking the rest."""
        lw, rw = view_settings.pane_widths(LEFT_W, RIGHT_W)
        total = max(sum(self.main_split.sizes()), lw + rw + 400)
        self.main_split.setSizes([lw, total - lw - rw, rw])

    def closeEvent(self, event):
        if not self._maybe_save():
            event.ignore()
            return
        for w in (self.figure_win, self.log_win):
            if w is not None:
                w.close()
        super().closeEvent(event)

    def save_log_csv(self):
        if not self.worklog.entries:
            QMessageBox.information(self, '작업 기록', '아직 기록이 없습니다.')
            return
        base = self.project_path.with_name(f'{self.project_path.stem}_log.csv') \
            if self.project_path else Path('work_log.csv')
        path, _ = QFileDialog.getSaveFileName(self, '작업 기록 저장', str(base), 'CSV (*.csv)')
        if path:
            n = self.worklog.write_csv(path)
            self.statusBar().showMessage(f'작업 기록 {n}줄 저장: {path}', 8000)

    # ---- loading (파일 → 불러오기) -----------------------------------------------

    @staticmethod
    def _path_key(p) -> str:
        try:
            return str(Path(p).resolve()).lower()
        except OSError:
            return str(p).lower()

    def import_files_dialog(self):
        start = str(self.project_path.parent) if self.project_path else ''
        files, _ = QFileDialog.getOpenFileNames(
            self, '불러오기', start,
            '불러올 수 있는 파일 (*.cyproj *.tcf *.TCF *.czi *.oir *.tif *.tiff *.TIF *.TIFF '
            '*.zip *.roi *.json image_groups.csv);;'
            'Cytosol Viewer 프로젝트 (*.cyproj);;'
            'Microscopy (*.tcf *.TCF *.czi *.oir *.tif *.tiff *.TIF *.TIFF);;'
            'ImageJ ROI (*.zip *.roi);;LUT 프리셋 / 마커 설정 (*.json);;All files (*)')
        if files:
            self.import_paths([Path(f) for f in files])

    def import_kind_dialog(self, kind):
        """불러오기 in a feature menu: files of that kind (still recognised by
        their content, so a file of another kind is put where it belongs)."""
        name, filt = IMPORT_KINDS[kind]
        start = str(self.project_path.parent) if self.project_path else ''
        files, _ = QFileDialog.getOpenFileNames(self, f'{name} 불러오기', start,
                                                f'{filt};;All files (*)')
        if not files:
            return
        if kind in ('crop', 'cell', 'particle', 'line') and not self.items:
            QMessageBox.information(self, f'{name} 불러오기', '먼저 이미지를 불러오세요.')
            return
        self.import_paths([Path(f) for f in files])

    def import_folder_dialog(self):
        folder = QFileDialog.getExistingDirectory(self, '불러올 폴더 선택')
        if folder:
            self.import_paths([Path(folder)])

    def import_paths(self, paths):
        """Load whatever was chosen: a project opens (closing the current
        work); LUT presets apply to every image; images, exported TIFFs, ROI
        files and groups go through add_files; a folder is paired by image ID."""
        from .project import is_project_file

        paths = [Path(p) for p in paths]
        projects = [p for p in paths if is_project_file(p)]
        if projects:
            if not self.open_project(projects[0]):
                return
            paths = [p for p in paths if p not in projects]
        folders = [p for p in paths if p.is_dir()]
        presets = [p for p in paths if p.suffix.lower() == '.json' and self._is_preset(p)]
        markers = [p for p in paths if p.suffix.lower() == '.json' and self._is_marker_file(p)]
        files = [p for p in paths if p not in folders and p not in presets and p not in markers]
        for p in markers:
            self.load_marker_settings(p)
        for d in folders:
            self.add_files(folder_files(d), pair=True)
        if files:
            self.add_files(files, pair=True, explicit=True)
        for p in presets:
            self._load_preset_file(p)
        self._refresh_crop_list(select=0)
        if self.current is not None:
            self.update_preview()

    @staticmethod
    def _is_marker_file(path) -> bool:
        import json

        try:
            return json.loads(Path(path).read_text()).get('format') == MARKER_FORMAT
        except Exception:
            return False

    def save_marker_settings(self):
        import json

        from .project import widget_state

        path, _ = QFileDialog.getSaveFileName(self, '마커 설정 저장', 'markers.json', 'JSON (*.json)')
        if not path:
            return
        Path(path).write_text(json.dumps({'format': MARKER_FORMAT, 'version': 1,
                                          'state': widget_state(self.markers)},
                                         ensure_ascii=False, indent=1), encoding='utf-8')
        self.statusBar().showMessage(f'마커 설정 저장: {Path(path).name}')

    def load_marker_settings(self, path):
        import json

        from .project import restore_widgets

        state = json.loads(Path(path).read_text(encoding='utf-8')).get('state', {})
        restore_widgets(self.markers, state)
        self.markers.changed.emit()
        self.statusBar().showMessage(f'마커 설정 불러옴: {Path(path).name}')

    @staticmethod
    def _is_preset(path) -> bool:
        import json

        try:
            return 'channels' in json.loads(Path(path).read_text())
        except Exception:
            return False

    # ---- export dialogs --------------------------------------------------------

    def _options_dialog(self, title, widgets, ok_text='저장…') -> bool:
        """Show option widgets (kept for the next time) in a dialog."""
        from PySide6.QtWidgets import QDialog, QDialogButtonBox

        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        lay = QVBoxLayout(dlg)
        for w in widgets:
            lay.addWidget(w)
            w.show()
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                               | QDialogButtonBox.StandardButton.Cancel)
        box.button(QDialogButtonBox.StandardButton.Ok).setText(ok_text)
        box.accepted.connect(dlg.accept)
        box.rejected.connect(dlg.reject)
        lay.addWidget(box)
        ok = dlg.exec() == QDialog.DialogCode.Accepted
        for w in widgets:
            w.hide()
            w.setParent(None)
        dlg.deleteLater()
        return ok

    def export_images_dialog(self):
        if not self.items:
            QMessageBox.information(self, '내보내기', '먼저 이미지를 불러오세요.')
            return
        from PySide6.QtWidgets import QButtonGroup, QRadioButton

        scope = QGroupBox('저장할 이미지')
        sl = QHBoxLayout(scope)
        cur = QRadioButton('현재 이미지만')
        every = QRadioButton(f'모든 이미지 ({len(self.items)}개)')
        every.setChecked(True)
        grp = QButtonGroup(scope)
        grp.addButton(cur)
        grp.addButton(every)
        sl.addWidget(cur)
        sl.addWidget(every)
        per = QCheckBox('이미지별 폴더에 나눠 저장')
        per.setChecked(self.opt_per_image.isChecked())
        per.setToolTip(self.opt_per_image.toolTip())
        if not self._options_dialog('이미지 내보내기', [scope, self.exp_box, per]):
            return
        self.opt_per_image.setChecked(per.isChecked())
        if cur.isChecked():
            self.export_current()
        else:
            self.export_all()

    def stack_export_dialog(self, kind):
        if self.current is None:
            QMessageBox.information(self, '스택 투영', '먼저 이미지를 고르세요.')
            return
        if kind == 'rotation' and not self.stack_panel.mode_3d.isChecked():
            QMessageBox.information(self, '3D 회전 시리즈',
                                    '스택 탭에서 3D projection을 켠 뒤 저장하세요 (스택 → 스택 탭 열기).')
            self.show_tab('stack_tab')
            return
        box = self.stack_panel.save_box
        if self._options_dialog('스택 투영 저장', [box]):
            self.save_projection(kind)

    # ---- crop ROI files -----------------------------------------------------

    def save_crops_current(self):
        it = self.current
        if it is None or not it.crops:
            QMessageBox.information(self, 'Crop 영역 ROI', '저장할 Crop 영역이 없습니다.')
            return
        default = str(it.path.with_name(f'{item_stem(it)}_crops.zip'))
        path, _ = QFileDialog.getSaveFileName(self, 'Crop 영역 ROI 저장', default,
                                              'ImageJ RoiSet (*.zip)')
        if path:
            f = save_crop_rois(path, it.crops, it.id_properties())
            self.statusBar().showMessage(f'Crop 영역 {len(it.crops)}개 저장: {f}')

    def save_crops_all(self):
        items = [it for it in self.items if it.crops]
        if not items:
            QMessageBox.information(self, 'Crop 영역 ROI', '저장할 Crop 영역이 없습니다.')
            return
        out = QFileDialog.getExistingDirectory(self, 'Crop 영역 ROI를 저장할 폴더')
        if not out:
            return
        per = self.opt_per_image.isChecked()
        stems = unique_stems(items)
        for it in items:
            folder = Path(out) / item_folder(it) if per else Path(out)
            stem = item_stem(it) if per else stems[id(it)]
            save_crop_rois(folder / f'{stem}_crops.zip', it.crops, it.id_properties())
        self.statusBar().showMessage(f'이미지 {len(items)}개의 Crop 영역 ROI 저장: {out}')

    # ---- project files --------------------------------------------------------

    def _panel_objects(self) -> dict:
        """What the project keeps the settings of (attribute widgets)."""
        return {
            'window': self, 'roi': self.roi_panel, 'roi_measure': self.roi_panel.measure,
            'particle': self.particle_panel, 'particle_measure': self.particle_panel.measure,
            'intensity': self.intensity_panel, 'intensity_measure': self.intensity_panel.measure,
            'intensity_bands': self.intensity_panel.bands_measure,
            'coloc': self.coloc_panel, 'profile': self.profile_panel, 'markers': self.markers,
            'stack': self.stack_panel,
        }

    _WINDOW_KEYS = ('align_tcf', 'copy_color', 'show_crop_btn', 'exp_full', 'exp_crops',
                    'exp_composite', 'exp_channels', 'exp_raw', 'exp_all_t', 'exp_format',
                    'exp_fps', 'opt_per_image', 'opt_with_roi')

    def _panel_state(self) -> dict:
        from .project import widget_state

        out = {}
        for key, obj in self._panel_objects().items():
            if obj is self:
                st = widget_state(self)
                out[key] = {k: v for k, v in st.items() if k in self._WINDOW_KEYS}
            else:
                out[key] = widget_state(obj, skip=('tool_btns',))
        return out

    def save_project(self, ask=False) -> bool:
        from .project import EXT

        path = self.project_path
        if ask or path is None:
            default = str(path) if path else str(
                (self.items[0].path.parent if self.items else Path.home()) / f'project{EXT}')
            name, _ = QFileDialog.getSaveFileName(self, '프로젝트 저장', default,
                                                  f'Cytosol Viewer 프로젝트 (*{EXT})')
            if not name:
                return False
            path = Path(name)
            if path.suffix.lower() != EXT:
                path = path.with_suffix(EXT)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.write_project_to(path)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, '프로젝트 저장 실패', str(exc))
            return False
        finally:
            QApplication.restoreOverrideCursor()
        self.project_path = path
        view_settings.add_recent(str(path))
        self.worklog.add(f'프로젝트 저장: {path.name}')
        self.set_dirty(False)
        self.statusBar().showMessage(f'프로젝트 저장: {path}', 8000)
        return True

    def write_project_to(self, path):
        """Write the whole session into a project file (image paths relative to it)."""
        from .project import figure_dict, header, image_entry, item_files, temp_dir, \
            widget_state, write_project

        path = Path(path)
        base = path.parent.resolve()
        data = header()
        files = {}
        with temp_dir() as tmp:
            images = []
            for n, it in enumerate(self.items):
                e = image_entry(it, base)
                e['files'] = item_files(it, n, self.particle_panel.cells_for, files, Path(tmp))
                images.append(e)
            data['images'] = images
            data['current'] = self.items.index(self.current) if self.current in self.items else -1
            data['tabs'] = self.open_tabs()
            cur = self._tab_name(self.right_tabs.currentWidget())
            data['tab_current'] = cur or self.right_tabs.currentIndex()
            data['panels'] = self._panel_state()
            # channels switched off for measuring, by channel name
            data['measure_channels_off'] = {key: sorted(obj.channels_off)
                                            for key, obj in self._panel_objects().items()
                                            if obj in self._measure_boxes()}
            data['batch_rows'] = {key: box.batch_rows for key, box in
                                  (('roi', self.roi_panel.measure),
                                   ('particle', self.particle_panel.measure),
                                   ('intensity', self.intensity_panel.measure))}
            if self.figure_win is not None:
                data['figure'] = figure_dict(self.figure_win.spec, self.items, files)
                data['figure_widgets'] = widget_state(self.figure_win)
            data['log'] = self.worklog.entries
            write_project(path, data, files)

    def new_project(self):
        if not self._maybe_save():
            return
        self._clear_all()
        self.project_path = None
        self.worklog.clear()
        self.set_dirty(False)
        self.statusBar().showMessage('새 프로젝트', 5000)

    def _clear_all(self):
        """Close every image and window that shows them."""
        if self.figure_win is not None:
            self.figure_win.close()
            self.figure_win.deleteLater()
            self.figure_win = None
        if self.items:
            self.file_list.selectAll()
            self.remove_selected(log=False)
        for box in self._measure_boxes():
            box.batch_rows = []
            box.rows = []
            box.set_channels_off(())
            box._fill_table()

    def open_project(self, path) -> bool:
        from .project import read_project, resolve_image, restore_widgets, temp_dir

        path = Path(path)
        try:
            data, files = read_project(path)
        except Exception as exc:
            QMessageBox.warning(self, '프로젝트 열기 실패', f'{path.name}: {exc}')
            return False
        if not self._maybe_save():
            return False
        self._clear_all()
        base = path.parent
        entries = data.get('images', [])
        found = [resolve_image(e, base) for e in entries]
        missing = [e for e, f in zip(entries, found) if f is None]
        if missing:
            names = '\n'.join(e['name'] for e in missing[:15])
            more = f'\n… 외 {len(missing) - 15}개' if len(missing) > 15 else ''
            QMessageBox.information(
                self, '이미지 찾기',
                f'이미지 {len(missing)}개를 원래 위치에서 찾지 못했습니다:\n{names}{more}\n\n'
                '이미지가 있는 폴더를 고르면 그 안(하위 폴더 포함)에서 같은 이름의 파일을 찾습니다.')
            folder = QFileDialog.getExistingDirectory(self, '이미지가 있는 폴더', str(base))
            if folder:
                found = [f if f is not None else resolve_image(e, base, [folder])
                         for e, f in zip(entries, found)]
        prog = QProgressDialog('프로젝트 여는 중…', '취소', 0, len(entries), self)
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        errors, notes, loaded = [], [], []
        self.file_list.blockSignals(True)
        with temp_dir() as tmp:
            for i, (e, f) in enumerate(zip(entries, found)):
                prog.setLabelText(f'불러오는 중: {e["name"]}')
                prog.setValue(i)
                QApplication.processEvents()
                if prog.wasCanceled() or f is None:
                    if f is None:
                        errors.append(f'{e["name"]}: 파일을 찾지 못함')
                    loaded.append(None)
                    continue
                try:
                    it = ImageItem.load(f, label=e.get('label'), **(e.get('load') or {}))
                    self._restore_item(it, e, base, files, Path(tmp), notes)
                except Exception as exc:
                    traceback.print_exc()
                    errors.append(f'{e["name"]}: {exc}')
                    loaded.append(None)
                    continue
                self.items.append(it)
                loaded.append(it)
        prog.setValue(len(entries))
        self.file_list.rebuild(self.items)
        for row in range(len(self.items)):
            self._update_tooltip(row)
        self.file_list.blockSignals(False)
        # settings of every tab, then the tabs that were open
        for key, obj in self._panel_objects().items():
            restore_widgets(obj, (data.get('panels') or {}).get(key, {}))
        off = data.get('measure_channels_off') or {}
        for key, obj in self._panel_objects().items():
            if obj in self._measure_boxes():
                obj.set_channels_off(off.get(key, ()))
        for name in list(self.tab_pages):
            if name in data.get('tabs', []):
                self.show_tab(name, focus=False)
            else:
                self.hide_tab(name)
        rows = data.get('batch_rows') or {}
        for key, box in (('roi', self.roi_panel.measure), ('particle', self.particle_panel.measure),
                         ('intensity', self.intensity_panel.measure)):
            box.batch_rows = list(rows.get(key) or [])
        self.worklog.entries = list(data.get('log') or [])
        self.project_path = path
        cur = data.get('current', 0)
        target = loaded[cur] if 0 <= cur < len(loaded) else None
        if target is None and self.items:
            target = self.items[0]
        if target is not None:
            self.file_list.setCurrentRow(self.items.index(target))
        tab = data.get('tab_current')
        if isinstance(tab, str) and tab in self.tab_pages and self.tab_open(tab):
            self.right_tabs.setCurrentWidget(self.tab_pages[tab][0])
        elif isinstance(tab, int) and 0 <= tab < self.right_tabs.count():
            self.right_tabs.setCurrentIndex(tab)
        if data.get('figure') and self.items:
            self._restore_figure(data, loaded, files)
        for box in self._measure_boxes():
            box._fill_table()
        view_settings.add_recent(str(path))
        self.worklog.add(f'프로젝트 열기: {path.name}')
        self.set_dirty(bool(errors))
        msg = f'프로젝트 {path.name}: 이미지 {len(self.items)}개'
        self.statusBar().showMessage(msg, 8000)
        if errors or notes:
            QMessageBox.warning(self, '프로젝트 열기', '\n'.join(errors + notes))
        return True

    def _restore_item(self, it, e, base, files, tmp, notes):
        from .lut import ChannelLUT
        from .project import restore_item_files

        it.id_suffix = e.get('id_suffix', '')
        if e.get('image_id') and it.image_id != e['image_id']:
            notes.append(f'{it.label}: 이미지 ID가 저장할 때와 다릅니다 ({e["image_id"]} → '
                         f'{it.image_id}). 다른 파일일 수 있습니다.')
        luts = e.get('luts') or []
        if len(luts) == len(it.channels):
            it.luts = [ChannelLUT.from_dict(d) for d in luts]
        it.crops = [c for c in (it.clip_region(*r) for r in e.get('crops', [])) if c]
        it.group = e.get('group', '')
        line = e.get('profile_line')
        it.profile_line = tuple(line) if line else None
        roles = e.get('roi_roles') or {}
        it.roi_roles = {k: roles.get(k) for k in ('nuc', 'bg')} if roles else {}
        s = e.get('particle_settings')
        if s:
            from .intensity import ParticleSettings

            it.particle_settings = ParticleSettings(**s)
        z = e.get('z', 'mip')
        if z in ('mip', 'mid') or (isinstance(z, int) and 0 <= z < it.nz):
            it.z = z
        t = int(e.get('t', 0) or 0)
        if 0 < t < it.nt:
            it.set_t(t)
        it.linked = [p for p in ((base / q) for q in e.get('linked', [])) if p.exists()]
        restore_item_files(it, e.get('files') or {}, files, tmp, notes)

    def _restore_figure(self, data, loaded, files):
        from .figure_window import FigureWindow
        from .project import figure_from, restore_widgets

        try:
            self.figure_win = FigureWindow(self)
            restore_widgets(self.figure_win, data.get('figure_widgets') or {})
            figure_from(self.figure_win.spec, data['figure'], loaded, files.__getitem__)
            self.figure_win.refresh_sources()
            self.figure_win.rebuild_table()
        except Exception:
            traceback.print_exc()

    # ---- files ----------------------------------------------------------

    def add_files_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, '이미지 파일 선택', '',
            'Microscopy (*.tcf *.TCF *.czi *.oir *.tif *.tiff *.TIF *.TIFF);;'
            '이미지 + ROI + 그룹 (*.tcf *.TCF *.czi *.oir *.tif *.tiff *.TIF *.TIFF *.zip *.roi image_groups.csv);;'
            'All files (*)',
        )
        self.add_files([Path(f) for f in files])

    def add_folder_dialog(self):
        folder = QFileDialog.getExistingDirectory(self, '불러올 폴더 선택')
        if folder:
            self.add_files(folder_files(Path(folder)), pair=True)

    def _add_item(self, item: ImageItem):
        self.items.append(item)
        self.file_list.rebuild(self.items)
        self._update_tooltip(len(self.items) - 1)

    def _update_tooltip(self, row):
        it = self.items[row]
        tip = [f'그룹: {it.group}'] if it.group else []
        tip += [str(it.path), f'이미지 ID: {it.image_id} '
               f'({it.image.metadata.get("image_id_source", "")})']
        if it.source_name != it.path.name:
            tip.append(f'원본: {it.source_name}')
        if it.linked:
            tip.append(f'함께 찾은 내보낸 파일 {len(it.linked)}개:')
            tip += [f'  {p.name}' for p in it.linked[:20]]
        if it.cells is not None and len(it.cells):
            tip.append(f'세포 ROI {len(it.cells)}개')
        self.file_list.item(row).setToolTip(0, '\n'.join(tip))

    def _attach_file(self, f, it, notes, replace=False, asked=None) -> int:
        """Put a ROI file saved by this app (or ImageJ) onto an image, by what
        it holds; returns 1 for cell ROIs loaded."""
        link = lambda: f in it.linked or it.linked.append(f)  # noqa: E731
        if is_bleach_file(f):  # bleach regions saved with the images
            it.bleach_rois = load_bleach_rois(f)
            it._info_summary = None
            link()
            return 0
        if is_crop_file(f):  # crop regions saved with the exports
            crops = [c for c in (it.clip_region(*r) for r in load_crop_rois(f)) if c]
            if crops and (replace or not it.crops):
                it.crops = crops
            link()
            return 0
        if is_region_file(f) or is_contour_file(f):
            # logic regions / iso-contour outlines follow from the ROIs: keep with the image
            link()
            return 0
        if is_particle_file(f):  # particle ROIs from the 입자 ROI tab
            self.particle_panel.load_particles_into(it, f)
            link()
            return 0
        line = read_line_roi(f)
        if line is not None:  # a line saved from the profile tab: restore it
            it.profile_line = line[0]
            link()
            return 0
        if it.cells is not None and len(it.cells):
            if not replace:
                link()
                notes.append(f'{f.name}: {it.label}에 이미 ROI가 있어 건너뜀')
                return 0
            if asked is not None:
                if 'replace' not in asked:
                    asked['replace'] = QMessageBox.question(
                        self, '불러오기', '이미 세포 ROI가 있는 이미지는 불러온 ROI로 바꿀까요?'
                    ) == QMessageBox.StandardButton.Yes
                if not asked['replace']:
                    link()
                    return 0
        self.roi_panel.load_into(it, [f])
        link()
        return 1

    def add_files(self, paths, pair=False, explicit=False):
        """Open images and attach ROI files to them by image ID.

        ROI files go to the image with their ID (older ROIs without one: by
        file name) when that image has no ROIs yet; with explicit (files the
        user picked in 불러오기) they replace its ROIs, and ones without a
        match go onto the current image. With pair (loading a
        folder), TIFFs this app exported are grouped by the ID of their
        original: with the original among the loaded images they are only
        listed with it, otherwise the best of them (full raw stack first) is
        opened in its place. Without pair every chosen image is opened.
        """
        group_files = [p for p in paths if p.name == GROUP_FILE]
        paths = [p for p in paths if p.suffix.lower() in SUPPORTED + ROI_EXT]
        if not paths:
            if group_files:
                self._load_groups(group_files)
            return
        plan = plan_pairing(paths)
        if not pair:
            plan['open'] = [p for p in paths if p.suffix.lower() in SUPPORTED]
            plan['exports'] = {}
        if explicit or pair:  # images already in the list are not opened again
            have = {self._path_key(it.path) for it in self.items}
            plan['open'] = [p for p in plan['open'] if self._path_key(p) not in have]
        prog = QProgressDialog('불러오는 중…', '취소', 0, len(plan['open']) + len(plan['exports']),
                               self)
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        errors, notes = [], []
        n_before = len(self.items)

        def load(p, i):
            prog.setLabelText(f'불러오는 중: {p.name}')
            prog.setValue(i)
            QApplication.processEvents()
            try:
                loaded = load_items(p, self.align_tcf.isChecked())
            except Exception as exc:  # keep loading the rest
                errors.append(f'{p.name}: {exc}')
                traceback.print_exc()
                return []
            for item in loaded:
                self._add_item(item)
            return loaded

        i = 0
        for p in plan['open']:
            if prog.wasCanceled():
                break
            load(p, i)
            i += 1
        by_id = {it.image_id: it for it in self.items}
        for iid, files in plan['exports'].items():
            if prog.wasCanceled():
                break
            if iid not in by_id:
                for f in files:  # open the best export that loads
                    loaded = load(f, i)
                    if loaded:
                        by_id[iid] = loaded[0]
                        files = [q for q in files if q != f]
                        break
            if iid in by_id:
                it = by_id[iid]
                it.linked += [f for f in files if f not in it.linked and f != it.path]
            i += 1
        prog.setValue(prog.maximum())

        n_roi = 0
        asked = {}
        for f in plan['rois']:
            it, how = match_roi(f, self.items, item_stem)
            if it is None and explicit and self.current is not None:
                it, how = self.current, '현재 이미지'  # chosen by hand: onto the image shown
                notes.append(f'{f.name}: 짝이 없어 현재 이미지({it.label})에 불러옴')
            if it is None:
                notes.append(f'{f.name}: {how}')
                continue
            try:
                n_roi += self._attach_file(f, it, notes, replace=explicit, asked=asked)
            except Exception as exc:
                errors.append(f'{f.name}: {exc}')
                traceback.print_exc()
        n_grouped = self._load_groups(group_files, errors) if group_files else 0
        for row in range(len(self.items)):
            self._update_tooltip(row)

        if errors:
            QMessageBox.warning(self, '불러오기 실패', '\n'.join(errors))
        if self.current is None and self.items:
            self.file_list.setCurrentRow(0)
        elif self.current is not None:
            self.roi_panel.bind(self.current)
            self.update_preview()
        n_linked = sum(len(it.linked) for it in self.items[n_before:])
        msg = f'이미지 {len(self.items)}개'
        if n_roi or plan['exports']:
            msg += f' · ROI {n_roi}개 연결, 내보낸 파일 {n_linked}개 짝지음'
        if n_grouped:
            msg += f' · 그룹 복원 {n_grouped}개'
        if notes:
            msg += f' · 짝 없는 ROI {len(notes)}개'
            print('\n'.join(notes))
        self.statusBar().showMessage(msg)

    # ---- groups ---------------------------------------------------------

    def _selected_items(self):
        rows = self.file_list.selected_rows()
        if not rows and self.file_list.currentRow() >= 0:
            rows = [self.file_list.currentRow()]
        return [self.items[r] for r in rows]

    def groups(self) -> list[str]:
        """Group names in list order."""
        return list(dict.fromkeys(it.group for it in self.items if it.group))

    def set_group(self, items, name):
        for it in items:
            it.group = name
        self._groups_changed()
        if items:
            self.statusBar().showMessage(f'이미지 {len(items)}개 → 그룹 ‘{name}’' if name
                                         else f'이미지 {len(items)}개를 그룹에서 뺐습니다.')

    def _groups_changed(self):
        self.file_list.rebuild(self.items)
        for row in range(len(self.items)):
            self._update_tooltip(row)
        for box in self._measure_boxes():
            box.regroup()

    def assign_group(self):
        items = self._selected_items()
        if not items:
            QMessageBox.information(self, '그룹 지정', '목록에서 이미지를 선택하세요.')
            return
        names = self.groups()
        # first choice: the name the selected images share (abc, abc_0001 -> abc)
        guess = suggest_name([it.label for it in items]) or f'Group {len(names) + 1}'
        choices = list(dict.fromkeys([guess] + names))
        name, ok = QInputDialog.getItem(
            self, '그룹 지정', f'선택한 이미지 {len(items)}개의 그룹 이름\n'
            '(파일 이름에서 추천한 이름입니다. 고치거나 있는 그룹을 고르세요):',
            choices, 0, True)
        name = name.strip()
        if ok and name:
            self.set_group(items, name)

    def rename_group(self):
        names = self.groups()
        if not names:
            QMessageBox.information(self, '그룹 이름 변경', '아직 그룹이 없습니다. ‘그룹 지정…’으로 만드세요.')
            return
        sel = self._selected_items()
        now = self.file_list.selected_group() or (sel[0].group if sel and sel[0].group else names[0])
        old, ok = QInputDialog.getItem(self, '그룹 이름 변경', '바꿀 그룹:', names,
                                       names.index(now), False)
        if not ok:
            return
        new, ok = QInputDialog.getText(self, '그룹 이름 변경', f'‘{old}’의 새 이름:', text=old)
        new = new.strip()
        if ok and new and new != old:
            self.set_group([it for it in self.items if it.group == old], new)

    def auto_group(self):
        """Group images whose names differ only by a trailing number."""
        items = self._selected_items()
        if len(items) < 2:
            items = self.items
        found = auto_groups([it.label for it in items])
        if not found:
            QMessageBox.information(self, '자동 그룹', '끝의 번호만 다른 이름의 이미지가 없습니다.')
            return
        plan = {}
        for i, name in found.items():
            plan.setdefault(name, []).append(items[i])
        lines = [f'{name}: {len(its)}개' for name, its in plan.items()]
        moved = sum(1 for i, name in found.items() if items[i].group and items[i].group != name)
        text = '다음 그룹을 만듭니다:\n\n' + '\n'.join(lines[:30])
        if len(lines) > 30:
            text += f'\n… 외 {len(lines) - 30}개'
        if moved:
            text += f'\n\n이미 다른 그룹에 있는 이미지 {moved}개도 옮겨집니다.'
        if QMessageBox.question(self, '자동 그룹', text) != QMessageBox.StandardButton.Yes:
            return
        self.apply_auto_groups(plan)

    def apply_auto_groups(self, plan):
        for name, its in plan.items():
            for it in its:
                it.group = name
        self._groups_changed()
        self.statusBar().showMessage(f'자동 그룹: {len(plan)}개 그룹, 이미지 '
                                     f'{sum(map(len, plan.values()))}개')

    def _load_groups(self, files, errors=None) -> int:
        n = 0
        for f in files:
            try:
                n += apply_groups(self.items, read_groups(f))
            except Exception as exc:
                traceback.print_exc()
                if errors is not None:
                    errors.append(f'{f.name}: {exc}')
        if n:
            self._groups_changed()
        return n

    def remove_selected(self, log=True):
        """Remove every selected image (or the current one) from the list."""
        rows = self.file_list.selected_rows()[::-1]
        if not rows and self.file_list.currentRow() >= 0:
            rows = [self.file_list.currentRow()]
        if not rows:
            return
        current_removed = False
        self.file_list.blockSignals(True)  # don't load images on the way
        for row in rows:
            removed = self.items.pop(row)
            current_removed |= removed is self.current
            self.stack_views.pop(id(removed), None)
            removed.image.release()
            if self.figure_win is not None:
                self.figure_win.spec.forget_item(removed)
        self.file_list.clearSelection()
        self.file_list.rebuild(self.items)
        self.file_list.blockSignals(False)
        if self.figure_win is not None:
            self.figure_win.refresh_sources()
        if self.items:
            row = self.items.index(self.current) if not current_removed \
                else min(rows[-1], len(self.items) - 1)
            self.file_list.blockSignals(True)
            self.file_list.setCurrentRow(row)
            self.file_list.blockSignals(False)
            if current_removed:
                self.current = None
                self._select(row)
        else:
            self.current = None
            self.tcache.follow(None)
            self._build_panels()
            self._build_stack_panels()
            self.profile_panel.bind(None)
            self.coloc_panel.bind(None)
            self.particle_panel.bind(None)
            self.intensity_panel.bind(None)
            self.info_panel.bind(None)
            self.canvas.show_line(None)
            self.roi_panel.bind(None)
            self.roi_panel.draw_overlay(hidden=True)
            self.canvas.pix.setPixmap(QPixmap())
        self.statusBar().showMessage(f'이미지 {len(rows)}개를 목록에서 제거했습니다.',
                                     0 if log else 3000)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.import_paths([Path(url.toLocalFile()) for url in event.mimeData().urls()])

    # ---- selection ------------------------------------------------------

    def _select(self, row):
        if row < 0 or row >= len(self.items):
            return
        prev = self.current
        if prev is not None and prev is not self.items[row]:
            prev.image.release()  # a lazy (TCF) volume is read again when needed
        self.current = self.items[row]
        it = self.current
        it.time_cache = self.tcache
        self.tcache.follow(it)
        self._sync_z_widgets()
        self.t_slider.blockSignals(True)
        self.t_slider.setRange(0, max(it.nt - 1, 0))
        self.t_slider.setValue(it.t)
        self.t_slider.blockSignals(False)
        self.t_row.setVisible(it.nt > 1)
        self._t_preview_label(it.t)
        self._build_panels()
        self.roi_panel.bind(it)
        self._refresh_crop_list(select=0)
        self.stack_panel.bind(self._stack_view(it))
        self._build_stack_panels()
        self.profile_panel.bind(it)
        self.coloc_panel.bind(it)
        self.particle_panel.bind(it)
        self.intensity_panel.bind(it)
        self.info_panel.bind(it)
        self.markers.set_bleach_count(it.bleach_rois, it.pixel_um)
        c, z, h, w = it.image.shape
        px = it.pixel_um
        self.info.setText(
            f'{w}×{h} px, Z {z}, C {c}' + (f', T {it.nt}' if it.nt > 1 else '')
            + (f', {px:.4f} µm/px' if px else ', 픽셀 크기 없음')
            + f', ID {it.image_id}'
        )
        self.update_preview(refit=True)

    def _build_panels(self):
        for p in self.panels:
            p.setParent(None)
            p.deleteLater()
        self.panels = []
        if self.current is not None:
            for i in range(len(self.current.channels)):
                panel = ChannelPanel(i)
                panel.bind(self.current)
                panel.changed.connect(self.update_preview)
                panel.changed.connect(self.set_dirty)
                panel.applyAll.connect(self.apply_channel_to_all)
                self.channel_box.insertWidget(self.channel_box.count() - 1, panel)
                self.panels.append(panel)
        self.visibility.set_panels(self.panels)

    def _t_preview_label(self, t):
        it = self.current
        if it is None or it.nt < 2:
            self.t_label.setText('')
            return
        times = it.image.times
        t = max(0, min(int(t), it.nt - 1))
        text = self.markers.time_style().text(times[t], times[-1] - times[0], t)
        self.t_label.setText(f'{t + 1}/{it.nt}  ({text.strip()})')

    def _t_value(self, t):
        if self.t_slider.isSliderDown():
            self._t_scrub(t)
        else:  # keys, clicks on the groove, wheel
            self._t_changed(t)

    def _t_scrub(self, t):
        """While dragging: draw timepoint t if it is loaded, else load it in the background."""
        it = self.current
        if it is None:
            return
        self._t_preview_label(t)
        self.tcache.follow(it, t)
        if self._stack_on():
            return  # projections need the whole volume: on release
        found = self.tcache.get_entry(it, t)
        if found is None:
            self._t_want = t  # drawn by _t_ready once read
            return
        self._t_want = None
        it.set_t(t)
        it.show_planes(*found)
        self.update_preview(light=True)

    def _t_ready(self, item, t):
        if item is self.current and self.tcache.reading_ahead(item):
            done = self.tcache.cached(item, exact=True)
            if done < item.nt:
                self.statusBar().showMessage(f'시점 미리 읽는 중 {done}/{item.nt}', 3000)
            else:
                self.statusBar().showMessage(f'모든 시점({item.nt}) 미리 읽기 완료', 3000)
        dragging = self.t_slider.isSliderDown() or self._scrub0 is not None
        if item is self.current and t == self._t_want and dragging:
            found = self.tcache.get_entry(item, t)
            if found is None:
                return
            self._t_want = None
            item.set_t(t)
            item.show_planes(*found)
            self.update_preview(light=True)

    # ---- right-drag through T and Z ----------------------------------------

    def _can_scrub(self) -> bool:
        it = self.current
        return it is not None and (it.nt > 1 or it.nz > 1) and not self._stack_on()

    def _scrub_start(self):
        it = self.current
        self._scrub0 = (it.t, it.z) if it is not None else None

    def _scrub_drag(self, dx, dy):
        """Right-drag on the image: left/right moves T, up/down moves Z; the
        whole range takes about 80% of the view (at least a few pixels a step)."""
        it = self.current
        if it is None or self._scrub0 is None:
            return
        t0, z0 = self._scrub0
        vp = self.canvas.viewport()
        t = t0
        if it.nt > 1:
            step = max(4.0, 0.8 * vp.width() / it.nt) / view_settings.value('scrub_drag')
            t = int(np.clip(t0 + round(dx / step), 0, it.nt - 1))
        z = it.z
        if it.nz > 1:
            step = max(4.0, 0.8 * vp.height() / it.nz) / view_settings.value('scrub_drag')
            dz = -round(dy / step)  # up = higher slice, like the Z slider
            if z0 in ('mip', 'mid') and dz == 0:
                z = z0  # MIP stays until the drag clearly goes up or down
            else:
                base = it.nz // 2 if z0 in ('mip', 'mid') else int(z0)
                z = int(np.clip(base + dz, 0, it.nz - 1))
        if z != it.z:
            it.z = z
            self._sync_z_widgets()
        if t != self.t_slider.value():
            self.t_slider.blockSignals(True)
            self.t_slider.setValue(t)
            self.t_slider.blockSignals(False)
        self._t_preview_label(t)
        if it.nt < 2:  # Z only: read the plane here
            self.update_preview(light=True)
            return
        self.tcache.follow(it, t)
        found = self.tcache.get_entry(it, t)
        if found is None:
            self._t_want = t  # drawn by _t_ready once read
            return
        self._t_want = None
        it.set_t(t)
        it.show_planes(*found)
        self.update_preview(light=True)

    def _wheel_t(self, steps) -> bool:
        """The wheel (without Cmd/Ctrl) moves through time on a time series."""
        it = self.current
        if it is None or it.nt < 2 or self.t_slider.isSliderDown():
            return False
        if steps:
            self.t_slider.setValue(int(np.clip(self.t_slider.value() + steps, 0, it.nt - 1)))
        return True

    def _scrub_end(self):
        it = self.current
        self._scrub0 = None
        if it is not None:
            self._t_changed(self.t_slider.value())

    def _t_changed(self, t):
        it = self.current
        if it is None:
            return
        self._t_want = None
        self.tcache.follow(it)  # the slider rests: read here (read-ahead goes on)
        if t != it.t or it._planes_preview:  # a drag may have left a preview plane
            cached = self.tcache.get(it, t) is not None
            if not cached:
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                it.set_t(t)
                it.drop_preview()
                it.planes()  # the exact plane
            except Exception as exc:
                traceback.print_exc()
                QMessageBox.warning(self, '시점 불러오기 실패', str(exc))
            finally:
                if not cached:
                    QApplication.restoreOverrideCursor()
        self._t_preview_label(it.t)
        if self._stack_on():
            self._t_refresh()
            return
        self.update_preview(light=True)
        self._t_full.start()  # histograms and the rest once T stops changing

    def _t_refresh(self):
        it = self.current
        if it is None:
            return
        for p in self.panels:
            p.bind(it)
        self.update_preview()

    # ---- Z ----------------------------------------------------------------

    def _sync_z_widgets(self):
        it = self.current
        nz = it.nz if it is not None else 1
        for w in (self.z_slider, self.z_mip):
            w.blockSignals(True)
        self.z_slider.setRange(1, max(nz, 1))
        self.z_slider.setPageStep(max(1, nz // 10))
        mip = it is None or it.z == 'mip'
        z = nz // 2 if mip or it.z == 'mid' else int(it.z)
        self.z_slider.setValue(z + 1)
        self.z_mip.setChecked(mip)
        for w in (self.z_slider, self.z_mip):
            w.blockSignals(False)
        self.z_col.setEnabled(nz > 1 and not self._stack_on())
        self._z_label()

    def _z_label(self):
        it = self.current
        if it is None:
            self.z_label.setText('')
        elif it.z == 'mip':
            self.z_label.setText(f'MIP\n({it.nz})')
        else:
            vz = it.image.voxel_size_um.get('Z')
            z = self.z_slider.value()
            um = f'\n{(z - 1) * float(vz):.1f} µm' if vz else ''
            self.z_label.setText(f'{z}/{it.nz}{um}')

    def _z_slider_moved(self, _):
        if self.z_mip.isChecked():
            self.z_mip.blockSignals(True)
            self.z_mip.setChecked(False)
            self.z_mip.blockSignals(False)
        self._z_timer.start()

    def _z_mip_toggled(self, _):
        self._z_timer.start()

    def _z_changed(self):
        it = self.current
        if it is None:
            return
        z = 'mip' if self.z_mip.isChecked() else self.z_slider.value() - 1
        if z == it.z:
            return
        it.z = z
        self.tcache.follow(it)  # planes loaded for the old Z no longer apply
        self._z_label()
        try:
            for p in self.panels:
                p.bind(it)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, 'Z 불러오기 실패', str(exc))
            return
        self.update_preview()

    # ---- stack tab ---------------------------------------------------------

    def _stack_on(self) -> bool:
        return self.tab_current('stack_tab')

    def _stack_view(self, it) -> StackView:
        view = self.stack_views.get(id(it))
        if view is None:
            view = self.stack_views[id(it)] = StackView(it)
        return view

    def _build_stack_panels(self):
        for p in self.stack_panels:
            p.setParent(None)
            p.deleteLater()
        self.stack_panels = []
        if self.current is not None:
            view = self._stack_view(self.current)
            for i in range(len(self.current.channels)):
                panel = ChannelPanel(i)
                panel.all_btn.hide()
                panel.bind(view)
                panel.changed.connect(self._stack_lut_edited)
                self.stack_panel.lut_box.addWidget(panel)
                self.stack_panels.append(panel)
        self.stack_panel.visibility.set_panels(self.stack_panels)

    def _stack_lut_edited(self):
        view = self.stack_views.get(id(self.current))
        if view is not None and view.linked:
            view.push()
            for p in self.panels:
                p.refresh()
        self.update_preview()

    def _tab_changed(self, _):
        it = self.current
        if self._stack_on():
            self.line_btn.setChecked(False)  # projections have their own geometry
        if not self._stack_on() and it is not None:
            it.image.release()
        self._sync_z_widgets()
        if it is not None and self.tab_current('roi_tab'):
            self.roi_panel.show_auto_values(it)
        self.update_preview(refit=True)
        self.roi_panel.measure.schedule()
        self.particle_panel.schedule()
        self.intensity_panel.schedule()

    def rois_changed(self, hidden=False):
        """The cell ROIs or the shown plane changed: particles and every
        measurement follow."""
        if not hasattr(self, 'intensity_panel'):
            return  # still building the window
        self.roi_panel.measure.schedule()
        self.particle_panel.overlay_changed(hidden)
        self.intensity_panel.overlay_changed(hidden)

    def particles_changed(self):
        self.intensity_panel.schedule()

    def _stack_preview(self, refit=False):
        import time

        it = self.current
        view = self._stack_view(it)
        self.stack_panel.read(region=it.crops[self._selected_crop()]
                              if self._selected_crop() is not None else None)
        three = view.settings.mode == '3d'
        self.canvas.set_view3d(three)
        # what has to be (re)built: 2D needs the volume for every new projection,
        # 3D only when its structure changes (not for a new angle)
        rebuild = view.raw3d_key != view.struct_key() if three else view.key() != view.result_key
        if rebuild and it.image.lazy and not it.image.volume_loaded:
            self.stack_panel.status.setText('Z 스택 불러오는 중…' if not three
                                            else '3D 구조 만드는 중 (한 번만)…')
            QApplication.processEvents()
        pulled = view.sync()  # linked LUTs first, so a new 3D structure uses them
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        t0 = time.perf_counter()
        try:
            rgb = view.preview_rgb()
        except Exception as exc:
            traceback.print_exc()
            self.stack_panel.status.setText(f'투영 실패: {exc}')
            return
        finally:
            QApplication.restoreOverrideCursor()
        dt = time.perf_counter() - t0
        pulled = view.sync() or pulled
        for p in self.stack_panels:
            if rebuild:
                p.bind(view)  # new data: new histogram and range
            elif pulled:
                p.refresh()
        rgb = view.decorate(rgb, self.markers.scale_style(), self.markers.time_style())
        self._t_preview_label(it.t)
        shape = rgb.shape
        self.canvas.set_image(to_qimage(rgb))
        if refit or shape != self._last_shape:
            self.canvas.fit()
        self._last_shape = shape
        self.canvas.show_crops([])
        self.roi_panel.draw_overlay(hidden=True)
        self.canvas.show_line(None)
        self.stack_panel.set_stale(three and view.lut_stale())
        if three:
            self.stack_panel.status.setText(
                f'{view.describe()} · {dt:.2f}초 · 3D 구조 {view.structure_mb():.0f} MB'
                + (' (새로 만듦)' if rebuild else ''))
        elif rebuild:
            mb = it.image.data.nbytes / 1e6 if it.image.volume_loaded else 0
            self.stack_panel.status.setText(
                f'{view.describe()} · {dt:.2f}초' + (f' · 스택 {mb:.0f} MB' if mb else ''))

    def _refresh_3d(self):
        it = self.current
        if it is None:
            return
        view = self._stack_view(it)
        if view.raw3d is not None:
            view.refresh_3d()
        self.update_preview()

    def save_projection(self, kind):
        it = self.current
        if it is None:
            return
        view = self._stack_view(it)
        self.stack_panel.read(region=it.crops[self._selected_crop()]
                              if self._selected_crop() is not None else None)
        st = view.settings
        tag = (f'{st.mode}_{st.method_2d}' if st.mode == '2d'
               else f'3d_{st.method_3d}_{st.axis}{st.angle:.0f}')
        if kind == 'rotation':
            tag = f'3d_{st.method_3d}_{st.axis}rotation'
        default = str(it.path.with_name(f'{item_stem(it)}_{tag}.tif'))
        path, flt = QFileDialog.getSaveFileName(self, '투영 저장', default,
                                                'TIFF (*.tif);;MP4 동영상 (*.mp4)')
        if not path:
            return
        movie = path.lower().endswith('.mp4') or ('mp4' in flt.lower()
                                                  and not path.lower().endswith('.tif'))
        stem = path[:-4] if path.lower().endswith(('.tif', '.mp4')) else path
        fps = self.stack_panel.fps.value() if movie else None
        full = self.stack_panel.save_full.isChecked()
        if kind == 'rotation':
            a, b, step = (self.stack_panel.rot_from.value(), self.stack_panel.rot_to.value(),
                          self.stack_panel.rot_step.value())
            angles = list(range(a, b + 1, step)) if b >= a else list(range(a, b - 1, -step))
            n = len(angles)
        else:
            n = it.nt if self.stack_panel.save_all_t.isChecked() and it.nt > 1 else 1
        prog = QProgressDialog('투영 저장 중…', '취소', 0, n, self)
        prog.setWindowModality(Qt.WindowModality.WindowModal)

        def progress(i, total):
            prog.setValue(i)
            QApplication.processEvents()
            return not prog.wasCanceled()

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if kind == 'rotation':
                files = export_rotation(view, stem, angles, self.markers.scale_style(),
                                        self.markers.time_style(), full_res=full,
                                        progress=progress, movie_fps=fps)
            else:
                files = export_projection(view, stem, self.markers.scale_style(),
                                          self.markers.time_style(),
                                          all_times=n > 1, full_res=full, progress=progress,
                                          movie_fps=fps)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, '저장 실패', str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
            prog.setValue(n)
        QMessageBox.information(self, '저장 완료', '\n'.join(files) or '저장한 파일이 없습니다.')
        self.update_preview()

    # ---- preview --------------------------------------------------------

    def _selected_crop(self):
        it = self.current
        row = self.crop_list.currentRow()
        if it is None or row < 0 or row >= len(it.crops):
            return None
        return row

    def update_preview(self, refit=False, light=False):
        """Redraw the image; ``light`` (while T changes) skips the line profile."""
        it = self.current
        if it is None:
            return
        if self._stack_on():
            self._stack_preview(refit=refit)
            return
        self._last_shape = None
        self.canvas.set_view3d(False)
        sel = self._selected_crop()
        only = self.show_crop_btn.isChecked() and sel is not None
        if self.roi_panel.show_input() and not only:
            rgb = self.roi_panel.preview_rgb(it)
        else:
            rgb = it.composite(it.crops[sel] if only else None)
        rgb = it.decorate(rgb, self.markers.scale_style(), self.markers.time_style(),
                          outline=self.markers.outline_style(), region=it.crops[sel] if only else None)
        self._t_preview_label(it.t)
        self.canvas.set_image(to_qimage(rgb), refit=refit and only)
        if refit and not only:
            self.canvas.fit()
        self.canvas.show_crops([] if only else it.crops, sel)
        self.roi_panel.draw_overlay(hidden=only)
        self._draw_profile_line()
        if not light:
            self.profile_panel.schedule()

    # ---- line profile ---------------------------------------------------

    def _view_offset(self):
        """Image-pixel origin of what the canvas shows (a crop when 'only crop' is on)."""
        it = self.current
        sel = self._selected_crop()
        if it is not None and self.show_crop_btn.isChecked() and sel is not None:
            return it.crops[sel][:2]
        return 0, 0

    def _line_mode(self, on):
        self.profile_panel.draw_btn.setChecked(on)
        if on:
            self.crop_btn.setChecked(False)
            self.show_tab('profile_tab')  # also leaves the stack tab
        self.canvas.set_line_mode(on)

    def _line_drawn(self, x0, y0, x1, y1):
        it = self.current
        if it is None or self._stack_on():
            self.canvas.show_line(None)
            return
        if x0 >= 0:
            ox, oy = self._view_offset()
            self.profile_panel.set_line((x0 + ox, y0 + oy, x1 + ox, y1 + oy))
        self._draw_profile_line()

    def _draw_profile_line(self):
        it = self.current
        line = getattr(it, 'profile_line', None)
        if line is None or self._stack_on():
            self.canvas.show_line(None)
            return
        ox, oy = self._view_offset()
        x0, y0, x1, y1 = line
        self.canvas.show_line((x0 - ox, y0 - oy, x1 - ox, y1 - oy),
                              self.profile_panel.width.value())

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

    def _crop_moved(self, k, dx, dy):
        it = self.current
        if it is None or k >= len(it.crops):
            return
        x0, y0, x1, y1 = it.move_crop(k, dx, dy)
        self._refresh_crop_list(select=k)
        self.statusBar().showMessage(f'Crop {k + 1} 이동: x {x0}–{x1}, y {y0}–{y1}')
        self.update_preview()

    def _crop_picked(self, k):
        if k != self.crop_list.currentRow():
            self.crop_list.setCurrentRow(k)

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
        shape = it.image.shape[-2:]
        n = 0
        for other in self.items:
            if other is not it and other.image.shape[-2:] == shape:
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

    def _load_preset_file(self, path):
        n = load_preset(self.items, path)
        for p in self.panels:
            p.refresh()
        self.update_preview()
        self.statusBar().showMessage(f'LUT 프리셋 {Path(path).name}: 채널 {n}개에 적용')

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
            rgb_format=self.exp_format.currentData(),
            fps=self.exp_fps.value(),
            outline=self.markers.outline_style(export=True),
        )

    def _export(self, items):
        if not items:
            return
        out = QFileDialog.getExistingDirectory(self, '저장할 폴더 선택')
        if not out:
            return
        kwargs = self._export_kwargs()
        per_image = self.opt_per_image.isChecked()
        stems = unique_stems(items)
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
                if per_image:
                    files += export_item(it, Path(out) / item_folder(it), **kwargs)
                else:
                    files += export_item(it, Path(out), stem=stems[id(it)], **kwargs)
            except Exception as exc:
                errors.append(f'{it.label}: {exc}')
                traceback.print_exc()
            it.image.release()
        prog.setValue(len(items))
        write_groups(Path(out) / GROUP_FILE, items)
        self.statusBar().showMessage(f'이미지 내보내기: 이미지 {len(items)}개, 파일 {len(files)}개 → {out}')
        msg = f'파일 {len(files)}개를 저장했습니다.\n{out}'
        if errors:
            msg += '\n\n실패:\n' + '\n'.join(errors)
        QMessageBox.information(self, '저장 완료', msg)

    def _measure_boxes(self):
        return [self.roi_panel.measure, self.particle_panel.measure, self.intensity_panel.measure,
                self.intensity_panel.bands_measure]

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
        n_done, n_files, rows, errors, coloc, intensity = 0, 0, [], [], [], {}
        for i, it in enumerate(items):
            if prog.wasCanceled():
                break
            prog.setLabelText(f'저장 중: {it.label}')
            prog.setValue(i)
            QApplication.processEvents()
            folder = Path(out) / item_folder(it)
            try:
                n_files += len(export_item(it, folder, **kwargs))
                has_cells = it.cells is not None and len(it.cells)
                if has_cells:
                    item_rows = self.roi_panel.save_item(it, folder)
                    write_csv(folder / f'{item_stem(it)}_cell_rois.csv', item_rows)
                    rows += item_rows
                for box in self._measure_boxes():
                    if box.has_rois(it):  # particles may cover the whole image
                        item_int = box.measure_item(it)
                        box.save_item(it, folder, item_int, companions=False)
                        intensity.setdefault(box.suffix, []).extend(item_int)
                pcells = self.particle_panel.cells_for(it)
                p = self.particle_panel.particles_for(it) if pcells is not None and len(pcells) else None
                if p is not None and p.mask.any():
                    self.particle_panel.save_particle_files(
                        it, folder / f'{item_stem(it)}_particles.zip', pcells, p)
                if has_cells:
                    self.intensity_panel._region_file(it, folder / item_stem(it))
                write_csv_rows(folder / f'{item_stem(it)}_info.csv', summarize(it).rows_csv())
                if it.coloc:
                    write_coloc_csv(folder / f'{item_stem(it)}_coloc2.csv', it.coloc)
                    coloc += it.coloc
                n_done += 1
            except Exception as exc:
                errors.append(f'{it.label}: {exc}')
                traceback.print_exc()
            it.image.release()
        prog.setValue(len(items))
        write_csv(Path(out) / 'cell_rois.csv', rows)
        write_coloc_csv(Path(out) / 'coloc2.csv', coloc)
        boxes = {box.suffix: box for box in self._measure_boxes()}
        for suffix, int_rows in intensity.items():
            write_rows(Path(out) / f'{suffix}.csv', int_rows)
            boxes[suffix].write_summaries(out, int_rows)
        write_groups(Path(out) / GROUP_FILE, items)
        try:
            self.write_project_to(Path(out) / 'project.cyproj')
        except Exception as exc:
            traceback.print_exc()
            errors.append(f'project.cyproj: {exc}')
        self.statusBar().showMessage(f'모든 분석 결과 통합 저장: 이미지 {n_done}개 → {out}')
        msg = f'이미지 {n_done}개를 이미지별 폴더에 저장했습니다 (파일 {n_files}개'
        msg += f', ROI 측정 {len(rows)}행).' if rows else ').'
        msg += f'\n{out}'
        if errors:
            msg += '\n\n실패:\n' + '\n'.join(errors)
        QMessageBox.information(self, '저장 완료', msg)


def main(argv=None):
    argv = sys.argv if argv is None else argv
    app = QApplication(argv)
    app.setApplicationName('Cytosol Viewer')
    app.setApplicationVersion(__version__)
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
