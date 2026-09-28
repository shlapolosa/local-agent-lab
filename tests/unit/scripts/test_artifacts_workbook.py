"""The workbook the team edits, and the master it turns back into.

The team asked for a spreadsheet and that is what they get — but the workbook is an EXCHANGE
format, never the source. DR-02 requires the human-readable master and the agent-readable form to
be the same artifact at the same version (`derived_from = master_sha256`), and that link is only
true if the derivation actually happens. So the round trip is: master -> workbook -> master, and
what the publisher hashes is the REGENERATED master. A workbook that cannot be turned back into
the master it came from is refused here rather than discovered at publish.
"""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("artifacts_workbook",
                                              ROOT / "scripts" / "artifacts_workbook.py")
wb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wb)

from lab.core.reference import master  # noqa: E402

SAMPLE = """# Criticality taxonomy

**Artifact:** criticality_taxonomy
**Source:** CAFE_Artifacts_Visualisation_v0_25.html

| Class | Dominant failure | Rigor it sets |
|---|---|---|
| Routine | Someone is inconvenienced | Standard harness |
| Business-critical | Financial loss | Golden dataset; named owner |
"""


def test_a_sheet_carries_the_schema_a_reader_needs_before_the_values():
    """A column of values with no schema is a column somebody guesses at. The record type, the key
    fields and the owner are what say which column identifies a row and who may change it."""
    rows = wb.sheet_rows("criticality-taxonomy", master.parse(SAMPLE),
                         ("class", "Class", "risk"))
    flat = [str(c) for row in rows for c in row]
    assert "criticality-taxonomy" in flat and "class" in flat and "risk" in flat
    assert "Class" in flat, "the key field must be named, not merely be a column"
    assert "Routine" in flat and "Business-critical" in flat


def test_the_table_header_row_is_the_master_s_own_headers():
    rows = wb.sheet_rows("criticality-taxonomy", master.parse(SAMPLE), ("class", "Class", "risk"))
    assert ["Class", "Dominant failure", "Rigor it sets"] in [list(map(str, r)) for r in rows]


def test_a_workbook_round_trips_to_the_master_it_came_from(tmp_path):
    """The whole justification for accepting a spreadsheet: what publishes is a REGENERATED master,
    byte-identical in content to a master parsed from the workbook. If this ever fails, the
    workbook has become a second source of truth and DR-02 no longer holds."""
    parsed = master.parse(SAMPLE)
    path = tmp_path / "artifacts.xlsx"
    wb.export({"criticality-taxonomy": (parsed, ("class", "Class", "risk"))}, path)
    back = wb.read_sheet(path, "criticality-taxonomy")
    assert back.headers == parsed.headers
    assert back.rows == parsed.rows
    assert back.meta.get("Artifact") == parsed.meta.get("Artifact")


def test_a_sheet_whose_header_row_was_edited_is_refused(tmp_path):
    """Renaming a column silently changes what `key_fields` points at, and a record keyed on a
    column that no longer exists is one the publisher cannot match to its predecessor."""
    parsed = master.parse(SAMPLE)
    path = tmp_path / "a.xlsx"
    wb.export({"criticality-taxonomy": (parsed, ("class", "Class", "risk"))}, path)
    import openpyxl
    book = openpyxl.load_workbook(path)
    sheet = book["criticality-taxonomy"]
    header_at = wb.header_row_index(sheet)
    sheet.cell(row=header_at, column=1, value="Klass")
    book.save(path)
    with pytest.raises(wb.WorkbookError, match="key field"):
        wb.read_sheet(path, "criticality-taxonomy", key_fields=("Class",))


def test_an_index_sheet_lists_every_artifact_so_the_team_can_see_the_whole_ask(tmp_path):
    path = tmp_path / "a.xlsx"
    wb.export({"criticality-taxonomy": (master.parse(SAMPLE), ("class", "Class", "risk"))}, path)
    import openpyxl
    book = openpyxl.load_workbook(path)
    assert wb.INDEX in book.sheetnames
    flat = [str(c.value) for row in book[wb.INDEX].iter_rows() for c in row]
    assert "criticality-taxonomy" in flat and "risk" in flat


COLLIDING = """# Input artifacts

**Artifact:** input_artifacts

| Artifact | Owner | Consumed at |
|---|---|---|
| Business capability map | Enterprise architecture | Match capabilities |
"""


