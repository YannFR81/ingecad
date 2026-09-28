# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""PLOT's Window pick (#52), the way AutoCAD asks for it (Plot dialog,
p. 1465): "Specify first corner:", then "Specify opposite corner:" with a
rectangle that follows the cursor -- two clicks, or two typed points, with
object snaps like any other point prompt. Esc or Enter gives up.

The tool knows nothing of the dialog: it hands the rectangle to the
callback the window left in ``_plot_window_callback`` (or None when
cancelled), after it has finished -- the callback reopens a modal dialog,
which must not run inside the click that ended the tool.
"""
from __future__ import annotations

from typing import Optional

from tools.base import Point, Tool


class PlotWindowTool(Tool):
    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self.name = "PLOTWINDOW"
        self._first: Optional[Point] = None

    def start(self) -> None:
        self.prompt("Specify first corner:")

    def on_point(self, point: Point) -> None:
        if self._first is None:
            self._first = point
            self.last_point = point
            self.prompt("Specify opposite corner:")
            return
        (x0, y0), (x1, y1) = self._first, point
        if abs(x1 - x0) < 1e-9 or abs(y1 - y0) < 1e-9:
            self.prompt("Specify opposite corner:")   # a line is not a window
            return
        self._done((min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)))

    def preview_segments(self, cursor: Point) -> list[tuple[Point, Point]]:
        if self._first is None:
            return []
        (x0, y0), (x1, y1) = self._first, cursor
        a, b, c, d = (x0, y0), (x1, y0), (x1, y1), (x0, y1)
        return [(a, b), (b, c), (c, d), (d, a)]

    def on_enter(self) -> None:
        self._done(None)

    def on_cancel(self) -> None:
        self._done(None)

    def _done(self, rect) -> None:
        from PySide6.QtCore import QTimer

        window = getattr(self.ctx.services, "window", None)
        callback = getattr(window, "_plot_window_callback", None)
        if window is not None:
            window._plot_window_callback = None
        self.ctx.finish()
        if callback is not None:
            QTimer.singleShot(0, lambda: callback(rect))


PLOT_WINDOW_TOOL_CLASSES = {"PLOTWINDOW": PlotWindowTool}
