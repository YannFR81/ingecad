# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Drawing cleanup (#37) through the window: typed -PURGE, the OVERKILL and
WBLOCK tools with real clicks, the Purge dialog's decision."""
from __future__ import annotations

import ezdxf
import pytest

from core import cleanup


def _window(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    doc = win.document.doc
    msp = doc.modelspace()
    doc.layers.add("UNUSED")
    block = doc.blocks.new("UNUSEDBLK")
    block.add_line((0, 0), (1, 1))
    msp.add_line((0, 0), (10, 0))
    msp.add_line((0, 0), (10, 0))            # duplicate
    msp.add_line((10, 0), (20, 0))           # end to end
    msp.add_circle((50, 50), 5)
    # the entities went in behind the Commands' back: let the warmer that
    # new_document started land (its index is empty) and rebuild after it
    while win.tools._warmers:
        qapp.processEvents()
    win.tools._invalidate_geometry()
    return win, win.tools


def test_typed_dash_purge_removes_the_block_and_undo_brings_it_back(qapp):
    win, t = _window(qapp)
    try:
        win.dispatcher.submit("-PURGE")
        assert "[Blocks/DEtailviewstyles" in win.dispatcher.pending_prompt
        win.dispatcher.submit("B")
        win.dispatcher.submit("*")
        win.dispatcher.submit("N")
        assert win.dispatcher.pending_prompt is None
        assert "UNUSEDBLK" not in win.document.doc.blocks
        assert "UNUSED" in win.document.doc.layers, "only blocks were asked for"
        win._cmd_undo()
        assert "UNUSEDBLK" in win.document.doc.blocks
        # PU is the alias, and the layers panel survives the refresh
        win.dispatcher.submit("-PU")
        win.dispatcher.submit("LA")
        win.dispatcher.submit("*")
        win.dispatcher.submit("N")
        assert "UNUSED" not in win.document.doc.layers
    finally:
        win.document.dirty = False
        win.close()


def test_purge_dialog_decides_and_the_window_applies_it(qapp):
    from views.purge_dialog import PurgeDialog

    win, t = _window(qapp)
    try:
        dialog = PurgeDialog(win, win.document)
        items = dialog.all_items()
        assert items["blocks"] == ["UNUSEDBLK"] and items["layers"] == ["UNUSED"]
        assert "zero" not in items, "unnamed objects only when asked"
        assert dialog.checked_items() == {}
        dialog.unnamed.setChecked(True)
        win.document.doc.modelspace().add_line((3, 3), (3, 3))
        dialog.refresh()
        assert len(dialog.all_items()["zero"]) == 1
        count = win.apply_purge(dialog.all_items())
        assert count >= 3, "block, layer, zero-length line (+ the template linetypes)"
        assert "UNUSEDBLK" not in win.document.doc.blocks
        assert not cleanup.zero_length_entities(win.document.doc)
        win._cmd_undo()
        assert "UNUSED" in win.document.doc.layers
        dialog.deleteLater()
    finally:
        win.document.dirty = False
        win.close()


def test_overkill_tool_runs_over_a_selection_and_reports_like_autocad(qapp):
    win, t = _window(qapp)
    try:
        said = []
        win.command_line.echo = lambda text, *a, **k: said.append(text)
        msp = win.document.doc.modelspace()
        t.selection = {e.dxf.handle for e in msp}          # noun-verb
        t.start_tool("OVERKILL")
        assert t.active()
        assert "[Ignore/Tolerance/Optimize plines" in t.current_prompt
        t.on_text("T")
        assert "tolerance" in t.current_prompt.lower()
        t.on_text("0.01")
        t.on_text("E")                                       # end to end: keep Yes
        assert "[Yes/No]" in t.current_prompt
        t.on_text("Y")
        t.on_text("")                                        # Enter = Done
        assert not t.active()
        assert said[-1] == "1 duplicate(s) deleted, 1 overlapping object(s) or segment(s) deleted"
        lines = sorted((e.dxf.start.x, e.dxf.end.x) for e in msp.query("LINE"))
        assert lines == [(0.0, 20.0)]
        assert len(msp.query("CIRCLE")) == 1
        win._cmd_undo()
        assert len(msp.query("LINE")) == 3
    finally:
        win.document.dirty = False
        win.close()


def test_wblock_tool_writes_the_selection_in_autocad_order(qapp, tmp_path, monkeypatch):
    from views import file_dialogs

    out = tmp_path / "pieza.dxf"
    monkeypatch.setattr(file_dialogs, "get_save_file",
                        lambda *a, **k: (str(out), "DXF drawing (*.dxf)"))
    win, t = _window(qapp)
    try:
        said = []
        win.command_line.echo = lambda text, *a, **k: said.append(text)
        t.start_tool("WBLOCK")
        assert t.active()
        assert "Enter name of existing block or" in t.current_prompt
        t.on_text("")                                # define new drawing
        assert "base point" in t.current_prompt
        t.osnap_on = False
        t.on_click(10.0, 0.0)                        # base point
        assert t.in_selection_mode(), "Select objects: came after the base point"
        t._pick_tolerance = 0.5
        t.on_click(55.0, 50.0)                       # the circle
        assert t.selection
        t.on_text("")                                # Enter ends the selection
        assert out.exists()
        written = ezdxf.readfile(out)
        circles = written.modelspace().query("CIRCLE")
        assert len(circles) == 1
        assert (circles[0].dxf.center.x, circles[0].dxf.center.y) == pytest.approx((40.0, 50.0))
        assert "[Retain/Convert to block/Delete]" in t.current_prompt
        t.on_text("D")
        assert not t.active()
        assert len(win.document.doc.modelspace().query("CIRCLE")) == 0
        win._cmd_undo()
        assert len(win.document.doc.modelspace().query("CIRCLE")) == 1
        assert any("written to" in s for s in said)

        # an existing block by name, straight from the first prompt
        out2 = tmp_path / "blk.dxf"
        monkeypatch.setattr(file_dialogs, "get_save_file",
                            lambda *a, **k: (str(out2), ""))
        win.dispatcher.submit("W")
        assert t.active()
        t.on_text("UNUSEDBLK")
        assert not t.active() and out2.exists()
        assert [e.dxftype() for e in ezdxf.readfile(out2).modelspace()] == ["LINE"]
    finally:
        win.document.dirty = False
        win.close()


def test_wblock_cancelled_file_dialog_ends_the_command(qapp, monkeypatch):
    from views import file_dialogs

    monkeypatch.setattr(file_dialogs, "get_save_file", lambda *a, **k: ("", ""))
    win, t = _window(qapp)
    try:
        t.start_tool("WBLOCK")
        assert not t.active()
    finally:
        win.document.dirty = False
        win.close()