def test_a_table_whose_first_column_is_named_like_a_schema_label_still_round_trips(tmp_path):
    """Four of the 53 real artifacts head their table with `Artifact` or `Owner` — the same words
    the schema block uses as labels. Locating the header row by "first row that is not a label"
    therefore skipped it and read the first DATA row as headers, and the import refused them.

    The separator is what is reliable: `export` writes exactly one blank row between the schema
    block and the table, so the header is the first non-empty row after it. No guessing at names.
    """
    parsed = master.parse(COLLIDING)
    path = tmp_path / "a.xlsx"
    wb.export({"input-artifacts": (parsed, ("artifact", "Artifact", "EA"))}, path)
    back = wb.read_sheet(path, "input-artifacts", key_fields=("Artifact",))
    assert back.headers == ("Artifact", "Owner", "Consumed at")
    assert back.rows == parsed.rows


UNNAMED_FIRST = """# Risk derivation

**Artifact:** risk_derivation
**Source:** CAFE_Artifacts_Visualisation_v0_25.html
**Section:** properties

|  | Exposure | Influence |
|---|---|---|
| Question | How bad is it when this step works? | How bad is it when this step is wrong? |
"""


def test_an_unnamed_first_column_survives_the_round_trip(tmp_path):
    """Two of the 53 masters lead with an unnamed column. Reading headers as "cells that have a
    value" dropped it, shifted every row one to the left and silently lost the last column — the
    kind of corruption that still looks like a table."""
    parsed = master.parse(UNNAMED_FIRST)
    assert parsed.headers[0] == "", "the fixture must really have an unnamed first column"
    path = tmp_path / "a.xlsx"
    wb.export({"risk-derivation": (parsed, ("property", "Exposure", "risk"))}, path)
    back = wb.read_sheet(path, "risk-derivation")
    assert back.headers == parsed.headers
    assert back.rows == parsed.rows


def test_the_master_s_whole_meta_block_survives_not_just_its_name(tmp_path):
    """`Section` is what keys the derived JSON and `Source` is the artifact's provenance. Carrying
    only `Artifact` would have published records under the wrong key and lost where they came
    from."""
    parsed = master.parse(UNNAMED_FIRST)
    path = tmp_path / "a.xlsx"
    wb.export({"risk-derivation": (parsed, ("property", "Exposure", "risk"))}, path)
    back = wb.read_sheet(path, "risk-derivation")
    assert back.meta.get("Section") == "properties"
    assert back.meta.get("Source") == "CAFE_Artifacts_Visualisation_v0_25.html"
    assert "Record type" not in back.meta, "the catalogue rows are ours, not the master's"


# ------------------------------------------------- how each artifact is meant to be READ

def test_the_retrieval_mode_is_computed_the_way_the_publisher_computes_it():
    """`whole`, `key` and `vector` are not cosmetic: they change what good content IS. A `whole`
    register is read in full, so every row must earn its place and "the relevant rows" would
    silently drop a rule. A `key` artifact is read by exact natural key, so that key must be
    unique and stable. A `vector` artifact is searched for relevance, so its text has to be worth
    embedding — prose, not a code.

    Computed rather than restated: declared modes come from the publisher's own RETRIEVAL table,
    and an artifact that declares nothing takes the kind's default (prose can only be searched; a
    record keeps its exact read). A second hand-maintained copy would drift from the thing that
    actually publishes."""
    assert wb.retrieval_for("criticality-taxonomy", "class") == "whole"     # declared
    assert wb.retrieval_for("ai-capability-map", "capability") == "whole"   # declared
    assert wb.retrieval_for("guardrails", "guardrail") == "key"             # record default
    assert wb.retrieval_for("some-prose-artifact", "") == "vector"          # prose default


def test_every_mode_carries_the_guidance_that_makes_it_actionable():
    """A mode a reader cannot act on is a label. The team is being asked to WRITE these, so each
    mode says what it means for the content."""
    for mode in ("whole", "key", "vector"):
        assert wb.RETRIEVAL_NOTE[mode] and len(wb.RETRIEVAL_NOTE[mode]) > 40


def test_the_sheet_and_the_index_both_say_how_the_artifact_is_read(tmp_path):
    parsed = master.parse(SAMPLE)
    path = tmp_path / "a.xlsx"
    wb.export({"criticality-taxonomy": (parsed, ("class", "Class", "risk"))}, path)
    import openpyxl
    book = openpyxl.load_workbook(path)
    sheet_cells = [str(c.value) for row in book["criticality-taxonomy"].iter_rows() for c in row]
    assert "whole" in sheet_cells
    assert any(wb.RETRIEVAL_NOTE["whole"][:30] in str(c) for c in sheet_cells), "guidance too"
    index_cells = [str(c.value) for row in book[wb.INDEX].iter_rows() for c in row]
    assert "whole" in index_cells


