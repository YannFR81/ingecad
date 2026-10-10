# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The AI bridge's work, without the socket: what each tool does to the
open drawing, and the lines a user pastes into an MCP client.

Every tool takes the *host* (the main window, or a test double with the
same attributes) and returns a plain dict the bridge sends back as JSON.
Mutations go through the host's history like any command, and each tool
call is folded into ONE undo step, so a single U (or Ctrl+Z) takes back
whatever the agent did in that call.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import traceback
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Optional

from core.i18n import tr

#: IngeTrazo's bridge listens on 4763; IngeCAD takes the next port so both
#: apps can be driven at once.
DEFAULT_PORT = 4764
PORT_ENV = "INGECAD_AI_PORT"
#: The server name the MCP client shows (and prefixes the tools with).
SERVER_NAME = "ingecad"
#: The name of the undo step an agent's call becomes.
STEP_NAME = "AI"

#: Caps on what query_model lists, so a cadastral plan with 900 layers
#: does not hand the agent a reply larger than its context.
MAX_LAYERS = 200
MAX_BLOCKS = 100
#: Above this many entities the extents come from the header, not from
#: walking every entity on the UI thread.
EXTENTS_WALK_LIMIT = 50_000


def bridge_port(env: Optional[dict] = None) -> int:
    """The port the bridge listens on (``INGECAD_AI_PORT`` overrides).
    0 asks the system for a free one -- the tests use that."""
    env = os.environ if env is None else env
    raw = str(env.get(PORT_ENV, "")).strip()
    try:
        return int(raw) if raw else DEFAULT_PORT
    except ValueError:
        return DEFAULT_PORT


# -- capturing what the command window says ----------------------------------------

@contextlib.contextmanager
def capture_echo(host):
    """Collect every line written to the command window while the block
    runs, whoever writes it (the dispatcher holds its own reference to the
    echo method, so the widget's append is the one place they all meet)."""
    lines: list[str] = []
    widget = getattr(getattr(host, "command_line", None), "history", None)
    original = getattr(widget, "appendPlainText", None)
    if widget is None or original is None:
        yield lines
        return

    def append(text):
        lines.append(str(text))
        original(text)

    widget.appendPlainText = append
    try:
        yield lines
    finally:
        try:
            del widget.appendPlainText
        except AttributeError:
            widget.appendPlainText = original


def _refresh(host) -> None:
    changed = getattr(getattr(host, "tools", None), "changed", None)
    if changed is not None:
        changed.emit()


# -- run_python --------------------------------------------------------------------

def bridge_namespace(host, namespace: Optional[dict] = None,
                     quiet: Optional[list] = None) -> dict:
    """APPLOAD's namespace plus what an agent needs that a script file
    rarely does: the layer operations and the user's selection. Variables
    the agent defines stay in ``namespace`` from one call to the next; the
    names below are rebound every call, since the drawing may have changed.

    ``execute`` runs a Command through the history WITHOUT the screen
    update the tool controller gives each command a user draws; the
    commands are collected in ``quiet`` and the screen catches up once,
    when the call ends (:func:`_catch_up`). Per command, that update files
    the entity in the pick index and the snap engine and redraws the
    overlay -- measured on the 0.6.6 canvas, 2 000 lines took 46 s one by
    one and 0.05 s as one regen.
    """
    from core import actions as core_actions
    from core import layers, scripting

    namespace = {} if namespace is None else namespace
    namespace.update(scripting.script_namespace(host))
    quiet = [] if quiet is None else quiet

    def execute(command) -> None:
        """Run an undoable Command; the screen shows it when the call ends."""
        tools = getattr(host, "tools", None)
        dimension = getattr(core_actions, "AddDimensionCommand", None)
        if (dimension is not None and isinstance(command, dimension)
                and getattr(command, "dimlfac", 0) is None
                and getattr(command, "dimlfac_resolver", 0) is None
                and tools is not None):
            # what the tool controller does for a dimension drawn in a
            # viewport: measure in model units, not paper ones
            command.dimlfac_resolver = tools.trans_spatial_factor
        host.history.execute(command)
        quiet.append(command)
        skipped = getattr(command, "skipped", None)
        if skipped:
            kinds = ", ".join(sorted({e.dxftype() for e in skipped}))
            print(f"{len(skipped)} object(s) unchanged by {command.name}: {kinds}")

    def selected():
        """The entities the user has selected that are still in the drawing
        (an ERASE unlinks entities but keeps them alive, for its undo)."""
        document = getattr(host, "document", None)
        handles = set(getattr(getattr(host, "tools", None), "selection", ()) or ())
        if document is None or not handles:
            return []
        return _placed(document, handles)

    def zoom_extents():
        """ZOOM Extents on the screen (what a screenshot shows next).

        In model space the extents come from the drawing itself: the
        canvas learns about what this very call drew only when its
        background regen lands, and its own Zoom Extents would frame the
        drawing as it was before the call."""
        viewport = getattr(host, "viewport", None)
        if viewport is None:
            return
        box = None
        if getattr(host, "_active_layout", "Model") == "Model":
            document = getattr(host, "document", None)
            if document is not None:
                box = _drawing_extents(document.current_space())
        if box is None:
            viewport.zoom_extents()
            return
        viewport.push_view()
        viewport.view.zoom_extents(*box)
        viewport.update()

    namespace.update(execute=execute, layers=layers, selected=selected,
                     zoom_extents=zoom_extents)
    namespace.setdefault("__name__", "__ingecad_ai__")
    return namespace


