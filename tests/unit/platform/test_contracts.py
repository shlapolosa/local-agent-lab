"""src/lab/platform/contracts.py — the build-time contract between the substrate and the workloads:
the tool catalogue of every substrate MCP server as typed constants (+ the gateway-qualified form),
the `art://` reference value object, the approval and workflow-request contracts. Pure: no I/O.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/platform/test_contracts.py"""
import json

import pytest

from lab.platform import contracts as C
from lab.platform.contracts import (APPROVAL_FINAL, WORKFLOW_FINISHED, WORKFLOW_OPEN, ApprovalKind,
                                    ApprovalStatus, ArtifactRef, Decision, EATools, ImportArtifact,
                                    SemanticTools, StorageTools, WorkflowRequest, WorkflowStatus,
                                    import_artifacts)


# ------------------------------------------------------------------ tool catalogues
def test_catalogues_name_the_tools_exactly_as_the_servers_register_them():
    assert StorageTools.read_vsdx == "storage_read_vsdx" and StorageTools.extract_figures == "storage_extract_figures"
    assert StorageTools.render_vsdx == "storage_render_vsdx"
    assert SemanticTools.store_spec == "semantic_store_spec" and SemanticTools.validate_model == "semantic_validate_model"
    assert EATools.render == "archimate_render" and EATools.stage_import == "ea_stage_import"
    assert EATools.search == "ea_search" and EATools.object == "ea_object"


def test_names_enumerates_only_the_tool_constants():
    assert StorageTools.names() == frozenset({"storage_list", "storage_info", "storage_get", "storage_read_document",
                                              "storage_read_vsdx", "storage_render_vsdx", "storage_extract_figures"})
    assert "storage_mcp" not in StorageTools.names()            # SERVER is the alias, not a tool
    assert all(n.startswith(("semantic_",)) for n in SemanticTools.names()) and len(SemanticTools.names()) == 13
    assert all(n.startswith(("archimate_", "ea_")) for n in EATools.names()) and len(EATools.names()) == 8
    assert "adoit_excel_render" not in EATools.names()        # the vendor's spreadsheet is adapter-private


def test_gateway_qualified_names_use_the_gateway_server_alias():
    assert C.gateway_name("storage_mcp", "storage_read_vsdx") == "storage_mcp-storage_read_vsdx"
    assert StorageTools.gateway(StorageTools.read_vsdx) == "storage_mcp-storage_read_vsdx"
    assert SemanticTools.gateway(SemanticTools.validate_model) == "semantic_mcp-semantic_validate_model"
    assert EATools.gateway(EATools.render) == "ea_mcp-archimate_render"
    with pytest.raises(ValueError, match="not a storage_mcp tool"):
        StorageTools.gateway("semantic_ask")


def test_registry_maps_gateway_aliases_to_catalogues_and_tools_are_globally_unique():
    assert C.SERVERS == {"storage_mcp": StorageTools, "semantic_mcp": SemanticTools, "ea_mcp": EATools,
                         "workflow_mcp": C.WorkflowTools,   # generated from PROCESSES; see tests/unit/substrate/mcp/workflow/
                         "collab_mcp": C.CollabTools}       # files + meetings; served by graph-mcp
    assert all(cls.SERVER == alias for alias, cls in C.SERVERS.items())
    every = [n for cls in C.SERVERS.values() for n in cls.names()]
    assert len(every) == len(set(every)) and C.ALL_TOOLS == frozenset(every)


# ------------------------------------------------------------------ ArtifactRef
def test_artifact_ref_parses_formats_and_round_trips():
    ref = ArtifactRef.parse("art://3f2a/malaffi.vsdx")
    assert ref == ArtifactRef(id="3f2a", name="malaffi.vsdx") and ref.page is None
    assert str(ref) == "art://3f2a/malaffi.vsdx" and ref.base == str(ref)
    paged = ArtifactRef.parse("art://3f2a/malaffi.vsdx#Shafafiya")
    assert paged.page == "Shafafiya" and paged.base == "art://3f2a/malaffi.vsdx"
    assert str(paged) == "art://3f2a/malaffi.vsdx#Shafafiya"           # round-trips WITH the page fragment
    assert ArtifactRef.parse("art://id/x.vsdx# ").page is None           # an empty fragment is no page
    assert ArtifactRef.parse("art://id/dir/nested name.docx").name == "dir/nested name.docx"


