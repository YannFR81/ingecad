# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The status bar shows the classic toggles and hides the rest until asked
(right-click or its menu button, as in AutoCAD and BricsCAD); the layout
tabs never shrink to an elided "..." (Marco's screenshot, 2026-09-28)."""
from __future__ import annotations

import pytest


@pytest.fixture
def win(qapp):
    from PySide6.QtCore import QSettings

    from views.main_window import MainWindow

    QSettings().remove(MainWindow.SETTING_STATUSBAR_HIDDEN)
    w = MainWindow()
    w.show()
    qapp.processEvents()
    yield w
    QSettings().remove(MainWindow.SETTING_STATUSBAR_HIDDEN)
    w.close()


def test_the_default_bar_shows_the_classic_toggles_only(win):
    for key in ("snap", "grid", "ortho", "polar", "osnap"):
        assert win._mode_buttons[key].isVisible(), key
    for key in ("otrack", "dyn", "lwt"):
        assert not win._mode_buttons[key].isVisible(), key
    assert not win._version_label.isVisible()
    assert win._space_btn.isVisible() and win._statusbar_custom_btn.isVisible()


def test_hiding_and_showing_is_remembered_and_the_f_key_still_works(win, qapp):
    from views.main_window import MainWindow

    win._set_statusbar_hidden(win._statusbar_hidden() - {"otrack"} | {"grid"})
    assert win._mode_buttons["otrack"].isVisible()
    assert not win._mode_buttons["grid"].isVisible()
    other = MainWindow()           # a new window reads the same setting
    other.show()
    qapp.processEvents()
    try:
        assert other._mode_buttons["otrack"].isVisible()
        assert not other._mode_buttons["grid"].isVisible()
    finally:
        other.close()
    before = win.viewport.grid_on
    win._toggle_mode("grid")       # what F7 does, button hidden or not
    assert win.viewport.grid_on != before
    win._set_statusbar_hidden(set())
    assert all(w.isVisible() for _k, _l, ws in win._statusbar_items() for w in ws)


def test_the_menu_lists_every_item_ticked_as_shown(win):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMenu

    seen = []

    def grab():
        menu = next(m for m in QApplication.topLevelWidgets()
                    if isinstance(m, QMenu) and m.isVisible())
        seen.extend((a.text(), a.isChecked()) for a in menu.actions()
                    if a.isCheckable())
        menu.close()

    QTimer.singleShot(0, grab)
    win._statusbar_menu()
    keys = [k for k, _l, _w in win._statusbar_items()]
    assert len(seen) == len(keys)
    hidden = win._statusbar_hidden()
    assert [checked for _t, checked in seen] == [k not in hidden for k in keys]


def test_layout_tabs_are_never_narrower_than_their_name(win):
    win.new_document()
    for name in ("A-01", "A-02", "E-01", "E-02", "D-01"):
        win.document.doc.layouts.new(name)
    win._refresh_layout_tabs()
    win.resize(900, 600)           # a crowded bar
    for button in win._tab_buttons:
        assert button.minimumWidth() >= button.sizeHint().width()
    win.document.dirty = False
