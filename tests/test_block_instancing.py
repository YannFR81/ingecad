# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Block references replay a recording of their block (#29).

ezdxf explodes a block again for every reference: a door placed 80 times
is tessellated 80 times. Within a model build each block is drawn once at
the origin -- per scale, resolved properties (ByBlock, layer 0) and draw
order group -- and every reference replays it rotated and moved. Measured:
Casa Peregrinos 1.6 s -> 1.0 s, Planos Constructivos 5.4 s -> 4.4 s.

On a deterministic drawing the result is the plain one, primitive for
primitive, within float rounding -- arcs aside: ezdxf splits them at the
quadrant boundaries, so its segment count follows the rotation, while a
replay keeps the recording's (both within the curve tolerance). On a real
plan it is also better: AutoCAD's filled dots are donuts whose width
exceeds their diameter, a self-overlapping outline whose triangulation
depends on where it sits -- in place the plain path left a notch in them
(Planos Constructivos); recorded at the origin they come out whole.
"""
from __future__ import annotations

import os

import ezdxf
import numpy as np
import pytest

from core.document import Document
from render import backend

pytestmark = pytest.mark.usefixtures("serial_regen")


@pytest.fixture
def serial_regen(monkeypatch):
    # the comparison is about instancing alone
    monkeypatch.setenv("INGECAD_SERIAL_REGEN", "1")


def _drawing(origin=(0.0, 0.0), arcs=False) -> Document:
    document = Document.new()
    doc = document.doc
    msp = doc.modelspace()
    doc.layers.add("MUROS", color=1)
    doc.layers.add("PUERTAS", color=3)
    door = doc.blocks.new("PUERTA", base_point=(0.1, 0.0))
    door.add_line((0, 0), (0.9, 0))
    if arcs:
        # ezdxf splits an arc into Beziers at the quadrant boundaries, so the
        # plain path's segment count depends on the reference's rotation;
        # a replay keeps the recording's -- see the arc test below
        door.add_arc((0, 0), 0.9, 0, 90)
    door.add_line((0, 0), (0, 0.9), dxfattribs={"color": 0})          # ByBlock
    door.add_lwpolyline([(0, 0), (0.05, 0), (0.05, 0.9)], dxfattribs={"layer": "0"})
    door.add_solid([(0, 0), (0.1, 0), (0, 0.1)])
    door.add_attdef("N", (0.2, 0.2), dxfattribs={"height": 0.1})
    frame = doc.blocks.new("MARCO")
    frame.add_lwpolyline([(0, 0), (1.2, 0), (1.2, 0.15), (0, 0.15)], close=True)
    frame.add_blockref("PUERTA", (0.2, 0.05), dxfattribs={"rotation": 15})  # nested
    frame.add_text("M", dxfattribs={"insert": (0.1, 0.3), "height": 0.2})
    ox, oy = origin
    for i in range(24):
        x, y = ox + (i % 6) * 3.0, oy + (i // 6) * 3.0
        attribs = {"rotation": i * 37.5, "layer": "PUERTAS" if i % 2 else "MUROS",
                   "color": 256 if i % 3 else 2}
        if i % 4 == 1:
            attribs["xscale"] = -1.0                                   # mirrored
        if i % 5 == 2:
            attribs["xscale"], attribs["yscale"] = 1.5, 0.75           # stretched
        ref = msp.add_blockref("PUERTA", (x, y), dxfattribs=attribs)
        ref.add_auto_attribs({"N": f"P{i}"})
        msp.add_blockref("MARCO", (x + 1, y + 1),
                         dxfattribs={"rotation": -i * 11.0, "layer": "MUROS"})
    return document


def _scene(document, monkeypatch, instancing: bool):
    monkeypatch.setenv("INGECAD_NO_INSTANCING", "" if instancing else "1")
    return backend.build_scene(document, "Model")


def _sorted_primitives(batch, per):
    """Primitives as rows, in a canonical order: a replay appends a
    reference's primitives in recording order, the plain path in ezdxf's;
    the set is what must match."""
    data = batch.data
    if not len(data):
        return np.zeros((0, per * 2))
    xy = np.stack([data["pos"][:, 0], data["pos"][:, 1]], axis=1).reshape(-1, per * 2)
    return xy[np.lexsort(np.round(xy, 6).T[::-1])]


def test_replayed_references_draw_what_the_plain_path_draws(monkeypatch):
    document = _drawing()
    plain = _scene(document, monkeypatch, instancing=False)
    fast = _scene(document, monkeypatch, instancing=True)
    for name, per in (("lines", 2), ("triangles", 3), ("points", 1)):
        a, b = getattr(plain, name), getattr(fast, name)
        assert a.vertex_count == b.vertex_count, name
        assert np.allclose(_sorted_primitives(a, per), _sorted_primitives(b, per),
                           atol=1e-7), name
    # every reference still owns its primitives: picking and hiding work
    assert set(plain.handle_ranges) == set(fast.handle_ranges)


def test_a_replayed_arc_stays_on_its_circle(monkeypatch):
    """Rotated references of a block with an arc: every replayed vertex
    lies on the real arc, within the flattening tolerance."""
    import math

    document = Document.new()
    doc = document.doc
    block = doc.blocks.new("ARCO")
    block.add_arc((0, 0), 2.0, 0, 90)
    msp = doc.modelspace()
    refs = [msp.add_blockref("ARCO", (i * 10.0, 0.0), dxfattribs={"rotation": i * 50.0})
            for i in range(6)]
    fast = _scene(document, monkeypatch, instancing=True)
    xy = fast.lines.data["pos"].astype(np.float64) + np.array(fast.origin)
    tolerance = fast.flatten * 1.01 + 1e-6
    for ref in refs:
        cx = ref.dxf.insert.x
        near = xy[np.abs(xy[:, 0] - cx) < 3]
        assert len(near)
        radius = np.hypot(near[:, 0] - cx, near[:, 1])
        assert np.all(np.abs(radius - 2.0) <= tolerance)
        angles = (np.degrees(np.arctan2(near[:, 1], near[:, 0] - cx)) - ref.dxf.rotation) % 360
        assert np.all((angles <= 90 + 1e-4) | (angles >= 360 - 1e-4))   # float32 on the GPU


def test_each_block_is_recorded_once_per_look(monkeypatch):
    document = _drawing()
    recorded = []
    real = backend.TolerantFrontend._record_block

    def spy(self, entity, properties, be):
        recorded.append(entity.dxf.name)
        return real(self, entity, properties, be)

    monkeypatch.setattr(backend.TolerantFrontend, "_record_block", spy)
    _scene(document, monkeypatch, instancing=True)
    # 24 doors and 24 frames drawn, but only one recording per distinct
    # (scale, resolved properties): far fewer than 48
    assert 0 < len(recorded) < 24
    assert recorded.count("MARCO") == 1


def test_references_that_cannot_be_replayed_take_the_usual_way(monkeypatch):
    document = Document.new()
    doc = document.doc
    msp = doc.modelspace()
    block = doc.blocks.new("B")
    block.add_circle((0, 0), 1)
    msp.add_blockref("B", (0, 0), dxfattribs={"extrusion": (0, 0, -1)})
    minsert = msp.add_blockref("B", (10, 0))
    minsert.dxf.column_count, minsert.dxf.column_spacing = 3, 3.0
    clipped = msp.add_blockref("B", (20, 0))
    from ezdxf import xclip

    xclip.XClip(clipped).set_block_clipping_path([(-0.5, -0.5), (0.5, 0.5)])
    keys = []
    real = backend.TolerantFrontend._instance_key

    def spy(self, entity, properties):
        key = real(self, entity, properties)
        keys.append(key)
        return key

    monkeypatch.setattr(backend.TolerantFrontend, "_instance_key", spy)
    fast = _scene(document, monkeypatch, instancing=True)
    assert keys and all(k is None for k in keys)
    plain = _scene(document, monkeypatch, instancing=False)
    assert fast.lines.vertex_count == plain.lines.vertex_count


def test_the_filled_dots_of_a_real_plan_come_out_whole(monkeypatch):
    """Planos Constructivos' _DOTSMALL, exactly: a donut of radius 0.0625
    and width 0.5 -- wider than its diameter, so its outline overlaps
    itself -- at 0.18. AutoCAD draws a full disc of radius 0.3125 x 0.18;
    the plain path left a notch in the ones in place (area short by a
    fifth). Recorded at the origin, every one is whole."""
    document = Document.new()
    doc = document.doc
    dot = doc.blocks.new("_DOTSMALL")
    dot.add_lwpolyline([(-0.0625, 0, 0, 0, 1), (0.0625, 0, 0, 0, 1)],
                       format="xyseb", close=True, dxfattribs={"const_width": 0.5})
    msp = doc.modelspace()
    for x, y in ((1646.593405491543, 304.9134302545202), (1650.2, 310.7),
                 (1700.123, 290.456)):
        msp.add_blockref("_DOTSMALL", (x, y), dxfattribs={"xscale": 0.18, "yscale": 0.18})
    fast = _scene(document, monkeypatch, instancing=True)
    tris = fast.triangles.data["pos"].reshape(-1, 3, 2).astype(np.float64)
    u, v = tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]
    covered = 0.5 * np.abs(u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]).sum()
    discs = 3 * np.pi * (0.3125 * 0.18) ** 2
    assert covered >= 0.97 * discs         # overlapping triangles may add a little


def test_instancing_is_only_for_the_model(monkeypatch):
    """A sheet clips its viewports in ezdxf's pipeline: no recordings."""
    document = _drawing()
    layout = next(n for n in document.doc.layout_names() if n != "Model")
    made = []
    real = backend.TolerantFrontend._record_block
    monkeypatch.setattr(backend.TolerantFrontend, "_record_block",
                        lambda *a: made.append(1) or real(*a))
    monkeypatch.setenv("INGECAD_NO_INSTANCING", "")
    backend.build_scene(document, layout)
    assert made == []
