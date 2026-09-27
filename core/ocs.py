# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Plan-view geometry of OCS entities, in one place.

CIRCLE, ARC, LWPOLYLINE and 2D POLYLINE store their coordinates in the
entity's Object Coordinate System, defined by its extrusion. In plan the
two common cases are:

- extrusion (0, 0, 1): OCS = WCS, the raw attributes are the drawing;
- extrusion (0, 0, -1): the arbitrary-axis algorithm gives the OCS X axis
  as WCS -X, so the drawing is the raw attributes with X negated and every
  angle mirrored (180 - a) — and an arc's sweep runs the other way.

The second one is not exotic: other CADs write it for mirrored arcs, and
ezdxf's own ``transform()`` produces it for a mirror matrix. The renderer
honours the OCS, so readers that take ``dxf.center`` at face value put the
entity somewhere it isn't drawn — the "ghost" arcs of issue #10.

Anything else (a tilted extrusion) is not a circle in plan at all; callers
trace those with ``ezdxf.path``, which handles the full OCS.
"""
from __future__ import annotations

import math

_TOL = 1e-9

#: The entities ``upright`` flips (ezdxf.upright's list) that a mirror
#: matrix turns upside down. INSERT is on ezdxf's list but a mirrored
#: insert comes out +Z already (negative scale), so it never needs it.
OCS_TYPES = frozenset({"CIRCLE", "ARC", "ELLIPSE", "LWPOLYLINE", "POLYLINE",
                       "SOLID", "TRACE", "HATCH", "MPOLYGON"})


def _extrusion(entity):
    try:
        ext = entity.dxf.get("extrusion")
    except Exception:
        return None
    return ext


def kind(entity) -> str:
    """'up' (+Z or none), 'flipped' (-Z) or 'tilted'."""
    ext = _extrusion(entity)
    if ext is None:
        return "up"
    x, y, z = float(ext[0]), float(ext[1]), float(ext[2])
    length = math.sqrt(x * x + y * y + z * z) or 1.0
    x, y, z = x / length, y / length, z / length
    if abs(x) < _TOL and abs(y) < _TOL:
        return "up" if z > 0 else "flipped"
    return "tilted"


def is_planar(entity) -> bool:
    """True when the plan view of the entity is its own 2D geometry."""
    return kind(entity) != "tilted"


def circle_wcs(entity) -> tuple[float, float, float]:
    """(cx, cy, r) in WCS for a CIRCLE or ARC that is planar."""
    c = entity.dxf.center
    r = float(entity.dxf.radius)
    if kind(entity) == "flipped":
        return (-c.x, c.y, r)
    return (c.x, c.y, r)


def center_wcs(entity):
    """The centre of a planar CIRCLE/ARC as a Vec2 in WCS."""
    from ezdxf.math import Vec2

    cx, cy, _r = circle_wcs(entity)
    return Vec2(cx, cy)


def angles_wcs(entity) -> tuple[float, float]:
    """(start_deg, end_deg) of a planar ARC in WCS, counter-clockwise."""
    return arc_wcs(entity)[3:]


def arc_wcs(entity) -> tuple[float, float, float, float, float]:
    """(cx, cy, r, start_deg, end_deg) in WCS, counter-clockwise."""
    cx, cy, r = circle_wcs(entity)
    a0 = float(entity.dxf.start_angle)
    a1 = float(entity.dxf.end_angle)
    if kind(entity) == "flipped":
        # X negated: angle a becomes 180 - a, and the ccw run from a0 to a1
        # becomes a clockwise run — read ccw, it goes from 180-a1 to 180-a0.
        a0, a1 = (180.0 - a1) % 360.0, (180.0 - a0) % 360.0
    return (cx, cy, r, a0, a1)


def bulge_vertices_wcs(entity, vertices):
    """[(x, y, bulge), ...] OCS vertices -> WCS for a planar polyline."""
    if kind(entity) != "flipped":
        return list(vertices)
    return [(-x, y, -b) for x, y, b in vertices]


def rows_wcs(entity, rows):
    """[(x, y, start_width, end_width, bulge), ...] OCS -> WCS."""
    if kind(entity) != "flipped":
        return list(rows)
    return [(-x, y, sw, ew, -b) for x, y, sw, ew, b in rows]


def points_wcs(entity, points):
    """[(x, y), ...] OCS points -> WCS for a planar polyline."""
    if kind(entity) != "flipped":
        return list(points)
    return [(-p[0], p[1]) for p in points]


def upright(entity) -> bool:
    """Flip a (0, 0, -1) entity to (0, 0, 1) in place, same geometry.

    What AutoCAD's MIRROR leaves behind: the normal of a plan drawing never
    points down. Returns True if the entity changed.
    """
    if kind(entity) != "flipped":
        return False
    from ezdxf.upright import upright as _upright

    _upright(entity)
    return kind(entity) == "up"
