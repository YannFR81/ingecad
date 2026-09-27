# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""AutoCAD's Move or Copy dialog, from a layout tab's shortcut menu:
"Before layout:" with "(move to end)", and "Create a copy"."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QVBoxLayout,
)

from core.i18n import tr

#: The last row of the list: no layout to go before.
TO_END = None


class MoveOrCopyDialog(QDialog):
    def __init__(self, parent, layout_names: list[str], name: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Move or Copy"))
        root = QVBoxLayout(self)
        root.addWidget(QLabel(tr("Before layout:"), self))
        self.list = QListWidget(self)
        self._targets = [n for n in layout_names if n != "Model"] + [TO_END]
        for target in self._targets:
            self.list.addItem(target if target is not None
                              else tr("(move to end)"))
        self.list.setCurrentRow(self._targets.index(name)
                                if name in self._targets else 0)
        root.addWidget(self.list, 1)
        self.copy = QCheckBox(tr("Create a copy"), self)
        root.addWidget(self.copy)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def before(self):
        """The layout picked to go before, or None for the end."""
        row = self.list.currentRow()
        return self._targets[row] if 0 <= row < len(self._targets) else None
