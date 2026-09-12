"""The Documentation Fabric's contracts: two continuation-only processes, three input kinds that carry
a pointer, an event id and a delivery context, two approval kinds, and the ArtifactChanged event."""
import json

import pytest

from lab.core import ids
from lab.platform import contracts, workflows
from lab.platform.contracts import (AGENTS, ARTIFACT_INTAKE, ARTIFACT_PUBLISH, PROCESSES,
                                    ApprovalKind, ArtifactChanged, InputField, InputKind,
                                    WorkflowTools)

POINTER = {"source": "collab", "handle": "collab://item/drive-1/01ABC", "version": "4.0"}


# ------------------------------------------------------------------ processes
def test_both_processes_are_registered_and_continuation_only():
    for spec in (ARTIFACT_INTAKE, ARTIFACT_PUBLISH):
        assert PROCESSES[spec.name] is spec
        assert spec.external is False, "an outside caller must never start intake or publication"
        assert "submit" not in WorkflowTools.verbs_for(spec)
        assert spec.tool("status") in WorkflowTools.names()
    assert ARTIFACT_INTAKE.group in workflows.GROUPS and ARTIFACT_PUBLISH.group in workflows.GROUPS


def test_intake_validates_its_inputs():
    ok = ARTIFACT_INTAKE.validate({"pointer": POINTER, "event_id": ids.ulid(),
                                   "context": "meeting:AAMk123", "produced_by": "transcript_to_minutes"})
    assert ok["pointer"] == POINTER and ok["context"] == "meeting:AAMk123"
    assert ok["produced_by"] == "transcript_to_minutes"
    with pytest.raises(ValueError):
        ARTIFACT_INTAKE.validate({"pointer": POINTER, "event_id": "nope"})
    with pytest.raises(ValueError):
        ARTIFACT_INTAKE.validate({"pointer": POINTER, "event_id": ids.ulid(), "produced_by": "not_a_process"})
    minimal = ARTIFACT_INTAKE.validate({"pointer": POINTER, "event_id": ids.ulid()})
    assert "context" not in minimal and "produced_by" not in minimal


def test_publish_takes_the_artifact_and_the_approval():
    ok = ARTIFACT_PUBLISH.validate({"artifact_iri": ids.artifact_iri(), "approval_id": "apr-0123456789ab"})
    assert ok["artifact_iri"].startswith("urn:fabric:artifact:") and ok["approval_id"] == "apr-0123456789ab"
    with pytest.raises(ValueError):
        ARTIFACT_PUBLISH.validate({"artifact_iri": "https://x/y", "approval_id": "apr-0123456789ab"})
    for bad in (ids.ulid(), "apr-xyz", "https://x/apr-0123456789ab", ""):
        with pytest.raises(ValueError):
            ARTIFACT_PUBLISH.validate({"artifact_iri": ids.artifact_iri(), "approval_id": bad})


# ------------------------------------------------------------------ input kinds
def _f(kind, **kw):
    return InputField("f", kind, "d", **kw)


def test_pointer_is_bounded_structured_and_source_checked():
    assert _f(InputKind.POINTER).coerce(POINTER) == POINTER
    assert _f(InputKind.POINTER).coerce(json.dumps(POINTER)) == POINTER, "a JSON string is accepted"
    lab = {"source": "lab", "ref": "art://abc/minutes.docx"}
    assert _f(InputKind.POINTER).coerce(lab) == lab
    for bad in ({"source": "dropbox", "id": "1"}, {"site": "ea"}, {"source": "collab"},
                {"source": "collab", "itemId": "x", "url": "https://evil"},
                {"source": "collab", "handle": "https://evil/x"},
                {"source": "collab", "itemId": "x" * 2000}, "not json", 42):
        with pytest.raises(ValueError):
            _f(InputKind.POINTER).coerce(bad)


def test_event_id_is_a_ulid():
    u = ids.ulid()
    assert _f(InputKind.EVENT).coerce(u) == u
    assert _f(InputKind.EVENT).coerce(f"  {u} ") == u
    for bad in ("01J9X5K7QZ3M8N2P4R6T8V0W1I", "", "x", 12):
        with pytest.raises(ValueError):
            _f(InputKind.EVENT).coerce(bad)