def fold_since(history, before: int, name: str) -> int:
    """Fold every history entry after index ``before`` into ONE undo step
    named ``name`` (APPLOAD does the same to a script's commands); returns
    how many entries there were."""
    from core.commands import CompositeCommand

    added = history._undo[before:]
    if len(added) > 1:
        del history._undo[before:]
        composite = CompositeCommand(name, added)
        composite._space = None        # already done; do() is never re-run here
        history._undo.append(composite)
    return len(added)


def _catch_up(host, command) -> None:
    """Bring the screen and the pick caches up to date with ``command``
    (the call's one undo step), as U and REDO do for a step they cross."""
    tools = getattr(host, "tools", None)
    invalidate = getattr(host, "invalidate_vp_model_cache", None)
    if callable(invalidate):
        invalidate()
    after = getattr(tools, "after_history_change", None)
    if callable(after):
        after(command)
    selection = getattr(tools, "selection", None)
    document = getattr(host, "document", None)
    if selection and document is not None:
        # erased or replaced entities leave the selection, as after ERASE
        tools.selection = {e.dxf.handle for e in _placed(document, selection)}


def _placed(document, handles) -> list:
    """The entities of ``handles`` that sit in the current space, in handle
    order: an erased entity is unlinked (owner None) but still alive."""
    db = document.doc.entitydb
    owner = document.current_space().layout_key
    out = []
    for handle in sorted(handles):
        entity = db.get(handle)
        if entity is not None and entity.is_alive and entity.dxf.get("owner") == owner:
            out.append(entity)
    return out


def _rollback(host, redo: list) -> None:
    """Undo the step just folded, and give the redo stack back the
    entries the code's first command had cleared."""
    history = host.history
    command = history.undo()
    history._redo[:] = redo
    after = getattr(getattr(host, "tools", None), "after_history_change", None)
    if command is not None and callable(after):
        after(command)


