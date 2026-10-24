"""contracts/modelling.json is what SAF vendors verbatim (M-6). These hold it to the code that emits it.

Exactness is right here, as in `test_contracts_match_servers`: the contract and the builder must agree in
both directions, and drift either way is the defect.
"""
import json
import os

import jsonschema
from referencing import Registry, Resource

from lab.core.modelling import envelope
from lab.core.modelling.provenance import LOCATION_KEYS, Source

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load(name):
    with open(os.path.join(ROOT, "contracts", name), encoding="utf-8") as f:
        return json.load(f)


MODELLING = _load("modelling.json")
SPEC = _load("archimate-spec.schema.json")
DEFS = MODELLING["$defs"]
REF_DEFS = {"capabilities": "capability_ref", "realisations": "realisation_ref",
            "repository": "repository_ref", "concepts": "concept_ref"}


def _validator(defn=None):
    registry = Registry().with_resources([(SPEC["$id"], Resource.from_contents(SPEC)),
                                          (MODELLING["$id"], Resource.from_contents(MODELLING))])
    schema = {"$ref": f'{MODELLING["$id"]}#/$defs/{defn}'} if defn else MODELLING
    return jsonschema.Draft202012Validator(schema, registry=registry)


def test_the_contract_is_a_valid_schema_at_the_code_s_version():
    jsonschema.Draft202012Validator.check_schema(MODELLING)
    assert MODELLING["version"] == envelope.CONTRACT_VERSION
    assert MODELLING["$id"].endswith(f":{envelope.CONTRACT_VERSION}")
    assert MODELLING["properties"]["contract_version"] == {"const": envelope.CONTRACT_VERSION}


def test_the_spec_slot_is_the_fr11_schema_by_reference():
    assert MODELLING["properties"]["spec"] == {"$ref": SPEC["$id"]}


def test_the_builder_s_whitelists_match_the_fr11_schema():
    assert set(envelope.SPEC_KEYS) == set(SPEC["properties"])
    assert set(envelope.ELEMENT_KEYS) == set(SPEC["$defs"]["element"]["properties"])
    assert set(envelope.RELATION_KEYS) == set(SPEC["$defs"]["relation"]["properties"])


def test_vocabularies_match_the_code():
    assert set(DEFS["location"]["properties"]) == set(LOCATION_KEYS)
    assert DEFS["change"]["enum"] == list(envelope.CHANGES)
    assert DEFS["status"]["enum"] == list(envelope.STATUSES)
    assert set(DEFS["open_question"]["properties"]["kind"]["enum"]) == set(envelope.QUESTION_KINDS)
    assert DEFS["review_decision"]["properties"]["state"]["enum"] == list(envelope.REVIEW_STATES)
    assert set(DEFS["review_decision"]["properties"]) == set(envelope.REVIEW_KEYS)


def test_every_reference_kind_is_published_with_the_fields_and_statuses_the_code_keeps():
    assert set(MODELLING["properties"]["references"]["properties"]) == set(envelope.REFERENCE_KINDS)
    for kind, rk in envelope.REFERENCE_KINDS.items():
        d = DEFS[REF_DEFS[kind]]["properties"]
        assert set(d) == set(rk.keys), kind
        status = d[rk.status_field]
        allowed = status.get("enum") or DEFS[status["$ref"].rsplit("/", 1)[-1]]["enum"]
        assert list(allowed) == list(rk.statuses), kind


def test_every_envelope_key_the_builder_emits_is_declared_and_required():
    env = envelope.build(spec={"name": "m"}, provenance={}, sources=[])
    assert set(env) == set(MODELLING["properties"]) == set(MODELLING["required"])


def test_the_published_id_prefixes_satisfy_the_id_rule():
    for prefix in MODELLING["x-id-prefixes"]:
        assert envelope.ID_PATTERN.fullmatch(prefix.rstrip("-") + "-x"), prefix


def test_a_full_envelope_validates_against_the_contract():
    spec = {"name": "m", "elements": [{"id": "ba-x", "type": "BusinessActor", "name": "X",
                                       "props": {"k": "v"}},
                                      {"id": "svc-knw-11", "type": "ApplicationService", "name": "Y"}],
            "relations": [{"id": "r-1", "type": "Serving", "src": "svc-knw-11", "tgt": "ba-x"}],
            "dropped": [], "gaps": []}
    prov = [{"source_ref": "art://a/b.md", "location": {"page": 1}, "quote": "X uses Y"}]
    env = envelope.build(
        spec=spec, provenance={"elements": {"ba-x": prov}, "relations": {"r-1": prov}},
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
