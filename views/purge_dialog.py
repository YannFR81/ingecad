# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""PURGE: the Purge dialog (acad_acr "Purge Dialog Box", p. 1569).

A tree of the named objects that can be purged, by category, each item
checkable; "Purge nested items"; "Purge zero-length geometry and empty text
objects"; Purge (the checked items) and Purge All. The decision of what to
purge is pure (:meth:`checked_items`, :meth:`all_items`), so the window
applies it and tests read it without an ``exec``.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout,
                               QLabel, QPushButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout)

from core import cleanup
from core.i18n import tr

#: Category key -> the tree's group label (the dialog's names).
LABELS = {
    "blocks": "Blocks", "dimstyles": "Dimension styles", "groups": "Groups",
    "layers": "Layers", "ltypes": "Linetypes",
    "mleaderstyles": "Multileader styles", "textstyles": "Text styles",
    "regapps": "Regapps",
}


class PurgeDialog(QDialog):
    def __init__(self, parent, document) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Purge"))
        self.document = document
        self.result_items: dict | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("Items not used in drawing:")))
        self.tree = QTreeWidget(self)
        self.tree.setHeaderHidden(True)
        layout.addWidget(self.tree, 1)
        self.nested = QCheckBox(tr("Purge nested items"), self)
        self.nested.setChecked(True)
        self.nested.toggled.connect(self.refresh)
        layout.addWidget(self.nested)
        self.unnamed = QCheckBox(
            tr("Purge zero-length geometry and empty text objects"), self)
        layout.addWidget(self.unnamed)
        self.summary = QLabel(self)
        layout.addWidget(self.summary)

        buttons = QHBoxLayout()
        self.purge_button = QPushButton(tr("Purge"), self)
        self.purge_button.clicked.connect(self._purge_checked)
        self.purge_all_button = QPushButton(tr("Purge All"), self)
        self.purge_all_button.clicked.connect(self._purge_all)
        buttons.addWidget(self.purge_button)
        buttons.addWidget(self.purge_all_button)
        buttons.addStretch(1)
        close = QDialogButtonBox(QDialogButtonBox.Close, self)
        close.rejected.connect(self.reject)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.resize(420, 480)
        self.refresh()

    # -- content -----------------------------------------------------------
    def refresh(self) -> None:
        self._found = cleanup.candidates(self.document.doc,
                                         nested=self.nested.isChecked())
        self.tree.clear()
        total = 0
        for key in cleanup.NAMED:
            names = self._found.get(key, [])
            if not names:
                continue
            group = QTreeWidgetItem([f"{tr(LABELS[key])} ({len(names)})"])
            group.setData(0, Qt.UserRole, key)
            group.setFlags(group.flags() | Qt.ItemIsAutoTristate
                           | Qt.ItemIsUserCheckable)
            group.setCheckState(0, Qt.Unchecked)
            for name in names:
                item = QTreeWidgetItem([name])
                item.setData(0, Qt.UserRole, key)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(0, Qt.Unchecked)
                group.addChild(item)
                total += 1
            self.tree.addTopLevelItem(group)
        unnamed = len(self._found.get("zero", [])) + len(self._found.get("empty", []))
        self.summary.setText(tr(
            "{named} unused named object(s); {unnamed} zero-length or empty "
            "text object(s).", named=total, unnamed=unnamed))
        self.purge_all_button.setEnabled(total > 0 or unnamed > 0)

    def _with_unnamed(self, items: dict) -> dict:
        if self.unnamed.isChecked():
            for key in cleanup.UNNAMED:
                if self._found.get(key):
                    items[key] = list(self._found[key])
        return items

    def checked_items(self) -> dict:
        """What the user ticked (plus the unnamed objects when asked)."""
        items: dict = {}
        for i in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(i)
            key = group.data(0, Qt.UserRole)
            for j in range(group.childCount()):
                child = group.child(j)
                if child.checkState(0) == Qt.Checked:
                    items.setdefault(key, []).append(child.text(0))
        return self._with_unnamed(items)

    def all_items(self) -> dict:
        items = {key: list(self._found.get(key, [])) for key in cleanup.NAMED
                 if self._found.get(key)}
        return self._with_unnamed(items)

    # -- buttons -----------------------------------------------------------
    def _purge_checked(self) -> None:
        self.result_items = self.checked_items()
        self.accept()

    def _purge_all(self) -> None:
        self.result_items = self.all_items()
        self.accept()