def test_the_read_mode_is_ours_and_never_becomes_part_of_the_master(tmp_path):
    """It is catalogue metadata, not artifact content. Writing it into the master's meta block
    would publish a field the publisher did not put there."""
    parsed = master.parse(SAMPLE)
    path = tmp_path / "a.xlsx"
    wb.export({"criticality-taxonomy": (parsed, ("class", "Class", "risk"))}, path)
    back = wb.read_sheet(path, "criticality-taxonomy")
    assert "Read as" not in back.meta and back.meta == parsed.meta


# ------------------------------------------------------- which step reads it, and the tab name

def test_a_sheet_is_named_for_the_step_that_reads_it():
    """`step-16-ai-capability-map` sorts and reads as the process does. The artifact name alone
    made a reader match names against a 27-step framework in their head."""
    assert wb.sheet_name("AI capability map", "16, 21") == "step-16-ai-capability-map"


def test_a_sheet_name_stays_inside_excel_s_limit():
    """Excel refuses a name over 31 characters; the index carries the full name either way."""
    name = wb.sheet_name("Reference architecture model", "22")
    assert len(name) <= 31 and name.startswith("step-22-")


def test_an_artifact_no_step_consumes_is_named_without_a_step():
    assert wb.sheet_name("Risk register", "") == "risk-register"


def test_a_step_with_a_decimal_keeps_it():
    """Steps 23 and 24 are compositions and the register cites their sub-steps (23.5, 24.6)."""
    assert wb.sheet_name("Role rate registry", "24.2").startswith("step-24.2-")


def test_the_business_and_technology_maps_are_BOTH_primary_and_realise_their_own_levels():
    """Superseded 28 Sep 2026 — the CAFÉ bundle is the source of truth, and it restores the business
    capability map as the ENTERPRISE-architecture map the early steps read (3, then 5 and 14),
    while the TECHNOLOGY map is what step 5 matches against from there on. It had been recorded
    here as retired, with step 5 matching the AI realisation view; that view is now step 6's."""
    inputs = wb.primary_map()["inputs"]
    business = inputs["Business capability map"]["corpus"]
    technology = inputs["Technology capability map"]["corpus"]
    assert {"business-capability-l1", "business-capability-l2", "business-capability-l3"} <= set(business)
    assert {"technology-capability-l1", "technology-capability-l2",
            "technology-capability-l3"} <= set(technology)
    assert "ai-capability-map" in inputs["AI capability map — realisation view"]["corpus"]


# ------------------------------------------- the PRIMARY registers, and full accounting

def test_every_register_row_is_accounted_for():
    """The docx register is the authority for what is primary. A row with no entry in the map is
    an artifact nobody decided about — and the decision that gets skipped is always the one for an
    artifact nobody is asking for yet."""
    register, mapping = wb.register(), wb.primary_map()
    named = {r[0] for r in register["inputs"]["rows"]}
    assert named - set(mapping["inputs"]) == set(), "register rows with no mapping"
    assert set(mapping["inputs"]) - named == set(), "mappings for rows the register does not have"


def test_every_published_artifact_is_either_primary_or_declared_framework():
    """The other direction. A published artifact in neither list is one that drifted in."""
    mapping = wb.primary_map()
    claimed = {c for v in mapping["inputs"].values() for c in v.get("corpus", ())}
    claimed |= {k for k in mapping["framework"] if not k.startswith("_")}
    assert set(wb.catalogue()) - claimed == set(), "published artifacts accounted for nowhere"


def test_a_primary_artifact_groups_its_sub_tables_under_one_sheet():
    """`Reference architecture model` is one artifact in the register and ten tables in the corpus.
    A sheet per table asked the team to review ten things that are one thing."""
    assert len(wb.primary_map()["inputs"]["Reference architecture model"]["corpus"]) > 1


def test_a_missing_artifact_with_a_declared_schema_is_offered_as_an_empty_table():
    """Six are missing but SPECIFIED — the fields are declared in the contract or, better, in the
    module that reads them. The team gets the columns and no rows."""
    entry = wb.primary_map()["inputs"]["Delegation of authority matrix"]
    assert entry["schema"] == ["limit", "authority"] and entry["schema_from"] == "code"


