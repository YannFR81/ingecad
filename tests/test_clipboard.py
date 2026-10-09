# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Delete-selection and clipboard (copy/cut/paste) — headless via PasteTool."""
from __future__ import annotations

import ezdxf
import pytest

from core import actions
from core.commands import History
from core.document import Document
from tools.base import ToolContext
from tools.edit import PasteTool


class Harness:
    def __init__(self):
        self.document = Document.new()
        self.history = History(self.document)
        self.finished = False
        self._clip = None
        self.ctx = ToolContext(
            execute=self.history.execute,
            prompt=lambda *_a: None,
            echo=lambda *_a: None,
            finish=lambda: setattr(self, "finished", True),
            services=self,
        )

    @property
    def msp(self):
        return self.document.modelspace()

    def clipboard_data(self):
        return self._clip if self._clip else (None, None)


def test_paste_translates_by_base_to_target():
    h = Harness()
    a = h.msp.add_line((0, 0), (2, 0))
    b = h.msp.add_circle((1, 1), 1)
    # emulate a copy: store copies + base at the extents min (0,0)
    h._clip = ([a.copy(), b.copy()], (0, 0))
    tool = PasteTool(h.ctx)
    tool.start()
    tool.on_point((10, 5))         # insertion point
    lines = [e for e in h.msp.query("LINE")]
    circles = [e for e in h.msp.query("CIRCLE")]
    assert len(lines) == 2 and len(circles) == 2   # originals + pasted
    pasted_line = [ln for ln in lines if ln is not a][0]
    assert pasted_line.dxf.start.x == pytest.approx(10)
    assert pasted_line.dxf.start.y == pytest.approx(5)


def test_paste_undo_removes_copies():
    h = Harness()
    a = h.msp.add_line((0, 0), (2, 0))
    h._clip = ([a.copy()], (0, 0))
    tool = PasteTool(h.ctx)
    tool.start()
    tool.on_point((10, 0))
    assert len(h.msp.query("LINE")) == 2
    h.history.undo()
    assert len(h.msp.query("LINE")) == 1


def test_paste_reusable_twice():
    h = Harness()
    a = h.msp.add_line((0, 0), (1, 0))
    h._clip = ([a.copy()], (0, 0))
    for target in ((5, 0), (0, 5)):
        tool = PasteTool(h.ctx)
        tool.start()
        tool.on_point(target)
    assert len(h.msp.query("LINE")) == 3   # original + two pastes


def test_paste_empty_clipboard_finishes():
    h = Harness()
    tool = PasteTool(h.ctx)
    tool.start()
    assert h.finished
    assert len(h.msp.query("LINE")) == 0


def test_erase_command_removes_and_undo_restores():
    # Delete-selection routes through EraseCommand; verify it round-trips.
    h = Harness()
    a = h.msp.add_line((0, 0), (2, 0))
    h.history.execute(actions.EraseCommand([a]))
    assert len(h.msp.query("LINE")) == 0
    h.history.undo()
    assert len(h.msp.query("LINE")) == 1


def test_erase_unlinks_for_instant_overlay_filter():
    # The overlay filters by owner=None; erase must unlink, undo must relink.
    h = Harness()
    a = h.msp.add_line((0, 0), (2, 0))
    h.history.execute(actions.EraseCommand([a]))
    assert a.dxf.owner is None       # invisible to the overlay immediately
    h.history.undo()
    assert a.dxf.owner is not None   # visible again immediately


def test_undo_records_removed_handles_for_surgical_hide():
    # Commands whose undo destroys entities must record the handles so the
    # UI can hide the base-scene copies without waiting for a regen.
    h = Harness()
    add = actions.add_line((0, 0), (3, 3))
    h.history.execute(add)
    handle = add.entity.dxf.handle
    h.history.undo()
    assert add.removed_handles == [handle]

    clip = [h.msp.add_line((0, 0), (1, 0)).copy()]
    paste = actions.PasteCommand(clip, 5, 5)
    h.history.execute(paste)
    handles = [c.dxf.handle for c in paste.copies]
    h.history.undo()
    assert paste.removed_handles == handles

    c = h.msp.add_circle((5, 5), 2)
    rep = actions.ReplaceEntitiesCommand(
        "TRIM", [c], [lambda m: m.add_circle((5, 5), 1)])
    h.history.execute(rep)
    new_handles = [e.dxf.handle for e in rep.new_entities]
    h.history.undo()
    assert rep.removed_handles == new_handles


