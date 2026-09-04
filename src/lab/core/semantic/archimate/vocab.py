"""ArchiMate 3.x vocabulary = taxonomy.json (classification, definitions, rules) +
Archi's machine-readable relationship matrix (the complete Appendix B: which relation
types are permitted between any two concepts). Both are data; this module only joins them.
"""
import json
import os
import xml.etree.ElementTree as ET

from ..ontology import Vocabulary

HERE = os.path.dirname(__file__)
NAME, BASE = "archimate-3.1", "urn:lab:semantic:archimate#"

# Archi relationships.xml letter key (verified against the spec: actor-i->process,
# process-a->object, driver-n->goal, component-r->service, interface-i->service …)
KEY = {"a": "Access", "c": "Composition", "f": "Flow", "g": "Aggregation", "i": "Assignment",
       "n": "Influence", "o": "Association", "r": "Realization", "s": "Specialization",
       "t": "Triggering", "v": "Serving"}

RELATIONS = {
    "Composition":    {"definition": "Whole consists of part; part cannot exist without the whole.", "category": "structural", "strength": 4},
    "Aggregation":    {"definition": "Whole groups parts that can exist independently.", "category": "structural", "strength": 3},
    "Assignment":     {"definition": "Active structure performs behaviour / is allocated to (interface exposes service, node hosts artifact).", "category": "structural", "strength": 2},
    "Realization":    {"definition": "More concrete element realizes a more abstract one (component realizes service, artifact realizes component, capability realizes goal).", "category": "structural", "strength": 1},
    "Serving":        {"definition": "Element provides its functionality to another (server -> served).", "category": "dependency"},
    "Access":         {"definition": "Behaviour or active structure observes or acts on a passive element (read/write).", "category": "dependency"},
    "Influence":      {"definition": "Element affects a motivation element (+/-).", "category": "dependency"},
    "Association":    {"definition": "Unspecified relationship — use only when nothing stronger is true.", "category": "dependency"},
    "Triggering":     {"definition": "Temporal or causal sequence between behaviours/events.", "category": "dynamic"},
    "Flow":           {"definition": "Transfer of information, goods or value between behaviours.", "category": "dynamic"},
    "Specialization": {"definition": "Specific element is a kind of general element (same type).", "category": "other"},
}

LAYERS = {"Motivation": "Why: stakeholders, drivers, goals, requirements, principles.",
          "Strategy": "Capabilities, resources, courses of action, value streams.",
          "Business": "Actors, roles, channels (interfaces), src/lab/workloads/functions, services, business objects.",
          "Application": "Components, APIs/UIs (interfaces), functions/processes, services, data objects.",
          "Technology": "Nodes, devices, system software, network, technology services, artifacts.",
          "Physical": "Equipment, facilities, distribution networks, materials.",
          "Implementation": "Work packages, deliverables, plateaus, gaps.",
          "Other": "Composite/cross-cutting: location, grouping, junction."}


def build() -> Vocabulary:
    tax = json.load(open(os.path.join(HERE, "taxonomy.json")))
    classes = {t: {"layer": c["layer"], "aspect": c["aspect"], "definition": c["definition"],
                   "examples": c.get("examples", []), "confusable_with": c.get("confusable_with")}
               for t, c in tax["elements"].items()}
    permitted = {}
    root = ET.parse(os.path.join(HERE, "archi-relationships.xml")).getroot()
    for src in root.findall("source"):
        s = src.get("concept")
        for tgt in src.findall("target"):
            t = tgt.get("concept")
            permitted[(s, t)] = {KEY[ch] for ch in tgt.get("relations", "") if ch in KEY}
            for c in (s, t):                       # matrix may name concepts the taxonomy lacks (e.g. junctions)
                classes.setdefault(c, {"layer": "Other", "aspect": "active", "matrix_only": True,
                                       "definition": "Concept from the relationship matrix.", "examples": []})
    return Vocabulary(name=NAME, base=BASE, classes=classes, relations=RELATIONS, permitted=permitted,
                      facets={"layer": LAYERS, "aspect": tax["aspects"]},
                      rules=list(tax["decomposition_rules"]))
