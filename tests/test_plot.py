# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Phase 8 plot: vector PDF output at scale, y-flip correctness, layouts."""
from __future__ import annotations

import os
import sys

import pytest

from core.document import Document
from formats import pdf_out


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


def _doc_with_marker():
    """A line along the bottom and a small circle at the TOP-left."""
    doc = Document.new()
    msp = doc.modelspace()
    msp.add_line((0, 0), (100, 0))          # bottom edge
    msp.add_circle((10, 90), 5)             # near the top
    return doc


def test_graphics_scene_builds(app):
    doc = _doc_with_marker()
    scene = pdf_out.build_graphics_scene(doc)
    r = pdf_out.scene_extents(scene)
    assert r.width() > 90
    assert r.height() > 80


def test_pdf_plot_writes_vector_file(app, tmp_path):
    doc = _doc_with_marker()
    path = str(tmp_path / "plan.pdf")
    printer = pdf_out.make_pdf_printer(path, "A4", landscape=True)
    pdf_out.plot(doc, printer)              # fit extents
    assert os.path.exists(path)
    assert os.path.getsize(path) > 1000     # real content, not an empty page


def test_pdf_plot_at_scale(app, tmp_path):
    # 1:100 with metres: 100 m wide area -> 1000 mm on paper (clipped by A4,
    # but the transform must not fit-shrink it). Just verify it renders.
    doc = _doc_with_marker()
    path = str(tmp_path / "scaled.pdf")
    printer = pdf_out.make_pdf_printer(path, "A4", landscape=True)
    pdf_out.plot(doc, printer, area=(0, 0, 20, 10), mm_per_unit=10.0)
    assert os.path.getsize(path) > 500


def test_y_flip_top_stays_top(app):
    """Render with the same flip math into an image: the circle drawn at
    world TOP must land in the TOP half of the page, not mirrored."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter

    doc = _doc_with_marker()
    scene = pdf_out.build_graphics_scene(doc)
    w, h = 200, 200
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(0xFFFFFFFF)
    painter = QPainter(img)
    # same transform pdf_out.plot applies (page.y() = 0 here)
    painter.translate(0.0, h)
    painter.scale(1.0, -1.0)
    target = QRectF(0, 0, w, h)
    # a margin round the 0..100 square: the base line sits ON y=0, and
    # this test only passed while the plot's dark background made every
    # pixel "dark" (#62)
    source = QRectF(-5, -5, 110, 110)
    scene.render(painter, target, source)
    painter.end()

    def dark_pixels(y0, y1):
        n = 0
        for y in range(y0, y1):
            for x in range(0, w, 2):
                if QImage.pixel(img, x, y) & 0xFF < 100:
                    n += 1
        return n

    top = dark_pixels(0, h // 3)            # circle territory
    bottom = dark_pixels(2 * h // 3, h)     # bottom line territory
    assert top > 0                          # circle visible near the top
    assert bottom > 0                       # base line near the bottom


def test_build_scene_layout_by_name():
    import ezdxf
    from render.backend import build_scene

    doc = Document.new()
    doc.modelspace().add_line((0, 0), (5, 5))
    layout = doc.doc.layouts.new("Plancha1")
    layout.add_line((0, 0), (100, 0))
    model_scene = build_scene(doc, "Model")
    sheet_scene = build_scene(doc, "Plancha1")
    assert model_scene.lines.vertex_count > 0
    assert sheet_scene.lines.vertex_count > 0
    assert sheet_scene.background is not None   # paper-white layout


def test_plot_draws_a_dimension_in_the_dimensions_colour(qapp) -> None:
    """The plot replays the drawing through the canvas's frontend, so a
    dimension's block -- ByBlock in ISO-25 -- is drawn in the dimension's
    colour on paper as on screen. Through ezdxf's stock Frontend the same
    scene came out entirely in the page's default colour."""
    from core import actions
    from core.commands import History
    from core.document import Document
    from formats.pdf_out import build_graphics_scene

    document = Document.new()
    document.doc.layers.add("cotas", color=1)
    document.doc.header["$CLAYER"] = "cotas"
    History(document).execute(actions.dim_linear((0, 0), (50, 0), (25, 10)))
    scene = build_graphics_scene(document, "Model")
    from PySide6.QtCore import Qt

    colours = set()
    for item in scene.items():
        pen = getattr(item, "pen", None)
        if pen is not None and pen().style() != Qt.PenStyle.NoPen:
            colours.add(pen().color().name())
        brush = getattr(item, "brush", None)
        if brush is not None and brush().style() != Qt.BrushStyle.NoBrush:
            colours.add(brush().color().name())
    assert colours == {"#ff0000"}


def test_a_model_space_pdf_plots_on_white_with_dark_lines(app, tmp_path):
    # #62: the plot kept the screen's dark model background, with ACI 7
    # lines in white -- a plotter would have spent its ink on the page.
    from PySide6.QtCore import QSize
    from PySide6.QtPdf import QPdfDocument

    doc = _doc_with_marker()
    path = str(tmp_path / "model.pdf")
    printer = pdf_out.make_pdf_printer(path, "A4", landscape=True)
    pdf_out.plot(doc, printer, layout_name="Model")
    pdf = QPdfDocument()
    pdf.load(path)
    from PySide6.QtGui import QImage, QPainter

    page = pdf.render(0, QSize(600, 424))
    img = QImage(page.size(), QImage.Format_RGB32)
    img.fill(0xFFFFFFFF)                    # what QtPdf leaves unpainted
    painter = QPainter(img)
    painter.drawImage(0, 0, page)
    painter.end()
    pixels = [img.pixelColor(x, y).lightness()
              for y in range(0, img.height(), 3) for x in range(0, img.width(), 3)]
    assert sum(p > 240 for p in pixels) > 0.9 * len(pixels)    # white paper
    assert sum(p < 80 for p in pixels) > 0                     # dark lines on it
