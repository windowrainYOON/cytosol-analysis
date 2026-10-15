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
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
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
from .imageid import ROI_EXT, match_roi, plan_pairing
from .marker_panel import MarkerPanel
from .lineprofile import read_line_roi
from .prefetch import TimeCache
from .profile_panel import ProfilePanel
from .movie import RGB_FORMATS, wants_mp4
from .roi_panel import RoiPanel, write_csv
from .stack import StackView, export_projection, export_rotation
from .stack_panel import StackPanel
from .version import __version__

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
LASSO_COLORS = {'add': QColor(80, 255, 120), 'sub': QColor(255, 80, 80), 'new': QColor(80, 220, 255)}


def folder_files(folder: Path) -> list[Path]:
    """Images and ROI files anywhere under folder (hidden files skipped)."""
    return sorted(q for q in folder.rglob('*')
                  if q.is_file() and not q.name.startswith('.')
                  and q.suffix.lower() in SUPPORTED + ROI_EXT)


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
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.scale(factor, factor)

    def mousePressEvent(self, event):
        btn = event.button()
        if btn == Qt.MouseButton.RightButton and self.view3d:
            self._rot = (event.position(), None)
            self.viewport().setCursor(Qt.CursorShape.SizeAllCursor)
            self.rotateStarted.emit()
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
            self.zoom_item.setRect(QRectF(pos, pos))
            self.zoom_item.show()
            return
        if self.crop_mode and btn == Qt.MouseButton.LeftButton:
            self._origin = pos
            self.rect_item.setRect(QRectF(self._origin, self._origin))
            self.rect_item.show()
            return
        if self.line_mode and btn == Qt.MouseButton.LeftButton:
            self._line_origin = (pos.x(), pos.y())
            width = self._line[4] if self._line else 1
            self.show_line((*self._line_origin, pos.x(), pos.y()), width)
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
        if btn == Qt.MouseButton.LeftButton and not self._drawing():
            k = self._crop_at(pos)
            if k is not None:
                self._crop_drag = [k, pos, False]
                self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
                return
        if btn == Qt.MouseButton.LeftButton:
            self._press_view = event.position()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
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
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
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
            self._lasso_item.setPath(polygon_path(np.asarray(self._lasso)))
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
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

        # left: file list
        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.file_list.setToolTip('Shift/Ctrl(⌘)+클릭으로 여러 개 선택, Delete 키로 목록에서 제거')
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
        ll.addWidget(folder_btn)
        ll.addWidget(rm_btn)

        # left, below files: crop regions of the current image
        self.crop_list = QListWidget()
        self.crop_list.setMaximumHeight(160)
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
        self.canvas.cropMoved.connect(self._crop_moved)
        self.canvas.cropPicked.connect(self._crop_picked)
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
        self.show_crop_btn = QCheckBox('선택한 Crop만 보기')
        self.show_crop_btn.toggled.connect(lambda _: self.update_preview(refit=True))
        self.line_btn = QPushButton('라인 프로파일 (선 그리기)')
        self.line_btn.setCheckable(True)
        self.line_btn.setToolTip('이미지 위에서 드래그해 선을 그리면 채널별 강도 그래프를 '
                                 '‘라인 프로파일’ 탭에 보여줍니다. Shift: 수평·수직·45°.')
        fit_btn = QPushButton('화면 맞춤')
        fit_btn.clicked.connect(self.canvas.fit)
        self.zoom_btn = QPushButton('영역 확대')
        self.zoom_btn.setCheckable(True)
        self.zoom_btn.setToolTip('누른 뒤 이미지 위에서 사각형을 드래그하면 그 영역을 확대합니다.\n'
                                 '버튼 없이 Shift + 드래그로도 됩니다. 원래대로: 화면 맞춤.')
        self.zoom_btn.toggled.connect(self.canvas.set_zoom_mode)
        self.canvas.zoomDone.connect(lambda: self.zoom_btn.setChecked(False))
        self.t_slider = QSlider(Qt.Orientation.Horizontal)
        # while dragging, timepoints are read in a thread (TimeCache) and drawn
        # as they arrive; histograms and the line profile follow when it stops
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
        bar1.addWidget(self.show_crop_btn)
        bar1.addStretch()
        bar1.addWidget(self.line_btn)
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
        self.exp_per_image = QCheckBox('이미지별 폴더에 나눠 저장')
        self.exp_per_image.setChecked(True)
        self.exp_per_image.setToolTip('폴더 안에 이미지마다 하위 폴더(이미지 이름_이미지 ID)를 만들어 그 이미지의 파일을 넣습니다.')
        exp_btn = QPushButton('모든 이미지 저장…')
        exp_btn.clicked.connect(self.export_all)
        exp_one = QPushButton('현재 이미지만 저장…')
        exp_one.clicked.connect(self.export_current)
        exp = QGroupBox('일괄 저장 (TIFF / MP4)')
        el = QVBoxLayout(exp)
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
        el.addWidget(self.exp_per_image)
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
        self.visibility = VisibilityRow()
        rl.addWidget(self.visibility)
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
        self.stack_panel = StackPanel()
        self.stack_panel.changed.connect(self.update_preview)
        self.stack_panel.saveRequested.connect(self.save_projection)
        self.stack_panel.refreshRequested.connect(self._refresh_3d)
        self.canvas.rotateStarted.connect(self.stack_panel.begin_drag)
        self.canvas.rotateDragged.connect(self.stack_panel.drag_rotate)
        self.stack_panels: list[ChannelPanel] = []
        self.stack_views: dict[int, StackView] = {}
        stack_scroll = QScrollArea()
        stack_scroll.setWidgetResizable(True)
        stack_scroll.setWidget(self.stack_panel)
        self.stack_tab = right.addTab(stack_scroll, '스택')
        self.profile_panel = ProfilePanel()
        self.profile_panel.changed.connect(self._draw_profile_line)
        self.profile_tab = right.addTab(self.profile_panel, '라인 프로파일')
        self.coloc_panel = ColocPanel(self)
        coloc_scroll = QScrollArea()
        coloc_scroll.setWidgetResizable(True)
        coloc_scroll.setWidget(self.coloc_panel)
        right.addTab(coloc_scroll, 'Coloc 2')
        self.canvas.lineDrawn.connect(self._line_drawn)
        self.line_btn.toggled.connect(self._line_mode)
        self.profile_panel.draw_btn.toggled.connect(self.line_btn.setChecked)
        self.crop_btn.toggled.connect(lambda on: on and self.line_btn.setChecked(False))
        right.currentChanged.connect(self._tab_changed)
        self.right_tabs = right
        self._last_shape = None
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
        folder_act = QAction('폴더 불러오기 (ID로 이미지·TIFF·ROI 짝짓기)…', self)
        folder_act.setShortcut(QKeySequence('Ctrl+Shift+O'))
        folder_act.triggered.connect(self.add_folder_dialog)
        menu = self.menuBar().addMenu('파일')
        menu.addAction(open_act)
        menu.addAction(folder_act)
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
            'Microscopy (*.tcf *.TCF *.czi *.oir *.tif *.tiff *.TIF *.TIFF);;'
            '이미지 + ROI (*.tcf *.TCF *.czi *.oir *.tif *.tiff *.TIF *.TIFF *.zip *.roi);;'
            'All files (*)',
        )
        self.add_files([Path(f) for f in files])

    def add_folder_dialog(self):
        folder = QFileDialog.getExistingDirectory(self, '불러올 폴더 선택')
        if folder:
            self.add_files(folder_files(Path(folder)), pair=True)

    def _add_item(self, item: ImageItem):
        self.items.append(item)
        entry = QListWidgetItem(item.label)
        self.file_list.addItem(entry)
        self._update_tooltip(len(self.items) - 1)

    def _update_tooltip(self, row):
        it = self.items[row]
        tip = [str(it.path), f'이미지 ID: {it.image_id} '
               f'({it.image.metadata.get("image_id_source", "")})']
        if it.source_name != it.path.name:
            tip.append(f'원본: {it.source_name}')
        if it.linked:
            tip.append(f'함께 찾은 내보낸 파일 {len(it.linked)}개:')
            tip += [f'  {p.name}' for p in it.linked[:20]]
        if it.cells is not None and len(it.cells):
            tip.append(f'세포 ROI {len(it.cells)}개')
        self.file_list.item(row).setToolTip('\n'.join(tip))

    def add_files(self, paths, pair=False):
        """Open images and attach ROI files to them by image ID.

        ROI files go to the image with their ID (older ROIs without one: by
        file name) when that image has no ROIs yet. With pair (loading a
        folder), TIFFs this app exported are grouped by the ID of their
        original: with the original among the loaded images they are only
        listed with it, otherwise the best of them (full raw stack first) is
        opened in its place. Without pair every chosen image is opened.
        """
        paths = [p for p in paths if p.suffix.lower() in SUPPORTED + ROI_EXT]
        if not paths:
            return
        plan = plan_pairing(paths)
        if not pair:
            plan['open'] = [p for p in paths if p.suffix.lower() in SUPPORTED]
            plan['exports'] = {}
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
        for f in plan['rois']:
            it, how = match_roi(f, self.items, item_stem)
            if it is None:
                notes.append(f'{f.name}: {how}')
                continue
            line = read_line_roi(f)
            if line is not None:  # a line saved from the profile tab: restore it
                it.profile_line = line[0]
                if f not in it.linked:
                    it.linked.append(f)
                continue
            if it.cells is not None and len(it.cells):
                if f not in it.linked:
                    it.linked.append(f)
                notes.append(f'{f.name}: {it.label}에 이미 ROI가 있어 건너뜀')
                continue
            try:
                self.roi_panel.load_into(it, [f])
                it.linked.append(f)
                n_roi += 1
            except Exception as exc:
                errors.append(f'{f.name}: {exc}')
                traceback.print_exc()
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
        if notes:
            msg += f' · 짝 없는 ROI {len(notes)}개'
            print('\n'.join(notes))
        self.statusBar().showMessage(msg)

    def remove_selected(self):
        """Remove every selected image (or the current one) from the list."""
        rows = sorted({i.row() for i in self.file_list.selectedIndexes()}, reverse=True)
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
            self.file_list.takeItem(row)
            if self.figure_win is not None:
                self.figure_win.spec.forget_item(removed)
        self.file_list.blockSignals(False)
        if self.figure_win is not None:
            self.figure_win.refresh_sources()
        self.file_list.clearSelection()
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
            self.canvas.show_line(None)
            self.roi_panel.bind(None)
            self.roi_panel.draw_overlay(hidden=True)
            self.canvas.pix.setPixmap(QPixmap())
        self.statusBar().showMessage(f'이미지 {len(rows)}개를 목록에서 제거했습니다.')

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths, pair = [], False
        for url in event.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.is_dir():
                paths += folder_files(p)
                pair = True
            else:
                paths.append(p)
        self.add_files(paths, pair=pair)

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
        if item is self.current and t == self._t_want and self.t_slider.isSliderDown():
            found = self.tcache.get_entry(item, t)
            if found is None:
                return
            self._t_want = None
            item.set_t(t)
            item.show_planes(*found)
            self.update_preview(light=True)

    def _t_changed(self, t):
        it = self.current
        if it is None:
            return
        self._t_want = None
        self.tcache.follow(it)  # read here, not in the background
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
        return getattr(self, 'right_tabs', None) is not None \
            and self.right_tabs.currentIndex() == self.stack_tab

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
        self.update_preview(refit=True)

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
        rgb = it.decorate(rgb, self.markers.scale_style(), self.markers.time_style())
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
            if self.right_tabs.currentIndex() != self.profile_tab:
                self.right_tabs.setCurrentIndex(self.profile_tab)  # also leaves the stack tab
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
            rgb_format=self.exp_format.currentData(),
            fps=self.exp_fps.value(),
        )

    def _export(self, items):
        if not items:
            return
        out = QFileDialog.getExistingDirectory(self, '저장할 폴더 선택')
        if not out:
            return
        kwargs = self._export_kwargs()
        per_image = self.exp_per_image.isChecked()
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
        msg = f'파일 {len(files)}개를 저장했습니다.\n{out}'
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
        n_done, n_files, rows, errors, coloc = 0, 0, [], [], []
        for i, it in enumerate(items):
            if prog.wasCanceled():
                break
            prog.setLabelText(f'저장 중: {it.label}')
            prog.setValue(i)
            QApplication.processEvents()
            folder = Path(out) / item_folder(it)
            try:
                n_files += len(export_item(it, folder, **kwargs))
                if it.cells is not None and len(it.cells):
                    item_rows = self.roi_panel.save_item(it, folder)
                    write_csv(folder / f'{item_stem(it)}_cell_rois.csv', item_rows)
                    rows += item_rows
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
