# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Plot to PDF or a system printer, at a real scale (Phase 8).

The ezdxf drawing frontend replays the layout into a QGraphicsScene through
PyQtBackend (true vector graphics — lines stay lines in the PDF), and
QGraphicsScene.render maps a world-area rectangle onto the printable page at
the requested scale. 1:N metric scaling: one paper mm equals N drawing mm, so
a drawing in metres plots 1:100 with ``mm_per_unit = 1000 / 100``.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter

# Paper sizes in mm (portrait), the ones a civil plan actually uses.
PAPER_SIZES_MM = {
    "A4": (210.0, 297.0),
    "A3": (297.0, 420.0),
    "A2": (420.0, 594.0),
    "A1": (594.0, 841.0),
    "A0": (841.0, 1189.0),
    "Letter": (215.9, 279.4),
}


class _PlotRenderContext:
    """Built by :func:`_plot_context`: ezdxf's RenderContext with a .ctb's
    pens applied to every colour -- explicit colour, grayscale, screening --
    including true-colour entities (by their nearest ACI, as AutoCAD plots
    them). Lineweights come through ezdxf itself (``plot_styles``)."""


def _plot_context(doc, table):
    from ezdxf import colors as _colors
    from ezdxf.addons.drawing import RenderContext

    if table is None or table.named:
        return RenderContext(doc, export_mode=True)

    class PlotRenderContext(RenderContext):
        def _true_entity_color(self, true_color, aci):
            if true_color is not None:
                rgb = tuple(true_color)
                aci = _nearest_aci(rgb)
            elif 0 < aci < 256:
                rgb = _colors.int2rgb(_colors.DXF_DEFAULT_COLORS[aci])
                if aci == 7:
                    rgb = _hex_to_rgb(self.current_layout_properties.default_color)
            else:
                return self.current_layout_properties.default_color
            return "#%02x%02x%02x" % tuple(table.pen_color(aci, rgb))

    return PlotRenderContext(doc, ctb=table.table, export_mode=True)


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _nearest_aci(rgb) -> int:
    from ezdxf import colors as _colors

    best, best_d = 7, None
    for aci in range(1, 256):
        r, g, b = _colors.int2rgb(_colors.DXF_DEFAULT_COLORS[aci])
        d = (r - rgb[0]) ** 2 + (g - rgb[1]) ** 2 + (b - rgb[2]) ** 2
        if best_d is None or d < best_d:
            best, best_d = aci, d
    return best


def plot_style_for(document, layout_name: str | None, ctb: str | None):
    """The table to plot with: the caller's choice, else the layout's own
    ``current_style_sheet`` (Page Setup), else none; an empty name means none."""
    from core import plotstyles

    if ctb is None:
        layout = None
        if layout_name and layout_name in document.doc.layouts:
            layout = document.doc.layouts.get(layout_name)
        elif not layout_name or layout_name == "Model":
            layout = document.doc.modelspace()
        try:
            ctb = str(layout.dxf_layout.dxf.get("current_style_sheet", "") or "")
        except Exception:                 # noqa: BLE001 - no layout, no table
            ctb = ""
    return plotstyles.load(ctb) if ctb else None


