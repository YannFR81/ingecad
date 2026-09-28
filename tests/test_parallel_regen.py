# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The model regenerates on several cores, and draws the same (#31).

Workers fork, each draws its runs of entities through the same draw_layout
the serial regen uses, and their buckets are stitched in order: on a
deterministic drawing the packed scene is identical, array for array. (A
pattern HATCH is not deterministic even serially: ezdxf's hatching stops at
a time limit.) Measured on Plaza Yanque: 4.2 s -> 1.25 s, pixels within
the serial-vs-serial noise.
"""
from __future__ import annotations

import sys

import numpy as np
import pytest

from core.document import Document
from render import backend, parallel

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"),
                                reason="fork-based: Linux only")

_REAL = parallel.draw_parallel
_REAL_SHEET = parallel.draw_sheet_parallel


def _drawing() -> Document:
    document = Document.new()
    doc = document.doc
    msp = doc.modelspace()
    for name, color in (("MUROS", 1), ("EJES", 5), ("TEXTO", 3)):
        doc.layers.add(name, color=color)
    door = doc.blocks.new("PUERTA")
    door.add_line((0, 0), (0.9, 0))
    door.add_arc((0, 0), 0.9, 0, 90)
    door.add_line((0, 0), (0, 0.9), dxfattribs={"layer": "0", "color": 0})  # ByBlock
    window = doc.blocks.new("VENTANA")
    window.add_lwpolyline([(0, 0), (1.2, 0), (1.2, 0.15), (0, 0.15)], close=True)
    window.add_blockref("PUERTA", (0.2, 0.05), dxfattribs={"xscale": 0.5})  # nested
    for i in range(160):
        x = (i % 20) * 5.0
        y = (i // 20) * 4.0
        msp.add_line((x, y), (x + 4, y), dxfattribs={"layer": "MUROS"})
        msp.add_circle((x + 2, y + 2), 0.4, dxfattribs={"layer": "EJES"})
        msp.add_blockref("PUERTA", (x + 1, y + 0.5), dxfattribs={
            "rotation": i * 7, "layer": "MUROS", "color": 2})
        msp.add_blockref("VENTANA", (x, y + 3), dxfattribs={"layer": "EJES"})
        msp.add_text(f"L{i}", dxfattribs={"insert": (x, y + 1), "height": 0.3,
                                          "layer": "TEXTO"})
        msp.add_solid([(x, y), (x + 0.5, y), (x, y + 0.5)],
                      dxfattribs={"layer": "MUROS"})
    return document


def _scene(document, monkeypatch, parallel_on: bool):
    monkeypatch.setenv("INGECAD_SERIAL_REGEN", "" if parallel_on else "1")
    monkeypatch.setattr(parallel, "MIN_COST", 0)
    used = []

    def spy(*a, **k):
        k["min_cost"] = 0
        result = _REAL(*a, **k)
        used.append(result is not None)
        return result

    monkeypatch.setattr(parallel, "draw_parallel", spy)
    scene = backend.build_scene(document, "Model")
    return scene, used


def test_the_parallel_scene_is_the_serial_one_array_for_array(monkeypatch):
    document = _drawing()
    serial, used_serial = _scene(document, monkeypatch, parallel_on=False)
    fast, used_fast = _scene(document, monkeypatch, parallel_on=True)
    assert used_serial == [False] and used_fast == [True]
    for name in ("lines", "triangles", "points"):
        a, b = getattr(serial, name), getattr(fast, name)
        assert a.vertex_count == b.vertex_count > 0 or name == "points"
        assert np.array_equal(a.data, b.data), name
    assert serial.handle_ranges == fast.handle_ranges


def test_the_runs_cover_every_entity_once_in_order():
    document = _drawing()
    costs = parallel.entity_costs(document.modelspace())
    runs = parallel.split(costs, 12)
    assert len(runs) == 12
    seen = [h for run in runs for h in sorted(run, key=[h for h, _c in costs].index)]
    assert seen == [h for h, _c in costs]
    # a block reference costs what its block holds, nested blocks included
    by_handle = dict(costs)
    msp = document.modelspace()
    door = next(e for e in msp if e.dxftype() == "INSERT" and e.dxf.name == "PUERTA")
    window = next(e for e in msp if e.dxftype() == "INSERT" and e.dxf.name == "VENTANA")
    assert by_handle[door.dxf.handle] == 1 + 1 + 3          # itself, BLOCK, 3 entities
    assert by_handle[window.dxf.handle] > by_handle[door.dxf.handle]


def test_a_worker_that_fails_leaves_the_serial_regen_to_do_it(monkeypatch):
    document = _drawing()
    layout = document.modelspace()

    def broken():
        raise RuntimeError("worker lost")

    assert parallel.draw_parallel(broken, layout, min_cost=0, processes=2) is None


def test_a_worker_that_dies_is_noticed_at_once(monkeypatch):
    """A child that crashes (a segfault, a kill) loses its task; the pool
    must say so now, not after the timeout, so the serial regen follows."""
    import os
    import time

    document = _drawing()

    def dies():
        os._exit(3)

    monkeypatch.setattr(parallel, "TIMEOUT_S", 60.0)
    started = time.monotonic()
    assert parallel.draw_parallel(dies, document.modelspace(),
                                  min_cost=0, processes=2) is None
    assert time.monotonic() - started < 10


def test_small_drawings_and_the_switch_stay_serial(monkeypatch):
    document = _drawing()
    layout = document.modelspace()
    make = lambda: (_ for _ in ()).throw(AssertionError("must not draw"))
    assert parallel.draw_parallel(make, layout) is None      # below MIN_COST
    monkeypatch.setenv("INGECAD_SERIAL_REGEN", "1")
    assert parallel.draw_parallel(make, layout, min_cost=0) is None


def test_the_window_regenerates_in_parallel_from_its_worker_thread(qapp, monkeypatch):
    """The real path: regen_in_memory runs build_scene on a QThread, and
    the fork happens there -- it must come back, and draw the same."""
    import time

    from views.main_window import MainWindow

    monkeypatch.setenv("INGECAD_SERIAL_REGEN", "")
    monkeypatch.setattr(parallel, "MIN_COST", 0)
    calls = []

    def spy(*a, **k):
        k["min_cost"] = 0
        result = _REAL(*a, **k)
        calls.append(result is not None)
        return result

    monkeypatch.setattr(parallel, "draw_parallel", spy)
    win = MainWindow()
    win.new_document("m")
    try:
        win.document = _drawing()
        win.history.document = win.document
        expected = None
        monkeypatch.setenv("INGECAD_SERIAL_REGEN", "1")
        expected = backend.build_scene(win.document, "Model")
        monkeypatch.setenv("INGECAD_SERIAL_REGEN", "")
        calls.clear()
        win.regen_in_memory()
        deadline = time.monotonic() + 60
        while win._regen_worker is not None and time.monotonic() < deadline:
            qapp.processEvents()
        assert win._regen_worker is None, "the parallel regen never came back"
        assert calls and calls[-1] is True
        scene = win.viewport._scene
        assert np.array_equal(scene.lines.data, expected.lines.data)
    finally:
        win.document.dirty = False
        win.close()


# -- sheets ----------------------------------------------------------------------
def _sheet_drawing():
    document = _drawing()
    doc = document.doc
    doc.layers.add("MARCOS", color=7)       # colour 7: black on the paper
    sheet = doc.layouts.new("A1")
    sheet.add_line((0, 0), (420, 0))                              # the sheet's own
    sheet.add_text("ROTULO", dxfattribs={"insert": (10, 10), "height": 5})
    for i, (center, size) in enumerate((((50, 20), 40), ((300, 60), 90))):
        sheet.add_viewport(center=(120 + i * 180, 150), size=(160, 120),
                           view_center_point=center, view_height=size,
                           dxfattribs={"layer": "MARCOS"})
    return document


def _canonical(batch, per):
    """Primitives as rows -- positions AND colours -- in a canonical order:
    within a same-colour group the order is not seen, the colour is."""
    data = batch.data
    if not len(data):
        return np.zeros((0, per * 6))
    rows = np.concatenate([data["pos"].astype(np.float64),
                           data["rgba"].astype(np.float64)], axis=1).reshape(-1, per * 6)
    return rows[np.lexsort(np.round(rows, 5).T[::-1])]


def test_a_sheet_draws_the_same_on_several_cores(monkeypatch):
    """Every worker draws the whole sheet through the same draw_layout,
    in each viewport only its runs of the model, and one of them the
    sheet's own entities; the viewports clip in ezdxf as always."""
    document = _sheet_drawing()
    monkeypatch.setattr(parallel, "MIN_COST", 0)
    used = []

    def spy(*a, **k):
        k["min_cost"] = 0
        result = _REAL_SHEET(*a, **k)
        used.append(result is not None)
        return result

    monkeypatch.setattr(parallel, "draw_sheet_parallel", spy)
    monkeypatch.setenv("INGECAD_SERIAL_REGEN", "1")
    serial = backend.build_scene(document, "A1")
    monkeypatch.setenv("INGECAD_SERIAL_REGEN", "")
    fast = backend.build_scene(document, "A1")
    assert used == [False, True]
    for name, per in (("lines", 2), ("triangles", 3), ("points", 1)):
        a, b = getattr(serial, name), getattr(fast, name)
        assert a.vertex_count == b.vertex_count, name
        assert np.allclose(_canonical(a, per), _canonical(b, per), atol=1e-6), name
    assert set(serial.handle_ranges) == set(fast.handle_ranges)
    borders = [e.dxf.handle for e in document.doc.layouts.get("A1")
               if e.dxftype() == "VIEWPORT"]
    assert any(h in fast.handle_ranges for h in borders)      # frames drawn


