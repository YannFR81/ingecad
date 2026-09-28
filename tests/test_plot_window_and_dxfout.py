# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""PLOT's Window area (#52) and File > Export > DXF / DXFOUT (#51)."""
from __future__ import annotations

from pathlib import Path

import ezdxf
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent


def _window(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.resize(1000, 700)
    win.new_document()
    from core import actions
    win.tools._execute(actions.add_line((0, 0), (100, 50)))
    qapp.processEvents()
    return win


def _mouse(vp, kind, button, x, y):
    event = QMouseEvent(kind, QPointF(x, y), vp.mapToGlobal(QPointF(x, y)),
                        button, button if kind != QMouseEvent.Type.MouseButtonRelease
                        else Qt.NoButton, Qt.NoModifier)
    if kind == QMouseEvent.Type.MouseButtonPress:
        vp.mousePressEvent(event)
    else:
        vp.mouseReleaseEvent(event)


def test_window_leaves_the_dialog_picks_on_the_canvas_and_comes_back(qapp, monkeypatch):
    from PySide6.QtCore import QTimer

    from views import print_dialog

    win = _window(qapp)
    try:
        opened = []
        real_exec = print_dialog.PrintDialog.exec

        def fake_exec(dialog):
            opened.append(dialog)
            if len(opened) == 1:
                dialog.scale.setCurrentIndex(3)      # a setting to carry over
                QTimer.singleShot(0, dialog._pick_window)
            else:
                QTimer.singleShot(0, dialog.reject)
            return real_exec(dialog)

        monkeypatch.setattr(print_dialog.PrintDialog, "exec", fake_exec)
        win._plot_dialog()
        assert len(opened) == 1 and win.viewport._zoom_window, "no pick started"
        vp = win.viewport
        _mouse(vp, QMouseEvent.Type.MouseButtonPress, Qt.LeftButton, 100, 100)
        _mouse(vp, QMouseEvent.Type.MouseButtonRelease, Qt.LeftButton, 400, 300)
        assert len(opened) == 2, "the dialog did not come back"
        again = opened[1]
        assert again.area.currentData() == "window"
        assert again.scale.currentIndex() == 3, "the settings were lost"
        x0, y0, x1, y1 = again._area_rect()
        wx0, wy1 = vp.view.screen_to_world(100, 100)
        wx1, wy0 = vp.view.screen_to_world(400, 300)
        assert (x0, y0, x1, y1) == pytest.approx((wx0, wy0, wx1, wy1))
        assert again._pdf_btn.isEnabled()
    finally:
        win.document.dirty = False
        win.close()


def test_right_click_cancels_the_pick_and_the_dialog_returns_without_a_window(qapp, monkeypatch):
    from PySide6.QtCore import QTimer

    from views import print_dialog

    win = _window(qapp)
    try:
        opened = []
        real_exec = print_dialog.PrintDialog.exec

        def fake_exec(dialog):
            opened.append(dialog)
            QTimer.singleShot(0, dialog._pick_window if len(opened) == 1 else dialog.reject)
            return real_exec(dialog)

        monkeypatch.setattr(print_dialog.PrintDialog, "exec", fake_exec)
        win._plot_dialog()
        _mouse(win.viewport, QMouseEvent.Type.MouseButtonPress, Qt.RightButton, 50, 50)
        assert len(opened) == 2
        assert opened[1]._area_rect() is None
        assert not opened[1]._pdf_btn.isEnabled(), "nothing to plot, yet PDF was enabled"
    finally:
        win.document.dirty = False
        win.close()


def test_a_plain_zoom_window_still_zooms(qapp):
    win = _window(qapp)
    try:
        vp = win.viewport
        before = vp.view.scale
        vp.start_zoom_window()
        _mouse(vp, QMouseEvent.Type.MouseButtonPress, Qt.LeftButton, 100, 100)
        _mouse(vp, QMouseEvent.Type.MouseButtonRelease, Qt.LeftButton, 200, 180)
        assert vp.view.scale > before
    finally:
        win.document.dirty = False
        win.close()


def test_the_window_area_plots_that_rectangle(qapp, tmp_path, monkeypatch):
    from formats import pdf_out
    from views.print_dialog import PrintDialog

    win = _window(qapp)
    try:
        dialog = PrintDialog(win, {"area": "window", "window": (10.0, 5.0, 60.0, 30.0)})
        seen = {}
        monkeypatch.setattr(pdf_out, "plot",
                            lambda *a, **k: seen.update(area=k.get("area")))
        dialog._plot_on(object())
        assert seen["area"] == (10.0, 5.0, 60.0, 30.0)
    finally:
        win.document.dirty = False
        win.close()


def test_dxfout_writes_a_copy_and_keeps_the_open_file(qapp, tmp_path):
    win = _window(qapp)
    try:
        original = tmp_path / "plano.dxf"
        win._write_document(original)
        said = []
        win.command_line.echo = lambda text, *a, **k: said.append(text)
        out = tmp_path / "para_blender"            # no extension given
        win._on_command_submitted(f"DXFOUT {out}")
        written = out.with_suffix(".dxf")
        assert written.is_file()
        back = ezdxf.readfile(written)
        assert len(back.modelspace().query("LINE")) == 1
        assert win.document.path == original, "export changed the open file"
        assert win.document.doc.filename in (None, str(original))
        assert any("Exported" in s for s in said), said
    finally:
        win.document.dirty = False
        win.close()


def test_file_export_dxf_is_in_the_menu(qapp):
    win = _window(qapp)
    try:
        bar_actions = win._menu_bar.actions()      # kept local (PySide lifetime)
        file_menu = None
        for action in bar_actions:
            menu = action.menu()
            if menu is not None and action.text().replace("&", "") in ("File", "Archivo"):
                file_menu = menu
                break
        assert file_menu is not None
        file_actions = file_menu.actions()
        export = None
        for action in file_actions:
            menu = action.menu()
            if menu is not None and action.text() in ("Export", "Exportar"):
                export = menu
                break
        assert export is not None, "no Export submenu"
        assert any(a.text() == "DXF..." for a in export.actions())
    finally:
        win.document.dirty = False
        win.close()
