# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A LEADER with a single vertex survives every save.

Real drawings carry them: all 73 leaders of a road plan in the corpus
(0073_STA ROSA3) have one vertex, and ODA reads them so. ezdxf refused to
export a LEADER with fewer than two vertices and its auditor deleted it, so
Save as DWG and Save as DXF both dropped every one without a word.
"""
from __future__ import annotations

import sys
from pathlib import Path

import ezdxf
import pytest
from ezdxf import recover

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.document import Document  # noqa: E402  (applies the ezdxf patches)
from formats.dwg_bridge import find_dxf2dwg, load_dwg  # noqa: E402

VERTEX = (249798.869, 8349426.552, 0.0)


def _doc_with_one_vertex_leader():
    doc = ezdxf.new("R2018")
    leader = doc.modelspace().add_leader([(0, 0), (5, 5)])
    leader.vertices = [VERTEX]
    return doc


def _leaders(doc):
    return [e for e in doc.modelspace() if e.dxftype() == "LEADER"]


def _check(leaders):
    assert len(leaders) == 1
    assert [tuple(v) for v in leaders[0].vertices] == [pytest.approx(VERTEX)]


def test_single_vertex_leader_survives_save_as_dxf(tmp_path):
    path = tmp_path / "leader.dxf"
    Document(_doc_with_one_vertex_leader()).save_as(path)
    _check(_leaders(Document.load(path).doc))
    # the recover path audits the drawing: the auditor must not delete it
    doc, _auditor = recover.readfile(path)
    _check(_leaders(doc))


@pytest.mark.skipif(find_dxf2dwg() is None, reason="LibreDWG not available")
def test_single_vertex_leader_survives_save_as_dwg(tmp_path):
    path = tmp_path / "leader.dwg"
    Document(_doc_with_one_vertex_leader()).save_as(path)
    _check(_leaders(load_dwg(path).doc))
