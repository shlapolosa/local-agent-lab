

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

    on_disk = {p.stem for p in (seed_dir / "masters").glob("*.md")}
    assert set(produced) == on_disk, {"only generated": set(produced) - on_disk,
                                      "only on disk": on_disk - set(produced)}
    differing = [stem for stem, text in produced.items()
                 if (seed_dir / "masters" / f"{stem}.md").read_text() != text]
    assert not differing, differing
