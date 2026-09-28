# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""APPLOAD runs a Python file over ``actions`` as one undo step; SCRIPT
feeds an AutoCAD .scr to the command line (issue #44)."""
from __future__ import annotations

from pathlib import Path

import pytest

from core import scripting


def _window(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    qapp.processEvents()
    return win


def test_a_python_file_draws_through_actions_and_undoes_in_one_step(qapp, tmp_path):
    script = tmp_path / "grid.py"
    script.write_text(
        "for i in range(5):\n"
        "    execute(actions.add_line((0, i * 10), (100, i * 10)))\n"
        "echo('grid done')\n")
    win = _window(qapp)
    try:
        said = []
        win.command_line.echo = lambda text, *a, **k: said.append(text)
        msp = win.document.doc.modelspace()
        before = len(msp)
        win._on_command_submitted(f"APPLOAD {script}")
        assert len(msp) == before + 5
        assert "grid done" in said
        assert any("5 command(s)" in s for s in said), said
        win._cmd_undo()                      # ONE step takes the five lines
        assert len(msp) == before
        win._cmd_redo()
        assert len(msp) == before + 5
    finally:
        win.document.dirty = False
        win.close()


def test_a_failing_script_keeps_what_it_did_and_reports_the_error(qapp, tmp_path):
    script = tmp_path / "half.py"
    script.write_text(
        "execute(actions.add_line((0, 0), (10, 0)))\n"
        "raise ValueError('boom')\n")
    win = _window(qapp)
    try:
        said = []
        win.command_line.echo = lambda text, *a, **k: said.append(text)
        msp = win.document.doc.modelspace()
        before = len(msp)
        win._on_command_submitted(f"AP {script}")        # the alias
        assert len(msp) == before + 1
        assert any("ValueError: boom" in s for s in said), said
    finally:
        win.document.dirty = False
        win.close()


def test_the_namespace_offers_the_headless_api_and_nothing_of_qt():
    class Host:
        document = None
        tools = None
        command_line = None

    names = scripting.script_namespace(Host())
    for name in ("actions", "ezdxf", "document", "execute", "command", "echo"):
        assert name in names
    assert not any(n.startswith("Q") for n in names)


def test_an_scr_feeds_the_command_line_line_by_line_with_delay_and_rscript():
    fed = []
    runner = scripting.ScriptRunner(
        ["LINE", "0,0", "10,10", "", "; a comment", "DELAY 250", "RESUME", "ZOOM E"],
        fed.append)
    waits = []
    while (w := runner.step()) is not None:
        waits.append(w)
    assert fed == ["LINE", "0,0", "10,10", "", "ZOOM E"]
    assert 250 in waits, "DELAY did not ask for a pause"

    fed.clear()
    looping = scripting.ScriptRunner(["A", "RSCRIPT"], fed.append)
    steps = 0
    while looping.step() is not None and steps < 50:
        steps += 1
    assert fed[:3] == ["A", "A", "A"], "RSCRIPT did not repeat"


def test_script_draws_a_line_through_the_real_command_line(qapp, tmp_path):
    scr = tmp_path / "draw.scr"
    scr.write_text("LINE\n0,0\n50,0\n\n")
    win = _window(qapp)
    try:
        win.tools.osnap_on = False
        msp = win.document.doc.modelspace()
        before = len(msp)
        win._on_command_submitted(f"SCRIPT {scr}")
        win.run_script_to_end()
        lines = [e for e in msp if e.dxftype() == "LINE"]
        assert len(msp) == before + 1 and lines
        assert (lines[-1].dxf.end.x, lines[-1].dxf.end.y) == pytest.approx((50.0, 0.0))
        assert not win.tools.active(), "the blank line did not end LINE"
    finally:
        win.document.dirty = False
        win.close()


def test_a_missing_file_is_reported_not_raised(qapp, tmp_path):
    win = _window(qapp)
    try:
        said = []
        win.command_line.echo = lambda text, *a, **k: said.append(text)
        win._on_command_submitted(f"APPLOAD {tmp_path / 'nope.py'}")
        win._on_command_submitted(f"SCRIPT {tmp_path / 'nope.scr'}")
        assert sum("Cannot find file" in s for s in said) == 2
    finally:
        win.document.dirty = False
        win.close()
