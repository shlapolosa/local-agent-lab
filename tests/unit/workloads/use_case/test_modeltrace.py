"""The throwaway per-step trace: silent when off, best-effort when on, never the run."""
import asyncio

import pytest

from lab.platform import config
from lab.platform.contracts import EATools, SemanticTools
from lab.workloads.usecase import modelling, modeltrace
from lab.workloads.usecase.derivation import Derivation


class _Gateway:
    def __init__(self, fail_render=False):
        self.calls, self.fail_render = [], fail_render

    async def call(self, cfg, tool, args):
        self.calls.append((tool, args))
        if tool == SemanticTools.store_spec:
            return {"spec_ref": "art://t/" + args["name"]}
        if self.fail_render:
            raise RuntimeError("render died")
        return {"xml_ref": "art://t/x.xml", "svg_refs": {"delta": "art://t/d.svg"}, "violations": []}


def _grown(monkeypatch, gw, on=True):
    monkeypatch.setattr(config, "USECASE_MODEL_TRACE", on)
    monkeypatch.setattr(modeltrace.gateway, "call", gw.call)
    d = Derivation()
    d.record("frame", {"problem": "p", "for_whom": "GPs", "expected_change": "e", "accountable_owner": "Dr K"}, "3")
    asyncio.run(modelling.grow({}, d, "frame"))
    d.record("criticality_band", {"band": "routine"}, "7")
    asyncio.run(modelling.grow({}, d, "criticality_band"))
    return d


def test_off_by_default_means_no_tool_call_and_no_trace_key(monkeypatch):
    gw = _Gateway()
    d = _grown(monkeypatch, gw, on=False)
    assert gw.calls == [] and "model_trace" not in d.derived
    assert "model" in d.derived and "model_summary" in d.available, "the model itself still grows"


def test_on_it_stores_and_renders_the_delta_of_every_step_that_touched_the_model(monkeypatch):
    gw = _Gateway()
    d = _grown(monkeypatch, gw)
    assert [t for t, _ in gw.calls] == [SemanticTools.store_spec, EATools.render] * 2
    delta = gw.calls[0][1]["spec"]
    assert {e["id"] for e in delta["elements"]} >= {"usecase", "drv-problem", "stk-gps"}
    assert delta["views"][0]["id"] == "delta-frame" and gw.calls[1][1]["basename"] == "model.frame"
    trace = d.derived["model_trace"]
    assert trace["frame"]["svg_refs"] == {"delta": "art://t/d.svg"} and trace["frame"]["added"] > 0
    assert trace["criticality_band"]["added"] == 1, "the root's props changed — one touched id"


def test_a_render_failure_is_recorded_on_that_step_and_the_run_goes_on(monkeypatch):
    d = _grown(monkeypatch, _Gateway(fail_render=True))
    assert "render died" in d.derived["model_trace"]["frame"]["error"]
    assert d.derived["model"]["elements"], "the mapper's work is intact"


def test_tabs_are_labelled_by_step_number_in_run_order():
    record = {"model_trace": {"workflow_graph": {"svg_refs": {"delta": "art://a"}},
                              "frame": {"svg_refs": {"delta": "art://b"}},
                              "composition": {"svg_refs": {"delta": "art://c", "full": "art://d"}},
                              "risk": {"error": "x"}}}
    assert modeltrace.tabs(record) == {"3 frame": "art://b", "10 workflow_graph": "art://a",
                                       "22 composition · delta": "art://c", "22 composition · full": "art://d"}
    assert modeltrace.tabs({}) == {}


def test_the_trace_never_reaches_a_prompt():
    from lab.workloads.usecase import agents as A
    assert all("model_trace" not in ctx and "model" not in ctx for ctx in A.CONTEXT_FOR.values())
