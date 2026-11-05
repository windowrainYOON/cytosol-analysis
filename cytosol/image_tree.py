"""The image list: images grouped under collapsible group folders, addressed
by row (= index in MainWindow.items) like the plain list it replaces.  Long
names wrap onto more lines (at word boundaries, else anywhere) so the whole
name stays visible at any panel width."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QMimeData, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFont, QPainter, QPalette, QTextLayout, QTextOption
from PySide6.QtWidgets import (
    QAbstractItemView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
)

ROW = Qt.ItemDataRole.UserRole       # image row, on image items
# drag format of image rows (comma-separated list positions); the Figure window
# takes it to place those images in its cells
ROWS_MIME = 'application/x-cytosol-image-rows'
GROUP = Qt.ItemDataRole.UserRole + 1  # group name, on folder items
CROP = Qt.ItemDataRole.UserRole + 2  # crop index, on crop items (under their image)


PAD = 3  # px above / below the text of a row
TRASH = 16  # remove glyph at the end of an image row (hover / selected)
TRASH_W = TRASH + 8  # room kept for it at the end of every row
BREAK_AFTER = '._-+'  # file-name separators that may end a line


def wrap_lines(text: str, font, width: float) -> list[str]:
    """`text` wrapped to `width` px: at spaces or name separators (. _ - +),
    or anywhere when one piece is wider than the line."""
    text = ''.join(c + '\u200b' if c in BREAK_AFTER else c for c in text)
    layout = QTextLayout(text, font)
    opt = QTextOption()
    opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(opt)
    layout.beginLayout()
    lines = []
    while True:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(max(width, 1.0))
        lines.append(text[line.textStart():line.textStart() + line.textLength()])
    layout.endLayout()
    return lines


class WrapDelegate(QStyledItemDelegate):
    """Draws an item's text over as many lines as the column width needs."""

    def _text_width(self, option, index) -> int:
        view = self.parent()
        depth = 0
        p = index.parent()
        while p.isValid():
            depth += 1
            p = p.parent()
        indent = view.indentation() * (depth + (1 if view.rootIsDecorated() else 0))
        return view.viewport().width() - indent - 8 - TRASH_W

    def sizeHint(self, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        n = len(wrap_lines(opt.text, opt.font, self._text_width(opt, index))) or 1
        return QSize(10, n * opt.fontMetrics.lineSpacing() + 2 * PAD)

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text, opt.text = opt.text, ''
        style = opt.widget.style() if opt.widget is not None else None
        view = self.parent()
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        active = selected and view.hasFocus()
        # tahoe sidebar selection: accent pill + white text while the list is
        # active, a neutral fill otherwise; hover a faint fill (radius 10)
        from . import theme  # noqa: PLC0415

        pill = None
        if selected:
            pill = theme.color('blue') if active else theme.color('fill')
        elif opt.state & QStyle.StateFlag.State_MouseOver:
            pill = theme.color('fill-quaternary')
        if pill is not None:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(pill)
            painter.drawRoundedRect(QRectF(opt.rect).adjusted(0, 1, 0, -1), 10, 10)
            painter.restore()
        opt.state &= ~(QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver
                       | QStyle.StateFlag.State_HasFocus)
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        r = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, opt.widget)
        painter.save()
        painter.setFont(opt.font)
        painter.setPen(theme.color('on-accent') if active else opt.palette.color(QPalette.ColorRole.Text))
        fm = opt.fontMetrics
        lines = wrap_lines(text, opt.font, self._text_width(opt, index))
        y = r.top() + max((r.height() - len(lines) * fm.lineSpacing()) / 2, 0)
        for line in lines:
            painter.drawText(QRectF(r.left() + 2, y, r.width(), fm.lineSpacing()),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, line)
            y += fm.lineSpacing()
        removable = index.data(ROW) is not None or index.data(CROP) is not None
        if removable and (selected or option.state & QStyle.StateFlag.State_MouseOver):
            from . import hig_widgets  # noqa: PLC0415

            token = 'on-accent' if active else 'label-secondary'
            painter.drawPixmap(view.trash_rect(opt.rect), hig_widgets.pixmap('trash', TRASH, token))
        painter.restore()


