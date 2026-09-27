# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Arcs with an inverted OCS, and MIRROR (issues #10 and #17).

An ARC with extrusion (0, 0, -1) stores its centre with X negated and its
angles mirrored. The renderer honours that; the pick index and the snap
engine used to read the raw attributes, so a mirrored arc showed in one
place and could only be "found" on the other side of the axis.
"""
from __future__ import annotations

import math

import ezdxf
import pytest

from core import actions, ocs
from core.commands import History
from core.document import Document
from core.select import GeometryIndex
from core.snap import SnapEngine


def _wcs_point(arc, angle_deg):
    """A point of the arc in WCS, computed through ezdxf's own OCS."""
    c, r = arc.dxf.center, arc.dxf.radius
    a = math.radians(angle_deg)
    p = arc.ocs().to_wcs((c.x + r * math.cos(a), c.y + r * math.sin(a), c.z))
    return (p.x, p.y)


def _flipped_arc_doc():
    """A quarter arc centred at WCS (25, 20), r 25, from 90° to 180° —
    written the way a mirror leaves it: OCS centre (-25, 20), extrusion -Z."""
    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    arc = msp.add_arc((-25, 20), 25, 0, 90,
                      dxfattribs={"extrusion": (0, 0, -1)})
    return Document(doc), arc


def test_arc_wcs_matches_ezdxf_ocs():
    _, arc = _flipped_arc_doc()
    cx, cy, r, a0, a1 = ocs.arc_wcs(arc)
    assert (cx, cy, r) == pytest.approx((25.0, 20.0, 25.0))
    # the ccw run in WCS: its two ends are the OCS ends, swapped
    start = (cx + r * math.cos(math.radians(a0)), cy + r * math.sin(math.radians(a0)))
    end = (cx + r * math.cos(math.radians(a1)), cy + r * math.sin(math.radians(a1)))
    assert start == pytest.approx(_wcs_point(arc, 90.0), abs=1e-9)
    assert end == pytest.approx(_wcs_point(arc, 0.0), abs=1e-9)
    assert (a0, a1) == pytest.approx((90.0, 180.0))


def test_a_flipped_arc_is_picked_where_it_is_drawn():
    document, arc = _flipped_arc_doc()
    index = GeometryIndex(document)
    mid = _wcs_point(arc, 45.0)
    assert index.pick(mid, tolerance=0.5) == arc.dxf.handle
    # and NOT at its raw OCS position, where nothing is drawn
    assert index.pick((-mid[0], mid[1]), tolerance=0.5) is None


def test_window_takes_an_arc_by_its_own_extent_not_its_circle():
    document, arc = _flipped_arc_doc()
    index = GeometryIndex(document)
    # the arc spans x 0..25, y 20..45: this window holds it, not its circle
    assert index.window((-1, 19, 26, 46)) == [arc.dxf.handle]
    assert index.window((1, 19, 26, 46)) == []


def test_crossing_ignores_the_part_of_the_circle_the_arc_lacks():
    # issue #17: the crossing test used the arc's whole circle, so a
    # rectangle over the missing part selected an arc drawn elsewhere
    doc = ezdxf.new("R2018")
    arc = doc.modelspace().add_arc((0, 0), 10, 0, 90)
    index = GeometryIndex(Document(doc))
    # (-10, 0) is on the circle but not on the 0°..90° arc
    assert index.crossing((-11, -1, -9, 1)) == []
    # the arc's end at (10, 0) is
    assert index.crossing((9, -1, 11, 1)) == [arc.dxf.handle]
    # and a rect the arc crosses without an end inside
    assert index.crossing((6, 6, 8, 8)) == [arc.dxf.handle]


def test_snap_finds_the_ends_and_centre_of_a_flipped_arc():
    document, arc = _flipped_arc_doc()
    engine = SnapEngine(document)
    hit = engine.find((0.3, 20.2), 1.0, kinds=frozenset({"END"}))
    assert hit is not None and (hit.x, hit.y) == pytest.approx((0.0, 20.0))
    hit = engine.find((25.3, 20.2), 1.0, kinds=frozenset({"CEN"}))
    assert hit is not None and (hit.x, hit.y) == pytest.approx((25.0, 20.0))


def _mirror_doc():
    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    arc = msp.add_arc((-25, 20), 25, 0, 90)
    circle = msp.add_circle((-10, 5), 3)
    poly = msp.add_lwpolyline([(-5, 0, 0.5), (-1, 0, 0), (-1, 4, 0)],
                              format="xyb")
    return Document(doc), [arc, circle, poly]


@pytest.mark.parametrize("keep_source", [True, False])
def test_mirror_leaves_the_normal_up_and_undo_is_exact(keep_source):
    document, sources = _mirror_doc()
    before = [e.dxf.all_existing_dxf_attribs() | {"pts": _pts(e)}
              for e in sources]
    history = History(document)
    cmd = actions.mirror_entities(sources, (0, 0), (0, 10), keep_source)
    history.execute(cmd)
    results = cmd.copies if keep_source else sources
    assert all(ocs.kind(e) == "up" for e in results)
    # geometry mirrored about x = 0
    arc = results[0]
    assert (arc.dxf.center.x, arc.dxf.center.y) == pytest.approx((25.0, 20.0))
    # a mirror reverses the sweep: the ccw start is the mirrored END
    assert _wcs_point(arc, arc.dxf.start_angle) == pytest.approx((25.0, 45.0), abs=1e-9)
    assert _wcs_point(arc, arc.dxf.end_angle) == pytest.approx((0.0, 20.0), abs=1e-9)
    # the mirrored arc is where the index looks for it
    index = GeometryIndex(document)
    assert index.pick(_wcs_point(arc, 135.0), tolerance=0.5) == arc.dxf.handle

    history.undo()
    after = [e.dxf.all_existing_dxf_attribs() | {"pts": _pts(e)}
             for e in sources]
    for b, a in zip(before, after):
        assert b.keys() == a.keys()
        for key in b:
            assert _close(b[key], a[key]), key
    history.redo()
    results = cmd.copies if keep_source else sources
    assert all(ocs.kind(e) == "up" for e in results)


