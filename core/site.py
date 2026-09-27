# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Site defaults: one folder that presets IngeCAD for every account on a
machine -- a classroom, an office. The user's own choices always win.

What AutoCAD does with a deployment (a shared support folder on the search
path for acad.pgp, and a profile), IngeCAD does with one folder:

    /etc/ingecad/            (or wherever $INGECAD_SITE_DIR points)
        defaults.ini         default values for any setting
        acad.pgp             aliases, under the user's own acad.pgp

``defaults.ini`` becomes Qt's system-scope settings file, the one QSettings
falls back to for a key the user never set -- so every setting in the app
takes it without the code that reads it knowing. Inside the Flatpak the
host's /etc is /run/host/etc, visible once the admin allows it (README).

Linux only: on Windows QSettings lives in the registry; there the folder is
not applied, and nothing breaks.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Optional

ENV = "INGECAD_SITE_DIR"
DEFAULTS = "defaults.ini"
PGP = "acad.pgp"


def site_dirs() -> list[Path]:
    """Where a site folder is looked for, in order."""
    out = []
    if os.environ.get(ENV):
        out.append(Path(os.environ[ENV]))
    out += [Path("/etc/ingecad"), Path("/run/host/etc/ingecad")]
    return out


def site_dir() -> Optional[Path]:
    """The first site folder that exists, or None."""
    for folder in site_dirs():
        try:
            if folder.is_dir():
                return folder
        except OSError:
            continue
    return None


def site_pgp() -> Optional[Path]:
    folder = site_dir()
    if folder is None:
        return None
    path = folder / PGP
    return path if path.is_file() else None


_staging: Optional[Path] = None


def install_defaults(organization: str, application: str) -> Optional[Path]:
    """Make the site's defaults.ini the settings every QSettings falls back
    to. Call after the application's names are set and before anything
    reads a setting. Returns the defaults file used, or None."""
    global _staging
    if sys.platform.startswith("win"):
        return None
    folder = site_dir()
    if folder is None or not (folder / DEFAULTS).is_file():
        return None
    from PySide6.QtCore import QSettings

    # Qt looks for <path>/<organization>/<application>.conf; the file is
    # staged under that name so the site keeps its readable one.
    base = os.environ.get("XDG_RUNTIME_DIR") or None
    staging = Path(tempfile.mkdtemp(prefix="ingecad-site-", dir=base))
    target = staging / organization / f"{application}.conf"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(folder / DEFAULTS, target)
    for fmt in (QSettings.NativeFormat, QSettings.IniFormat):
        QSettings.setPath(fmt, QSettings.SystemScope, str(staging))
    if _staging is not None:
        shutil.rmtree(_staging, ignore_errors=True)
    _staging = staging
    import atexit

    atexit.register(shutil.rmtree, staging, True)
    return folder / DEFAULTS
