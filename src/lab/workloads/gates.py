"""The agent loop around the deterministic gate: run, gate, one corrective retry.

The gate itself is domain and lives in `lab.core.validation`; this module only runs the model, which is
orchestration.
"""
from __future__ import annotations

from typing import Callable

from jsonschema import Draft202012Validator

from lab.core.validation import GateFailed, gate, json_of
from lab.workloads import gateway

__all__ = ["run_gated"]


async def run_gated(agent, message: str, *, step: str, validator: Draft202012Validator,
                    normalise: Callable[[dict], None] | None = None,
                    complete: Callable[[dict], list[str]] | None = None,
                    soft: Callable[[dict], list[str]] | None = None,
                    soft_key: str = "unresolved", soft_remedy: str = "") -> dict:
    """Run the agent, gate it, and give it exactly one corrective attempt.

    The retry re-sends the ORIGINAL message with the problems appended, because the client is
    stateless: a follow-up carrying only "you missed X" would arrive with no X to fix. A second
    failure raises — negotiating with a model that has already been told what is wrong produces
    plausible output rather than correct output, which is worse.

    A SOFT rule is asked for on the retry like any other, but a second shortfall is RECORDED on the
    answer under `soft_key` rather than raised: it names something the design still owes (a
    required family no selected component carries) — a finding a reviewer must see, not a reason
    to lose the twenty minutes of work around it. A soft rule runs only over an answer the hard
    gate accepted, so it never reasons about an answer of the wrong shape. The retry hears the
    finding WITH its `soft_remedy`; the answer carries the finding alone — a record is read by a
    person, and "select a component" is an instruction to a model, not a design decision.
    """
    reply = await gateway.survive_restart(lambda: agent.run(message))
    out = json_of(reply)
    problems = gate(out, validator=validator, normalise=normalise, complete=complete)
    owed = list(soft(out)) if soft and not problems else []
    if not problems and not owed:
        return out

    told = problems + [f"{p} — {soft_remedy}" if soft_remedy else p for p in owed]
    corrective = (f"{message}\n\n## Your previous answer was rejected\n\n"
                  + "\n".join(f"- {p}" for p in told)
                  + "\n\nReturn the WHOLE answer again, corrected. Do not return only the parts "
                    "that changed, and do not explain — the reply is parsed as JSON.")
    out = json_of(await gateway.survive_restart(lambda: agent.run(corrective)))
    problems = gate(out, validator=validator, normalise=normalise, complete=complete)
    if problems:
        raise GateFailed(step, problems)
    owed = list(soft(out)) if soft else []
    if owed:
        out[soft_key] = list(out.get(soft_key) or []) + owed
    return out