def test_artifact_ref_is_immutable_and_hashable():
    ref = ArtifactRef.parse("art://a/b.png")
    with pytest.raises(Exception):
        ref.id = "z"                                                     # frozen
    assert {ref, ArtifactRef("a", "b.png")} == {ref}


@pytest.mark.parametrize("bad", ["", "/tmp/x.vsdx", "art:/a/b", "art://", "art:///x", "art://id", "art://id/", "art://id#p"])
def test_artifact_ref_rejects_paths_and_malformed_refs(bad):
    with pytest.raises(ValueError, match="artifact ref"):
        ArtifactRef.parse(bad)


def test_split_fragment_is_the_one_page_parser_shared_with_docparse():
    from lab.platform import docparse
    assert docparse.split_fragment is C.split_fragment           # re-exported, never re-implemented
    assert C.split_fragment("malaffi.vsdx#Shafafiya") == ("malaffi.vsdx", "Shafafiya")
    assert C.split_fragment("art://ab12/m.vsdx#P 1") == ("art://ab12/m.vsdx", "P 1")
    assert C.split_fragment("x.vsdx") == ("x.vsdx", None) and C.split_fragment("x.vsdx#") == ("x.vsdx", None)
    assert C.split_fragment("") == ("", None)


def test_is_ref_is_the_cheap_syntactic_check():
    assert ArtifactRef.is_ref("art://id/x.vsdx") and ArtifactRef.is_ref("art://id/x.vsdx#Page 1")
    assert not ArtifactRef.is_ref("/tmp/x.vsdx") and not ArtifactRef.is_ref(None) and not ArtifactRef.is_ref(42)


# ------------------------------------------------------------------ approvals
def test_approval_contract_values_are_the_wire_strings():
    assert [d.value for d in Decision] == ["approve", "decline", "update"]
    assert [s.value for s in ApprovalStatus] == ["pending", "approve", "decline", "update"]
    assert APPROVAL_FINAL == frozenset({ApprovalStatus.APPROVE, ApprovalStatus.DECLINE})   # `update` stays open
    assert ApprovalKind.EA_IMPORT == "ea-import"           # neutral: the PORT never names an EA vendor
    assert Decision.APPROVE == "approve" and f"{Decision.UPDATE}" == "update"        # StrEnum: plain-string compatible
    assert "decline" in Decision and "maybe" not in Decision


# ------------------------------------------------------------------ staged import artifacts
def test_import_artifact_derives_the_download_from_the_ref_alone():
    """The adapter supplies MEANING (label, note); everything mechanical comes off the ref, so an
    adapter cannot get the filename or the MIME type of its own artifact wrong."""
    a = ImportArtifact("art://x2/claims.objects.xlsx", "Download objects .xlsx (3 objects)")
    assert a.filename == "claims.objects.xlsx"
    assert a.mime == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert ImportArtifact("art://x1/m.archimate.xml", "L").mime == "application/xml"
    assert ImportArtifact("art://x/o.unknownext", "L").mime == "application/octet-stream"
    assert ImportArtifact("art://x/a.bin", "L", media_type="application/pdf").mime == "application/pdf"
    assert ImportArtifact("art://x/p.pdf#2", "L").filename == "p.pdf"          # a page fragment is not a name
    assert ImportArtifact("/tmp/local/objects.xlsx", "L").filename == "objects.xlsx"   # local dev path


def test_import_artifact_round_trips_through_the_approval_payload():
    a = ImportArtifact("art://x/o.xlsx", "Objects", note="matched by name", media_type="application/x")
    assert ImportArtifact.from_dict(a.to_dict()) == a
    assert set(a.to_dict()) == {"ref", "label", "note", "media_type"}
    assert ImportArtifact.from_dict({"ref": "art://x/o.xlsx", "label": "Objects"}).note == ""
    with pytest.raises(ValueError, match="both a ref and a label"):
        ImportArtifact("", "Objects")
    with pytest.raises(ValueError, match="both a ref and a label"):
        ImportArtifact("art://x/o.xlsx", "  ")


