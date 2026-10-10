#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""IngeCAD MCP server: connect Claude (Desktop, Code) or any MCP client to
the drawing open in IngeCAD.

A stdio MCP server using only Python's standard library. It relays each
tool call to the AI bridge the AIBRIDGE command starts inside IngeCAD (on
127.0.0.1, port 4764 unless INGECAD_AI_PORT says otherwise), so IngeCAD
must be open with the bridge on.

    claude mcp add ingecad -- python3 /path/to/plugins/puente_ia/mcp_server.py

The packages carry it too: ``ingecad --mcp`` on Linux, ``ingecad-mcp.exe``
beside the app on Windows. Kept stdlib-only and import-free on purpose:
it runs from a checkout, from a plugin folder and from the frozen builds
alike, and needs neither Qt nor ezdxf.
"""
from __future__ import annotations

import json
import os
import socket
import sys

PORT_ENV = "INGECAD_AI_PORT"
DEFAULT_PORT = 4764


def _port() -> int:
    try:
        return int(os.environ.get(PORT_ENV, "").strip() or DEFAULT_PORT)
    except ValueError:
        return DEFAULT_PORT


PORT = _port()
#: Where the bridge is. It only ever listens on the IngeCAD machine's own
#: loopback (no password, and run_python runs code in the app); a client in
#: a container or on another machine reaches it through a tunnel the user
#: sets up, and names the tunnel's end here.
HOST = os.environ.get("INGECAD_AI_HOST", "").strip() or "127.0.0.1"
#: The protocol versions this server speaks; the client's own is echoed
#: back when it is one of them.
PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
VERSION = "0.1.0"

#: What the model needs to draw well without exploring the API first.
REFERENCE = """\
IngeCAD is a 2D DXF/DWG CAD in the spirit of classic AutoCAD. These tools act
on the drawing OPEN in IngeCAD, live: what you draw appears on the user's
screen and goes into their undo history. Each tool call is ONE undo step: the
user takes it back with U, and so can you (the undo tool).

Work like this: query_model first (units, layers, extents, selection), then
draw with run_python or command, then LOOK with screenshot. If what you drew
may be off screen, zoom first (zoom_extents() in run_python, or command
"ZOOM" then "E").

Coordinates are drawing units -- query_model says which (Meters on most civil
plans, Millimeters on the default template). X right, Y up, angles in degrees
counter-clockwise from +X. Points are (x, y) tuples.

