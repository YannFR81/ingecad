# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Drawing cleanup (#37): PURGE / -PURGE, OVERKILL, WBLOCK.

The round-trip promise applies to a purge like to any edit: what was not
purged is byte-for-byte what it was, and undo brings back every item.
"""
from __future__ import annotations

import ezdxf
import pytest

from core import cleanup
from core.commands import History
from core.document import Document


def _drawing():
    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    doc.layers.add("USED")
    doc.layers.add("UNUSED")
    doc.layers.add("CURRENT")
    doc.header["$CLAYER"] = "CURRENT"
    doc.linetypes.add("USEDLT", pattern=[1.0, 0.5, -0.5])
    doc.linetypes.add("UNUSEDLT", pattern=[1.0, 0.25, -0.25])
    doc.styles.add("USEDSTYLE", font="arial.ttf")
    doc.styles.add("UNUSEDSTYLE", font="arial.ttf")
    doc.dimstyles.new("ARROWED", dxfattribs={"dimblk": "ARCHTICK"})
    arrow = doc.blocks.new("_ARCHTICK")
    arrow.add_line((0, 0), (1, 1))
    used = doc.blocks.new("USEDBLK")
    used.add_line((0, 0), (1, 1))
    unused = doc.blocks.new("UNUSEDBLK")
    unused.add_circle((0, 0), 2)
    nested = doc.blocks.new("NESTED")
    nested.add_line((0, 0), (1, 0))
    unused.add_blockref("NESTED", (0, 0))
    msp.add_blockref("USEDBLK", (0, 0), dxfattribs={"layer": "USED"})
    msp.add_line((0, 0), (5, 0), dxfattribs={"linetype": "USEDLT"})
    msp.add_text("hola", dxfattribs={"style": "USEDSTYLE"})
    msp.add_line((3, 3), (3, 3))                 # zero length
    msp.add_text("   ")                          # empty
    return doc


def _fingerprint(doc, skip_handles=()):
    """Every entity's attributes, for "nothing else changed"."""
    out = {}
    for layout in doc.layouts:
        for e in layout:
            if e.dxf.handle not in skip_handles:
                out[e.dxf.handle] = (e.dxftype(), repr(sorted(e.dxfattribs().items())))
    return out


# -- what can go ---------------------------------------------------------------

def test_candidates_find_the_unused_and_protect_the_used():
    found = cleanup.candidates(_drawing(), nested=False)
    assert found["layers"] == ["UNUSED"]          # 0, Defpoints, CURRENT, USED stay
    assert found["ltypes"] == ["UNUSEDLT"]
    assert found["textstyles"] == ["UNUSEDSTYLE"]
    assert "UNUSEDBLK" in found["blocks"]
    assert "USEDBLK" not in found["blocks"]
    assert "NESTED" not in found["blocks"], "-PURGE removes one level only"
    assert "_ARCHTICK" not in found["blocks"], "a dimstyle's arrow is a reference"
    assert len(found["zero"]) == 1 and len(found["empty"]) == 1


def test_nested_purge_reaches_a_block_only_an_unused_block_uses():
    found = cleanup.candidates(_drawing(), nested=True)
    assert "NESTED" in found["blocks"] and "UNUSEDBLK" in found["blocks"]


def test_the_current_layer_is_never_a_candidate():
    doc = _drawing()
    doc.header["$CLAYER"] = "UNUSED"
    assert "UNUSED" not in cleanup.candidates(doc)["layers"]
    # the inverse: any other name and it goes again
    doc.header["$CLAYER"] = "0"
    assert "UNUSED" in cleanup.candidates(doc)["layers"]


def test_zero_length_and_empty_text_skip_locked_layers():
    doc = _drawing()
    doc.layers.add("LOCKED").lock()
    doc.modelspace().add_line((1, 1), (1, 1), dxfattribs={"layer": "LOCKED"})
    doc.modelspace().add_mtext("  ", dxfattribs={"layer": "LOCKED"})
    found = cleanup.candidates(doc)
    assert len(found["zero"]) == 1 and len(found["empty"]) == 1


# -- the Command ---------------------------------------------------------------

