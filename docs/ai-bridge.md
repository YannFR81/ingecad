# AI bridge — drawing with Claude (MCP)

IngeCAD can be driven by an AI agent (Claude Desktop, Claude Code, Cursor, or
any other [Model Context Protocol](https://modelcontextprotocol.io) client).
The agent reads the open drawing, draws in it, types at the command line and
**sees** the canvas, live, while you watch. Every call it makes is **one
undo step**, and Python that fails is rolled back whole: the agent can never
leave the drawing half-changed, and `U` takes back whatever it did.

It is the bundled plugin `plugins/puente_ia` (the **AI** menu), built the
same way as IngeTrazo's AI bridge and speaking the same wire format.

## How it fits together

```
MCP client (Claude...)  ──stdio──>  mcp_server.py  ──TCP 127.0.0.1:4764──>  IngeCAD (AIBRIDGE)
```

- **Inside IngeCAD**, `AIBRIDGE` starts a small server on this computer's
  loopback, port **4764** (IngeTrazo uses 4763, so both can be driven at
  once; `INGECAD_AI_PORT` changes it). It is served on the GUI thread by a
  timer — no worker thread — so every tool runs where the drawing lives.
- **Outside**, `plugins/puente_ia/mcp_server.py` is the MCP server the client
  starts. It uses only Python's standard library and relays each tool call
  to the bridge. The packages carry it:

  | Installation | MCP server command |
  |---|---|
  | Windows (installer or zip) | `<install folder>\ingecad-mcp.exe` |
  | Linux AppImage / Flatpak / snap / tarball | `<ingecad> --mcp` (the window shows the exact line) |
  | From the repository | `python3 /path/to/plugins/puente_ia/mcp_server.py` |

## Use

1. In IngeCAD: **AI ▸ AI bridge (MCP)...** (or type `AIBRIDGE`). The window
   that opens starts the bridge and shows, with a **Copy** button, the exact
   lines for this computer. Tick **Start with IngeCAD** to have the bridge
   start on its own with the first drawing of every session.
2. **Claude Desktop**: paste the block into its configuration file and
   restart Claude Desktop (quit it from the tray icon, not just the window):

   ```json
   {
     "mcpServers": {
       "ingecad": {
         "command": "C:\\Users\\you\\AppData\\Local\\Programs\\IngeCAD\\ingecad-mcp.exe",
         "args": []
       }
     }
   }
   ```

   The file is `%APPDATA%\Claude\claude_desktop_config.json` on Windows —
   or, for the Microsoft Store edition of Claude Desktop,
   `%LOCALAPPDATA%\Packages\Claude_<id>\LocalCache\Roaming\Claude\` — and
   `~/.config/Claude/claude_desktop_config.json` on Linux. Settings ▸
   Developer ▸ Edit Config opens it.

   **Claude Code**, in a terminal: `claude mcp add ingecad -- <command>`.
3. Ask: *"draw a 30 m roundabout with a 2 m apron and four 3.5 m entries,
   on a ROUNDABOUT layer, then show me"*.

Keyboard: `AIBRIDGE ON`, `AIBRIDGE OFF`, `AIBRIDGE STATUS`.

## The tools

| Tool | What it does |
|---|---|
| `run_python` | Python over the live drawing, with APPLOAD's namespace (`actions`, `execute`, `command`, `document`, `doc`, `msp`, `echo`, `ezdxf`) plus `layers`, `selected()` and `zoom_extents()`. One undo step per call; rolled back whole if it raises. Variables persist between calls. |
| `command` | Types at the command line, one entry per line, like a `.scr` (a blank line is Enter). Answers with what the command window said and the command still waiting for input. A command left half-done is cancelled first. One undo step per call. |
| `query_model` | Drawing name, units, current space and layer, layers and their state, entity counts by type, blocks, extents, the visible area, selection, georeference. |
| `screenshot` | The canvas as you see it (a PNG). Where the canvas has no OpenGL to read from, the plot renderer draws the same view. |
| `undo` / `redo` | The history, as `U` and `REDO` run it. |

The MCP server hands the model a short reference of the drawing API with
`run_python`, so it draws through `actions` and `execute` (undoable, shown
on screen) instead of writing to the ezdxf document behind IngeCAD's back.
`tests/test_puente_ia.py` checks that every name the reference promises
exists.

A tool that opens a modal dialog (a command that asks the user something)
waits for that dialog to close; the next request waits behind it.
Command-line forms (`-LAYER`, `-HATCH`, `-INSERT`) never block.

## Security

The bridge listens **only on 127.0.0.1** and has no password: `run_python`
runs code inside IngeCAD, with your rights. Any program already running on
your computer could do the same to your files, but nothing on the network
can reach it. Keep it off when you are not using it (or leave **Start with
IngeCAD** unticked).

An agent in a container, in WSL or on another machine reaches it through a
tunnel you set up yourself (`ssh -L 4764:127.0.0.1:4764 user@pc`, `socat`...),
and tells the MCP server where the tunnel ends:

    INGECAD_AI_HOST=host.docker.internal INGECAD_AI_PORT=4764 \
        python3 /path/to/plugins/puente_ia/mcp_server.py

`INGECAD_AI_HOST` only changes where the client connects; the bridge itself
never listens anywhere but the loopback.

## An IngeCAD older than the plugin

The folder works dropped into the user's plugins folder of IngeCAD 0.6.5 or
later (`%APPDATA%\IngeCAD\plugins\puente_ia` on Windows,
`~/.config/IngeCAD/plugins/puente_ia` on Linux), turned on in **Tools ▸
Plugins...**. Those builds have no `ingecad-mcp.exe` or `--mcp`, so the
client runs `mcp_server.py` with any Python 3 on the computer (3.7 or later,
standard library only — the one QGIS installs will do):

```json
"ingecad": {
  "command": "C:\\Program Files\\QGIS 3.36.3\\apps\\Python312\\python.exe",
  "args": ["-I", "-S", "C:\\Users\\you\\AppData\\Roaming\\IngeCAD\\plugins\\puente_ia\\mcp_server.py"]
}
```

## Troubleshooting

- *"Cannot reach IngeCAD's AI bridge"*: IngeCAD is closed, or the bridge is
  off — `AIBRIDGE STATUS` says which.
- The client lists no `ingecad` tools: the command in its configuration does
  not run. Run it by hand in a terminal; it should wait silently for input
  (type Ctrl+C to leave). In Claude Desktop, Settings ▸ Developer shows the
  server's log.
- *"already on in another window"*: one IngeCAD window holds the port at a
  time; stop it there, or start the other with another `INGECAD_AI_PORT`.
