"""The rendering ladder: how text reached the fabric, and how far that is from the artifact itself."""
from lab.core.semantic.fabric import renderings as R


def test_the_ladder_orders_a_translation_below_a_transcript_below_the_document():
    assert R.weaker("transcript", than="document")
    assert R.weaker("transcript-translated", than="transcript")
    assert not R.weaker("document", than="transcript")


def test_two_renderings_at_the_SAME_rank_are_not_ordered():
    """The measurements separate a transcript from a document; they do not separate a page image from a
    figure, and a ladder that pretended otherwise would be inventing precision."""
    assert not R.weaker("figure", than="page-image") and not R.weaker("page-image", than="figure")
    assert R.rank_of("document") == R.rank_of("structured") == 0


def test_an_UNDECLARED_rendering_is_treated_as_the_WEAKEST_not_the_strongest():
    """An unstated provenance is where the fabric knows least. Defaulting it to the document's own words would
    make the least trustworthy evidence indistinguishable from the most — and it would do so silently, on
    exactly the inputs nobody has classified yet."""
    assert R.of("").name == R.DEFAULT and R.of("something-new").name == R.DEFAULT
    assert R.rank_of("whatever") == max(r.rank for r in R.RENDERINGS.values())
    assert not R.weaker("document", than="whatever") and R.weaker("whatever", than="document")


def test_every_declared_rendering_explains_what_can_go_wrong_at_that_step():
    """The note is what a reviewer reads, so it must say more than the name does."""
    for name, r in R.RENDERINGS.items():
        assert r.name == name and r.rank >= 0
        assert len(r.note) > 20 and name.split("-")[0] not in r.note.split()[:1]


def test_the_SHAPE_and_the_LADDER_declare_exactly_the_same_renderings():
    """Two homes for one list, so the exactness IS the contract — a two-way parity test, like the catalogue
    and its server. Add a rendering to the module and forget the shape and every record naming it is refused
    at the gate; add it to the shape alone and the facet accepts a value no reader can order."""
    from pathlib import Path

    ttl = (Path(R.__file__).parent / "fab-shapes.ttl").read_text()
    block = ttl.split("sh:path fab:rendering", 1)[1].split("sh:in (", 1)[1].split(")", 1)[0]
    declared = {w.strip('" ') for w in block.split() if w.strip('" ')}
    assert declared == set(R.RENDERINGS), f"shape {declared ^ set(R.RENDERINGS)} differs from the ladder"
