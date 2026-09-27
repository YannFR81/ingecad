# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""One-shot object snaps (#18): typed END/TAN/NONE... or picked from the
Shift + right-click menu, for the next point only."""
from __future__ import annotations

import math


def _window(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document()
    msp = win.document.modelspace()
    msp.add_circle((50, 0), 10)
    msp.add_line((0, 40), (20, 40))
    win.tools._invalidate_geometry()
    return win


def _line_ends(win):
    return [(e.dxf.start, e.dxf.end) for e in win.document.modelspace()
            if e.dxftype() == "LINE"]


def _tangent_hover_point():
    # from (0, 0), the upper tangent to the circle: cursor near it
    angle = math.asin(10 / 50)
    t = (math.cos(angle) * math.sqrt(50 ** 2 - 10 ** 2),)
    return (t[0] * math.cos(angle), t[0] * math.sin(angle))


def test_typed_tangent_snaps_the_next_point_only(qapp):
    win = _window(qapp)
    tools = win.tools
    try:
        assert "TAN" not in tools.osnap_modes          # not a running mode
        win._on_command_submitted("LINE")
        win._on_command_submitted("0,0")
        hx, hy = _tangent_hover_point()
        tools.on_hover(hx + 0.3, hy + 0.3, threshold_world=3.0)
        assert tools.snap_hit is None or tools.snap_hit.kind != "TAN"
        win._on_command_submitted("TAN")
        assert tools.osnap_override == frozenset({"TAN"})
        tools.on_hover(hx + 0.3, hy + 0.3, threshold_world=3.0)
        assert tools.snap_hit is not None and tools.snap_hit.kind == "TAN"
        tools.on_click(hx + 0.3, hy + 0.3)
        assert tools.osnap_override is None            # one point only
        start, end = next(se for se in _line_ends(win)
                          if se[0].isclose((0, 0, 0)))
        # really tangent: the circle's centre is one radius from the line
        dx, dy = end.x - start.x, end.y - start.y
        dist = abs(dx * (0 - start.y) - dy * (50 - start.x)) / math.hypot(dx, dy)
        assert dist == __import__("pytest").approx(10, abs=1e-9)
        tools.on_hover(hx + 0.3, hy + 0.3, threshold_world=3.0)
        assert tools.snap_hit is None or tools.snap_hit.kind != "TAN"
    finally:
        tools.cancel()
        win.document.dirty = False
        win.close()


def test_typed_none_turns_the_running_snaps_off_for_one_point(qapp):
    win = _window(qapp)
    tools = win.tools
    try:
        win._on_command_submitted("LINE")
        tools.on_hover(20.4, 40.3, threshold_world=3.0)
        assert tools.snap_hit is not None and tools.snap_hit.kind == "END"
        win._on_command_submitted("NONE")
        tools.on_hover(20.4, 40.3, threshold_world=3.0)
        assert tools.snap_hit is None
        tools.on_click(20.4, 40.3)                     # the raw point
        assert tools.tool.last_point == (20.4, 40.3)
        tools.on_hover(20.4, 40.3, threshold_world=3.0)
        assert tools.snap_hit is not None              # running snaps are back
    finally:
        tools.cancel()
        win.document.dirty = False
        win.close()


def test_override_words_are_read_like_autocad():
    from core.osnap import override_from_text as read

    assert read("TAN") == read("tang") == read("TANGENT") == {"TAN"}
    assert read("_endp") == {"END"}
    assert read("NON") == read("NONE") == frozenset()
    assert read("C") is None and read("ANGLE") is None


def test_shift_right_click_opens_the_snap_menu_for_one_point(qapp):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    win = _window(qapp)
    tools = win.tools
    try:
        win._on_command_submitted("LINE")
        vp = win.viewport
        QTest.mouseClick(vp, Qt.RightButton, Qt.ShiftModifier,
                         QPoint(vp.width() // 2, vp.height() // 2))
        menu = win._osnap_menu
        menu_actions = menu.actions()
        labels = [a.text() for a in menu_actions]
        assert "Tangent" in labels and "None" in labels
        assert tools.active()                  # not taken as Enter
        next(a for a in menu_actions if a.text() == "Tangent").trigger()
        assert tools.osnap_override == frozenset({"TAN"})
        menu.close()
        # without Shift, right-click stays Enter: no snap menu
        win._osnap_menu = None
        QTest.mouseClick(vp, Qt.RightButton, Qt.NoModifier,
                         QPoint(vp.width() // 2, vp.height() // 2))
        assert win._osnap_menu is None
    finally:
        tools.cancel()
        win.document.dirty = False
        win.close()
