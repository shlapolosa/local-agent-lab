

# ------------------------------------------------- the masters are signed inputs, so: reproducible

def test_every_committed_master_is_what_the_generator_produces():
    """The masters are hashed and signed, so "same input, byte-identical output" is not a nicety —
    a master the generator cannot reproduce is an input nobody can regenerate or verify.

    It was not true: `main()` wrote `master_for` while 15 of the 50 masters could only come from
    `masters_for`, so re-running the documented entry point would have failed to produce those and
    overwritten their parents into a shape the publisher refuses."""
    import importlib.util
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[4]
    spec = importlib.util.spec_from_file_location("ex", root / "scripts" / "extract_cafe_seed.py")
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)

    seed_dir = root / "src" / "lab" / "core" / "usecase" / "seed"
    produced: dict[str, str] = {}
    for payload_file in sorted(seed_dir.glob("*.json")):
        produced |= generator.masters_for(payload_file.stem,
                                          json.loads(payload_file.read_text()))

    # Since 28 Sep 2026 the CAFÉ WORKBOOK is the source of truth for the tables it carries, so the
    # generator owns only the masters it still renders — a master says which script rendered it —
    # and the private ones are not in this repository at all. See the next test.
    owned = {stem for stem in produced if generator.writes(seed_dir / "masters", stem)}
    produced = {stem: text for stem, text in produced.items() if stem in owned}
    on_disk = {p.stem for p in (seed_dir / "masters").glob("*.md")
               if generator.writes(seed_dir / "masters", p.stem)}
    assert set(produced) == on_disk, {"only generated": set(produced) - on_disk,
                                      "only on disk": on_disk - set(produced)}
    differing = [stem for stem, text in produced.items()
                 if (seed_dir / "masters" / f"{stem}.md").read_text() != text]
    assert not differing, differing



def test_the_generator_never_OVERWRITES_a_master_another_source_owns():
    """Re-running `extract_cafe_seed.py` regenerates from the HTML-era seed JSON. Before this rule
    it would have silently rewritten every table the CAFÉ workbook (28 Sep 2026) had replaced —
    32 guardrails back to 26, 92 components back to 59 — and the result would still have parsed,
    published and signed. It also must not write a PRIVATE master into this public repository."""
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parents[4]
    spec = importlib.util.spec_from_file_location("ex2", root / "scripts" / "extract_cafe_seed.py")
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    masters = root / "src" / "lab" / "core" / "usecase" / "seed" / "masters"
    assert not generator.writes(masters, "guardrails"), "the workbook imported this one"
    assert not generator.writes(masters, "build_surface"), "private — never in this repository"
    assert generator.writes(masters, "intake_fields"), "the workbook does not carry this one"


def test_seed_components_goes_through_the_same_ownership_guard():
    """Review F4: `seed_components.py` — which its own docstring says to run after the extractor —
    wrote masters with no guard, so it would have put the HTML-era tables back over the workbook's."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[4] / "scripts" / "seed_components.py").read_text()
    body = src.split("for stem, text in gen.masters_for(name, payload).items():", 1)[1][:600]
    assert "gen.writes(" in body.split("write_text", 1)[0], "every master write is guarded"


def test_process_step_keys_says_what_each_step_is_ACTUALLY_handed():
    """Review F10: the published table the review app's roadmap shows still listed the inputs steps
    read BEFORE the CAFÉ workbook — frame "submission", step 6 "elements; landscape". Exactness is the
    contract here: the roadmap tells a reviewer what an agent saw."""
    from pathlib import Path
    from lab.core.reference import master
    from lab.workloads.usecase.agents import CONTEXT_FOR
    path = Path(__file__).resolve().parents[4] / "src/lab/core/usecase/seed/masters/process_step_keys.md"
    parsed = master.parse(path.read_text())
    rows = [dict(zip(parsed.headers, r)) for r in parsed.rows]
    agent_rows = [r for r in rows if r["Kind"] == "agent"]
    assert agent_rows
    for r in agent_rows:
        assert [x.strip() for x in r["Reads"].split(";")] == list(CONTEXT_FOR[r["Record key"]]), \
            f'{r["Record key"]}: re-run scripts/derive_process_step_keys.py'


def test_the_workbook_import_never_overwrites_a_table_derived_from_CODE(tmp_path, monkeypatch):
    """The workbook carries a copy of process-step-keys, and it is the stale one: the table is
    derived from `lab.workloads.usecase` by its own script. Importing it back would undo the
    derivation silently, so the importer leaves a code-derived table alone and says so."""
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parents[4]
    spec = importlib.util.spec_from_file_location("aw", root / "scripts" / "artifacts_workbook.py")
    wb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wb)
    assert "process-step-keys" in wb._publisher().DERIVED_FROM_CODE
