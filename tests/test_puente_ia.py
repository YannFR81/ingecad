# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The AI bridge plugin (plugins/puente_ia, docs/ai-bridge.md): an agent's
call is one undo step or nothing, the command line answers it like a .scr,
it sees what the user sees, and the MCP server in front of it speaks MCP."""
from __future__ import annotations

import base64
import importlib
import importlib.util
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "plugins" / "puente_ia" / "mcp_server.py"


def _plugin(module: str):
    """A module of the plugin as the app loads it (by path, under the
    ``ingecad_plugin_puente_ia`` package name the loader gives it)."""
    from core.plugins import load_plugin

    name = "ingecad_plugin_puente_ia"
    if name not in sys.modules:
        loaded = load_plugin(ROOT / "plugins" / "puente_ia", bundled=True)
        assert loaded.available, loaded.reason
    return importlib.import_module(f"{name}.{module}")


def _window(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    qapp.processEvents()
    return win


def _close(win):
    bridge = getattr(win, "_ai_bridge", None)
    if bridge is not None:
        bridge.stop()
    win.document.dirty = False
    win.close()


@pytest.fixture
def free_port(monkeypatch):
    """The bridge on a port the system picks, never the user's 4764."""
    monkeypatch.setenv("INGECAD_AI_PORT", "0")


# -- run_python: one step, or nothing --------------------------------------------------

def test_run_python_draws_through_actions_as_one_undo_step(qapp):
    actions = _plugin("actions")
    win = _window(qapp)
    try:
        msp = win.document.doc.modelspace()
        before = len(msp)
        steps = len(win.history._undo)
        reply = actions.run_code(win, (
            "for i in range(4):\n"
            "    execute(actions.add_line((0, i * 10), (100, i * 10)))\n"
            "print('drawn', len(msp))\n"))
        assert reply["error"] is None
        assert reply["changed"] == 4
        assert reply["stdout"].strip() == f"drawn {before + 4}"
        assert len(msp) == before + 4
        assert len(win.history._undo) == steps + 1    # ONE step for the four
        win._cmd_undo()
        assert len(msp) == before
        win._cmd_redo()
        assert len(msp) == before + 4
    finally:
        _close(win)


def _wait_regen(qapp, win, timeout_s=30.0):
    deadline = time.monotonic() + timeout_s
    while win._regen_worker is not None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    qapp.processEvents()


def test_thousands_of_commands_in_one_call_cost_one_screen_update(qapp):
    """Executed one by one through the tool controller, every command files
    its entity in the pick index and redraws the overlay: 2 000 lines took
    46 s, and an agent's 10 000 froze the user's IngeCAD for many minutes
    (2026-10-10). The bridge updates the screen once, at the end."""
    actions = _plugin("actions")
    win = _window(qapp)
    try:
        started = time.monotonic()
        reply = actions.run_code(win, (
            "for i in range(3000):\n"
            "    execute(actions.add_line((i * 0.01, 0), (i * 0.01, 1)))\n"))
        assert reply["changed"] == 3000
        assert time.monotonic() - started < 10, "one screen update per command again?"
        _wait_regen(qapp, win)
        assert win.viewport.scene_bounds() == pytest.approx((0, 0, 29.99, 1))
        win._cmd_undo()
        assert len(win.document.doc.modelspace()) == 0
    finally:
        _close(win)


def test_a_single_command_shows_at_once_and_is_pickable(qapp):
    actions = _plugin("actions")
    win = _window(qapp)
    try:
        actions.run_code(win, "execute(actions.add_circle((5, 5), 2))")
        _wait_regen(qapp, win)
        circle = win.document.doc.modelspace().query("CIRCLE")[0]
        handles = {h for h, *_ in win.tools.index.query_rect(3, 3, 7, 7)} \
            if hasattr(win.tools.index, "query_rect") else None
        if handles is not None:
            assert circle.dxf.handle in handles
        assert win.tools.select_all() == 1
    finally:
        _close(win)


