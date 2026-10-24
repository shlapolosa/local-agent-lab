"""The MODELLING slice: input artifacts -> an architecture model with provenance (ADR 2026-10-24).

Its own process (D7), externally startable, so a channel can ask for a model without a use-case
screening. Visualisation is a separate capability: it takes the envelope's `spec` and draws it.
"""
from __future__ import annotations

from lab.platform import config
from lab.platform.contracts import AgentSpec, InputField, InputKind, ProcessSpec, ToolCatalogue

ARCHITECTURE_MODELLING = ProcessSpec(
    name="architecture_modelling",
    group="wf-architecture-modelling",
    title="Model the architecture a set of documents describes",
    description=(
        "Read the submitted documents and build the ArchiMate model they describe, across every layer "
        "they cover: motivation, strategy, business, data, application and technology. Every element "
        "and relationship cites the words that justify it (document, location, verbatim quote); a "
        "quote that does not appear in its source is flagged, never silently kept. Ends by asking an "
        "architect to review the model against its citations, before anything is drawn or imported. "
        "Returns `model_ref`, the modelling envelope (contracts/modelling.json): the engine spec "
        "unchanged, with provenance, references and open questions beside it."),
    inputs=(
        InputField("documents", InputKind.REF_LIST,
                   "One or more art://<id>/<name> references to the documents to model from (.docx, "
                   ".pdf, .md, .txt). Upload them first; the run reads them through the governed "
                   "store.", kinds=("document",)),
        InputField("submitter", InputKind.IDENTITY,
                   "Who asked for the model. Recorded as the requester of the review.", required=False),
    ),
    outputs=("trace_id", "approval_id", "review_app", "model_ref", "summary"),
    identity=("documents",),
)

AGENTS: tuple[AgentSpec, ...] = (
    AgentSpec(name="architecture-modelling-agent", prefix="MODELLING_AGENT",
              description="Builds the ArchiMate model a set of documents describes, citing every "
                          "element and relationship.",
              skills=("architecture_modelling",), model=config.MODELLING_AGENT_MODEL,
              processes=("architecture_modelling",)),
)

PROCESSES: tuple[ProcessSpec, ...] = (ARCHITECTURE_MODELLING,)
#: No MCP server of its own: modelling is a workload calling existing tools.
CATALOGUES: tuple[type[ToolCatalogue], ...] = ()

__all__ = ["AGENTS", "ARCHITECTURE_MODELLING", "CATALOGUES", "PROCESSES"]
