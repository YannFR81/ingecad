# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A small "Loading <name>…" window for the long waits (issue #50).

Opening a real plan takes ten seconds and showed nothing but a text on the
coordinates line -- it looked like nothing was happening (Marco). This is
the IngeTrazo answer, non-modal: the file name, the phase as it happens
(converting DWG, reading, regenerating), the elapsed time, and a Cancel
when the caller can abandon the work. It never takes the focus and never
blocks input: the work already runs on a worker, and the canvas keeps
painting behind it. It appears only after ``min_ms``, so a small file
never flashes it.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QProgressBar, QPushButton,
                               QVBoxLayout, QWidget)

from core.i18n import tr


class LoadingWindow(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint
                         | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setObjectName("loadingWindow")
        self.setStyleSheet(
            "#loadingWindow { background: #2b2b2b; border: 1px solid #5a5a5a; }"
            "QLabel { color: #e8e8e8; } QLabel#title { font-weight: bold; }"
            "QLabel#elapsed { color: #a8a8a8; }")
        self._title = QLabel(self)
        self._title.setObjectName("title")
        self._phase = QLabel(self)
        self._elapsed = QLabel(self)
        self._elapsed.setObjectName("elapsed")
        self._bar = QProgressBar(self)
        self._bar.setRange(0, 0)              # busy: no known total
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(6)
        self._cancel = QPushButton(tr("Cancel"), self)
        self._cancel.setFocusPolicy(Qt.NoFocus)
        self._cancel.clicked.connect(self._on_cancel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.addWidget(self._title)
        layout.addWidget(self._phase)
        layout.addWidget(self._bar)
        row = QHBoxLayout()
        row.addWidget(self._elapsed)
        row.addStretch(1)
        row.addWidget(self._cancel)
        layout.addLayout(row)
        self.setFixedWidth(360)
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._tick)
        self._show_timer = QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.timeout.connect(self._show_now)
        self._t0 = 0.0
        self._on_cancel_cb: Optional[Callable[[], None]] = None
        self.active = False

    # -- API ---------------------------------------------------------------------
    def begin(self, title: str, on_cancel: Optional[Callable[[], None]] = None,
              min_ms: int = 400) -> None:
        """Start a wait: shown after ``min_ms`` if still running."""
        self._title.setText(title)
        self._phase.setText("")
        self._elapsed.setText("")
        self._on_cancel_cb = on_cancel
        self._cancel.setVisible(on_cancel is not None)
        self._t0 = time.monotonic()
        self.active = True
        self._timer.start()
        if min_ms <= 0:
            self._show_now()
        else:
            self._show_timer.start(min_ms)

    def phase(self, text: str) -> None:
        self._phase.setText(text)

    def finish(self) -> None:
        self.active = False
        self._show_timer.stop()
        self._timer.stop()
        self._on_cancel_cb = None
        self.hide()

    def elapsed_s(self) -> float:
        return time.monotonic() - self._t0 if self.active else 0.0

    # -- internals -----------------------------------------------------------------
    def _show_now(self) -> None:
        if not self.active:
            return
        parent = self.parentWidget()
        if parent is not None:
            centre = parent.geometry().center()
            self.adjustSize()
            self.move(centre.x() - self.width() // 2,
                      centre.y() - self.height() // 2)
        self._tick()
        self.show()

    def _tick(self) -> None:
        seconds = int(self.elapsed_s())
        self._elapsed.setText(tr("{s} s", s=seconds))

    def _on_cancel(self) -> None:
        callback = self._on_cancel_cb
        self.finish()
        if callback is not None:
            callback()
