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

if [ "$MODE" = "--cov" ]; then
  mkdir -p var/coverage; rm -f var/coverage/.coverage var/coverage/.coverage.*
  exec $PY -m pytest -q -p no:warnings --cov --cov-branch --cov-config=.coveragerc --cov-report=term tests
fi

exec $PY -m pytest -q -p no:warnings tests