def test_code_that_raises_is_rolled_back_whole_and_keeps_the_redo_stack(qapp):
    actions = _plugin("actions")
    from core import actions as core_actions

    win = _window(qapp)
    try:
        msp = win.document.doc.modelspace()
        win.tools._execute(core_actions.add_circle((0, 0), 5))
        win._cmd_undo()                          # something the user may redo
        assert win.history.can_redo
        before, steps = len(msp), len(win.history._undo)
        reply = actions.run_code(win, (
            "execute(actions.add_line((0, 0), (10, 0)))\n"
            "execute(actions.add_line((0, 0), (0, 10)))\n"
            "raise ValueError('boom')\n"))
        assert reply["rolled_back"] is True
        assert reply["changed"] == 0
        assert "ValueError: boom" in reply["error"]
        assert "<run_python>" in reply["error"]
        assert "actions.py" not in reply["error"], "the bridge's own frame leaked"
        assert len(msp) == before
        assert len(win.history._undo) == steps
        assert win.history.can_redo, "the rollback threw away the user's redo"
        win._cmd_redo()
        assert len(msp) == before + 1            # the circle, still redoable
    finally:
        _close(win)


def test_a_syntax_error_changes_nothing_and_says_where(qapp):
    actions = _plugin("actions")
    win = _window(qapp)
    try:
        steps = len(win.history._undo)
        reply = actions.run_code(win, "execute(actions.add_line((0, 0), (1, 1))\n")
        assert "SyntaxError" in reply["error"]
        assert reply["changed"] == 0
        assert len(win.history._undo) == steps
    finally:
        _close(win)


def test_variables_survive_between_calls_and_inspection_leaves_no_step(qapp):
    actions = _plugin("actions")
    win = _window(qapp)
    try:
        scope: dict = {}
        steps = len(win.history._undo)
        actions.run_code(win, "axis = [(0, 0), (50, 0), (80, 30)]", scope)
        reply = actions.run_code(win, "print(len(axis), document.name)", scope)
        assert reply["stdout"].split()[0] == "3"
        assert len(win.history._undo) == steps
        reply = actions.run_code(win, "execute(actions.add_polyline(axis))", scope)
        assert reply["changed"] == 1
    finally:
        _close(win)


def test_the_namespace_offers_layers_and_the_users_selection(qapp):
    actions = _plugin("actions")
    from core import actions as core_actions

    win = _window(qapp)
    try:
        command = core_actions.add_line((0, 0), (5, 5))
        win.tools._execute(command)
        win.tools.selection = {command.entity.dxf.handle}
        reply = actions.run_code(win, (
            "execute(layers.NewLayerCommand('AXE', color=1))\n"
            "layers.set_current_layer(document, 'AXE')\n"
            "print([e.dxftype() for e in selected()])\n"
            "execute(actions.add_circle((0, 0), 2))\n"))
        assert reply["error"] is None, reply["error"]
        assert reply["stdout"].strip() == "['LINE']"
        assert "AXE" in win.document.doc.layers
        circle = win.document.doc.modelspace().query("CIRCLE")[0]
        assert circle.dxf.layer == "AXE"         # drawn on the current layer
        win._cmd_undo()                          # one step: layer and circle
        assert "AXE" not in win.document.doc.layers
    finally:
        _close(win)


def test_zoom_extents_frames_what_the_same_call_just_drew(qapp):
    """The canvas regenerates in the background; a zoom computed from it
    in the same call would frame the drawing as it was before."""
    actions = _plugin("actions")
    win = _window(qapp)
    try:
        actions.run_code(win, "execute(actions.add_rectangle((1000, 2000), (1040, 2006)))\n"
                              "zoom_extents()")
        view = win.viewport.view
        assert view.cx == pytest.approx(1020) and view.cy == pytest.approx(2003)
        assert view.width / view.scale == pytest.approx(40 / 0.95, rel=0.05) or \
            view.height / view.scale == pytest.approx(6 / 0.95, rel=0.05)
    finally:
        _close(win)


def test_erased_entities_leave_the_selection_and_selected(qapp):
    """ERASE unlinks (the entities stay alive for its undo): what the agent
    erased must not linger in the user's selection or in selected()."""
    actions = _plugin("actions")
    win = _window(qapp)
    try:
        actions.run_code(win, "for i in range(6):\n"
                              "    execute(actions.add_line((i, 0), (i, 1)))")
        assert win.tools.select_all() == 6
        reply = actions.run_code(win, "execute(actions.EraseCommand(selected()[::2]))\n"
                                      "print(len(selected()))")
        assert reply["stdout"].strip() == "3"
        assert len(win.tools.selection) == 3
        assert actions.model_summary(win)["selection"] == 3
    finally:
        _close(win)


# -- command: the command line, as a .scr ---------------------------------------------------

