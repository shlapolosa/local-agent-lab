"""The CAFÉ projection: ours only, placed by zone, nothing guessed, nothing inlined."""
import pytest

from lab.substrate.mcp.semantic import cafe


def _spec(**over):
    spec = {"name": "Referral triage", "id": "usecase",
            "elements": [
                {"id": "usecase", "type": "Grouping", "name": "Referral triage",
                 "props": {"cafe.archetype": "A2", "cafe.topology": "T2"}},
                {"id": "ac-cmp-model", "type": "ApplicationComponent", "name": "Foundry model catalog",
                 "doc": "SECRET documentation text", "props": {"cafe.zone": "mod", "cafe.families": "F2"}},
                {"id": "ac-cmp-apim", "type": "ApplicationComponent", "name": "API Management",
                 "props": {"cafe.zone": "gw"}},
                {"id": "ac-cerner", "type": "ApplicationComponent", "name": "Cerner",
                 "props": {"existing": True}},
                {"id": "bf-assess", "type": "BusinessFunction", "name": "assess referral"}],
            "relations": [
                {"id": "r1", "type": "Serving", "src": "ac-cmp-apim", "tgt": "ac-cmp-model"},
                {"id": "r2", "type": "Serving", "src": "ac-cmp-model", "tgt": "bf-assess"},
                {"id": "r3", "type": "Access", "src": "ac-cmp-model", "tgt": "ac-cerner"}]}
    return spec | over


def test_ours_only_placed_by_zone_with_the_gateway_as_the_edge():
    solution, report = cafe.solution_spec(_spec())
    assert solution["include_comps"] == ["none"] and solution["base_archetype"] == "A2"
    by_cid = {c["cid"]: c for c in solution["custom_comps"]}
    assert by_cid["c_ac_cmp_model"]["zone"] == "z_mod" and by_cid["c_ac_cmp_model"]["desc"] == "F2"
    assert by_cid["c_ac_cmp_apim"]["zone"] == "z_edge", "the corpus's gw zone is the skill's edge"
    assert all(c["kind"] == "m4-extension" for c in solution["custom_comps"])
    assert report["placed"] == ["ac-cmp-apim", "ac-cmp-model"] and report["unplaced"] == ["ac-cerner"]


def test_edges_are_drawn_only_between_two_placed_components():
    solution, _ = cafe.solution_spec(_spec())
    assert solution["edges"] == [{"from": "c_ac_cmp_apim", "to": "c_ac_cmp_model", "kind": "request"}]


def test_no_documentation_text_reaches_the_drawing():
    solution, _ = cafe.solution_spec(_spec())
    assert "SECRET" not in str(solution)


def test_a_model_without_an_archetype_is_refused_by_name():
    spec = _spec()
    spec["elements"][0] = {"id": "usecase", "type": "Grouping", "name": "x"}
    with pytest.raises(ValueError, match="cafe.archetype"):
        cafe.solution_spec(spec)


def test_an_unknown_zone_is_reported_not_guessed():
    spec = _spec()
    spec["elements"][1]["props"]["cafe.zone"] = "nowhere"
    _, report = cafe.solution_spec(spec)
    assert "ac-cmp-model" in report["unplaced"]


def test_every_corpus_zone_maps_onto_a_zone_the_skill_draws():
    assert set(cafe.ZONE_IDS) >= {"exp", "gw", "cog", "knw", "mod", "too", "data", "ext", "ident", "obs", "plat"}


def test_render_produces_a_drawio_file_and_an_svg_preview():
    out = cafe.render(_spec())
    assert out["drawio"].startswith("<mxfile") or "<mxGraphModel" in out["drawio"]
    assert out["svg"].lstrip().startswith("<svg") or "<svg" in out["svg"][:200]
    assert "Foundry model catalog" in out["drawio"] and out["placed"] == ["ac-cmp-apim", "ac-cmp-model"]
    assert any("m4-extension" in w or "M4 extension" in w for w in out["warnings"])


def test_the_frozen_zone_table_matches_the_engines_own():
    drawio_cafe, _ = cafe.engine()
    engine_zones = {z[0] for z in [drawio_cafe.TOP_RAIL, *drawio_cafe.ZONES, drawio_cafe.BOTTOM_RAIL,
                                   drawio_cafe.PLAT_ZONE]}
    assert set(cafe.ZONE_IDS.values()) == engine_zones


def test_a_missing_skill_fails_the_one_tool_by_name_not_the_import(monkeypatch, tmp_path):
    """The engine is imported on first use, so semantic-mcp starts (and serves its other ~25 tools)
    with the skill directory absent; the draw call is what refuses."""
    import sys
    from lab.platform import config
    monkeypatch.setattr(config, "SKILLS_DIR", tmp_path)
    # An earlier test may have imported the real engine: forget the modules AND the real path.
    monkeypatch.setattr(sys, "path", [p for p in sys.path if "drawio-cafe" not in p])
    for name in ("drawio_cafe", "drawio_cafe_svg", "drawio_c4"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    cafe.engine.cache_clear()
    try:
        solution, _ = cafe.solution_spec(_spec())            # the pure half needs no engine
        assert solution["base_archetype"] == "A2"
        with pytest.raises(RuntimeError, match="drawio-cafe skill is not importable"):
            cafe.render(_spec())
    finally:
        cafe.engine.cache_clear()


def test_a_component_the_reference_architecture_carries_keeps_its_catalogue_id_and_its_edges():
    """Our corpus components were extracted from the same artifact the skill draws, so a canonical
    id is what lets the published edges between two selected components be drawn (run 5: fifteen
    tiles and no lines, because every id was minted)."""
    spec = _spec()
    spec["elements"][1]["name"] = "APIM — AI Gateway"
    spec["elements"][2]["name"] = "Microsoft Entra ID"
    spec["elements"][2]["props"]["cafe.zone"] = "ident"
    solution, report = cafe.solution_spec(spec, cafe.catalogue())
    by_name = {c["title"]: c for c in solution["custom_comps"]}
    assert by_name["APIM — AI Gateway"]["cid"] == "c_apim"
    assert by_name["APIM — AI Gateway"]["kind"] == "boundary", "a catalogue component is no extension"
    assert report["catalogued"] == 2
    # (the engine renames cids to internal ids in banded mode, so the EDGE COUNT is the evidence)
    assert cafe.render(spec)["edges"] >= 1


def test_a_component_the_catalogue_does_not_carry_keeps_a_minted_id_and_is_flagged():
    spec = _spec()
    spec["elements"][1]["name"] = "Referral triage engine"          # nothing like it in the catalogue
    solution, report = cafe.solution_spec(spec, cafe.catalogue())
    minted = [c for c in solution["custom_comps"] if c["cid"].startswith("c_ac_")]
    assert minted and all(c["kind"] == "m4-extension" for c in minted)
    assert any(c["title"] == "Referral triage engine" for c in minted)


def test_a_view_of_tiles_with_no_connection_says_so_rather_than_passing_as_an_architecture():
    spec = _spec()
    for e in spec["elements"]:
        if e["type"] == "ApplicationComponent" and (e.get("props") or {}).get("cafe.zone"):
            e["name"] = "Referral " + e["id"]                        # nothing the catalogue connects
    spec["relations"] = []                                           # and nothing our own model asserts
    out = cafe.render(spec)
    assert out["edges"] == 0
    assert any("no connections drawn" in w for w in out["warnings"])
