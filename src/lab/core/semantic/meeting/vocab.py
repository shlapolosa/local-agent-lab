"""The meeting vocabulary: a pure read of `taxonomy.json`. No behaviour is coded per type.

It diverges from the ArchiMate vocabulary in one deliberate way: the relations live in the JSON too.
ArchiMate keeps them in Python because they are frozen by a standard and shared with the derivation
engine. Here the most important property is that adding a `WorkItem` hub later is a DATA change, so
putting relations in code would be the one thing that broke it.

Relation names deliberately avoid ArchiMate's. If this vocabulary declared a `Composition`, the
derivation engine would fire and mint derived triples with ArchiMate's semantics, silently, in a
model that never asked for them. With domain verbs it derives nothing — by choice rather than luck.
"""
from __future__ import annotations

import json
import os

from ..ontology import Vocabulary

HERE = os.path.dirname(__file__)
NAME, BASE = "meeting-1.0", "urn:lab:semantic:meeting#"


def build() -> Vocabulary:
    tax = json.load(open(os.path.join(HERE, "taxonomy.json"), encoding="utf-8"))
    classes = {t: {"nature": c["nature"], "pii": c["pii"], "definition": c["definition"],
                   "examples": c.get("examples", []), "confusable_with": c.get("confusable_with")}
               for t, c in tax["elements"].items()}
    permitted = {(src, tgt): set(rels)
                 for src, targets in tax["permitted"].items()
                 for tgt, rels in targets.items()}
    return Vocabulary(name=NAME, base=BASE, classes=classes, relations=tax["relations"],
                      permitted=permitted,
                      facets={"nature": tax["natures"], "pii": tax["pii"]},
                      rules=list(tax["rules"]))