def test_command_lines_run_like_a_script_and_fold_into_one_step(qapp):
    actions = _plugin("actions")
    win = _window(qapp)
    try:
        msp = win.document.doc.modelspace()
        before, steps = len(msp), len(win.history._undo)
        reply = actions.run_command_lines(
            win, "CIRCLE\n50,50\n10\nLINE\n0,0\n100,0\n100,50\n\n")
        assert len(msp) == before + 3
        assert reply["changed"] == 3
        assert reply["waiting_for_input"] is None
        assert any("Specify radius" in line for line in reply["echo"])
        assert len(win.history._undo) == steps + 1
    finally:
        _close(win)


def test_a_command_left_waiting_is_reported_and_cancelled_by_the_next_call(qapp):
    actions = _plugin("actions")
    win = _window(qapp)
    try:
        reply = actions.run_command_lines(win, "LINE\n0,0\n")
        assert reply["waiting_for_input"] == "LINE"
        reply = actions.run_command_lines(win, "CIRCLE\n0,0\n3\n")
        assert reply["waiting_for_input"] is None
        assert len(win.document.doc.modelspace().query("CIRCLE")) == 1
        assert not win.document.doc.modelspace().query("LINE")
    finally:
        _close(win)


# -- query_model and screenshot ----------------------------------------------------------------

def test_query_model_says_what_an_agent_needs_to_orient_itself(qapp):
    actions = _plugin("actions")
    win = _window(qapp)
    try:
        actions.run_code(win, (
            "execute(layers.NewLayerCommand('BORDURE', color=3))\n"
            "for x in (0, 10, 20):\n"
            "    execute(actions.add_circle((x, 0), 1))\n"
            "execute(actions.add_line((0, -5), (40, 5)))\n"))
        summary = actions.model_summary(win)
        json.dumps(summary)                       # it has to travel as JSON
        assert summary["entities"]["total"] == 4
        assert summary["entities"]["by_type"] == {"CIRCLE": 3, "LINE": 1}
        assert "BORDURE" in [layer["name"] for layer in summary["layers"]]
        assert summary["units"] in ("Meters", "Millimeters")
        assert summary["extents"] == {"min": [-1.0, -5.0], "max": [40.0, 5.0]}
        assert summary["space"] == "Model"
        assert summary["waiting_for_input"] is None
    finally:
        _close(win)


def test_screenshot_hands_back_a_png_of_the_view(qapp):
    bridge = _plugin("bridge")
    actions = _plugin("actions")
    win = _window(qapp)
    try:
        actions.run_code(win, "execute(actions.add_rectangle((0, 0), (40, 20)))\n"
                              "zoom_extents()")
        shot = bridge.screenshot(win, 320, 200)
        png = base64.b64decode(shot["png_base64"])
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        assert shot["source"] in ("canvas", "plot")
        assert 0 < shot["width"] <= 320 and 0 < shot["height"] <= 200
    finally:
        _close(win)


# -- the bridge: a socket on the loopback, served on the UI thread ---------------------------------

def _talk(qapp, port, requests):
    """Send ``requests`` from a worker thread while this (the UI) thread
    keeps turning the event loop, as the running app does."""
    replies, errors = [], []

    def client():
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=30) as sock:
                stream = sock.makefile("rwb")
                for request in requests:
                    stream.write((json.dumps(request) + "\n").encode())
                    stream.flush()
                    replies.append(json.loads(stream.readline()))
        except Exception as exc:          # noqa: BLE001 - surfaced below
            errors.append(exc)

    worker = threading.Thread(target=client)
    worker.start()
    deadline = time.monotonic() + 60
    while worker.is_alive() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.002)
    worker.join(timeout=1)
    assert not errors, errors
    return replies


def test_aibridge_listens_on_the_loopback_and_answers_on_the_ui_thread(qapp, free_port):
    win = _window(qapp)
    try:
        win._on_command_submitted("AIBRIDGE ON")
        bridge = win._ai_bridge
        assert bridge.running
        assert bridge._server.getsockname()[0] == "127.0.0.1"
        replies = _talk(qapp, bridge.port, [
            {"id": 1, "tool": "run_python",
             "args": {"code": "import threading\n"
                              "print(threading.current_thread() is threading.main_thread())\n"
                              "execute(actions.add_line((0, 0), (9, 9)))"}},
            {"id": 2, "tool": "query_model", "args": {}},
            {"id": 3, "tool": "undo", "args": {}},
            {"id": 4, "tool": "redo", "args": {}},
            {"id": 5, "tool": "no_such_tool", "args": {}},
        ])
        assert [r["id"] for r in replies] == [1, 2, 3, 4, 5]
        assert replies[0]["ok"] and replies[0]["result"]["stdout"].strip() == "True"
        assert replies[1]["result"]["entities"]["total"] == 1
        assert replies[2]["result"]["done"] is True
        assert replies[3]["result"]["done"] is True
        assert not replies[4]["ok"] and "unknown tool" in replies[4]["error"]
        assert len(win.document.doc.modelspace()) == 1
    finally:
        _close(win)


