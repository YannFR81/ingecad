# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Regenerate the model on several cores (#31).

A full regen is ezdxf's drawing frontend -- pure Python, one entity after
another -- and nearly all of it: on Plaza Yanque (10 000 objects) 4.26 s of
the frontend against 0.11 s of packing. Python threads share one GIL, so the
cores sat idle while the window waited.

Each worker is a fork of this process: it inherits the drawing as it is in
memory (nothing to serialise, nothing to re-read), draws ITS share of the
entities through the very same ``draw_layout`` -- a filter lets through only
its handles, so the redraw order, the background, the annotation scale and
every other rule are the ones a serial regen applies -- and sends back its
buckets. The parent stitches them in order and packs as before.

The shares are runs of consecutive entities in redraw order, cut by an
estimate of what each costs -- an INSERT costs what its block holds, nested
blocks included -- four per worker, each handed to whichever worker is
free. What cannot be split (one block of 15 000 objects) bounds the
speed-up.

Linux only (fork); anywhere else, for a small drawing, or if anything goes
wrong -- a worker that fails or takes too long -- the caller draws serially,
as it always did. ``INGECAD_SERIAL_REGEN=1`` forces the serial path.
"""
from __future__ import annotations

import logging
import os
import sys
import warnings
from dataclasses import fields
from typing import Optional

logger = logging.getLogger(__name__)

#: Below this estimated cost a fork costs more than it saves (measured: the
#: pool alone is ~0.1 s; a 3 000-object plan draws in well under a second).
MIN_COST = 20000
#: Cost of an entity that is not a block reference.
BASE_COST = {"HATCH": 40, "MTEXT": 6, "DIMENSION": 12, "ARC_DIMENSION": 12,
             "LEADER": 4, "MULTILEADER": 8, "MLEADER": 8, "SPLINE": 4,
             "TEXT": 3, "ATTRIB": 3}
#: Runs per worker: each takes the next free run when it finishes one.
SHARES_PER_WORKER = 4
#: A worker that has not answered in this long is given up on.
TIMEOUT_S = 60.0

_BUCKET_LISTS = None          # the list fields of Bucket, read once


def available() -> bool:
    return (sys.platform.startswith("linux") and hasattr(os, "fork")
            and os.environ.get("INGECAD_SERIAL_REGEN", "") not in ("1", "true"))


def workers() -> int:
    return max(1, min(8, (os.cpu_count() or 1) - 1))


def entity_costs(layout) -> list[tuple[str, int]]:
    """(handle, estimated cost) of every entity, in redraw order."""
    from ezdxf import reorder

    doc = layout.doc
    memo: dict[str, int] = {}

    def block_cost(name: str, depth: int = 0) -> int:
        if name in memo:
            return memo[name]
        memo[name] = 1                       # a cycle costs little
        block = doc.blocks.get(name) if depth < 16 else None
        total = 1
        if block is not None:
            for e in block:
                total += cost(e, depth + 1)
        memo[name] = total
        return total

    def cost(entity, depth: int = 0) -> int:
        kind = entity.dxftype()
        if kind == "INSERT":
            return 1 + block_cost(entity.dxf.name, depth)
        return BASE_COST.get(kind, 1)

    order = list(layout.get_redraw_order())
    entities = reorder.ascending(layout, order) if order else layout
    return [(e.dxf.handle, cost(e)) for e in entities]


def split(costs: list[tuple[str, int]], parts: int) -> list[frozenset]:
    """Consecutive runs of about the same total cost."""
    total = sum(c for _h, c in costs)
    target = total / parts
    runs, run, acc = [], [], 0.0
    for handle, c in costs:
        run.append(handle)
        acc += c
        if acc >= target * (len(runs) + 1) and len(runs) < parts - 1:
            runs.append(frozenset(run))
            run = []
    runs.append(frozenset(run))
    return [r for r in runs if r]


def draw_parallel(make_frontend, layout, *, min_cost: int = MIN_COST,
                  processes: Optional[int] = None):
    """Draw ``layout`` on several processes; the merged ``VertexBackend``
    and the skipped-entity notes -- or None, and the caller draws serially.

    ``make_frontend()`` builds a fresh (frontend, backend) pair, exactly as
    the serial regen does; it is called in each worker after the fork.
    """
    if not available():
        return None
    processes = processes or workers()
    if processes < 2:
        return None
    try:
        costs = entity_costs(layout)
    except Exception as exc:                  # noqa: BLE001 - serial will do
        logger.warning("parallel regen: cannot estimate costs: %s", exc)
        return None
    if sum(c for _h, c in costs) < min_cost:
        return None
    # many small runs, handed to whichever worker is free: the estimate
    # only has to be roughly right (a solid HATCH costs little, an MTEXT
    # more than it looks), and the slowest run no longer sets the pace
    shares = split(costs, processes * SHARES_PER_WORKER)
    if len(shares) < 2:
        return None

    def work(share):
        frontend, backend = make_frontend()
        frontend.draw_layout(layout, filter_func=lambda e: e.dxf.handle in share)
        return backend.buckets, backend.images, backend.background, list(frontend.skipped)

    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor

    global _WORK
    _WORK = work                  # the forked children find it here
    try:
        with warnings.catch_warnings():
            # "this process is multi-threaded, fork() may deadlock": the
            # children run only ezdxf and never Qt (see _run_share), and a
            # child that dies or hangs anyway costs a serial regen, not the
            # drawing: a dead one is noticed at once (BrokenProcessPool),
            # a stuck one at the timeout
            warnings.simplefilter("ignore", DeprecationWarning)
            pool = ProcessPoolExecutor(
                max_workers=min(processes, len(shares)),
                mp_context=multiprocessing.get_context("fork"))
            try:
                # the children fork on the first submit, inside this filter
                parts = list(pool.map(_run_share, shares, timeout=TIMEOUT_S))
            finally:
                for process in list(getattr(pool, "_processes", {}).values()):
                    process.kill()    # a stuck child must not outlive the regen
                pool.shutdown(wait=False, cancel_futures=True)
    except Exception as exc:                  # noqa: BLE001 - serial will do
        logger.warning("parallel regen failed, drawing serially: %s: %s",
                       type(exc).__name__, exc)
        return None
    finally:
        _WORK = None
    return _merge(make_frontend()[1], parts)


_WORK = None


def _run_share(share):
    # The fork copied every object of the window, Qt wrappers included. A
    # garbage collection here would run their destructors outside Qt's
    # thread -- the crash core/gc_guard exists for. The child lives for
    # seconds: it never collects.
    import gc

    gc.disable()
    return _WORK(share)


def _merge(backend, parts):
    """The workers' buckets, stitched in share order into ``backend``."""
    global _BUCKET_LISTS
    skipped: list[str] = []
    for buckets, images, background, notes in parts:
        for key, bucket in buckets.items():
            mine = backend.buckets.get(key)
            if mine is None:
                backend.buckets[key] = bucket
                continue
            if _BUCKET_LISTS is None:
                _BUCKET_LISTS = [f.name for f in fields(bucket)
                                 if isinstance(getattr(bucket, f.name), list)]
            for name in _BUCKET_LISTS:
                getattr(mine, name).extend(getattr(bucket, name))
            mine.text_height_sum += bucket.text_height_sum
            mine.text_count += bucket.text_count
        backend.images.extend(images)
        if background is not None:
            backend.background = background
        skipped.extend(notes)
    return backend, skipped
