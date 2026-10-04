"""The USE-CASE INTAKE feature's (the CAFÉ derivations, the four processes, their agents) slice of the contract. Re-exported by `lab.platform.contracts` for the callers that
predate the split; a NEW name here is imported from this module directly.

Imported by the package `__init__` AFTER the kernel types it builds on are defined — so import it only
through `lab.platform.contracts` (Python runs that `__init__` first either way).
"""
from __future__ import annotations

from lab.platform import config
from lab.platform.contracts import AgentSpec, Column, InputField, InputKind, ProcessSpec, ToolCatalogue


class DecisionTools(ToolCatalogue):
    """decision-mcp — the CAFÉ derivations that are DETERMINISTIC, as governed tools.

    They are deployed rather than run inside the workload for the reason the framework gives: they
    read governed artifacts that change under governance approval, so a change to the criticality
    taxonomy or the guardrail set must not require an application release. Conformance review
    evaluates the same predicates against the same facet vectors, so one service also stops two
    implementations of one rule set drifting apart.

    All read-only derivations. No READ/WRITE split, because there is nothing here to split.
    """
    SERVER = "decision_mcp"
    #: The corpus artifacts the derivations read, so a workload can PIN exactly them before the
    #: first call: a derivation whose pin lacks one refuses (never answers from the image), and a
    #: pin of the whole corpus would put fifty unread versions in the run's consumption trail.
    #: decision-mcp's own RULES table is held equal to this by a test.
    READS = ("guardrails", "guardrail-mapping", "family-triggers")
    readiness = "decision_readiness"          # step 14 — the four M0 gates
    feasibility = "decision_feasibility"      # step 16 — proceed / reject / integration
    exposure = "decision_exposure"            # step 18 — exposure and influence per step
    obligations = "decision_obligations"      # step 19 — the control requirement set
    composition = "decision_composition"      # step 22 — topology, families, enforcement points


class ValuationTools(ToolCatalogue):
    """valuation-mcp — the two CAFÉ derivations that are FINANCIAL, as governed tools.

    A separate server from `decision_mcp` for the reason the framework splits them: the artifacts
    behind them have a different OWNER and a different release cadence. The price sheet, the role
    rate registry and the delegation-of-authority thresholds are finance's, and re-releasing them
    must not mean redeploying the service that holds architecture governance's guardrail set.

    Read-only, like the derivations next door — nothing here writes, so there is no READ/WRITE
    split to make.
    """
    SERVER = "valuation_mcp"
    #: The finance artifact the cost derivation reads under a pin (see DecisionTools.READS).
    READS = ("component-prices",)
    cost = "valuation_cost"                   # step 23 — the cost model over the reference sheet
    benefit = "valuation_benefit"             # step 24 — the drivers, the summary, the verdict


# ---------------------------------------------------------------- the use-case intake pipeline
#
# FOUR processes, split at exactly the human gates that ALWAYS fire — steps 12, 26a and 26b. Step
# 16's gate is conditional (it routes a REJECTION to an architect; a proceed does not wait) and
# step 24's fires only when a benefit figure is missing, so neither is a boundary: a conditional
# boundary would need the ordinary path to self-submit the next process from inside a workload.
#
# Why not one 27-step run that blocks on its approvals. `lab.workloads.consumer` reads with count=1
# and states that concurrency is REPLICAS, so a run blocked for a multi-day review pins its replica
# and every other submission queues behind it. Worse, `close_stale_runs` marks any request the
# consumer took and never acked as FAILED on restart — and CD redeploys every service on every push
# to main, so a blocked three-day run would be destroyed by an unrelated commit. Continuations give
# NFR-04's multi-day open run for free: the durable state is the request hash, the art:// refs and
# the approval, none of which lives in a process's memory.