def test_two_agents_can_be_connected_at_once(qapp, free_port):
    """Claude Desktop and Claude Code on the same drawing: neither waits
    for the other to hang up."""
    win = _window(qapp)
    try:
        win._on_command_submitted("AIBRIDGE ON")
        port = win._ai_bridge.port
        first = socket.create_connection(("127.0.0.1", port), timeout=30)
        try:
            replies = _talk(qapp, port, [{"id": 9, "tool": "query_model", "args": {}}])
            assert replies[0]["ok"]
            assert win._ai_bridge.clients == 2
        finally:
            first.close()
    finally:
        _close(win)


def test_the_bridge_runs_no_thread_of_its_own(qapp, free_port):
    """Served from the GUI thread by a timer: a listening worker would
    keep the garbage collector paused all session (core/gc_guard.py)."""
    import threading

    before = set(threading.enumerate())
    win = _window(qapp)
    try:
        win._on_command_submitted("AIBRIDGE ON")
        assert set(threading.enumerate()) <= before | {threading.main_thread()}
    finally:
        _close(win)


def _talk_paced(qapp, port, steps):
    """Like :func:`_talk`, with ``("sleep", seconds)`` steps between the
    requests, for what has to happen meanwhile on the UI thread."""
    replies, errors = [], []

    def client():
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=30) as sock:
                stream = sock.makefile("rwb")
                for step in steps:
                    if step[0] == "sleep":
                        time.sleep(step[1])
                        continue
                    stream.write((json.dumps(step[1]) + "\n").encode())
                    stream.flush()
                    line = stream.readline()
                    replies.append((time.monotonic(), json.loads(line)))
        except Exception as exc:          # noqa: BLE001 - surfaced below
            errors.append(exc)

    worker = threading.Thread(target=client)
    worker.start()
    deadline = time.monotonic() + 60
    while worker.is_alive() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.002)
    worker.join(timeout=1)
    assert not errors, errors
    return replies


def _close_dialog_later(ms):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    closed = []

    def close():
        dialog = QApplication.activeModalWidget()
        if dialog is not None:
            closed.append(dialog.windowTitle())
            dialog.reject()

    QTimer.singleShot(ms, close)
    return closed


def test_a_call_that_opens_a_dialog_is_answered_at_once(qapp, free_port):
    """UNITS opens a modal dialog. The agent hears so right away instead of
    waiting for the user; calls made while it is open are refused, not run
    inside its event loop; once it closes, the bridge serves again."""
    win = _window(qapp)
    try:
        win._on_command_submitted("AIBRIDGE ON")
        closed = _close_dialog_later(2500)
        started = time.monotonic()
        replies = _talk_paced(qapp, win._ai_bridge.port, [
            ("send", {"id": 1, "tool": "command", "args": {"lines": "UNITS\n"}}),
            ("send", {"id": 2, "tool": "run_python",
                      "args": {"code": "execute(actions.add_line((0, 0), (1, 1)))"}}),
            ("sleep", 3.0),
            ("send", {"id": 3, "tool": "query_model", "args": {}}),
        ])
        (t1, first), (_t2, second), (_t3, third) = replies
        assert t1 - started < 2.0, "the agent waited for the user"
        assert not first["ok"] and "opened a dialog" in first["error"]
        assert not second["ok"] and "A dialog is open" in second["error"]
        assert third["ok"] and third["result"]["entities"]["total"] == 0
        assert closed, "the dialog never opened"
    finally:
        _close(win)


