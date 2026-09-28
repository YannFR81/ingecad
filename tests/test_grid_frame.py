# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The grid and the world axes are in EVERY frame, including the one that
rebuilds the grid.

Rafael (video review, 11:41): "activo la grid y no se ve... en cuanto paso
el ratón se reescala"; Marco's screen recordings (2026-09-27): with the grid
on, the grid and the red/green axes vanished after a wheel notch and came
back on the next repaint. The frame that rebuilt the grid's buffer -- the
first after F7, a zoom or a pan across a cell -- built it with ``_make_vao``,
which releases the shader program, and then drew the grid and the axes with
no program bound: nothing. The frame after, with nothing to rebuild, was
fine, so it looked like a flicker.

Pixels, from the frame that does the rebuild: the view changes WITHOUT a
repaint, so the grab itself is that frame. Needs a real GL context (Xvfb in
CI, X11 locally); offscreen has none.
"""
from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtTest import QTest

AXIS_X = (122, 46, 46)
AXIS_Y = (41, 107, 46)


@pytest.fixture
def canvas(qapp):
    if QGuiApplication.platformName() in ("offscreen", "minimal"):
        pytest.skip("no OpenGL on this platform: the pixels need a real context")
    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document("m")
    win.resize(1000, 700)
    win.show()
    QTest.qWaitForWindowExposed(win, 5000)
    for _ in range(5):
        qapp.processEvents()
        QTest.qWait(10)
    win.viewport.grid_on = True
    yield win.viewport
    win.document.dirty = False
    win.close()


def _pixels(viewport) -> np.ndarray:
    img = viewport.grabFramebuffer().convertToFormat(QImage.Format_RGB888)
    rows = np.frombuffer(img.constBits(), np.uint8).reshape(
        img.height(), img.bytesPerLine())[:, :img.width() * 3]
    return rows.reshape(img.height(), img.width(), 3).astype(int)


def _count(pixels, rgb, tol=6) -> int:
    return int(np.all(np.abs(pixels - rgb) <= tol, axis=2).sum())


def _grid_and_axes(viewport) -> tuple[int, int, int]:
    pixels = _pixels(viewport)
    grid = sum(_count(pixels, rgb[:3])
               for rgb in (viewport.GRID_MINOR, viewport.GRID_MAJOR))
    return grid, _count(pixels, AXIS_X), _count(pixels, AXIS_Y)


def test_the_frame_that_rebuilds_the_grid_still_draws_it(canvas):
    view = canvas.view
    _grid_and_axes(canvas)                  # builds the grid for this view
    grid, axis_x, axis_y = _grid_and_axes(canvas)
    if not (grid > 0 and axis_x > 0 and axis_y > 0):
        # A zero only counts when the control is not zero: this GL (CI's
        # software renderer under Xvfb) draws no grid in colours this test
        # can count even in the frame that needs no rebuild, so the frame
        # under test cannot be judged here. Real GL (X11, Wayland) can.
        pytest.skip("the control frame shows no measurable grid on this GL")
    # a wheel notch and a pan: each one a new set of grid cells, each one
    # grabbed as the very frame that rebuilds the grid
    for step in range(8):
        if step % 2:
            view.pan_pixels(37, 23)
        else:
            view.zoom_at(canvas.width() / 2, canvas.height() / 2,
                         1.2 if step < 4 else 1 / 1.2)
        grid, axis_x, axis_y = _grid_and_axes(canvas)
        assert grid > 0, f"step {step}: no grid in the rebuilding frame"
        assert axis_x > 0 and axis_y > 0, f"step {step}: no axes"
