# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Save as DWG must keep every application's XDATA apart.

LibreDWG's DXF importer (``add_eed``) had two faults that only show when an
object carries XDATA from more than one application:

* the slot a ``1001`` fills with its APPID handle was wiped (``memset``) when
  the group's first value reused it, for every group after the first, and
* the search for the group's header walked down without stopping, so it
  always found the FIRST group.

Together they fused every later group into the first one. Measured on 42
real drawings: 851 objects with two or more groups, 0 intact before, 851
after. That erased ``AcadAnnotative`` flags, Topografía's point data under
``INGECAD`` and — through the second fault, ``ACAD`` hard-coded at handle
0x12 while ezdxf puts it at 2A — a dimension's style overrides, so the
DIMLFAC that makes a dimension drawn through a viewport read model units was
gone the moment AutoCAD opened the file.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.document import Document
from formats.dwg_bridge import find_dxf2dwg, load_dwg


def _xdata(entity):
    if not entity.xdata or not entity.xdata.data:
        return {}
    return {app: [(t.code, t.value) for t in entity.xdata.get(app)]
            for app in entity.xdata.data}


@pytest.mark.skipif(find_dxf2dwg() is None, reason="LibreDWG not available")
def test_several_applications_survive_save_as_dwg(tmp_path: Path):
    document = Document.new()
    doc = document.doc
    for app in ("APPA", "AcadAnnotative", "INGECAD"):
        doc.appids.add(app)
    msp = doc.modelspace()
    dim = msp.add_linear_dim(base=(0, 5), p1=(0, 0), p2=(100, 0),
                             override={"dimlfac": 0.05})
    dim.render()
    text = msp.add_text("P12", dxfattribs={"insert": (0, 10)})
    text.set_xdata("AcadAnnotative", [
        (1000, "AnnotativeData"), (1002, "{"), (1070, 1), (1070, 1),
        (1002, "}")])
    text.set_xdata("INGECAD", [(1000, "P12"), (1000, "BM-3")])
    point = msp.add_point((1, 2, 3))
    point.set_xdata("APPA", [(1000, "x"), (1010, (1.5, 2.5, 3.5))])
    point.set_xdata("INGECAD", [(1000, "P7"), (1070, -12)])
    want = {e.dxf.handle: _xdata(e) for e in msp if _xdata(e)}

    document.save_as(tmp_path / "multi.dwg")
    back = load_dwg(tmp_path / "multi.dwg").doc

    got = {e.dxf.handle: _xdata(e) for e in back.modelspace()
           if e.dxf.handle in want}
    assert got == want
    dims = [e for e in back.modelspace() if e.dxftype() == "DIMENSION"]
    assert dims[0].override().get("dimlfac") == pytest.approx(0.05)
