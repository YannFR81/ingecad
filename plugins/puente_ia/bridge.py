# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The in-app half of the AI bridge: a localhost-only TCP server, served
on the GUI thread, whose requests act on the window that started it.

The wire format is IngeTrazo's (plugins/ai_bridge.py there):
newline-delimited JSON on 127.0.0.1, request ``{"id": n, "tool": name,
"args": {...}}``, reply ``{"id": n, "ok": bool, "result": ... | "error":
str}``. The companion ``mcp_server.py`` turns it into an MCP server for
Claude and the rest.

No worker thread: the sockets are non-blocking and a QTimer polls them on
the GUI thread, so every tool runs where the drawing and Qt live, and the
garbage collector is never paused for the whole session the way a
long-lived worker would need (core/gc_guard.py: workers pause it for
seconds, not hours). An idle bridge costs one non-blocking ``accept`` a
tenth of a second; a connected client, one ``recv`` every few
milliseconds.

It listens on the loopback only and never anywhere else: there is no
password, and ``run_python`` runs code inside the app. An agent in a
container or on another machine reaches it through a tunnel the user
sets up (docs/ai-bridge.md).
"""
from __future__ import annotations

import base64
import json
import socket
import time

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QRectF, Qt, QTimer

from . import actions

#: The longest side of a screenshot, whatever the agent asks for.
MAX_SIDE = 2048
#: Poll intervals: listening only, and with a client connected.
IDLE_MS = 100
ACTIVE_MS = 10
#: How soon a call that opened a dialog is answered.
WATCH_MS = 100
#: A request line longer than this is not an agent talking: drop it.
MAX_REQUEST = 32 * 1024 * 1024
#: How long a reply may take to leave (a screenshot is a few hundred KB).
SEND_TIMEOUT_S = 30.0
BAD_JSON = b'{"id": null, "ok": false, "error": "bad json"}\n'


def _modal_dialog() -> str | None:
    """The title of the modal dialog open in IngeCAD, if any -- a native
    file dialog included, which Qt also counts as a modal window."""
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    widget = QApplication.activeModalWidget()
    if widget is not None:
        return widget.windowTitle() or type(widget).__name__
    window = QGuiApplication.modalWindow()
    if window is not None:
        return window.title() or "dialog"
    return None


class Bridge(QObject):
    """Serves the agents connected to this window's bridge, one request
    at a time, on the GUI thread."""

    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        self._server: socket.socket | None = None
        self._clients: dict[socket.socket, bytes] = {}
        self._namespace: dict = {}
        self._busy = False
        self._pending: dict | None = None    # the call running now, and its client
        self.port: int | None = None
        self.clients = 0                 # connections accepted so far
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._watch = QTimer(self)
        self._watch.setInterval(WATCH_MS)
        self._watch.timeout.connect(self._watch_call)

    # -- lifecycle --------------------------------------------------------------
    def start(self, port: int | None = None) -> int:
        if self._server is not None:
            return self.port
        port = actions.bridge_port() if port is None else port
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            # Windows: SO_REUSEADDR there would let another program bind
            # the same port over ours; exclusive use forbids exactly that.
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind(("127.0.0.1", port))
            srv.listen(4)
        except OSError:
            srv.close()
            raise
        srv.setblocking(False)
        self._server = srv
        self.port = srv.getsockname()[1]
        self._timer.start(IDLE_MS)
        return self.port

    def stop(self) -> None:
        try:
            self._timer.stop()
            self._watch.stop()
        except RuntimeError:          # Qt already tore it down (app exit)
            pass
        for conn in list(self._clients):
            self._drop(conn)
        srv, self._server = self._server, None
        if srv is not None:
            try:
                srv.close()
            except OSError:
                pass
        self.port = None

    @property
    def running(self) -> bool:
        return self._server is not None

    @property
    def connected(self) -> int:
        """Agents connected right now."""
        return len(self._clients)

    # -- the poll -------------------------------------------------------------------
    def _poll(self) -> None:
        if self._server is None or self._busy:
            return
        # a dialog the user opened: refuse, for the reason _watch gives
        self._serve(refuse=_modal_dialog())
        if self._server is not None:
            self._timer.setInterval(ACTIVE_MS if self._clients else IDLE_MS)

    def _watch_call(self) -> None:
        """While a call runs. This only fires when the call itself turns
        the event loop -- a modal dialog it opened, or a wait for the
        display -- and Qt never re-fires the poll timer from inside its own
        slot, hence a timer of its own. A dialog waits for the user, not
        for the agent: the call that opened it is answered now, and new
        calls are refused until it closes, because running code inside a
        dialog's exec() is how re-entrancy bugs are made."""
        dialog = _modal_dialog()
        if not self._busy or dialog is None or self._server is None:
            return
        self._answer_pending(dialog)
        self._serve(refuse=dialog)

    def _serve(self, refuse: str | None = None) -> None:
        self._accept()
        for conn in list(self._clients):
            if conn in self._clients and not self._read(conn, refuse):
                self._drop(conn)
            if self._server is None:          # a request stopped the bridge
                return

    def _accept(self) -> None:
        while self._server is not None:
            try:
                conn, _addr = self._server.accept()
            except (BlockingIOError, InterruptedError):
                return
            except OSError:
                return
            conn.setblocking(False)
            self._clients[conn] = b""
            self.clients += 1

    def _read(self, conn, refuse: str | None = None) -> bool:
        """Take what the client sent and answer each complete line (or
        refuse it, while ``refuse`` names an open dialog); False when the
        client has gone. The buffer lives in ``_clients``, never in a local:
        a dialog opened by one line runs a nested poll that reads on."""
        while True:
            try:
                chunk = conn.recv(1 << 16)
            except (BlockingIOError, InterruptedError):
                break
            except OSError:
                return False
            if not chunk:
                return False
            self._clients[conn] += chunk
            if len(self._clients[conn]) > MAX_REQUEST:
                return False
        while conn in self._clients and b"\n" in self._clients[conn]:
            line, self._clients[conn] = self._clients[conn].split(b"\n", 1)
            if not line.strip():
                continue
            reply = (self._refuse_line(line, refuse) if refuse is not None
                     else self._handle_line(conn, line))
            if reply is not None and not self._send(conn, reply):
                return False
        return True

    @staticmethod
    def _send(conn, data: bytes) -> bool:
        try:
            conn.settimeout(SEND_TIMEOUT_S)
            conn.sendall(data)
            return True
        except OSError:
            return False
        finally:
            try:
                conn.setblocking(False)
            except OSError:
                pass

    def _drop(self, conn) -> None:
        self._clients.pop(conn, None)
        try:
            conn.close()
        except OSError:
            pass

    # -- one request ----------------------------------------------------------------
    @staticmethod
    def _parse(line: bytes):
        try:
            req = json.loads(line)
        except ValueError:
            return None
        return req if isinstance(req, dict) else None

    @staticmethod
    def _encode(reply: dict) -> bytes:
        return (json.dumps(reply, default=str) + "\n").encode()

    def _handle_line(self, conn, line: bytes) -> bytes | None:
        """Run one request line; its reply, or None when the reply already
        left (a dialog the call opened answered it early)."""
        req = self._parse(line)
        if req is None:
            return BAD_JSON
        pending = {"conn": conn, "id": req.get("id"), "answered": False}
        self._pending = pending
        try:
            reply = self.call(req)
        finally:
            self._pending = None
        return None if pending["answered"] else self._encode(reply)

    def _refuse_line(self, line: bytes, dialog: str) -> bytes:
        req = self._parse(line)
        if req is None:
            return BAD_JSON
        return self._encode({"id": req.get("id"), "ok": False, "error": (
            f"A dialog is open in IngeCAD ({dialog}) and waits for the user: "
            "nothing runs until it is closed. Ask the user to close it, then "
            "try again.")})

    def _answer_pending(self, dialog: str) -> None:
        pending = self._pending
        if pending is None or pending["answered"]:
            return
        pending["answered"] = True
        conn = pending["conn"]
        reply = {"id": pending["id"], "ok": False, "error": (
            f"This call opened a dialog in IngeCAD ({dialog}), which now waits "
            "for the user; it finishes when the user closes it, and until then "
            "every call is refused. Use the command-line form instead "
            "(-LAYER, -HATCH, -INSERT...) when there is one.")}
        if conn in self._clients and not self._send(conn, self._encode(reply)):
            self._drop(conn)

    def call(self, req: dict) -> dict:
        """Run one request on this (the GUI) thread; the reply dict."""
        tool = str(req.get("tool", ""))
        args = req.get("args") or {}
        if not self._plugin_active():
            # once this reply has left: stopping now would close its socket
            QTimer.singleShot(0, self.stop)
            return {"id": req.get("id"), "ok": False,
                    "error": "the AI bridge plugin was turned off in IngeCAD"}
        self._busy = True
        self._watch.start()
        try:
            handler = getattr(self, f"_tool_{tool}", None)
            if handler is None or not isinstance(args, dict):
                raise ValueError(f"unknown tool {tool!r}")
            return {"id": req.get("id"), "ok": True, "result": handler(**args)}
        except Exception as exc:  # noqa: BLE001 - reported to the agent
            return {"id": req.get("id"), "ok": False,
                    "error": f"{type(exc).__name__}: {exc}"}
        finally:
            self._busy = False
            try:
                self._watch.stop()
            except RuntimeError:          # torn down under a closing app
                pass

    def _plugin_active(self) -> bool:
        plugins = getattr(self._window, "plugins", None)
        is_active = getattr(plugins, "is_active", None)
        return True if is_active is None else bool(is_active("puente_ia"))

    # -- tools -------------------------------------------------------------------------
    def _tool_run_python(self, code: str = "") -> dict:
        reply = actions.run_code(self._window, code, self._namespace)
        _settle()
        return reply

    def _tool_command(self, lines: str = "", cancel: bool = True) -> dict:
        reply = actions.run_command_lines(self._window, lines, cancel=bool(cancel))
        _settle()
        return reply

    def _tool_query_model(self) -> dict:
        return actions.model_summary(self._window)

    def _tool_screenshot(self, width: int = 1280, height: int = 800) -> dict:
        return screenshot(self._window, width, height)

    def _tool_undo(self) -> dict:
        return self._history_step("undo")

    def _tool_redo(self) -> dict:
        return self._history_step("redo")

    def _history_step(self, which: str) -> dict:
        window = self._window
        history = window.history
        before = len(history._undo)
        with actions.capture_echo(window) as said:
            (window._cmd_undo if which == "undo" else window._cmd_redo)()
        return {"done": len(history._undo) != before, "echo": said}


