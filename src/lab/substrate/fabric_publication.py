"""Staging the vocabulary the fabric owns for publication into the governed corpus.

The fabric cannot publish, and must not. Publication has no tool surface, the Ed25519 signing seed is
deliberately off every service (`var/run/reference_signing_key`, never `.env`/`LAB_ENV`), and the corpus
reader's database role holds SELECT plus an insert on pin and consumption — nothing else. So the honest split
is the one the licensed workbooks already use in reverse: the fabric RENDERS what it owns and STAGES it by
reference, and an operator signs and releases it with `python -m lab.substrate.reference.publish`.

The master is the source, not a by-product. `lab.core.reference.master.render`/`parse` are a round trip, and
the publisher hashes THIS text and derives its records from parsing it — `derived_from = master_sha256` is then
mechanical rather than an assertion, which is the whole of DR-02. So this module renders and never emits a
second, independently-built form.

Published under the ids the use-case pipeline already joins on, so their switch from the packaged copy to the
fabric's is an artifact id and not a line of code.
"""
from __future__ import annotations

from typing import Any

from lab.core.reference.master import render
from lab.platform.contracts import SemanticTools
from lab.substrate import fabric_gateway

CONCEPTS_ID = "ontology-concepts"
RELATIONSHIPS_ID = "ontology-relationships"

#: The columns each master leads with. The rest of a concept's own columns follow in the order the master
#: carried them — a vocabulary the fabric did not model must survive the round trip, because this IS its master
#: now and a column dropped here is a column lost from the tenant's own document.
CONCEPT_LEAD = ("id", "name", "module", "kind", "parent", "definition", "alt", "resolves_to")
RELATIONSHIP_COLUMNS = ("subject", "predicate", "object", "cardinality", "note")

#: What the operator's publish must say for each artifact. `whole` because a vocabulary is read ENTIRELY — a
#: consumer that fetched "the relevant concepts" would classify against a subset and never know which.
PUBLISH_ARGS: dict[str, dict[str, str]] = {
    CONCEPTS_ID: {"kind": "record", "record-type": "ontology-concept", "key-fields": "id", "retrieval": "whole"},
    RELATIONSHIPS_ID: {"kind": "record", "record-type": "ontology-relationship",
                       "key-fields": "subject,predicate,object", "retrieval": "whole"},
}


def _concept_rows(scheme) -> tuple[list[str], list[list[Any]]]:
    """Every concept, retired ones included. A consumer joining on an old id must still resolve it — dropping
    the row is what turns a correct historical statement into a dangling one."""
    rows = scheme.rows()
    extra = [k for r in rows for k in r if k not in CONCEPT_LEAD]
    headers = list(CONCEPT_LEAD) + sorted(dict.fromkeys(extra))
    out = []
    for r, c in zip(rows, scheme.concepts.values()):
        row = {**r, "alt": list(c.get("alt") or [])}
        out.append([row.get(h, "") for h in headers])
    return headers, out


def masters(scheme) -> dict[str, str]:
    """The markdown masters for one vocabulary, by artifact id. Pure — no store, no gateway, no clock."""
    if not scheme.concepts:
        raise ValueError(f"{scheme.name} has no concepts, and an empty vocabulary is not a publication")
    meta = {"Vocabulary": scheme.name, "Version": getattr(scheme, "version", "") or "unversioned",
            "Curated by": "the Documentation Fabric — admissions and retirements are a steward's decisions, "
                          "recorded with their name"}
    headers, rows = _concept_rows(scheme)
    out = {CONCEPTS_ID: render(title=f"{scheme.title} — concepts", headers=headers, rows=rows, meta=meta)}
    edges = list(getattr(scheme, "relationships", ()) or ())
    if edges:
        # absent rather than empty: an empty table publishes "this vocabulary states no relationships", which
        # is a claim, where no artifact is simply the absence of one
        out[RELATIONSHIPS_ID] = render(
            title=f"{scheme.title} — relationships", headers=list(RELATIONSHIP_COLUMNS), meta=meta,
            rows=[[e.get(c, "") for c in RELATIONSHIP_COLUMNS] for e in edges])
    return out


def command(artifact_id: str, ref: str, version: str, owner: str) -> str:
    """The exact line an operator runs. Printed rather than executed: the seed is theirs, not the service's."""
    args = " ".join(f"--{k} {v}" for k, v in PUBLISH_ARGS[artifact_id].items() if v)
    return (f"python -m lab.substrate.reference.publish publish {artifact_id} "
            f"--master-ref {ref} --version {version} --owner {owner} {args}")


async def stage(scheme, *, call=None, owner: str = "ea@doh", version: str = "") -> dict[str, dict]:
    """Render the masters and store each by reference. Returns {artifact_id: {ref, name, command}}.

    By REFERENCE because the content is tenant-sourced: it goes into the private artifact store, never into
    this repository and never into a log. The operator fetches it with the ref."""
    go = call or fabric_gateway.call
    version = version or getattr(scheme, "version", "") or "unversioned"
    out: dict[str, dict] = {}
    for artifact_id, text in masters(scheme).items():
        name = f"{artifact_id}.md"
        stored = (await go([(SemanticTools.store_page, {"text": text, "name": name})]))[0]
        ref = str((stored or {}).get("ref") or "")
        out[artifact_id] = {"ref": ref, "name": name, "rows": text.count("\n| ") - 1,
                            "command": command(artifact_id, ref, version, owner)}
    return out


__all__ = ["CONCEPTS_ID", "RELATIONSHIPS_ID", "PUBLISH_ARGS", "masters", "command", "stage"]
