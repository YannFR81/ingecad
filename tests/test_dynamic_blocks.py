# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Dynamic blocks from AutoCAD (issue #36): the current state shows, and
the round trip keeps everything.

What the corpus says (239 of 1657 real plans carry the dynamic-block
classes; 14 surveyed in detail, ODA and LibreDWG reading them alike): an
INSERT of a dynamic block references an anonymous ``*U`` block holding the
geometry of its CURRENT state -- the entities other visibility states hide
are there too, flagged ``invisible`` (18 of 74 representations had some) --
and the definition block carries the ACAD_ENHANCEDBLOCK dictionary with the
parameters. So displaying the current state means drawing the ``*U`` block
and honouring the invisible flag, which the frontend does; changing the
state (grips) is the part that comes after, as the issue says.
"""
from __future__ import annotations

import ezdxf

from core.document import Document


def _dynamic_block_drawing():
    doc = ezdxf.new("R2018")
    # the definition: a door with two visibility states, plus its dictionary
    definition = doc.blocks.new("DOOR")
    definition.add_line((0, 0), (900, 0))
    definition.add_arc((0, 0), 900, 0, 90)
    xdict = definition.block_record.new_extension_dict()
    xdict.add_dictionary("ACAD_ENHANCEDBLOCK")
    # the representation AutoCAD inserts: the current state's geometry, the
    # other state's entities flagged invisible
    rep = doc.blocks.new("*U7")
    rep.add_line((0, 0), (900, 0))
    rep.add_arc((0, 0), 900, 0, 90)
    hidden = rep.add_line((0, 0), (0, 900))       # the "open left" state
    hidden.dxf.invisible = 1
    hidden_arc = rep.add_arc((0, 0), 900, 90, 180)
    hidden_arc.dxf.invisible = 1
    rep.block_record.new_extension_dict().add_dictionary("AcDbBlockRepresentation")
    doc.modelspace().add_blockref("*U7", (1000, 1000))
    return doc


def _drawn_kinds(document):
    from render.backend import build_scene

    scene = build_scene(document, "Model")
    return scene.lines.count if hasattr(scene.lines, "count") else len(scene.lines.data)


def test_the_current_state_is_drawn_and_the_hidden_state_is_not(qapp):
    document = Document(_dynamic_block_drawing())
    with_hidden = _drawn_kinds(document)

    # the inverse: unhide the other state and the picture grows
    for e in document.doc.blocks.get("*U7"):
        e.dxf.invisible = 0
    assert _drawn_kinds(document) > with_hidden, (
        "the invisible flag of the other visibility state was ignored")


def test_the_round_trip_keeps_the_definition_and_the_representation(tmp_path):
    doc = _dynamic_block_drawing()
    path = tmp_path / "dyn.dxf"
    doc.saveas(path)
    back = Document.load(path).doc
    definition = back.blocks.get("DOOR")
    assert definition.block_record.has_extension_dict
    assert "ACAD_ENHANCEDBLOCK" in definition.block_record.get_extension_dict().dictionary
    rep = back.blocks.get("*U7")
    assert rep is not None and len(list(rep)) == 4
    assert sum(1 for e in rep if e.dxf.get("invisible", 0)) == 2
    assert "AcDbBlockRepresentation" in rep.block_record.get_extension_dict().dictionary
    inserts = back.modelspace().query("INSERT")
    assert len(inserts) == 1 and inserts[0].dxf.name == "*U7"