def run_code(host, code: str, namespace: Optional[dict] = None) -> dict:
    """Execute agent Python against the live drawing.

    One undo step per call. If the code raises -- or does not even
    compile -- everything it did is rolled back and the drawing is exactly
    as it was, the redo stack included: an agent's call happens whole or
    not at all. stdout and stderr are captured, and so is the command
    window, so a ``command("LINE")`` inside the code reports its prompts.
    """
    if getattr(host, "document", None) is None:
        new_document = getattr(host, "new_document", None)
        if callable(new_document):
            new_document()
    reply = {"stdout": "", "stderr": "", "echo": [], "changed": 0,
             "error": None, "rolled_back": False}
    try:
        compiled = compile(str(code), "<run_python>", "exec")
    except SyntaxError:
        reply["error"] = traceback.format_exc(limit=0).strip()
        return reply
    quiet: list = []
    namespace = bridge_namespace(host, namespace, quiet)
    history = host.history
    before, redo = len(history._undo), list(history._redo)
    out, err = io.StringIO(), io.StringIO()
    with capture_echo(host) as said, \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            exec(compiled, namespace)                # noqa: S102 - the agent's code, by design
        except Exception as exc:                     # noqa: BLE001 - reported to the agent
            # from the code's own frame on: this function's is noise to its author
            reply["error"] = "".join(traceback.format_exception(
                type(exc), exc, exc.__traceback__.tb_next)).strip()
        count = fold_since(history, before, tr(STEP_NAME))
        if reply["error"] is not None and count:
            _rollback(host, redo)
            reply["rolled_back"] = True
        elif quiet and count:
            _catch_up(host, history._undo[-1])
    if reply["rolled_back"] or count:
        _refresh(host)
    reply.update(stdout=out.getvalue(), stderr=err.getvalue(), echo=said,
                 changed=0 if reply["rolled_back"] else count)
    return reply


# -- command -----------------------------------------------------------------------

def _active_command(host) -> Optional[str]:
    tools = getattr(host, "tools", None)
    tool = getattr(tools, "tool", None)
    if tool is not None:
        return getattr(tool, "name", None) or type(tool).__name__
    dispatcher = getattr(host, "dispatcher", None)
    if getattr(dispatcher, "pending_prompt", None) is not None:
        return getattr(dispatcher, "last_command", None) or "?"
    return None


def run_command_lines(host, text: str, cancel: bool = True) -> dict:
    """Type ``text`` at the command line, one entry per line, the way
    SCRIPT runs a .scr: a blank line is Enter, ``;`` starts a comment line.
    ``DELAY`` is skipped (nothing on screen to wait for). With ``cancel``
    the call starts the way an AutoCAD menu macro does, with ^C^C: a
    command left half-done is cancelled first.

    The whole call is one undo step. The reply carries what the command
    window said, and the command still waiting for input, if any.
    """
    from core import scripting

    if getattr(host, "document", None) is None:
        new_document = getattr(host, "new_document", None)
        if callable(new_document):
            new_document()
    history = host.history
    with capture_echo(host) as said:
        if cancel and _active_command(host) is not None:
            host._on_prompt_cancelled()
        before = len(history._undo)
        lines = [line.rstrip("\r") for line in str(text).split("\n")]
        if lines and lines[-1] == "":
            lines.pop()            # the newline that ends the text is not an Enter
        runner = scripting.ScriptRunner(
            [l for l in lines if not l.strip().upper().startswith("DELAY")],
            host._on_command_submitted)
        while runner.step() is not None:
            pass
        changed = fold_since(history, before, tr(STEP_NAME))
    if changed:
        _refresh(host)
    return {"echo": said, "changed": changed,
            "waiting_for_input": _active_command(host)}


# -- query_model -------------------------------------------------------------------

def _drawing_extents(space):
    """(min_x, min_y, max_x, max_y) of what ``space`` holds, or None."""
    try:
        from ezdxf import bbox

        box = bbox.extents(space, fast=True)
    except Exception:
        return None
    if not box.has_data:
        return None
    return box.extmin.x, box.extmin.y, box.extmax.x, box.extmax.y


def _extents(space, count: int, doc) -> Optional[dict]:
    lo = hi = None
    if count <= EXTENTS_WALK_LIMIT:
        try:
            from ezdxf import bbox

            box = bbox.extents(space, fast=True)
            if box.has_data:
                lo, hi = box.extmin, box.extmax
        except Exception:
            lo = hi = None
    if lo is None:
        try:
            lo, hi = doc.header.get("$EXTMIN"), doc.header.get("$EXTMAX")
        except Exception:
            return None
        if lo is None or hi is None or lo[0] > hi[0]:
            return None
    return {"min": [round(lo[0], 6), round(lo[1], 6)],
            "max": [round(hi[0], 6), round(hi[1], 6)]}


