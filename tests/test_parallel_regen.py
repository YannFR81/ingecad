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
