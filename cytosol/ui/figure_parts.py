"""Figure window parts: Prompt-like label window, brightness row (SettingsRow variant range), the figure table (Table variant grid) and its header."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QMimeData, QPointF, QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QApplication, QHeaderView, QCheckBox, QColorDialog, QDialog, QDialogButtonBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSlider, QTableWidget, QVBoxLayout, QWidget
from .. import theme
from .color_well import ColorWell


CELL_MIME = 'application/x-cytosol-figure-cell'   # "row,col" of a dragged cell


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
        self.color_btn = ColorWell(None, pick=False)
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
        self.color_btn.setColor(c.name())

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


LEVEL_STEPS = 1000


class LevelRow(QWidget):
    """자동 / Min / Max with sliders for one channel of a figure cell or inset."""

    autoToggled = Signal(int, bool)
    valuesChanged = Signal(int, float, float)
    autoPicked = Signal(int)

    def __init__(self, item, ch):
        super().__init__()
        self.ch = ch
        self._busy = False
        self.lo, self.hi, note = item.value_range(ch)
        integer = bool(note) and note != 'RI' and float(self.lo).is_integer() \
            and float(self.hi).is_integer()
        span = self.hi - self.lo
        self.steps = int(span) if integer and 0 < span <= 1_000_000 else LEVEL_STEPS
        swatch = QPixmap(14, 14)
        swatch.fill(_qcolor(item.luts[ch].color))
        self.name = QLabel()
        self.name.setText(item.channels[ch])
        icon = QLabel()
        icon.setPixmap(swatch)
        self.auto = QCheckBox('자동')
        self.auto.toggled.connect(lambda on: self._busy or self.autoToggled.emit(ch, on))
        self.pick = QPushButton('Auto')
        self.pick.setToolTip('이 칸(확대 영역)에 보이는 부분의 밝기 분포로 Min/Max 정하기')
        self.pick.clicked.connect(lambda: self.autoPicked.emit(ch))
        self.note = QLabel()
        theme.hint(self.note)
        self.min_spin, self.max_spin = QDoubleSpinBox(), QDoubleSpinBox()
        self.min_slider = QSlider(Qt.Orientation.Horizontal)
        self.max_slider = QSlider(Qt.Orientation.Horizontal)
        for spin, slider in ((self.min_spin, self.min_slider), (self.max_spin, self.max_slider)):
            spin.setDecimals(0 if integer else 4)
            spin.setRange(self.lo, self.hi)
            spin.setSingleStep(1 if integer else span / 100)
            spin.setKeyboardTracking(False)
            spin.valueChanged.connect(self._from_spins)
            slider.setRange(0, self.steps)
            slider.valueChanged.connect(lambda v, sp=spin: self._slider(sp, v))
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(icon)
        top.addWidget(self.name)
        top.addWidget(self.auto)
        top.addWidget(self.note, 1)
        top.addWidget(self.pick)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        for r, (text, slider, spin) in enumerate((('Min', self.min_slider, self.min_spin),
                                                  ('Max', self.max_slider, self.max_spin))):
            grid.addWidget(QLabel(text), r, 0)
            grid.addWidget(slider, r, 1)
            grid.addWidget(spin, r, 2)
        grid.setColumnStretch(1, 1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.addLayout(top)
        lay.addLayout(grid)

    def _to_slider(self, v):
        return int(round((v - self.lo) / (self.hi - self.lo) * self.steps))

    def _slider(self, spin, value):
        if not self._busy:
            spin.setValue(self.lo + value / self.steps * (self.hi - self.lo))

    def _from_spins(self, *_):
        if self._busy:
            return
        lo, hi = self.min_spin.value(), self.max_spin.value()
        self._busy = True
        self.min_slider.setValue(self._to_slider(lo))
        self.max_slider.setValue(self._to_slider(hi))
        self._busy = False
        self.valuesChanged.emit(self.ch, lo, hi)

    def show_values(self, lo, hi, auto, editable, note=''):
        """The values in use (also while automatic); fields editable only for own levels."""
        self._busy = True
        self.auto.setChecked(auto)
        self.min_spin.setValue(lo)
        self.max_spin.setValue(hi)
        self.min_slider.setValue(self._to_slider(lo))
        self.max_slider.setValue(self._to_slider(hi))
        for w in (self.min_spin, self.max_spin, self.min_slider, self.max_slider):
            w.setEnabled(editable)
        self.note.setText(note)
        self._busy = False


class FigureHeader(QHeaderView):
    """Row / column titles of the figure table.  The last section is the ＋
    that adds a row / column (grey, darker under the mouse); a hovered title
    shows a red × right beside its text (delete, confirmed); dragging a title
    moves the row / column, a blue line shows where it goes."""

    X_GAP = 9    # px between the title text and the ×
    X_HIT = 8    # half size of the × click area

    def __init__(self, orient, win, kind):
        super().__init__(orient)
        self.win, self.kind = win, kind
        self.setSectionsClickable(True)
        self.setHighlightSections(False)
        self.setMouseTracking(True)
        self.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hover = -1
        self._press = None      # (section, pos) of a press on a title
        self._drop = None       # insertion index while dragging

    # ---- geometry ----
    def count_real(self):
        return self.count() - 1  # without the ＋ section

    def _rect(self, i) -> QRect:
        pos, size = self.sectionViewportPosition(i), self.sectionSize(i)
        if self.orientation() == Qt.Orientation.Horizontal:
            return QRect(pos, 0, size, self.height())
        return QRect(0, pos, self.width(), size)

    def x_center(self, i) -> QPointF:
        r = self._rect(i)
        item = (self.win.table.horizontalHeaderItem(i) if self.kind == 'col'
                else self.win.table.verticalHeaderItem(i))
        text = item.text() if item is not None else ''
        fm = self.fontMetrics()
        w = max((fm.horizontalAdvance(t) for t in text.split('\n')), default=0)
        x = min(r.center().x() + w / 2 + self.X_GAP, r.right() - self.X_HIT)
        return QPointF(x, r.center().y())

    def _on_x(self, pos) -> int:
        i = self.logicalIndexAt(pos)
        if 0 <= i < self.count_real() and self.count_real() > 1:
            c = self.x_center(i)
            if abs(pos.x() - c.x()) <= self.X_HIT and abs(pos.y() - c.y()) <= self.X_HIT:
                return i
        return -1

    def _insert_at(self, pos) -> int:
        horiz = self.orientation() == Qt.Orientation.Horizontal
        v = pos.x() if horiz else pos.y()
        n = self.count_real()
        for i in range(n):
            r = self._rect(i)
            start, size = (r.x(), r.width()) if horiz else (r.y(), r.height())
            if v < start + size / 2:
                return i
        return n

    def line_pos(self, k) -> int:
        """Viewport coordinate of the boundary before section k."""
        if k < self.count_real():
            return self.sectionViewportPosition(k)
        last = self.count_real() - 1
        return self.sectionViewportPosition(last) + self.sectionSize(last)

    # ---- painting ----
    def paintSection(self, painter, rect, i):
        super().paintSection(painter, rect, i)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if i == self.count_real():  # the ＋
            pen = QPen(theme.color('label' if i == self._hover else 'label-tertiary'), 1.8)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            c = QPointF(rect.center())
            painter.drawLine(c - QPointF(5, 0), c + QPointF(5, 0))
            painter.drawLine(c - QPointF(0, 5), c + QPointF(0, 5))
        elif i == self._hover and self._drop is None and self.count_real() > 1:
            c = self.x_center(i)
            pen = QPen(theme.color('red'), 1.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(c + QPointF(-3.5, -3.5), c + QPointF(3.5, 3.5))
            painter.drawLine(c + QPointF(-3.5, 3.5), c + QPointF(3.5, -3.5))
        painter.restore()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._drop is None:
            return
        p = QPainter(self.viewport())
        p.setPen(QPen(theme.color('accent'), 3))
        v = self.line_pos(self._drop)
        if self.orientation() == Qt.Orientation.Horizontal:
            p.drawLine(v, 0, v, self.height())
        else:
            p.drawLine(0, v, self.width(), v)
        p.end()

    # ---- mouse ----
    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        if self._press is not None and event.buttons() & Qt.MouseButton.LeftButton:
            if (self._drop is not None or (pos - self._press[1]).manhattanLength()
                    >= QApplication.startDragDistance()):
                self._drop = self._insert_at(pos)
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self.viewport().update()
                self.win.table.set_drop_line(self.kind, self._drop)
                return
        i = self.logicalIndexAt(pos)
        if i != self._hover:
            self._hover = i
            self.viewport().update()
        on = self._on_x(pos) >= 0 or i == self.count_real()
        self.setCursor(Qt.CursorShape.PointingHandCursor if on else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hover = -1
        self.viewport().update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        pos = event.position().toPoint()
        if event.button() == Qt.MouseButton.LeftButton:
            i = self.logicalIndexAt(pos)
            if i == self.count_real():
                self.win.add_at_end(self.kind)
                return
            k = self._on_x(pos)
            if k >= 0:
                self.win._confirm_remove(self.kind, k)
                return
            if 0 <= i < self.count_real():
                self._press = (i, pos)
                self.win.select_label(self.kind, i)
                return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        press, drop = self._press, self._drop
        self._press = self._drop = None
        self.unsetCursor()
        self.win.table.set_drop_line(self.kind, None)
        self.viewport().update()
        if press is not None:
            if drop is not None:
                self.win.move_label(self.kind, press[0], drop)
            return
        super().mouseReleaseEvent(event)


class FigureTable(QTableWidget):
    """The figure's cell table with drag and drop: a cell is dragged onto
    another cell (moved, Option/Alt = copied); image files and images from the
    main window's list are dropped onto a cell.  The window does the work
    (`FigureWindow.drop_on`); the table only finds the target cell."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._line = None  # (kind, index): blue insertion line of a header drag

    def set_drop_line(self, kind, index):
        self._line = None if index is None else (kind, index)
        self.viewport().update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._line is None:
            return
        kind, k = self._line
        p = QPainter(self.viewport())
        p.setPen(QPen(theme.color('accent'), 3))
        if kind == 'col':
            x = self.horizontalHeader().line_pos(k)
            p.drawLine(x, 0, x, self.viewport().height())
        else:
            y = self.verticalHeader().line_pos(k)
            p.drawLine(0, y, self.viewport().width(), y)
        p.end()

    def is_plus(self, r, c) -> bool:
        s = self.win.spec
        return r >= s.nrows or c >= s.ncols

    def mousePressEvent(self, event):
        idx = self.indexAt(event.position().toPoint())
        if idx.isValid() and self.is_plus(idx.row(), idx.column()):
            if event.button() == Qt.MouseButton.LeftButton:
                self.win.add_at_end('row' if idx.row() >= self.win.spec.nrows else 'col')
            return
        super().mousePressEvent(event)

    def mimeTypes(self):
        return [CELL_MIME, 'text/uri-list']

    def mimeData(self, items):
        data = QMimeData()
        if items:
            it = items[0]
            data.setData(CELL_MIME, QByteArray(f'{it.row()},{it.column()}'.encode()))
        return data

    def supportedDropActions(self):
        return Qt.DropAction.MoveAction | Qt.DropAction.CopyAction

    def _target(self, event):
        idx = self.indexAt(event.position().toPoint())
        if not idx.isValid() or self.is_plus(idx.row(), idx.column()):
            return None
        return idx.row(), idx.column()

    def dragEnterEvent(self, event):
        if self.win.can_drop(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self.win.can_drop(event.mimeData()) and self._target(event) is not None:
            super().dragMoveEvent(event)  # auto-scroll + indicator
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        target = self._target(event)
        if target is None or not self.win.can_drop(event.mimeData()):
            event.ignore()
            return
        copy = bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
        # handled here (the table's own drop would move QTableWidgetItems)
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        self.win.drop_on(event.mimeData(), *target, copy=copy)
