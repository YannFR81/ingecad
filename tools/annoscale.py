# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""OBJECTSCALE / -OBJECTSCALE (p. 1281-1285): add or delete the annotation
scales an annotative object supports.

The command-line form (-OBJECTSCALE) is what both names run: AutoCAD's
OBJECTSCALE opens a dialog over the same two operations, and the prompts
below are the ones it documents. Adding a scale gives the object a new
representation laid out like its default one; deleting one never touches
the default (the scale "referenced by objects" cannot be deleted).
"""
from __future__ import annotations

from core import annotative
from core.i18n import tr
from tools.base import Tool


class ObjectScaleTool(Tool):
    wants_selection = True

    def start(self) -> None:
        self.name = "OBJECTSCALE"
        self._entities: list = []
        self._add = True
        self._await = None

    def selection_prompt(self) -> str:
        return tr("Select annotative objects:")

    def _document(self):
        services = self.ctx.services
        window = getattr(services, "window", None) if services else None
        return getattr(window, "document", None)

    def on_selection(self, entities: list) -> None:
        chosen = [e for e in entities if annotative.is_annotative(e)]
        if not chosen:
            self.ctx.echo(tr("No annotative objects selected."))
            self.ctx.finish()
            return
        self._entities = chosen
        self._await = "option"
        self.prompt("Enter an option [Add/Delete/?] <Add>:")

    def _list_scales(self) -> None:
        names = sorted({r.scale.name for e in self._entities
                        for r in annotative.representations(e)})
        self.ctx.echo(tr("Supported scales: {names}", names=", ".join(names)))

    def _scale_prompt(self) -> None:
        self._await = "scale"
        if self._add:
            self.prompt("Enter named scale to add or [?]:")
        else:
            self.prompt("Enter named scale to delete or [?]:")

    def on_enter(self) -> None:
        if self._await == "option":
            self._add = True
            self._scale_prompt()
            return
        self.ctx.finish()

    def on_option(self, text: str) -> bool:
        stripped = text.strip()
        if self._await == "option":
            if stripped == "?":
                self._list_scales()
                self.prompt("Enter an option [Add/Delete/?] <Add>:")
                return True
            key = self.option(stripped) or stripped.upper()
            if key in ("A", "ADD"):
                self._add = True
            elif key in ("D", "DELETE"):
                self._add = False
            else:
                return False
            self._scale_prompt()
            return True
        if self._await == "scale":
            document = self._document()
            if document is None:
                return False
            if stripped == "?":
                names = [s.name for s in annotative.scale_list(document.doc)]
                self.ctx.echo(tr("Named scales: {names}", names=", ".join(names)))
                self._scale_prompt()
                return True
            scale = annotative.standard_scale(document.doc, stripped)
            if scale is None:
                self.ctx.echo(tr("Scale \"{name}\" is not in the drawing's "
                                 "scale list.", name=stripped))
                self._scale_prompt()
                return True
            command = annotative.ObjectScaleCommand(
                self._entities, scale.name, add=self._add)
            self.ctx.execute(command)
            done = len(command.entities) - command.skipped
            if self._add:
                self.ctx.echo(tr("{n} object(s) now support {scale}.",
                                 n=done, scale=scale.name))
            else:
                self.ctx.echo(tr("{scale} removed from {n} object(s).",
                                 n=done, scale=scale.name))
            self.ctx.finish()
            return True
        return False


ANNO_TOOL_CLASSES = {"OBJECTSCALE": ObjectScaleTool,
                     "-OBJECTSCALE": ObjectScaleTool}
