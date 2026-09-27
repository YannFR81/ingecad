# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The right sidebar folds away and comes back with one click (#47).

As in IngeTrazo: a slim handle sits ON the line where the sidebar is
resized, half-way down the drawing; a click folds the sidebar and leaves the
handle at the window's edge, a second click brings it back at the width it
had. View > Sidebar (Ctrl+F5) is the same toggle, and the next session opens
the way this one closed. Clicked and pressed for real, not called.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest

from views.main_window import SETTING_SIDEBAR_SHOWN, SETTING_SIDEBAR_WIDTH


@pytest.fixture
def clean_settings():
    settings = QSettings()
    for key in (SETTING_SIDEBAR_SHOWN, SETTING_SIDEBAR_WIDTH):
        settings.remove(key)
    yield
    for key in (SETTING_SIDEBAR_SHOWN, SETTING_SIDEBAR_WIDTH):
        settings.remove(key)


def _window(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document("m")
    win.resize(1200, 800)
    win.show()
    win.activateWindow()
    QTest.qWaitForWindowActive(win, 5000)
    win.viewport.setFocus()
    _settle(qapp)
    return win


def _settle(qapp):
    for _ in range(3):
        qapp.processEvents()
        QTest.qWait(10)


def _close(win):
    win.document.dirty = False
    win.close()


def _click(qapp, win):
    QTest.mouseClick(win._sidebar_handle, Qt.LeftButton)
    _settle(qapp)


def _drawing_edge(win) -> QPoint:
    return win.viewport.mapTo(win, QPoint(win.viewport.width(), 0))


def test_the_handle_sits_on_the_resize_line_and_folds_the_sidebar(qapp,
                                                                  clean_settings):
    win = _window(qapp)
    try:
        dock, btn = win._layers_dock, win._sidebar_handle
        assert dock.isVisible() and btn.isVisible()
        # on the line between the drawing and the sidebar, half-way down
        centre = btn.geometry().center()
        assert abs(centre.x() - _drawing_edge(win).x()) <= 1
        middle = _drawing_edge(win).y() + win.viewport.height() // 2
        assert abs(centre.y() - middle) <= 1
        # the user widens the sidebar before folding it
        win.resizeDocks([dock], [360], Qt.Horizontal)
        _settle(qapp)
        width = dock.width()
        assert width > 300

        _click(qapp, win)
        assert not dock.isVisible()
        assert not win._act_sidebar.isChecked()
        # the drawing takes the room; the handle waits at the window's edge,
        # clear of the frameless window's resize margin, still clickable
        assert btn.isVisible()
        assert btn.geometry().right() < win.width() - win.RESIZE_MARGIN + 1
        assert btn.geometry().right() > win.width() - 40

        _click(qapp, win)
        assert dock.isVisible()
        assert abs(dock.width() - width) <= 2
        assert abs(btn.geometry().center().x() - _drawing_edge(win).x()) <= 1
    finally:
        _close(win)


def test_ctrl_f5_and_the_view_menu_are_the_same_toggle(qapp, clean_settings):
    win = _window(qapp)
    try:
        dock = win._layers_dock
        QTest.keySequence(win, QKeySequence("Ctrl+F5"))
        _settle(qapp)
        assert not dock.isVisible()
        bar_actions = win._menu_bar.actions()
        view = next(a for a in bar_actions
                    if a.text().replace("&", "") == "View").menu()
        view_actions = view.actions()
        entry = next(a for a in view_actions if a.text() == "Sidebar")
        assert entry.isChecked() is False
        entry.trigger()
        _settle(qapp)
        assert dock.isVisible()
        QTest.keySequence(win, QKeySequence("Ctrl+F5"))
        _settle(qapp)
        assert not dock.isVisible()
    finally:
        _close(win)


def test_a_command_that_opens_a_sidebar_tab_unfolds_it(qapp, clean_settings):
    win = _window(qapp)
    try:
        _click(qapp, win)
        assert not win._layers_dock.isVisible()
        win._on_command_submitted("LA")
        _settle(qapp)
        assert win._layers_dock.isVisible()
        assert win._sidebar_tabs.currentWidget() is win._layers_panel
        assert win._act_sidebar.isChecked()
    finally:
        _close(win)


def test_the_next_session_opens_the_way_this_one_closed(qapp, clean_settings):
    win = _window(qapp)
    try:
        win.resizeDocks([win._layers_dock], [340], Qt.Horizontal)
        _settle(qapp)
        width = win._layers_dock.width()
        _click(qapp, win)
    finally:
        _close(win)
    win = _window(qapp)
    try:
        assert not win._layers_dock.isVisible()
        assert win._sidebar_handle.isVisible()
        _click(qapp, win)
        assert win._layers_dock.isVisible()
        assert abs(win._layers_dock.width() - width) <= 2
    finally:
        _close(win)


def test_clean_screen_hides_the_handle_and_gives_it_back(qapp, clean_settings):
    win = _window(qapp)
    try:
        QTest.keySequence(win, QKeySequence("Ctrl+0"))
        _settle(qapp)
        assert not win._layers_dock.isVisible()
        assert not win._sidebar_handle.isVisible()
        QTest.keySequence(win, QKeySequence("Ctrl+0"))
        _settle(qapp)
        assert win._layers_dock.isVisible()
        assert win._sidebar_handle.isVisible()
    finally:
        _close(win)