def test_a_missing_artifact_with_no_schema_gets_no_invented_columns():
    """An invented header is worse than an honest gap: the team would fill it in good faith and
    the result would not be readable by anything."""
    entry = wb.primary_map()["inputs"]["Historical delivery actuals"]
    assert not entry.get("corpus") and not entry.get("schema") and entry.get("note")


def test_a_grouped_sheet_still_round_trips_to_every_master_in_it(tmp_path):
    """Grouping sub-tables under one sheet made the sheet hold several tables — and very nearly
    made the exporter one-way, which would have abandoned the round trip that was the entire
    argument for accepting a spreadsheet. Each table is delimited by its own `— <artifact-id>`
    marker, so it splits back exactly."""
    out = tmp_path / "a.xlsx"
    wb.build_workbook(out)
    title = wb.sheet_name("Facet schema and defaults", "17, 18")
    back = wb.read_primary_sheet(out, title)
    assert set(back) == {"facet-schema", "facet-schema-defaults", "facet-schema-readers"}
    for artifact_id, parsed in back.items():
        original = wb.master.parse(wb.master_path(artifact_id).read_text())
        assert parsed.headers == original.headers, artifact_id
        assert parsed.rows == original.rows, artifact_id


def test_a_sheet_for_an_artifact_nobody_supplied_yields_no_master(tmp_path):
    """A declared schema with no rows is not a master. Writing one would publish an empty artifact
    over nothing, which reads downstream as 'the corpus says there are none'."""
    out = tmp_path / "a.xlsx"
    wb.build_workbook(out)
    step = dict((r[0], r[3]) for r in wb.register()["inputs"]["rows"])["Role rate registry"]
    assert wb.read_primary_sheet(out, wb.sheet_name("Role rate registry", step)) == {}


def test_a_row_whose_last_cell_is_legitimately_empty_keeps_it(tmp_path):
    """Trailing empties are trimmed on the HEADER row, to find the table's real width. Doing the
    same to a data row drops a cell the artifact declares and the row comes back one column short
    — it still parses, still looks like a table, and has quietly lost a value."""
    src = '''# T

**Artifact:** t

| A | B | C |
|---|---|---|
| one | two |  |
'''
    parsed = master.parse(src)
    assert parsed.rows[0] == ("one", "two", ""), "the fixture must really end empty"
    path = tmp_path / "a.xlsx"
    wb.export({"criticality-taxonomy": (parsed, ("t", "A", "x"))}, path)
    assert wb.read_sheet(path, "criticality-taxonomy").rows == parsed.rows


# ------------------------------------------------ reading a workbook the TEAM reorganised
def _book(path, sheets):
    """A workbook of `{title: [rows]}`, written as a person would lay it out."""
    import openpyxl
    book = openpyxl.Workbook()
    book.remove(book.active)
    for title, rows in sheets.items():
        sheet = book.create_sheet(title)
        for row in rows:
            sheet.append(list(row))
    book.save(path)
    return path


def _table(artifact_id, headers, *rows):
    return [[], [f"— {artifact_id}", f"The {artifact_id} table"], ["Read as", "whole: …"], [],
            list(headers),
            *[list(r) for r in rows]]


def test_a_table_is_found_by_ITS_MARKER_whatever_the_sheet_is_now_called(tmp_path):
    """The marker names the table; the sheet title is presentation. Measured 28 Sep 2026: the
    team's CAFÉ bundle moved the business capability map to step 3 and the AI capability map to
    step 6, and an importer that COMPUTED the sheet title from its own register refused both —
    while each table still carried the marker that says exactly which artifact it is."""
    path = _book(tmp_path / "a.xlsx", {
        "0. index": [["#", "Primary artifact"]],
        "step-99-renamed-by-the-team": [["Artifact", "X"],
                                        *_table("criticality-taxonomy", ("Class", "Rigor"),
                                                ("Routine", "Standard"))],
    })
    got = wb.read_all_tables(path)
    assert set(got) == {"criticality-taxonomy"}
    assert got["criticality-taxonomy"].rows == (("Routine", "Standard"),)


def test_one_table_shown_on_TWO_sheets_is_one_table_when_both_copies_agree(tmp_path):
    """The bundle shows `financial-formulas` under both the benefit library and the finance
    assumptions — the same table, offered where each reader looks for it."""
    body = _table("financial-formulas", ("Quantity", "Formula"), ("npv", "Σ …"))
    path = _book(tmp_path / "a.xlsx", {"0. index": [["#"]], "a": body, "b": body})
    assert set(wb.read_all_tables(path)) == {"financial-formulas"}