def test_a_dialog_the_user_opened_holds_the_agent_off(qapp, free_port):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QDialog

    win = _window(qapp)
    try:
        win._on_command_submitted("AIBRIDGE ON")
        dialog = QDialog(win)
        dialog.setWindowTitle("Options")
        QTimer.singleShot(0, dialog.exec)
        closed = _close_dialog_later(1500)
        replies = _talk_paced(qapp, win._ai_bridge.port, [
            ("sleep", 0.3),
            ("send", {"id": 1, "tool": "run_python",
                      "args": {"code": "execute(actions.add_line((0, 0), (1, 1)))"}}),
            ("sleep", 2.0),
            ("send", {"id": 2, "tool": "run_python",
                      "args": {"code": "execute(actions.add_line((0, 0), (1, 1)))"}}),
        ])
        (_t, refused), (_t2, done) = replies
        assert not refused["ok"] and "(Options)" in refused["error"]
        assert done["ok"] and done["result"]["changed"] == 1
        assert closed == ["Options"]
        assert len(win.document.doc.modelspace()) == 1
    finally:
        _close(win)


def test_bad_json_is_answered_not_fatal(qapp, free_port):
    win = _window(qapp)
    try:
        win._on_command_submitted("AIBRIDGE ON")
        port = win._ai_bridge.port
        replies = []

        def client():
            with socket.create_connection(("127.0.0.1", port), timeout=30) as sock:
                stream = sock.makefile("rwb")
                stream.write(b"this is not json\n")
                stream.flush()
                replies.append(json.loads(stream.readline()))

        worker = threading.Thread(target=client)
        worker.start()
        while worker.is_alive():
            qapp.processEvents()
            time.sleep(0.002)
        assert replies == [{"id": None, "ok": False, "error": "bad json"}]
        assert win._ai_bridge.running
    finally:
        _close(win)


def test_aibridge_off_frees_the_port_and_status_says_so(qapp, free_port):
    win = _window(qapp)
    try:
        said = []
        echo = win.command_line.echo
        win.command_line.echo = lambda text, *a, **k: (said.append(text), echo(text))
        win._on_command_submitted("AIBRIDGE ON")
        port = win._ai_bridge.port
        win._on_command_submitted("AIBRIDGE STATUS")
        assert any(f"127.0.0.1:{port}" in s for s in said)
        win._on_command_submitted("AIBRIDGE OFF")
        assert not win._ai_bridge.running
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
        win._on_command_submitted("AIBRIDGE STATUS")
        assert said[-1] == "AI bridge is off."
        win._on_command_submitted("AIBRIDGE MAYBE")
        assert "AIBRIDGE takes ON, OFF or STATUS" in said[-1]
    finally:
        _close(win)


def test_turning_the_plugin_off_stops_the_bridge(qapp, free_port):
    win = _window(qapp)
    try:
        win._on_command_submitted("AIBRIDGE ON")
        assert win._ai_bridge.running
        win.plugins.deactivate("puente_ia")
        assert not win._ai_bridge.running
        assert win.plugins.activate("puente_ia")
    finally:
        _close(win)


def test_a_host_without_the_off_hook_stops_on_the_next_request(qapp, free_port):
    """Dropped into an IngeCAD older than ``on_deactivate``, the bridge
    still notices its plugin is gone, refuses, and lets go of the port."""
    win = _window(qapp)
    try:
        win._on_command_submitted("AIBRIDGE ON")
        bridge = win._ai_bridge
        win.plugins._active.pop("puente_ia")   # off, as an old host does it: no hook
        assert bridge.running
        replies = _talk(qapp, bridge.port, [{"id": 1, "tool": "query_model", "args": {}}])
        assert not replies[0]["ok"] and "turned off" in replies[0]["error"]
        qapp.processEvents()                   # the stop queued after the reply
        assert not bridge.running
    finally:
        win.plugins._active.pop("puente_ia", None)
        win.plugins.activate("puente_ia")
        _close(win)


def test_a_second_window_does_not_fight_for_the_port(qapp, free_port):
    first, second = _window(qapp), _window(qapp)
    try:
        said = []
        echo = second.command_line.echo
        second.command_line.echo = lambda text, *a, **k: (said.append(text), echo(text))
        first._on_command_submitted("AIBRIDGE ON")
        second._on_command_submitted("AIBRIDGE ON")
        assert first._ai_bridge.running
        assert not second._ai_bridge.running
        assert any("already on in another window" in s for s in said)
    finally:
        _close(first)
        _close(second)


def test_start_with_ingecad_starts_it_on_the_next_drawing(qapp, free_port):
    commands = _plugin("commands")
    win = _window(qapp)
    try:
        commands.set_autostart(False)
        win.new_document()
        assert getattr(win, "_ai_bridge", None) is None or not win._ai_bridge.running
        commands.set_autostart(True)
        win.new_document()
        assert win._ai_bridge.running
    finally:
        commands.set_autostart(False)
        _close(win)


