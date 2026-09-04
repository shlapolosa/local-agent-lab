"""The build-time CONTRACT between the substrate and the workloads — what a workload may rely on
without importing the substrate (CLAUDE.md tier rule: a workload reaches the substrate only over the
network, so what it compiles against lives here, in the kernel both tiers share). Pure data: no I/O,
no clients, importable by every tier.

  Tool catalogues   the tools each substrate MCP server registers, as typed constants, EXACTLY as
                    registered (`tests/governance/test_contracts_match_servers.py` enforces parity in
                    both directions), plus the gateway-qualified form the LiteLLM proxy exposes them
                    under (`<server alias>-<tool>`; aliases per config/litellm-config.yaml `mcp_servers`).
  ArtifactRef       the `art://<id>/<name>[#<page>]` reference — the only handle a workload holds on an
                    input or an artifact (the substrate's stores mint and resolve them).
  Approval contract request kinds, decision values and status names of the human-in-the-loop gate.
  Workflow requests the `workflow:requests` event (statuses, field names) a host consumes.

Adding a tool = one constant on its catalogue (the parity test fails until it matches the server).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

# ----------------------------------------------------------------------------- tool catalogues
def gateway_name(server: str, tool: str) -> str:
    """The name the gateway exposes a server's tool under: `<server alias>-<tool>`."""
    return f"{server}-{tool}"


class ToolCatalogue:
    """Base of the per-server catalogues: `SERVER` is the gateway alias; every other public class
    attribute is a tool name as the server registers it."""

    SERVER: str = ""

    @classmethod
    def names(cls) -> frozenset[str]:
        return frozenset(v for k, v in vars(cls).items()
                         if not k.startswith("_") and k != "SERVER" and isinstance(v, str))

    @classmethod
    def gateway(cls, tool: str) -> str:
        if tool not in cls.names():
            raise ValueError(f"{tool!r} is not a {cls.SERVER} tool")
        return gateway_name(cls.SERVER, tool)


class StorageTools(ToolCatalogue):
    """storage-mcp — READ-ONLY governed access to the upload store (the only way a workload reads an input)."""
    SERVER = "storage_mcp"
    list = "storage_list"
    info = "storage_info"
    get = "storage_get"
    read_document = "storage_read_document"
    read_vsdx = "storage_read_vsdx"
    extract_figures = "storage_extract_figures"


class SemanticTools(ToolCatalogue):
    """semantic-mcp — vocabularies as data, legality, SPARQL, reference models; `store_spec` persists any JSON by ref."""
    SERVER = "semantic_mcp"
    ontologies = "semantic_ontologies"
    describe = "semantic_describe"
    classify = "semantic_classify"
    check = "semantic_check"
    validate_model = "semantic_validate_model"
    load_model = "semantic_load_model"
    query = "semantic_query"
    schemes = "semantic_schemes"
    concepts = "semantic_concepts"
    export_archimate = "semantic_export_archimate"
    store_spec = "semantic_store_spec"
    questions = "semantic_questions"
    ask = "semantic_ask"


class AdoitTools(ToolCatalogue):
    """adoit-mcp — the ArchiMate engine + the governed ADOIT repository facade (reads; human-gated import)."""
    SERVER = "adoit_mcp"
    validate = "archimate_validate"
    render = "archimate_render"
    excel_render = "adoit_excel_render"
    repos = "adoit_repos"
    search = "adoit_search"
    object = "adoit_object"
    request_import = "adoit_request_import"
    import_status = "adoit_import_status"
    import_instructions = "adoit_import_instructions"


SERVERS: dict[str, type[ToolCatalogue]] = {c.SERVER: c for c in (StorageTools, SemanticTools, AdoitTools)}
ALL_TOOLS: frozenset[str] = frozenset(n for c in SERVERS.values() for n in c.names())


# ----------------------------------------------------------------------------- artifact references
_SCHEME = "art://"


def split_fragment(src: str) -> tuple[str, str | None]:
    """(base, page) for any source — a path or an `art://` ref. A `#<page>` fragment selects ONE page of a
    multi-page .vsdx (`malaffi.vsdx#Shafafiya`, `art://<id>/malaffi.vsdx#Shafafiya`). The ONE parser:
    `lab.platform.docparse` re-exports this, so a ref and a path are split identically."""
    base, _, frag = (src or "").partition("#")
    return base, (frag.strip() or None)


