

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
