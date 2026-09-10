"""The packaged seed is a PUBLISH-TIME master, not a runtime fallback — a ratchet.

Every runtime READ of the seed (`seed.artifact(...)`, `seed.guardrails()`, `seed.live_guardrails()`)
is a place where a run can answer from the image instead of the governed corpus while still
claiming the corpus, and where changing an artifact means building a new image. Counted by CALL
SITE across the whole package, not by import in two tiers: `valuation-mcp` never imports the seed
and still prices every run from it, through `lab.core.usecase.cost.price_lines`. The set below is
what is left; it may only shrink. When it is empty, the seed's only reader is the publisher.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "src" / "lab"

#: The runtime readers still to be moved onto the corpus (Phase 3 of the reference-layer plan).
RATCHET = {
    "core/usecase/composition.py",            # default-argument fallback to the packaged families
    "core/usecase/obligations.py",            # default-argument fallback to the packaged guardrails
    "substrate/review/app.py",                # the Submit form's intake fields
}

READS = {"artifact", "guardrails", "live_guardrails", "names"}


def _seed_importers() -> set[str]:
    """Modules that CALL a seed read — `seed.<read>(…)` or a bare `<read>(…)` imported from it."""
    out = set()
    for path in ROOT.rglob("*.py"):
        if path.name == "seed.py" and path.parent.name == "usecase":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "lab.core.usecase.seed":
                imported |= {a.asname or a.name for a in node.names if a.name in READS}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if (isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name)
                    and fn.value.id == "seed" and fn.attr in READS):
                out.add(str(path.relative_to(ROOT)))
            elif isinstance(fn, ast.Name) and fn.id in imported:
                out.add(str(path.relative_to(ROOT)))
    return out


def test_runtime_seed_reads_only_shrink():
    found = _seed_importers()
    assert found <= RATCHET, f"new runtime seed readers: {sorted(found - RATCHET)}"


def test_the_ratchet_names_only_readers_that_still_exist():
    """A ratchet entry for a reader that has moved is a lie that lets the next one in."""
    found = _seed_importers()
    assert RATCHET <= found, f"remove from RATCHET, they no longer read the seed: {sorted(RATCHET - found)}"