def build_graphics_scene(document, layout_name: str | None = None,
                         ctb: str | None = None):
    """Replay a layout into a QGraphicsScene (vector items, world coords).

    ``ctb`` names the plot style table (see core.plotstyles); None takes the
    layout's own, "" plots with none.
    """
    from ezdxf.addons.drawing.pyqt import PyQtBackend
    from PySide6.QtWidgets import QGraphicsScene

    from render.backend import TolerantFrontend, pick_layout

    if layout_name and layout_name != "Model" \
            and layout_name in document.doc.layouts:
        layout = document.doc.layouts.get(layout_name)
    else:
        layout, _name = pick_layout(document)
    scene = QGraphicsScene()
    backend = PyQtBackend(scene)
    # export_mode: render as plotted — layers with Plot off are skipped
    # (they still display on screen, exactly AutoCAD's Plot column).
    context = _plot_context(document.doc,
                            plot_style_for(document, layout_name, ctb))
    # The canvas's frontend, so the plot obeys the same rules the screen
    # does: a dimension's block drawn in the dimension's colour (ISO-25 is
    # ByBlock), MULTILEADER content instead of its baked proxy picture, a
    # malformed entity skipped instead of blanking the page.
    # Paper is white: AutoCAD plots model space on white too, never on the
    # screen's dark background, and ACI 7 follows the background to black
    # (#62: a model-space PDF came out dark blue with white lines).
    from ezdxf.addons.drawing.properties import LayoutProperties

    sheet = LayoutProperties.from_layout(layout)
    sheet.set_colors("#ffffff")
    # POINT symbols at the size the canvas shows them ($PDSIZE <= 0 is
    # relative to the view, which ezdxf alone draws 1 unit wide)
    from ezdxf.addons.drawing.config import Configuration

    from render.backend import point_size

    size = point_size(document)
    config = Configuration() if size is None else Configuration(pdsize=size)
    TolerantFrontend(context, backend, config).draw_layout(
        layout, finalize=False, layout_properties=sheet)
    if getattr(layout, "is_any_paperspace", False):
        # Viewport frames plot only when the page setup asks for them
        # (plot_layout_flags bit 1, off by AutoCAD's own default — clean
        # sheets are what a signed plan wants).
        try:
            flags = int(layout.dxf.get_default("plot_layout_flags"))
        except Exception:
            flags = 0
        if flags & 1:
            from render.backend import _draw_viewport_borders

            _draw_viewport_borders(layout, context, backend)
    backend.finalize()
    return scene


def scene_extents(scene) -> QRectF:
    """World-coordinate bounding rect of everything in the graphics scene."""
    return scene.itemsBoundingRect()


_PT_TO_MM = 25.4 / 72.0
# Thinnest plotted stroke: AutoCAD's fine-pen practice (never a 0-width
# hairline that disappears on high-resolution devices).
_MIN_PLOT_MM = 0.1


def _use_physical_pens(scene) -> None:
    """Convert the backend's cosmetic pens (points, fixed device pixels —
    a screen convention) into physical widths in scene units.

    Only valid when the scene units are paper mm (a layout plot): the
    0.25 mm default lineweight arrives as a 0.708 pt cosmetic pen, which a
    1200 dpi printer would render as an invisible 0.015 mm hairline.
    """
    from PySide6.QtCore import Qt

    for item in scene.items():
        if not hasattr(item, "pen"):
            continue
        pen = item.pen()
        if pen.style() == Qt.NoPen:
            continue
        pen.setCosmetic(False)
        pen.setWidthF(max(pen.widthF() * _PT_TO_MM, _MIN_PLOT_MM))
        item.setPen(pen)


def plot(document, printer, layout_name: str | None = None,
         area: tuple[float, float, float, float] | None = None,
         mm_per_unit: float | None = None,
         physical_pens: bool = False, ctb: str | None = None,
         painter: QPainter | None = None) -> None:
    """Render onto ``printer`` (PDF file or a physical printer).

    ``area`` is the world rect (x0, y0, x1, y1) to plot; None plots the
    extents. ``mm_per_unit`` fixes the scale (paper mm per drawing unit);
    None fits the area to the page. The plot is centred on the page.
    ``ctb`` is the plot style table (None: the layout's own). ``painter``
    lets PUBLISH draw several pages with one painter; None opens and closes
    its own.
    """
    scene = build_graphics_scene(document, layout_name, ctb)
    if physical_pens:
        _use_physical_pens(scene)
    if area is None:
        r = scene_extents(scene)
        area = (r.left(), r.top(), r.right(), r.bottom())
    x0, y0, x1, y1 = area
    aw, ah = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)

    own_painter = painter is None
    if own_painter:
        painter = QPainter(printer)
    painter.save()
    try:
        page = printer.pageRect(printer.Unit.DevicePixel)
        px_per_mm = printer.resolution() / 25.4
        if mm_per_unit is None:
            px_per_unit = min(page.width() / aw, page.height() / ah)
        else:
            px_per_unit = mm_per_unit * px_per_mm
        tw, th = aw * px_per_unit, ah * px_per_unit
        tx = page.x() + (page.width() - tw) / 2.0
        ty = page.y() + (page.height() - th) / 2.0

        # DXF is y-up, the page is y-down: flip the painter and hand render()
        # a target rect expressed in the flipped coordinate system.
        painter.translate(0.0, page.y() * 2 + page.height())
        painter.scale(1.0, -1.0)
        target = QRectF(tx, page.y() * 2 + page.height() - (ty + th), tw, th)
        source = QRectF(x0, y0, aw, ah)
        scene.render(painter, target, source)
    finally:
        painter.restore()
        if own_painter:
            painter.end()


