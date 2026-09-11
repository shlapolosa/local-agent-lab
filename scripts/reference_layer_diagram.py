"""The reference layer and the use-case intake pipeline, in detail — the area the reference-layer
redesign (Sep 2026) touched, drawn as code so it is regenerated as components land, not at the end.

    .venv/bin/python scripts/reference_layer_diagram.py
    .venv/bin/python scripts/drawio_to_png.py var/out/architecture/reference-layer.drawio
    cp var/out/architecture/reference-layer.* docs/architecture/

Same colour rule as `worktree_heatmap.py` (docs/architecture/README.md): GREEN is deployed AND
exercised end to end, AMBER is built with a NAMED limitation stated in the box, GREY is verified
absent. The colour and its reason are edited on the same line, or the colour is decoration.

A* layout, not banded: the banded renderer never reads a per-component `fill` (see the heatmap).
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
    d = C4Diagram("local-agent-lab · reference layer & use-case intake (main @ 83442b7+)", width=2600)

    d.zone("z_people", "PEOPLE & SURFACES", stroke="#D79B00", height=180, comp_fill="#FFE6CC")
    d.zone("z_gov", "GATEWAY · LiteLLM (the single egress)", stroke="#B85450", height=180,
           comp_fill="#F8CECC")
    d.zone("z_ports", "CAPABILITY PORTS · MCP servers", stroke="#3A7CA5", height=260,
           comp_fill="#D7E8F2")
    d.zone("z_work", "WORKLOADS · the four intake processes (no store credentials)", stroke="#6C8EBF",
           height=260, comp_fill="#DAE8FC")
    d.zone("z_sub", "SUBSTRATE SERVICES & OPERATOR SCRIPTS", stroke="#9673A6", height=180,
           comp_fill="#E1D5E7")
    d.zone("z_core", "DOMAIN CORE · lab.core (imports nothing above it)", stroke="#82B366", height=260,
           comp_fill="#D5E8D4")
    d.zone("z_state", "STATE & EXTERNAL SYSTEMS", stroke="#7A7A7A", height=180, comp_fill="#EDEDED")

    # ---------------------------------------------------------------- people & surfaces
    d.component("submit", "z_people", "review app · Submit",
                "intake groups rendered FROM the\ncorpus (intake-fields, under a pin)", fill=DONE)
    d.component("approve", "z_people", "review app · Review",
                "VERIFIED 11 Sep: item form for a\nnon-voice question, {label:{value}}", fill=DONE)
    d.component("teams", "z_people", "Teams card / Copilot connector",
                "AMBER: card shows the choices;\nno connector has answered a class yet", fill=PART)
    d.component("uiprobe", "z_people", "LiteLLM UI · Test Vector Store",
                "VERIFIED 10 Sep: ad-hoc search,\nattributed adhoc/gateway-<date>", fill=DONE)

    # ---------------------------------------------------------------- gateway
    d.component("gw_api", "z_gov", "/api front door",
                "per-operation Entra app roles;\nsubmit · status · approvals decide", fill=DONE)
    d.component("gw_vs", "z_gov", "/v1/vector_stores/<map>/search",
                "pg_vector provider -> reference-mcp;\nstores are DB registry objects (CD)", fill=DONE)
    d.component("gw_emb", "z_gov", "/v1/embeddings",
                "nomic-embed-text via EMBED_URL;\nPII-redacted like any prompt", fill=DONE)
    d.component("gw_mcp", "z_gov", "/mcp · per-team grants",
                "reference_mcp read grant to every\nintake team; workflow_mcp to none", fill=DONE)

    # ---------------------------------------------------------------- ports
    d.component("m_ref", "z_ports", "reference-mcp :9700",
                "reference_pin · lookup · search ·\npin_info · catalogue (v0.27, ring 0)", fill=DONE)
    d.component("m_vs", "z_ports", "vector-store façade",
                "OpenAI page shape; filters carry\npin/run/process/field or go ad hoc", fill=DONE)
    d.component("m_wf", "z_ports", "workflow-mcp :9400",
                "screening_submit only — design has\nNO entry point (continuation)", fill=DONE)
    d.component("m_appr", "z_ports", "approval tools",
                "approvals_ask(fields=) · decide;\nquestion kind still 'speaker-mapping'", fill=DONE)
    d.component("m_dec", "z_ports", "decision-mcp :9800",
                "VERIFIED: readiness verdict under\na pin (gate C failed honestly)", fill=DONE, row=1)
    d.component("m_val", "z_ports", "valuation-mcp :9900",
                "AMBER: valuation_cost join proven\noffline only — never reached live", fill=PART, row=1)
    d.component("m_lib", "z_ports", "McpReferenceLibrary",
                "decision/valuation/review read the\ncorpus via reference-mcp, no DSN", fill=DONE, row=1)
    d.component("m_sem", "z_ports", "semantic-mcp :9200",
                "AMBER: still parses the workbooks\ninto memory for ArchiMate export", fill=PART, row=1)

    # ---------------------------------------------------------------- workloads
    d.component("w_scr", "z_work", "use_case_screening",
                "VERIFIED 11 Sep: pins, steps 3-5,7,9,10;\nleaves matcher 7.7 min; asks the class", fill=DONE)
    d.component("w_cov", "z_work", "coverage matchers",
                "drill | leaves | vector; leaves chosen\n(F1 .41/.56); budget 200k fits the map", fill=DONE)
    d.component("w_pin", "z_work", "usecase.reference",
                "pin · drift · records · attribution;\nevery run pins REFERENCE_ARTIFACTS", fill=DONE)
    d.component("w_des", "z_work", "use_case_design",
                "AMBER: re-pins, records drift, then\nHALTS at gate C (3 tenant corpora absent)", fill=PART)
    d.component("w_gate", "z_work", "step gates [D]",
                "VERIFIED 11 Sep: step 3 judges the\nowner's NAME; step 21 by catalogue id", fill=DONE, row=1)
    d.component("w_cost", "z_work", "step 23 · cost join",
                "AMBER: PriceLine × envelope × volume\nproven by spine tests only", fill=PART, row=1)
    d.component("w_inv", "z_work", "use_case_investment",
                "AMBER: deployed, never reached\n(design halts at gate C)", fill=PART, row=1)
    d.component("w_pro", "z_work", "use_case_provisioning",
                "AMBER: deployed, never reached\n(design halts at gate C)", fill=PART, row=1)
    d.component("w_absent", "z_work", "steps 6 · 8 · 11",
                "GREY: landscape, service levels,\nsource classification — no corpora", fill=TODO, row=1)

    # ---------------------------------------------------------------- substrate & scripts
    d.component("cont", "z_sub", "continuations",
                "VERIFIED 10 Sep: approve -> design run;\nreleased_request_id on the approval", fill=DONE)
    d.component("pub", "z_sub", "reference.publish",
                "AMBER: workbook -> records+passages;\n1 INSERT per Neon round trip (~25 min/map)", fill=PART)
    d.component("regvs", "z_sub", "register_vector_stores (CD)",
                "reconciles VectorStores to the DB;\na yaml registry is deleted by the list", fill=DONE)
    d.component("evalh", "z_sub", "scripts/eval_coverage",
                "AMBER: harness ran 3 matchers × 2 cases;\nall below 0.60 recall target", fill=PART)

    # ---------------------------------------------------------------- core
    d.component("c_model", "z_core", "reference.model",
                "Retrieval whole|key|vector on artifact\nAND version; Pin.searchable; Passage.record_id",
                fill=DONE)
    d.component("c_derive", "z_core", "reference.derive · cells · workbook",
                "record passages (FIELD_SEP); rows();\ncapability_table keyed (id,parent,level)", fill=DONE)
    d.component("c_err", "z_core", "reference.errors",
                "NotPinned · NotSearchable ·\nIndexUnavailable — typed refusals", fill=DONE)
    d.component("c_gates", "z_core", "usecase.gates · predicates",
                "readiness A-D; canonical_criticality;\nNAMED_CONDITIONS as rules", fill=DONE, row=1)
    d.component("c_cost", "z_core", "usecase.cost",
                "AMBER: envelope_for lives in code —\nbelongs in the criticality taxonomy", fill=PART, row=1)
    d.component("c_rules", "z_core", "usecase.composition · obligations",
                "take their rows as REQUIRED args;\nseed ratchet is empty", fill=DONE, row=1)

    # ---------------------------------------------------------------- state
    d.component("neon", "z_state", "Neon · ref_* tables",
                "53 artifacts @ v0.27 ring 0; 3,345\npassages; pin/consumption trail", fill=DONE)
    d.component("trail", "z_state", "ref_consumption",
                "AMBER: query_digest holds the query\nin PLAIN TEXT, not a digest", fill=PART)
    d.component("embedder", "z_state", "Embedder (Railway ollama)",
                "nomic-embed-text 768-d, volume;\n32-text batches, 300 s, 4 retries", fill=DONE)
    d.component("ollama", "z_state", "Ollama Cloud · kimi-k3",
                "AMBER: account-wide session limit\n(~3.5 h) hit 10 Sep by eval + run", fill=PART)
    d.component("wb", "z_state", "BA Guild workbooks",
                "licensed; travel by art:// ref only;\nnever committed", fill=DONE)

    d.system("THE LAB (one image, one build)", ["z_gov", "z_ports", "z_work", "z_sub"], "#6C8EBF")
    d.security("z_gov", "every corpus read through the gateway is granted, metered, traced")
    d.security("z_work", "workloads read the corpus by pin; never a DSN")
    d.security("z_state", "reader DSN in the substrate only; signing seed in var/run")

    # the value path: a submission to a halted design, and how the corpus reaches it
    for s_, t_ in [("submit", "gw_api"), ("approve", "gw_api"), ("uiprobe", "gw_vs")]:
        d.edge(s_, t_, "xtrust")
    d.edge("gw_api", "m_wf", "sync"); d.edge("gw_vs", "m_vs", "sync"); d.edge("gw_mcp", "m_ref", "sync")
    d.edge("m_wf", "w_scr", "async"); d.edge("w_scr", "m_appr", "async")
    d.edge("m_appr", "cont", "async"); d.edge("cont", "w_des", "async")
    d.edge("w_pin", "m_ref", "sync"); d.edge("w_des", "m_dec", "sync"); d.edge("w_des", "m_val", "sync")
    d.edge("m_lib", "m_ref", "sync"); d.edge("m_ref", "neon", "sync"); d.edge("m_vs", "gw_emb", "sync")
    d.edge("gw_emb", "embedder", "sync"); d.edge("pub", "gw_emb", "sync"); d.edge("pub", "neon", "sync")
    d.edge("regvs", "gw_vs", "sync"); d.edge("w_scr", "ollama", "sync")

    d.legend([
        ("DONE — deployed and exercised end to end", f"fillColor={DONE};strokeColor=#82B366;"),
        ("PARTIAL — built, with a named limitation", f"fillColor={PART};strokeColor=#D79B00;"),
        ("NOT BUILT — verified absent", f"fillColor={TODO};strokeColor=#999999;"),
    ])
    return d


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    xml = build().render(strict=False)
    path = OUT / "reference-layer.drawio"
    path.write_text(xml)
    print(f"wrote {path}")