def test_purge_touches_nothing_else_and_undo_restores_everything():
    doc = _drawing()
    document = Document(doc)
    history = History(document)
    found = cleanup.candidates(doc, nested=True)
    going = {e.dxf.handle for e in found["zero"] + found["empty"]}
    before = _fingerprint(doc, going)
    tables_before = (sorted(l.dxf.name for l in doc.layers), sorted(d.dxf.name for d in doc.dimstyles),
                     sorted(l.dxf.name for l in doc.linetypes),
                     sorted(s.dxf.name for s in doc.styles),
                     sorted(b.name for b in doc.blocks))
    command = cleanup.PurgeCommand(found)
    history.execute(command)
    assert command.count == 8          # + the unused ARROWED dimstyle
    assert "ARROWED" not in doc.dimstyles
    assert "UNUSED" not in doc.layers and "UNUSEDLT" not in doc.linetypes
    assert "UNUSEDSTYLE" not in doc.styles
    assert "UNUSEDBLK" not in doc.blocks and "NESTED" not in doc.blocks
    assert len(cleanup.zero_length_entities(doc)) == 0
    assert _fingerprint(doc) == before, "a purge changed something it did not purge"
    history.undo()
    assert (sorted(l.dxf.name for l in doc.layers), sorted(d.dxf.name for d in doc.dimstyles),
            sorted(l.dxf.name for l in doc.linetypes),
            sorted(s.dxf.name for s in doc.styles),
            sorted(b.name for b in doc.blocks)) == tables_before
    assert [e.dxftype() for e in doc.blocks.get("UNUSEDBLK")] == ["CIRCLE", "INSERT"]
    assert len(cleanup.zero_length_entities(doc)) == 1
    assert set(_fingerprint(doc)) >= set(before) | going
    history.redo()
    assert "UNUSED" not in doc.layers and _fingerprint(doc) == before


# -- the -PURGE prompt flow ----------------------------------------------------

class Flow:
    def __init__(self, doc, args=(), **kwargs):
        self.document = Document(doc)
        self.history = History(self.document)
        self.echoes: list[str] = []
        self.refreshed = 0
        self.prompt = cleanup.purge_command(
            self.document, self.history, echo=self.echoes.append,
            refresh=self._refresh, args=args, **kwargs)

    def _refresh(self):
        self.refreshed += 1

    def answer(self, *texts):
        for text in texts:
            assert self.prompt is not None, "flow already ended"
            self.prompt = self.prompt.on_input(text)
        return self.prompt


def test_dash_purge_blocks_without_verifying():
    f = Flow(_drawing())
    assert "[Blocks/DEtailviewstyles" in f.prompt.text
    f.answer("B", "*", "N")
    assert f.prompt is None
    assert "UNUSEDBLK" not in f.document.doc.blocks
    assert "NESTED" in f.document.doc.blocks, "one level of reference per run"
    assert any('Deleting block "UNUSEDBLK"' in e for e in f.echoes)
    assert f.refreshed == 1
    f.history.undo()
    assert "UNUSEDBLK" in f.document.doc.blocks


def test_dash_purge_verifies_each_name_and_honours_the_answer():
    doc = _drawing()
    doc.layers.add("UNUSED2")
    f = Flow(doc)
    f.answer("LA", "*", "Y")
    assert 'Purge layer "UNUSED"' in f.prompt.text
    f.answer("N")                                   # keep UNUSED
    assert 'Purge layer "UNUSED2"' in f.prompt.text
    f.answer("Y")
    assert f.prompt is None
    assert "UNUSED" in doc.layers and "UNUSED2" not in doc.layers


def test_dash_purge_all_and_the_unnamed_categories():
    doc = _drawing()
    f = Flow(doc, args=("A", "*", "N"))
    assert f.prompt is None
    assert "UNUSED" not in doc.layers and "UNUSEDSTYLE" not in doc.styles
    assert "UNUSEDLT" not in doc.linetypes and "UNUSEDBLK" not in doc.blocks
    assert len(cleanup.zero_length_entities(doc)) == 1, "All is the named objects"
    f2 = Flow(doc, args=("Z",))
    assert f2.prompt is None and len(cleanup.zero_length_entities(doc)) == 0
    f3 = Flow(doc, args=("E",))
    assert len(cleanup.empty_text_entities(doc)) == 0
    assert any("deleted" in e for e in f3.echoes)


def test_dash_purge_says_when_there_is_nothing_and_for_unsupported_kinds():
    f = Flow(ezdxf.new("R2018"), args=("B", "*", "N"))
    assert any("No unreferenced blocks found" in e for e in f.echoes)
    f = Flow(ezdxf.new("R2018"), args=("MA",))
    assert f.prompt is None
    assert any("materials" in e for e in f.echoes)
    f = Flow(ezdxf.new("R2018"))
    f.answer("XYZ")
    assert any("Invalid option" in e for e in f.echoes)
    assert f.prompt is not None                     # asks again


