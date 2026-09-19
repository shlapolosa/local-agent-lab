"""The run as a vertical roadmap — the published methodology, with this run's state on it.

The runs page drew a Mermaid graph of EXECUTORS (`readiness`, `feasibility`, `derive_design`), which
answers "which node" when an SME is asking "which step". The nineteen rows of the published
`process-steps` artifact are what a person recognises, and each already declares its **input
artifacts**, **what is decided** and **output artifacts**.

This module invents none of that. It joins four things that already exist:

  * the published rows — the methodology, so the roadmap tracks the framework rather than a copy of
    it in code;
  * the run log's node timeline, where every step is recorded as `step_<n>` (`runlog.span_node`
    emits start on entry, done with elapsed on exit, fail with the error text);
  * the record (`screening.json` / `design.package.json`) — the section each step produced, its gap
    flags, and which steps were DEFAULTED;
  * the trace activity, for what a step cost.

And one thing that was already declared and never surfaced: **which agent performs a step**.
`Step.service` says so — ten roles across seventeen agent steps — and a DERIVED step has none,
which is a stronger statement about its answer than any name would be.

Pure by construction: no Streamlit, no Redis, no HTTP. A roadmap is a projection, and a projection
is testable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

__all__ = ["RoadmapStep", "build", "index_from"]

#: The published row's leading cell is "E0.3 Match capabilities Pre-work" — an id, a title and the
#: kind, run together. Split rather than re-typed, so the artifact stays the single source.
_ROW = re.compile(r"^(?P<id>\S+)\s+(?P<title>.*?)\s+(?P<kind>Pre-work|Decision|Gate)\s*$")

#: `published id -> ((number, record key, agent, process, reads), …)`. INJECTED, never imported: the facts come
#: from `lab.workloads.usecase.steps`, and `substrate` may not import `workloads` — that seam is what
#: keeps a workload reachable only over the network. So they are derived into a published artifact
#: (`process-step-keys`, by `scripts/derive_process_step_keys.py`) and read from the corpus like
#: every other reference. `index_from` turns those rows into this shape.
Index = Mapping[str, Sequence[tuple[str, str, str]]]

#: `published id -> its position in the process`. Separate from `Index` because it is needed even
#: for a step the implementation does not run: a corpus lookup returns records in NO order, so
#: without this the roadmap renders the methodology shuffled — measured on the running app, which
#: came back Q1.1, E0.3, E0.10, E0.4. Lexical sorting does not rescue it: "E0.10" precedes "E0.2".
Order = Mapping[str, str]


@dataclass(frozen=True)
class RoadmapStep:
    """One row of the roadmap: what the framework says, and what this run did about it."""

    id: str
    title: str
    kind: str
    numbers: tuple[str, ...] = ()
    keys: tuple[str, ...] = ()
    #: The record sections this step's agent is actually SHOWN (`agents.CONTEXT_FOR`, published).
    reads: tuple[str, ...] = ()
    agent: str = ""
    derived: bool = False
    state: str = "pending"                 # pending | running | done | failed | defaulted
    inputs_declared: str = ""
    decided: str = ""
    outputs_declared: str = ""
    #: What this run actually fed in — the record sections named by `reads`. Distinct from
    #: `inputs_declared`, which is the methodology's prose and identical on every run.
    input: Any = None
    output: Any = None
    gaps: tuple[str, ...] = ()
    note: str = ""
    elapsed: float | None = None
    error: str = ""
    model: str = ""
    tokens: int = 0
    cost: float = 0.0
    artifacts: Mapping[str, str] = field(default_factory=dict)

    @property
    def open(self) -> bool:
        """Whether a reader should find this one already expanded — what is happening now, and what
        went wrong, are the two things nobody should have to click for."""
        return self.state in ("running", "failed") or bool(self.gaps)


def order_from(rows: Sequence[Sequence[str]], headers: Sequence[str]) -> dict:
    """`published id -> sort key`, from the same artifact as the index."""
    if not rows or not headers or "Order" not in headers:
        return {}
    col = {name: i for i, name in enumerate(headers)}
    return {str(r[col.get("Step", 0)]).strip(): str(r[col["Order"]]).strip() for r in rows}


def index_from(rows: Sequence[Sequence[str]], headers: Sequence[str]) -> dict:
    """The published `process-step-keys` rows as the index `build` wants.

    Columns: Step · Number · Record key · Agent · Kind. A row with no number is a published step the
    implementation does not run as a step — a readiness gate, say — and it stays in the roadmap with
    nothing under it, because the process still has that step.
    """
    if not rows or not headers:
        return {}
    col = {name: i for i, name in enumerate(headers)}
    def cell(row, name):
        return str(row[col[name]]).strip() if name in col and col[name] < len(row) else ""

    out: dict[str, list[tuple[str, str, str, str, tuple[str, ...]]]] = {}
    for row in rows:
        ident = str(row[col.get("Step", 0)]).strip()
        number, key, agent = cell(row, "Number"), cell(row, "Record key"), cell(row, "Agent")
        # "Process" and "Reads" arrived after the first roadmap shipped. A corpus published before
        # them yields "" for both, and every consumer below treats "" as "do not filter" / "nothing
        # declared" — an app must still draw a roadmap against an older corpus.
        process = cell(row, "Process")
        reads = tuple(r.strip() for r in cell(row, "Reads").split(";") if r.strip() and r.strip() != "—")
        out.setdefault(ident, [])
        # "—" is the corpus's marker for a published step with no numbered implementation step (the
        # readiness gate). It keeps its row — the process still has that step — and contributes no
        # state, because there is nothing running to have a state.
        if number and number != "—":
            out[ident].append((number, key, agent, process, reads))
        elif process:
            # A gate runs no numbered step but still BELONGS to a process, and the roadmap has to
            # know that to keep it when filtering — otherwise the step that closes screening
            # disappears from screening's own roadmap.
            out[ident].append(("", "", "", process, ()))
    return {k: tuple(v) for k, v in out.items()}


def _states(nodes: Iterable[Mapping[str, Any]]) -> dict[str, dict]:
    """`step_<n>` -> the last thing the run log said about it.

    Tolerant of an unknown status, unlike `_node_states`, which raises `KeyError` on anything
    outside start/done/fail: a roadmap that dies because a host recorded something new is worse than
    one that shows an unrecognised step as running.
    """
    out: dict[str, dict] = {}
    for n in nodes or ():
        name = str(n.get("name") or "")
        if not name.startswith("step_"):
            continue
        attrs = n.get("attrs") or {}
        out[name[len("step_"):]] = {
            "state": {"start": "running", "done": "done", "fail": "failed"}.get(
                str(n.get("status")), "running"),
            "elapsed": attrs.get("elapsed"), "error": str(attrs.get("error") or "")}
    return out


def _gaps(section: Any, record: Mapping[str, Any], keys: Sequence[str]) -> tuple[str, ...]:
    out: list[str] = []
    if isinstance(section, Mapping):
        for flag in section.get("gap_flags") or ():
            out.append(str(flag.get("what") if isinstance(flag, Mapping) else flag))
        out += [str(u) for u in section.get("unresolved") or ()]
    for number in keys:
        pending = (record.get("pending_steps") or {}).get(number)
        if pending:
            out.append(str(pending))
    return tuple(g for g in out if g)


def build(rows: Sequence[Sequence[str]], headers: Sequence[str], index: Index | None = None, *,
          order: Order | None = None, nodes: Sequence[Mapping[str, Any]] = (),
          record: Mapping[str, Any] | None = None, process: str = "",
          activity: Sequence[Any] = ()) -> list[RoadmapStep]:
    """The roadmap for one run.

    `rows`/`headers` are the published `process-steps` artifact. **An empty artifact yields an empty
    roadmap** rather than a list from code: the methodology is published, and a fallback here would
    quietly let the app show a process the framework no longer describes.
    """
    if not rows or not headers:
        return []
    col = {name: i for i, name in enumerate(headers)}
    record = record or {}
    states = _states(nodes)
    defaulted = {str(k): str(v) for k, v in (record.get("defaulted_steps") or {}).items()}
    spend = {str(getattr(a, "node", ""))[len("step_"):]: a for a in activity
             if str(getattr(a, "node", "")).startswith("step_")}

    out: list[RoadmapStep] = []
    for row in rows:
        head = str(row[col.get("Step", 0)])
        m = _ROW.match(head)
        ident = m.group("id") if m else head.split(" ", 1)[0]
        entries = tuple((index or {}).get(ident, ()))
        # A row whose process is KNOWN and is not this one belongs to another run entirely. A row
        # whose process is unknown ("" — an older corpus, or a step nothing declares) is kept: the
        # filter removes what is certainly foreign, never what is merely unrecognised.
        if process and entries and all(p and p != process for *_, p, _ in entries):
            continue
        numbers = tuple(n for n, _, _, _, _ in entries if n)
        keys = tuple(k for _, k, _, _, _ in entries if k)
        agents = [a for _, _, a, _, _ in entries if a]
        reads = tuple(dict.fromkeys(r for *_, rs in entries for r in rs))

        # The state of a row covering several numbers is the WORST of them: a row is not done while
        # any part of it is still running, and a failure anywhere is what a reader must see first.
        seen = [states[n]["state"] for n in numbers if n in states]
        state = ("failed" if "failed" in seen else "running" if "running" in seen
                 else "done" if seen and all(s == "done" for s in seen) else "pending")
        note = ""
        if any(n in defaulted for n in numbers) and state != "failed":
            state, note = "defaulted", next(defaulted[n] for n in numbers if n in defaulted)

        section = next((record[k] for k in keys if k in record), None)
        # The ACTUAL input: the record sections this step was shown. A name the record does not
        # carry (`capabilities`, `ontology` — corpus reads, not record sections) is omitted rather
        # than shown empty, which would claim the agent saw nothing.
        shown = {k: record[k] for k in reads if k in record}
        act = next((spend[n] for n in numbers if n in spend), None)
        llm = list(getattr(act, "llm", ()) or ()) if act else []
        out.append(RoadmapStep(
            id=ident, title=(m.group("title") if m else head).strip(),
            kind=(m.group("kind") if m else ""), numbers=numbers, keys=keys, reads=reads,
            agent=agents[0] if agents else "", derived=bool(numbers) and not agents,
            state=state, note=note,
            inputs_declared=str(row[col["Input artifacts"]]) if "Input artifacts" in col else "",
            decided=str(row[col["What is decided"]]) if "What is decided" in col else "",
            outputs_declared=str(row[col["Output artifacts"]]) if "Output artifacts" in col else "",
            input=shown or None, output=section, gaps=_gaps(section, record, numbers),
            elapsed=next((states[n]["elapsed"] for n in numbers if n in states), None),
            error=next((states[n]["error"] for n in numbers if n in states and states[n]["error"]), ""),
            model=str(getattr(llm[0], "model", "")) if llm else "",
            tokens=sum(int(getattr(c, "input_tokens", 0) or 0) + int(getattr(c, "output_tokens", 0) or 0)
                       for c in llm),
            cost=round(sum(float(getattr(c, "cost", 0) or 0) for c in llm), 4)))
    # Sorted only when an order is known. Absent, the artifact's own row order stands — which is
    # right for a caller that already has them in order, and honest for one that does not.
    return sorted(out, key=lambda s: order.get(s.id, "")) if order else out
