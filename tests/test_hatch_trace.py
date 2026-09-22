# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""HATCH's Pick-internal-point on drawings made of LINEs and ARCs.

A tester: "al momento de dibujar el HATCH no detecta las islas". The
detector only knew closed OBJECTS (a closed polyline, a circle); a wall
section drawn as four lines, or an island drawn as four lines, was invisible
to it -- "No closed boundary found" where AutoCAD fills. The region is now
traced from every curve in view, cut at the crossings, the way BPOLY does.
"""
from __future__ import annotations

import math
import random
import time

import ezdxf
import pytest

from core.hatch_boundary import region_at_point
from core.hatch_trace import signed_area, trace_region


def _msp():
    doc = ezdxf.new()
    return doc, doc.modelspace()


def _lines(msp, *segments):
    for a, b in segments:
        msp.add_line(a, b)


def _area(poly) -> float:
    return abs(signed_area(poly))


def test_a_rectangle_of_four_lines_with_overshoots_is_a_boundary():
    """Drafters overshoot corners; the crossings cut the lines and the dead
    ends fall away, leaving the 100 x 60 room."""
    doc, msp = _msp()
    _lines(msp, ((-5, 0), (105, 0)), ((100, -5), (100, 65)),
           ((105, 60), (-5, 60)), ((0, 65), (0, -5)))
    outer, islands = trace_region(list(msp), (10, 10))
    assert _area(outer) == pytest.approx(6000.0)
    assert islands == []
    assert trace_region(list(msp), (200, 200)) is None   # outside: nothing


def test_islands_drawn_with_lines_a_circle_and_a_text_are_holes():
    doc, msp = _msp()
    _lines(msp, ((0, 0), (100, 0)), ((100, 0), (100, 60)),
           ((100, 60), (0, 60)), ((0, 60), (0, 0)),
           ((20, 20), (40, 20)), ((40, 20), (40, 40)),
           ((40, 40), (20, 40)), ((20, 40), (20, 20)))
    msp.add_circle((70, 30), 8)
    msp.add_text("SALA", dxfattribs={"height": 3}).set_placement((50, 50))
    outer, islands = trace_region(list(msp), (10, 10))
    assert _area(outer) == pytest.approx(6000.0)
    areas = sorted(_area(i) for i in islands)
    assert len(areas) == 3
    assert any(a == pytest.approx(400.0) for a in areas)            # the line square
    assert any(a == pytest.approx(math.pi * 64, rel=0.01) for a in areas)  # the circle
    assert min(areas) > 0                                           # the text's box
    # picking inside the island hatches the island itself, with no holes
    inner, holes = trace_region(list(msp), (30, 30))
    assert _area(inner) == pytest.approx(400.0) and holes == []


def test_two_rooms_sharing_a_wall_hatch_separately():
    doc, msp = _msp()
    _lines(msp, ((0, 0), (100, 0)), ((100, 0), (100, 50)), ((100, 50), (0, 50)),
           ((0, 50), (0, 0)), ((50, 0), (50, 50)))
    left, _ = trace_region(list(msp), (25, 25))
    right, _ = trace_region(list(msp), (75, 25))
    assert _area(left) == pytest.approx(2500.0)
    assert _area(right) == pytest.approx(2500.0)
    assert all(x <= 50.0 + 1e-9 for x, _y in left)
    assert all(x >= 50.0 - 1e-9 for x, _y in right)


def test_a_gap_in_the_boundary_is_no_boundary():
    """HPGAPTOL 0: an open region is not filled (AutoCAD says so too)."""
    doc, msp = _msp()
    _lines(msp, ((0, 0), (100, 0)), ((100, 0), (100, 50)), ((100, 50), (0, 50)),
           ((0, 50), (0, 2)))
    assert trace_region(list(msp), (25, 25)) is None


def test_a_line_and_an_arc_close_a_region():
    doc, msp = _msp()
    msp.add_line((0, -10), (0, 10))
    msp.add_arc((0, 0), 10, -90, 90)
    outer, _ = trace_region(list(msp), (3, 0))
    assert _area(outer) == pytest.approx(math.pi * 100 / 2, rel=0.01)


def test_nested_islands_are_all_listed_for_the_even_odd_fill():
    doc, msp = _msp()
    msp.add_lwpolyline([(0, 0), (100, 0), (100, 100), (0, 100)], close=True)
    msp.add_circle((50, 50), 30)
    msp.add_lwpolyline([(45, 45), (55, 45), (55, 55), (45, 55)], close=True)
    outer, islands = trace_region(list(msp), (5, 5))
    assert _area(outer) == pytest.approx(10000.0)
    assert sorted(round(_area(i)) for i in islands) == [100, 2827]


def test_region_at_point_traces_first_and_keeps_the_closed_object_rule():
    """The public entry: a closed polyline still answers (the old rule),
    and lines answer now; the window limits the boundary set."""
    doc, msp = _msp()
    msp.add_lwpolyline([(0, 0), (20, 0), (20, 20), (0, 20)], close=True)
    _lines(msp, ((200, 0), (300, 0)), ((300, 0), (300, 50)),
           ((300, 50), (200, 50)), ((200, 50), (200, 0)))
    outer, _ = region_at_point(list(msp), (10, 10))
    assert _area(outer) == pytest.approx(400.0)
    outer, _ = region_at_point(list(msp), (250, 25))
    assert _area(outer) == pytest.approx(5000.0)
    # the lines are out of the window: the point is enclosed by nothing
    assert region_at_point(list(msp), (250, 25), window=(0, 0, 100, 100)) is None
    # an entity partly in view is in whole (AutoCAD's current-viewport set):
    # a diamond whose four edges cross a window that holds none of its corners
    _lines(msp, ((500, -50), (600, 25)), ((600, 25), (500, 100)),
           ((500, 100), (400, 25)), ((400, 25), (500, -50)))
    outer, _ = region_at_point(list(msp), (500, 25), window=(450, 0, 550, 50))
    assert _area(outer) == pytest.approx(200 * 150 / 2)


def test_the_hatch_tool_fills_a_room_drawn_with_lines(qapp):
    """End to end through the real controller: HATCH, pick inside a room
    of four lines, Enter -- a HATCH with the room as its path."""
    from core import actions
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        win.new_document()
        t = win.tools
        for a, b in (((0, 0), (100, 0)), ((100, 0), (100, 60)),
                     ((100, 60), (0, 60)), ((0, 60), (0, 0)),
                     ((20, 20), (40, 20)), ((40, 20), (40, 40)),
                     ((40, 40), (20, 40)), ((20, 40), (20, 20))):
            t._execute(actions.add_line(a, b))
        # offscreen the canvas is 100 x 30 px and never lays out: give the
        # view a real size and aim it at the room, so "what the canvas
        # shows" (the boundary set) holds every wall
        view = win.viewport.view
        view.width, view.height = 800, 600
        view.cx, view.cy, view.scale = 50.0, 30.0, 5.0
        region = t.hatch_region_at((10, 10))
        assert region is not None
        outer, islands = region
        assert _area(outer) == pytest.approx(6000.0)
        assert [round(_area(i)) for i in islands] == [400]
    finally:
        win.close()


def test_three_thousand_random_segments_answer_fast():
    random.seed(3)
    doc, msp = _msp()
    for _ in range(3000):
        x, y = random.uniform(0, 1000), random.uniform(0, 1000)
        a, length = random.uniform(0, math.tau), random.uniform(5, 60)
        msp.add_line((x, y), (x + length * math.cos(a), y + length * math.sin(a)))
    t0 = time.perf_counter()
    trace_region(list(msp), (500, 500))
    assert time.perf_counter() - t0 < 2.0
