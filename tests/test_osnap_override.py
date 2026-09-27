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


def _dist_to_line(p, a, b):
    dx, dy = b.x - a.x, b.y - a.y
    return abs(dx * (p[1] - a.y) - dy * (p[0] - a.x)) / math.hypot(dx, dy)


def test_line_tangent_to_two_circles_uses_deferred_tangents(qapp):
    """#19: the first TAN has no point to be tangent from -- AutoCAD defers
    it and solves both touch points once the second circle is picked."""
    import pytest

    win = _window(qapp)
    tools = win.tools
    win.document.modelspace().add_circle((100, 30), 5)
    tools._invalidate_geometry()
    try:
        before = len(_line_ends(win))
        win._on_command_submitted("LINE")
        win._on_command_submitted("TAN")
        tools.on_hover(50, 10.2, threshold_world=2.0)
        assert tools.snap_hit is not None and tools.snap_hit.kind == "DTAN"
        tools.on_click(50, 10.2)
        assert len(_line_ends(win)) == before           # nothing drawn yet
        win._on_command_submitted("TAN")
        tools.on_hover(100, 35.2, threshold_world=2.0)
        assert tools.snap_hit.kind == "DTAN"
        tools.on_click(100, 35.2)
        lines = _line_ends(win)
        assert len(lines) == before + 1
        a, b = lines[-1]
        assert _dist_to_line((50, 0), a, b) == pytest.approx(10, abs=1e-9)
        assert _dist_to_line((100, 30), a, b) == pytest.approx(5, abs=1e-9)
        assert a.y > 0 and b.y > 30                    # the upper outer one
    finally:
        tools.cancel()
        win.document.dirty = False
        win.close()


def test_deferred_tangent_then_a_point(qapp):
    import pytest

    win = _window(qapp)
    tools = win.tools
    try:
        win._on_command_submitted("LINE")
        win._on_command_submitted("TAN")
        tools.on_hover(50, 10.2, threshold_world=2.0)
        tools.on_click(50, 10.2)
        before = len(_line_ends(win))
        win._on_command_submitted("0,40")
        a, b = _line_ends(win)[before]
        assert (b.x, b.y) == pytest.approx((0, 40))
        assert _dist_to_line((50, 0), a, b) == pytest.approx(10, abs=1e-9)
        assert a.y > 5                                  # the touch near the pick
    finally:
        tools.cancel()
        win.document.dirty = False
        win.close()


def test_circle_tan_tan_tan_from_the_draw_menu(qapp):
    """#13: Draw > Circle > Tan, Tan, Tan -- here the incircle of a
    30-40-50 triangle, picked on its three sides."""
    import pytest

    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document()
    msp = win.document.modelspace()
    for a, b in (((0, 0), (30, 0)), ((30, 0), (0, 40)), ((0, 40), (0, 0))):
        msp.add_line(a, b)
    win.tools._invalidate_geometry()
    tools = win.tools
    try:
        bar_actions = win._menu_bar.actions()
        draw = next(a for a in bar_actions
                    if a.text().replace("&", "") == "Draw").menu()
        draw_actions = draw.actions()
        circle = next(a for a in draw_actions
                      if a.text().replace("&", "") == "Circle").menu()
        circle_actions = circle.actions()
        next(a for a in circle_actions if a.text() == "Tan, Tan, Tan").trigger()
        for pick in ((12, 0), (15, 20), (0, 12)):
            tools.on_click(*pick)
        made = [e for e in msp if e.dxftype() == "CIRCLE"]
        assert len(made) == 1
        c = made[0]
        assert (c.dxf.center.x, c.dxf.center.y) == pytest.approx((10, 10))
        assert c.dxf.radius == pytest.approx(10)
    finally:
        tools.cancel()
        win.document.dirty = False
        win.close()


def test_three_circles_inside_or_around_by_the_picks():
    import pytest

    from core import actions

    c1, c2, c3 = (("circle", (0, 0), 5), ("circle", (30, 0), 5),
                  ("circle", (15, 25), 5))
    center, r = actions.ttt_circle([(c1, (4, 3)), (c2, (26, 3)),
                                    (c3, (15, 20))])
    assert center == pytest.approx((15, 8)) and r == pytest.approx(12)
    center, r = actions.ttt_circle([(c1, (-4, -3)), (c2, (34, -3)),
                                    (c3, (15, 30))])
    assert center == pytest.approx((15, 8)) and r == pytest.approx(22)