def test_context_is_kind_colon_id_from_a_closed_set():
    assert _f(InputKind.CONTEXT).coerce("usecase:UC-42") == "usecase:UC-42"
    assert _f(InputKind.CONTEXT).coerce("workitem:4471") == "workitem:4471"
    for bad in ("ticket:1", "usecase:", "usecase:has space", "usecase:http://x", "usecase:" + "a" * 300):
        with pytest.raises(ValueError):
            _f(InputKind.CONTEXT).coerce(bad)


# ------------------------------------------------------------------ approval kinds
def test_new_approval_kinds_name_no_vendor_and_are_distinct():
    assert ApprovalKind.ASSOCIATION == "association" and ApprovalKind.DRAFT_REVIEW == "draft-review"
    assert len({k.value for k in ApprovalKind}) == len(list(ApprovalKind))


# ------------------------------------------------------------------ the event
def _event(**over):
    base = dict(event_id=ids.ulid(), pointer=POINTER, source_kind="collab", change="updated",
                actor_oid="3f2a", occurred_at="2026-09-11T08:10:31Z")
    base.update(over)
    return ArtifactChanged(**base)


def test_event_round_trips_through_redis_fields():
    e = _event(fabric_tag={"runId": "r1", "kind": "draft"}, produced_by="transcript_to_minutes",
               context="meeting:AAMk1")
    fields = e.to_fields()
    assert all(isinstance(v, str) for v in fields.values())
    back = ArtifactChanged.from_fields(fields)
    assert back == e
    assert e.pointer_key == "collab:collab://item/drive-1/01ABC"
    assert e.is_fabric_originated


def test_event_refuses_a_bad_shape():
    with pytest.raises(ValueError):
        _event(event_id="nope")
    with pytest.raises(ValueError):
        _event(change="exploded")
    with pytest.raises(ValueError):
        _event(source_kind="sharepoint")
    with pytest.raises(ValueError):
        _event(pointer={"source": "collab"})
    with pytest.raises(ValueError):
        _event(produced_by="not_a_process")
    plain = _event()
    assert not plain.is_fabric_originated and plain.fabric_tag is None


# ------------------------------------------------------------------ agents
def test_the_two_fabric_agents_are_registered_for_intake():
    by = {a.prefix: a for a in AGENTS}
    for prefix in ("CLASSIFIER_AGENT", "SYNTHESIS_AGENT"):
        assert prefix in by and by[prefix].processes == ("artifact_intake",)
        assert by[prefix].model == "kimi-k3"


def test_semantic_tools_split_read_pipeline_and_promote():
    """The grants partition the server: READ is every query (what every team had, plus the products' reads);
    PIPELINE is what the intake/publish workloads write at a rung; PROMOTE is a person's decision and REINDEX
    an operator's sweep, neither reaching a workload. WRITE = the three non-READ grants so the guarded-write
    ratchet covers the catalogue."""
    from lab.platform.contracts import SemanticTools as T
    grants = [set(g) for g in T.GRANTS]
    assert set.union(*grants) == T.names() and all(a.isdisjoint(b) for a in grants for b in grants if a is not b)
    assert set(T.WRITE) == set(T.PIPELINE) | set(T.PROMOTE) | set(T.REINDEX)
    assert T.PROMOTE == ("semantic_promote",) and T.REINDEX == ("semantic_reindex",)
    assert {"semantic_catalog_get", "semantic_impact", "semantic_search", "semantic_query"} <= set(T.READ)
    assert {"semantic_catalog_upsert", "semantic_edge_assert", "semantic_embed"} <= set(T.PIPELINE)
    assert T.READ in T.GRANTS and T.REINDEX in T.GRANTS



def test_the_contract_imports_no_semantic_layer_at_module_level():
    """`lab.platform.contracts` is imported by every tier and by CI steps that install no rdflib (the
    store-registration step died on `ModuleNotFoundError: rdflib` the day the contract reached through
    `lab.core.semantic`). The pointer id fields live in the stdlib-only `lab.core.ids` for that reason."""
    import ast, inspect
    from lab.platform import contracts
    from lab.core.ids import POINTER_ID_FIELDS
    tree = ast.parse(inspect.getsource(contracts))
    top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    names = [getattr(n, "module", None) or "" for n in top] + [a.name for n in top if isinstance(n, ast.Import) for a in n.names]
    assert not any(m.startswith("lab.core.semantic") for m in names), names
    assert contracts.POINTER_ID_FIELDS is POINTER_ID_FIELDS
