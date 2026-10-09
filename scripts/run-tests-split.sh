#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Run the test suite in N processes, each under its own Xvfb, as the CI does.
#
# One process for the whole suite grows slower test after test: what one
# test leaves alive slows the next, and v0.6.5's tag build spent 213 min in
# its Tests step (v0.6.4: 63) and then failed a timing test. Locally the
# suite has always run in four processes; this is that, for CI.
#
#   scripts/run-tests-split.sh [python] [processes]
#
# Test files are dealt round-robin, so the slow families (topography,
# layouts, viewports) spread over every process. Exit status: non-zero if
# any part failed; every part's log is printed at the end.
set -uo pipefail

PY=${1:-python}
N=${2:-4}
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
cd "$ROOT"

ls tests/test_*.py | split -n "r/$N" - "$WORK/part_"

pids=()
i=0
for part in "$WORK"/part_*; do
    i=$((i + 1))
    if command -v xvfb-run >/dev/null; then
        # -n: a server number per part; -a would race between parallel starts
        xvfb-run -n $((90 + i)) -s "-screen 0 1600x1000x24" \
            "$PY" -m pytest -q -p no:cacheprovider $(cat "$part") \
            > "$part.log" 2>&1 &
    else
        # no Xvfb (a developer's desktop): tests/conftest.py picks offscreen
        "$PY" -m pytest -q -p no:cacheprovider $(cat "$part") \
            > "$part.log" 2>&1 &
    fi
    pids+=($!)
done

status=0
for pid in "${pids[@]}"; do
    wait "$pid" || status=1
done

for log in "$WORK"/part_*.log; do
    echo "::group::$(basename "$log" .log)"
    cat "$log"
    echo "::endgroup::"
    tail -1 "$log"
done
exit $status