USE_CASE_SCREENING = ProcessSpec(
    name="use_case_screening",
    group="wf-usecase-screening",
    title="Screen a submitted AI use case and derive its criticality class",
    description=(
        "Take a business team's AI use case as prose and run the first half of the CAFÉ assessment "
        "over it: frame the problem and name one accountable owner, decompose it into active, "
        "behavioural and passive elements, match those to business capabilities and to what already "
        "realises them, derive quality attributes from existing service commitments, check every "
        "business object against the ontology, sequence the work into an explicit workflow graph, "
        "contract its grounding sources, and derive the criticality class. "
        "Ends by asking an architect to confirm that class — the class governs the rigour of a "
        "system somebody else will build, and under-classification propagates. Approving it starts "
        "the design run; nothing else can."),
    inputs=(
        InputField("submission", InputKind.REF,
                   "ONE art://<id>/<name> reference to the submitted use case as prose — a .md, "
                   ".docx or .pdf saying what the problem is, who has it, and what changes if it "
                   "works. Upload it first; a workload reads it through the governed store and "
                   "never from the channel it arrived on.", required=False),
        InputField("submission_handle", InputKind.HANDLE,
                   "Alternative to `submission` for a channel that has the document in the "
                   "collaboration platform rather than in the upload store: the run fetches it "
                   "into the store as its first step. Supply exactly one of the two.",
                   required=False),
        InputField("attachments", InputKind.REF_LIST,
                   "Optional supporting documents — the current process description, a vendor "
                   "quote, an existing analysis. Evidence, not new scope.", required=False),
        InputField("submitter", InputKind.IDENTITY,
                   "The business owner submitting it. Recorded as the accountable person on the "
                   "record and told the outcome — and told only after an architect has seen a "
                   "rejection, never before."),
        InputField("intake", InputKind.MAPPING,
                   "The structured intake fields the business case needs, which prose cannot carry "
                   "reliably: the effort table (role, headcount, frequency per week, current and "
                   "expected minutes), the quality baseline (volume, error rate, expected "
                   "reduction, error class), the sensitivity flags, the budget bucket or vendor "
                   "quote, and the urgency. Missing entries do not block the run — they become "
                   "requires-input markers that the business case carries to the approver as gate "
                   "conditions rather than estimating around. Call `use_case_screening_fields` "
                   "for the published questions — their labels, types, choices and which are "
                   "required — rather than inventing labels: a label nothing published matches is "
                   "carried into the record and reported by nothing.",
                   required=False, questions="intake-field-specs"),
        InputField("effort", InputKind.TABLE,
                   "Who does this work today and for how long — ONE ROW PER ROLE. The only benefit "
                   "driver a submitter can answer from memory, and the one the business case can "
                   "compute exactly: headcount x frequency x the minutes saved, at the published "
                   "rate for that seniority. A role left out is effort the case will not claim.",
                   required=False,
                   columns=(
                       Column("role", InputKind.CHOICE, required=True,
                              choices=("junior", "mid", "senior", "lead", "exec"),
                              description="Seniority band — the key the published rate registry "
                                          "is written against. Job titles vary per team; bands do "
                                          "not, which is why the rate card is keyed on them."),
                       Column("headcount", InputKind.NUMBER, required=True,
                              description="How many people at this band do it."),
                       Column("frequency_per_week", InputKind.NUMBER, required=True,
                              description="How many times a week, per person."),
                       Column("current_minutes", InputKind.NUMBER, required=True,
                              description="Minutes it takes now, per occurrence."),
                       Column("expected_minutes", InputKind.NUMBER, required=True,
                              description="Minutes it would take with the solution. Must not "
                                          "exceed `current_minutes` — a saving is what this "
                                          "measures."))),
        InputField("conversation", InputKind.CONVERSATION,
                   "Optional id of the conversation the submission came from, so the outcome can "
                   "be announced where it was asked for.", required=False),
    ),
    # The submission arrives EITHER as an uploaded ref OR as a handle to fetch. Neither field can
    # carry that rule alone, and leaving it to the workload cost a run per mistake.
    # Two documents is an ambiguity; NO document is not, when the intake itself carries the case.
    one_of=(("submission", "submission_handle"),),
    at_least_one=(("submission", "submission_handle", "intake"),),
    outputs=("trace_id", "approval_id", "review_app", "submission_ref", "screening_ref",
             # What a person looking for a past use case actually searches by. Without it a listing
             # of runs is a column of `art://` refs and nobody can find "the referral triage one".
             "subject", "criticality_band", "summary"),
    products=('screening_ref',),
    identity=("submission", "submission_handle"),
)