def _layer_rows(doc) -> list[dict]:
    rows = []
    for layer in doc.layers:
        rows.append({
            "name": layer.dxf.name,
            "on": layer.is_on(),
            "frozen": layer.is_frozen(),
            "locked": layer.is_locked(),
            "color": abs(layer.dxf.get("color", 7)),
            "linetype": layer.dxf.get("linetype", "Continuous"),
        })
    return rows


def model_summary(host) -> dict:
    """What is in the open drawing: enough for an agent to orient itself
    before it draws, small enough to read at a glance."""
    from core import units as units_mod

    document = getattr(host, "document", None)
    if document is None:
        return {"drawing": None, "note": "no drawing is open"}
    doc = document.doc
    space = document.current_space()
    by_type: dict[str, int] = {}
    for entity in space:
        kind = entity.dxftype()
        by_type[kind] = by_type.get(kind, 0) + 1
    total = sum(by_type.values())
    layers = _layer_rows(doc)
    blocks = sorted(b.name for b in doc.blocks
                    if not b.name.startswith("*") and not b.is_any_layout)
    insunits = units_mod.insunits(doc)
    summary = {
        "drawing": document.name,
        "path": str(document.path) if getattr(document, "path", None) else None,
        "unsaved_changes": bool(getattr(document, "dirty", False)),
        "units": units_mod.INSUNIT_NAMES.get(insunits, str(insunits)),
        "space": getattr(host, "_active_layout", "Model"),
        "layouts": [name for name in doc.layout_names() if name != "Model"],
        "current_layer": doc.header.get("$CLAYER", "0"),
        "layers_total": len(layers),
        "layers": layers[:MAX_LAYERS],
        "entities": {"total": total,
                     "by_type": dict(sorted(by_type.items(),
                                            key=lambda kv: (-kv[1], kv[0])))},
        "blocks_total": len(blocks),
        "blocks": blocks[:MAX_BLOCKS],
        "extents": _extents(space, total, doc),
        "selection": len(getattr(getattr(host, "tools", None), "selection", ()) or ()),
        "waiting_for_input": _active_command(host),
        "undo_steps": len(getattr(getattr(host, "history", None), "_undo", ()) or ()),
    }
    view = getattr(getattr(host, "viewport", None), "view", None)
    if view is not None and getattr(view, "scale", 0):
        summary["view"] = {
            "center": [round(view.cx, 6), round(view.cy, 6)],
            "width": round(view.width / view.scale, 6),
            "height": round(view.height / view.scale, 6),
        }
    try:
        from core.georef import read_georef

        georef = read_georef(doc)
    except Exception:
        georef = None
    if georef is not None:
        summary["georef"] = {"crs": georef.crs or None, "datum": georef.datum,
                             "utm_zone": georef.zone_label()}
    return summary


# -- connecting a client -----------------------------------------------------------

def server_script() -> Path:
    """The stdio MCP server, beside this file wherever the plugin lives
    (the app's plugins/ or the user's own plugins folder)."""
    return Path(__file__).resolve().with_name("mcp_server.py")


def mcp_command(platform: Optional[str] = None, frozen: Optional[bool] = None,
                executable: Optional[str] = None, env: Optional[dict] = None,
                script: Optional[Path] = None,
                exists=os.path.exists, which=shutil.which) -> list[str]:
    """The command an MCP client must run to reach this IngeCAD.

    The packages carry the server, so nobody needs Python installed:
    ``ingecad-mcp.exe`` beside the app on Windows, ``<ingecad> --mcp`` for
    the Linux packages (the AppImage by its own stable path, the Flatpak
    through ``flatpak run``, the snap through /snap/bin), and the script
    itself from a checkout. A plugin dropped into the user's folder of an
    older Windows build has no ``ingecad-mcp.exe`` to point at, so it falls
    back to running its own script with the system's Python.
    """
    platform = platform or sys.platform
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    executable = executable or sys.executable
    env = os.environ if env is None else env
    script = script or server_script()
    windows = platform.startswith("win")
    path_of = PureWindowsPath if windows else PurePosixPath
    if not windows:
        if env.get("APPIMAGE"):
            return [env["APPIMAGE"], "--mcp"]
        if env.get("FLATPAK_ID"):
            return ["flatpak", "run", env["FLATPAK_ID"], "--mcp"]
        if env.get("SNAP_NAME"):
            return [f"/snap/bin/{env['SNAP_NAME']}", "--mcp"]
    if frozen:
        exe = path_of(executable)
        if windows:
            sibling = exe.with_name("ingecad-mcp.exe")
            if exists(str(sibling)):
                return [str(sibling)]
        else:
            return [str(exe), "--mcp"]
    python = "python" if windows else "python3"
    if windows and which is not None:
        # by its full path when there is one: a client started from the
        # Start menu does not always see the PATH a terminal does
        found = which("python")
        if found:
            return [found, str(path_of(str(script)))]
        launcher = which("py")
        if launcher:
            return [launcher, "-3", str(path_of(str(script)))]
    return [python, str(path_of(str(script)))]


