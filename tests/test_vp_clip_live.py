# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Panning inside a viewport stays live on the sheets colleagues send.

Marco (2026-09-27): "dentro del viewport hago pan para centrar el dibujo y
hay lag". Measured with real mouse events on Planos Constructivos: 60 moves
fired 60 sheet regens, and the live path never engaged. The reason: the
live navigation took any clipping_boundary_handle as "clipped, only the
bake can draw it" -- but on 25 of that sheet's 30 viewports (and on every
viewport of Plaza Yanque and Casa Peregrinos) the handle points at
NOTHING, a dangling reference the conversion leaves behind, and ezdxf
itself falls back to the frame for those. The other five are plain
rectangles, which a scissor clips as well as the frame does.

So :func:`core.layouts.viewport_clip` mirrors ezdxf's rule exactly, and
only a shaped boundary keeps the baked path.
"""
from __future__ import annotations

import pytest
from ezdxf.lldxf import const


def _sheet(win, boundary=None, dangling=False):
    """A sheet with one viewport; optionally a clipping boundary."""
    doc = win.document
    doc.modelspace().add_line((0, 0), (100, 50))
    psp = doc.doc.layouts.get("Layout1")
    vp = psp.add_viewport(center=(100, 70), size=(120, 80),
                          view_center_point=(50, 25), view_height=60)
    if boundary is not None:
        vp.dxf.flags |= const.VSF_NON_RECTANGULAR_CLIPPING
        vp.dxf.clipping_boundary_handle = boundary.dxf.handle
    elif dangling:
        vp.dxf.flags |= const.VSF_NON_RECTANGULAR_CLIPPING
        vp.dxf.clipping_boundary_handle = "FFFFFF"
    return psp, vp


def _drag(win, vp, moves=5):
    """Activate the viewport and pan the model inside it, as a middle-drag
    does; returns how many sheet regens the drag fired."""
    fired = []
    real = win.regen_in_memory
    win.regen_in_memory = lambda *a, **k: fired.append(1) or real(*a, **k)
    win.switch_layout("Layout1")
    win._activate_viewport(vp)
    _warm(win)                     # the user looks for a moment, then drags
    fired.clear()
    for _ in range(moves):
        assert win.vp_view_pan(1.0, 0.5) is True
    return len(fired)


def _warm(win) -> None:
    """Let the live model scene the activation started finish landing."""
    from PySide6.QtWidgets import QApplication

    worker = getattr(win, "_vp_live_worker", None)
    if worker is not None:
        worker.wait()
    for _ in range(5):
        QApplication.processEvents()


@pytest.fixture
def win(qapp):
    from views.main_window import MainWindow

    window = MainWindow()
    window.new_document("mm")
    yield window
    window.document.dirty = False
    window.close()


def test_viewport_clip_mirrors_ezdxf(win):
    from core.layouts import viewport_clip

    psp, vp = _sheet(win)
    assert viewport_clip(vp) is None                                   # no clip
    vp.dxf.clipping_boundary_handle = "FFFFFF"
    assert viewport_clip(vp) is None                                   # flag off: no clip
    vp.dxf.flags |= const.VSF_NON_RECTANGULAR_CLIPPING
    assert viewport_clip(vp) is None                                   # dangling: the frame
    rect = psp.add_lwpolyline([(60, 40), (140, 40), (140, 100), (60, 100)], close=True)
    vp.dxf.clipping_boundary_handle = rect.dxf.handle
    assert viewport_clip(vp) == (60.0, 40.0, 140.0, 100.0)
    shape = psp.add_lwpolyline([(60, 40), (140, 40), (150, 70), (140, 100),
                                (60, 100), (50, 70)], close=True)
    vp.dxf.clipping_boundary_handle = shape.dxf.handle
    assert viewport_clip(vp) is False                                  # a real shape
    bulged = psp.add_lwpolyline([(60, 40, 0, 0, 1), (140, 40), (140, 100), (60, 100)],
                                format="xyseb", close=True)
    vp.dxf.clipping_boundary_handle = bulged.dxf.handle
    assert viewport_clip(vp) is False                                  # arcs: not a rectangle


def test_a_dangling_clip_handle_pans_live_and_fires_no_regen(win):
    _psp, vp = _sheet(win, dangling=True)
    assert _drag(win, vp) == 0
    assert win.viewport._live_vp is not None


def test_a_rectangular_clip_pans_live_scissored_to_the_rectangle(win):
    psp, vp = _sheet(win)
    rect = psp.add_lwpolyline([(60, 40), (140, 40), (140, 100), (60, 100)], close=True)
    vp.dxf.flags |= const.VSF_NON_RECTANGULAR_CLIPPING
    vp.dxf.clipping_boundary_handle = rect.dxf.handle
    assert _drag(win, vp) == 0
    live = win.viewport._live_vp[0]
    assert live["rect"] == (60.0, 40.0, 140.0, 100.0)


def test_a_shaped_clip_keeps_the_baked_path(win):
    psp, vp = _sheet(win)
    shape = psp.add_lwpolyline([(60, 40), (140, 40), (150, 70), (140, 100),
                                (60, 100), (50, 70)], close=True)
    vp.dxf.flags |= const.VSF_NON_RECTANGULAR_CLIPPING
    vp.dxf.clipping_boundary_handle = shape.dxf.handle
    win.switch_layout("Layout1")
    win._activate_viewport(vp)
    assert win._vp_live_draw() is False


def test_a_full_turn_of_twist_is_no_twist(win):
    """Planos Constructivos' title-block viewport: view_twist_angle 720.
    One viewport that cannot go live keeps the whole sheet baked, so this
    one alone made every pan a regen."""
    from core.layouts import viewport_twist

    _psp, vp = _sheet(win, dangling=True)
    vp.dxf.view_twist_angle = 720.0
    assert viewport_twist(vp) == 0.0
    assert _drag(win, vp) == 0
    assert win.viewport._live_vp is not None
    vp.dxf.view_twist_angle = 15.0
    assert viewport_twist(vp) == 15.0
    win._vp_live_stop()
    assert win._vp_live_draw() is False                 # a real twist: the bake


def test_dragging_right_after_the_double_click_never_freezes_or_regens(win):
    """The live model used to be built on the first pan tick, on the GUI
    thread: 5.8 s frozen on Planos Constructivos. The activation now starts
    it in the background; a drag meanwhile fires no regen per tick, and the
    display catches up with the cursor the moment the scene lands."""
    from PySide6.QtWidgets import QApplication

    _psp, vp = _sheet(win, dangling=True)
    fired = []
    real = win.regen_in_memory
    win.regen_in_memory = lambda *a, **k: fired.append(1) or real(*a, **k)
    win.switch_layout("Layout1")
    win._activate_viewport(vp)
    worker = win._vp_live_worker
    assert worker is not None and worker.objectName() == "vp-live"
    fired.clear()
    for _ in range(5):                                # dragging already
        assert win.vp_view_pan(1.0, 0.5) is True
    assert fired == []
    worker.wait()
    for _ in range(5):
        QApplication.processEvents()
    assert win.viewport._live_vp is not None          # caught up, mid-gesture
    assert fired == []
