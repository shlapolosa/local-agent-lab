"""The Documentation Fabric's DETAILED architecture view — the area feat/doc-fabric touches — kept in
this tree per docs/architecture/README.md and updated as components land, not at the end.

    .venv/bin/python scripts/fabric_diagram.py
    .venv/bin/python scripts/drawio_to_png.py var/out/architecture/fabric.drawio
    cp var/out/architecture/fabric.* docs/architecture/

COLOURS ARE EVIDENCE (same rule as the worktree heatmap): GREEN deployed AND exercised end to end;
AMBER built with a NAMED limitation in the description; GREY not built, verified absent. A colour
without a reason is decoration. Every wave of the POC plan updates this file BEFORE it starts.
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "skills" / "drawio-c4"))

from drawio_c4 import C4Diagram  # noqa: E402

DONE, PART, TODO = "#D5E8D4", "#FFE6CC", "#E8E8E8"
OUT = HERE.parent / "var" / "out" / "architecture"

WAVE = "LIVE 11 Sep 2026: full loop proved on the local stack; DEPLOYED to the cloud (sha-83ae1c0) where the 9-step proof passes; cloud intake awaits an allow-listed library"


def build() -> C4Diagram:
    d = C4Diagram(f"Documentation Fabric on the lab · detail (feat/doc-fabric) · {WAVE}", width=2600)
    d.zone("z_prod", "PRODUCERS & SOURCE ADAPTERS · the fabric knows contracts, not sources (note 003)", stroke="#D79B00", height=230, comp_fill="#FFE6CC")
    d.zone("z_events", "CHANGE EVENTS · durable, at-least-once, idempotent per pointer (product 4)", stroke="#9673A6", height=170, comp_fill="#E1D5E7")
    d.zone("z_work", "FABRIC WORKLOADS · Agent Framework graphs under governed_run · MCP clients only", stroke="#6C8EBF", height=230, comp_fill="#DAE8FC")
    d.zone("z_sem", "SEMANTIC LAYER · semantic-mcp: the four product ports, synchronous (catalog · graph · vocabulary · facade)", stroke="#3A7CA5", height=230, comp_fill="#D7E8F2")
    d.zone("z_gate", "CURATORS & CONSUMERS · workflow-mcp approvals, review app, Teams, Copilot Studio via the gateway", stroke="#B85450", height=200, comp_fill="#F8CECC")
    d.zone("z_state", "STATE & EXTERNAL", stroke="#7A7A7A", height=200, comp_fill="#EDEDED")

    g = lambda why: f"GREY: not built — {why}"
    d.component("contracts", "z_events", "contracts · ids · config (WP1)", "GREEN: ArtifactChanged, 2 ProcessSpecs, 5 InputKinds, 2 approval\nkinds, 3 AgentSpecs — exercised live by every hop of the proof", fill=DONE)
    # producers & adapters
    d.component("runs", "z_prod", "existing runs", "minutes · visio · use-case EXIST; AMBER: the proof used a\nstored minutes artifact + emitted event, not a real minutes\nrun finishing (Ollama quota exhausted 11 Sep)", fill=PART)
    d.component("notif", "z_prod", "graph-mcp /notifications", "AMBER: route deployed on graph-mcp's public domain\n(graph-mcp-production-2a35); no library subscribed yet", fill=PART)
    d.component("recon", "z_prod", "fabric-reconciler", "AMBER: deployed and sweeping every 900 s — but\nFABRIC_ALLOWLIST is empty, so drives=0", fill=PART)
    d.component("delivery", "z_prod", "DeliveryContext port", "GREEN: meeting:<id> carried from the event to a rung-C\ndeliveredUnder edge live; usecase/submission by test; workitem later", fill=DONE)
    # events
    d.component("stream", "z_events", "fabric:events (Redis)", "GREEN: real Redis live — publish, group read, reclaim after\nthe ingress crash, ack; dead-letter + loop-guard by test", fill=DONE)
    d.component("ingress", "z_events", "fabric-ingress", "GREEN: live — dropped the non-allow-listed collab event,\nsubmitted artifact_intake for the lab event (serve-handler\nbug found and fixed live)", fill=DONE)
    # workloads
    d.component("intake", "z_work", "wf-fabric · artifact_intake", "GREEN: live run 67 s — identify→classify→associate→impact→\nsynthesise (2 decision records)→overlap→draft-review asked;\n1858-span trace", fill=DONE)
    d.component("publish", "z_work", "wf-artifact-publish", "GREEN: live run 13 s — released by the approval, record\npublished with a baseline version; re-index best-effort", fill=DONE)
    d.component("agents", "z_work", "classifier · synthesis · publish agents", "GREEN: 3 Entra apps + keys provisioned, 2 skills registered;\nAMBER note: on claude-haiku-4-5 while the Ollama quota is out", fill=DONE)
    # semantic layer
    d.component("catalog", "z_sem", "Knowledge Catalog", "GREEN: Postgres rows in Neon (DDL applied at boot, hnsw index),\nupsert/get/state/assert live from both the local and the cloud stack", fill=DONE)
    d.component("graph", "z_sem", "Traceability Graph", "GREEN: live — edges at C/X/S, SHACL refused a body and a\nguessed owner, impact skipped S, promote S→H by a named\nperson, N-Quads shadow written", fill=DONE)
    d.component("vocab", "z_sem", "Vocabulary", "GREEN: fab: + doc-types registered live beside the BA Guild\nschemes; vocab_link/propose exercised (a candidate parked)", fill=DONE)
    d.component("facade", "z_sem", "Facade", "GREEN in the cloud: embed (nomic, 768-d) · search · similar\nranked the ADR above the minutes for a claims-bus query; the\nlocal stack has no embedder, so local similarity is by test", fill=DONE)
    # gate & consumers
    d.component("approvals", "z_gate", "workflow-mcp approvals + curator", "GREEN: draft-review asked live with 2 drafts attached,\napproved by a named person, curator promoted the type to H,\nrunner bound approval_id and released the publish run", fill=DONE)
    d.component("projector", "z_gate", "fabric-projector", "AMBER: deployed; rendered the page live (752 chars) but\nFABRIC_WIKI_FOLDER is unset, so it logs instead of writing", fill=PART)
    d.component("bot", "z_gate", "Copilot Studio bot", g("post-POC: MCP through the gateway, same door as\nagents; scripts/fabric_demo.py is the POC's caller"), fill=TODO)
    # state
    d.component("neon", "z_state", "Neon Postgres", "GREEN: keys · artifacts · corpus · fabric_artifact +\nfabric_embedding (hnsw), migrated at semantic-mcp boot", fill=DONE)
    d.component("redis", "z_state", "Redis Streams", "GREEN: local Redis carried fabric:events, fabric:graphs,\nthe lock, approvals and requests through the whole proof", fill=DONE)
    d.component("m365", "z_state", "M365 · pilot library", "AMBER: no pilot library chosen — FABRIC_ALLOWLIST and the\nnotification subscription are the two settings that start it", fill=PART)

    for s, t, k in (("runs", "ingress", "async"), ("notif", "stream", "async"), ("recon", "stream", "async"), ("stream", "ingress", "async"),
                    ("ingress", "intake", "async"), ("intake", "catalog", "sync"), ("intake", "graph", "sync"), ("intake", "vocab", "sync"),
                    ("intake", "approvals", "sync"), ("approvals", "publish", "async"), ("publish", "catalog", "sync"), ("publish", "graph", "sync"),
                    ("publish", "projector", "async"), ("projector", "m365", "sync"), ("bot", "facade", "sync"), ("catalog", "neon", "sync"),
                    ("stream", "redis", "sync"), ("delivery", "ingress", "sync"), ("agents", "intake", "sync")):
        d.edge(s, t, k)
    d.legend([("Synchronous (gateway MCP call)", "strokeColor=#1A1A1A;"), ("Async (Redis stream)", "strokeColor=#777777;dashed=1;dashPattern=6 6;"),
              ("green = deployed + exercised", f"fillColor={DONE};"), ("amber = built, named limitation", f"fillColor={PART};"), ("grey = not built", f"fillColor={TODO};")])
    return d


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    diagram = build()
    xml = diagram.render(strict=False)     # A* path: per-component fill is honoured
    path = OUT / "fabric.drawio"; path.write_text(xml)
    counts = {DONE: 0, PART: 0, TODO: 0}
    for comp in diagram._comps:
        if comp[6] in counts: counts[comp[6]] += 1
    print(f"wrote {path}\nviolations: {diagram.violations}\ngreen={counts[DONE]}  amber={counts[PART]}  grey={counts[TODO]}")