def desktop_config_path(platform: Optional[str] = None,
                        env: Optional[dict] = None) -> str:
    """Where Claude Desktop reads its MCP servers on this platform. The
    Microsoft Store edition keeps it inside its package folder, not in
    %APPDATA% (found on the first Windows machine the bridge met)."""
    platform = platform or sys.platform
    env = os.environ if env is None else env
    if platform.startswith("win"):
        local = env.get("LOCALAPPDATA")
        if local:
            try:
                packages = sorted(Path(local, "Packages").glob("Claude_*"))
            except OSError:
                packages = []
            for package in packages:
                store = package / "LocalCache" / "Roaming" / "Claude"
                if store.is_dir():
                    return str(store / "claude_desktop_config.json")
        return r"%APPDATA%\Claude\claude_desktop_config.json"
    if platform == "darwin":
        return "~/Library/Application Support/Claude/claude_desktop_config.json"
    return "~/.config/Claude/claude_desktop_config.json"


#: Where other common MCP clients read the same ``mcpServers`` block:
#: MCP is an open standard, not one vendor's feature.
OTHER_CLIENTS = (
    ("Cursor", "~/.cursor/mcp.json"),
    ("VS Code (Copilot)", '.vscode/mcp.json  (key "servers")'),
    ("Windsurf", "~/.codeium/windsurf/mcp_config.json"),
    ("Codex CLI", "~/.codex/config.toml  ([mcp_servers.ingecad])"),
)


def client_config(port: int, **kw) -> dict:
    """The ``mcpServers`` block for this machine."""
    cmd = mcp_command(**kw)
    entry: dict = {"command": cmd[0], "args": cmd[1:]}
    if port != DEFAULT_PORT:
        entry["env"] = {PORT_ENV: str(port)}
    return {"mcpServers": {SERVER_NAME: entry}}


def connect_instructions(port: int, **kw) -> str:
    """The text the AIBRIDGE window shows (and copies): Claude Code's
    one-liner, the JSON Claude Desktop and the others take, and where."""
    cmd = mcp_command(**kw)
    quoted = " ".join(f'"{c}"' if " " in c else c for c in cmd)
    config = client_config(port, **kw)
    env_flag = f"-e {PORT_ENV}={port} " if port != DEFAULT_PORT else ""
    others = "\n".join(f"    {name}: {path}" for name, path in OTHER_CLIENTS)
    needs_python = cmd[0] in ("python", "python3")
    text = (
        tr("The AI bridge is listening on 127.0.0.1:{port}. Any MCP client can "
           "connect: Claude Desktop, Claude Code, Cursor, VS Code, Windsurf, "
           "Codex CLI...", port=port)
        + "\n\n"
        + tr("Claude Desktop: add this to {path} and restart Claude Desktop:",
             path=desktop_config_path(kw.get("platform"), kw.get("env"))) + "\n"
        + json.dumps(config, indent=2) + "\n\n"
        + tr("Claude Code (in a terminal):") + "\n"
        + f"    claude mcp add {env_flag}{SERVER_NAME} -- {quoted}\n\n"
        + tr("Other clients take the same block in their own file:") + "\n"
        + others + "\n\n"
    )
    if needs_python:
        text += tr("This command needs Python 3 on this computer (the server "
                   "uses only its standard library).") + "\n"
    text += tr("Keep IngeCAD open with the bridge on: the tools answer only "
               "while it listens.")
    return text
