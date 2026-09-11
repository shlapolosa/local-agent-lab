"""The deterministic gate every use-case agent's output passes through.

CLAUDE.md's rule: agents emit schema-validated JSON and a deterministic `[D]` step gates it before
the next agent sees it. Agents never call each other; the workflow mediates through a typed
contract, and this is the contract's enforcement.

Three checks, in this order, because the order decides whether a retry can act on the answer:

1. **Shape** — the near-misses a model reliably makes, repaired in place. Only where the canonical
   field is ABSENT, so a model that got it right is never overwritten. A whole screening run is not
   worth discarding over a synonym.
2. **Schema** — jsonschema, reporting at most five errors. More than five and a retry is being
   asked to fix a different answer rather than this one.
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
from lab.workloads import gateway

__all__ = ["GateFailed", "gate", "json_of", "run_gated", "validator_for"]

#: Enough for a retry to act on. Beyond it, the answer is wrong in kind rather than in detail.
MAX_REPORTED = 5


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
    return [f'{"/".join(str(p) for p in e.path) or "(root)"}: {e.message}'
            for e in list(validator.iter_errors(obj))[:MAX_REPORTED]]


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


async def run_gated(agent, message: str, *, step: str, validator: Draft202012Validator,
                    normalise: Callable[[dict], None] | None = None,
                    complete: Callable[[dict], list[str]] | None = None) -> dict:
    """Run the agent, gate it, and give it exactly one corrective attempt.

    The retry re-sends the ORIGINAL message with the problems appended, because the client is
    stateless: a follow-up carrying only "you missed X" would arrive with no X to fix. A second
    failure raises — negotiating with a model that has already been told what is wrong produces
    plausible output rather than correct output, which is worse.
    """
    reply = await gateway.survive_restart(lambda: agent.run(message))
    out = json_of(reply)
    problems = gate(out, validator=validator, normalise=normalise, complete=complete)
    if not problems:
        return out

    corrective = (f"{message}\n\n## Your previous answer was rejected\n\n"
                  + "\n".join(f"- {p}" for p in problems)
                  + "\n\nReturn the WHOLE answer again, corrected. Do not return only the parts "
                    "that changed, and do not explain — the reply is parsed as JSON.")
    out = json_of(await gateway.survive_restart(lambda: agent.run(corrective)))
    problems = gate(out, validator=validator, normalise=normalise, complete=complete)
    if problems:
        raise GateFailed(step, problems)
    return out
