"""A workload's side of the corpus: pin once, read under it, say what moved."""
import asyncio

import pytest

from fixtures.usecase_corpus import tools
from fixtures.workflow import Router
from lab.workloads import gateway
from lab.workloads.usecase import reference


def _cfg(router, run_id="run-1"):
    return {"headers": {}, "mcp_url": "http://gw/mcp", "run_id": run_id,
            "process": "use_case_design"}


@pytest.fixture
def corpus(monkeypatch):
    router = Router(tools(), full=True)
    monkeypatch.setattr(gateway, "Client", router.client_class())
    return router


def test_a_pin_freezes_exactly_the_artifacts_asked_for_and_lands_on_the_run_board(corpus, monkeypatch):
    noted = {}
    monkeypatch.setattr(reference.runlog, "update", lambda rid, **f: noted.update({rid: f}))
    pinned = asyncio.run(reference.pin(_cfg(corpus), ["guardrails", "facet-schema"]))
    assert corpus.called("reference_pin") == [{"artifact_ids": ["guardrails", "facet-schema"]}]
    assert {v["artifact_id"] for v in pinned["versions"]} == {"guardrails", "facet-schema"}
    assert noted["run-1"]["pin_id"] == pinned["pin_id"]


def test_drift_names_every_artifact_whose_version_moved_and_nothing_else():
    before = [{"artifact_id": "guardrails", "version": "v0.26"},
              {"artifact_id": "facet-schema", "version": "v0.26"},
              {"artifact_id": "only-before", "version": "v0.26"}]
    after = [{"artifact_id": "guardrails", "version": "v0.27"},
             {"artifact_id": "facet-schema", "version": "v0.26"},
             {"artifact_id": "only-after", "version": "v0.27"}]
    assert reference.drift(before, after) == [
        {"artifact_id": "guardrails", "before": "v0.26", "after": "v0.27"}]


def test_a_pin_records_the_drift_against_what_an_earlier_run_cited(corpus):
    pinned = asyncio.run(reference.pin(
        _cfg(corpus, run_id=""), ["guardrails"],
        previous=[{"artifact_id": "guardrails", "version": "v0.26"}]))
    assert pinned["drift"] == [{"artifact_id": "guardrails", "before": "v0.26", "after": "v0.27"}]


def test_a_read_is_attributed_to_the_derived_field_and_comes_back_as_the_domain_s_rows(corpus):
    rows = asyncio.run(reference.records(_cfg(corpus), "pin-test", "guardrails",
                                         record_type="guardrail", field="obligations"))
    call = corpus.called("reference_lookup")[0]
    assert call["field"] == "obligations" and call["process"] == "use_case_design"
    assert call["run_id"] == "run-1" and call["artifact_id"] == "guardrails"
    assert rows and "id" in rows[0] and "record_id" not in rows[0]
    assert isinstance(rows[0].get("src", []), list), "a declared list column decodes as a list"


def test_a_run_with_no_id_is_still_attributed_as_what_it_is(corpus):
    assert reference.attribution({"process": "p"}, "f") == {"run_id": "local", "process": "p",
                                                             "field": "f"}


def test_a_read_the_server_had_to_cut_at_the_limit_is_refused_rather_than_matched_over(monkeypatch):
    """The surviving subset is ordered by a content hash — a coverage map over a random two thirds
    of the map would look exactly like a whole one."""
    many = {"reference_lookup": lambda a: {"records": [{"record_id": f"r{i}", "key": {}, "body": {"id": f"L{i}"}}
                                                       for i in range(20)], "matched": 20}}
    router = Router(many, full=True)
    monkeypatch.setattr(gateway, "Client", router.client_class())
    with pytest.raises(RuntimeError) as e:
        asyncio.run(reference.records(_cfg(router), "pin-test", "capability-map",
                                      record_type="capability", field="coverage_map", limit=20))
    assert "limit" in str(e.value)
