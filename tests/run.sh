#!/usr/bin/env bash
# Run the whole suite. ONE PROCESS PER TEST FILE, on purpose: 11 test modules pin os.environ / config at
# import (script-style), so a single-process `pytest tests` lets the last-imported module's environment leak
# into every other module's tests (22 false failures). Per-file processes reproduce the script semantics
# exactly; `pytest <one file>` (or any non-colliding subset) still works interactively.
# Backlog: move import-time env pinning into monkeypatch fixtures, then collapse this to `pytest tests`.
# `--cov` adds branch coverage (coverage.py, combined across the per-file processes; .coveragerc).
# Offline except tests/integration (local Redis; they skip themselves when it is unreachable).
set -u
cd "$(dirname "$0")/.."
PY=.venv/bin/python
export PYTHONPATH="src:tests${PYTHONPATH:+:$PYTHONPATH}"   # `lab` + `fixtures` importable even without pip install -e .
COV=${1:-}
have_pytest=0; $PY -c "import pytest" 2>/dev/null && have_pytest=1
mkdir -p var/coverage; rm -f var/coverage/.coverage var/coverage/.coverage.*
fail=0
for t in $(find tests -name 'test_*.py' | sort); do
  if [ $have_pytest -eq 1 ]; then
    if [ "$COV" = "--cov" ]; then out=$($PY -m coverage run -p --rcfile=.coveragerc -m pytest -q -p no:warnings "$t" 2>&1)
    else out=$($PY -m pytest -q -p no:warnings "$t" 2>&1); fi
  else
    if [ "$COV" = "--cov" ]; then out=$($PY -m coverage run -p --rcfile=.coveragerc "$t" 2>&1)
    else out=$($PY "$t" 2>&1); fi
  fi
  if [ $? -eq 0 ]; then echo "PASS $t  $(echo "$out" | tail -1)"; else fail=1; echo "FAIL $t"; echo "$out" | tail -8 | sed 's/^/    /'; fi
done
if [ "$COV" = "--cov" ]; then
  $PY -m coverage combine --rcfile=.coveragerc -q && $PY -m coverage report --rcfile=.coveragerc --sort=cover
fi
exit $fail
