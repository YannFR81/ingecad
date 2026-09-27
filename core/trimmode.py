# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""TRIMMODE: whether CHAMFER and FILLET trim the edges they join.

One setting for both commands, as in AutoCAD (TRIMMODE, saved in the
registry, initial value 1): changing Trim in FILLET changes it in CHAMFER.
"""
from __future__ import annotations

_KEY = "drafting/trimmode"
_value: bool | None = None


def trimmode() -> bool:
    global _value
    if _value is None:
        try:
            from PySide6.QtCore import QSettings

            _value = str(QSettings().value(_KEY, 1)) not in ("0", "false")
        except Exception:  # noqa: BLE001 -- no Qt settings: the default
            _value = True
    return _value


def set_trimmode(on: bool) -> None:
    global _value
    _value = bool(on)
    try:
        from PySide6.QtCore import QSettings

        QSettings().setValue(_KEY, 1 if _value else 0)
    except Exception:  # noqa: BLE001
        pass
