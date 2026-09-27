# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Objects ezdxf cannot move or copy -- a Civil 3D proxy, an OLE object --
inside a selection. MOVE over a window that took one raised half-way on a
real road plan (0957, 69 proxies and 34 OLE objects): what it had moved
stayed moved and there was no undo. Now they stay put, the rest of the
command runs whole, and it says what it left."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import actions  # noqa: E402
from core.commands import History  # noqa: E402
from core.document import Document  # noqa: E402
from core.modify import ArrayCommand  # noqa: E402


def _doc():
    document = Document.new()
    msp = document.modelspace()
    line = msp.add_line((0, 0), (10, 0))
    ole = msp.new_entity("OLE2FRAME", {})
    return document, msp, line, ole


def test_move_leaves_the_ole_object_and_undo_is_whole():
    document, msp, line, ole = _doc()
    history = History(document)
    cmd = actions.move_entities([ole, line], 5, 5)
    history.execute(cmd)                             # no exception
    assert cmd.skipped == [ole]
    assert tuple(line.dxf.start)[:2] == (5, 5)
    history.undo()
    assert tuple(line.dxf.start)[:2] == (0, 0)


def test_copy_mirror_paste_and_array_skip_it_too():
    document, msp, line, ole = _doc()
    history = History(document)
    for cmd in (actions.CopyEntitiesCommand([ole, line],
                                            actions._mirror_matrix((0, 0), (0, 1))),
                actions.PasteCommand([ole, line], 20, 0),
                ArrayCommand([ole, line], [actions._mirror_matrix((0, 0), (1, 0))])):
        history.execute(cmd)
        assert cmd.skipped == [ole]
    assert len([e for e in msp if e.dxftype() == "OLE2FRAME"]) == 1
    assert len([e for e in msp if e.dxftype() == "LINE"]) == 4


def test_the_window_says_what_it_left(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document()
    msp = win.document.modelspace()
    line = msp.add_line((0, 0), (10, 0))
    ole = msp.new_entity("OLE2FRAME", {})
    echoes = []
    real = win.command_line.echo
    win.command_line.echo = lambda text, *a, **k: (echoes.append(text),
                                                   real(text, *a, **k))
    try:
        win.tools._execute(actions.move_entities([line, ole], 1, 1))
        assert any("cannot move or copy OLE2FRAME" in e for e in echoes)
    finally:
        win.document.dirty = False
        win.close()
