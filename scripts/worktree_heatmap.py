"""A C4 heatmap of this worktree: every component, coloured by how finished it actually is.

Diagram-as-code, kept here so the view is regenerable (CLAUDE.md: "Keep generator scripts under
`scripts/` so views are regenerable"). Re-run after any change that moves a component's status:

    .venv/bin/python scripts/worktree_heatmap.py

THE COLOURS ARE EVIDENCE, NOT IMPRESSION. Each one is set from something checkable:

  GREEN  deployed AND exercised end to end — a live run, a governed tool call, or a test that
         drives the real path. `deploy/railway.py substrate images` lists the service on the current
         build, and something in this session or the run log proves it did its job.
  AMBER  built and reachable, but not finished: a known limitation, a quality result that fails its
         own purpose, a path that works only under a condition, or code shipped but never exercised.
  GREY   not built. Verified absent rather than assumed — `grep -rl presidio src/` is empty,
         `src/lab/core/*/port.py` is only collab/reference/speech, `adoit_rest` is imported
         concretely by the server, evals is a data file with no runner.

Where a component is amber or grey the description says WHY, because a heatmap whose colours cannot
be argued with is decoration.
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "skills" / "drawio-c4"))

from drawio_c4 import C4Diagram  # noqa: E402

DONE = "#D5E8D4"      # green
PART = "#FFE6CC"      # amber
TODO = "#E8E8E8"      # grey

OUT = HERE.parent / "var" / "out" / "architecture"


def build() -> C4Diagram:
    d = C4Diagram("local-agent-lab · worktree heatmap (main @ b72701e+)", width=3000)

    # ---------------------------------------------------------------- bands, top -> down
    d.zone("z_people", "HUMANS & CLIENT SURFACES", stroke="#D79B00", height=250, comp_fill="#FFE6CC")
    d.zone("z_gov", "GOVERNANCE PLANE · the single egress", stroke="#B85450", height=250, comp_fill="#F8CECC")
    d.zone("z_ports", "CAPABILITY PORTS · MCP servers (substrate)", stroke="#3A7CA5", height=150, comp_fill="#D7E8F2")
    d.zone("z_work", "WORKLOADS · business processes (Agent Framework graphs)", stroke="#6C8EBF",
           comp_fill="#DAE8FC")
    d.zone("z_sub", "SUBSTRATE SERVICES · the plane the workloads never import", stroke="#9673A6",
           comp_fill="#E1D5E7")
    d.zone("z_core", "DOMAIN CORE · imports nothing below it", stroke="#82B366", height=250, comp_fill="#D5E8D4")
    d.zone("z_plat", "PLATFORM KERNEL · shared by every tier", stroke="#666666", height=250, comp_fill="#F0F0F0")
    d.zone("z_state", "STATE & EXTERNAL SYSTEMS", stroke="#7A7A7A", height=250, comp_fill="#EDEDED")

    # ---------------------------------------------------------------- humans & clients
    d.component("teams_chat", "z_people", "Teams · Flow bot chat",
                "adaptive cards, one per lane\nVERIFIED: 3 cards, 3 answers", fill=DONE)
    d.component("teams_ch", "z_people", "Teams channel card",
                "lab-approvals notification\nVERIFIED: 3 sent", fill=DONE)
    d.component("flow", "z_people", "Power Automate flow",
                "AMBER: lanes are SEQUENTIAL\n(SetVariable bars concurrency)", fill=PART)
    d.component("review", "z_people", "Review app (Streamlit)",
                "approve · submit · runs board", fill=DONE)
    d.component("cc", "z_people", "Claude Code / CLI",
                "(base_url, credential)\n7 models via claude/ alias", fill=DONE)
    d.component("tg", "z_people", "Telegram channel",
                "AMBER: plumbing only,\nnever exercised", fill=PART, row=1)
    d.component("a2a_client", "z_people", "A2A caller",
                "GREY: cards are discovery-only;\nnothing hosts /a2a/{id}", fill=TODO, row=1)
    d.component("rest", "z_people", "REST ingress /api",
                "Entra app roles per operation", fill=DONE, row=1)

    # ---------------------------------------------------------------- governance plane
    d.component("gw", "z_gov", "LiteLLM gateway",
                "virtual keys · budgets · ACLs\nstore_model_in_db: true", fill=DONE)
    d.component("auth", "z_gov", "custom_auth",
                "Entra JWT -> virtual key\nAPIM validate-jwt analogue", fill=DONE)
    d.component("pii", "z_gov", "PII guardrail (regex)",
                "reversible pseudonymisation\n82 patterns, ~1ms", fill=DONE)
    d.component("ner", "z_gov", "Presidio NER tier",
                "GREY: 0 files in src/.\nNames & clinical PII uncaught", fill=TODO)
    d.component("router", "z_gov", "auto_router",
                "glm-flash classifier\n+ regex fallback", fill=DONE)
    d.component("agents", "z_gov", "Agent registry",
                "17 cards, 17 keys linked", fill=DONE, row=1)
    d.component("hub", "z_gov", "Public agent hub",
                "AMBER: bulk make_public fixed,\nnot yet re-verified live", fill=PART, row=1)
    d.component("skills", "z_gov", "Skill registries",
                "AMBER: drawio-c4 / drawio-cafe\nNOT registered; /v1/skills 500s", fill=PART, row=1)
    d.component("meter", "z_gov", "Metering & spend",
                "per key -> per team -> per agent", fill=DONE, row=1)

    # ---------------------------------------------------------------- MCP capability ports
    for cid, title, desc, fill in [
        ("m_sem", "semantic-mcp :9200", "vocabularies · SPARQL · SKOS", DONE),
        ("m_ea", "adoit-mcp :9100 (ea_mcp)", "AMBER: REST writes edge-blocked;\nfile-import path only", PART),
        ("m_sto", "storage-mcp :9300", "read-only upload store", DONE),
        ("m_wf", "workflow-mcp :9400", "submit/status/result + approvals", DONE),
        ("m_col", "graph-mcp :9500 (collab_mcp)", "M365 behind a neutral port", DONE),
        ("m_sp", "speech-mcp :9600", "transcribe · diarize", DONE),
        ("m_ref", "reference-mcp :9700", "VERIFIED 11 Sep: pin · lookup · search\n+ vector-store façade via gateway", DONE),
        ("m_dec", "decision-mcp :9800", "VERIFIED: readiness verdict under\na pin (design run, gate C)", DONE),
        ("m_val", "valuation-mcp :9900", "AMBER: valuation_cost join proven\noffline only — design halts at gate C", PART),
    ]:
        d.component(cid, "z_ports", title, desc, fill=fill)

    # ---------------------------------------------------------------- workloads
    d.component("w_visio", "z_work", "visio_to_archimate",
                "the reference workload\nBA -> Architect -> stage", fill=DONE)
    d.component("w_tr", "z_work", "meeting_to_transcript ×2",
                "VERIFIED today: 3 lanes,\n13-17s per run", fill=DONE)
    d.component("w_min", "z_work", "transcript_to_minutes",
                "VERIFIED today: 171 triples,\nnames not labels", fill=DONE)
    d.component("w_scr", "z_work", "use_case_screening",
                "VERIFIED 11 Sep: leaves matcher,\n7.7 min, pinned, trail recorded", fill=DONE)
    d.component("w_des", "z_work", "use_case_design",
                "AMBER: started by the approval, re-pins,\nHALTS at gate C: 3 tenant corpora absent", fill=PART)
    d.component("w_inv", "z_work", "use_case_investment",
                "AMBER: deployed, never reached\n(design halts at gate C)", fill=PART)
    d.component("w_pro", "z_work", "use_case_provisioning",
                "AMBER: deployed, never reached\n(design halts at gate C)", fill=PART)
    d.component("w_run", "z_work", "governed_run skeleton",
                "one root span, one close path\nevery host goes through it", fill=DONE, row=1)
    d.component("w_pre", "z_work", "preflight",
                "refuses a skewed run at 0 tokens\n+ argument checking", fill=DONE, row=1)
    d.component("w_trans", "z_work", "translate step",
                "GREY: analysed, not built.\nPer-segment language unusable", fill=TODO, row=1)
    d.component("w_evals", "z_work", "eval harness",
                "GREY: one evals.json data file,\nno runner, no baseline", fill=TODO, row=1)

    # ---------------------------------------------------------------- substrate services
    d.component("appr", "z_sub", "approvals",
                "streams · human_decision\n+ withdraw (used today)", fill=DONE)
    d.component("cont", "z_sub", "continuations",
                "VERIFIED: 3 decisions ->\n3 minutes runs", fill=DONE)
    d.component("mnot", "z_sub", "meeting_notifier",
                "AMBER: needs chat_id, which\nonly a resolved meeting has", fill=PART)
    d.component("unot", "z_sub", "usecase_notifier", "tells a submitter the outcome", fill=DONE)
    d.component("art", "z_sub", "artifacts store",
                "art:// by ref; file/s3/postgres", fill=DONE)
    d.component("agreg", "z_sub", "agentregistry",
                "port + litellm/null adapters", fill=DONE, row=1)
    d.component("apol", "z_sub", "apipolicy", "(method, path) -> Entra role", fill=DONE, row=1)
    d.component("mauth", "z_sub", "mcpauth", "shared-secret bearer", fill=DONE, row=1)
    d.component("upl", "z_sub", "review.uploads", "art:// staging for inputs", fill=DONE, row=1)

    # ---------------------------------------------------------------- domain core
    d.component("c_arch", "z_core", "archimate",
                "engine · notation · relrepair · xsd", fill=DONE)
    d.component("c_sem", "z_core", "semantic",
                "vocabularies · SKOS · SPARQL", fill=DONE)
    d.component("c_sp", "z_core", "speech",
                "Transcriber port · compare\n(script mix, not WER)", fill=DONE)
    d.component("c_col", "z_core", "collab", "CollabRepository port", fill=DONE)
    d.component("c_meet", "z_core", "meetings",
                "minutes · naming (names, not labels)", fill=DONE)
    d.component("c_vis", "z_core", "visio", "parsers · geometry recovery", fill=DONE)
    d.component("c_uc", "z_core", "usecase",
                "AMBER: gates/predicates live; cost join\n& obligations proven offline only", fill=PART)
    d.component("c_ref", "z_core", "reference",
                "retrieval as data (whole|key|vector)\nrecord passages · pins · drift", fill=DONE)
    d.component("c_ea", "z_core", "EARepository port",
                "GREY: no core/ea/port.py.\nadoit_rest imported concretely", fill=TODO, row=1)
    d.component("c_id", "z_core", "AgentIdentity port",
                "GREY: msal constructed directly\nin identity.py + graph_auth.py", fill=TODO, row=1)
    d.component("c_par", "z_core", "DocumentParser port",
                "GREY: parsers are concrete", fill=TODO, row=1)
    d.component("c_canon", "z_core", "canon", "canonical names", fill=DONE, row=1)

    # ---------------------------------------------------------------- platform kernel
    for cid, title, desc, fill, row in [
        ("p_cfg", "config", "the one address book", DONE, 0),
        ("p_con", "container", "DI roots (platform + substrate)", DONE, 0),
        ("p_ctr", "contracts", "tools · processes · AGENTS", DONE, 0),
        ("p_run", "runlog", "run rows, closed in one place", DONE, 0),
        ("p_wf", "workflows", "submit · lanes · finished stream", DONE, 0),
        ("p_str", "streams", "StreamGroup · serve · reclaim", DONE, 0),
        ("p_lock", "locks", "workload lock", DONE, 1),
        ("p_otel", "otel", "tracer; no-op when unset", DONE, 1),
        ("p_doc", "docparse", "image sizing in ONE place", DONE, 1),
        ("p_emb", "embed", "GatewayEmbedder -> nomic-embed-text\n3,345 passages indexed (v0.27)", DONE, 1),
        ("p_hook", "webhook", "the one outbound JSON POST", DONE, 1),
        ("p_reg", "staged_registry", "staged imports", DONE, 1),
    ]:
        d.component(cid, "z_plat", title, desc, fill=fill, row=row)

    # ---------------------------------------------------------------- state & external
    d.component("redis", "z_state", "Redis (in-substrate)", "streams · limiter · locks", fill=DONE)
    d.component("neon", "z_state", "Neon Postgres",
                "keys · spend · artifacts · agents\n+ ref_* corpus (signed, ringed, pinned)", fill=DONE)
    d.component("jaeger", "z_state", "Jaeger", "one trace per run", fill=DONE)
    d.component("bucket", "z_state", "Upload bucket (S3)", "art:// inputs", fill=DONE)
    d.component("ollama", "z_state", "Ollama Cloud", "kimi-k3 · glm-flash · gpt-oss", fill=DONE)
    d.component("embedder", "z_state", "Embedder (Railway ollama)",
                "nomic-embed-text, 768-d, on a volume", fill=DONE, row=1)
    d.component("entra", "z_state", "Entra ID", "1 app registration per agent", fill=DONE)
    d.component("adoit", "z_state", "ADOIT:CE",
                "AMBER: reads work,\nwrites edge-blocked", fill=PART)
    d.component("m365", "z_state", "Microsoft 365 Graph", "recordings · files · meetings", fill=DONE)
    d.component("el", "z_state", "ElevenLabs", "best of 3 on every recording", fill=DONE, row=1)
    d.component("as", "z_state", "AssemblyAI", "close second", fill=DONE, row=1)
    d.component("mu", "z_state", "Munsit",
                "AMBER: runs, but 3/3 unusable\n(18% Arabic script, -30% words)", fill=PART, row=1)
    d.component("sx", "z_state", "Soniox / soniox-en",
                "AMBER: built + credentialed,\nNOT in SPEECH_LANES", fill=PART, row=1)
    d.component("pg_local", "z_state", "Local Postgres",
                "GREY: fully-offline mode\nnever built (Neon is cloud)", fill=TODO, row=1)

    # ---------------------------------------------------------------- systems & boundaries
    d.system("THE LAB (one image, one build)", ["z_gov", "z_ports", "z_work", "z_sub"], "#6C8EBF")
    d.system("SOURCE TIERS (import downward only)", ["z_core", "z_plat"], "#82B366")
    d.trust_boundary("EGRESS TRUST BOUNDARY · every LLM, tool and A2A call crosses here", "z_people")

    d.security("z_gov", "Entra JWT · virtual key · per-tool ACL · PII redaction")
    d.security("z_ports", "shared-secret bearer · granted per team")
    d.security("z_work", "no store credentials · art:// refs only")
    d.security("z_state", "credentials live here, never in a workload")

    # ---------------------------------------------------------------- the value path only
    # Deliberately sparse. Every client reaching the gateway, the gateway reaching all nine MCP
    # servers, and every workload reaching its domain package is TRUE but unreadable: it was 32
    # long cross-band fans and the A* router pushed them through boxes (H2). The tier bands already
    # say "everything above reaches everything below"; what they cannot say is the ORDER a meeting
    # actually travels in, so that is what is drawn.
    for s_, t_ in [("teams_chat", "flow"), ("flow", "gw"), ("review", "gw"), ("cc", "gw")]:
        d.edge(s_, t_, "xtrust")                       # crosses the egress boundary
    for s_, t_ in [("gw", "m_wf"), ("gw", "m_sp"), ("gw", "m_col")]:
        d.edge(s_, t_, "sync")                         # the three the meeting path uses
    for s_, t_ in [("m_wf", "w_tr"), ("w_tr", "appr"), ("appr", "cont"), ("cont", "w_min"),
                   ("w_min", "mnot")]:
        d.edge(s_, t_, "async")                        # queued, durable, one run per lane
    d.edge("auth", "entra", "identity")
    d.edge("m_sp", "el", "sync")
    d.edge("gw", "ollama", "sync")

    d.legend([
        ("DONE — deployed and exercised end to end", f"fillColor={DONE};strokeColor=#82B366;"),
        ("PARTIAL — built, with a named limitation", f"fillColor={PART};strokeColor=#D79B00;"),
        ("NOT BUILT — verified absent", f"fillColor={TODO};strokeColor=#999999;"),
        ("Synchronous (tool / HTTP)", "strokeColor=#1A1A1A;"),
        ("Async (stream / queue)", "strokeColor=#777777;dashed=1;dashPattern=6 6;"),
        ("Crosses the egress boundary", "strokeColor=#B85450;strokeWidth=2;"),
        ("Identity", "strokeColor=#9673A6;dashed=1;dashPattern=1 3;"),
    ])
    return d


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    diagram = build()
    # A*, NOT banded. `_render_banded` builds its nodes from (cid, zid, title, desc) and never
    # reads the per-component `fill` — verified in drawio_c4.py — so every box would take its band's
    # colour and the heatmap would say nothing. The A* path does `f = fill or zfill[zid]`, which is
    # exactly the per-component override this diagram exists for. Zone heights matter again in this
    # mode, hence the explicit `height=` on each band.
    xml = diagram.render(strict=False)
    path = OUT / "worktree-heatmap.drawio"
    path.write_text(xml)
    # counted from the tuple the engine actually stores: (cid, zid, title, desc, row, col, fill)
    counts = {DONE: 0, PART: 0, TODO: 0}
    for comp in diagram._comps:
        if comp[6] in counts:
            counts[comp[6]] += 1
    print(f"wrote {path}")
    print(f"violations: {diagram.violations}")
    print(f"green={counts[DONE]}  amber={counts[PART]}  grey={counts[TODO]}")