def test_import_artifacts_reads_the_adapters_list_verbatim():
    """The review app renders what the ADAPTER sent — order, labels and notes included. Nothing here
    knows that one of them is a spreadsheet."""
    payload = {"xml_ref": "art://x1/m.archimate.xml", "summary": {},
               "import_artifacts": [{"ref": "art://x1/m.archimate.xml", "label": "Views XML"},
                                    {"ref": "art://x2/o.xlsx", "label": "Objects", "note": "by name"}]}
    got = import_artifacts(payload)
    assert [(a.ref, a.label, a.note) for a in got] == [("art://x1/m.archimate.xml", "Views XML", ""),
                                                       ("art://x2/o.xlsx", "Objects", "by name")]
    assert import_artifacts({"import_artifacts": []}) == []      # a repository that writes over its own API
    assert import_artifacts({}) == []


def test_import_artifacts_still_opens_an_approval_staged_before_the_neutral_shape():
    """COMPAT: ~10 approvals were staged with the old flat payload (`xml_ref` + `xlsx_ref`). The rule is
    GENERIC — every `*_ref` string becomes a download labelled by its own filename — so a reviewer can
    still take every file out of an old request without this module knowing what any of them were."""
    legacy = {"xml_ref": "art://x1/model.archimate.xml", "xlsx_ref": "art://x2/objects.xlsx",
              "svg_refs": {"Overview": "art://s1/o.svg"},          # a dict of previews is not a download
              "summary": {"elements": 3}}
    assert [(a.ref, a.label) for a in import_artifacts(legacy)] == [
        ("art://x1/model.archimate.xml", "model.archimate.xml"), ("art://x2/objects.xlsx", "objects.xlsx")]


# ------------------------------------------------------------------ workflow requests
def test_workflow_status_values():
    assert [s.value for s in WorkflowStatus] == ["pending", "running", "done", "failed"]
    assert WORKFLOW_FINISHED == frozenset({WorkflowStatus.DONE, WorkflowStatus.FAILED})
    assert WORKFLOW_OPEN == frozenset({WorkflowStatus.PENDING, WorkflowStatus.RUNNING})
    assert WorkflowStatus.RUNNING == "running" and "done" in WorkflowStatus


def test_workflow_request_round_trips_through_the_stream_fields():
    req = WorkflowRequest(request_id="wfr-1", process="visio_to_archimate",
                          inputs={"diagram": "art://d/x.vsdx", "requirements": []}, requester="socrates",
                          created_at="2026-09-04T10:00:00+00:00", created_ts="1.5")
    fields = req.to_fields()
    assert fields == {"request_id": "wfr-1", "process": "visio_to_archimate",
                      "inputs": json.dumps({"diagram": "art://d/x.vsdx", "requirements": []}),
                      "requester": "socrates", "status": "pending",
                      "created_at": "2026-09-04T10:00:00+00:00", "created_ts": "1.5"}
    assert all(isinstance(v, str) for v in fields.values())            # Redis hash / stream values are strings
    back = WorkflowRequest.from_fields(fields)
    assert back == req and back.status is WorkflowStatus.PENDING
    assert back.diagram == "art://d/x.vsdx" and back.requirements == []


def test_workflow_request_from_fields_tolerates_a_consumer_updated_hash():
    fields = {"request_id": "wfr-2", "process": "p", "inputs": '{"diagram": "d", "requirements": ["r1"]}',
              "requester": "u", "status": "running", "created_at": "t", "created_ts": "2", "trace_id": "abc",
              "consumer": "1"}                                            # extra progress fields are ignored
    req = WorkflowRequest.from_fields(fields)
    assert req.status is WorkflowStatus.RUNNING and req.requirements == ["r1"] and req.diagram == "d"
    with pytest.raises(KeyError):
        WorkflowRequest.from_fields({"request_id": "x"})                 # a malformed event is an error, not a guess


def test_contracts_module_is_pure():
    """Importable by both tiers with no I/O: only stdlib + lab.core/lab.platform names."""
    import ast
    tree = ast.parse(open(C.__file__, encoding="utf-8").read())
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | \
           {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert all(not m.startswith("lab.") or m.startswith(("lab.core", "lab.platform")) for m in mods), mods
    assert not {m for m in mods if m in ("redis", "os", "requests", "httpx", "fastmcp")}


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
