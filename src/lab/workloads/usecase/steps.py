"""The nine screening steps: their schema, and the completeness rule a schema cannot express.

A schema says the shape is right. It cannot say the answer is. Every rule below is a sentence from
the specification that valid JSON would otherwise walk straight past:

* step 3 — "reject a problem stated as a solution, and reject shared accountability" (FR-05)
* step 4 — "sequence nothing; an implied order means you have skipped to E0.7" (E0.2)
* step 5 — "never invent a capability to justify the use case" (FR-07); coverage BOTH ways
* step 6 — "record confidence as lookup, assumption or survey" (FR-08)
* step 7 — the band is PROVISIONAL, for the feasibility verdict only
* step 8 — a numeric response measure "taken from an existing business commitment" (FR-13)
* step 9 — the check is at OBJECT level, coverage AND conflict (FR-14)
* step 10 — "one step per business function per active element" (FR-15)
* step 11 — "a citation policy in every retrieval contract" (FR-16)

Each is a pure function over the agent's output, so it is tested without a model and the rule can
be read next to the sentence that requires it.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from lab.core.usecase.model import VOCABULARY, canonical_facet
from lab.core.usecase.predicates import NAMED_CONDITIONS, normalise_value
from lab.workloads.usecase.gates import validator_for
from lab.core.usecase import enforcement
from lab.workloads.usecase.mappers import as_list

__all__ = ["CAPABILITY_QUERY", "DESIGN_STEPS", "SCREENING_STEPS", "STEPS", "Step", "schema",
           "step_for"]

SCHEMAS = Path(__file__).parent / "schemas"
PROMPTS = Path(__file__).parent / "prompts"

#: Words that turn a problem statement into a solution statement. FR-05 rejects the second, because
#: a use case framed as its answer has already skipped the assessment it came for.
_SOLUTION_WORDS = ("we need a", "we should build", "implement a", "deploy a", "use an llm",
                   "use ai to", "a chatbot", "a copilot", "an agent that", "rpa")

#: An implied order in the behavioural list. E0.2: "sequence nothing" — ordering is step 10's job,
#: and a decomposition that has already ordered has skipped the exercise.
_ORDER_WORDS = ("first", "then", "next", "finally", "afterwards", "subsequently", "step 1",
                "step 2", "before that", "once that")


def schema(name: str) -> dict:
    out = json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))
    if name == "facet_vectors":
        # The nine conditions are declared ONCE, in `predicates.NAMED_CONDITIONS`; the schema the
        # model reads and the validator checks carries them by name, each required. A free-form
        # object with two examples left the model to guess the exact strings, and the gate refused
        # every answer twice in the first live design run (13 Sep 2026).
        conditions = out["properties"]["steps"]["items"]["properties"]["conditions"]
        conditions["properties"] = {c: {"type": "boolean"} for c in sorted(NAMED_CONDITIONS)}
        conditions["required"] = sorted(NAMED_CONDITIONS)
        conditions["additionalProperties"] = False
        conditions["description"] = ("Answer EVERY one of these conditions for THIS step, true or "
                                     "false, using the exact keys listed. An unanswered condition is "
                                     "refused, never read as false: a guardrail that silently fails "
                                     "to fire is invisible.")
        # Every facet's PUBLISHED values, as the enum the model reads and the validator checks —
        # from the domain, the one place they are declared. A free string left the model to write
        # "assess AI use case" for an activity, which the exposure derivation refused twenty minutes
        # later (14 Sep 2026); a contract the model cannot read is not a contract.
        facets = out["properties"]["steps"]["items"]["properties"]
        for facet, values in VOCABULARY.items():
            if facet in facets:
                facets[facet]["enum"] = list(values)
    return out


def _normalise_facets(out: dict) -> None:
    """A near-miss spelling of a published value ("Interpret", "record-write") becomes the
    published one before the schema sees it; a value no spelling of which is published is left
    for the enum to refuse by name."""
    for step in out.get("steps") or []:
        if not isinstance(step, dict):
            continue
        for facet in VOCABULARY:
            if facet in step and isinstance(step[facet], str):
                step[facet] = canonical_facet(facet, step[facet]) or step[facet]


def prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8")


@dataclass(frozen=True)
class Step:
    """One screening step: which agent performs it, what it emits, and what makes it complete."""
    number: str
    key: str                    # the field it contributes to the screening record
    service: str                # the bounded context that owns it
    #: `(out, context)` — the context is what the agent was shown; most rules ignore it, step
    #: 21's checks a component id against the pinned catalogue it was given.
    complete: Callable[[dict, Mapping[str, Any] | None], list[str]]
    #: A few words for what this step DOES, for a person watching a run. `step_5` is an address,
    #: not a description, and nobody should have to hold a 25-step numbering in their head to read
    #: a progress page. It lives here because the same label is wanted by the screening record
    #: (`pending_steps`), the run log and the live view — three readers, one home.
    title: str = ""
    normalise: Callable[[dict], None] | None = None
    #: A rule whose second shortfall is RECORDED on the answer under `soft_key` rather than raised —
    #: something the design still owes, which a reviewer must see (see `gates.run_gated`).
    soft: Callable[[dict, Mapping[str, Any] | None], list[str]] | None = None
    soft_key: str = "unresolved"
    #: What the RETRY is told to do about a soft finding — never written onto the answer, which a
    #: person reads as a design record, not as an instruction.
    soft_remedy: str = ""

    def validator(self):
        return validator_for(schema(self.key))

    def prompt(self) -> str:
        return prompt(self.key)


# ---------------------------------------------------------------- the completeness rules

def _frame(out: dict, context: Mapping[str, Any] | None = None) -> list[str]:
    bad = []
    problem = str(out.get("problem", "")).lower()
    hit = [w for w in _SOLUTION_WORDS if w in problem]
    if hit:
        bad.append(f"the problem is stated as a solution ({hit[0]!r}) — say what is wrong and for "
                   f"whom, not what to build; choosing the answer is what the rest of this "
                   f"assessment is for")
    owner = str(out.get("accountable_owner", "")).strip()
    # An owner the submission does not name is an OPEN QUESTION, not a failure. A live run proved
    # why: the model read a submission that names nobody, said so honestly, and the gate refused it
    # — leaving one honest answer and one fabricated one, of which only the fabricated one passes.
    # That is the opposite of what every prompt here asks for. A gap that reaches a human gets
    # closed; a name invented to satisfy a gate never does.
    unnamed = not owner or any(w in owner.lower() for w in (
        "unspecified", "not named", "unknown", "names no person", "no person", "no named",
        "no individual", "nobody", "no one", "no-one", "not identified"))
    if unnamed:
        if not any("owner" in str(q).lower() or "accountab" in str(q).lower()
                   for q in out.get("open_questions") or []):
            bad.append("no accountable owner is named and no open question asks for one — an "
                       "unowned use case must reach a human as a question, not pass as an answer")
        return bad[:5]
    # `&` and `/` are not word characters, so a `\b` around them matches nothing — the separators
    # have to be looked for literally, and " and " needs its spaces or it fires inside "Alexander".
    # A COMMA is deliberately not a separator: "Jane Smith, Chief Medical Officer" is one person
    # with a title, and treating punctuation as plurality refused more honest answers than shared
    # ones.
    # Judged on the NAME — the first clause — not on an explanation that follows a dash or a full
    # stop: "the reviewing architect — who assesses and signs off" is one seat, and a live run was
    # refused twice for the "and" inside its explanation (11 Sep 2026).
    name = re.split(r"\s—\s|\s-\s|\.\s|;", owner, maxsplit=1)[0]
    shared = any(sep in name for sep in ("&", "/")) or " and " in f" {name} "
    if shared or any(w in name.lower() for w in (" team", " group", " department", " unit")):
        bad.append(f"accountability is shared ({owner!r}) — name ONE person; a use case everyone "
                   f"owns is a use case nobody answers for")
    return bad


def _elements(out: dict, context: Mapping[str, Any] | None = None) -> list[str]:
    bad = []
    for kind in ("active", "behavioural", "passive"):
        if not out.get(kind):
            bad.append(f"the {kind} list is empty — a decomposition that found no {kind} elements "
                       f"has not been done")
    ordered = [b["name"] for b in out.get("behavioural") or []
               if any(w in str(b.get("name", "")).lower() for w in _ORDER_WORDS)]
    if ordered:
        bad.append(f"the behavioural list implies an order ({ordered[:2]}) — sequence nothing here; "
                   f"ordering is step 10, and a decomposition that has already ordered has skipped "
                   f"the exercise")
    return bad


def _coverage_map(out: dict, context: Mapping[str, Any] | None = None) -> list[str]:
    bad = []
    if not out.get("matched") and not out.get("functions_without_capability"):
        bad.append("neither a match nor an unmatched function — the coverage check was not done")
    for match in out.get("matched") or []:
        if not str(match.get("capability_id", "")).strip():
            bad.append(f'{match.get("function")!r} names no capability id — a capability must be '
                       f'looked up, never invented to justify the use case')
    # The id must be one this step was SHOWN, checked the way step 21 checks a component id: a
    # reasoning model substitutes the human-readable label for the key (measured by the minutes
    # workload, 12 Sep 2026 — nine of nine identifiers), and recall cannot see it because the label
    # is right. A capability id nothing can look up is a match the design cannot build on.
    known = {str(row.get("id", "")) for row in (context or {}).get("capabilities") or []
             if isinstance(row, Mapping) and row.get("id")}
    unknown = sorted({str(m.get("capability_id")) for m in out.get("matched") or []
                      if str(m.get("capability_id", "")).strip()
                      and str(m.get("capability_id")) not in known})
    if unknown and known:
        bad.append(f"{unknown} are not ids among the capabilities this step was shown — use the "
                   f"`id` column, not the label; a match is a lookup, not a paraphrase")
    if "capabilities_without_function" not in out:
        bad.append("coverage must be reported BOTH ways, even where the second direction is empty")
    # The heat-map position is what step 16's reject rule reads. Required whenever anything
    # matched, and required WITH its source: a capability that is commodity, mature and already
    # meeting target is a reason not to build, and that verdict must rest on a lookup rather than
    # on an agent's impression of how common the capability feels.
    # Ten matches, none of them a lookup, and nothing saying so (run 5, 15 Sep 2026): a coverage
    # map every line of which was inferred from labels reads exactly like one read off the map. The
    # confidence is not forced up — that would be fabricating certainty — the map is made to SAY it.
    matched = out.get("matched") or []
    if matched and not any(str(m.get("confidence")) == "lookup" for m in matched):
        if not any("infer" in str(g.get("what", "")).lower() or "assumption" in str(g.get("what", "")).lower()
                   or "lookup" in str(g.get("what", "")).lower() for g in out.get("gap_flags") or []):
            bad.append(f"none of the {len(matched)} matches is a `lookup` — every one was inferred "
                       f"from labels, and a map that does not say so reads like one read off the "
                       f"published map; add a gap flag saying the matching is inferred and naming "
                       f"the body that owns the authoritative mapping")
    heat = out.get("heat_map")
    if out.get("matched") and not heat:
        bad.append("a capability matched but its heat-map position is missing — the "
                   "commodity/mature/meets-target reject rule cannot fire without it, and a rule "
                   "that never fires is one nobody can tell is broken")
    elif heat and not str(heat.get("source", "")).strip():
        bad.append("the heat-map position names no source — it is a LOOKUP against the published "
                   "capability map, not a judgement made here")
    # A TRUE position needs a column to have been read from. The rows this step is shown carry
    # `id/label/level/parent/path` unless a tenant heat map is published beside them — and on 14 Sep
    # 2026 a model wrote "lookup from published capability map" over all three flags for a map that
    # carries none, which rejected the case on a position nobody had assessed.
    elif heat and any(heat.get(k) is True for k in _HEAT_FLAGS) and context is not None:
        rows = [r for r in (context.get("capabilities") or []) if isinstance(r, Mapping)]
        if rows and not any(k in row for row in rows for k in _HEAT_COLUMNS):
            bad.append("the heat-map position claims a lookup but the capabilities this step was "
                       "shown carry no heat-map column (commodity / maturity / meets-target) — "
                       "there is nothing to look up: answer false and let `source` say the "
                       "published map carries no heat-map position")
    return bad


_HEAT_FLAGS = ("commodity", "mature", "meets_target")
#: A row carrying any of these was published WITH a heat-map position a lookup can read.
_HEAT_COLUMNS = ("commodity", "mature", "maturity", "meets_target", "meets-target", "target",
                 "heat", "heat_map", "tier")


def _realisation_match(out: dict, context: Mapping[str, Any] | None = None) -> list[str]:
    bad = []
    if not out.get("matched") and not out.get("unrealised"):
        bad.append("no element was matched and none reported unrealised — the check was not done")
    for match in out.get("matched") or []:
        if match.get("confidence") == "survey" and not (out.get("gap_flags") or []):
            bad.append(f'{match.get("element")!r} was matched by SURVEY with no gap flag — a survey '
                       f'result is a gap flag candidate, never a silent assumption')
    return bad


def _criticality_band(out: dict, context: Mapping[str, Any] | None = None) -> list[str]:
    if out.get("provisional") is not True:
        return ["the band must be marked provisional — it exists for the feasibility verdict only, "
                "and step 12 derives the confirmed class independently"]
    return []


def _quality_attributes(out: dict, context: Mapping[str, Any] | None = None) -> list[str]:
    bad = []
    for scenario in out.get("scenarios") or []:
        taken = str(scenario.get("taken_from", "")).strip().lower()
        if not taken or taken in ("none", "n/a", "assumed", "estimated"):
            bad.append(f'{scenario.get("function")!r} has no business commitment behind its '
                       f'response measure — a service level is taken from an existing commitment '
                       f'or it is a gap flag, never invented')
    if not out.get("scenarios") and not (out.get("gap_flags") or []):
        bad.append("no scenarios and no gap flags — where no commitment exists, RAISE the gap")
    return bad


def _ontology_delta(out: dict, context: Mapping[str, Any] | None = None) -> list[str]:
    if not out.get("concepts"):
        return ["no business object was checked — the ontology check is per OBJECT, and an empty "
                "result means it was not run"]
    if "conflicts" not in out:
        return ["conflicts must be reported even where empty — one word meaning two things is the "
                "half of this check that a coverage list cannot show"]
    return []


def _workflow_graph(out: dict, context: Mapping[str, Any] | None = None) -> list[str]:
    bad = []
    nodes = {n["id"] for n in out.get("nodes") or []}
    if not nodes:
        bad.append("the graph has no nodes — a workflow that cannot be stated explicitly is a "
                   "Board escalation, not an empty answer")
    for edge in out.get("edges") or []:
        for end in ("from", "to"):
            if edge.get(end) not in nodes:
                bad.append(f'an edge names {edge.get(end)!r}, which is not a node in this graph')
        if not str(edge.get("data_class", "")).strip():
            bad.append(f'the edge {edge.get("from")}->{edge.get("to")} carries no data class — '
                       f'every data-flow edge carries a business object')
    bad += _decomposes(out, context)
    return bad[:5]


def _decomposes(out: dict, context: Mapping[str, Any] | None = None) -> list[str]:
    """The graph must be a DECOMPOSITION, not the function list renamed.

    Run 8 (15 Sep 2026): ten functions in, ten nodes out, each node's activity the function's own
    words. Everything after this step reasons about the graph — the determinism tier, the facet
    vector, the exposure, the control set are all PER NODE — so a graph that adds no detail makes
    the whole risk chain exactly as coarse as the inventory it copied, while looking like analysis.

    A function that genuinely is one step stays one node; what is refused is EVERY function being
    one, which is the signature of a rename rather than a decomposition.
    """
    functions = [str(b.get("name", "")).strip()
                 for b in ((context or {}).get("elements") or {}).get("behavioural") or []
                 if isinstance(b, Mapping) and str(b.get("name", "")).strip()]
    nodes = [n for n in out.get("nodes") or [] if isinstance(n, Mapping)]
    if len(functions) < 3 or len(nodes) != len(functions):
        return []
    named = {normalise_value(f) for f in functions}
    restated = [n for n in nodes if normalise_value(str(n.get("activity", ""))) in named]
    if len(restated) < len(nodes):
        return []
    return [f"the graph restates the function list — {len(nodes)} nodes for {len(functions)} "
            f"functions, each named after one of them. A function is what the business DOES; a node "
            f"is a step that does it, with a performer and the data it moves. Decompose at least the "
            f"functions that take more than one action (retrieve, then interpret, then record), and "
            f"keep one node only where the function genuinely is one step"]


def _source_contracts(out: dict, context: Mapping[str, Any] | None = None) -> list[str]:
    bad = []
    for source in out.get("sources") or []:
        if not str(source.get("citation_policy", "")).strip():
            bad.append(f'{source.get("source")!r} has no citation policy — every retrieval contract '
                       f'carries one, or the grounding cannot be audited')
    if not out.get("sources") and not (out.get("gap_flags") or []):
        bad.append("no source was contracted and no gap flagged — a source with no contract FAILS "
                   "readiness, so it must be reported either way")
    return bad



# ---------------------------------------------------------------- the design-side rules

def _assertions(out: dict, context: Mapping[str, Any] | None = None) -> list[str]:
    """E0.10 / FR-18: "evaluable against a system of record without reading anything the workflow
    produced". The rule this enforces is the difference between monitoring and self-congratulation:
    an assertion that reads the workflow's own output is true whenever the workflow says so, and
    cannot detect the failure it was written for."""
    bad = []
    if not out.get("assertions"):
        bad.append("no outcome assertion — a workflow with influence above the lowest class must "
                   "declare at least one, monitored independently of the steps producing it")
    for item in out.get("assertions") or []:
        if item.get("reads_workflow_output"):
            bad.append(f'{item.get("statement", "")[:60]!r} reads the workflow\'s own output — it '
                       f'would be true whenever the workflow says it is, and cannot detect the '
                       f'failure it was written for')
        if not str(item.get("evaluated_against", "")).strip():
            bad.append("an assertion names no system of record to evaluate it against")
    return bad[:5]


def _covers_every_node(out: dict, context: Mapping[str, Any] | None, what: str) -> list[str]:
    """Every node of the workflow graph has exactly one entry, and no entry names a node the graph
    does not have.

    A partial set is the dangerous shape: it is valid, it derives cleanly, and every service
    downstream reasons about the steps it was given as if they were the workflow. Measured 15 Sep
    2026 — step 17 returned ONE vector for a ten-node graph and the whole control chain (exposure,
    obligations, composition) came back describing that one node, with max exposure 0. A run that
    fails here is recoverable; a control set that is quietly nine steps short looks exactly like a
    complete one.
    """
    graph = (context or {}).get("workflow_graph") or {}
    # A readiness EVIDENCE record carries `nodes` as a count, not a list; only a real graph can
    # hold an answer to anything.
    listed = graph.get("nodes") if isinstance(graph, Mapping) else None
    nodes = [str(n.get("id", "")).strip() for n in (listed if isinstance(listed, list) else [])
             if isinstance(n, Mapping)]
    if not nodes:
        return []                       # no graph in context: nothing to hold the answer to
    given = [str(s.get("id", "")).strip() for s in out.get("steps") or [] if isinstance(s, Mapping)]
    bad = []
    missing = [n for n in nodes if n not in given]
    if missing:
        bad.append(f"{what} for {missing} — the workflow graph has {len(nodes)} nodes and this "
                   f"answer covers {len(set(given) & set(nodes))}; every node gets exactly one, "
                   f"because everything downstream reads this set AS the workflow")
    phantom = sorted({g for g in given if g and g not in nodes})
    if phantom:
        bad.append(f"{phantom} are not nodes of the workflow graph — a step nobody decomposed "
                   f"cannot be reasoned about; use the node ids you were shown")
    duplicated = sorted({g for g in given if given.count(g) > 1})
    if duplicated:
        bad.append(f"{duplicated} appear more than once — one entry per node")
    return bad


def _determinism(out: dict, context: Mapping[str, Any] | None = None) -> list[str]:
    """Q1.1-Q1.5. The necessity test is asked ONCE per non-D0 step, and a step reducible by
    criteria 6-7 is re-tiered to D0 — the observed failure is over-classifying as
    non-deterministic, which buys an agent where a lookup table would do."""
    bad = []
    if not out.get("graph_is_explicit", True):
        bad.append("the graph is not explicit — that is D3 at orchestration level and a Board "
                   "escalation, which must be said rather than scored around")
    tiers = [s.get("tier") for s in out.get("steps") or []]
    if not tiers:
        bad.append("no step was classified")
    bad += _covers_every_node(out, context, "no determinism tier")
    for step in out.get("steps") or []:
        if step.get("tier") != "D0" and not step.get("necessity"):
            bad.append(f'step {step.get("id")!r} is above D0 with no necessity test — every '
                       f'non-D0 step is asked once whether it is irreducible')
        if step.get("necessity") == "by default" and step.get("reducible_to") != "D0":
            bad.append(f'step {step.get("id")!r} is non-deterministic BY DEFAULT, which means a '
                       f'rule exists and nobody wrote it down — it re-tiers to D0')
    aggregate = out.get("governance_tier")
    if tiers and aggregate and aggregate != max(tiers):
        bad.append(f"the governance tier is the MAXIMUM of the step tiers: {max(tiers)}, not "
                   f"{aggregate}")
    return bad[:5]


#: What the published guardrail predicates ask that a facet vector cannot answer — declared beside
#: the predicate parser, and compared against the corpus by a test, so a new guardrail's condition
#: becomes required the moment it is published rather than the next time somebody remembers this.


def _facet_vectors(out: dict, context: Mapping[str, Any] | None = None) -> list[str]:
    """Q2.4 and FR-22: every override carries a written justification, and exposure and influence
    are NOT decided here — they follow by a published derivation, and deciding them in an agent
    would make the derivation an opinion."""
    bad = []
    if not out.get("steps"):
        bad.append("no step was given a facet vector")
    bad += _covers_every_node(out, context, "no facet vector")
    for step in out.get("steps") or []:
        for override in step.get("overrides") or []:
            if len(str(override.get("justification", "")).strip()) < 10:
                bad.append(f'the override of {override.get("facet")!r} on step {step.get("id")!r} '
                           f'has no justification — an override without a reason is a default '
                           f'nobody checked')
        for forbidden in ("exposure", "influence"):
            if forbidden in step:
                bad.append(f"step {step.get('id')!r} sets {forbidden!r} — that is derived from "
                           f"these facets by a deterministic service, not decided here")
        # The prose conditions the guardrail predicates ask about. Every one, or the derivation
        # REFUSES — `predicates.Named` will not read an unanswered condition as false, because a
        # guardrail that silently fails to fire is the failure nobody can see. Answering them here
        # is not the same as choosing controls: these describe the step this agent is already
        # describing, and it never sees which guardrails they turn on.
        unanswered = sorted(set(NAMED_CONDITIONS) - set(step.get("conditions") or {}))
        if unanswered:
            # EVERY missing key, by name: the refusal is what the retry answers from, and a list
            # cut to three left the model unable to comply (13 Sep 2026).
            bad.append(f'step {step.get("id")!r} leaves these conditions unanswered — answer each '
                       f'with true or false, under exactly this key: {unanswered}')
    return bad


def _build_surface(out: dict, context: Mapping[str, Any] | None = None) -> list[str]:
    """FR-25 and FR-26. The incumbent question is asked FIRST and its failures recorded; an
    obligation the selected surface cannot enforce sends the design back to step 17, because a
    different runtime with the same gap is the same gap."""
    bad = []
    if not out.get("incumbent_considered"):
        bad.append("the incumbent-platform question was not asked — it is asked first, and an "
                   "incumbent that satisfies the obligations is usually the right answer")
    if out.get("incumbent") and not out.get("incumbent_failed_obligations") \
            and out.get("surface") != out.get("incumbent"):
        bad.append(f'the incumbent {out.get("incumbent")!r} was rejected without recording which '
                   f'obligations it failed — "we chose something else" is not a decision record')
    return bad


def _component_selection(out: dict, context: Mapping[str, Any] | None = None) -> list[str]:
    """FR-27 and FR-28, and G04 as a GATE: a component is admitted by its catalogue id, checked
    against the pinned catalogue this step was shown — a component named in prose costs nothing in
    the join and looks free. A tradeoff is RECORDED, never resolved by dropping a constraint — a
    constraint quietly dropped reappears as an incident."""
    bad = []
    if not out.get("selected"):
        bad.append("nothing was selected")
    known = {str(row.get("id", "")) for row in (context or {}).get("component_catalogue") or []
             if isinstance(row, Mapping) and row.get("id")}
    if context is not None and not known:
        bad.append("the component catalogue in context carries no ids — G04 cannot be checked, "
                   "and a selection nothing can join is not a selection")
    unknown = [str(c.get("component_id")) for c in out.get("selected") or []
               if str(c.get("component_id", "")) not in known]
    if unknown and known:
        bad.append(f"{unknown} are not ids in the component catalogue — a design admits components "
                   f"by catalogue identity (G04); use the `id` column, or declare a building block")
    for choice in out.get("selected") or []:
        if not choice.get("rejected_alternatives"):
            bad.append(f'{choice.get("capability")!r} names no rejected alternative — a selection '
                       f'with none is a preference written down, not a decision')
    for tradeoff in out.get("tradeoffs") or []:
        for field in ("compensating_control", "review_trigger"):
            if not str(tradeoff.get(field, "")).strip():
                bad.append(f'a tradeoff has no {field.replace("_", " ")} — that is a dropped '
                           f'constraint wearing a decision record')
    for block in out.get("building_blocks") or []:
        if not str(block.get("owner", "")).strip():
            bad.append(f'the building block {block.get("what")!r} has no named owner — an '
                       f'out-of-scope component nobody owns is an obligation nobody carries')
    return bad[:5]


def _families_realised(out: dict, context: Mapping[str, Any] | None = None) -> list[str]:
    """Step 21's SOFT rule: every family the composition (step 22, run first) requires is carried
    by a selected catalogue component, or is named under `unresolved`.

    Policy, stated so it can be changed in one place: a `building_block` does NOT realise a family.
    It is out of scope and owned by someone else, so a family met only there is a dependency the
    design still owes — which is exactly what `unresolved` is for. A catalogue with no `families`
    column makes no claim (the column is authored content, published separately), and a run with
    no composition has nothing to require: both are silent, never a refusal.
    """
    ctx = context or {}
    required = as_list(((ctx.get("model_summary") or {}).get("required_families")))
    derived = ctx.get("component_families") or {}
    families_of = {str(k): as_list(v) for k, v in (derived.get("by_component") or {}).items()}
    # A catalogue column, if a tenant ever publishes one, is believed over the derivation.
    families_of |= {str(row.get("id")): as_list(row.get("families"))
                    for row in ctx.get("component_catalogue") or []
                    if isinstance(row, Mapping) and row.get("id") and row.get("families")}
    # What the corpus is SILENT about is not something this design failed to do.
    required = [f for f in required if f not in set(as_list(derived.get("unclaimed")))]
    if not required or not any(families_of.values()):
        return []
    selected = [str(c.get("component_id", "")) for c in out.get("selected") or []]
    realised = {f for cid in selected for f in families_of.get(cid, ())}
    named = " ".join(str(u) for u in out.get("unresolved") or [])
    return [f"family {f} is required by the composition and no selected component carries it"
            for f in required if f not in realised and f not in named]


FAMILY_REMEDY = ("select a catalogue component whose `families` include it, or name it under "
                 "`unresolved` as something the design still owes")

#: The CAFÉ zones that RUN the use case, as opposed to the cross-cutting ones that govern it
#: (`ident`, `obs`, `plat`). A selection drawn entirely from the cross-cutting zones is a control
#: plane with nothing inside it — measured run 5, 15 Sep 2026: sixteen components, every one of them
#: identity, observability, platform or gateway, and a solution view that was a parts list.
DELIVERY_ZONES = ("exp", "cog", "knw", "mod", "too", "data", "ext")
DELIVERY_REMEDY = ("select the components that DO the work as well as the ones that govern it — the "
                   "runtime or orchestrator, the model, the knowledge or grounding store, the tools "
                   "it calls, the data it reads — or name under `unresolved` why this design needs "
                   "none of them")


def _does_the_work(out: dict, context: Mapping[str, Any] | None = None) -> list[str]:
    """Step 21's second SOFT rule: something in the selection runs the use case.

    Zones are the catalogue's own column, so this asks nothing the corpus does not already say. A
    catalogue with no zone column makes no claim, exactly as the family rule does.
    """
    ctx = context or {}
    zone_of = {str(r.get("id")): str(r.get("zone") or "") for r in ctx.get("component_catalogue") or []
               if isinstance(r, Mapping) and r.get("id")}
    if not any(zone_of.values()):
        return []
    chosen = {str(c.get("component_id", "")) for c in out.get("selected") or []}
    zones = {zone_of.get(cid, "") for cid in chosen} - {""}
    if not zones or zones & set(DELIVERY_ZONES):
        return []
    named = " ".join(str(u) for u in out.get("unresolved") or []).lower()
    if "zone" in named or "runtime" in named or "model" in named:
        return []
    return [f"every selected component sits in a cross-cutting zone ({sorted(zones)}) — this is a "
            f"control plane with nothing inside it, and the solution view drawn from it is a parts "
            f"list; nothing here runs the use case"]

#: The deterministic steps' numbers — they have no `Step` (a governed derivation's, not an agent's)
#: but they are named by number wherever a person reads a run. ONE home, beside the agent steps'.
DERIVED_STEP_NUMBERS = {"risk": "18", "obligations": "19", "composition": "22", "cost": "23",
                        "benefit": "24"}


def _obligations_bound(out: dict, context: Mapping[str, Any] | None = None) -> list[str]:
    """Step 21's SOFT rule for composition move 5: every obligation enforced by something SELECTED.

    M4 is explicit that this is the Stage 5 exit gate — "selection is not complete until every
    obligation resolves to a named enforcement point on a selected component". Its sibling
    `_families_realised` checks a weaker thing: that a family is present. A family is a shape, so an
    obligation can be covered by a family and still have nothing in the deployment enforcing it.

    An obligation the CORPUS cannot bind is not reported. `enforcement.bind` separates the two, and
    only `unbound` — the corpus can enforce this, the design chose nothing that does — is the
    architect's to answer. Reporting `unenforceable` would charge them for a gap in the framework.
    """
    ctx = context or {}
    points = ctx.get("enforcement_points")
    if not points:
        return []                      # `_compose` defers by name; not this rule's to re-report
    binding = enforcement.bind(
        as_list((ctx.get("obligations") or {}).get("guardrails")), candidates=points,
        selected=[str(c.get("component_id", "")) for c in out.get("selected") or []])
    # Whole ids, never containment: `"G09" in text` is also true of "G09-annex" or "G090", and this
    # is the only rule that would have surfaced G09, so a near-miss silently deletes the finding.
    #
    # What this still cannot do is tell a note that OWNS an obligation from one that merely cites it
    # — free text carries no such distinction. The structured answer is `enforcement.bind`'s
    # `advisory` argument, which takes exactly this list and refuses to launder an obligation the
    # corpus cannot bind; wiring it needs `unresolved` to name the obligation it answers, which is a
    # schema change and is deliberately not made here.
    named = set(re.findall(r"\bG\d+\b", " ".join(str(u) for u in out.get("unresolved") or [])))
    return [f"obligation {g} is required and no selected component enforces it — "
            f"{', '.join(points.get(g) or ()) or 'nothing catalogued does'} would"
            for g in binding.unbound if g not in named]


OBLIGATION_REMEDY = ("select the component that enforces it — the finding names which ones would — "
                     "or name it under `unresolved` as a control the design still owes")


def _soft_21(out: dict, context: Mapping[str, Any] | None = None) -> list[str]:
    """Step 21's soft findings: what the composition requires that nothing carries, whether every
    obligation is enforced by something selected, and whether anything selected actually runs the
    use case. All three are things the design OWES a reviewer, not reasons to lose the run —
    recorded under `unresolved` after one corrective attempt."""
    return (_families_realised(out, context) + _obligations_bound(out, context)
            + _does_the_work(out, context))


SOFT_21_REMEDY = f"{FAMILY_REMEDY}; {OBLIGATION_REMEDY}; and {DELIVERY_REMEDY}"


# ---------------------------------------------------------------- the registry

#: Steps 3-11 — the pre-work exercises, run by the SCREENING process before the criticality gate.
#: The eight sections a business case has. Named here rather than counted, so a case missing
#: "Risks and mitigations" fails on the name a person can go and write.
BUSINESS_CASE_SECTIONS = ("executive summary", "current state", "proposed solution",
                          "value drivers", "financial summary", "roadmap",
                          "risks and mitigations", "approvals and recommendation")


def _delivery_artifacts(out: dict, context: Mapping[str, Any] | None = None) -> list[str]:
    """Step 25. Four artifacts, and each rule below is the field its own schema calls the one worth
    keeping — which is exactly the field a model under length pressure drops first."""
    bad = []
    written = {str(s.get("section", "")).strip().lower() for s in out.get("business_case") or []}
    missing = [s for s in BUSINESS_CASE_SECTIONS if s not in written]
    if missing:
        bad.append(f"the business case is missing {missing} — an approver reading seven of eight "
                   f"sections cannot tell which one is absent")
    for record in out.get("decision_records") or []:
        if len(record.get("options") or []) < 2:
            bad.append(f'the decision record for {record.get("decision")!r} considered fewer than '
                       f'two options, which is a preference and not a decision')
        if not str(record.get("sacrificed", "")).strip():
            bad.append(f'the decision record for {record.get("decision")!r} names nothing that was '
                       f'sacrificed — the field that makes the record worth keeping')
    for contract in out.get("service_contracts") or []:
        if not str(contract.get("service_level_source", "")).strip():
            bad.append(f'the service level for {contract.get("name")!r} names no source; a service '
                       f'level is DERIVED from the business one, never invented, and an invented '
                       f'latency target is a promise somebody will be held to')
    unowned = [w.get("key") for w in out.get("work_items") or []
               if not str(w.get("owner", "")).strip()]
    if unowned:
        bad.append(f"work items {unowned} name no owner — a task nobody has agreed to do")
    return bad[:5]


def _cost_inputs(out: dict, context: Mapping[str, Any] | None = None) -> list[str]:
    """Sub-step 23.5. The run cost is a join the service does; what an agent contributes is the
    build cost with its provenance, and a build cost never arrives without one."""
    bad = []
    if out.get("build_amount") and not out.get("build_provenance"):
        bad.append("a build cost was given with no provenance — an approver reads a vendor quote "
                   "as a number somebody will be held to, and an estimate is not one")
    if out.get("build_provenance") and not out.get("build_amount"):
        bad.append("a build provenance was given with no amount — the provenance describes a "
                   "figure, and there is none")
    return bad[:5]


def _benefit_inputs(out: dict, context: Mapping[str, Any] | None = None) -> list[str]:
    """Sub-steps 24.1-24.4. The one rule worth the gate: an absent driver is DECLARED, never
    silently omitted and never filled with a default that looks like evidence."""
    bad = []
    for row in out.get("effort") or []:
        if not str(row.get("source", "")).strip():
            bad.append(f'the effort figures for {row.get("role")!r} carry no source — a headcount '
                       f'somebody will act on and nobody can check')
        if _number(row.get("expected_minutes")) > _number(row.get("current_minutes")):
            bad.append(f'{row.get("role")!r} is expected to take LONGER after the change, which is '
                       f'a cost and not a benefit; state it as such or correct the figures')
    baseline = out.get("quality_baseline") or {}
    if baseline and not str(baseline.get("source", "")).strip():
        bad.append("the quality baseline carries no source")
    if not (out.get("effort") or []) and not baseline and not (out.get("unsupplied") or []):
        bad.append("no driver has inputs and nothing is declared unsupplied — a case with no "
                   "evidence either way is not the same as a case worth nothing, and only one of "
                   "them should reach a funding decision")
    return bad[:5]


def _number(value) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _capability_query(out: dict, context: Mapping[str, Any] | None = None) -> list[str]:
    """One translation per function, and nothing invented.

    The register is the whole point: an `ability` that is the function's own words rearranged has
    translated nothing, and searching with it finds what searching with the function found.
    """
    bad = []
    queries = out.get("queries") or []
    functions = {str(b.get("name", "")).strip().lower()
                 for b in ((context or {}).get("elements") or {}).get("behavioural") or []
                 if isinstance(b, Mapping)}
    named = {str(q.get("function", "")).strip().lower() for q in queries}
    missing = sorted(functions - named)
    if functions and missing:
        bad.append(f"no ability written for {missing} — every function is translated, or the search "
                   f"that follows cannot find what it never asked for")
    invented = sorted(named - functions)
    if functions and invented:
        bad.append(f"{invented} are not functions from the inventory — translate what the use case "
                   f"does, not what it might")
    for q in queries:
        ability = str(q.get("ability", "")).strip()
        if ability.lower() == str(q.get("function", "")).strip().lower():
            bad.append(f"{ability!r} repeats the function verbatim — that is not a translation, and "
                       f"it will search for exactly what the function's own words already failed on")
    return bad[:5]


#: NOT a screening step: a sub-stage of step 5 that the `translate` matcher runs before it searches.
#: It has a prompt and a schema like any other exercise, so it is gated like any other exercise.
CAPABILITY_QUERY = Step("5q", "capability_query", "Business Architect", _capability_query, title="translate the functions")


SCREENING_STEPS: tuple[Step, ...] = (
    Step("3", "frame", "Business Analyst", _frame, title="frame use case"),
    Step("4", "elements", "Business Architect", _elements, title="decompose elements"),
    Step("5", "coverage_map", "Business Architect", _coverage_map, title="match capabilities"),
    Step("6", "realisation_match", "Application Architect", _realisation_match, title="match realisations"),
    Step("7", "criticality_band", "Risk Officer", _criticality_band, title="assign criticality band"),
    Step("8", "quality_attributes", "Product Owner", _quality_attributes, title="derive quality attributes"),
    Step("9", "ontology_delta", "Data Architect", _ontology_delta, title="check ontology"),
    Step("10", "workflow_graph", "Business Analyst", _workflow_graph, title="sequence workflow"),
    Step("11", "source_contracts", "Data Architect", _source_contracts, title="contract sources"),
)

#: Steps 13-21 — the interpretive half of the DESIGN process. 14, 16, 18, 19 and 22 are absent
#: because they are deterministic: they are `decision-mcp`'s, not an agent's, and putting one here
#: would be a second implementation of a published rule.
DESIGN_STEPS: tuple[Step, ...] = (
    Step("13", "assertions", "Product Owner", _assertions, title="write assertions"),
    Step("15", "determinism", "Solution Architect", _determinism, title="decide determinism"),
    Step("17", "facet_vectors", "Risk Officer", _facet_vectors, title="score risk facets", normalise=_normalise_facets),
    Step("20", "build_surface", "Technology Architect", _build_surface, title="shape build surface"),
    Step("21", "component_selection", "Solution Architect", _component_selection, title="select components",
         soft=_soft_21, soft_remedy=SOFT_21_REMEDY),
    Step("23", "cost_inputs", "Cost Engineer", _cost_inputs, title="gather cost inputs"),
    Step("24", "benefit_inputs", "Value Analyst", _benefit_inputs, title="gather benefit inputs"),
    Step("25", "delivery_artifacts", "Product Owner", _delivery_artifacts, title="plan delivery artifacts"),
)

STEPS: tuple[Step, ...] = SCREENING_STEPS + DESIGN_STEPS


#: step key -> the number a person reads it by, agent steps and derived steps together. Lives here
#: because it is the steps' own fact; it was previously a private table in the throwaway model-trace
#: module, which is no home for something the design half now reads to decide a verdict.
NUMBER_OF: dict[str, str] = {s.key: s.number for s in STEPS} | DERIVED_STEP_NUMBERS


def step_for(number: str) -> Step:
    for step in STEPS:
        if step.number == number:
            return step
    raise KeyError(f"no step {number!r}; have {[s.number for s in STEPS]}")
