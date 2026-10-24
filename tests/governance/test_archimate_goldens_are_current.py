"""The golden layout fixtures ARE what the engine draws — byte for byte (FR-11).

A channel porting the deterministic half of the engine proves itself against `contracts/goldens/out/`.
So any change to view composition, layout, routing or the Exchange XML must show up as a diff here, and
the failure says what to do: re-render, bump the version, tell the porters.
"""
import json
import os
import subprocess
import sys

import pytest

from lab.core.archimate import goldens

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SPECS = os.path.join(ROOT, "contracts", "goldens", "specs")
OUT = os.path.join(ROOT, "contracts", "goldens", "out")
NAMES = sorted(f[:-5] for f in os.listdir(SPECS) if f.endswith(".json"))
MESSAGE = ("layout changed — re-render goldens (`PYTHONPATH=src .venv/bin/python scripts/render_ea_contracts.py`), "
           "bump the archimate contract version (lab.core.archimate.spec_schema.VERSION), and notify channels "
           "porting the engine")


def _spec(name):
    return json.load(open(os.path.join(SPECS, f"{name}.json"), encoding="utf-8"))


@pytest.mark.parametrize("name", NAMES)
def test_each_golden_equals_what_the_engine_renders(name):
    fresh = goldens.render(_spec(name))
    committed_dir = os.path.join(OUT, name)
    committed = sorted(os.listdir(committed_dir)) if os.path.isdir(committed_dir) else []
    assert sorted(fresh) == committed, f"{name}: the files differ ({sorted(set(fresh) ^ set(committed))}) — {MESSAGE}"
    for fname, text in fresh.items():
        assert open(os.path.join(committed_dir, fname), encoding="utf-8").read() == text, f"{name}/{fname}: {MESSAGE}"


def test_no_orphan_goldens():
    assert sorted(os.listdir(OUT)) == NAMES, f"goldens without a spec, or a spec without goldens — {MESSAGE}"


def test_the_layout_does_not_depend_on_hash_order():
    """A port must be able to rely on the output being a function of the spec alone. Two interpreters
    with different hash seeds must draw the same thing."""
    probe = ("import json,sys,hashlib;from lab.core.archimate import goldens;"
             "s=json.load(open(sys.argv[1]));f=goldens.render(s);"
             "print(hashlib.sha256(''.join(k+f[k] for k in sorted(f)).encode()).hexdigest())")
    spec = os.path.join(SPECS, "cross-layer.json")
    digests = set()
    for seed in ("1", "4242"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": os.path.join(ROOT, "src")}
        env.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
        digests.add(subprocess.run([sys.executable, "-c", probe, spec], env=env, capture_output=True,
                                   text=True, check=True).stdout.strip())
    assert len(digests) == 1
