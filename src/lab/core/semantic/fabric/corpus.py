"""The whole catalogue as one picture: every record, what each is about, and what the vocabulary says
about THAT — the view that answers "what is our knowledge about, and what is it silent on".

The sibling of `topology.view_of`, divided by the question. `view_of` has a focus and a handful of nodes:
it answers "what is THIS record about". This one has no focus and only means anything at scale.

Built after drawing the catalogue by hand for the first time (10 Oct 2026), which showed two things weeks
of counts had hidden: one concept held half the links, and two thirds of the corpus was the lab's own test
output rather than anything a person wrote. So two decisions are baked in here rather than left to
whoever draws:

  * every record carries the FACETS a person narrows by (source, lifecycle state, document type). An
    unfiltered corpus is a hairball, and a picture nobody can narrow is a picture nobody reads twice.
  * the VOCABULARY'S OWN EDGES are in the view. Without them the picture says two records share a tag,
    which is what tagging already did; with them it says the vocabulary relates the two things they are
    about, which is the claim that owning an ontology makes.

Pure: mappings in, a `TopologyView` out. No store, no HTTP, nothing that knows where a record was read.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from lab.core.semantic.fabric.ontology import SUBJECT, short
from lab.core.viz import ARTIFACT, CONCEPT, VOCABULARY, Edge, Node, TopologyView

__all__ = ["view_of_corpus"]

_ABOUT = short(SUBJECT)


def _tail(iri: str) -> str:
    return str(iri).rsplit("#", 1)[-1].rsplit("/", 1)[-1].rsplit(":", 1)[-1]


def _plural(n: int, what: str) -> str:
    return f"{n} {what}{'' if n == 1 else 's'}"


def view_of_corpus(records: Iterable[Mapping[str, Any]], *, schemes: Iterable[Any] = (),
                   title: str = "The corpus, by what it is about", as_of: str = "") -> TopologyView:
    """Every record that is ABOUT something, the concepts they share, and the vocabulary's edges between
    those concepts. `schemes` are the vocabularies the records were classified against — PLURAL for the
    same reason `topology.view_of` takes several: the fabric may own more than one, and a picture that
    read one would draw edges it could not explain.

    A record with no subject is COUNTED and not drawn. It has no edge, so it would sit on the rim saying
    nothing — while the count of them is itself the finding (40 of 100 on the first real run), which is
    why it goes in the subtitle a person actually reads."""
    nodes: list[Node] = []
    edges: list[Edge] = []
    concepts: dict[str, str] = {}            # concept iri -> label
    holding: dict[str, int] = {}             # concept iri -> how many records are about it
    silent = 0

    for record in records:
        iri = str(record.get("iri") or "")
        subjects = [l for l in (record.get("links") or []) if l.get("predicate") == _ABOUT]
        if not iri or not subjects:
            silent += 1
            continue
        document_type = _tail(str(record.get("document_type") or "")) if record.get("document_type") else ""
        nodes.append(Node(
            id=iri, label=str(record.get("title") or _tail(iri)), kind=ARTIFACT,
            status=str(record.get("state") == "published" and "C" or "X"),
            note=str(record.get("state") or ""),
            facets=(("source", str((record.get("pointer") or {}).get("source") or "")),
                    ("state", str(record.get("state") or "")),
                    ("document_type", document_type))))
        for link in subjects:
            cid = str(link.get("object") or "")
            if not cid:
                continue
            concepts.setdefault(cid, str(link.get("label") or _tail(cid)))
            holding[cid] = holding.get(cid, 0) + 1
            edges.append(Edge(source=iri, target=cid, label="about",
                              status=str(link.get("rung") or VOCABULARY)))

    # The vocabulary's half. Asked of every scheme for every concept: one that does not hold a term answers
    # with nothing, so asking costs nothing and not asking loses a whole vocabulary's contribution.
    for scheme in schemes:
        for cid in list(concepts):
            for predicate, other, direction in scheme.relations_of(_tail(cid)):
                target = str(scheme.uri(other))
                if target not in concepts:
                    concepts[target] = str((scheme.concepts.get(other) or {}).get("label") or other)
                a, b = (cid, target) if direction == "out" else (target, cid)
                edges.append(Edge(source=a, target=b, label=predicate, status=VOCABULARY))

    for cid, label in concepts.items():
        held = holding.get(cid, 0)
        nodes.append(Node(id=cid, label=label, kind=CONCEPT, status=VOCABULARY,
                          note=_plural(held, "record"),
                          facets=(("records", str(held)),)))

    drawn = len(nodes) - len(concepts)
    subtitle = " · ".join([_plural(drawn, "record"), _plural(len(concepts), "concept"),
                           _plural(len(edges), "link")]
                          + ([f"{_plural(silent, 'record')} with no subject, not drawn"] if silent else []))
    return TopologyView(title=title, focus="", nodes=tuple(nodes), edges=tuple(edges),
                        as_of=as_of, subtitle=subtitle)
