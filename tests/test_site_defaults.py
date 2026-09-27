# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Site defaults (#25): one folder presets IngeCAD for every account on a
machine -- a classroom -- and the user's own choices always win."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import aliases as aliases_mod, site  # noqa: E402

pytestmark = pytest.mark.skipif(sys.platform.startswith("win"),
                                reason="QSettings is the registry there")

CLASSROOM = """; the teacher's defaults for the whole class
[input]
right_click=enter

[plugins]
topografia\\enabled=false
terreno\\enabled=false
"""


@pytest.fixture
def classroom(tmp_path, monkeypatch, qapp):
    from PySide6.QtCore import QCoreApplication, QSettings

    folder = tmp_path / "ingecad"
    folder.mkdir()
    (folder / "defaults.ini").write_text(CLASSROOM, encoding="utf-8")
    (folder / "acad.pgp").write_text("DE, *DESPLAZA\nL, *CIRCLE\n",
                                     encoding="utf-8")
    monkeypatch.setenv(site.ENV, str(folder))
    names = (QCoreApplication.organizationName(),
             QCoreApplication.applicationName())
    QCoreApplication.setOrganizationName("IngeCAD")
    QCoreApplication.setApplicationName("IngeCAD")
    # a user who never set anything: their own file in a scratch folder
    user = tmp_path / "user"
    for fmt in (QSettings.NativeFormat, QSettings.IniFormat):
        QSettings.setPath(fmt, QSettings.UserScope, str(user))
    installed = site.install_defaults(QCoreApplication.organizationName(),
                                      QCoreApplication.applicationName())
    yield folder, installed
    QCoreApplication.setOrganizationName(names[0])
    QCoreApplication.setApplicationName(names[1])
    # back to what Qt uses by default -- which, under the test suite, is the
    # scratch XDG_CONFIG_HOME conftest sets, NEVER the developer's ~/.config
    system = os.environ.get("XDG_CONFIG_DIRS", "/etc/xdg").split(":")[0]
    user = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    for fmt in (QSettings.NativeFormat, QSettings.IniFormat):
        QSettings.setPath(fmt, QSettings.SystemScope, system)
        QSettings.setPath(fmt, QSettings.UserScope, user)


def test_the_classroom_settings_are_every_students_defaults(classroom):
    from PySide6.QtCore import QSettings

    from core.plugins import PluginManager
    from views.options_dialog import RIGHT_CLICK_ENTER, right_click_mode

    folder, installed = classroom
    assert installed == folder / "defaults.ini"
    assert right_click_mode() == RIGHT_CLICK_ENTER
    manager = PluginManager()
    manager.discover()
    assert "topografia" in manager.loaded
    assert not manager.enabled("topografia")
    assert not manager.enabled("terreno")
    # the student's own choice wins over the classroom's
    QSettings().setValue("input/right_click", "menu")
    assert right_click_mode() == "menu"


def test_the_classroom_acad_pgp_sits_under_the_users(classroom, tmp_path,
                                                     monkeypatch):
    folder, _ = classroom
    user_pgp = tmp_path / "user.pgp"
    monkeypatch.setattr(aliases_mod, "user_pgp_path", lambda: user_pgp)
    aliases = aliases_mod.load_aliases()
    assert aliases["DE"] == "DESPLAZA"          # the classroom's
    assert aliases["L"] == "CIRCLE"             # it overrides the stock one
    user_pgp.write_text("L, *LINE\n", encoding="utf-8")
    assert aliases_mod.load_aliases()["L"] == "LINE"   # the user's wins


def test_no_site_folder_changes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv(site.ENV, str(tmp_path / "missing"))
    monkeypatch.setattr(site, "site_dirs", lambda: [tmp_path / "missing"])
    assert site.site_dir() is None
    assert site.install_defaults("IngeCAD", "IngeCAD") is None
    assert site.site_pgp() is None
