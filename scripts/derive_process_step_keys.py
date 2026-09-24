"""Derive the join between the PUBLISHED process steps and the code's steps — as data.

The roadmap needs three things the published `process-steps` artifact does not carry: which numbered
step of the implementation each published row corresponds to, which section of the record it
produces, and WHICH AGENT performs it. All three are declared in `lab.workloads.usecase.steps`
(`Step(number, key, service, …)`), and the review app may not import that — `substrate` never
imports `workloads`, which is the seam that keeps a workload reachable only over the network.

So it is generated here, committed as seed, published as an artifact, and read by the app from the
corpus under a pin like every other reference. A generator may import across tiers; a running
service may not.

    PYTHONPATH=src .venv/bin/python scripts/derive_process_step_keys.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from lab.workloads.usecase.agents import CONTEXT_FOR                     # noqa: E402
from lab.workloads.usecase.steps import (DERIVED_STEP_NUMBERS, DESIGN_STEPS,   # noqa: E402
                                         SCREENING_STEPS, STEPS)

SEED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                    "src", "lab", "core", "usecase", "seed")

#: What the corpus writes for "no numbered step here" — the framework's own marker for absence.
NONE = "—"

#: published step id -> the implementation step numbers it covers. The ONE judgement in this file:
#: the two vocabularies are independent (E0.4 is step 6, and nothing in either name says so), so the
#: correspondence is asserted once, here, where it can be read and argued with.
COVERS = {
    "E0.1": ("3",), "E0.2": ("4",), "E0.3": ("5",), "E0.4": ("6",), "E0.5": ("8",),
    "E0.6": ("9",), "E0.7": ("10",), "E0.8": ("11",), "E0.9": ("7",), "E0.10": ("13",),
    "Q0.8–Q0.9": (), "Q1.1–Q1.5": ("15",), "Q2.1–Q2.4": ("17", "18"),
    "Q3.1–Q3.4": ("19",), "Q4.1–Q4.3": ("20",), "Q5.1–Q5.3": ("21",),
    "Q6.1–Q6.2": ("22",), "Q7.1": ("25",), "Q7.2–Q7.3": ("23", "24"),
}

#: Which PROCESS runs a published row. The roadmap drew all nineteen rows for every run, so a
#: screening — which implements E0.1–E0.10 and the gate, and nothing below Q1.1 — showed ten rows
#: permanently pending and read as half-finished when it had in fact completed. The split is not a
#: judgement: `SCREENING_STEPS` and `DESIGN_STEPS` already declare it. Only the two rows with no
#: numbered step of their own need saying, and the readiness gate closes screening by definition.
GATE_PROCESS = {"Q0.8–Q0.9": "screening"}



def _write(stem: str, payload: dict) -> None:
    """Write the seed JSON and its master THROUGH the corpus generator.

    Not `master.render` directly: `tests/unit/core/usecase/test_seed.py` requires every committed
    master to be byte-reproducible by `extract_cafe_seed.masters_for`, because the masters are
    hashed and signed — one the generator cannot reproduce is an input nobody can verify. One
    renderer, therefore, and this file only decides the ROWS.
    """
    import importlib.util

    with open(os.path.join(SEED, f"{stem}.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    spec = importlib.util.spec_from_file_location(
        "_extract", os.path.join(root, "scripts", "extract_cafe_seed.py"))
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    for name, text in generator.masters_for(stem, payload).items():
        with open(os.path.join(SEED, "masters", f"{name}.md"), "w", encoding="utf-8") as fh:
            fh.write(text)


def main() -> int:
    by_number = {s.number: (s.key, s.service) for s in STEPS}
    for key, number in DERIVED_STEP_NUMBERS.items():
        by_number.setdefault(number, (key, ""))          # derived: no agent, deliberately
    # A derived step belongs to the process that runs the step it derives from; every derived
    # number here (18, 19, 22, 23, 24) is part of the design half.
    process_of = {s.number: "screening" for s in SCREENING_STEPS}
    process_of |= {s.number: "design" for s in DESIGN_STEPS}
    for number in DERIVED_STEP_NUMBERS.values():
        process_of.setdefault(number, "design")

    rows = []
    for position, (ident, numbers) in enumerate(COVERS.items(), start=1):
        # "—" for a published step the implementation runs no numbered step for (the readiness
        # gate). Not "": the natural key is `Step,Number`, and the publisher REFUSES a row missing a
        # key field — correctly, since a blank key is not a key. "—" is what the framework's own
        # artifacts already use for "none", so the marker is borrowed rather than invented.
        for number in numbers or ("—",):
            key, agent = by_number.get(number, ("", ""))
            # ORDER is carried explicitly. A corpus lookup returns records in no particular order —
            # verified on the running app, where the roadmap came back Q1.1, E0.3, E0.10, E0.4 — and
            # a roadmap out of process order is a list, not a roadmap. Lexical sorting cannot save
            # it either: "E0.10" sorts before "E0.2".
            # What the agent is actually SHOWN. `CONTEXT_FOR` is the one declaration of it, and
            # the roadmap needs it to say what a step's real INPUT was rather than repeating the
            # methodology's prose — which was the same for every run and therefore told a reviewer
            # nothing about theirs. Published as data for the same reason the rest of this file is:
            # `substrate` may not import `workloads`.
            reads = "; ".join(CONTEXT_FOR.get(key, ())) or NONE
            rows.append([ident, number, key, agent,
                         "derived" if number != NONE and not agent else "gate" if number == NONE
                         else "agent", f"{position:02d}",
                         process_of.get(number, GATE_PROCESS.get(ident, "")) or NONE, reads])
    unknown = [r for r in rows if r[1] != NONE and not r[2]]
    if unknown:
        raise SystemExit(f"step numbers with no step: {[r[1] for r in unknown]}")

    headers = ["Step", "Number", "Record key", "Agent", "Kind", "Order", "Process", "Reads"]
    payload = {"step_keys": {"headers": headers, "rows": rows},
               "_source": "derived from lab.workloads.usecase.steps by "
                          "scripts/derive_process_step_keys.py — regenerate when a step is added"}
    _write("process_step_keys", payload)
    agents = sorted({r[3] for r in rows if r[3]})
    print(f"{len(rows)} rows, {len(agents)} agents: {agents}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
