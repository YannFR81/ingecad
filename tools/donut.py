# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""DONUT: a filled circle or a wide ring (DONUT, p. 656).

``Specify inside diameter of donut <current>:``, ``Specify outside
diameter of donut <current>:``, then ``Specify center of donut or
<exit>:`` for every donut until Enter. The diameters are the DONUTID /
DONUTOD system variables: the last ones used are the next defaults.
"""
from __future__ import annotations

from core import actions
from core.i18n import tr
from tools.base import Point, Tool


class DonutTool(Tool):
    _inside = 0.5          # DONUTID default
    _outside = 1.0         # DONUTOD default

    def start(self) -> None:
        self.name = "DONUT"
        self._await = "inside"
        self.prompt("Specify inside diameter of donut <{d:.4f}>:", d=type(self)._inside)

    def on_option(self, text: str) -> bool:
        if self._await is None:
            return False
        stripped = text.strip()
        try:
            value = float(stripped) if stripped else None
        except ValueError:
            self.ctx.echo(tr("Requires numeric distance or two points."))
            return True
        if value is not None and value < 0:
            self.ctx.echo(tr("Value must be positive."))
            return True
        self._take(value)
        return True

    def _take(self, value: float | None) -> None:
        cls = type(self)
        if self._await == "inside":
            if value is not None:
                cls._inside = value
            self._await = "outside"
            self.prompt("Specify outside diameter of donut <{d:.4f}>:", d=cls._outside)
            return
        if value is not None:
            cls._outside = value
        if cls._outside <= 0 and cls._inside <= 0:
            self.ctx.echo(tr("Value must be positive."))
            self.prompt("Specify outside diameter of donut <{d:.4f}>:", d=cls._outside)
            return
        self._await = None
        self.prompt("Specify center of donut or <exit>:")

    def on_enter(self) -> None:
        if self._await is not None:
            self._take(None)          # accept the default
            return
        self.ctx.finish()

    def on_point(self, point: Point) -> None:
        if self._await is not None:
            # AutoCAD takes a diameter as two points too; the first click
            # measured from the last point is the distance-entry path the
            # controller already offers, so a bare point here is ignored
            return
        cls = type(self)
        self.ctx.execute(actions.add_donut(point, cls._inside, cls._outside))
        self.last_point = point
        self.prompt("Specify center of donut or <exit>:")


DONUT_TOOL_CLASSES = {"DONUT": DonutTool}