def test_start_with_ingecad_needs_no_drawing_open(qapp, free_port):
    """IngeCAD can start on its startup window with no drawing at all: the
    bridge starts when the plugin comes on, not with the first drawing."""
    commands = _plugin("commands")
    win = _window(qapp)
    try:
        win.plugins.deactivate("puente_ia")
        commands.set_autostart(True)
        assert win.plugins.activate("puente_ia")
        assert win._ai_bridge.running
    finally:
        commands.set_autostart(False)
        _close(win)


def test_an_older_host_gets_the_autostart_once_its_loop_runs(qapp, free_port):
    """0.6.5 and 0.6.6 have no on_activate: the plugin looks for its
    windows once the event loop turns."""
    commands = _plugin("commands")
    package = sys.modules["ingecad_plugin_puente_ia"]
    win = _window(qapp)
    try:
        commands.set_autostart(True)
        package._autostart_where_active()
        assert win._ai_bridge.running
    finally:
        commands.set_autostart(False)
        _close(win)


def test_the_bridge_window_shows_the_lines_to_paste(qapp, free_port):
    win = _window(qapp)
    try:
        win._on_command_submitted("AIBRIDGE")
        dialog = win._ai_bridge_dialog
        assert dialog.isVisible() and not dialog.isModal()
        text = dialog._text.toPlainText()
        assert f"127.0.0.1:{win._ai_bridge.port}" in text
        assert '"mcpServers"' in text and '"ingecad"' in text
        dialog.toggle()
        assert not win._ai_bridge.running
        assert not dialog._text.isVisible()
        win.plugins.deactivate("puente_ia")
        assert win._ai_bridge_dialog is None
        assert win.plugins.activate("puente_ia")
    finally:
        _close(win)


# -- what to paste into a client --------------------------------------------------------------

def test_the_command_to_paste_matches_how_ingecad_was_installed():
    actions = _plugin("actions")
    script = Path("/opt/ingecad/plugins/puente_ia/mcp_server.py")
    # Linux packages: a stable path from the host, never the AppImage mount
    assert actions.mcp_command("linux", frozen=True, env={"APPIMAGE": "/home/u/IngeCAD.AppImage"},
                               script=script) == ["/home/u/IngeCAD.AppImage", "--mcp"]
    assert actions.mcp_command("linux", frozen=True, env={"FLATPAK_ID": "org.ingecad.IngeCAD"},
                               script=script) == ["flatpak", "run", "org.ingecad.IngeCAD", "--mcp"]
    assert actions.mcp_command("linux", frozen=True, env={"SNAP_NAME": "ingecad"},
                               script=script) == ["/snap/bin/ingecad", "--mcp"]
    assert actions.mcp_command("linux", frozen=True, env={}, executable="/opt/ingecad/ingecad",
                               script=script) == ["/opt/ingecad/ingecad", "--mcp"]
    # Windows: the console program beside the app...
    exe = r"C:\Program Files\IngeCAD\ingecad.exe"
    assert actions.mcp_command("win32", frozen=True, env={}, executable=exe, script=script,
                               exists=lambda p: True) == [r"C:\Program Files\IngeCAD\ingecad-mcp.exe"]
    # ...or, in a build that predates it, the plugin's own script
    win_script = r"C:\Users\u\AppData\Roaming\IngeCAD\plugins\puente_ia\mcp_server.py"
    assert actions.mcp_command("win32", frozen=True, env={}, executable=exe, script=win_script,
                               exists=lambda p: False, which=lambda n: None) == ["python", win_script]
    found = r"C:\Users\u\AppData\Local\Programs\Python\Python312\python.exe"
    assert actions.mcp_command("win32", frozen=True, env={}, executable=exe, script=win_script,
                               exists=lambda p: False, which=lambda n: found) == [found, win_script]
    # a checkout runs the script
    assert actions.mcp_command("linux", frozen=False, env={}, script=script) == [
        "python3", str(script)]


def test_the_windows_fallback_finds_a_python_or_the_py_launcher():
    actions = _plugin("actions")
    exe = r"C:\Program Files\IngeCAD\ingecad.exe"
    script = r"C:\Users\u\AppData\Roaming\IngeCAD\plugins\puente_ia\mcp_server.py"
    py = r"C:\Windows\py.exe"
    assert actions.mcp_command("win32", frozen=True, env={}, executable=exe, script=script,
                               exists=lambda p: False,
                               which=lambda n: py if n == "py" else None) == [py, "-3", script]


