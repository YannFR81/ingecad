# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Any projected coordinate system, through PROJ (#27).

GeoSpark, from the UK: OSGB36 / the British National Grid is what they
draw in, and hard-coding countries one at a time does not scale. A drawing
may now declare any projected CRS by its EPSG code; conversions go through
PROJ, grids included (OSTN15, fetched and cached on first use), and fall
back to the next path offline. UTM on WGS84/PSAD56 keeps IngeCAD's own
maths -- which PROJ confirms here to a nanodegree.
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest

pytest.importorskip("pyproj")

from core.commands import History  # noqa: E402
from core.document import Document  # noqa: E402
from core.georef import Georef, SetGeorefCommand, read_georef  # noqa: E402
from plugins.terreno import actions, datum  # noqa: E402

BNG = Georef(crs="EPSG:27700")
#: Near Great Yarmouth, Norfolk, in WGS84.
NORFOLK = (52.657, 1.718)


def test_a_declared_crs_travels_in_the_drawing_and_undoes(tmp_path):
    document = Document.new()
    history = History(document)
    history.execute(SetGeorefCommand(Georef(crs=" epsg:27700 ")))
    assert read_georef(document.doc) == BNG            # normalised
    document.doc.modelspace().add_line((0, 0), (1, 1))
    path = tmp_path / "bng.dxf"
    document.save_as(path)
    assert read_georef(Document.load(path).doc) == BNG
    history.undo()
    assert read_georef(document.doc) is None


def test_a_crs_record_carries_no_utm_zone():
    assert BNG.to_tags() == [(1, "crs=EPSG:27700")]
    assert BNG.label() == "EPSG:27700" and BNG.zone_label() == "" and not BNG.is_utm
    assert Georef.from_tags(BNG.to_tags()) == BNG


def test_proj_and_ingecad_agree_on_utm():
    """The same point, declared as UTM 19 S (IngeCAD's maths) and as
    EPSG:32719 (PROJ): one answer."""
    own, proj = Georef(19, False), Georef(crs="EPSG:32719")
    for point in ((229038.4878, 8185246.5211), (350123.456, 8245678.9)):
        a = datum.drawing_to_latlon(own, *point)
        b = datum.drawing_to_latlon(proj, *point)
        assert a == pytest.approx(b, abs=1e-9)


def test_the_british_national_grid_round_trips_and_shifts_the_datum():
    east, north = datum.latlon_to_drawing(BNG, *NORFOLK)
    lat, lon = datum.drawing_to_latlon(BNG, east, north)
    assert (lat, lon) == pytest.approx(NORFOLK, abs=1e-8)       # ~1 mm
    # the datum shift is really applied: the same lat/lon read as if it
    # were OSGB36 lands ~130 m away, which is what skipping it would do
    from pyproj import Transformer

    unshifted = Transformer.from_crs("EPSG:4277", "EPSG:27700", always_xy=True)
    ue, un = unshifted.transform(NORFOLK[1], NORFOLK[0])
    assert math.hypot(east - ue, north - un) > 50


def test_offline_a_grid_that_cannot_be_read_falls_back_to_the_next_path(monkeypatch):
    class Unreadable:           # a grid transformation with no grid: inf
        def transform(self, x, y, direction=None):
            return math.inf, math.inf

    class Helmert:
        def transform(self, x, y, direction=None):
            return 1.5, 52.5

    monkeypatch.setattr(datum, "_candidates", lambda code: (Unreadable(), Helmert()))
    assert datum.drawing_to_latlon(BNG, 600000, 300000) == (52.5, 1.5)
    monkeypatch.setattr(datum, "_candidates", lambda code: (Unreadable(),))
    with pytest.raises(ValueError):
        datum.drawing_to_latlon(BNG, 600000, 300000)


def test_only_projected_systems_are_accepted():
    assert datum.check_crs("27700").name == "OSGB36 / British National Grid"
    with pytest.raises(ValueError):
        datum.check_crs("EPSG:4326")                    # geographic: degrees
    with pytest.raises(ValueError):
        datum.check_crs("EPSG:999999")                  # not a thing


def test_describe_and_the_report_name_the_system():
    assert actions.describe(BNG) == "EPSG:27700, OSGB36 / British National Grid"
    from plugins.topografia import actions as topo

    document = Document.new()
    History(document).execute(SetGeorefCommand(BNG))
    lot = document.doc.modelspace().add_lwpolyline(
        [(0, 0), (12, 0), (12, 10), (0, 10)], close=True)
    text = topo.memoria_for(document, lot, "L", "", 0, {}).text()
    assert "coordinate system EPSG:27700" in text and "UTM zone" not in text


# -- GEOREF, typed ---------------------------------------------------------------------
def _harness():
    from tests.test_terreno_georef import _Harness

    return _Harness()


def test_georef_coordsys_takes_an_epsg_code():
    from plugins.terreno.tools import GeorefTool

    h = _harness()
    tool = GeorefTool(h.ctx)
    tool.start()
    assert tool.on_option("C")
    assert h.prompts[-1] == "Coordinate system code, as EPSG:27700:"
    assert tool.on_option("4326")                       # geographic: refused
    assert "not a projected coordinate system" in h.echoed[-1]
    assert not h.finished
    assert tool.on_option("27700")
    assert h.finished and read_georef(h.doc) == BNG
    assert h.echoed[-1] == ("Drawing georeferenced: EPSG:27700, "
                            "OSGB36 / British National Grid")


def test_georef_coordsys_enter_keeps_the_declared_code():
    from plugins.terreno.tools import GeorefTool

    h = _harness()
    h.history.execute(SetGeorefCommand(BNG))
    tool = GeorefTool(h.ctx)
    tool.start()
    assert h.echoed[-1].endswith("OSGB36 / British National Grid")
    tool.on_option("C")
    assert h.prompts[-1] == "Coordinate system code, as EPSG:27700 <EPSG:27700>:"
    tool.on_enter()
    assert h.finished and read_georef(h.doc) == BNG


def test_pyproj_is_a_dependency_of_every_package():
    reqs = (Path(__file__).resolve().parent.parent / "requirements.txt").read_text()
    assert any(line.startswith("pyproj") for line in reqs.splitlines())
