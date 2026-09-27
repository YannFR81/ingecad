# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Which object snaps are running — AutoCAD's OSMODE, as a set of modes.

The state is a bitcode in AutoCAD ($OSMODE, documented on p.2436) and it is
kept as one here too, because that is what a drawing and a user's settings
carry: 1 endpoint, 2 midpoint, 4 centre, 8 node, 16 quadrant, 32
intersection, 64 insertion, 128 perpendicular, 256 tangent, 512 nearest,
2048 apparent intersection, 4096 extension, 8192 parallel. Bit 16384 means
"object snap switched off at the status bar", which is how AutoCAD tells a
user who pressed F3 from a user who unticked every box.

Geometric Center is newer than the reference we work from and has no
documented bit there, so it takes the next free one (32768). Origin is
IngeCAD's own -- no CAD has it, a tester insisted it is elementary, and
it is: the (0, 0) of the current space as a snappable point. It takes the
bit after that (65536). Both live only in the user's settings, never in a
drawing's $OSMODE.

Modes that are listed but not yet implemented are marked ``available=False``:
they appear in the menu greyed out with the reason, rather than offering a
tick that does nothing.
"""
from __future__ import annotations

from dataclasses import dataclass

OFF_BIT = 16384          # $OSMODE's "toggled off at the status bar" flag


@dataclass(frozen=True)
class Mode:
    key: str             # what core.snap calls it
    bit: int             # the OSMODE bit
    label: str           # what the menu shows
    available: bool = True
    note: str = ""


MODES: tuple[Mode, ...] = (
    Mode("END", 1, "Endpoint"),
    Mode("MID", 2, "Midpoint"),
    Mode("CEN", 4, "Center"),
    Mode("GCE", 32768, "Geometric Center"),
    Mode("NOD", 8, "Node"),
    Mode("ORI", 65536, "Origin"),
    Mode("QUA", 16, "Quadrant"),
    Mode("INT", 32, "Intersection"),
    Mode("EXT", 4096, "Extension", False,
         "Extension tracking is not implemented yet."),
    Mode("INS", 64, "Insertion"),
    Mode("PER", 128, "Perpendicular"),
    Mode("TAN", 256, "Tangent"),
    Mode("NEA", 512, "Nearest"),
    Mode("APP", 2048, "Apparent Intersection", False,
         "Apparent intersection is not implemented yet."),
    Mode("PAR", 8192, "Parallel", False,
         "Parallel tracking is not implemented yet."),
)

BY_KEY = {mode.key: mode for mode in MODES}
AVAILABLE = frozenset(mode.key for mode in MODES if mode.available)

# What a fresh install snaps to. AutoCAD ships 4133 (endpoint, centre,
# intersection, extension); ours is the same idea minus the tracking mode we
# do not have, plus midpoint and node, which a drafter turns on immediately.
DEFAULT_BITS = 1 | 2 | 4 | 8 | 32 | 128 | 512


def from_bits(bits: int) -> frozenset[str]:
    """The running modes in a bitcode (the off-flag is not a mode)."""
    return frozenset(mode.key for mode in MODES
                     if mode.available and bits & mode.bit)


def to_bits(keys) -> int:
    wanted = set(keys)
    return sum(mode.bit for mode in MODES if mode.key in wanted)


def is_off(bits: int) -> bool:
    return bool(bits & OFF_BIT)


def with_off(bits: int, off: bool) -> int:
    return (bits | OFF_BIT) if off else (bits & ~OFF_BIT)


def label_of(key: str) -> str:
    if key == "DTAN":
        return "Deferred Tangent"      # TAN with no previous point yet
    mode = BY_KEY.get(key)
    return mode.label if mode else key


#: What a one-shot override may be typed as: the three-letter key or any
#: longer start of the full name (END, ENDP, ENDPOINT), as AutoCAD reads
#: them at a point prompt.
_FULL_NAMES = {
    "END": "ENDPOINT", "MID": "MIDPOINT", "CEN": "CENTER",
    "GCE": "GCENTER", "NOD": "NODE", "ORI": "ORIGIN", "QUA": "QUADRANT",
    "INT": "INTERSECTION", "EXT": "EXTENSION", "INS": "INSERTION",
    "PER": "PERPENDICULAR", "TAN": "TANGENT", "NEA": "NEAREST",
    "APP": "APPINT", "PAR": "PARALLEL",
}


def override_from_text(text: str):
    """The one-shot object snap a typed word asks for, or None.

    ``frozenset({"TAN"})`` for TAN / TANG / TANGENT (a leading ``_`` is
    allowed), ``frozenset()`` for NON / NONE -- no snap for the next point.
    A mode that is not implemented answers its key all the same; the
    caller says it cannot be used.
    """
    word = text.strip().upper().lstrip("_")
    if len(word) < 3:
        return None
    if "NONE".startswith(word):
        return frozenset()
    for key, full in _FULL_NAMES.items():
        if word.startswith(key) and full.startswith(word):
            return frozenset({key})
    return None


#: The word AutoCAD prompts after a one-shot snap: "of" for a point that
#: belongs to the object (_endp of), "to" for one reached toward it (_tan to).
_TO = frozenset({"PER", "TAN", "NEA", "PAR"})

#: The command form a menu or a macro echoes (_endp, _tan...).
_COMMAND_FORM = {
    "END": "_endp", "MID": "_mid", "CEN": "_cen", "GCE": "_gcen",
    "NOD": "_nod", "ORI": "_ori", "QUA": "_qua", "INT": "_int",
    "EXT": "_ext", "INS": "_ins", "PER": "_per", "TAN": "_tan",
    "NEA": "_nea", "APP": "_app", "PAR": "_par",
}


def preposition(key: str) -> str:
    return "to" if key in _TO else "of"


def command_form(key: str) -> str:
    return _COMMAND_FORM.get(key, "_" + key.lower())
