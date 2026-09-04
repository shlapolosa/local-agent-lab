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
  Process registry  every business PROCESS declared once (`PROCESSES`): how it is addressed, what a
                    caller must know about it, its typed INPUT CONTRACT and the outputs a finished run
                    publishes. workflow-mcp generates its tools from this, so registering a process is
                    one entry here — no code change in the server.

Adding a tool = one constant on its catalogue (the parity test fails until it matches the server).
Adding a process = one `ProcessSpec` in `PROCESSES` (+ its consumer group in lab.platform.workflows.GROUPS).
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


class WorkflowTools(ToolCatalogue):
    """workflow-mcp — the governed front door to every business PROCESS. Its tools are not fixed
    constants: they are GENERATED, three per entry in `PROCESSES` below (`<process>_submit`,
    `<process>_status`, `<process>_result`), so registering a process is the one place that changes."""
    SERVER = "workflow_mcp"
    VERBS = ("submit", "status", "result")             # a tuple, so `names()`'s string filter ignores it

    @classmethod
    def names(cls) -> frozenset[str]:
        return frozenset(spec.tool(v) for spec in PROCESSES.values() for v in cls.VERBS)


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


# ----------------------------------------------------------------------------- process registry
class InputKind(StrEnum):
    """How one input field is carried. Both kinds are `art://` references (or, for local dev, a path):
    a workload holds no store credentials, so an input is ALWAYS passed by reference."""
    REF = "ref"            # exactly one reference
    REF_LIST = "ref_list"  # zero or more references


@dataclass(frozen=True)
class InputField:
    """One field of a process's input contract: its name, kind, prose (the JSON-schema description an
    agent reads) and whether it is required. `coerce` is the validator, meant to be the ONE validator
    every producer shares — workflow-mcp uses it today; the review app's Submit page and the
    `workflows.py` CLI still publish unvalidated and are to be moved onto it."""

    name: str
    kind: InputKind
    description: str
    required: bool = True

    def coerce(self, value: Any) -> Any:
        """The normalised value, or ValueError naming the field. `None`/absent is legal only when the
        field is optional (a REF_LIST then normalises to [])."""
        if value is None or value == "" or value == []:
            if self.required:
                raise ValueError(f"{self.name} is required")
            return [] if self.kind is InputKind.REF_LIST else None
        if self.kind is InputKind.REF:
            return self._one(value)
        if isinstance(value, str) or not isinstance(value, (list, tuple)):
            raise ValueError(f"{self.name} must be a list of references, got {type(value).__name__}")
        return [self._one(v) for v in value]

    def _one(self, value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{self.name} must be a non-empty reference string")
        value = value.strip()
        if ArtifactRef.is_ref(value):
            ArtifactRef.parse(value)          # raises ValueError on a malformed ref
        elif "://" in value:                  # a URL is never an input: uploads live in the lab's store
            raise ValueError(f"{self.name}: {value!r} is not an art:// reference (upload the file first)")
        return value


@dataclass(frozen=True)
class ProcessSpec:
    """One business process, declared ONCE: how it is addressed (name + the Redis consumer group of the
    host that runs it), what a human/agent needs to know about it, its typed input contract, and the
    fields its finished run publishes. Every external surface (workflow-mcp today; REST/A2A later) is
    generated from this — adding a process is one entry in `PROCESSES`, not a code change."""

    name: str                          # the `process` field of a workflow:requests event
    group: str                         # the consumer group of the host that runs it (lab.platform.workflows.GROUPS)
    title: str
    description: str                   # what it does, for a tool description an agent reads unaided
    inputs: tuple[InputField, ...]
    outputs: tuple[str, ...] = ()      # request-hash fields a finished run publishes

    def tool(self, verb: str) -> str:
        """The name of one of this process's generated tools (`<process>_<verb>`)."""
        if verb not in WorkflowTools.VERBS:
            raise ValueError(f"{verb!r} is not one of {WorkflowTools.VERBS}")
        return f"{self.name}_{verb}"

    def field(self, name: str) -> InputField:
        for f in self.inputs:
            if f.name == name:
                return f
        raise ValueError(f"{self.name} has no input {name!r}")

    def validate(self, values: dict[str, Any]) -> dict[str, Any]:
        """The `inputs` payload of a workflow:requests event, or ValueError. Unknown keys are refused
        (a typo must not be silently dropped); optional fields absent from `values` stay absent."""
        unknown = sorted(set(values) - {f.name for f in self.inputs})
        if unknown:
            raise ValueError(f"{self.name}: unknown input(s) {unknown}; expected "
                             f"{[f.name for f in self.inputs]}")
        out: dict[str, Any] = {}
        for f in self.inputs:
            v = f.coerce(values.get(f.name))
            if v is not None:
                out[f.name] = v
        return out


VISIO_TO_ARCHIMATE = ProcessSpec(
    name="visio_to_archimate",
    group="wf-visio",
    title="Visio/diagram to ArchiMate model",
    description=(
        "Turn a system diagram — a Microsoft Visio .vsdx or a diagram image — plus any requirements "
        "documents into a validated ArchiMate 3.1 model of that system, matched against the existing "
        "architecture in the ADOIT repository and staged for human approval before import. "
        "A run takes 10-20 minutes, so it is asynchronous: submit returns a request_id immediately."),
    inputs=(
        InputField("diagram", InputKind.REF,
                   "The diagram to read: ONE art://<id>/<name> reference to a .vsdx file or a diagram "
                   "image (.png/.jpg) already uploaded to the lab's upload store. Append #<page> to "
                   "read a single page of a multi-page .vsdx."),
        InputField("requirements", InputKind.REF_LIST,
                   "Optional art:// references to requirements documents (.docx/.pdf/.md/.txt) that "
                   "describe the same system; they are used as evidence about the diagram, never as a "
                   "source of elements the diagram does not show.", required=False),
    ),
    outputs=("trace_id", "approval_id", "review_app", "xml_ref", "xlsx_ref", "summary"),
)

PROCESSES: dict[str, ProcessSpec] = {p.name: p for p in (VISIO_TO_ARCHIMATE,)}


# ----------------------------------------------------------------------------- the registry of servers
# Last, because WorkflowTools' tool names are derived from PROCESSES above.
SERVERS: dict[str, type[ToolCatalogue]] = {c.SERVER: c for c in (StorageTools, SemanticTools, AdoitTools,
                                                                 WorkflowTools)}
ALL_TOOLS: frozenset[str] = frozenset(n for c in SERVERS.values() for n in c.names())


__all__ = ["gateway_name", "ToolCatalogue", "StorageTools", "SemanticTools", "AdoitTools", "WorkflowTools",
           "SERVERS", "ALL_TOOLS",
           "split_fragment", "ArtifactRef", "ApprovalKind", "Decision", "ApprovalStatus", "APPROVAL_FINAL",
           "WorkflowStatus", "WORKFLOW_FINISHED", "WORKFLOW_OPEN", "WorkflowRequest",
           "InputKind", "InputField", "ProcessSpec", "PROCESSES", "VISIO_TO_ARCHIMATE"]
