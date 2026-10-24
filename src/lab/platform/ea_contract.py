"""The VISUALISATION capability's results, declared ONCE (FR-19, user decision 24 Oct 2026).

Visualisation takes an engine spec (`contracts/archimate-spec.schema.json`) and builds the outputs: the
Exchange XML with its views, an SVG per view, the repository's import files, and the `ea-import` approval
a human decides. A channel that emulates it until the lab lands in its tenant (the SAF pack) needs to
know the SHAPE of those results, not only the tools' inputs — so they are typed here and published as
JSON Schema: per tool in `contracts/ea-tools.json` (`resultSchema`) and, for the approval a person sees,
`contracts/ea-approval.schema.json`.

WHY NOT the tools' MCP `outputSchema`. Declaring one makes fastmcp's client hydrate `.data` into a
generated object instead of a dict (measured, fastmcp 3.4.7), and `lab.platform.mcp_client` hands `.data`
to every workload — the visio workflow reads `r["xml_ref"]`. So the schemas are published and enforced by
tests against the real outputs, and the wire stays as it is.

ADDITIVE by design (`extra="allow"`): an adapter MAY add facts of its own (this one adds
`import_objects`, `render_violations`); a caller must never require them, and a schema that refused them
would turn every new fact into a breaking change. The import artifact mirrors `ImportArtifact` field for
field (a test holds them equal).
"""
from __future__ import annotations

import pydantic

from lab.platform.contracts import ApprovalStatus, EATools
from lab.platform.submit_schema import inline

__all__ = ["result_schemas", "approval_schema"]

_OPEN = pydantic.ConfigDict(extra="allow")


class _Artifact(pydantic.BaseModel):
    """`lab.platform.contracts.ImportArtifact` as data: one file a human carries into the repository."""
    model_config = pydantic.ConfigDict(extra="forbid")
    ref: str = pydantic.Field(min_length=1, description="art://<id>/<name> — the download")
    label: str = pydantic.Field(min_length=1, description="what the human sees, in the adapter's words")
    note: str = pydantic.Field("", description="one line of guidance: how this file is imported")
    media_type: str = pydantic.Field("", description="overrides the MIME guessed from the filename")


class _Staged(pydantic.BaseModel):
    """The staged MODEL: the Exchange XML with its views and an SVG preview per view."""
    model_config = _OPEN
    xml_ref: str = pydantic.Field(min_length=1, description="the ArchiMate Model Exchange XML (with views)")
    svg_refs: dict[str, str] = pydantic.Field(default_factory=dict, description="view id -> SVG preview ref")


class _Summary(pydantic.BaseModel):
    """What the reviewer triages on. The caller's counts plus any facts the adapter adds — all optional."""
    model_config = _OPEN
    elements: int | None = None
    relations: int | None = None
    views: int | None = None
    violations: int | None = None
    warnings: int | None = None
    import_objects: int | None = pydantic.Field(None, description="adapter fact: objects in the import file")
    render_violations: int | None = pydantic.Field(None, description="adapter fact: the lenient render's violations")


class ApprovalPayload(_Staged):
    """The `ea-import` approval a human decides — opaque import files rendered as labelled downloads."""
    summary: _Summary = pydantic.Field(default_factory=_Summary)
    import_artifacts: list[_Artifact] = pydantic.Field(default_factory=list,
                                                       description="empty on a repository that writes over its own API")
    instructions: str = pydantic.Field("", description="the adapter's human import procedure")


class RenderResult(pydantic.BaseModel):
    """`archimate_render`: the model laid out and rendered, stored by reference."""
    model_config = _OPEN
    xml_ref: str = pydantic.Field(min_length=1)
    svg_refs: dict[str, str]
    views: dict[str, tuple[int, int]] = pydantic.Field(description="view id -> [canvas width, canvas height]")
    violations: list[str] = pydantic.Field(description="layout-invariant / XSD findings (non-empty only when strict=false)")
    warnings: list[str] = pydantic.Field(description="relationship-legality warnings")
    schema_validated: bool = pydantic.Field(description="whether the XML was checked against the Exchange XSD")
    files: list[str] = pydantic.Field(default_factory=list, description="local copies, only with outdir (dev)")


class StageImportResult(pydantic.BaseModel):
    """`ea_stage_import`: the approval was published; nothing was written to the repository."""
    model_config = _OPEN
    request_id: str = pydantic.Field(min_length=1, description="poll with ea_import_status")
    status: str = pydantic.Field(description="'pending' — a human has not decided yet")
    channels: list[str]
    review_app: str
    artifacts: _Staged
    import_artifacts: list[_Artifact]
    instructions: str


class ImportStatusResult(pydantic.BaseModel):
    """`ea_import_status`: the decision so far and what happens next."""
    model_config = _OPEN
    request_id: str
    kind: str
    subject: str = ""
    status: ApprovalStatus
    next: str = pydantic.Field(description="what happens next, in words")
    write_path: str = pydantic.Field(description="'file-import' on this tenant")
    rest_write_enabled: bool
    payload: ApprovalPayload | None = None
    comment: str | None = None
    decided_by: str | None = None


def _schema(model: type[pydantic.BaseModel]) -> dict:
    return inline(model.model_json_schema())


def result_schemas() -> dict[str, dict]:
    """tool name -> the JSON Schema of what it returns."""
    return {EATools.render: _schema(RenderResult),
            EATools.stage_import: _schema(StageImportResult),
            EATools.import_status: _schema(ImportStatusResult)}


def approval_schema() -> dict:
    """The `ea-import` approval payload — what every channel shows a person deciding an EA write."""
    return _schema(ApprovalPayload)