def test_a_worker_is_told_a_number_never_sent_the_drawing(monkeypatch):
    """A job that carried the layout pickled the whole drawing to every
    worker (0.65 s each, and the worker drew a copy): a parallel sheet was
    ten times slower than a serial one. Nothing of the drawing may travel."""
    from ezdxf.document import Drawing

    def refuse(self, *a):
        raise AssertionError("the drawing was pickled for a worker")

    monkeypatch.setattr(Drawing, "__reduce_ex__", refuse, raising=False)
    document = _sheet_drawing()
    frontends = []

    def make():
        from core.draworder import order_groups

        layout = document.doc.layouts.get("A1")
        be = backend.VertexBackend(1.0, order_groups(layout))
        fe = backend.TolerantFrontend(backend.TolerantRenderContext(document.doc), be,
                                      backend.frontend_config(1.0))
        frontends.append(fe)
        return fe, be

    layout = document.doc.layouts.get("A1")
    assert _REAL_SHEET(make, layout, min_cost=0, processes=2) is not None
    assert _REAL(make, document.modelspace(), min_cost=0, processes=2) is not None


def test_a_sheet_draws_every_block_every_time(monkeypatch):
    """The viewport culling cached boxes by id(): a block's content is
    made of temporary copies, and Python gives a freed copy's id to the
    next one, which then inherited a stranger's box and was culled -- 8
    sheet regens in 50 lost part of a block, serially too (v0.6.4). Only
    the drawing's own entities are culled now."""
    document = _sheet_drawing()
    monkeypatch.setenv("INGECAD_SERIAL_REGEN", "1")
    seen = {(s.lines.vertex_count, s.triangles.vertex_count)
            for s in (backend.build_scene(document, "A1") for _ in range(25))}
    assert len(seen) == 1, seen