USE_CASE_DESIGN = ProcessSpec(
    name="use_case_design",
    group="wf-usecase-design",
    title="Rule on feasibility, then derive the obligations, architecture, cost and business case",
    description=(
        "Continues a screened use case once an architect has confirmed its criticality class. "
        "Declares the outcome assertions, computes the readiness verdict and the determinism "
        "classification, and rules on feasibility. A rejection or an integration finding HALTS the "
        "run here — steps 17 to 25 are not attempted and no partial design package is produced — "
        "and goes to an architect before the submitter hears it. Otherwise it derives the facet "
        "vectors, the exposure and influence classes, the control requirement set, the build "
        "surface, the component selection and the composed architecture, then costs it and builds "
        "the business case, ending at the architect's conformance decision. "
        "Cannot be started directly: its criticality class is a human's answer, and a caller able "
        "to start it would supply its own."),
    inputs=(
        InputField("submission_ref", InputKind.REF,
                   "The validated submission record the screening run persisted."),
        InputField("screening_ref", InputKind.REF,
                   "The screening run's derived output — the elements, capability coverage, "
                   "realisations, quality attributes, ontology findings, workflow graph and "
                   "source contracts, as one artifact."),
        InputField("criticality", InputKind.MAPPING,
                   "The architect's answer at step 12: the confirmed criticality class, and a "
                   "justification where it differs from the derived one. An override is a "
                   "calibration signal for the framework, so it is recorded rather than replaced."),
        InputField("submitter", InputKind.IDENTITY,
                   "Carried from the submission so the outcome reaches the person who asked.",
                   required=False),
        InputField("conversation", InputKind.CONVERSATION,
                   "Carried from the submission, for announcing the outcome.", required=False),
    ),
    outputs=("trace_id", "approval_id", "review_app", "verdict", "halted",
             "readiness", "governance_tier", "risk_ref", "obligations_ref", "architecture_ref",
             "cost_ref", "business_case_ref", "recommendation", "delivery_ref", "summary"),
    products=('architecture_ref',),
    identity=("submission_ref",),
    external=False,
)

USE_CASE_INVESTMENT = ProcessSpec(
    name="use_case_investment",
    group="wf-usecase-investment",
    title="Route the conformance-approved design to the authority that can fund it",
    description=(
        "Continues a design an architect has approved on conformance. Assembles the investment "
        "package — the financial summary, the recommendation and every open gate condition — and "
        "routes it to the delegated authority the investment value calls for. "
        "Conformance approval is not funding approval: a conformant design can be deferred on "
        "value and a valuable one returned on conformance, so the two decisions are taken by "
        "different people against different questions and recorded separately."),
    inputs=(
        InputField("design_ref", InputKind.REF,
                   "The design package the conformance decision approved."),
        InputField("conformance", InputKind.MAPPING,
                   "The architect's answer at step 26a: the conformance decision and any conditions "
                   "attached to it."),
        InputField("submitter", InputKind.IDENTITY, "Carried through.", required=False),
        InputField("conversation", InputKind.CONVERSATION, "Carried through.", required=False),
    ),
    outputs=("trace_id", "approval_id", "review_app", "investment_ref", "recommendation",
             "authority", "summary"),
    products=('investment_ref',),
    identity=("design_ref",),
    external=False,
)

USE_CASE_PROVISIONING = ProcessSpec(
    name="use_case_provisioning",
    group="wf-usecase-provisioning",
    title="Create the work items and catalog entries an approved investment authorised",
    description=(
        "Continues an investment the delegated authority approved. Creates the work item tree and "
        "the portal catalog entries in the target systems — idempotently and reversibly, so "
        "re-running an approved package creates nothing new. "
        "Nothing is created before that approval, and no earlier process is even granted a write "
        "tool: the control is a grant, not a branch somebody could take the wrong way."),
    inputs=(
        InputField("investment_ref", InputKind.REF,
                   "The investment package the funding decision approved."),
        InputField("authorisation", InputKind.MAPPING,
                   "The delegated authority's answer at step 26b: the funding decision, the "
                   "authority that took it, and any conditions."),
        InputField("submitter", InputKind.IDENTITY, "Carried through.", required=False),
    ),
    outputs=("trace_id", "provisioned", "work_items_ref", "catalog_ref", "import_artifacts",
             # The staging key, declared as an output because it is what makes a re-run checkable
             # from OUTSIDE: two runs of one approved package answer with the same key.
             "idempotency", "summary"),
    external=False,
)


