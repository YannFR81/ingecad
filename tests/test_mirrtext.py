# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""MIRROR keeps text readable (MIRRTEXT = 0, AutoCAD's default) — #26.

ezdxf mirrors a TEXT or MTEXT into mirror writing: a (0, 0, -1) extrusion.
AutoCAD's MIRROR, with MIRRTEXT at 0, moves the text to where the mirror
puts it and keeps it reading the right way. The check that does not depend
on how that is encoded: the mirrored text's box, measured by ezdxf with the
font, is the original box mirrored — and the text faces up.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import ezdxf
import pytest
from ezdxf import bbox

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import actions, ocs  # noqa: E402
from core.commands import History  # noqa: E402
from core.document import Document  # noqa: E402

AXES = {
    "vertical": ((0, 0), (0, 10)),
    "horizontal": ((0, -3), (10, -3)),
    "diagonal": ((0, 0), (10, 4)),
}


def _mirror_box(entity, p1, p2):
    """The box of the text mirrored the way ezdxf does it (mirror writing):
    the same rectangle a readable text has to fill."""
    clone = entity.copy()
    clone.transform(actions._mirror_matrix(p1, p2))
    return _box(clone)


def _box(entity):
    b = bbox.extents([entity], fast=False)
    return (b.extmin.x, b.extmin.y, b.extmax.x, b.extmax.y)


def _texts(msp):
    return [
        msp.add_text("Planta 1:50", dxfattribs={
            "insert": (10, 2), "height": 2.5, "rotation": 0}),
        msp.add_text("EJE A", dxfattribs={"height": 2.0}).set_placement(
            (30, 8), align=ezdxf.enums.TextEntityAlignment.MIDDLE_RIGHT),
        msp.add_text("Muro", dxfattribs={
            "insert": (12, 20), "height": 1.8, "rotation": 30}),
        msp.add_text("Alineado", dxfattribs={"height": 2.0}).set_placement(
            (5, 40), (25, 44), align=ezdxf.enums.TextEntityAlignment.ALIGNED),
        msp.add_mtext("Nota\\Pgeneral", dxfattribs={
            "insert": (15, 30), "char_height": 2.0, "attachment_point": 1}),
    ]


def test_a_new_drawing_starts_with_mirrtext_zero():
    # ezdxf's own default is 1; AutoCAD's templates have 0
    assert Document.new().doc.header["$MIRRTEXT"] == 0


@pytest.mark.parametrize("axis", sorted(AXES))
@pytest.mark.parametrize("keep_source", [True, False])
def test_mirrored_text_is_readable_and_sits_in_the_mirrored_box(axis,
                                                                 keep_source):
    p1, p2 = AXES[axis]
    document = Document.new()
    sources = _texts(document.modelspace())
    wanted = [_mirror_box(e, p1, p2) for e in sources]
    before = [e.dxf.all_existing_dxf_attribs() for e in sources]
    history = History(document)
    cmd = actions.mirror_entities(sources, p1, p2, keep_source)
    history.execute(cmd)
    results = cmd.copies if keep_source else sources
    for entity, box in zip(results, wanted):
        assert ocs.kind(entity) == "up", entity.dxftype()
        assert _box(entity) == pytest.approx(box, abs=1e-6), (
            entity.dxftype(), entity.dxf.get("text", ""))
        # never upside down: the baseline keeps reading left to right or
        # turns less than a right angle from where it was
        if axis != "diagonal":
            direction = (entity.dxf.text_direction
                         if entity.dxftype() == "MTEXT"
                         else ezdxf.math.Vec3.from_deg_angle(
                             entity.dxf.rotation))
            assert direction.x > 0 or entity.dxf.get("rotation", 0) == 30
    history.undo()
    if not keep_source:
        after = [e.dxf.all_existing_dxf_attribs() for e in sources]
        for b, a in zip(before, after):
            assert b.keys() == a.keys()
            for key in b:
                if isinstance(b[key], float):
                    assert math.isclose(b[key], a[key], abs_tol=1e-9), key
                elif hasattr(b[key], "isclose"):
                    assert b[key].isclose(a[key], abs_tol=1e-9), key
                else:
                    assert b[key] == a[key], key


def test_mirrtext_one_writes_the_text_mirrored():
    document = Document.new()
    document.doc.header["$MIRRTEXT"] = 1
    text = document.modelspace().add_text("ABC", dxfattribs={
        "insert": (10, 0), "height": 2.5})
    History(document).execute(
        actions.mirror_entities([text], (0, 0), (0, 10), keep_source=False))
    assert ocs.kind(text) == "flipped"


def test_attributes_of_a_mirrored_block_stay_readable():
    """"Variable attributes" follow MIRRTEXT; the block itself is mirrored."""
    document = Document.new()
    doc = document.doc
    block = doc.blocks.new("ROTULO")
    block.add_line((0, 0), (20, 0))
    block.add_attdef("NOMBRE", (1, 1), dxfattribs={"height": 2.0})
    insert = document.modelspace().add_blockref("ROTULO", (10, 0))
    insert.add_auto_attribs({"NOMBRE": "Sala"})
    attrib = insert.attribs[0]
    wanted = _mirror_box(attrib, (0, 0), (0, 10))
    history = History(document)
    history.execute(actions.mirror_entities([insert], (0, 0), (0, 10),
                                            keep_source=False))
    attrib = insert.attribs[0]
    assert ocs.kind(attrib) == "up"
    assert _box(attrib) == pytest.approx(wanted, abs=1e-6)
    history.undo()
    assert insert.attribs[0].dxf.insert.isclose((11, 1, 0), abs_tol=1e-9)
    assert ocs.kind(insert.attribs[0]) == "up"


def test_mirrtext_is_a_system_variable_typed_at_the_command_line(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document()
    try:
        header = win.document.doc.header
        assert header["$MIRRTEXT"] == 0
        win.dispatcher.submit("MIRRTEXT 1")
        assert header["$MIRRTEXT"] == 1
        win.dispatcher.submit("MIRRTEXT")
        win.dispatcher.submit("0")
        assert header["$MIRRTEXT"] == 0
        win.dispatcher.submit("MIRRTEXT 5")            # out of range: refused
        assert header["$MIRRTEXT"] == 0
    finally:
        win.document.dirty = False
        win.close()
