# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Creating leaders: LEADER, QLEADER and MLEADER (issue #34).

Reference: ``docs/reference/dim/autocad-leaders.md``. The headless half
drives the tools through their prompts the way the command line does; the
window half checks the wiring (aliases, the in-place editor, the overlay).
"""
from __future__ import annotations

import pytest

from core import leaders
from core.commands import History
from core.document import Document
from tools.base import ToolContext
from tools.leaders import LeaderTool, MLeaderTool, QLeaderTool


class Harness:
    def __init__(self):
        self.document = Document.new()
        self.history = History(self.document)
        self.finished = False
        self.prompts: list[str] = []
        self.echoes: list[str] = []
        self.ctx = ToolContext(
            execute=self.history.execute,
            prompt=self.prompts.append,
            echo=self.echoes.append,
            finish=lambda: setattr(self, "finished", True),
            ask_text=lambda prompt, default="": "typed in a dialog",
            ask_choice=lambda prompt, items, default="": items[0] if items else None,
            undo_last=self.history.undo,
            services=self,
        )

    def entities(self, kind):
        return [e for e in self.document.doc.modelspace() if e.dxftype() == kind]


def _run(tool_cls, steps, harness=None):
    """Feed points (tuples) and typed tokens (str; "" is Enter) in order."""
    h = harness or Harness()
    tool = tool_cls(h.ctx)
    tool.start()
    for step in steps:
        if isinstance(step, tuple):
            tool.on_point(step)
        elif step == "":
            tool.on_enter()
        else:
            tool.on_option(step)
    return h, tool


# -- LEADER ------------------------------------------------------------------

def test_leader_prompts_follow_autocad():
    h, _t = _run(LeaderTool, [(0, 0), (10, 10)])
    assert h.prompts[0] == "Specify leader start point:"
    assert h.prompts[1] == "Specify next point:"
    assert h.prompts[2] == "Specify next point or [Annotation/Format/Undo] <Annotation>:"


def test_leader_with_typed_annotation_makes_a_leader_and_its_mtext():
    h, _t = _run(LeaderTool, [(0, 0), (10, 10), "", "NOTA 1", "NOTA 2", ""])
    assert h.finished
    (leader,) = h.entities("LEADER")
    (mtext,) = h.entities("MTEXT")
    assert mtext.text == "NOTA 1\\PNOTA 2"
    assert leader.dxf.annotation_type == 0
    assert leader.dxf.annotation_handle == mtext.dxf.handle
    # the last segment is not horizontal: a hook line one arrow long
    assert leader.dxf.has_hookline == 1
    assert len(leader.vertices) == 3
    arrow, height, gap = leaders.dimstyle_values(h.document.doc)
    assert leader.vertices[-1].x == pytest.approx(10 + arrow)
    assert mtext.dxf.insert.x == pytest.approx(10 + arrow + gap)
    assert mtext.dxf.attachment_point == 4       # middle left, text to the right
    assert mtext.dxf.char_height == pytest.approx(height)
    # one command: undo removes both, redo brings both back
    h.history.undo()
    assert not h.entities("LEADER") and not h.entities("MTEXT")
    h.history.redo()
    assert len(h.entities("LEADER")) == 1 and len(h.entities("MTEXT")) == 1


def test_leader_annotation_none_and_format_options():
    h, _t = _run(LeaderTool, [(0, 0), (10, 0), "F", "S", "N", "", "A", "", "N"])
    assert h.prompts[3] == "Enter leader format option [Spline/STraight/Arrow/None] <Exit>:"
    assert "Enter an annotation option [Tolerance/Copy/Block/None/Mtext] <Mtext>:" in h.prompts
    (leader,) = h.entities("LEADER")
    assert not h.entities("MTEXT")
    assert leader.dxf.path_type == 1              # Spline
    assert leader.dxf.has_arrowhead == 0          # None
    assert leader.dxf.annotation_type == 3
    assert leader.dxf.has_hookline == 0           # horizontal, no hook


def test_leader_undo_option_drops_the_last_vertex():
    h, t = _run(LeaderTool, [(0, 0), (10, 0), (20, 5), "U", "", "X", ""])
    (leader,) = h.entities("LEADER")
    assert [(v.x, v.y) for v in leader.vertices][:2] == [(0, 0), (10, 0)]
    assert len(leader.vertices) == 2


def test_leader_enter_at_the_option_prompt_opens_mtext_by_default():
    # Enter <Annotation>, Enter (no text) <options>, Enter <Mtext>
    h, _t = _run(LeaderTool, [(0, 0), (10, 10), "", "", ""])
    (mtext,) = h.entities("MTEXT")
    assert mtext.text == "typed in a dialog"


# -- QLEADER -----------------------------------------------------------------

def test_qleader_prompts_points_width_and_text():
    h, _t = _run(QLeaderTool, [(0, 0), (5, 5), (10, 5), "0", "TEXTO", ""])
    assert h.prompts[0] == "Specify first leader point, or [Settings] <Settings>:"
    assert h.prompts[1] == h.prompts[2] == "Specify next point:"
    assert h.prompts[3] == "Specify text width <0>:"
    assert h.prompts[4] == "Enter first line of annotation text <Mtext>:"
    (leader,) = h.entities("LEADER")
    (mtext,) = h.entities("MTEXT")
    assert len(leader.vertices) == 3
    assert mtext.text == "TEXTO"
    assert mtext.dxf.width == 0


def test_qleader_settings_change_the_number_of_points():
    saved = QLeaderTool.number_of_points
    try:
        h, _t = _run(QLeaderTool, ["", "2", (0, 0), (8, 8), "12.5", "A", ""])
        assert h.prompts[1] == "Enter number of leader points <3>:"
        assert QLeaderTool.number_of_points == 2
        (mtext,) = h.entities("MTEXT")
        assert mtext.dxf.width == pytest.approx(12.5)
    finally:
        QLeaderTool.number_of_points = saved


def test_qleader_enter_before_the_last_point_ends_the_leader_early():
    h, _t = _run(QLeaderTool, [(0, 0), (8, 8), "", "", "T", ""])
    (leader,) = h.entities("LEADER")
    assert len(leader.vertices) == 3          # 2 points + the hook line
    assert h.entities("MTEXT")[0].text == "T"


# -- MLEADER -----------------------------------------------------------------

def test_mleader_arrow_landing_text():
    h, _t = _run(MLeaderTool, [(0, 0), (30, 20), "COTA", ""])
    assert h.prompts[0] == ("Specify leader arrowhead location or "
                            "[leader Landing first/Content first/Options] <Options>:")
    assert h.prompts[1] == "Specify leader landing location:"
    assert h.prompts[2] == "Enter first line of annotation text <Mtext>:"
    (ml,) = h.entities("MULTILEADER")
    assert ml.context.mtext.default_content == "COTA"
    line = ml.context.leaders[0].lines[0]
    assert (line.vertices[0].x, line.vertices[0].y) == (0, 0)
    assert ml.dxf.style_handle == h.document.doc.mleader_styles.get("Standard").dxf.handle
    h.history.undo()
    assert not h.entities("MULTILEADER")


def test_mleader_options_stick_and_are_honoured():
    saved = (MLeaderTool.leader_type, MLeaderTool.landing_on,
             MLeaderTool.content, MLeaderTool.maxpoints)
    try:
        h, _t = _run(MLeaderTool, ["O", "L", "P", "A", "N", "M", "3", "X",
                                   (0, 0), (5, 5), (30, 20), "T", ""])
        assert ("Enter an option [Leader type/leader lAnding/Content type/"
                "Maxpoints/First angle/Second angle/eXit options] "
                "<eXit options>:") in h.prompts
        assert (MLeaderTool.leader_type, MLeaderTool.landing_on,
                MLeaderTool.maxpoints) == ("P", False, 3)
        (ml,) = h.entities("MULTILEADER")
        assert ml.dxf.leader_type == 2            # spline
        assert ml.dxf.has_dogleg == 0
        assert len(ml.context.leaders[0].lines[0].vertices) == 2
    finally:
        (MLeaderTool.leader_type, MLeaderTool.landing_on,
         MLeaderTool.content, MLeaderTool.maxpoints) = saved


def test_mleader_content_none_and_block():
    saved = MLeaderTool.content
    try:
        h = Harness()
        h.document.doc.blocks.new("TAG").add_circle((0, 0), 2)
        _run(MLeaderTool, ["O", "C", "N", "X", (0, 0), (30, 20)], h)
        (ml,) = h.entities("MULTILEADER")
        assert ml.dxf.content_type == 2 and ml.context.mtext is None
        _run(MLeaderTool, ["O", "C", "B", "X", (0, 0), (30, 40)], h)
        blocks = [e for e in h.entities("MULTILEADER") if e.dxf.content_type == 1]
        assert len(blocks) == 1
        assert blocks[0].dxf.block_record_handle == h.document.doc.blocks.get(
            "TAG").block_record.dxf.handle
    finally:
        MLeaderTool.content = saved


def test_mleader_landing_first_and_content_first():
    h, _t = _run(MLeaderTool, ["L", (30, 20), (0, 0), "A", ""])
    assert h.prompts[1] == "Specify leader landing location:"
    assert h.prompts[2] == "Specify leader arrowhead location:"
    (ml,) = h.entities("MULTILEADER")
    assert ml.context.mtext.default_content == "A"
    h2, _t = _run(MLeaderTool, ["C", (30, 20), "B", "", (0, 0)])
    (ml2,) = h2.entities("MULTILEADER")
    assert ml2.context.mtext.default_content == "B"
    assert (ml2.context.leaders[0].lines[0].vertices[0].x) == 0


def test_mleader_enter_at_the_landing_prompt_leaves_a_leader_without_text():
    h, _t = _run(MLeaderTool, [(0, 0), ""])
    (ml,) = h.entities("MULTILEADER")
    assert ml.context.mtext is None
    assert h.finished


# -- through the window --------------------------------------------------------

def _window(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    qapp.processEvents()
    return win, win.tools


def test_aliases_reach_the_leader_tools(qapp):
    from core import aliases as aliases_mod

    win, t = _window(qapp)
    try:
        for alias, name in (("MLD", "MLEADER"), ("LE", "QLEADER"),
                            ("LEAD", "LEADER")):
            assert aliases_mod.resolve(alias, win.dispatcher.aliases) == name
            win._on_command_submitted(alias)
            assert t.active() and t.tool.name == name, alias
            t.cancel()
    finally:
        win.close()


def test_qleader_enter_opens_the_in_place_editor_and_commits_a_leader(qapp):
    win, t = _window(qapp)
    try:
        t.start_tool("QLEADER")
        t.osnap_on = False
        t.on_click(0.0, 0.0)
        t.on_click(10.0, 10.0)
        t.on_click(20.0, 10.0)
        win._on_command_submitted("0")         # text width
        win._on_command_submitted("")          # Enter: the editor
        editor = t._mtext_editor
        assert editor is not None, "no in-place editor opened"
        editor._on_commit("EDITOR", {})
        msp = win.document.doc.modelspace()
        kinds = sorted(e.dxftype() for e in msp)
        assert kinds == ["LEADER", "MTEXT"], kinds
        assert msp.query("MTEXT")[0].text == "EDITOR"
        # both ride the overlay: nothing waits for a regen to show
        shown = {e.dxftype() for c in t._draw_commands()
                 for e in t._command_entities(c)}
        assert shown == {"LEADER", "MTEXT"}
    finally:
        win.close()


def test_mleaderstyle_says_which_style_is_used(qapp):
    win, t = _window(qapp)
    try:
        said = []
        win.command_line.echo = lambda text, *a, **k: said.append(text)
        win._on_command_submitted("MLEADERSTYLE")
        assert said and "Standard" in said[-1]
    finally:
        win.close()