def test_the_store_edition_of_claude_desktop_is_told_its_own_config(tmp_path):
    actions = _plugin("actions")
    assert actions.desktop_config_path("win32", {"LOCALAPPDATA": str(tmp_path)}) == \
        r"%APPDATA%\Claude\claude_desktop_config.json"
    store = tmp_path / "Packages" / "Claude_pzs8sxrjxfjjc" / "LocalCache" / "Roaming" / "Claude"
    store.mkdir(parents=True)
    found = actions.desktop_config_path("win32", {"LOCALAPPDATA": str(tmp_path)})
    assert found == str(store / "claude_desktop_config.json")
    assert actions.desktop_config_path("linux", {}) == "~/.config/Claude/claude_desktop_config.json"


def test_the_client_block_names_a_non_default_port():
    actions = _plugin("actions")
    config = actions.client_config(5000, platform="linux", frozen=False, env={},
                                   script=Path("/x/mcp_server.py"))
    entry = config["mcpServers"]["ingecad"]
    assert entry == {"command": "python3", "args": ["/x/mcp_server.py"],
                     "env": {"INGECAD_AI_PORT": "5000"}}
    default = actions.client_config(actions.DEFAULT_PORT, platform="linux", frozen=False,
                                    env={}, script=Path("/x/mcp_server.py"))
    assert "env" not in default["mcpServers"]["ingecad"]


def test_the_default_port_is_not_ingetrazos():
    actions = _plugin("actions")
    assert actions.DEFAULT_PORT == 4764 != 4763
    assert actions.bridge_port({}) == 4764
    assert actions.bridge_port({"INGECAD_AI_PORT": "5123"}) == 5123
    assert actions.bridge_port({"INGECAD_AI_PORT": "nonsense"}) == 4764


# -- the MCP server --------------------------------------------------------------------------------

def _mcp_module():
    spec = importlib.util.spec_from_file_location("ingecad_mcp_server_under_test", SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_mcp_server_is_standard_library_only():
    """It runs from a checkout, a plugin folder and a frozen console exe
    with nothing of the app beside it."""
    import ast

    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    imported.discard("__future__")
    assert imported <= set(sys.stdlib_module_names), imported - set(sys.stdlib_module_names)


def test_the_mcp_server_lists_six_tools_and_its_instructions():
    mcp = _mcp_module()
    init = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"protocolVersion": "2025-06-18"}})
    assert init["result"]["protocolVersion"] == "2025-06-18"
    assert init["result"]["serverInfo"]["name"] == "ingecad"
    assert "undo step" in init["result"]["instructions"]
    old = mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "initialize",
                      "params": {"protocolVersion": "1999-01-01"}})
    assert old["result"]["protocolVersion"] in mcp.PROTOCOLS
    assert mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    tools = mcp.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})["result"]["tools"]
    assert [t["name"] for t in tools] == [
        "run_python", "command", "query_model", "screenshot", "undo", "redo"]
    for tool in tools:
        assert tool["inputSchema"]["type"] == "object"
    unknown = mcp.handle({"jsonrpc": "2.0", "id": 4, "method": "resources/list"})
    assert unknown["error"]["code"] == -32601


def test_the_reference_names_only_actions_that_exist():
    """The agent reads this instead of exploring: a name it promises that
    core.actions does not have costs a failed call every time."""
    import re

    from core import actions as core_actions

    mcp = _mcp_module()
    block = mcp.REFERENCE[mcp.REFERENCE.index("actions    every"):mcp.REFERENCE.index("execute(cmd)")]
    names = set(re.findall(r"\b([A-Za-z_]\w*)\(", block))
    missing = sorted(n for n in names if not hasattr(core_actions, n))
    assert not missing, missing
    from core import layers

    for name in ("NewLayerCommand", "set_current_layer", "LayerPropertyCommand"):
        assert hasattr(layers, name), name


def test_the_mcp_server_says_how_to_start_the_bridge_when_it_is_off(monkeypatch):
    mcp = _mcp_module()
    with socket.socket() as probe:              # a port nobody listens on
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    monkeypatch.setattr(mcp, "PORT", port)
    reply = mcp.handle({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                        "params": {"name": "query_model", "arguments": {}}})
    result = reply["result"]
    assert result["isError"] is True
    assert "AIBRIDGE" in result["content"][0]["text"]


