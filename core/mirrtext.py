# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""MIRRTEXT = 0: MIRROR moves text where the mirror puts it, readable.

AutoCAD: "By default, when you mirror a text object, the direction of the
text is not changed" (MIRROR; MIRRTEXT, initial value 0, saved in the
drawing). ezdxf's transform() writes mirror writing instead -- a (0, 0, -1)
extrusion -- which is MIRRTEXT = 1.

The mirrored text fills the rectangle the mirror-written one would, reading
the right way. Of the two readable ways to fill it, the one kept is the one
whose baseline turns least from the original: a vertical mirror line
reverses the reading direction (so left and right justification trade
places), a horizontal one turns the text over (so it moves by its height
instead of standing on its head).
"""
from __future__ import annotations

import math

from ezdxf.math import Vec3

from core import ocs

#: What MIRRTEXT governs: text, attribute definitions and the variable
#: attributes of a block reference (INSERT is handled through its attribs).
TEXT_TYPES = frozenset({"TEXT", "ATTRIB", "ATTDEF", "MTEXT"})

_LEFT, _CENTER, _RIGHT, _ALIGNED, _MIDDLE, _FIT = range(6)
_BASELINE, _BOTTOM, _VMIDDLE, _TOP = range(4)


def keeps_text_readable(document) -> bool:
    """MIRRTEXT from the drawing's header; 0 (readable) when it is absent."""
    try:
        return int(document.doc.header.get("$MIRRTEXT", 0)) == 0
    except (TypeError, ValueError):
        return True


def make_readable(entity, before, matrix) -> None:
    """Rewrite ``entity`` -- ``before`` after ``matrix`` -- as readable text.

    ``before`` is the entity as it was before the mirror. Text that was not
    lying in the plan (a tilted extrusion) keeps ezdxf's answer.
    """
    if before.dxftype() not in TEXT_TYPES or ocs.kind(before) != "up":
        return
    if before.dxftype() == "MTEXT":
        _mtext(entity, before, matrix)
    else:
        _text(entity, before, matrix)


def _frame(rotation_deg: float, matrix):
    """(baseline, up, reversed): the readable frame after ``matrix``."""
    angle = math.radians(rotation_deg)
    u = Vec3(math.cos(angle), math.sin(angle), 0)
    v = Vec3(-math.sin(angle), math.cos(angle), 0)
    ru = matrix.transform_direction(u).normalize()
    rv = matrix.transform_direction(v).normalize()
    if ru.dot(u) > 1e-9:
        return ru, -rv, False          # turned over: same reading direction
    return -ru, rv, True               # reading direction reversed


def _text(entity, before, matrix) -> None:
    dxf = before.dxf
    height = float(dxf.get("height", 1.0))
    halign = int(dxf.get("halign", _LEFT))
    valign = int(dxf.get("valign", _BASELINE))
    rotation = float(dxf.get("rotation", 0.0))
    two_points = halign in (_ALIGNED, _FIT) and dxf.hasattr("align_point")
    if two_points:
        # the baseline runs between the two points, whatever rotation says
        run = Vec3(dxf.align_point) - Vec3(dxf.insert)
        rotation = math.degrees(math.atan2(run.y, run.x))
    baseline, up, reversed_ = _frame(rotation, matrix)
    insert = matrix.transform(Vec3(dxf.insert))
    align = (matrix.transform(Vec3(dxf.align_point))
             if dxf.hasattr("align_point") else insert)

    entity.dxf.discard("extrusion")
    entity.dxf.rotation = math.degrees(math.atan2(baseline.y, baseline.x)) % 360
    if halign in (_ALIGNED, _FIT):
        # two points on the baseline: the text runs from the first to the
        # second, so reversing means swapping them
        if reversed_:
            insert, align = align, insert
        else:
            cap, descender = _metrics(before, height)
            if halign == _ALIGNED:
                # ALIGNED scales the whole text to fit between the points
                scale = _aligned_scale(before)
                cap, descender = cap * scale, descender * scale
            shift = up * (descender - cap)
            insert, align = insert + shift, align + shift
        entity.dxf.insert = insert
        entity.dxf.align_point = align
        return
    anchor = insert if (halign, valign) == (_LEFT, _BASELINE) else align
    if reversed_:
        halign = {_LEFT: _RIGHT, _RIGHT: _LEFT}.get(halign, halign)
    else:
        # Turned over: the box [baseline - descender, baseline + cap] comes
        # back as [baseline - cap, baseline + descender], so the baseline
        # moves by cap - descender and the anchor keeps its place in the box.
        cap, descender = _metrics(before, height)
        level = (cap / 2 if halign == _MIDDLE else
                 {_BASELINE: 0.0, _BOTTOM: -descender, _VMIDDLE: cap / 2,
                  _TOP: cap}[valign])
        anchor = anchor + up * (2 * level - cap + descender)
    entity.dxf.halign = halign
    entity.dxf.valign = valign
    entity.dxf.insert = anchor
    if (halign, valign) == (_LEFT, _BASELINE):
        entity.dxf.discard("align_point")
    else:
        entity.dxf.align_point = anchor


def _aligned_scale(text) -> float:
    """How much ALIGNED scales the text to span its two points."""
    try:
        from ezdxf.tools.text_size import text_size

        width = text_size(text).width
        span = (Vec3(text.dxf.align_point) - Vec3(text.dxf.insert)).magnitude
        return span / width if width > 1e-12 else 1.0
    except Exception:  # noqa: BLE001
        return 1.0


def _metrics(text, height: float) -> tuple[float, float]:
    """(cap height, descender) of a one-line text, as ezdxf draws it."""
    try:
        from ezdxf.tools.text_size import text_size

        size = text_size(text)
        return size.cap_height, max(0.0, size.total_height - size.cap_height)
    except Exception:  # noqa: BLE001 -- no font: the cap box alone
        return height, 0.0


def _mtext(entity, before, matrix) -> None:
    baseline, _up, reversed_ = _frame(before.get_rotation(), matrix)
    point = int(before.dxf.get("attachment_point", 1))
    row, col = divmod(point - 1, 3)
    if reversed_:
        col = 2 - col
    else:
        row = 2 - row
    entity.dxf.discard("extrusion")
    entity.dxf.discard("rotation")
    entity.dxf.insert = matrix.transform(Vec3(before.dxf.insert))
    entity.dxf.text_direction = Vec3(baseline.x, baseline.y, 0)
    entity.dxf.attachment_point = row * 3 + col + 1