@dataclass(frozen=True)
class ArtifactRef:
    """`art://<id>/<name>[#<page>]` — an artifact or input in a substrate store, by reference. The
    optional `#<page>` fragment selects ONE page of a multi-page .vsdx (`split_fragment` above — the
    same parser `lab.platform.docparse` uses for paths). `str(ref)` round-trips the parsed text."""

    id: str
    name: str
    page: str | None = None

    @staticmethod
    def is_ref(src: Any) -> bool:
        """The cheap syntactic check (a path is not a ref)."""
        return isinstance(src, str) and src.startswith(_SCHEME)

    @classmethod
    def parse(cls, ref: str) -> "ArtifactRef":
        if not cls.is_ref(ref):
            raise ValueError(f"not an artifact ref: {ref!r}")
        base, page = split_fragment(ref[len(_SCHEME):])
        aid, _, name = base.partition("/")
        if not aid or not name:
            raise ValueError(f"malformed artifact ref (want art://<id>/<name>): {ref!r}")
        return cls(aid, name, page)

    @property
    def base(self) -> str:
        """The ref without its page fragment — what is loaded/stored."""
        return f"{_SCHEME}{self.id}/{self.name}"

    def __str__(self) -> str:
        return self.base + (f"#{self.page}" if self.page else "")


# ----------------------------------------------------------------------------- approval gate
class ApprovalKind(StrEnum):
    ADOIT_IMPORT = "adoit-import"


class Decision(StrEnum):
    """What a human may answer; `update` = changes requested, the request stays open."""
    APPROVE = "approve"
    DECLINE = "decline"
    UPDATE = "update"


class ApprovalStatus(StrEnum):
    """A request's status: pending until a decision, then the decision itself."""
    PENDING = "pending"
    APPROVE = "approve"
    DECLINE = "decline"
    UPDATE = "update"


APPROVAL_FINAL = frozenset({ApprovalStatus.APPROVE, ApprovalStatus.DECLINE})   # `update` = changes requested, still open


# ----------------------------------------------------------------------------- workflow requests
class WorkflowStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


WORKFLOW_FINISHED = frozenset({WorkflowStatus.DONE, WorkflowStatus.FAILED})
WORKFLOW_OPEN = frozenset({WorkflowStatus.PENDING, WorkflowStatus.RUNNING})


@dataclass(frozen=True)
class WorkflowRequest:
    """One `workflow:requests` event / `workflow:req:<id>` hash as published by a producer (the
    review app's Submit, the CLI). Progress fields the consumer writes back (trace_id, approval_id,
    error, …) are not part of the request contract and are ignored on `from_fields`."""

    request_id: str
    process: str
    inputs: dict[str, Any]            # {"diagram": art://…, "requirements": [art://…]} for visio_to_archimate
    requester: str
    created_at: str
    created_ts: str
    status: WorkflowStatus = WorkflowStatus.PENDING

    @property
    def diagram(self) -> str:
        return self.inputs["diagram"]

    @property
    def requirements(self) -> list[str]:
        return list(self.inputs.get("requirements") or [])

    def to_fields(self) -> dict[str, str]:
        """The Redis hash / stream entry (every value a string; `inputs` JSON-encoded)."""
        return {"request_id": self.request_id, "process": self.process, "inputs": json.dumps(self.inputs),
                "requester": self.requester, "status": self.status.value,
                "created_at": self.created_at, "created_ts": self.created_ts}

    @classmethod
    def from_fields(cls, fields: dict[str, str]) -> "WorkflowRequest":
        return cls(request_id=fields["request_id"], process=fields["process"], inputs=json.loads(fields["inputs"]),
                   requester=fields["requester"], created_at=fields["created_at"], created_ts=fields["created_ts"],
                   status=WorkflowStatus(fields["status"]))


__all__ = ["gateway_name", "ToolCatalogue", "StorageTools", "SemanticTools", "AdoitTools", "SERVERS", "ALL_TOOLS",
           "split_fragment", "ArtifactRef", "ApprovalKind", "Decision", "ApprovalStatus", "APPROVAL_FINAL",
           "WorkflowStatus", "WORKFLOW_FINISHED", "WORKFLOW_OPEN", "WorkflowRequest"]
