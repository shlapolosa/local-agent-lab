"""contracts/modelling.json is what SAF vendors verbatim (M-6), GENERATED from lab.core.modelling.

The file is held to the generator byte for byte; the rest pins what generation alone cannot: that it
carries the FR-11 spec unchanged, and that the builder's OUTPUT validates against it for any input.
"""
import json
import os

import jsonschema
from referencing import Registry, Resource

from lab.core.archimate import ids
from lab.core.modelling import contract, envelope
from lab.core.modelling.provenance import Source

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load(name):
    with open(os.path.join(ROOT, "contracts", name), encoding="utf-8") as f:
        return f.read()


MODELLING_TEXT = _load("modelling.json")
MODELLING = json.loads(MODELLING_TEXT)
SPEC = json.loads(_load("archimate-spec.schema.json"))


def _validator(defn=None):
    registry = Registry().with_resources([(SPEC["$id"], Resource.from_contents(SPEC)),
                                          (MODELLING["$id"], Resource.from_contents(MODELLING))])
    schema = {"$ref": f'{MODELLING["$id"]}#/$defs/{defn}'} if defn else MODELLING
    return jsonschema.Draft202012Validator(schema, registry=registry)


def test_the_committed_contract_is_what_the_code_generates():
    assert MODELLING_TEXT == contract.dumps(contract.schema()), (
        "contracts/modelling.json is stale: run PYTHONPATH=src .venv/bin/python "
        "scripts/render_modelling_contract.py, bump envelope.CONTRACT_VERSION if the shape changed, "
        "and tell SAF")


def test_the_contract_is_a_valid_schema_carrying_the_fr11_spec_by_reference():
    jsonschema.Draft202012Validator.check_schema(MODELLING)
    assert MODELLING["properties"]["spec"] == {"$ref": SPEC["$id"]} and contract.SPEC_ID == SPEC["$id"]


def test_the_builder_s_whitelists_match_the_fr11_schema():
    assert set(envelope.SPEC_KEYS) == set(SPEC["properties"])
    assert set(envelope.ELEMENT_KEYS) == set(SPEC["$defs"]["element"]["properties"])
    assert set(envelope.RELATION_KEYS) == set(SPEC["$defs"]["relation"]["properties"])


def test_every_published_prefix_satisfies_the_id_rule_and_the_type_table_is_complete():
    for prefix in MODELLING["x-id-prefixes"]:
        assert envelope.ID_PATTERN.fullmatch(prefix.rstrip("-") + "-x"), prefix
    assert set(ids.PREFIXES.values()) <= set(MODELLING["x-id-prefixes"])


def test_every_envelope_key_the_builder_emits_is_declared_and_required():
    env = envelope.build(spec={"name": "m"}, provenance={}, sources=[])
    assert set(env) == set(MODELLING["properties"]) == set(MODELLING["required"])


