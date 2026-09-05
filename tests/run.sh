#!/usr/bin/env bash
# Run the whole suite in ONE pytest process.
#
# It used to be one process PER TEST FILE, because 11 modules pinned os.environ (and module-level
# config) at IMPORT time, so in a shared process the last-imported module's environment leaked into
# every other module's tests. Those modules now pin the environment in fixtures instead, and
# tests/conftest.py closes the process-global seams for everyone: os.environ and the OpenTelemetry
# tracer provider are snapshotted and restored around every test, and `import litellm`'s
# `load_dotenv()` — which poured the real .env (Entra secrets, the Neon DATABASE_URL, the cloud
# REDIS_URL) into the suite — is done and undone once, before collection.
#
#   tests/run.sh              the suite
#   tests/run.sh --cov        + branch coverage (pytest-cov, .coveragerc: source, omits, fail_under)
#   tests/run.sh --by-tier    several processes sized by MEASURED memory (workloads per file).
#                             Use when the single process is being OOM-killed — the symptom is
#                             progress dots and then no summary at all.
#   tests/run.sh --per-file   FALLBACK: one process per file, the old behaviour. Use it to tell a
#                             genuine failure from a new cross-test coupling — if a test passes here
#                             but not in the single process, something leaks process-global state.
#
# Offline except tests/integration (local Redis; they skip themselves when it is unreachable).
set -u
cd "$(dirname "$0")/.."
PY=.venv/bin/python
export PYTHONPATH="src:tests${PYTHONPATH:+:$PYTHONPATH}"   # `lab` + `fixtures` importable even without pip install -e .
MODE=${1:-}

if [ "$MODE" = "--per-file" ]; then
  fail=0
  for t in $(find tests -name 'test_*.py' | sort); do
    out=$($PY -m pytest -q -p no:warnings "$t" 2>&1)
    if [ $? -eq 0 ]; then echo "PASS $t  $(echo "$out" | tail -1)"; else fail=1; echo "FAIL $t"; echo "$out" | tail -8 | sed 's/^/    /'; fi
  done
  exit $fail
fi

# --by-tier: split the suite into several processes instead of one, sized by MEASURED memory.
#
# Measured on this machine (peak RSS), and each number changed the design:
#   ~235 MB   the floor — importing agent_framework, litellm, rdflib and OpenTelemetry, which
#             conftest pulls in before a single test runs. Every process pays this.
#   ~240-355  any single test FILE, including the heaviest.
#   ~2300 MB  tests/unit/workloads as ONE process.
#
# It is NOT a leak, and it is worth saying so because the obvious conclusion is wrong. A tracemalloc
# diff across six workload modules found NO allocation site growing by even 1 MB, and the live-object
# count returns to its baseline after each module (1.49M -> 2.27M -> 1.49M). Nothing is retained.
# What grows is the high-water mark: a couple of modules allocate hard and briefly — building real
# Agent Framework graphs, and the DevUI run-log tests touching 2.27M live objects at their peak — and
# the allocator does not hand those pages back to the OS. One long process therefore keeps the worst
# moment of every module forever; a fresh process per file does not.
#
# So the split below is the remedy rather than a workaround: the workloads package runs FILE BY FILE,
# everything else runs one process per tier. The single-process default remains the fast path; use
# this when it is being OOM-killed, which looks like progress dots and then no summary at all.
if [ "$MODE" = "--by-tier" ]; then
  fail=0
  printf "\n=== tests/unit (excluding workloads)\n"
  $PY -m pytest -q -p no:warnings tests/unit --ignore=tests/unit/workloads || fail=1
  printf "\n=== tests/unit/workloads (per file — 2.3 GB high-water mark in one process)\n"
  for t in $(find tests/unit/workloads -name 'test_*.py' | sort); do
    out=$($PY -m pytest -q -p no:warnings "$t" 2>&1)
    if [ $? -eq 0 ]; then echo "  PASS $(basename $t)  $(echo "$out" | tail -1)"
    else fail=1; echo "  FAIL $t"; echo "$out" | tail -8 | sed 's/^/      /'; fi
  done
  for tier in tests/governance tests/deploy tests/integration; do
    [ -d "$tier" ] || continue
    printf "\n=== %s\n" "$tier"
    if $PY -m pytest -q -p no:warnings "$tier"; then :; else fail=1; fi
  done
  exit $fail
fi

if [ "$MODE" = "--cov" ]; then
  mkdir -p var/coverage; rm -f var/coverage/.coverage var/coverage/.coverage.*
  exec $PY -m pytest -q -p no:warnings --cov --cov-branch --cov-config=.coveragerc --cov-report=term tests
fi

exec $PY -m pytest -q -p no:warnings tests
