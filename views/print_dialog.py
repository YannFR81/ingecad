# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""PLOT dialog — paper, orientation, area, scale; PDF or system printer.

Kept to what a civil plan needs: pick the paper, plot the extents, the
current view or a window picked on the drawing, at Fit or a real 1:N metric
scale (drawing unit metres or millimetres), then save a vector PDF or send
to a printer.

Window (#52) works as AutoCAD's does: "Window <" closes the dialog, two
corners are picked on the drawing, and the dialog comes back with every
setting as it was and the window as the area. The dialog returns
:data:`PICK_WINDOW` and its :meth:`PrintDialog.state`; the main window
runs the pick and reopens it with that state.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QPushButton,
)

from core.i18n import tr
from views import file_dialogs
from formats import pdf_out

#: exec() result: the user asked to pick a window on the drawing.
PICK_WINDOW = 2


class PrintDialog(QDialog):
    def __init__(self, window, state: dict | None = None) -> None:
        super().__init__(window)
        self._window_rect = None
        self.window = window
        self.setWindowTitle(tr("Plot"))
        self.setMinimumWidth(320)
        form = QFormLayout(self)

        self.paper = QComboBox(self)
        self.paper.addItems(list(pdf_out.PAPER_SIZES_MM))
        self.orientation = QComboBox(self)
        self.orientation.addItem(tr("Landscape"), True)
        self.orientation.addItem(tr("Portrait"), False)
        self.area = QComboBox(self)
        self._layout_name = getattr(window, "_active_layout", "Model")
        is_layout_tab = (self._layout_name != "Model"
                         and window.document is not None)
        if is_layout_tab:
            # AutoCAD's contract: a layout plots at 1:1 — the sheet maps
            # mm-to-mm and every viewport prints at its exact scale.
            self.area.addItem(tr("Layout (sheet at 1:1)"), "layout")
        self.area.addItem(tr("Extents"), "extents")
        self.area.addItem(tr("Current view"), "view")
        self.area.addItem(tr("Window"), "window")
        self.pick_btn = QPushButton(tr("Window <"), self)
        self.pick_btn.setToolTip(tr("Pick two corners of the area to plot"))
        self.pick_btn.clicked.connect(self._pick_window)
        self.area.currentIndexChanged.connect(self._on_area_changed)
        self.scale = QComboBox(self)
        self.scale.addItem(tr("Fit to paper"), None)
        for n in pdf_out.COMMON_SCALES:
            self.scale.addItem(f"1:{n}", n)
        self.units = QComboBox(self)
        self.units.addItem(tr("Meters"), 1000.0)       # 1 unit = 1000 mm
        self.units.addItem(tr("Millimeters"), 1.0)

        # Plot style table (pen assignments): the layout's own by default,
        # as the Page Setup left it; the folder's tables to choose from.
        from core import plotstyles

        self.style = QComboBox(self)
        self.style.addItem(tr("None"), "")
        for name in plotstyles.available():
            self.style.addItem(name, name)
        current = ""
        if window.document is not None:
            try:
                layout = (window.document.doc.layouts.get(self._layout_name)
                          if self._layout_name != "Model"
                          else window.document.doc.modelspace())
                current = str(layout.dxf_layout.dxf.get("current_style_sheet", "") or "")
            except Exception:                # noqa: BLE001 - no table then
                current = ""
        idx = self.style.findData(current)
        if idx < 0 and current:
            self.style.addItem(current, current)
            idx = self.style.count() - 1
        self.style.setCurrentIndex(max(idx, 0))

        form.addRow(tr("Paper size"), self.paper)
        form.addRow(tr("Orientation"), self.orientation)
        form.addRow(tr("Plot area"), self.area)
        form.addRow("", self.pick_btn)
        form.addRow(tr("Scale"), self.scale)
        form.addRow(tr("Drawing unit"), self.units)
        form.addRow(tr("Plot style table"), self.style)

        buttons = QDialogButtonBox(self)
        pdf_btn = QPushButton(tr("Save PDF..."), self)
        printer_btn = QPushButton(tr("Print..."), self)
        buttons.addButton(pdf_btn, QDialogButtonBox.AcceptRole)
        buttons.addButton(printer_btn, QDialogButtonBox.ActionRole)
        buttons.addButton(QDialogButtonBox.Cancel)
        buttons.rejected.connect(self.reject)
        pdf_btn.clicked.connect(self._to_pdf)
        printer_btn.clicked.connect(self._to_printer)
        form.addRow(buttons)
        self._pdf_btn, self._printer_btn = pdf_btn, printer_btn
        if state:
            self._restore(state)
        self._on_area_changed()

    # -- Window: leave, pick, come back -----------------------------------------
    def state(self) -> dict:
        """Everything the user set, to reopen the dialog as it was."""
        return {"paper": self.paper.currentIndex(),
                "orientation": self.orientation.currentIndex(),
                "area": self.area.currentData(),
                "scale": self.scale.currentIndex(),
                "units": self.units.currentIndex(),
                "style": self.style.currentIndex(),
                "window": self._window_rect}

    def _restore(self, state: dict) -> None:
        for combo, key in ((self.paper, "paper"), (self.orientation, "orientation"),
                           (self.scale, "scale"), (self.units, "units"),
                           (self.style, "style")):
            if state.get(key) is not None and 0 <= state[key] < combo.count():
                combo.setCurrentIndex(state[key])
        self._window_rect = state.get("window")
        idx = self.area.findData(state.get("area"))
        if idx >= 0:
            self.area.setCurrentIndex(idx)

    def _pick_window(self) -> None:
        idx = self.area.findData("window")
        self.area.setCurrentIndex(idx)
        self.done(PICK_WINDOW)

    # -- plot parameters -------------------------------------------------------
    def _layout_mode(self) -> bool:
        return self.area.currentData() == "layout"

    def _on_area_changed(self) -> None:
        # In layout mode paper/orientation/scale come from the page setup.
        manual = not self._layout_mode()
        for widget in (self.paper, self.orientation, self.scale, self.units):
            widget.setEnabled(manual)
        # Window: nothing to plot until a window has been picked
        window_area = self.area.currentData() == "window"
        self.pick_btn.setVisible(window_area)
        ready = not window_area or self._window_rect is not None
        self._pdf_btn.setEnabled(ready)
        self._printer_btn.setEnabled(ready)

    def _mm_per_unit(self):
        n = self.scale.currentData()
        if n is None:
            return None                         # fit
        return self.units.currentData() / n     # 1:N metric

    def _area_rect(self):
        if self.area.currentData() == "view":
            return self.window.viewport._view_world_rect()
        if self.area.currentData() == "window":
            return self._window_rect
        return None                             # extents

    def _ctb(self) -> str:
        return self.style.currentData() or ""

    def _plot_on(self, printer) -> None:
        if self._layout_mode():
            pdf_out.plot_layout(self.window.document, printer,
                                self._layout_name, ctb=self._ctb())
            return
        pdf_out.plot(
            self.window.document, printer,
            layout_name=getattr(self.window, "_active_layout", None),
            area=self._area_rect(),
            mm_per_unit=self._mm_per_unit(), ctb=self._ctb())

    # -- outputs ---------------------------------------------------------------
    def _to_pdf(self) -> None:
        name = self.window.document.name if self.window.document else "plano"
        path, _f = file_dialogs.get_save_file(
            self, tr("Save PDF"), f"{name}.pdf", "PDF (*.pdf)",
            preferred=self.window.document.path if self.window.document else None)
        if not path:
            return
        if self._layout_mode():
            (width, height), _sheet = pdf_out.layout_sheet(
                self.window.document, self._layout_name)
            printer = pdf_out.make_pdf_printer_mm(path, width, height)
        else:
            printer = pdf_out.make_pdf_printer(
                path, self.paper.currentText(),
                landscape=self.orientation.currentData())
        self._plot_on(printer)
        self.window.command_line.echo(tr("PDF saved: {p}", p=path))
        self.accept()

    def _to_printer(self) -> None:
        from PySide6.QtGui import QPageLayout, QPageSize
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter

        printer = QPrinter(QPrinter.HighResolution)
        if self._layout_mode():
            from PySide6.QtCore import QSizeF

            (width, height), _sheet = pdf_out.layout_sheet(
                self.window.document, self._layout_name)
            printer.setPageSize(QPageSize(QSizeF(width, height),
                                          QPageSize.Millimeter))
        else:
            size_id = getattr(QPageSize, self.paper.currentText(), QPageSize.A4)
            printer.setPageSize(QPageSize(size_id))
            printer.setPageOrientation(
                QPageLayout.Landscape if self.orientation.currentData()
                else QPageLayout.Portrait)
        dlg = QPrintDialog(printer, self)
        if dlg.exec():
            self._plot_on(printer)
            self.accept()