def test_a_full_envelope_validates_against_the_contract():
    spec = {"name": "m", "elements": [{"id": "ba-x", "type": "BusinessActor", "name": "X",
                                       "props": {"k": "v"}},
                                      {"id": "svc-knw-11", "type": "ApplicationService", "name": "Y"}],
            "relations": [{"id": ids.rid("svc-knw-11", "Serving", "ba-x"), "type": "Serving",
                           "src": "svc-knw-11", "tgt": "ba-x"}],
            "dropped": [], "gaps": []}
    r = spec["relations"][0]["id"]
    prov = [{"source_ref": "art://a/b.md", "location": {"page": 1}, "quote": "X uses Y"}]
    env = envelope.build(
        spec=spec, provenance={"elements": {"ba-x": prov}, "relations": {r: prov}},
        sources=[Source(ref="art://a/b.md", name="b.md", media_type="text/markdown", text="X uses Y")],
        questions=[{"text": "who owns Y?", "refs": {"elements": ["svc-knw-11"]}}],
        references={
            "capabilities": [{"element_id": "svc-knw-11", "map": "m", "map_version": "1",
                              "capability_id": "KNW.11", "label": "Y", "level": 3, "status": "new",
                              "confidence": "high"},
                             {"element_id": "", "map": "m", "capability_id": "KNW.12",
                              "status": "missing"}],
            "realisations": [{"element_id": "svc-knw-11", "capability_id": "KNW.11",
                              "realised_by": "Z", "catalogue_id": "cmp-1", "status": "consumed"}],
            "repository": [{"element_id": "ba-x", "repository_id": "o-1", "repository_class": "C_X",
                            "match": "updated", "confidence": "high", "candidates": []}],
            "concepts": [{"element_id": "ba-x", "concept_iri": "urn:fabric:concept:x", "label": "X",
                          "scheme": "cafe", "status": "linked"}]},
        changes={"ba-x": "updated", "svc-knw-11": "new"},
        renamed_from={"ba-x": ["ba-old-x"]},
        reviews=[{"item_kind": "element", "item_id": "ba-old-x", "state": "corrected",
                  "actor": "ea@tenant", "note": "a role", "correction": {"type": "BusinessRole"}}])
    _validator().validate(env)
    assert env["reviews"][0]["item_id"] == "ba-x"
    assert {q["kind"] for q in env["open_questions"]} == {"no-provenance", "raised"}


def test_the_contract_carries_the_agent_s_schema_and_prompt_so_a_vendor_sees_every_change():
    """1.3.0, confirmed by SAF: one vendored file is everything a channel mirrors. The prompt is inline
    AND hashed, so a channel's build can check the text it was given."""
    import hashlib
    from lab.core.modelling import agent_schema
    agent = MODELLING["x-agent"]
    assert agent["schema"] == agent_schema.schema()
    assert agent["prompt"] == agent_schema.prompt()
    assert agent["prompt_sha256"] == hashlib.sha256(agent["prompt"].encode("utf-8")).hexdigest()
    with open(os.path.join(ROOT, agent["prompt_path"]), "rb") as f:
        assert hashlib.sha256(f.read()).hexdigest() == agent["prompt_sha256"]


def test_the_paragraph_goldens_are_what_the_code_extracts_and_splits():
    """1.4.0, agreed with SAF: a channel reading Word through another library proves its split matches
    ours against these files, so they must be exactly what the lab produces."""
    import glob
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "render_modelling_contract", os.path.join(ROOT, "scripts", "render_modelling_contract.py"))
    render = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(render)
    sources = sorted(glob.glob(os.path.join(ROOT, "contracts", "goldens", "paragraphs", "*", "source.*")))
    assert {os.path.basename(os.path.dirname(s)) for s in sources} >= {"design-docx", "synthetic", "markdown"}
    for source in sources:
        text, split = render.golden(source)
        folder = os.path.dirname(source)
        with open(os.path.join(folder, "extracted.txt"), encoding="utf-8", newline="") as f:
            assert f.read() == text, f"{folder}: re-render the goldens"
        with open(os.path.join(folder, "paragraphs.json"), encoding="utf-8", newline="") as f:
            assert f.read() == split, f"{folder}: re-render the goldens"


def test_the_published_paragraph_rule_is_the_code_s():
    from lab.core.modelling import paragraphs
    rule = MODELLING["x-paragraph-rule"]
    assert rule["by_media_type"] == paragraphs.PARAGRAPH_RULES and rule["default"] == paragraphs.DEFAULT_RULE
    assert rule["pdf_page_separator"] == paragraphs.PDF_PAGE_SEPARATOR == "\f"


def test_a_review_decision_shape_is_published_for_the_d8_gate():
    _validator("review_decision").validate(
        {"item_kind": "element", "item_id": "ba-x", "state": "corrected", "actor": "ea@tenant",
         "note": "it is a role", "correction": {"type": "BusinessRole"}})
