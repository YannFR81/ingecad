# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""AIBRIDGE: start, stop and show the AI bridge of this window.

    AIBRIDGE           opens the bridge window and starts the bridge
    AIBRIDGE ON / OFF  starts / stops it from the keyboard
    AIBRIDGE STATUS    says whether it listens, and where

The bridge window's "Start with IngeCAD" box (off until the user ticks it)
makes IngeCAD start the bridge on its own, as soon as the plugin is on.
"""
from __future__ import annotations

from core.i18n import tr


def _name_of(window) -> str:
    document = getattr(window, "document", None)
    return document.name if document is not None else tr("Untitled")


#: QSettings key of the "Start with IngeCAD" box.
AUTOSTART_SETTING = "plugins/puente_ia/autostart"


def autostart_enabled() -> bool:
    try:
        from PySide6.QtCore import QSettings

        raw = QSettings().value(AUTOSTART_SETTING, "false")
    except Exception:
        return False
    return str(raw).lower() in ("true", "1", "yes")


def set_autostart(flag: bool) -> None:
    from PySide6.QtCore import QSettings

    QSettings().setValue(AUTOSTART_SETTING, "true" if flag else "false")


def autostart(ctx) -> None:
    """The plugin came on, or a drawing was opened: start the bridge if the
    user asked for it to start with IngeCAD and no window has it on yet."""
    if not autostart_enabled():
        return
    from .bridge import bridge_of, running_elsewhere

    window = ctx.host
    bridge = bridge_of(window, create=False)
    if (bridge is not None and bridge.running) or running_elsewhere(window) is not None:
        return
    start(window)


def start(window):
    """Start this window's bridge; the port, or None (and why, echoed)."""
    from .bridge import bridge_of, running_elsewhere

    bridge = bridge_of(window)
    if bridge.running:
        return bridge.port
    other = running_elsewhere(window)
    if other is not None:
        window.echo(tr("The AI bridge is already on in another window ({name}): "
                       "stop it there first.", name=_name_of(other)))
        return None
    try:
        port = bridge.start()
    except OSError as exc:
        window.echo(tr("The AI bridge could not start: {error}", error=str(exc)))
        return None
    window.echo(tr("AI bridge listening on 127.0.0.1:{port}.", port=port))
    return port


def stop(window, quiet: bool = False) -> None:
    from .bridge import bridge_of

    bridge = bridge_of(window, create=False)
    if bridge is not None and bridge.running:
        bridge.stop()
        if not quiet:
            window.echo(tr("AI bridge stopped."))


def show_dialog(window) -> None:
    from .dialog import BridgeDialog

    dialog = getattr(window, "_ai_bridge_dialog", None)
    if dialog is None:
        dialog = BridgeDialog(window)
        window._ai_bridge_dialog = dialog
    dialog.refresh()
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()


def aibridge(ctx, *args) -> None:
    window = ctx.host
    option = args[0].upper() if args else ""
    if option == "ON":
        start(window)
    elif option == "OFF":
        stop(window)
    elif option in ("STATUS", "S", "?"):
        from .bridge import bridge_of

        bridge = bridge_of(window, create=False)
        if bridge is not None and bridge.running:
            ctx.echo(tr("AI bridge listening on 127.0.0.1:{port}.", port=bridge.port))
        else:
            ctx.echo(tr("AI bridge is off."))
    elif option:
        ctx.echo(tr('Unknown option "{option}": AIBRIDGE takes ON, OFF or STATUS.',
                    option=args[0]))
    else:
        start(window)
        show_dialog(window)


def on_deactivate(ctx) -> None:
    """The plugin is turned off: the port and the window go with it."""
    window = ctx.host
    stop(window, quiet=True)
    dialog = getattr(window, "_ai_bridge_dialog", None)
    if dialog is not None:
        dialog.close()
        dialog.setParent(None)
        dialog.deleteLater()
        window._ai_bridge_dialog = None
