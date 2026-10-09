# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""What the Windows build (#28) needs from code that runs everywhere."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# The application's own code; tools/ holds developer harnesses (corpus
# sweeps, the ODA judge) that never ship.
APP_DIRS = ("core", "views", "formats", "render", "plugins")
# Linux-only by construction: the AppImage desktop integration.
EXEMPT = {"core/appimage.py"}
_SPAWN = re.compile(r"subprocess\.(run|Popen|call|check_call|check_output)\s*\(")


def test_every_program_the_app_runs_hides_its_console():
    """On Windows a console program started from the GUI flashes a black
    terminal window unless it is asked not to: every spawn passes
    quiet_process() (formats.dwg_bridge)."""
    offenders = []
    for folder in APP_DIRS:
        for path in (ROOT / folder).rglob("*.py"):
            rel = path.relative_to(ROOT).as_posix()
            if rel in EXEMPT:
                continue
            text = path.read_text(encoding="utf-8")
            for match in _SPAWN.finditer(text):
                call = text[match.start():text.find(")\n", match.start()) + 1]
                if "quiet_process()" not in call:
                    line = text.count("\n", 0, match.start()) + 1
                    offenders.append(f"{rel}:{line}")
    assert not offenders, offenders


def test_the_guard_would_catch_a_bare_spawn():
    text = 'subprocess.run(["dwg2dxf", "x.dwg"], check=False)\n'
    match = _SPAWN.search(text)
    assert match and "quiet_process()" not in text[match.start():]


def test_converters_are_found_by_their_windows_name(tmp_path, monkeypatch):
    from formats import dwg_bridge

    (tmp_path / "dwg2dxf.exe").write_bytes(b"MZ")
    monkeypatch.setattr(dwg_bridge, "_VENDOR_BIN", tmp_path)
    monkeypatch.setattr(dwg_bridge.os, "name", "nt")
    assert dwg_bridge.find_dwg2dxf() == tmp_path / "dwg2dxf.exe"
    assert dwg_bridge.quiet_process() == {"creationflags": 0x08000000}   # CREATE_NO_WINDOW
    monkeypatch.setattr(dwg_bridge.os, "name", "posix")
    assert dwg_bridge.quiet_process() == {}