class ImageTree(QTreeWidget):
    """Rows: images (by row), group folders, and each image's crop regions
    under it (owner request 2026-11-04).  A remove glyph sits at the end of
    the hovered / selected image or crop row (`removeClicked`,
    `cropRemoveClicked`); with no image the viewport shows the drop target
    (empty state)."""

    currentRowChanged = Signal(int)
    removeClicked = Signal(int)
    cropPicked = Signal(int, int)  # image row, crop index
    cropRemoveClicked = Signal(int, int)
    EMPTY_TITLE = '이미지를 여기로 끌어다 놓으세요'
    EMPTY_HINT = 'TCF · CZI · OIR · TIF 파일이나 폴더 · 파일 → 불러오기'

    def __init__(self):
        super().__init__()
        self.setHeaderHidden(True)
        self.setColumnCount(1)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setExpandsOnDoubleClick(True)
        # names wrap to the panel width instead of scrolling sideways
        self.setItemDelegate(WrapDelegate(self))
        self.setUniformRowHeights(False)
        self.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.header().setStretchLastSection(True)
        self._leaves: list[QTreeWidgetItem] = []
        self._collapsed: set[str] = set()
        self._crops_collapsed: set[int] = set()  # id() of images whose crops are folded
        self._ids: list[int] = []
        self.itemCollapsed.connect(lambda n: self._folded(n, True))
        self.itemExpanded.connect(lambda n: self._folded(n, False))
        self.currentItemChanged.connect(self._current_changed)
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        # images can be dragged out (onto the Figure window); the list itself
        # takes no drops, so files dropped here still reach the main window
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)

    def mimeTypes(self):
        return [ROWS_MIME]

    def mimeData(self, items):
        rows = []
        for it in items:
            if it.data(0, ROW) is not None:
                rows.append(it.data(0, ROW))
            else:  # a folder: its images
                rows += [it.child(k).data(0, ROW) for k in range(it.childCount())]
        rows = list(dict.fromkeys(r for r in rows if r is not None))
        data = QMimeData()
        if rows:
            data.setData(ROWS_MIME, QByteArray(','.join(map(str, rows)).encode()))
        return data

    def supportedDragActions(self):
        return Qt.DropAction.CopyAction

    def _folded(self, node, folded):
        r = node.data(0, ROW)
        if r is not None:
            if 0 <= r < len(self._ids):
                (self._crops_collapsed.add if folded else self._crops_collapsed.discard)(self._ids[r])
            return
        (self._collapsed.add if folded else self._collapsed.discard)(node.data(0, GROUP))

    def trash_rect(self, row_rect: QRect) -> QRect:
        x = self.viewport().width() - TRASH - 6
        return QRect(x, row_rect.center().y() - TRASH // 2 + 1, TRASH, TRASH)

    def mousePressEvent(self, ev):
        it = self.itemAt(ev.position().toPoint())
        if it is not None and ev.button() == Qt.MouseButton.LeftButton \
                and (it.data(0, ROW) is not None or it.data(0, CROP) is not None):
            r = self.trash_rect(self.visualItemRect(it)).adjusted(-3, -3, 3, 3)
            if r.contains(ev.position().toPoint()):
                if it.data(0, CROP) is not None:
                    self.cropRemoveClicked.emit(it.parent().data(0, ROW), it.data(0, CROP))
                else:
                    self.removeClicked.emit(it.data(0, ROW))
                return
        super().mousePressEvent(ev)

    def drawBranches(self, painter, rect, index):
        # image rows have no disclosure triangle: draw nothing in their indent,
        # so the selection is one pill on the name (tahoe sidebar)
        if index.data(ROW) is None or self.model().hasChildren(index):
            super().drawBranches(painter, rect, index)

    def mouseMoveEvent(self, ev):
        super().mouseMoveEvent(ev)
        self.viewport().update()

    def paintEvent(self, ev):
        super().paintEvent(ev)
        if self._leaves:
            return
        # empty state: a translucent drop glyph, one sentence, the next action
        from . import hig_widgets, theme  # noqa: PLC0415

        vp = self.viewport()
        qp = QPainter(vp)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = 44
        cy = vp.height() * 0.40
        qp.drawPixmap(round((vp.width() - size) / 2), round(cy - size), hig_widgets.pixmap(
            'tray.and.arrow.down', size, 'label-tertiary'))
        f = QFont(self.font())
        f.setWeight(QFont.Weight.DemiBold)
        qp.setFont(f)
        qp.setPen(theme.color('label-secondary'))
        w = vp.width() - 24
        qp.drawText(QRectF(12, cy + 10, w, 40),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
                    | Qt.TextFlag.TextWordWrap, self.EMPTY_TITLE)
        f.setWeight(QFont.Weight.Normal)
        f.setPixelSize(max(10, round(self.font().pixelSize() * 12 / 13)) if
                       self.font().pixelSize() > 0 else 12)
        qp.setFont(f)
        qp.setPen(theme.color('label-tertiary'))
        qp.drawText(QRectF(12, cy + 50, w, 40),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
                    | Qt.TextFlag.TextWordWrap, self.EMPTY_HINT)
        qp.end()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if event.size().width() != event.oldSize().width():
            self.scheduleDelayedItemsLayout()  # row heights follow the new width

    def _current_changed(self, item, prev):
        if item is None:
            return
        if item.data(0, CROP) is not None:  # a crop: its image, then the crop
            row = item.parent().data(0, ROW)
            was = self._row_of(prev)
            if row != was:
                self.currentRowChanged.emit(row)
            self.cropPicked.emit(row, item.data(0, CROP))
        elif item.data(0, ROW) is not None:
            if item.data(0, ROW) != self._row_of(prev):
                self.currentRowChanged.emit(item.data(0, ROW))

    @staticmethod
    def _row_of(item):
        if item is None:
            return None
        if item.data(0, CROP) is not None:
            return item.parent().data(0, ROW)
        return item.data(0, ROW)

    @staticmethod
    def crop_text(k, region) -> str:
        x0, y0, x1, y1 = region
        return f'Crop {k + 1}   {x1 - x0}×{y1 - y0}'

    def set_crops(self, row, crops, select=None):
        """The crop rows under image `row`; `select` makes one the current row."""
        if not 0 <= row < len(self._leaves):
            return
        leaf = self._leaves[row]
        blocked = self.blockSignals(True)
        cur_crop = self.current_crop()
        leaf.takeChildren()
        for k, region in enumerate(crops):
            c = QTreeWidgetItem([self.crop_text(k, region)])
            c.setData(0, CROP, k)
            c.setToolTip(0, f'x {region[0]}–{region[2]}, y {region[1]}–{region[3]}')
            leaf.addChild(c)
        leaf.setExpanded(row < len(self._ids) and self._ids[row] not in self._crops_collapsed)
        if select is not None and 0 <= select < leaf.childCount():
            leaf.setExpanded(True)
            self.setCurrentItem(leaf.child(select))
        elif cur_crop is not None and cur_crop[0] == row:
            k = min(cur_crop[1], leaf.childCount() - 1)
            self.setCurrentItem(leaf.child(k) if k >= 0 else leaf)
        self.blockSignals(blocked)

    def current_crop(self):
        """(image row, crop index) of the current crop row, else None."""
        it = self.currentItem()
        if it is not None and it.data(0, CROP) is not None:
            return it.parent().data(0, ROW), it.data(0, CROP)
        return None

    def rebuild(self, items):
        """Group folders in order of first appearance, then ungrouped images;
        keeps the current row, selection and collapsed folders."""
        cur = self.currentRow()
        sel = set(self.selected_rows(expand_groups=False))
        blocked = self.blockSignals(True)
        self.clear()
        self._leaves = []
        folders = {}
        for it in items:
            if it.group and it.group not in folders:
                node = QTreeWidgetItem([it.group])
                node.setData(0, GROUP, it.group)
                f = node.font(0)
                f.setWeight(QFont.Weight.DemiBold)
                node.setFont(0, f)
                self.addTopLevelItem(node)
                folders[it.group] = node
        self._ids = [id(it) for it in items]
        for row, it in enumerate(items):
            leaf = QTreeWidgetItem([it.label])
            leaf.setData(0, ROW, row)
            if it.group:
                folders[it.group].addChild(leaf)
            else:
                self.addTopLevelItem(leaf)
            self._leaves.append(leaf)
            for k, region in enumerate(getattr(it, 'crops', None) or []):
                c = QTreeWidgetItem([self.crop_text(k, region)])
                c.setData(0, CROP, k)
                leaf.addChild(c)
            leaf.setExpanded(id(it) not in self._crops_collapsed)
        for name, node in folders.items():
            node.setText(0, f'{name}  ({node.childCount()})')
            node.setExpanded(name not in self._collapsed)
        if 0 <= cur < len(self._leaves):
            self.setCurrentItem(self._leaves[cur])
        for r in sel:
            if r < len(self._leaves):
                self._leaves[r].setSelected(True)
        self.blockSignals(blocked)

    # ---- QListWidget-style access by row ------------------------------------

    def count(self) -> int:
        return len(self._leaves)

    def item(self, row) -> QTreeWidgetItem:
        return self._leaves[row]

    def currentRow(self) -> int:
        r = self._row_of(self.currentItem())
        return -1 if r is None else r

    def setCurrentRow(self, row):
        if 0 <= row < len(self._leaves):
            leaf = self._leaves[row]
            if leaf.parent() is not None:
                leaf.parent().setExpanded(True)
            self.setCurrentItem(leaf)

    def selected_rows(self, expand_groups=True) -> list[int]:
        """Rows of the selected images; a selected group folder counts as all
        of its images."""
        rows = set()
        for it in self.selectedItems():
            if it.data(0, CROP) is not None:
                continue  # a crop row is not its image
            r = it.data(0, ROW)
            if r is not None:
                rows.add(r)
            elif expand_groups:
                rows |= {it.child(i).data(0, ROW) for i in range(it.childCount())}
        return sorted(rows)

    def selected_group(self) -> str:
        """Name of the selected (or current) group folder, else ''."""
        for it in self.selectedItems() or [self.currentItem()]:
            if it is not None and it.data(0, GROUP) is not None:
                return it.data(0, GROUP)
        return ''
