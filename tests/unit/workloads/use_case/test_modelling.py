"""The one hook: the model is read from the right place, seeded before a step reads it, re-recorded."""
from lab.workloads.usecase import modelling
from lab.workloads.usecase.derivation import Derivation

CARRIED = {"name": "triage", "id": "usecase-model",
           "elements": [{"id": "bf-assess", "type": "BusinessFunction", "name": "assess", "folder": "Business"}],
           "relations": []}


def test_the_design_half_continues_the_screenings_model_from_the_pool():
    """The screening record is spread into `available`; this half's `derived` starts empty."""
    d = Derivation(available={"model": CARRIED})
    d.record("build_surface", {"surface": "Foundry hosted agent", "topology": "T2"}, "20")
    model = modelling.apply_mapper(d, "build_surface")
    assert model is not None and {"bf-assess", "node-foundry-hosted-agent"} <= set(model.elements)
    assert d.derived["model"] is not CARRIED and "node-foundry-hosted-agent" in str(d.derived["model"])
    assert d.available["model"] == d.derived["model"], "re-recorded: context to every later step"


def test_this_halfs_model_wins_over_the_carried_one_once_it_exists():
    d = Derivation(available={"model": CARRIED},
                   derived={"model": {"name": "later", "id": "usecase-model", "elements": [], "relations": []}})
    assert modelling.current(d).name == "later"


def test_ensure_seeds_the_summary_so_a_step_that_reads_it_is_not_deferred():
    d = Derivation(available={"model": CARRIED, "composition": {"families": ["F2"]}})
    assert "model_summary" not in d.available
    modelling.ensure(d)
    assert d.available["model_summary"]["required_families"] == ["F2"]
    assert d.available["model_summary"]["elements"]["BusinessFunction"] == [{"id": "bf-assess", "name": "assess"}]
    assert "model" in d.derived, "and the package will carry the model"
    before = dict(d.derived)
    modelling.ensure(d)
    assert d.derived == before, "idempotent"


def test_a_step_without_a_mapper_or_that_did_not_run_leaves_the_model_alone():
    d = Derivation(available={"model": CARRIED})
    assert modelling.apply_mapper(d, "benefit_inputs") is None
    assert modelling.apply_mapper(d, "frame") is None, "frame never ran"
    assert "model" not in d.derived
