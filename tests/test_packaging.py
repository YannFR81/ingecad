# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""What the PyInstaller bundle (AppImage and tar.gz) must NOT carry.

0.6.3 bundled Ubuntu 22.04's libstdc++. On Arch and Debian testing the
host's Mesa needs a newer one (libSPIRV-Tools asks for GLIBCXX_3.4.32), the
bundled copy loads first, the GL driver fails, and the app never opened
(issues #20, #21). The fix lives in packaging/ingecad.spec; this keeps it.
"""
from __future__ import annotations

import ast
from pathlib import Path

SPEC = Path(__file__).resolve().parent.parent / "packaging" / "ingecad.spec"


def _host_libraries(text: str) -> set[str]:
    for node in ast.parse(text).body:
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == "HOST_LIBRARIES" for t in node.targets):
            return set(ast.literal_eval(node.value))
    return set()


def test_the_bundle_leaves_the_c_plus_plus_runtime_to_the_host():
    text = SPEC.read_text(encoding="utf-8")
    libraries = _host_libraries(text)
    # the runtime pair travels together or not at all, and the old
    # fontconfig cannot read newer systems' configuration files
    assert {"libstdc++.so.6", "libgcc_s.so.1",
            "libfontconfig.so.1", "libfreetype.so.6"} <= libraries


def test_the_filter_runs_before_the_bundle_is_collected():
    text = SPEC.read_text(encoding="utf-8")
    filtered = text.index("a.binaries = [entry for entry in a.binaries")
    assert filtered < text.index("coll = COLLECT(")
    assert "not in HOST_LIBRARIES" in text[filtered:text.index("coll = COLLECT(")]
