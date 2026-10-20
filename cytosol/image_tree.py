"""The image list: images grouped under collapsible group folders, addressed
by row (= index in MainWindow.items) like the plain list it replaces."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QAbstractItemView, QTreeWidget, QTreeWidgetItem

ROW = Qt.ItemDataRole.UserRole       # image row, on image items
GROUP = Qt.ItemDataRole.UserRole + 1  # group name, on folder items


class ImageTree(QTreeWidget):
    currentRowChanged = Signal(int)

    def __init__(self):
        super().__init__()
        self.setHeaderHidden(True)
        self.setColumnCount(1)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setExpandsOnDoubleClick(True)
        self._leaves: list[QTreeWidgetItem] = []
        self._collapsed: set[str] = set()
        self.itemCollapsed.connect(lambda n: self._collapsed.add(n.data(0, GROUP)))
        self.itemExpanded.connect(lambda n: self._collapsed.discard(n.data(0, GROUP)))
        self.currentItemChanged.connect(self._current_changed)

    def _current_changed(self, item, _prev):
        if item is not None and item.data(0, ROW) is not None:
            self.currentRowChanged.emit(item.data(0, ROW))

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
        for row, it in enumerate(items):
            leaf = QTreeWidgetItem([it.label])
            leaf.setData(0, ROW, row)
            if it.group:
                folders[it.group].addChild(leaf)
            else:
                self.addTopLevelItem(leaf)
            self._leaves.append(leaf)
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
        it = self.currentItem()
        r = it.data(0, ROW) if it is not None else None
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
            r = it.data(0, ROW)
            if r is not None:
                rows.add(r)
            elif expand_groups:
                rows |= {it.child(i).data(0, ROW) for i in range(it.childCount())}
        return sorted(rows)

    def selected_group(self) -> str:
        """Name of the selected (or current) group folder, else ''."""
        for it in self.selectedItems() or [self.currentItem()]:
            if it is not None and it.data(0, ROW) is None:
                return it.data(0, GROUP)
        return ''
