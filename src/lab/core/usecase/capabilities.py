"""The technology capability map's identity — the one spelling of its join key.

CAFÉ's M4 names a capability by its domain and its label together: "Knowledge · Agentic retrieval".
Every published reference INTO the map is that string — a guardrail's enforcement point (`cap`), and
in time anything else that has to point at a capability rather than at a component.

It lived privately in `lab.workloads.usecase.families` while one caller needed it. Three now do —
the family join, the obligation binding, and the governance check that refuses a reference resolving
to nothing — and two spellings of a join key is the defect the check exists to catch: a key that
normalises differently accepts a reference the other rejects, and the disagreement shows up as a
silently unenforced guardrail rather than as an error.

Identity matters here in a way it does not on the business capability map. A guardrail binds to a
capability, a capability names components, and a component carries a price — so a near-miss is not
a near-answer, it is a wrong control and a wrong number
(`docs/decisions/2026-09-18-two-capability-maps.md`, rule 3).
"""
from __future__ import annotations

from typing import Any, Mapping

__all__ = ["LEVEL", "SEP", "concepts", "is_key", "key", "refs"]

#: U+00B7 MIDDLE DOT, spaced — how the framework writes it, and therefore how the corpus does.
SEP = " · "


def key(row: Mapping[str, Any]) -> str:
    """The map's natural key for one capability row: "Domain · Capability".

    A row missing either half yields the half it has and NO separator. Returning "Knowledge · " for
    a row with no label would look like a well-formed key that happens to match nothing, and the
    caller would report a dangling guardrail instead of an incomplete map row.
    """
    domain = str(row.get("domain", "") or "").strip()
    capability = str(row.get("capability", "") or "").strip()
    return SEP.join(p for p in (domain, capability) if p)


def is_key(ident: Any) -> bool:
    """Whether this identifier addresses a TECHNOLOGY capability.

    The id is the distinguishing fact, and deliberately so: a technology capability is addressed by
    its natural key ("Knowledge · Agentic retrieval"), a business one by a synthetic content id
    ("cap-7f3a91"), and no other field distinguishes a match from one map from a match from the
    other. The ArchiMate mapper needs to know, because the two belong at different layers — a
    business capability is a Strategy-layer `Capability`, a technology capability is an
    `ApplicationService` the solution exposes. Putting the second on the Strategy layer would make
    the repository answer "what ability does the business possess" with a list of products.
    """
    return SEP in str(ident or "")


def refs(value: Any) -> list[str]:
    """The capability references in one cell — a guardrail's `cap` column.

    `cap` is deliberately NOT in `cells.LIST_COLUMNS`: G04's rule text contains a semicolon, and
    splitting the whole artifact on one would cut a sentence in half. So the column travels joined
    and is split here, by the module that knows it is a list of keys.

    A reference that is prose rather than a key is RETURNED, not dropped. A silently dropped
    reference is a guardrail nobody is told is unenforced — precisely the condition that went
    unnoticed for twenty of them.

    **`;` and only `;`.** The version of this inherited from `families._list` also treated a comma
    as a separator, defensively. That was harmless only while no capability was named with one, and
    on 18 Sep 2026 `Semantic · Ontology (entities, rules)` became an enforcement point and was split
    into `"Semantic · Ontology (entities"` and `"rules)"` — two references resolving to nothing,
    reported as a dangling guardrail in a map that in fact carried the row. Every list-valued column
    in the corpus arrives as an actual list (`cells.LIST_COLUMNS`); `cap` is the one joined string
    and its separator is `cells.LIST_SEP`. So there is nothing for comma-tolerance to buy, and a
    label is free to contain a comma.
    """
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [v.strip() for v in str(value or "").split(";") if v.strip()]


#: The level a match is made AT. CAFÉ's M4 is L1 domain -> L2 capability -> L3 product, and only the
#: first two are rows here — a product is a `primary`/`alternative` string and a `components` id.
#: Named rather than inferred from the deepest level present: if a tenant ever publishes products as
#: rows, the grain must stay at the capability, because that is what a guardrail binds to and what a
#: component realises. Inferring would silently move the match onto products the day someone did.
LEVEL = 2


def concepts(rows, domains=()) -> list[dict]:
    """The technology capability map as CANDIDATES a matcher can be shown.

    The matchers speak one shape — `{id, label, level, parent, path, definition}` — and read it
    generically, which is what lets the same three strategies run over any map. This is the mapper
    between the corpus's own columns and that shape, and it lives in `core` because it is a
    statement about the DOMAIN's map, not about how a workload happens to fetch it.

    **The id is the natural key**, `"Domain · Capability"`. That is the single most important thing
    here: a match returns the exact string the guardrail chain (`guardrails.cap`) and the component
    catalogue (`ai-capability-map.components`) already join on, so a matched capability reaches its
    obligations and its components with no further resolution. A synthetic id would make a match a
    dead end one hop later — which is precisely what matching a BUSINESS map produced, since its
    concepts join to nothing this framework catalogues.

    The definition is built from what the map actually says — the rationale for the row and the
    products that realise it. A label alone is the least informative field it carries, and a match
    made on a label is a match made on a coincidence of words.
    """
    covers = {str(d.get("domain", "")).strip(): str(d.get("covers", "") or "").strip()
              for d in domains or () if isinstance(d, Mapping)}
    out: list[dict] = []
    seen: set[str] = set()
    for row in rows or ():
        if not isinstance(row, Mapping):
            continue
        ident = key(row)
        # Half a key is no key: `SEP` is absent when either side is missing, and a row that cannot
        # be addressed cannot be matched TO, so it is dropped rather than given a broken id.
        if SEP not in ident or ident in seen:
            continue
        seen.add(ident)
        domain = str(row.get("domain", "")).strip()
        detail = " ".join(p for p in (str(row.get("rationale", "") or "").strip(),
                                      str(row.get("primary", "") or "").strip(),
                                      str(row.get("alternative", "") or "").strip()) if p)
        out.append({"id": ident, "label": str(row.get("capability", "")).strip(), "level": LEVEL,
                    "parent": domain, "path": ident, "definition": detail})
    # Domains come SECOND and only for the domains actually used: the matcher reads a list, and a
    # domain with no capability under it is a heading, not a candidate.
    used = {c["parent"] for c in out}
    return [{"id": d, "label": d, "level": 1, "parent": None, "path": d,
             "definition": covers.get(d, "")} for d in sorted(used) if d] + out