def test_name_patterns_follow_autocad_wildcards():
    names = ["COL", "COLUMNA", "VIGA", "V2"]
    assert cleanup.match_names(names, "*") == names
    assert cleanup.match_names(names, "COL*") == ["COL", "COLUMNA"]
    assert cleanup.match_names(names, "viga,v2") == ["VIGA", "V2"]


# -- OVERKILL ------------------------------------------------------------------

def _overkill_doc():
    doc = ezdxf.new("R2018")
    doc.layers.add("OTHER")
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 0))
    msp.add_line((0, 0), (10, 0))                    # exact duplicate
    msp.add_line((5, 0), (15, 0))                    # partial overlap
    msp.add_line((15, 0), (20, 0))                   # end to end
    msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "OTHER"})   # other layer
    msp.add_arc((0, 0), 5, 0, 90)
    msp.add_arc((0, 0), 5, 90, 180)                  # end to end arc
    msp.add_lwpolyline([(0, 0), (1, 0), (2, 0), (2, 2)])
    return doc


def test_overkill_removes_duplicates_and_merges_collinear_geometry():
    doc = _overkill_doc()
    msp = doc.modelspace()
    plan = cleanup.overkill_plan(list(msp))
    assert plan.duplicate_count == 1
    assert plan.overlap_count == 4          # 2 line joins + 1 arc join + 1 pline vertex
    document = Document(doc)
    history = History(document)
    history.execute(cleanup.overkill_command(plan))
    lines = sorted((round(e.dxf.start.x, 6), round(e.dxf.end.x, 6), e.dxf.layer)
                   for e in msp.query("LINE"))
    assert lines == [(0.0, 10.0, "OTHER"), (0.0, 20.0, "0")]
    arcs = list(msp.query("ARC"))
    assert len(arcs) == 1
    assert (arcs[0].dxf.start_angle, arcs[0].dxf.end_angle) == pytest.approx((0.0, 180.0))
    pline = msp.query("LWPOLYLINE")[0]
    assert [tuple(round(v, 6) for v in p[:2]) for p in pline.get_points("xy")] == \
        [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0)]
    history.undo()
    assert len(msp) == 8
    assert len(msp.query("LINE")) == 5


def test_overkill_ignoring_layer_merges_across_layers_and_tolerance_matters():
    doc = _overkill_doc()
    settings = cleanup.OverkillSettings(ignore={"LA"})
    plan = cleanup.overkill_plan(list(doc.modelspace()), settings)
    assert plan.duplicate_count == 2, "the OTHER-layer line is a duplicate too"
    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 0))
    msp.add_line((0, 0.001), (10, 0.001))
    assert cleanup.overkill_plan(list(msp)).duplicate_count == 0
    assert cleanup.overkill_plan(list(msp), cleanup.OverkillSettings(
        tolerance=0.01)).duplicate_count == 1


def test_overkill_options_off_leave_the_geometry_alone():
    doc = _overkill_doc()
    settings = cleanup.OverkillSettings(partial=False, end_to_end=False,
                                        optimize_plines=False)
    plan = cleanup.overkill_plan(list(doc.modelspace()), settings)
    assert plan.duplicate_count == 1 and plan.overlap_count == 0
    assert cleanup.overkill_command(cleanup.OverkillPlan()) is None


# -- WBLOCK --------------------------------------------------------------------

def test_wblock_writes_a_block_a_selection_and_the_whole_drawing(tmp_path):
    doc = _drawing()
    document = Document(doc)
    path = tmp_path / "out.dxf"
    assert cleanup.write_block_file(document, path, block_name="USEDBLK") == 1
    out = ezdxf.readfile(path)
    assert [e.dxftype() for e in out.modelspace()] == ["LINE"]

    msp = doc.modelspace()
    selection = [e for e in msp if e.dxftype() in ("INSERT", "LINE")]
    n = cleanup.write_block_file(document, path, entities=selection,
                                 base_point=(5.0, 0.0, 0.0))
    out = ezdxf.readfile(path)
    assert n == len(out.modelspace()) == len(selection)
    insert = out.modelspace().query("INSERT")[0]
    assert (insert.dxf.insert.x, insert.dxf.insert.y) == pytest.approx((-5.0, 0.0)), \
        "the base point becomes the new drawing's origin"
    assert "USEDBLK" in out.blocks and "USED" in out.layers and "USEDLT" in out.linetypes
    assert "UNUSEDBLK" not in out.blocks, "unreferenced symbols are not written"

    n = cleanup.write_block_file(document, path, whole=True)
    out = ezdxf.readfile(path)
    assert n == len(msp) == len(out.modelspace())