def test_circle_center_diameter_from_the_draw_menu(qapp):
    import pytest

    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document()
    tools = win.tools
    try:
        bar_actions = win._menu_bar.actions()
        draw = next(a for a in bar_actions
                    if a.text().replace("&", "") == "Draw").menu()
        draw_actions = draw.actions()
        circle = next(a for a in draw_actions
                      if a.text().replace("&", "") == "Circle").menu()
        circle_actions = circle.actions()
        next(a for a in circle_actions
             if a.text() == "Center, Diameter").trigger()
        win._on_command_submitted("50,50")
        win._on_command_submitted("20")               # a DIAMETER
        made = [e for e in win.document.modelspace() if e.dxftype() == "CIRCLE"]
        assert len(made) == 1 and made[0].dxf.radius == pytest.approx(10)
    finally:
        tools.cancel()
        win.document.dirty = False
        win.close()


def test_circle_3p_with_typed_tangents_is_tan_tan_tan(qapp):
    """What an AutoCAD user types: C, 3P, then TAN before each pick."""
    import pytest

    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document()
    msp = win.document.modelspace()
    for a, b in (((0, 0), (30, 0)), ((30, 0), (0, 40)), ((0, 40), (0, 0))):
        msp.add_line(a, b)
    win.tools._invalidate_geometry()
    tools = win.tools
    prompts = []
    real = tools._on_prompt
    tools._on_prompt = lambda text: (prompts.append(text), real(text))
    try:
        win._on_command_submitted("CIRCLE")
        win._on_command_submitted("3P")
        for pick in ((12, 0), (15, 20), (0, 12)):
            win._on_command_submitted("TAN")
            assert prompts[-1] == "to"                 # AutoCAD's answer
            tools.on_click(*pick)
        c = next(e for e in msp if e.dxftype() == "CIRCLE")
        assert (c.dxf.center.x, c.dxf.center.y) == pytest.approx((10, 10))
        assert c.dxf.radius == pytest.approx(10)
        # the menu entry runs the same macro, prompting "_tan to"
        prompts.clear()
        bar_actions = win._menu_bar.actions()
        draw = next(a for a in bar_actions
                    if a.text().replace("&", "") == "Draw").menu()
        draw_actions = draw.actions()
        circle = next(a for a in draw_actions
                      if a.text().replace("&", "") == "Circle").menu()
        circle_actions = circle.actions()
        next(a for a in circle_actions if a.text() == "Tan, Tan, Tan").trigger()
        assert prompts[-2:] == ["Specify first point on circle:", "_tan to"]
    finally:
        tools.cancel()
        win.document.dirty = False
        win.close()


def _line_with(win, *inputs):
    win._on_command_submitted("LINE")
    for text in inputs:
        win._on_command_submitted(text)
    return win.tools.tool


def test_from_offsets_the_next_point_from_a_base(qapp):
    """FROM (Command Modifier): Base point, then <Offset>."""
    import pytest

    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document()
    prompts = []
    real = win.tools._on_prompt
    win.tools._on_prompt = lambda text: (prompts.append(text), real(text))
    try:
        tool = _line_with(win, "FROM")
        assert prompts[-1] == "Base point:"
        win._on_command_submitted("10,10")
        assert prompts[-1] == "<Offset>:"
        win._on_command_submitted("@5,0")
        assert tool.last_point == pytest.approx((15, 10))
        # an absolute coordinate at <Offset> cancels FROM and is used as is
        win._on_command_submitted("FROM")
        win._on_command_submitted("100,100")
        win._on_command_submitted("3,4")
        assert tool.last_point == pytest.approx((3, 4))
    finally:
        win.tools.cancel()
        win.document.dirty = False
        win.close()


def test_m2p_takes_the_midpoint_of_two_points(qapp):
    import pytest

    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document()
    prompts = []
    real = win.tools._on_prompt
    win.tools._on_prompt = lambda text: (prompts.append(text), real(text))
    try:
        tool = _line_with(win, "M2P")
        assert prompts[-1] == "First point of mid:"
        win._on_command_submitted("0,0")
        assert prompts[-1] == "Second point of mid:"
        win.tools.on_click(10, 20)                # a pick works as well
        assert tool.last_point == pytest.approx((5, 10))
    finally:
        win.tools.cancel()
        win.document.dirty = False
        win.close()


def test_snap_menu_is_in_autocads_order(qapp):
    win = _window(qapp)
    try:
        win._on_command_submitted("LINE")
        menu = win.osnap_override_menu()
        labels = [a.text() for a in menu.actions() if not a.isSeparator()]
        assert labels[:3] == ["From", "Mid Between 2 Points", "Endpoint"]
        assert labels.index("Intersection") < labels.index("Center") \
            < labels.index("Tangent") < labels.index("Perpendicular") \
            < labels.index("Nearest") < labels.index("None")
    finally:
        win.tools.cancel()
        win.document.dirty = False
        win.close()
