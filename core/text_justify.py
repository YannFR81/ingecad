# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A TEXT's justification changed without moving the text (#77).

AutoCAD's Properties palette (and JUSTIFYTEXT) change which point of the
text is its alignment point; the letters stay where they are. ezdxf's
``set_placement`` moves the text instead, so the new alignment point is
worked out here from the text's own box: its width, cap height and
descender (ezdxf.tools.text_size), turned by its rotation.
"""
from __future__ import annotations

import math

#: AutoCAD's Justify list, in the Properties palette's order:
#: (label, ezdxf TextEntityAlignment name).
JUSTIFICATIONS = (
    ("Left", "LEFT"), ("Center", "CENTER"), ("Right", "RIGHT"),
    ("Aligned", "ALIGNED"), ("Middle", "MIDDLE"), ("Fit", "FIT"),
    ("Top left", "TOP_LEFT"), ("Top center", "TOP_CENTER"),
    ("Top right", "TOP_RIGHT"), ("Middle left", "MIDDLE_LEFT"),
    ("Middle center", "MIDDLE_CENTER"), ("Middle right", "MIDDLE_RIGHT"),
    ("Bottom left", "BOTTOM_LEFT"), ("Bottom center", "BOTTOM_CENTER"),
    ("Bottom right", "BOTTOM_RIGHT"),
)

#: MTEXT attachment points 1-9, as AutoCAD lists them.
ATTACHMENTS = (
    ("Top left", 1), ("Top center", 2), ("Top right", 3),
    ("Middle left", 4), ("Middle center", 5), ("Middle right", 6),
    ("Bottom left", 7), ("Bottom center", 8), ("Bottom right", 9),
)


def justification(text) -> str:
    return text.get_align_enum().name


def _offset(name: str, width: float, cap: float, descent: float) -> tuple[float, float]:
    """Where the alignment point sits from the left end of the baseline."""
    if name in ("LEFT", "ALIGNED", "FIT", "TOP_LEFT", "MIDDLE_LEFT", "BOTTOM_LEFT"):
        x = 0.0
    elif name in ("RIGHT", "TOP_RIGHT", "MIDDLE_RIGHT", "BOTTOM_RIGHT"):
        x = width
    else:
        x = width / 2.0
    if name.startswith("TOP_"):
        y = cap
    elif name.startswith("MIDDLE_"):
        y = cap / 2.0
    elif name.startswith("BOTTOM_"):
        y = -descent
    elif name == "MIDDLE":
        y = (cap - descent) / 2.0
    else:                                   # baseline: LEFT/CENTER/RIGHT/ALIGNED/FIT
        y = 0.0
    return x, y


def set_justification(text, name: str) -> None:
    """Give a TEXT the justification ``name`` (a TextEntityAlignment name)
    without moving its letters."""
    from ezdxf.enums import TextEntityAlignment
    from ezdxf.tools.text_size import text_size

    old = justification(text)
    if name == old:
        return
    size = text_size(text)
    width, cap = size.width, size.cap_height
    descent = max(size.total_height - size.cap_height, 0.0)
    angle = math.radians(text.dxf.get("rotation", 0.0))
    cos, sin = math.cos(angle), math.sin(angle)

    def turned(dx: float, dy: float) -> tuple[float, float]:
        return dx * cos - dy * sin, dx * sin + dy * cos

    _align, p1, _p2 = text.get_placement()
    ox, oy = turned(*_offset(old, width, cap, descent))
    base = (p1.x - ox, p1.y - oy)             # left end of the baseline
    nx, ny = turned(*_offset(name, width, cap, descent))
    target = (base[0] + nx, base[1] + ny)
    align = getattr(TextEntityAlignment, name)
    if name in ("ALIGNED", "FIT"):
        ex, ey = turned(width, 0.0)
        text.set_placement(target, (base[0] + ex, base[1] + ey), align=align)
    else:
        text.set_placement(target, align=align)