def layout_sheet(document, layout_name: str):
    """((width_mm, height_mm), sheet_rect) of a paperspace layout's paper."""
    from core.layouts import paper_frame

    layout = document.doc.layouts.get(layout_name)
    sheet = paper_frame(layout)["sheet"]
    x0, y0, x1, y1 = sheet
    return (x1 - x0, y1 - y0), sheet


def plot_layout(document, printer, layout_name: str,
                ctb: str | None = None, painter: QPainter | None = None) -> None:
    """Plot a paperspace layout at 1:1 — the sheet maps mm-to-mm onto the
    page, so every viewport prints at its exact scale (the AutoCAD
    contract: layouts plot at 1:1, the scale lives in the viewports)."""
    _size, sheet = layout_sheet(document, layout_name)
    printer.setFullPage(True)   # the sheet IS the page; margins are drawn
    plot(document, printer, layout_name, area=sheet, mm_per_unit=1.0,
         physical_pens=True, ctb=ctb, painter=painter)   # paper mm on a layout


def publish(document, layout_names, path: str, ctb: str | None = None) -> int:
    """PUBLISH: several layouts into ONE multi-page PDF, each page the
    size of its sheet, each layout at 1:1. Returns the number of pages."""
    from PySide6.QtCore import QSizeF
    from PySide6.QtGui import QPageSize

    names = [n for n in layout_names if n in document.doc.layouts and n != "Model"]
    if not names:
        return 0
    (width, height), _sheet = layout_sheet(document, names[0])
    printer = make_pdf_printer_mm(path, width, height)
    painter = QPainter(printer)
    try:
        for index, name in enumerate(names):
            if index:
                (width, height), _sheet = layout_sheet(document, name)
                printer.setPageSize(QPageSize(QSizeF(width, height),
                                              QPageSize.Millimeter))
                printer.newPage()
            plot_layout(document, printer, name, ctb=ctb, painter=painter)
    finally:
        painter.end()
    return len(names)


def make_pdf_printer_mm(path: str, width_mm: float, height_mm: float):
    """A vector-PDF QPrinter with an exact page size in mm (layout plots)."""
    from PySide6.QtCore import QSizeF
    from PySide6.QtGui import QPageSize
    from PySide6.QtPrintSupport import QPrinter

    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(path)
    printer.setPageSize(QPageSize(QSizeF(width_mm, height_mm),
                                  QPageSize.Millimeter))
    printer.setFullPage(True)
    return printer


def make_pdf_printer(path: str, paper: str = "A4", landscape: bool = True):
    """A QPrinter configured for vector PDF output."""
    from PySide6.QtGui import QPageLayout, QPageSize
    from PySide6.QtPrintSupport import QPrinter

    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(path)
    size_id = getattr(QPageSize, paper, QPageSize.A4)
    printer.setPageSize(QPageSize(size_id))
    printer.setPageOrientation(
        QPageLayout.Landscape if landscape else QPageLayout.Portrait)
    return printer
