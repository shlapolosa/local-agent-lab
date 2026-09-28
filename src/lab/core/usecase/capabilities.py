"""The technology capability map's identity — the one spelling of its join key.

Since the CAFÉ workbook of 28 Sep 2026 the technology capability map is its own artifact —
`technology-capability-l1`, `-l2`, `-l3` — and a capability is addressed by its **L3 id**: `KNW.11`.
Every published reference INTO the map uses it: a guardrail's enforcement point (`cap`, written
"COG.11 Agent definition integrity"), a component's `l3` ("TEC.06; COG.05"), and the realisation
view (`ai-capability-map`), which carries exactly one row per L3 by `l3_id`. The previous key,
"Domain · Capability", resolves against nothing in that corpus: 0 of 81 guardrail references did.

It lived privately in `lab.workloads.usecase.families` while one caller needed it. Several now do —
the family join, the obligation binding, the ArchiMate mapper and the governance check that refuses
a reference resolving to nothing — and two spellings of a join key is the defect the check exists
to catch: a key that normalises differently accepts a reference the other rejects, and the
disagreement shows up as a silently unenforced guardrail rather than as an error.

Identity matters here in a way it does not on the business capability map. A guardrail binds to a
capability, a capability names components, and a component carries a price — so a near-miss is not
a near-answer, it is a wrong control and a wrong number
(`docs/decisions/2026-09-18-two-capability-maps.md`, rule 3).
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

__all__ = ["LEVEL", "concepts", "domain", "is_key", "key", "label", "refs"]

#: A technology L3 id: the L1's three-letter code, a dot, two digits — `KNW.11`. A business L3 is
#: `B1.1.2` and an L2 `KNW-B`, so the shape alone says which map an id belongs to.
_L3_ID = re.compile(r"[A-Z]{3}\.\d{2}")
_LEADING_ID = re.compile(rf"^({_L3_ID.pattern})\b\s*")

#: The level a match is made AT. The map is L1 domain -> L2 capability area -> L3 capability; a
#: product is not a row here but a realisation in `ai-capability-map`. Named rather than inferred
#: from the deepest level present: a guardrail binds to an L3 and a component realises one, and
#: inferring would move the match the day a tenant published a fourth level.
LEVEL = 3


def is_key(ident: Any) -> bool:
    """Whether this identifier addresses a TECHNOLOGY capability.

    The id is the distinguishing fact: a technology L3 is `KNW.11`, a business L3 `B1.1.2`, and no
    other field distinguishes a match from one map from a match from the other. The ArchiMate
    mapper needs to know, because the two belong at different layers — a business capability is a
    Strategy-layer `Capability`, a technology capability is an `ApplicationService` the solution
    exposes. Putting the second on the Strategy layer would make the repository answer "what
    ability does the business possess" with a list of products.
    """
    return bool(_L3_ID.fullmatch(str(ident or "").strip()))


def key(row: Mapping[str, Any]) -> str:
    """The map's key for one row: its L3 id — `l3_id` on a realisation-view row, `id` on a map row.

    A row that carries no technology L3 id has NO key rather than a plausible one: a business L3,
    an L2, or a row in the retired "Domain · Capability" shape would otherwise look like a
    well-formed key that matches nothing, and the caller would report a dangling guardrail instead
    of a row that does not belong in this join.
    """
    for field in ("l3_id", "id"):
        ident = str(row.get(field, "") or "").strip()
        if is_key(ident):
            return ident
    return ""


def refs(value: Any) -> list[str]:
    """The references in one cell, with each capability reference reduced to its L3 id.

    A guardrail's `cap` reads "COG.11 Agent definition integrity; XCT.22 Approval & gate
    evidence": the id is the reference and the name is for the reader. A component's `l3` is the
    bare list, and the realisation view's `components` a list of catalogue ids — both pass through.

    A reference that is prose rather than a key is RETURNED, not dropped: a silently dropped
    reference is a guardrail nobody is told is unenforced — precisely the condition that went
    unnoticed for twenty of them.

    **`;` and only `;`.** A comma once split `Ontology (entities, rules)` in half (18 Sep 2026) and
    reported a dangling guardrail in a map that carried the row. Every list-valued column arrives
    as a list or `;`-joined, so there is nothing for comma-tolerance to buy.
    """
    items: Iterable[Any] = value if isinstance(value, (list, tuple)) else \
        str(value or "").split(";")
    out: list[str] = []
    for item in (str(v).strip() for v in items):
        if item:
            leading = _LEADING_ID.match(item)
            # Reduced to the id only when exactly ONE id is in the item: "COG.11, COG.12 X" trimmed
            # to COG.11 would silently lose COG.12 (review, 28 Sep 2026). Returned whole instead, it
            # resolves to nothing and the governance check fails loudly on it.
            if leading and len(_L3_ID.findall(item)) == 1:
                out.append(leading.group(1))
            else:
                out.append(item)
    return out


def domain(ident: Any) -> str:
    """The L1 a technology L3 belongs to — its code, `KNW` for `KNW.11`. Empty for anything else."""
    text = str(ident or "").strip()
    return text.split(".", 1)[0] if is_key(text) else ""


def label(text: Any) -> str:
    """A capability's name with a LEADING L3 id trimmed off — "KNW.11 Agentic retrieval" reads
    "Agentic retrieval" on a drawing. Models write the key into the label field (measured), so the
    trim happens where the label is read. A bare id is left as it is: it is all there is."""
    raw = str(text or "").strip()
    trimmed = _LEADING_ID.sub("", raw).strip()
    return trimmed or raw


def concepts(rows, parents=()) -> list[dict]:
    """The technology capability map as CANDIDATES a matcher can be shown.

    The matchers speak one shape — `{id, label, level, parent, path, definition}` — and read it
    generically, which is what lets the same strategies run over any map. This is the mapper
    between the corpus's own columns and that shape, and it lives in `core` because it is a
    statement about the DOMAIN's map, not about how a workload happens to fetch it.

    `rows` are the L3 rows; `parents` the L1 and L2 rows, used only to name the path and to offer
    the headings a drill walks down. **The id is the L3 id**, so a match returns the exact string
    the guardrail chain and the realisation view join on and reaches its obligations and its
    components with no further resolution. The definition is what the map says the capability IS
    and WHEN it is exercised — a label alone is the least informative field it carries, and a match
    made on a label is a match made on a coincidence of words.
    """
    named = {str(p.get("id", "")).strip(): p for p in parents or () if isinstance(p, Mapping)}
    out: list[dict] = []
    seen: set[str] = set()
    for row in rows or ():
        if not isinstance(row, Mapping):
            continue
        ident = key(row)
        if not ident or ident in seen:
            continue
        seen.add(ident)
        l1, l2 = str(row.get("l1", "") or domain(ident)).strip(), str(row.get("l2", "")).strip()
        name = str(row.get("name", "")).strip() or ident
        path = " · ".join(str(named[p].get("name", "")).strip() or p
                          for p in (l1, l2) if p in named) or l1
        exercised = str(row.get("when_exercised", "") or "").strip()
        definition = " ".join(p for p in (str(row.get("description", "") or "").strip(),
                                          f"Exercised: {exercised}." if exercised else "") if p)
        out.append({"id": ident, "label": name, "level": LEVEL, "parent": l2 or l1,
                    "path": f"{path} · {name}" if path else name, "definition": definition})
    if not out:
        return []
    # Headings come FIRST and only those actually used: the matcher reads a list, and a heading
    # with nothing under it is not a candidate.
    used2 = {c["parent"] for c in out if c["parent"] in named}
    used1 = {str(named[p].get("l1", "")).strip() for p in used2} | {domain(c["id"]) for c in out}
    head = [{"id": p, "label": str(named[p].get("name", "")).strip() or p, "level": 1,
             "parent": None, "path": str(named[p].get("name", "")).strip() or p,
             "definition": str(named[p].get("description", "") or "").strip()}
            for p in sorted(used1) if p in named]
    head += [{"id": p, "label": str(named[p].get("name", "")).strip() or p, "level": 2,
              "parent": str(named[p].get("l1", "")).strip() or None,
              "path": " · ".join(x for x in (str(named.get(str(named[p].get("l1", "")), {})
                                                 .get("name", "")).strip(),
                                             str(named[p].get("name", "")).strip()) if x),
              "definition": str(named[p].get("description", "") or "").strip()}
             for p in sorted(used2)]
    return head + out
