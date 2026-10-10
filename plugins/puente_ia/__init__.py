# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""AI bridge -- let an AI agent draw in the open drawing over MCP
(docs/ai-bridge.md).

AIBRIDGE starts a server on this computer's loopback only; the companion
``mcp_server.py`` (``ingecad --mcp``, ``ingecad-mcp.exe`` on Windows)
connects it to Claude Desktop, Claude Code or any other MCP client. The
agent gets six tools: ``run_python`` (Python over ``actions``, APPLOAD's
namespace), ``command`` (the command line, as a .scr), ``query_model``,
``screenshot`` (the canvas as the user sees it), ``undo`` and ``redo``.

Every call is ONE undo step, and Python that raises is rolled back whole:
the agent can never leave the drawing half-changed, and the user takes
back anything it did with a single U.

The spec imports nothing heavy: the socket and the bridge load when
AIBRIDGE first runs (or when "Start with IngeCAD" starts it). The folder
also works dropped into the user's own plugins folder of an IngeCAD that
predates it (0.6.5 and later).
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

from core.plugins import MenuItem, PluginSpec


def _aibridge(ctx, *args):
    from .commands import aibridge

    return aibridge(ctx, *args)


def _on_document_open(ctx, document):
    from .commands import autostart

    autostart(ctx)


def _on_activate(ctx):
    from .commands import autostart

    autostart(ctx)


def _on_deactivate(ctx):
    from .commands import on_deactivate

    on_deactivate(ctx)


def _autostart_where_active():
    """For a host older than ``on_activate``: once the event loop runs (the
    windows built, their plugins on), start the bridge where it is wanted."""
    from types import SimpleNamespace

    from PySide6.QtWidgets import QApplication

    for widget in QApplication.topLevelWidgets():
        plugins = getattr(widget, "plugins", None)
        if plugins is not None and plugins.is_active("puente_ia"):
            _on_document_open(SimpleNamespace(host=widget), None)


_fields = {f.name for f in dataclasses.fields(PluginSpec)}
_hooks = {"on_document_open": _on_document_open}
if "on_activate" in _fields:
    _hooks["on_activate"] = _on_activate
else:
    try:
        from PySide6.QtCore import QCoreApplication, QTimer

        if QCoreApplication.instance() is not None:
            QTimer.singleShot(0, _autostart_where_active)
    except ImportError:
        pass
# A host older than the hook still turns the plugin off cleanly: the bridge
# then notices on its next request that its plugin is gone, and stops.
if "on_deactivate" in _fields:
    _hooks["on_deactivate"] = _on_deactivate


PLUGIN = PluginSpec(
    id="puente_ia",
    name="AI",
    version="0.1.0",
    description="Let an AI agent (Claude, Cursor...) draw in the open drawing over MCP, "
                "from this computer only: every call is one undo step.",
    commands={"AIBRIDGE": _aibridge},
    menu=(MenuItem("AI bridge (MCP)...", "AIBRIDGE"),),
    i18n_dir=Path(__file__).parent / "i18n",
    **_hooks,
)
