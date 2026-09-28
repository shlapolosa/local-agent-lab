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

from lab.platform import config
from lab.workloads.usecase.steps import Step, schema

__all__ = ["CONTEXT_FOR", "EXCLUDED_FROM", "OPTIONAL_CONTEXT", "build_all", "context_for", "instructions",
           "make_agent", "message"]

#: What each step is given. A step reads what its exercise needs and nothing else — a context that
#: carried everything would make every prompt a search problem and every wrong answer unattributable.
CONTEXT_FOR: dict[str, tuple[str, ...]] = {
    # Since the CAFÉ workbook (28 Sep 2026) is the source of truth for which step reads which
    # artifact, each corpus below is the one its index places at that step. Step 3 frames the use
    # case in ENTERPRISE-architecture terms — the business L3s it serves — and step 4 decomposes it
    # against the ontology's concepts, so an element is named in the enterprise's own vocabulary.
    "frame": ("submission", "business_capabilities"),
    "elements": ("frame", "ontology"),
    # The technology map is the match; the business L3s step 3 chose, with the technology the
    # corpus says serves each, are its "business context" (E0.3's own inputs).
    "coverage_map": ("elements", "capabilities", "business_context", "landscape"),
    # The translation before the search: the functions, and a SAMPLE of the map so the abilities
    # are written in its register rather than in the submission's.
    "capability_query": ("elements", "register"),
    # The realisation view for exactly what step 5 matched, and the estate as it stands (AI and
    # traditional as-is) — step 6 shortlists; selection is step 21's.
    "realisation_match": ("elements", "coverage_map", "realisations", "landscape"),
    "criticality_band": ("frame", "criticality_taxonomy"),
    "quality_attributes": ("coverage_map", "service_levels", "quality_patterns"),
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
    # Step 21 reads the MODEL the run has grown so far — as `model_summary`, names by type plus the
    # families the composition (22, run first) requires and which are realised — never the whole
    # spec, which would put every element's properties into a prompt an architect skims.
    "component_selection": ("obligations", "quality_attributes", "realisation_match",
                            "ai_capability_map", "component_catalogue", "build_surface",
                            "model_summary",
                            # WHICH technology capabilities this use case needs — step 5's own
                            # output, now that it matches the technology map. Its `capability_id`
                            # is the map's natural key, so selection starts from the capabilities
                            # the functions actually demanded rather than from the whole catalogue.
                            "coverage_map",
                            # What each catalogue component could ENFORCE, so an obligation is
                            # carried by a deliberate choice rather than caught by the gate after.
                            "enforcement_points",
                            # What each catalogue component would SATISFY of this design's required
                            # families, derived from the published chain — the information the
                            # selection is then held to.
                            "component_families"),
    # The valuation half. The run cost is a JOIN the governed service does on step 21's component
    # ids; the cost engineer reads what intake captured about the BUILD and what the design needs
    # beyond the catalogue. The value analyst reads the submission the figures have to come from
    # and never the cost, because a benefit sized to clear a known investment is not evidence.
    "cost_inputs": ("intake", "component_selection", "composition", "delivery_rates"),
    "benefit_inputs": ("frame", "workflow_graph", "quality_attributes", "criticality"),
    # Step 25 is the only step that reads nearly everything, and legitimately: it is not deciding
    # anything, it is writing down what was already decided. The one thing it must NOT invent is a
    # service level, so it gets the quality attributes the levels have to be derived from.
    "delivery_artifacts": ("frame", "composition", "obligations", "cost", "benefit",
                           "component_selection", "quality_attributes", "criticality",
                           "model_summary"),
}

#: CR-19, as data rather than a convention. Step 12 confirms the criticality class and must never
#: see step 7's provisional band; an anchored confirmation agrees with the guess and looks exactly
#: like an independent one.
EXCLUDED_FROM: dict[str, tuple[str, ...]] = {
    "confirm_criticality": ("criticality_band",),
}


#: Inputs that ENRICH a step without being a precondition of it: handed over when present, named
#: in `corpora_unavailable` when absent, never a reason to defer. Everything else in `CONTEXT_FOR`
#: is a hard input — a step asked without it would answer from nothing. The distinction arrived with
#: the CAFÉ workbook (28 Sep 2026), which placed governed corpora at steps that had always run
#: without them — the ontology at step 4, the backbone every later step reads, is published by
#: REFERENCE from a private master, and one upload nobody made must not stall every run there.
OPTIONAL_CONTEXT: dict[str, frozenset[str]] = {
    # The business map is PINNED STRICTLY (public; readiness gate A rests on it — recommendation 2),
    # so an unpublished map fails the run at the pin. What is left is a transient READ failure, and
    # for that step 3 must still frame the problem and the owner from the submission: a hard input
    # here stalled every step after it on a corpus outage. Its absence stays visible — no
    # `business_capabilities_served` on the record, and the corpus named as unavailable.
    "frame": frozenset({"business_capabilities"}),
    "elements": frozenset({"ontology"}),
    # The estate tells step 5 whether a capability already EXISTS (consumed / updated) or not.
    "coverage_map": frozenset({"business_context", "landscape"}),
    "realisation_match": frozenset({"coverage_map", "realisations"}),
    "criticality_band": frozenset({"criticality_taxonomy"}),
    "quality_attributes": frozenset({"quality_patterns"}),
    "cost_inputs": frozenset({"delivery_rates"}),
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
               timeout: float = 300.0, max_tokens: int = 32000,
               temperature: float = 0.0, seed: int | None = None) -> Agent:
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
    # Asked the same way every time. Nothing set `temperature` anywhere in this codebase, so every
    # agent ran at the provider's default — and a setting that must be remembered per call site is
    # one that gets missed, so the deterministic ask is the DEFAULT here.
    #
    # It is NOT reproducibility, and the first version of this comment claimed it was. Measured on
    # a SHORT prompt (20 Sep 2026), `gpt-5.4-mini` and `gpt-4.1` at temperature=0 with a seed came
    # back byte-identical, and that was written down as "this makes a non-reasoning model exactly
    # reproducible". Re-measured the same day on what step 5 ACTUALLY sends — 74 candidates with
    # definitions, ~22 KB, a long structured answer — both `gpt-5.4-mini` and `gpt-5.4-mini-think`
    # returned THREE DISTINCT answers out of three. The seed narrows nothing that survives a
    # payload of this size.
    #
    # So the deterministic ask stays, because asking the same way every time costs nothing and is
    # a precondition for anything else — but consistency at step 5 has to be bought by SAMPLING and
    # a vote, not by decoding options. The lesson is the cheaper one: a spike measures the prompt
    # it was given, and step 5's prompt is not a sentence.
    return Agent(client=client, name=f"usecase-{step.key}", instructions=instructions(step),
                 default_options=ChatOptions(store=store, max_tokens=max_tokens,
                                             temperature=temperature,
                                             seed=config.AGENT_SEED if seed is None else seed))


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
