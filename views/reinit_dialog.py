# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The Re-initialization dialog (REINIT, Command Reference p. 1617):
"Reinitializes the digitizer, digitizer input/output port, and program
parameters file". IngeCAD has no digitizer, so only the PGP file can be
ticked; the digitizer boxes are there, greyed, as in the layout users
know."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QVBoxLayout,
)

from core.i18n import tr


class ReinitDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Re-initialization"))
        root = QVBoxLayout(self)

        port = QGroupBox(tr("I/O Port Initialization"), self)
        port_box = QVBoxLayout(port)
        digitizer_port = QCheckBox(tr("Digitizer"), port)
        digitizer_port.setEnabled(False)
        digitizer_port.setToolTip(tr("IngeCAD does not use a digitizer."))
        port_box.addWidget(digitizer_port)
        root.addWidget(port)

        device = QGroupBox(tr("Device and File Initialization"), self)
        device_box = QVBoxLayout(device)
        digitizer = QCheckBox(tr("Digitizer"), device)
        digitizer.setEnabled(False)
        digitizer.setToolTip(tr("IngeCAD does not use a digitizer."))
        device_box.addWidget(digitizer)
        self.pgp = QCheckBox(tr("PGP File"), device)
        device_box.addWidget(self.pgp)
        root.addWidget(device)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