#: The use-case pipeline's agents, in the order `AGENTS` lists them.
AGENTS: tuple[AgentSpec, ...] = (
    AgentSpec(name="usecase-agent", prefix="USECASE_AGENT",
              description="Screens a submitted use case and designs it.",
              skills=("use_case_screening", "use_case_design"), model=config.USECASE_AGENT_MODEL,
              processes=("use_case_screening", "use_case_design")),
    AgentSpec(name="usecase-delivery-agent", prefix="USECASE_DELIVERY",
              description="Values a designed use case and provisions its delivery artifacts.",
              skills=("use_case_investment", "use_case_provisioning"), model=config.USECASE_AGENT_MODEL,
              processes=("use_case_investment", "use_case_provisioning")),

    # The ten CAFE bounded contexts. One registration, one key, one card each — because spend
    # attributes per identity, so "the risk officer costs four times what the cost engineer does" is
    # a fact somebody can read rather than infer, and a wrong answer is attributable to the context
    # that gave it rather than to "the use-case workload". `processes` here mirrors which steps each
    # context OWNS in `lab.workloads.usecase.steps`; the parity test is what keeps the two agreeing,
    # since this tier may not import a workload to derive it.
    AgentSpec(name="usecase-business-analyst", prefix="USECASE_BA",
              description="Frames a submitted use case and maps the workflow it implies.",
              skills=("use_case_framing",), model=config.USECASE_AGENT_MODEL, processes=("use_case_screening",)),
    AgentSpec(name="usecase-business-architect", prefix="USECASE_BUSARCH",
              description="Identifies the business elements a use case touches and maps its coverage.",
              skills=("capability_mapping",), model=config.USECASE_AGENT_MODEL, processes=("use_case_screening",)),
    AgentSpec(name="usecase-application-architect", prefix="USECASE_APPARCH",
              description="Matches a use case to the applications that would realise it.",
              skills=("realisation_matching",), model=config.USECASE_AGENT_MODEL, processes=("use_case_screening",)),
    AgentSpec(name="usecase-risk-officer", prefix="USECASE_RISK",
              description="Bands a use case for criticality and states its exposure facets.",
              skills=("criticality_banding",), model=config.USECASE_AGENT_MODEL,
              processes=("use_case_screening", "use_case_design")),
    AgentSpec(name="usecase-product-owner", prefix="USECASE_PO",
              description="States the quality attributes, assertions and delivery artifacts a use case needs.",
              skills=("quality_attributes",), model=config.USECASE_AGENT_MODEL,
              processes=("use_case_screening", "use_case_design")),
    AgentSpec(name="usecase-data-architect", prefix="USECASE_DATA",
              description="States the ontology delta a use case implies and the contracts of its sources.",
              skills=("ontology_delta",), model=config.USECASE_AGENT_MODEL, processes=("use_case_screening",)),
    AgentSpec(name="usecase-solution-architect", prefix="USECASE_SOLARCH",
              description="Decides what must be deterministic and selects the components.",
              skills=("component_selection",), model=config.USECASE_AGENT_MODEL, processes=("use_case_design",)),
    AgentSpec(name="usecase-technology-architect", prefix="USECASE_TECHARCH",
              description="States the build surface a designed use case requires.",
              skills=("build_surface",), model=config.USECASE_AGENT_MODEL, processes=("use_case_design",)),
    AgentSpec(name="usecase-cost-engineer", prefix="USECASE_COST",
              description="States the cost inputs a use case's investment case is valued on.",
              skills=("cost_inputs",), model=config.USECASE_AGENT_MODEL, processes=("use_case_design",)),
    AgentSpec(name="usecase-value-analyst", prefix="USECASE_VALUE",
              description="States the benefit inputs a use case's investment case is valued on.",
              skills=("benefit_inputs",), model=config.USECASE_AGENT_MODEL, processes=("use_case_design",)),
)

# WHAT THIS SLICE CONTRIBUTES — the kernel's PROCESSES, AGENTS and SERVERS are assembled from these.
PROCESSES: tuple[ProcessSpec, ...] = (USE_CASE_SCREENING, USE_CASE_DESIGN, USE_CASE_INVESTMENT,
                                      USE_CASE_PROVISIONING)
CATALOGUES: tuple[type[ToolCatalogue], ...] = (DecisionTools, ValuationTools)

__all__ = ["DecisionTools", "ValuationTools", "USE_CASE_SCREENING", "USE_CASE_DESIGN", "USE_CASE_INVESTMENT",
           "USE_CASE_PROVISIONING", "PROCESSES", "AGENTS", "CATALOGUES"]
