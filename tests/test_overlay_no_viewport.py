# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A VIEWPORT never rides the overlay: drawn there it re-drew the whole
model through it on the GUI thread -- undoing a MOVE on Planos
Constructivos' sheet froze the window 5.3 s (release bench, 0.6.5). Only
the background regen shows a viewport, and undo/redo ask for it."""
from __future__ import annotations

import time

import pytest
from ezdxf.math import Matrix44


def _wait(qapp, win, timeout_s=20.0):
    t0 = time.monotonic()
    while (win._regen_worker is not None or win.tools._warmers) \
            and time.monotonic() - t0 < timeout_s:
        qapp.processEvents()


def test_undoing_a_move_of_a_viewport_leaves_it_to_the_regen(qapp):
    from core import actions
    from render import backend
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    try:
        msp = win.document.doc.modelspace()
        for i in range(50):
            msp.add_line((i * 10, 0), (i * 10, 100))
        psp = win.document.doc.layouts.get("Layout1")
        psp.add_text("TITLE", dxfattribs={"height": 5, "insert": (600, 40)})
        vp = psp.add_viewport(center=(150, 100), size=(200, 120),
                              view_center_point=(250, 50), view_height=150)
        win._refresh_layout_tabs()
        win.switch_layout("Layout1")
        _wait(qapp, win)
        sheet = [e for e in win.document.current_space()]
        assert any(e.dxftype() == "VIEWPORT" for e in sheet)
        win.tools._execute(actions.TransformCommand(
            "MOVE", sheet, Matrix44.translate(5, 5, 0)))
        _wait(qapp, win)

        drawn = []
        real = backend.build_scene_for_entities
        import views.tool_controller as tcm
        def spy(document, entities, *a, **k):
            drawn.extend(entities)
            return real(document, entities, *a, **k)
        tcm.build_scene_for_entities = spy
        regens = []
        real_regen = win.regen_in_memory
        win.regen_in_memory = lambda *a, **k: (regens.append(1), real_regen(*a, **k))[1]
        try:
            t0 = time.monotonic()
            win._cmd_undo()
            took = time.monotonic() - t0
        finally:
            tcm.build_scene_for_entities = real
        assert not [e for e in drawn if e.dxftype() == "VIEWPORT"], \
            "a viewport was drawn through the overlay"
        assert any(e.dxftype() == "TEXT" for e in drawn), "the rest still rides the overlay"
        assert regens, "nothing asked the regen to show the viewport back"
        assert took < 2.0
        _wait(qapp, win)
        assert vp.dxf.center.x == pytest.approx(150.0)
    finally:
        win.document.dirty = False
        win.close()
