# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""ALIGN: move and rotate objects onto other objects by point pairs.

AutoCAD (ALIGN, p. 107): one pair moves, two pairs move and rotate and
then ask ``Scale objects based on alignment points? [Yes/No] <N>:``,
three pairs add a 3D tilt that a 2D drawing has no use for -- the third
pair is accepted and ignored, as the reference's 2D case does.
"""
from __future__ import annotations

from core import modify
from tools.base import Point, Tool


class AlignTool(Tool):
    wants_selection = True

    def start(self) -> None:
        self.name = "ALIGN"
        self._entities: list = []
        self._sources: list[Point] = []
        self._destinations: list[Point] = []
        self._await_scale = False

    def on_selection(self, entities: list) -> None:
        if not entities:
            self.ctx.finish()
            return
        self._entities = entities
        self.prompt("Specify first source point:")

    def _ask_next(self) -> None:
        n = len(self._sources)
        if n == len(self._destinations):
            if n == 0:
                self.prompt("Specify first source point:")
            elif n == 1:
                self.prompt("Specify second source point or <continue>:")
            elif n == 2:
                self.prompt("Specify third source point or <continue>:")
            else:
                self._finish_pairs()
        elif n == 1:
            self.prompt("Specify first destination point:")
        elif n == 2:
            self.prompt("Specify second destination point:")
        else:
            self.prompt("Specify third destination point:")

    def on_point(self, point: Point) -> None:
        if self._await_scale or not self._entities:
            return
        if len(self._sources) == len(self._destinations):
            self._sources.append(point)
        else:
            self._destinations.append(point)
        self.last_point = point
        self._ask_next()

    def on_enter(self) -> None:
        if self._await_scale:
            self._apply(scale=False)          # <N>
            return
        if self._sources and len(self._sources) == len(self._destinations):
            self._finish_pairs()              # <continue>
            return
        if not self._entities:
            self.ctx.finish()

    def _finish_pairs(self) -> None:
        if len(self._sources) >= 2:
            self._await_scale = True
            self.prompt("Scale objects based on alignment points? [Yes/No] <N>:")
            return
        self._apply(scale=False)

    def on_option(self, text: str) -> bool:
        if not self._await_scale:
            return False
        token = self.option(text) or text.strip().upper()
        if token in ("Y", "YES"):
            self._apply(scale=True)
            return True
        if token in ("N", "NO", ""):
            self._apply(scale=False)
            return True
        return False

    def _apply(self, scale: bool) -> None:
        self.ctx.execute(modify.align_entities(
            self._entities, self._sources, self._destinations, scale))
        self.ctx.finish()

    def preview_segments(self, cursor: Point):
        # a rubber band from the point whose partner is being asked for
        if len(self._sources) > len(self._destinations):
            return [(self._sources[-1], cursor)]
        return []


ALIGN_TOOL_CLASSES = {"ALIGN": AlignTool}
