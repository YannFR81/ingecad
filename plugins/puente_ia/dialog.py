# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The AIBRIDGE window: on/off, where the bridge listens, and the exact
lines to paste into the MCP client -- whoever reaches this window rarely
knows them by heart."""
from __future__ import annotations

from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QHBoxLayout,
                               QLabel, QPlainTextEdit, QPushButton, QSizePolicy,
                               QVBoxLayout)

from core.i18n import tr

from . import actions
from .bridge import bridge_of


class BridgeDialog(QDialog):
    """Modeless: the user keeps drawing (and watching the agent draw)
    with it open."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self._window = window
        self.setObjectName("ai_bridge_dialog")
        self.setWindowTitle(tr("AI bridge (MCP)"))
        self.setModal(False)
        self.resize(640, 520)
        lay = QVBoxLayout(self)
        self._status = QLabel()
        self._status.setWordWrap(True)
        self._status.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        lay.addWidget(self._status)
        row = QHBoxLayout()
        self._toggle = QPushButton()
        self._toggle.clicked.connect(self.toggle)
        row.addWidget(self._toggle)
        self._copy = QPushButton(tr("Copy"))
        self._copy.setToolTip(tr("Copy the connection instructions"))
        self._copy.clicked.connect(self._on_copy)
        row.addWidget(self._copy)
        row.addStretch(1)
        self._close = QPushButton(tr("Close"))
        self._close.clicked.connect(self.close)
        row.addWidget(self._close)
        lay.addLayout(row)
        from .commands import autostart_enabled

        self._autostart = QCheckBox(tr("Start with IngeCAD"))
        self._autostart.setToolTip(tr(
            "Start the bridge on its own when IngeCAD opens a drawing, so the "
            "agent finds it without typing AIBRIDGE first."))
        self._autostart.setChecked(autostart_enabled())
        self._autostart.toggled.connect(self._on_autostart)
        lay.addWidget(self._autostart)
        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        lay.addWidget(self._text, 1)
        # takes the room the instructions leave when the bridge is off, so
        # the status and the buttons stay at the top instead of floating
        lay.addStretch(0)
        self.refresh()

    @property
    def running(self) -> bool:
        bridge = bridge_of(self._window, create=False)
        return bridge is not None and bridge.running

    def toggle(self) -> None:
        from . import commands

        if self.running:
            commands.stop(self._window)
        else:
            commands.start(self._window)
        self.refresh()

    def refresh(self, error: str | None = None) -> None:
        on = self.running
        self._toggle.setText(tr("Stop bridge") if on else tr("Start bridge"))
        self._copy.setVisible(on)
        self._text.setVisible(on)
        if on:
            port = bridge_of(self._window).port
            self._status.setText(tr(
                "Listening on 127.0.0.1:{port}. Connect your MCP client with "
                "the lines below; every call the agent makes is one undo step.",
                port=port))
            self._text.setPlainText(actions.connect_instructions(port))
        elif error:
            self._status.setText(tr("The AI bridge could not start: {error}",
                                    error=error))
        else:
            self._status.setText(tr(
                "Off. Start it to let an AI agent (Claude, Cursor...) draw in "
                "this drawing over MCP, from this computer only."))

    def _on_autostart(self, flag: bool) -> None:
        from .commands import set_autostart

        set_autostart(flag)

    def _on_copy(self) -> None:
        QApplication.clipboard().setText(self._text.toPlainText())
        self._window.echo(tr("Connection instructions copied."))