def _pts(e):
    return list(e.get_points("xyb")) if e.dxftype() == "LWPOLYLINE" else None


def _close(a, b):
    if isinstance(a, (list, tuple)) or hasattr(a, "__iter__") and not isinstance(a, str):
        a, b = list(a), list(b)
        return len(a) == len(b) and all(_close(x, y) for x, y in zip(a, b))
    if isinstance(a, float) or isinstance(b, float):
        return math.isclose(a, b, abs_tol=1e-9)
    return a == b


# -- editing an inverted-OCS entity from another CAD -----------------------------
# One drawing in five of the real corpus carries some (61 of 327 sampled):
# once they became pickable where they are drawn, every tool that reads
# their geometry had to read it in WCS too, or it would edit a ghost.

from core.modify import break_pieces, stretch_entities          # noqa: E402
from core.select import apply_grip_edit, entity_grips           # noqa: E402
from tests.test_editing import Harness                           # noqa: E402
from tools.edit import OffsetTool, TrimTool                      # noqa: E402


def _flipped_circle(msp, center_wcs, r):
    return msp.add_circle((-center_wcs[0], center_wcs[1]), r,
                          dxfattribs={"extrusion": (0, 0, -1)})


def test_trim_a_flipped_circle_between_two_lines():
    h = Harness()
    circle = _flipped_circle(h.msp, (20, 0), 10)      # drawn at WCS (20, 0)
    h.msp.add_line((20, -20), (20, 20))               # both cut it at x = 20
    h.msp.add_line((0, 0), (40, 0))
    h.services.index.invalidate()
    tool = TrimTool(h.ctx)
    tool.start()
    tool.on_selection([])
    tool.on_point((20 + 10 * math.cos(math.radians(45)),
                   10 * math.sin(math.radians(45))))  # the NE quarter
    arcs = h.msp.query("ARC")
    assert len(arcs) == 1 and not h.msp.query("CIRCLE")
    cx, cy, r, a0, a1 = ocs.arc_wcs(arcs[0])
    assert (cx, cy, r) == pytest.approx((20.0, 0.0, 10.0))
    assert ((a1 - a0) % 360) == pytest.approx(270.0)
    assert circle.dxf.handle not in [e.dxf.handle for e in h.msp]


def test_offset_a_flipped_arc_lands_beside_it():
    h = Harness()
    arc = h.msp.add_arc((-25, 20), 25, 0, 90,
                        dxfattribs={"extrusion": (0, 0, -1)})
    h.services.index.invalidate()
    tool = OffsetTool(h.ctx)
    tool.start()
    assert tool.on_option("5")
    tool.on_point(_wcs_point(arc, 45.0))
    tool.on_point((25.0, 20.0))                        # toward the centre
    new = [a for a in h.msp.query("ARC") if a is not arc]
    assert len(new) == 1
    cx, cy, r, a0, a1 = ocs.arc_wcs(new[0])
    assert (cx, cy, r) == pytest.approx((25.0, 20.0, 20.0))
    assert (a0, a1) == pytest.approx((90.0, 180.0))


def test_grips_of_a_flipped_arc_sit_on_it_and_edit_it():
    doc = ezdxf.new("R2018")
    arc = doc.modelspace().add_arc((-25, 20), 25, 0, 90,
                                   dxfattribs={"extrusion": (0, 0, -1)})
    grips = entity_grips(arc)
    points = [(round(x, 6), round(y, 6)) for x, y, _role in grips]
    assert points[0] == (25.0, 20.0)                  # centre
    assert (0.0, 20.0) in points and (25.0, 45.0) in points
    mid = next(g for g in grips if g[2] == "mid")
    assert (mid[0], mid[1]) == pytest.approx(_wcs_point(arc, 45.0))
    # drag the centre: the arc moves by the drag, in WCS
    assert apply_grip_edit(arc, 0, "center", (30.0, 20.0)) is not False
    assert tuple(ocs.center_wcs(arc)) == pytest.approx((30.0, 20.0))


def test_arc_mid_grip_across_zero_degrees():
    doc = ezdxf.new("R2018")
    arc = doc.modelspace().add_arc((0, 0), 10, 350, 10)
    mid = next(g for g in entity_grips(arc) if g[2] == "mid")
    assert (mid[0], mid[1]) == pytest.approx((10.0, 0.0))


def test_break_and_stretch_read_a_flipped_arc_in_wcs():
    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    arc = msp.add_arc((-25, 20), 25, 0, 90,
                      dxfattribs={"extrusion": (0, 0, -1)})
    pieces = break_pieces(arc, _wcs_point(arc, 30.0), _wcs_point(arc, 60.0))
    assert len(pieces) == 2
    for _kind, center, radius, _a0, _a1 in pieces:
        assert center == pytest.approx((25.0, 20.0)) and radius == 25.0

    document = Document(doc)
    history = History(document)
    before = arc.dxf.all_existing_dxf_attribs()
    # catch only the WCS end at (0, 20) and pull it 2 left
    history.execute(stretch_entities([arc], [(-1, 19, 1, 21)], -2.0, 0.0))
    ends = [(round(x, 6), round(y, 6)) for x, y, role in entity_grips(arc)
            if role == "end"]
    assert (-2.0, 20.0) in ends and (25.0, 45.0) in ends
    history.undo()
    assert arc.dxf.all_existing_dxf_attribs() == before
