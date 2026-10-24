"""The deterministic gate every agent's output passes through — the PURE half (shape, schema, completeness).

The agent loop that calls it, with its one retry, is `lab.workloads.gates.run_gated`: running a model is
orchestration; deciding whether its answer meets the contract is domain.


CLAUDE.md's rule: agents emit schema-validated JSON and a deterministic `[D]` step gates it before
the next agent sees it. Agents never call each other; the workflow mediates through a typed
contract, and this is the contract's enforcement.

Three checks, in this order, because the order decides whether a retry can act on the answer:

1. **Shape** — the near-misses a model reliably makes, repaired in place. Only where the canonical
   field is ABSENT, so a model that got it right is never overwritten. A whole screening run is not
   worth discarding over a synonym.
2. **Schema** — jsonschema, reporting up to `MAX_REPORTED` problems, one line each: a retry answers
   from the refusal, so the refusal carries the whole list.
3. **Completeness** — what a schema cannot see. An empty `elements` list is valid JSON and a
   useless decomposition; a capability match that invented a capability is valid JSON and a
   fabrication. These are the checks that matter and they are per-agent.

**One retry, and it re-sends the full content.** The client is stateless (`store=False`), so a
follow-up carrying only the complaint would arrive with no idea what it was complaining about. The
retry says what was wrong and asks again — it does not negotiate, and a second failure raises.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Sequence

from jsonschema import Draft202012Validator

__all__ = ["MAX_REPORTED", "GateFailed", "gate", "json_of", "schema_errors", "validator_for"]

#: How many schema problems a retry is told about. Five was a prose courtesy; it left a model unable
#: to comply when a schema requires N keys on each of M steps (facet vectors: nine conditions on
#: every workflow step — 13 Sep 2026, a 4×10 shortfall reported as 5 lines, refused twice). A retry
#: answers from the refusal, so the refusal carries the whole list; the messages are one line each.
MAX_REPORTED = 60


class GateFailed(ValueError):
    """The agent's output did not meet its contract, twice. The run stops rather than passing it on.

    Named problems, not a diff: the next agent would have consumed this, and "the decomposition was
    empty" is what an architect needs at review, not a JSON pointer.
    """

    def __init__(self, step: str, problems: Sequence[str]) -> None:
        self.step, self.problems = step, list(problems)
        super().__init__(f"step {step}: " + "; ".join(self.problems))


def validator_for(schema: dict) -> Draft202012Validator:
    return Draft202012Validator(schema)


def json_of(reply: Any) -> dict:
    """An agent's reply as an object.

    Models fence JSON in markdown often enough that stripping it here is worth more than a prompt
    line asking them not to — and a reply that is not JSON at all still fails, loudly."""
    text = reply if isinstance(reply, str) else getattr(reply, "text", None) or str(reply)
    body = text.strip()
    if body.startswith("```"):
        body = body.split("```")[1] if "```" in body[3:] else body[3:]
        body = body.removeprefix("json").strip()
    try:
        parsed = json.loads(body)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def schema_errors(validator: Draft202012Validator, obj: Any) -> list[str]:
    if not isinstance(obj, dict) or not obj:
        return ["the reply was not a JSON object"]
    return [f'{"/".join(str(p) for p in e.path) or "(root)"}: {_explain(validator.schema, e)}'
            for e in list(validator.iter_errors(obj))[:MAX_REPORTED]]


def _explain(schema: dict, error) -> str:
    """The validator's message — and, for a value that is ALLOWED in a sibling field, which field.

    "'internal group' is not one of [...]" names what is permitted, not what went wrong: the value
    was an audience written into blast_radius (wfr-47625c3ebdd5, 30 Sep 2026), and a retry told only
    the list made the same swap again. The sibling is found through the error's own schema path, so
    the rule is general and names no field."""
    path = list(error.schema_path)
    if error.validator != "enum" or len(path) < 3 or path[-3] != "properties":
        return error.message
    siblings: Any = schema
    try:
        for part in path[:-2]:
            siblings = siblings[part]
    except (KeyError, IndexError, TypeError):
        return error.message
    field = path[-2]
    owners = [name for name, spec in siblings.items()
              if name != field and isinstance(spec, dict) and error.instance in (spec.get("enum") or ())]
    if not owners:
        return error.message
    return (f"{error.instance!r} is an `{owners[0]}` value, not a {field} one — "
            f"{field} takes one of {list(error.validator_value)}")


def gate(obj: dict, *, validator: Draft202012Validator,
         normalise: Callable[[dict], None] | None = None,
         complete: Callable[[dict], list[str]] | None = None) -> list[str]:
    """Every problem with this output, in the order a retry should hear them. Empty means it passes."""
    if normalise and isinstance(obj, dict):
        normalise(obj)
    problems = schema_errors(validator, obj)
    if problems:
        return problems
    return list(complete(obj)) if complete else []
