# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""SCALETEXT: resize text objects without moving them (SCALETEXT, p. 1698).

``Select objects:``, then ``Enter a base point option for scaling
[Existing/Left/Center/Middle/Right/TL/TC/TR/ML/MC/MR/BL/BC/BR] <Existing>:``,
then ``Specify new model height or [Paper height/Match object/Scale factor]
<current>:``. Each text scales about its OWN base point, so nothing moves.
Paper height is for annotative objects, which IngeCAD does not create yet
(#43): the option says so.
"""
from __future__ import annotations

from core import modify
from core.i18n import tr
from tools.base import Point, Tool

_BASE_PROMPT = ("Enter a base point option for scaling "
                "[Existing/Left/Center/Middle/Right/TL/TC/TR/ML/MC/MR/BL/BC/BR] "
                "<Existing>:")
_BASES = ("E", "EXISTING", "L", "LEFT", "C", "CENTER", "M", "MIDDLE", "R", "RIGHT",
          "TL", "TC", "TR", "ML", "MC", "MR", "BL", "BC", "BR")


class ScaleTextTool(Tool):
    wants_selection = True
    entity_picker = True

    _last_height: float | None = None
    _last_factor = 2.0

    def start(self) -> None:
        self.name = "SCALETEXT"
        self._entities: list = []
        self._base = "E"
        self._await = "base"          # base | height | match | factor | ref | new
        self._reference: float | None = None

    def selection_prompt(self) -> str:
        return tr("Select objects (Enter when done):")

    def on_selection(self, entities: list) -> None:
        self._entities = [e for e in entities if modify.text_height_of(e)]
        if not self._entities:
            self.ctx.echo(tr("No text objects selected."))
            self.ctx.finish()
            return
        self.prompt(_BASE_PROMPT)

    def _default_height(self) -> float:
        if type(self)._last_height:
            return type(self)._last_height
        return modify.text_height_of(self._entities[0]) or 2.5

    def _ask_height(self) -> None:
        self._await = "height"
        self.prompt("Specify new model height or [Paper height/Match object/"
                    "Scale factor] <{h:.4f}>:", h=self._default_height())

    def on_option(self, text: str) -> bool:
        token = self.option(text) or text.strip().upper()
        stripped = text.strip()
        if self._await == "base":
            if token in _BASES or token == "":
                self._base = {"EXISTING": "E", "LEFT": "L", "CENTER": "C",
                              "MIDDLE": "M", "RIGHT": "R"}.get(token, token or "E")
                self._ask_height()
                return True
            return False
        if self._await == "height":
            if token in ("P", "PAPER"):
                self.ctx.echo(tr("Paper height applies to annotative objects only; "
                                 "IngeCAD does not create them yet."))
                self._ask_height()
                return True
            if token in ("M", "MATCH"):
                self._await = "match"
                self.prompt("Select a text object with the desired height:")
                return True
            if token in ("S", "SCALE"):
                self._await = "factor"
                self.prompt("Specify scale factor or [Reference] <{f:.4f}>:",
                            f=type(self)._last_factor)
                return True
            return self._number(stripped, self._default_height(), self._by_height)
        if self._await == "factor":
            if token in ("R", "REFERENCE"):
                self._await = "ref"
                self.prompt("Specify reference length <1.0000>:")
                return True
            return self._number(stripped, type(self)._last_factor, self._by_factor)
        if self._await == "ref":
            return self._number(stripped, 1.0, self._take_reference)
        if self._await == "new":
            return self._number(stripped, None, self._take_new_length)
        return False

    def _number(self, stripped: str, default, then) -> bool:
        if stripped == "":
            if default is None:
                return True
            value = default
        else:
            try:
                value = float(stripped)
            except ValueError:
                self.ctx.echo(tr("Requires numeric value."))
                return True
        if value <= 0:
            self.ctx.echo(tr("Value must be positive."))
            return True
        then(value)
        return True

    def on_enter(self) -> None:
        if self._await == "base":
            self._ask_height()
        elif self._await == "height":
            self._by_height(self._default_height())
        elif self._await == "factor":
            self._by_factor(type(self)._last_factor)
        elif self._await == "ref":
            self._take_reference(1.0)
        elif self._await == "match":
            self.prompt("Select a text object with the desired height:")

    def on_point(self, point: Point) -> None:
        if self._await != "match":
            return
        services = self.ctx.services
        entity = services.pick_entity(point) if services else None
        height = modify.text_height_of(entity) if entity is not None else None
        if not height:
            self.ctx.echo(tr("Select a text object."))
            self.prompt("Select a text object with the desired height:")
            return
        self._by_height(height)

    def _by_height(self, height: float) -> None:
        type(self)._last_height = height
        self._run(modify.scale_texts(self._entities, self._base, height=height))

    def _by_factor(self, factor: float) -> None:
        type(self)._last_factor = factor
        self._run(modify.scale_texts(self._entities, self._base, factor=factor))

    def _take_reference(self, value: float) -> None:
        self._reference = value
        self._await = "new"
        self.prompt("Specify new length:")

    def _take_new_length(self, value: float) -> None:
        self._by_factor(value / self._reference)

    def _run(self, command) -> None:
        if command is not None:
            self.ctx.execute(command)
            self.ctx.echo(tr("{n} text object(s) changed.", n=len(self._entities)))
        self.ctx.finish()


SCALETEXT_TOOL_CLASSES = {"SCALETEXT": ScaleTextTool}