run_python -- what is in scope (APPLOAD's namespace, plus a few names):
  actions    every drawing operation as an undoable Command:
             add_line(p1, p2)  add_circle(center, r)  add_arc_3p(p1, p2, p3)
             add_polyline(points, closed=False)  points (x, y) or (x, y, sw, ew, bulge)
             add_rectangle(p1, p2)  add_polygon(center, vertex, sides)
             add_text(pos, text, height, rotation=0.0, align="LEFT")
             add_mtext(p1, p2, text, char_height)  add_point(pos)
             add_ellipse(center, major_axis_vector, ratio)  add_spline(fit_points)
             add_hatch([boundary_points], pattern="SOLID", scale=1.0, angle=0.0)
             dim_linear(p1, p2, location)  dim_aligned(p1, p2, location)
             dim_radius(center, r, location)  insert_block(name, point, xscale=1.0)
             move_entities(ents, dx, dy)  copy_entities(ents, dx, dy)
             rotate_entities(ents, base, deg)  scale_entities(ents, base, factor)
             mirror_entities(ents, p1, p2)  EraseCommand(ents)
  execute(cmd)  run a Command through the history. ALWAYS change the drawing
             this way, e.g.:
                 cmd = actions.add_line((0, 0), (10, 0))
                 cmd.layer = "ROAD"        # optional: else the current layer
                 execute(cmd)              # cmd.entity is the new entity
  layers     execute(layers.NewLayerCommand("ROAD", color=1, linetype="Continuous"))
             layers.set_current_layer(document, "ROAD")
             execute(layers.LayerPropertyCommand("ROAD", "color", 3))
                 (properties: color, linetype, lineweight, on, frozen, locked)
  command(text)  type ONE entry at the command line, as the user would:
             command("CIRCLE"); command("50,50"); command("10")
  document, doc, msp  the Document, its ezdxf Drawing, its modelspace. READ them
             freely: msp.query('LINE[layer=="ROAD"]'), e.dxf.start, doc.layers.
             Never add or modify entities through msp/ezdxf directly: that
             bypasses undo and the screen does not show it.
  selected()     the entities the user has selected
  zoom_extents() ZOOM Extents on the screen
  echo(text)     write in IngeCAD's command window; print() output comes back to you
  ezdxf          the library itself
Variables you define persist between run_python calls. If the code raises,
everything it did in that call is rolled back: the drawing is unchanged.
Draw in bulk: one run_python call can execute thousands of commands, and the
screen catches up once, when the call ends. The command tool replays each
entry like a user typing, which is slow for more than a few dozen objects.

command -- the command line, one entry per line, exactly as typed in IngeCAD
(AutoCAD names and aliases: L, C, A, PL, REC, POL, O, TR, EX, M, CO, RO, SC, MI,
E, F, H, -LAYER, ZOOM, DIMLINEAR, LIST, DIST, AREA...). A blank line is Enter;
point entries are "x,y", "@dx,dy" or "@dist<angle". Prompts and messages come
back in "echo". Prefer the command-line forms (-LAYER, -HATCH, -INSERT) to
commands that open a dialog: a dialog waits for the user, not for you.
"""

INSTRUCTIONS = (
    "These tools drive the drawing open in IngeCAD on the user's computer, "
    "live, through its AI bridge (AIBRIDGE).\n\n" + REFERENCE)

TOOLS = [
    {
        "name": "run_python",
        "description": (
            "Execute Python against the LIVE IngeCAD drawing. Returns stdout, "
            "the command window's output and, on error, the traceback (the "
            "call is then rolled back). The reference below is all you need; "
            "read it instead of exploring the API.\n\n" + REFERENCE),
        "inputSchema": {
            "type": "object",
            "properties": {"code": {"type": "string",
                                    "description": "Python source to run."}},
            "required": ["code"],
        },
    },
    {
        "name": "command",
        "description": (
            "Type at IngeCAD's command line, one entry per line (a blank line "
            "is Enter), like an AutoCAD .scr: e.g. \"LINE\\n0,0\\n100,0\\n\\n\". "
            "Returns what the command window said and which command still "
            "waits for input. A command left half-done is cancelled first "
            "unless cancel is false. The whole call is one undo step."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "lines": {"type": "string",
                          "description": "Command-line entries, one per line."},
                "cancel": {"type": "boolean",
                           "description": "Cancel a pending command first (default true)."},
            },
            "required": ["lines"],
        },
    },
    {
        "name": "query_model",
        "description": (
            "Overview of the open drawing: name, units, current space and "
            "layer, layers with their state, entity counts by type, blocks, "
            "extents, the visible area, selection size, georeference."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "screenshot",
        "description": (
            "See the drawing as the user sees it on screen (the current view). "
            "Use it after drawing, to check and correct."),
        "inputSchema": {
            "type": "object",
            "properties": {"width": {"type": "integer"},
                           "height": {"type": "integer"}},
        },
    },
    {
        "name": "undo",
        "description": "Undo the last step in IngeCAD (one tool call is one step).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "redo",
        "description": "Redo the last undone step in IngeCAD.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

_sock = None
_req_id = 0


def _bridge(tool: str, args: dict) -> dict:
    """One request to the in-app bridge, reconnecting once if it dropped
    (IngeCAD restarted, the bridge was switched off and on)."""
    global _sock, _req_id
    for attempt in (0, 1):
        if _sock is None:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(180.0)
            sock.connect((HOST, PORT))
            _sock = sock
        _req_id += 1
        try:
            _sock.sendall((json.dumps(
                {"id": _req_id, "tool": tool, "args": args}) + "\n").encode())
            buf = b""
            while b"\n" not in buf:
                chunk = _sock.recv(1 << 20)
                if not chunk:
                    raise OSError("the bridge closed the connection")
                buf += chunk
            return json.loads(buf.split(b"\n", 1)[0])
        except OSError:
            try:
                _sock.close()
            except OSError:
                pass
            _sock = None
            if attempt:
                raise
    raise OSError("unreachable")


#: The most text one tool call hands back. A print() over a whole plan is
#: easy to write and would fill the model's context in one go.
MAX_TEXT = 40_000


def _clip(text: str, limit: int = MAX_TEXT) -> str:
    if len(text) <= limit:
        return text
    head = limit * 3 // 4
    tail = limit - head
    return (text[:head] + "\n[... %d characters cut: print less, or summarise "
            "in the code ...]\n" % (len(text) - limit) + text[-tail:])


def _text(text: str, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": _clip(text)}], "isError": is_error}


def _echo_block(lines) -> str:
    lines = [str(l) for l in lines or () if str(l).strip()]
    return "command window:\n" + "\n".join(lines) if lines else ""


def _format(name: str, result: dict) -> dict:
    if name == "screenshot" and result.get("png_base64"):
        note = "%dx%d, %s" % (result.get("width", 0), result.get("height", 0),
                              "the canvas" if result.get("source") == "canvas"
                              else "plot rendering (the canvas gave no image)")
        return {"content": [
            {"type": "image", "data": result["png_base64"], "mimeType": "image/png"},
            {"type": "text", "text": note}]}
    if name == "run_python":
        parts = []
        if result.get("stdout"):
            parts.append(result["stdout"].rstrip())
        echo = _echo_block(result.get("echo"))
        if echo:
            parts.append(echo)
        if result.get("stderr"):
            parts.append("stderr:\n" + result["stderr"].rstrip())
        if result.get("error"):
            head = ("ROLLED BACK, the drawing is unchanged:"
                    if result.get("rolled_back") else "error:")
            parts.append(head + "\n" + str(result["error"]))
        parts.append("(commands executed: %s)" % result.get("changed", 0))
        return _text("\n".join(p for p in parts if p),
                     is_error=bool(result.get("error")))
    if name == "command":
        parts = [_echo_block(result.get("echo")) or "(the command window said nothing)",
                 "(commands executed: %s)" % result.get("changed", 0)]
        if result.get("waiting_for_input"):
            parts.append("still waiting for input: %s" % result["waiting_for_input"])
        return _text("\n".join(parts))
    return _text(json.dumps(result, indent=2, ensure_ascii=False))


def _call(name: str, args: dict) -> dict:
    if name not in {tool["name"] for tool in TOOLS}:
        return _text("unknown tool %r" % name, is_error=True)
    try:
        reply = _bridge(name, args)
    except OSError as exc:
        return _text(
            "Cannot reach IngeCAD's AI bridge on %s:%d (%s). In IngeCAD: type "
            "AIBRIDGE (or the AI menu > AI bridge (MCP)...) to start it, and "
            "keep IngeCAD open." % (HOST, PORT, exc), is_error=True)
    if not reply.get("ok"):
        return _text(str(reply.get("error")), is_error=True)
    return _format(name, reply.get("result") or {})


def handle(msg: dict):
    """One JSON-RPC message -> the reply (None for a notification)."""
    method = msg.get("method")
    msg_id = msg.get("id")
    if method == "initialize":
        asked = (msg.get("params") or {}).get("protocolVersion")
        return {"jsonrpc": "2.0", "id": msg_id, "result": {
            "protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[-1],
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "ingecad", "version": VERSION},
            "instructions": INSTRUCTIONS,
        }}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = msg.get("params") or {}
        return {"jsonrpc": "2.0", "id": msg_id,
                "result": _call(params.get("name", ""), params.get("arguments") or {})}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if msg_id is None:            # a notification: initialized, cancelled...
        return None
    return {"jsonrpc": "2.0", "id": msg_id,
            "error": {"code": -32601, "message": "unknown method %s" % method}}


def main() -> int:
    # MCP frames are UTF-8 lines whatever the console's code page says
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if not isinstance(msg, dict):
            continue
        reply = handle(msg)
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
