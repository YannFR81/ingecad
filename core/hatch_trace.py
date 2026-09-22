# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Boundary tracing for HATCH's "Pick internal point" -- AutoCAD's BPOLY.

A civil plan is drawn with LINEs and ARCs far more than with closed
polylines: a wall section is four lines, a lot is a lot until someone
joins it. AutoCAD hatches those all the same, because it does not look for
a closed OBJECT around the point but for a closed REGION: every curve in
the boundary set is cut where it crosses another, the pieces form a planar
graph, and the smallest face around the point is the boundary. Whatever
lies inside that face -- a closed loop of lines, a circle, a text -- is an
island. A tester hatching a plan drawn with lines got "no closed boundary"
where AutoCAD fills; this module is what was missing.

The graph is built once per pick from the segments of the candidate
entities (curves flattened to chords), split at every mutual crossing,
with dead ends pruned. The face around the point is walked with the
left-hand rule from the first edge a horizontal ray from the point meets;
the components left inside it are walked the same way, their outer face
being the island. Everything is pure Python + NumPy; the pair search is
bucketed on a grid so a viewport with a few thousand segments answers in
well under a second.
"""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

Point = tuple[float, float]

#: Curves are flattened to chords whose sagitta is this fraction of the
#: curve's size (a circle gets ~72 chords).
CURVE_SAGITTA = 2000.0

#: Entities the tracer reads as boundary curves. TEXT/MTEXT are islands.
CURVE_TYPES = frozenset(("LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE",
                         "ELLIPSE", "SPLINE"))
TEXT_TYPES = frozenset(("TEXT", "MTEXT"))

#: The most chords a pick works on; beyond it the boundary set closes in
#: around the point (halving the window) until it fits.
MAX_SEGMENTS = 60_000


# -- flattening ------------------------------------------------------------------

def _flatten(entity) -> list[list[Point]]:
    """The entity as one or more chord chains (a polyline may be several
    when it has breaks; a LINE is one chain of two points)."""
    t = entity.dxftype()
    if t == "LINE":
        s, e = entity.dxf.start, entity.dxf.end
        return [[(s.x, s.y), (e.x, e.y)]]
    if t == "POLYLINE" and entity.get_mode() != "AcDb2dPolyline":
        return []
    try:
        from ezdxf import bbox as ezbbox
        from ezdxf import path as ezpath

        path = ezpath.make_path(entity)
        box = ezbbox.extents([entity], fast=True)
        size = max(box.size.x, box.size.y) if box.has_data else 1.0
        distance = max(abs(size) / CURVE_SAGITTA, 1e-9)
        chain = [(v.x, v.y) for v in path.flattening(distance)]
    except Exception:
        return []
    if len(chain) < 2:
        return []
    closed = False
    if t == "LWPOLYLINE":
        closed = bool(entity.closed)
    elif t == "POLYLINE":
        closed = bool(entity.is_closed)
    elif t in ("CIRCLE", "ELLIPSE"):
        closed = t == "CIRCLE" or entity.dxf.get("end_param", 6.28) - \
            entity.dxf.get("start_param", 0.0) >= math.tau - 1e-9
    if closed and chain[0] != chain[-1]:
        chain.append(chain[0])
    return [chain]


def segments_of(entities, window=None) -> np.ndarray:
    """All chords of the candidate entities as an (n, 4) array.

    ``window`` = (x0, y0, x1, y1) limits the set the way AutoCAD's "current
    viewport" does: an ENTITY is in when any part of it shows, and then it
    is in whole -- a wall that runs off the screen still closes the room.
    """
    rows = []
    for e in entities:
        if not e.is_alive or e.dxftype() not in CURVE_TYPES:
            continue
        chains = _flatten(e)
        if window is not None and chains:
            xs = [p[0] for chain in chains for p in chain]
            ys = [p[1] for chain in chains for p in chain]
            x0, y0, x1, y1 = window
            if max(xs) < x0 or min(xs) > x1 or max(ys) < y0 or min(ys) > y1:
                continue
        for chain in chains:
            for a, b in zip(chain, chain[1:]):
                if a != b:
                    rows.append((a[0], a[1], b[0], b[1]))
    if not rows:
        return np.zeros((0, 4), dtype=float)
    return np.asarray(rows, dtype=float)


# -- the planar arrangement ------------------------------------------------------

def _tolerance(segs: np.ndarray) -> float:
    """Two points closer than this are one node: a millionth of the
    boundary set's size, which is below any station's or drafter's
    precision and above float noise."""
    if len(segs) == 0:
        return 1e-9
    xs = np.concatenate([segs[:, 0], segs[:, 2]])
    ys = np.concatenate([segs[:, 1], segs[:, 3]])
    size = max(xs.max() - xs.min(), ys.max() - ys.min(), 1e-6)
    return size * 1e-7


def _split_at_crossings(segs: np.ndarray, tol: float) -> np.ndarray:
    """Cut every segment where it crosses or touches another.

    Candidate pairs come from a sort-and-sweep on x (NumPy end to end: on
    a colleague's plan the per-cell Python loops this replaced cost 2.1 s
    of a 2.6 s pick), then the parametric intersection of both lines;
    collinear overlaps contribute each other's endpoints.
    """
    n = len(segs)
    if n == 0:
        return segs
    x1, y1, x2, y2 = segs.T
    lo_x, hi_x = np.minimum(x1, x2), np.maximum(x1, x2)
    lo_y, hi_y = np.minimum(y1, y2), np.maximum(y1, y2)
    lengths = np.hypot(x2 - x1, y2 - y1)
    cuts: list[list[float]] = [[] for _ in range(n)]

    order = np.argsort(lo_x, kind="stable")
    lo_s, hi_s = lo_x[order], hi_x[order]
    ends = np.searchsorted(lo_s, hi_s + tol, side="right")
    starts = np.arange(n) + 1
    counts = np.maximum(ends - starts, 0)
    total = int(counts.sum())
    # pairs (i, j) in sorted order, j in [i+1, ends[i]); walked in chunks
    # so a dense sheet never asks for gigabytes at once
    chunk = 2_000_000
    first = np.cumsum(counts) - counts
    pos = 0
    while pos < total:
        stop = min(pos + chunk, total)
        idx = np.arange(pos, stop)
        i_sorted = np.searchsorted(first, idx, side="right") - 1
        j_sorted = starts[i_sorted] + (idx - first[i_sorted])
        a, b = order[i_sorted], order[j_sorted]
        pos = stop
        ok = (lo_y[a] <= hi_y[b] + tol) & (lo_y[b] <= hi_y[a] + tol)
        a, b = a[ok], b[ok]
        if len(a) == 0:
            continue
        dxa, dya = x2[a] - x1[a], y2[a] - y1[a]
        dxb, dyb = x2[b] - x1[b], y2[b] - y1[b]
        den = dxa * dyb - dya * dxb
        ex, ey = x1[b] - x1[a], y1[b] - y1[a]
        parallel = np.abs(den) <= 1e-12 * (lengths[a] * lengths[b] + 1e-30)
        with np.errstate(divide="ignore", invalid="ignore"):
            ta = np.where(parallel, np.nan, (ex * dyb - ey * dxb) / den)
            tb = np.where(parallel, np.nan, (ex * dya - ey * dxa) / den)
        eps_a = tol / np.maximum(lengths[a], tol)
        eps_b = tol / np.maximum(lengths[b], tol)
        hit = (~parallel) & (ta >= -eps_a) & (ta <= 1 + eps_a) & \
              (tb >= -eps_b) & (tb <= 1 + eps_b)
        ta_c = np.clip(ta[hit], 0.0, 1.0)
        tb_c = np.clip(tb[hit], 0.0, 1.0)
        for ia, t in zip(a[hit].tolist(), ta_c.tolist()):
            cuts[ia].append(t)
        for ib, t in zip(b[hit].tolist(), tb_c.tolist()):
            cuts[ib].append(t)
        # collinear overlaps: b's start must lie on a's line
        par = np.nonzero(parallel)[0]
        if len(par):
            ia, ib = a[par], b[par]
            cross = np.abs(dxa[par] * (y1[ib] - y1[ia])
                           - dya[par] * (x1[ib] - x1[ia]))
            near = cross <= tol * np.maximum(lengths[ia], tol)
            for k in par[near].tolist():
                ia_k, ib_k = int(a[k]), int(b[k])
                la2 = float(dxa[k] * dxa[k] + dya[k] * dya[k])
                lb2 = float(dxb[k] * dxb[k] + dyb[k] * dyb[k])
                for px, py in ((x1[ib_k], y1[ib_k]), (x2[ib_k], y2[ib_k])):
                    t = ((px - x1[ia_k]) * dxa[k] + (py - y1[ia_k]) * dya[k]) / la2
                    if 0.0 < t < 1.0:
                        cuts[ia_k].append(float(t))
                for px, py in ((x1[ia_k], y1[ia_k]), (x2[ia_k], y2[ia_k])):
                    t = ((px - x1[ib_k]) * dxb[k] + (py - y1[ib_k]) * dyb[k]) / lb2
                    if 0.0 < t < 1.0:
                        cuts[ib_k].append(float(t))
    out = []
    for i in range(n):
        ts = sorted(set([0.0, 1.0] + [t for t in cuts[i] if 0.0 < t < 1.0]))
        for t0, t1 in zip(ts, ts[1:]):
            ax, ay = x1[i] + (x2[i] - x1[i]) * t0, y1[i] + (y2[i] - y1[i]) * t0
            bx, by = x1[i] + (x2[i] - x1[i]) * t1, y1[i] + (y2[i] - y1[i]) * t1
            if math.hypot(bx - ax, by - ay) > tol:
                out.append((ax, ay, bx, by))
    return np.asarray(out, dtype=float) if out else np.zeros((0, 4))


class _Graph:
    """Nodes (merged within tol), undirected edges, angular adjacency."""

    def __init__(self, segs: np.ndarray, tol: float) -> None:
        self.tol = tol
        self.nodes: list[Point] = []
        self._grid: dict[tuple[int, int], list[int]] = defaultdict(list)
        self.edges: set[tuple[int, int]] = set()
        self.adj: dict[int, set[int]] = defaultdict(set)
        for x1, y1, x2, y2 in segs:
            a = self._node(x1, y1)
            b = self._node(x2, y2)
            if a != b:
                self._add_edge(a, b)
        self._prune_dead_ends()

    def _node(self, x: float, y: float) -> int:
        cell = self.tol * 4.0
        cx, cy = int(math.floor(x / cell)), int(math.floor(y / cell))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for idx in self._grid.get((cx + dx, cy + dy), ()):
                    px, py = self.nodes[idx]
                    if abs(px - x) <= self.tol and abs(py - y) <= self.tol:
                        return idx
        idx = len(self.nodes)
        self.nodes.append((x, y))
        self._grid[(cx, cy)].append(idx)
        return idx

    def _add_edge(self, a: int, b: int) -> None:
        key = (a, b) if a < b else (b, a)
        if key in self.edges:
            return
        self.edges.add(key)
        self.adj[a].add(b)
        self.adj[b].add(a)

    def _prune_dead_ends(self) -> None:
        """A node with one edge cannot lie on a closed boundary; removing it
        may expose the next, so repeat until stable."""
        stack = [n for n, nb in self.adj.items() if len(nb) == 1]
        while stack:
            n = stack.pop()
            nb = self.adj.get(n)
            if not nb or len(nb) != 1:
                continue
            (m,) = nb
            self.adj[n].clear()
            self.adj[m].discard(n)
            self.edges.discard((n, m) if n < m else (m, n))
            if len(self.adj[m]) == 1:
                stack.append(m)

    def _angle(self, a: int, b: int) -> float:
        ax, ay = self.nodes[a]
        bx, by = self.nodes[b]
        return math.atan2(by - ay, bx - ax)

    def next_left(self, prev: int, cur: int) -> int:
        """From the directed edge prev->cur, the outgoing edge that turns
        the most to the LEFT (the face on the left is walked ccw)."""
        back = self._angle(cur, prev)
        best, best_turn = prev, -1.0
        for nxt in self.adj[cur]:
            if nxt == prev and len(self.adj[cur]) > 1:
                continue
            turn = (self._angle(cur, nxt) - back) % math.tau
            if turn > best_turn:
                best, best_turn = nxt, turn
        return best

    def walk_face(self, a: int, b: int) -> list[int] | None:
        """The face on the left of a->b, as a node cycle; None if the walk
        does not close (it always should on a pruned graph)."""
        cycle = [a]
        prev, cur = a, b
        limit = 4 * len(self.edges) + 4
        while len(cycle) <= limit:
            cycle.append(cur)
            nxt = self.next_left(prev, cur)
            prev, cur = cur, nxt
            if prev == a and cur == b:
                return cycle[:-1]
        return None

    def polygon(self, cycle: list[int]) -> list[Point]:
        return [self.nodes[i] for i in cycle]

    def components(self) -> list[set[int]]:
        seen: set[int] = set()
        out = []
        for start in list(self.adj):
            if start in seen or not self.adj[start]:
                continue
            comp, stack = set(), [start]
            while stack:
                n = stack.pop()
                if n in comp:
                    continue
                comp.add(n)
                stack.extend(self.adj[n])
            seen |= comp
            out.append(comp)
        return out


# -- geometry -----------------------------------------------------------------------

def signed_area(poly: list[Point]) -> float:
    a = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return a / 2.0


def point_in_polygon(poly: list[Point], pt: Point) -> bool:
    x, y = pt
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            xc = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < xc:
                inside = not inside
        j = i
    return inside


def _first_edge_right(graph: _Graph, point: Point):
    """The edge a horizontal ray from ``point`` towards +x meets first, as
    (a, b) directed so that the point lies on its LEFT; None if the ray
    escapes."""
    px, py = point
    best = None
    for a, b in graph.edges:
        ax, ay = graph.nodes[a]
        bx, by = graph.nodes[b]
        if (ay > py) == (by > py):
            continue
        x = ax + (bx - ax) * (py - ay) / (by - ay)
        if x <= px:
            continue
        if best is None or x < best[0]:
            # the point is left of a->b when a->b goes downwards past it
            best = (x, (b, a) if ay > by else (a, b))
    return None if best is None else best[1]


# -- the public entry ------------------------------------------------------------

def trace_region(entities, point: Point, window=None):
    """(outer_polygon, [island_polygons]) of the closed region around
    ``point`` formed by the curves of ``entities``, or None when the point
    is not enclosed. Text inside the region is an island (AutoCAD's rule).
    ``window`` limits the boundary set, like AutoCAD's current viewport.
    """
    entities = [e for e in entities if e.is_alive]
    segs = segments_of(entities, window)
    # A whole sheet in view can be a hundred thousand chords; the region
    # around the point rarely needs more than what a closer look shows,
    # so the set shrinks around the point until it is tractable.
    while len(segs) > MAX_SEGMENTS and window is not None:
        x0, y0, x1, y1 = window
        px, py = point
        w, h = (x1 - x0) / 4.0, (y1 - y0) / 4.0
        if w <= 0 or h <= 0:
            break
        window = (px - w, py - h, px + w, py + h)
        segs = segments_of(entities, window)
    if len(segs) < 3:
        return None
    tol = _tolerance(segs)
    graph = _Graph(_split_at_crossings(segs, tol), tol)
    if not graph.edges:
        return None
    edge = _first_edge_right(graph, point)
    if edge is None:
        return None
    cycle = graph.walk_face(*edge)
    if cycle is None or len(cycle) < 3:
        return None
    outer = graph.polygon(cycle)
    if signed_area(outer) <= 0.0 or not point_in_polygon(outer, point):
        return None            # the unbounded face: the point is outside
    outer = _dedupe(outer)
    boundary_nodes = set(cycle)
    islands: list[list[Point]] = []
    for comp in graph.components():
        if comp & boundary_nodes:
            continue
        sample = graph.nodes[next(iter(comp))]
        if not point_in_polygon(outer, sample):
            continue
        hull = _outer_cycle(graph, comp)
        if hull is not None and len(hull) >= 3:
            islands.append(_dedupe(hull))
    islands.extend(_text_islands(entities, outer))
    return outer, islands


def _outer_cycle(graph: _Graph, comp: set[int]) -> list[Point] | None:
    """A component's outer boundary: its unbounded face, reversed. Found
    from its leftmost node, whose unbounded face is on the left of the
    edge leaving it with the smallest angle turned clockwise from "down"."""
    start = min(comp, key=lambda n: (graph.nodes[n][0], graph.nodes[n][1]))
    # from the leftmost node every edge points right; the unbounded face
    # lies to the left of the edge with the LARGEST angle (the top one)
    top = max(graph.adj[start], key=lambda m: graph._angle(start, m))
    cycle = graph.walk_face(start, top)
    if cycle is None:
        return None
    poly = graph.polygon(cycle)
    if signed_area(poly) > 0.0:      # walked a bounded face after all
        poly.reverse()
    return poly


def _dedupe(poly: list[Point]) -> list[Point]:
    out = []
    for p in poly:
        if not out or p != out[-1]:
            out.append(p)
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out


def _text_islands(entities, outer: list[Point]) -> list[list[Point]]:
    """AutoCAD keeps the hatch off any text inside the region."""
    try:
        from ezdxf import bbox as ezbbox
    except Exception:
        return []
    out = []
    for e in entities:
        if e.dxftype() not in TEXT_TYPES:
            continue
        try:
            box = ezbbox.extents([e], fast=True)
        except Exception:
            continue
        if not box.has_data:
            continue
        x0, y0 = box.extmin.x, box.extmin.y
        x1, y1 = box.extmax.x, box.extmax.y
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        if point_in_polygon(outer, (cx, cy)):
            out.append([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
    return out