def _settle() -> None:
    """Let what a command queued for "right after" run inside the call:
    several commands open their dialog from a zero-delay timer, and a
    dialog opened there must be reported to this call, not found by the
    next one."""
    from PySide6.QtWidgets import QApplication

    for _ in range(3):
        QApplication.processEvents()


# -- seeing the drawing ---------------------------------------------------------------

def _wait_for_display(window, timeout_s: float = 10.0) -> None:
    """Let a background regen land, so the picture shows the drawing as
    it is now and not as it was one edit ago."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app.processEvents()
        if getattr(window, "_regen_worker", None) is None \
                and getattr(window, "_open_thread", None) is None:
            break
        time.sleep(0.01)
    app.processEvents()


def _plotted_view(window, width: int, height: int):
    """The current view drawn by the plot renderer (ezdxf onto a
    QGraphicsScene), for when the canvas cannot hand over its pixels: no
    OpenGL context (a headless run, a broken driver)."""
    from PySide6.QtGui import QColor, QImage, QPainter

    from formats import pdf_out

    layout = getattr(window, "_active_layout", "Model")
    scene = pdf_out.build_graphics_scene(window.document, layout)
    view = getattr(getattr(window, "viewport", None), "view", None)
    if view is not None and view.scale:
        w, h = view.width / view.scale, view.height / view.scale
        source = QRectF(view.cx - w / 2, view.cy - h / 2, w, h)
    else:
        source = pdf_out.scene_extents(scene)
    aspect = source.width() / source.height() if source.height() else 1.0
    if width / height > aspect:
        width = max(1, int(height * aspect))
    else:
        height = max(1, int(width / aspect))
    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(QColor("#ffffff"))
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.Antialiasing)
        # DXF is y-up, the image y-down
        painter.translate(0, height)
        painter.scale(1, -1)
        scene.render(painter, QRectF(0, 0, width, height), source)
    finally:
        painter.end()
    return image


def screenshot(window, width: int = 1280, height: int = 800) -> dict:
    """The canvas as the user sees it, as a base64 PNG."""
    width = max(64, min(int(width), MAX_SIDE))
    height = max(64, min(int(height), MAX_SIDE))
    _wait_for_display(window)
    source = "canvas"
    viewport = getattr(window, "viewport", None)
    image = viewport.grabFramebuffer() if viewport is not None else None
    if image is None or image.isNull():
        source = "plot"
        image = _plotted_view(window, width, height)
    elif image.width() > width or image.height() > height:
        image = image.scaled(width, height, Qt.KeepAspectRatio,
                             Qt.SmoothTransformation)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return {"png_base64": base64.b64encode(bytes(data)).decode("ascii"),
            "width": image.width(), "height": image.height(), "source": source}


# -- one bridge per window ----------------------------------------------------------------

def bridge_of(window, create: bool = True):
    bridge = getattr(window, "_ai_bridge", None)
    if bridge is None and create:
        bridge = Bridge(window)
        window._ai_bridge = bridge
        # the window goes, the port goes with it
        window.destroyed.connect(lambda *_a, b=bridge: b.stop())
    return bridge


def running_elsewhere(window):
    """Another open window whose bridge already holds the port, if any."""
    from PySide6.QtWidgets import QApplication

    for widget in QApplication.topLevelWidgets():
        if widget is window:
            continue
        other = getattr(widget, "_ai_bridge", None)
        if other is not None and other.running:
            return widget
    return None