def _colleague(tmp_path):
    """A drawing whose content needs its own layer, block, text style and
    a dimension (with its anonymous *D block)."""
    doc = ezdxf.new("R2018", setup=True)
    doc.layers.add("MUROS", color=1)
    doc.styles.add("ROMANS", font="romans.shx")
    door = doc.blocks.new("PUERTA")
    door.add_arc((0, 0), 1, 0, 90)
    door.add_line((0, 0), (1, 0))
    msp = doc.modelspace()
    msp.add_blockref("PUERTA", (5, 5), dxfattribs={"layer": "MUROS"})
    msp.add_text("Hola", dxfattribs={"style": "ROMANS", "layer": "MUROS"})
    msp.add_linear_dim(base=(0, 3), p1=(0, 0), p2=(10, 0)).render()
    path = tmp_path / "colega.dxf"
    doc.saveas(path)
    return path


def _open(qapp, win, path):
    import time

    win.open_path(path)
    t0 = time.monotonic()
    while (win._open_thread is not None or win._regen_worker is not None) \
            and time.monotonic() - t0 < 30:
        qapp.processEvents()
    qapp.processEvents()
    # the "Loading file" window (#50) may have taken the activation
    from PySide6.QtTest import QTest

    win.activateWindow()
    QTest.qWaitForWindowActive(win, 5000)
    win.viewport.setFocus()
    qapp.processEvents()


def test_copy_in_one_drawing_and_paste_in_another_keeps_what_it_needs(qapp, tmp_path):
    # #75: copy/paste between files "truncated" the elements -- the pasted
    # copies named the first drawing's block, layer and styles, which the
    # second one did not have. Pressed for real: Ctrl+C, open, Ctrl+V.
    from PySide6.QtGui import QKeySequence
    from PySide6.QtTest import QTest

    from views.main_window import MainWindow

    mine = ezdxf.new("R2018")
    mine.modelspace().add_circle((0, 0), 1)
    mine.blocks.new("*D1")                       # a name the paste must not take
    mine.saveas(tmp_path / "mio.dxf")
    win = MainWindow()
    win.maybe_save_changes = lambda: True
    win.show()
    # Xvfb has no window manager: a keystroke to an inactive window is lost
    win.activateWindow()
    QTest.qWaitForWindowActive(win, 5000)
    try:
        _open(qapp, win, _colleague(tmp_path))
        win.tools.select_all()
        win.viewport.setFocus()
        QTest.keySequence(win.viewport, QKeySequence("Ctrl+C"))
        qapp.processEvents()
        assert win.tools.clipboard_originals(), "Ctrl+C did not reach the canvas"
        _open(qapp, win, tmp_path / "mio.dxf")
        win.viewport.setFocus()
        QTest.keySequence(win.viewport, QKeySequence("Ctrl+V"))
        qapp.processEvents()
        assert win.tools.tool is not None and win.tools.tool.name == "PASTECLIP", \
            "Ctrl+V did not reach the canvas"
        win.tools.on_text("100,0")
        qapp.processEvents()
        out = tmp_path / "pegado.dxf"
        win.document.save_as(out)
    finally:
        win.document.dirty = False
        win.close()
    back = ezdxf.readfile(out)
    pasted = {e.dxftype(): e for e in back.modelspace()}
    assert set(pasted) == {"CIRCLE", "INSERT", "TEXT", "DIMENSION"}
    assert "MUROS" in back.layers and "ROMANS" in back.styles
    assert len(back.blocks.get("PUERTA")) == 2
    # moved together, about 100 to the right (the base is the selection's
    # lower-left corner, a little left of the text)
    ins, text = pasted["INSERT"].dxf.insert, pasted["TEXT"].dxf.insert
    assert (ins.x - text.x, ins.y - text.y) == pytest.approx((5, 5))
    assert 100 < text.x < 101
    geometry = pasted["DIMENSION"].dxf.geometry
    assert geometry != "*D1" and len(back.blocks.get(geometry)) > 0
    assert not back.audit().has_errors