def test_two_DIFFERENT_copies_of_one_table_are_refused_rather_than_one_silently_winning(tmp_path):
    """Two edits to 'the same' table on two sheets is a conflict a person must resolve. Letting
    the later sheet win publishes whichever the workbook happened to list last."""
    path = _book(tmp_path / "a.xlsx", {
        "0. index": [["#"]],
        "a": _table("financial-formulas", ("Quantity", "Formula"), ("npv", "one")),
        "b": _table("financial-formulas", ("Quantity", "Formula"), ("npv", "two")),
    })
    with pytest.raises(wb.WorkbookError, match="financial-formulas"):
        wb.read_all_tables(path)


def test_the_index_sheet_is_never_read_as_a_table(tmp_path):
    path = _book(tmp_path / "a.xlsx", {"0. index": _table("criticality-taxonomy", ("Class",),
                                                         ("Routine",))})
    assert wb.read_all_tables(path) == {}


def test_an_imported_master_names_the_WORKBOOK_as_its_source_and_keeps_the_rest_of_its_meta(
        tmp_path, monkeypatch):
    """Keeping the old meta verbatim kept `Source: CAFE_Artifacts_Visualisation_v0_25.html` on rows
    that now came from somewhere else — a master that misstates its own provenance, which is the
    one thing DR-02's derivation link exists to make checkable. Everything else in the meta (a
    `Section`, say) is still the artifact's own and survives."""
    masters = tmp_path / "masters"
    masters.mkdir()
    (masters / "criticality_taxonomy.md").write_text(
        "# Criticality taxonomy\n\n**Artifact:** criticality_taxonomy\n"
        "**Source:** CAFE_Artifacts_Visualisation_v0_25.html\n**Section:** classes\n\n"
        "| Class | Rigor |\n|---|---|\n| Routine | Standard |\n")
    monkeypatch.setattr(wb, "master_path", lambda a: masters / f"{a.replace('-', '_')}.md")
    path = _book(tmp_path / "cafe-artifacts.xlsx", {
        "0. index": [["#"]],
        "s": _table("criticality-taxonomy", ("Class", "Rigor"), ("Routine", "Harness")),
    })
    assert wb.main(["import", str(path)]) == 0
    written = master.parse((masters / "criticality_taxonomy.md").read_text())
    assert written.rows == (("Routine", "Harness"),)
    assert written.meta["Source"] == "cafe-artifacts.xlsx"
    assert written.meta["Section"] == "classes", "the artifact's own meta must survive"


def test_a_NEW_master_takes_its_title_from_the_marker_not_its_id(tmp_path, monkeypatch):
    """The marker row is `— <id> | <title>`. Reading only the id headed every new master
    `# ontology-concepts` — and the title is what a citation opens."""
    masters = tmp_path / "masters"
    masters.mkdir()
    monkeypatch.setattr(wb, "master_path", lambda a: masters / f"{a.replace('-', '_')}.md")
    path = _book(tmp_path / "cafe-artifacts.xlsx", {
        "0. index": [["#"]],
        "s": _table("ontology-concepts", ("id", "name"), ("C1", "Patient")),
    })
    assert wb.main(["import", str(path)]) == 0
    written = master.parse((masters / "ontology_concepts.md").read_text())
    assert written.title == "The ontology-concepts table"
    assert written.meta["Artifact"] == "ontology_concepts"
    assert written.meta["Source"] == "cafe-artifacts.xlsx"


def test_a_table_nobody_CLASSIFIED_is_refused_never_written_into_the_public_tree(tmp_path,
                                                                                 monkeypatch):
    """Review finding F3, 28 Sep 2026: anything not listed PRIVATE was written under src/ — so the
    next bundle's new restricted table would land in this public repository by default, caught only
    if its text happened to name a source the tripwire knows. A table must be classified (public in
    `ARTIFACTS`, or `PRIVATE`) before it can be imported at all."""
    masters = tmp_path / "masters"
    masters.mkdir()
    monkeypatch.setattr(wb, "master_path", lambda a: masters / f"{a.replace('-', '_')}.md")
    path = _book(tmp_path / "cafe-artifacts.xlsx", {
        "0. index": [["#"]],
        "s": _table("never-seen-before", ("id", "x"), ("A1", "restricted-looking content")),
    })
    assert wb.main(["import", str(path)]) == 1
    assert not list(masters.iterdir()), "an unclassified table must not be written anywhere"
