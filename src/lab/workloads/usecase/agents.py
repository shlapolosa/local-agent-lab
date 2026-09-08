"""The use-case agents: one factory per bounded context, and the context each one is allowed.

Ten services grouped by the DOMAIN they reason about, not the verb they perform. Grouping by verb
would have produced a matching service and a drafting service, each reasoning across four unrelated
corpora; grouping by domain gives each one vocabulary, one corpus and one owning role — which is
what makes a prompt writable and a wrong answer attributable.

**CR-19 lives here.** "The provisional criticality band from step 7 is excluded from the context of
step 12." Enforced at context assembly, which is the only place it can be: step 7 produces a band
for the feasibility verdict and step 12 derives the confirmed class INDEPENDENTLY, and if the
confirmation can see the guess it will tend to agree with it. This is the only anchoring risk left
in the process after the coarse determinism estimate was removed, and it is invisible when it fails
— the class simply comes back the same and nobody can tell whether that was agreement or an echo.

Every setting is an argument. The composition root reads configuration; nothing here does.
"""
from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from agent_framework import Agent, ChatOptions
from agent_framework.openai import OpenAIChatClient
from openai import AsyncOpenAI

from lab.workloads.usecase.steps import Step, schema

__all__ = ["CONTEXT_FOR", "EXCLUDED_FROM", "build_all", "context_for", "instructions",
           "make_agent", "message"]

#: What each step is given. A step reads what its exercise needs and nothing else — a context that
#: carried everything would make every prompt a search problem and every wrong answer unattributable.
CONTEXT_FOR: dict[str, tuple[str, ...]] = {
    "frame": ("submission",),
    "elements": ("frame",),
    "coverage_map": ("elements", "capabilities"),
    "realisation_match": ("elements", "landscape"),
    "criticality_band": ("frame",),
    "quality_attributes": ("coverage_map", "service_levels"),
    "ontology_delta": ("elements", "ontology"),
    "workflow_graph": ("elements", "coverage_map", "ontology_delta"),
    "source_contracts": ("workflow_graph", "source_classification"),
    # The design half. Note what step 17 does NOT read: the control requirement set it will
    # eventually shape. Facets are assigned from the step's own nature, and letting it see the
    # obligations would let it assign the vector that produces the controls it prefers.
    "assertions": ("workflow_graph", "criticality"),
    "determinism": ("workflow_graph", "determinism_criteria"),
    "facet_vectors": ("workflow_graph", "determinism", "facet_schema"),
    "build_surface": ("obligations", "realisation_match", "surface_enforceability"),
    "component_selection": ("obligations", "quality_attributes", "realisation_match",
                            "ai_capability_map", "build_surface"),
}

#: CR-19, as data rather than a convention. Step 12 confirms the criticality class and must never
#: see step 7's provisional band; an anchored confirmation agrees with the guess and looks exactly
#: like an independent one.
EXCLUDED_FROM: dict[str, tuple[str, ...]] = {
    "confirm_criticality": ("criticality_band",),
}


def context_for(step_key: str, available: Mapping[str, Any]) -> dict:
    """Exactly what this step may read, minus anything CR-19 excludes from it.

    The exclusion is applied AFTER selection rather than relying on the selection to omit it, so a
    later widening of `CONTEXT_FOR` cannot silently reintroduce the anchor."""
    wanted = CONTEXT_FOR.get(step_key, ())
    excluded = set(EXCLUDED_FROM.get(step_key, ()))
    return {k: available[k] for k in wanted if k in available and k not in excluded}


def instructions(step: Step) -> str:
    """The step's prompt, with the schema it must satisfy appended.

    The schema goes in the SYSTEM prompt rather than being described in prose: the gate validates
    against this exact document, so a model that has read it is being asked for the thing that will
    be checked rather than a description of it."""
    return (f"{step.prompt()}\n\n## The schema your answer is validated against\n\n"
            f"```json\n{json.dumps(schema(step.key), indent=2)}\n```\n")


def make_agent(step: Step, *, credential: str, gateway_url: str, model: str,
               headers: Mapping[str, str] | None = None, store: bool = False,
               timeout: float = 300.0, max_tokens: int = 32000) -> Agent:
    """One agent for one step.

    `base_url` is the GATEWAY's `/v1/` and the key is this workload's own credential, so spend
    attributes per identity and every call is metered, traced and PII-guarded like any other.
    `store=False` forces the stateless turn: the gateway's upstream implements only the
    non-stateful `/v1/responses`, and the retry in `gates.run_gated` re-sends full content because
    of it.
    """
    http = AsyncOpenAI(base_url=gateway_url.rstrip("/") + "/v1/", api_key=credential,
                       default_headers=dict(headers or {}), timeout=timeout, max_retries=3)
    client = OpenAIChatClient(model=model, api_key=credential, async_client=http)
    return Agent(client=client, name=f"usecase-{step.key}", instructions=instructions(step),
                 default_options=ChatOptions(store=store, max_tokens=max_tokens))


def message(step: Step, context: Mapping[str, Any]) -> str:
    """What the agent is asked, this run.

    JSON rather than prose: every value here was produced by an earlier step against a schema, and
    re-narrating it would invite the model to reinterpret what a gate already accepted."""
    parts = [f"## {name}\n\n```json\n{json.dumps(value, indent=2, ensure_ascii=False)}\n```"
             if not isinstance(value, str) else f"## {name}\n\n{value}"
             for name, value in context.items()]
    return (f"# Step {step.number} — {step.service}\n\n" + "\n\n".join(parts)
            + "\n\nAnswer for THIS use case only, as one JSON object.")


def build_all(steps: Sequence[Step], *, credential_for, gateway_url: str, model: str,
              headers: Mapping[str, str] | None = None, **options) -> dict[str, Agent]:
    """One agent per STEP, each authenticated as the SERVICE that owns it.

    Nine steps, six services: steps 3 and 10 are both the Business Analyst, 4 and 5 both the
    Business Architect, 9 and 11 both the Data Architect. They are separate agents because each has
    its own prompt and its own schema — a single agent asked to do two exercises is asked to hold
    two vocabularies — but they authenticate as ONE identity, because the bounded context is what
    owns a corpus and answers for an answer.

    `credential_for(service)` is the seam that makes ten identities a configuration change: today
    it returns the same workload credential for every service, and when the per-agent Entra
    registrations land it returns theirs. Nothing here changes.
    """
    return {step.key: make_agent(step, credential=credential_for(step.service),
                                 gateway_url=gateway_url, model=model, headers=headers, **options)
            for step in steps}