def test_the_mcp_server_formats_each_tool_for_the_model():
    mcp = _mcp_module()
    image = mcp._format("screenshot", {"png_base64": "iVBOR", "width": 10, "height": 8,
                                       "source": "canvas"})
    assert image["content"][0] == {"type": "image", "data": "iVBOR", "mimeType": "image/png"}
    failed = mcp._format("run_python", {"stdout": "", "echo": [], "changed": 0,
                                        "error": "Traceback...\nNameError: x",
                                        "rolled_back": True})
    assert failed["isError"] is True
    assert "ROLLED BACK" in failed["content"][0]["text"]
    typed = mcp._format("command", {"echo": ["Command: LINE", "Specify first point:"],
                                    "changed": 0, "waiting_for_input": "LINE"})
    text = typed["content"][0]["text"]
    assert "Specify first point:" in text and "still waiting for input: LINE" in text


def test_a_flood_of_output_is_clipped_with_a_note():
    mcp = _mcp_module()
    reply = mcp._format("run_python", {"stdout": "A" * 100_000 + "END", "echo": [],
                                       "changed": 0, "error": None})
    text = reply["content"][0]["text"]
    assert len(text) < mcp.MAX_TEXT + 500
    assert "characters cut" in text and "END" in text and text.startswith("AAA")


def test_a_real_mcp_session_draws_in_the_open_drawing(qapp, free_port):
    """The whole chain: an MCP client speaking JSON-RPC over stdio to the
    server process, the server to the bridge, the bridge to the drawing."""
    win = _window(qapp)
    proc = None
    try:
        win._on_command_submitted("AIBRIDGE ON")
        port = win._ai_bridge.port
        env = dict(os.environ, INGECAD_AI_PORT=str(port))
        proc = subprocess.Popen([sys.executable, str(SERVER)], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, env=env, text=True,
                                encoding="utf-8")
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                        "clientInfo": {"name": "test", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "command", "arguments": {"lines": "CIRCLE\n0,0\n25\n"}}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "run_python", "arguments": {
                 "code": "execute(actions.add_text((0, 30), 'ROND-POINT', 2.5))\n"
                         "zoom_extents()\nprint(len(msp))"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "screenshot", "arguments": {"width": 300, "height": 200}}},
        ]
        replies = []

        def converse():
            for message in messages:
                proc.stdin.write(json.dumps(message) + "\n")
                proc.stdin.flush()
                if "id" in message:
                    replies.append(json.loads(proc.stdout.readline()))

        worker = threading.Thread(target=converse)
        worker.start()
        deadline = time.monotonic() + 60
        while worker.is_alive() and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.002)
        worker.join(timeout=1)
        assert [r["id"] for r in replies] == [1, 2, 3, 4]
        assert replies[1]["result"]["isError"] is False
        assert "Specify radius" in replies[1]["result"]["content"][0]["text"]
        assert replies[2]["result"]["content"][0]["text"].startswith("2")
        content = replies[3]["result"]["content"]
        assert content[0]["type"] == "image"
        assert base64.b64decode(content[0]["data"])[:4] == b"\x89PNG"
        msp = win.document.doc.modelspace()
        assert sorted(e.dxftype() for e in msp) == ["CIRCLE", "TEXT"]
    finally:
        if proc is not None:
            proc.stdin.close()
            proc.wait(timeout=10)
        _close(win)


def test_ingecad_dash_dash_mcp_runs_the_server():
    """What the packages hand to a client: ``ingecad --mcp`` answers MCP on
    stdio without opening a window."""
    request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
    done = subprocess.run([sys.executable, str(ROOT / "main.py"), "--mcp"], input=request,
                          capture_output=True, text=True, timeout=60,
                          env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
    assert done.returncode == 0, done.stderr
    reply = json.loads(done.stdout.splitlines()[0])
    assert len(reply["result"]["tools"]) == 6


def test_windows_builds_carry_a_console_mcp_program():
    spec = (ROOT / "packaging" / "ingecad.spec").read_text(encoding="utf-8")
    assert 'name="ingecad-mcp"' in spec
    assert '"puente_ia" / "mcp_server.py"' in spec
    block = spec[spec.index('name="ingecad-mcp"'):]
    assert "console=True" in block[:400]
