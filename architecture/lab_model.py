"""Lab architecture model — authored per the archimate-adoit skill method
(behaviour -> active -> passive per layer, then relationships, strictest first).
Source of truth: Local-Agentic-Prototyping-Platform.docx v0.3 + the running stack.

Emits architecture/lab_model.json — the spec consumed by the adoit-mcp tools
through the LiteLLM gateway (see run_via_gateway.py). Element ids are STABLE:
changing them causes duplicate objects on ADOIT re-import.
"""
import json
import os

E, R = [], []


def el(eid, t, name, doc=None):
    E.append({"id": eid, "type": t, "name": name, **({"doc": doc} if doc else {})})


def rel(t, s, g, **kw):
    R.append({"type": t, "src": s, "tgt": g, **kw})


# ---------- Motivation ----------
el("driver-azure", "Driver", "Azure-first enterprise strategy")
el("goal-parity", "Goal", "Pattern parity with Azure at zero licence cost",
   "Every prototype agent authenticates, egresses through a gateway, is metered, PII-scanned and traced")
el("principle-gw", "Principle", "Single gateway for all egress")
el("req-gov", "Requirement", "All traffic authenticated, metered, traced")
el("req-pii", "Requirement", "No unredacted PII crosses the egress boundary")

# ---------- Strategy ----------
el("cap-apa", "Capability", "Agentic Process Automation")
el("coa-cloud", "CourseOfAction", "Cloud-first inference",
   "No local models; 7B-class local inference out of scope on 8 GB")
el("res-lab", "Resource", "M1 MacBook prototyping lab")

# ---------- Business ----------
el("actor-ea", "BusinessActor", "DOH Enterprise Architect")
el("svc-auto", "BusinessService", "Business Process Automation")
el("proc-biz", "BusinessProcess", "Automated Business Process",
   "Pilot processes run as Agent Framework workflows")

# ---------- Application ----------
el("comp-gw", "ApplicationComponent", "LiteLLM Proxy",
   "Governance plane: /v1, /mcp, A2A; virtual keys, budgets, rate limits, tool ACLs")
el("if-v1", "ApplicationInterface", "/v1 (OpenAI)")
el("if-mcp", "ApplicationInterface", "/mcp (MCP gateway)")
el("if-a2a", "ApplicationInterface", "A2A")
el("svc-route", "ApplicationService", "Model Routing")
el("svc-tools", "ApplicationService", "Tool Gateway",
   "Central MCP registry; per-key tool filtering; upstream credential injection")
el("svc-a2a", "ApplicationService", "A2A Mediation")
el("comp-host", "ApplicationComponent", "Workflow Host (Agent Framework)",
   "One async Python host per business process (~100 MB idle)")
el("comp-presidio", "ApplicationComponent", "Presidio PII Middleware")
el("comp-guard", "ApplicationComponent", "Guardrails Middleware",
   "Prompt-injection and output scanning; heavy checks delegated to cloud LLM-judge")
el("svc-redact", "ApplicationService", "PII Redaction",
   "Prompts, tool arguments and results redacted before egress")
el("svc-exec", "ApplicationService", "Workflow Execution")
el("comp-adoitmcp", "ApplicationComponent", "ADOIT MCP Server",
   "FastMCP facade: ArchiMate engine + ADOIT REST reads; holds ADOIT credentials")
el("svc-ea", "ApplicationService", "EA Model Generation",
   "ArchiMate validate/render; ADOIT-importable Model Exchange XML")
el("data-keys", "DataObject", "Virtual Keys & Budgets")
el("data-cards", "DataObject", "A2A Agent Cards")
el("data-model", "DataObject", "ArchiMate Model (Exchange XML)")

# ---------- Technology ----------
el("node-mac", "Node", "M1 MacBook (8 GB, macOS)")
el("ss-python", "SystemSoftware", "Python 3.12 (.venv)")
el("ss-uvicorn", "SystemSoftware", "Uvicorn")
el("ss-fastmcp", "SystemSoftware", "FastMCP 3")
el("ss-prisma", "SystemSoftware", "Prisma Client",
   "LiteLLM ORM to the Neon key/spend store")
el("node-ollama", "Node", "Ollama Cloud")
el("tsvc-infer", "TechnologyService", "Model Inference",
   "gpt-oss:120b primary, glm-5.3-flash utility; OpenAI-compatible")
el("node-entra", "Node", "Entra ID Tenant (free)")
el("tsvc-id", "TechnologyService", "Identity & OAuth2",
   "One app registration per agent; MSAL locally; OAuth2 for MCP flows")
el("node-jaeger", "SystemSoftware", "Jaeger v2 (native binary)",
   "Trace store + UI; in-memory storage; ~50 MB RSS instead of a 2 GB Colima VM")
el("if-otlp", "TechnologyInterface", "OTLP")
el("tsvc-trace", "TechnologyService", "Trace Collection",
   "Trace tree per workflow run; doubles as audit trail")
el("node-adoit", "Node", "ADOIT:CE (BOC Cloud)")
el("if-rest", "TechnologyInterface", "REST API (read-only)",
   "Only /rest/2.0/repos works on CE; writes go through governed UI import")
el("tsvc-repo", "TechnologyService", "EA Repository")

el("ss-redis", "SystemSoftware", "Redis (Homebrew)",
   "Gateway limiter/budget/router state and the approval event streams")
el("node-neon", "Node", "Neon Postgres (cloud)")
el("tsvc-keystore", "TechnologyService", "Key & Spend Store",
   "LiteLLM teams, virtual keys, budgets, spend logs, skills")
el("tsvc-events", "TechnologyService", "Approval Event Bus",
   "Redis Streams approvals:requests / approvals:decisions; consumer group per channel")
el("comp-review", "ApplicationComponent", "Architecture Review App (Streamlit)",
   "Approval channel with diagrams, model contents, trace link")
el("comp-telegram", "ApplicationComponent", "Telegram Approval Channel",
   "Same contract as the review app; plumbing only until a bot token is configured")
el("svc-approval", "ApplicationService", "Import Approval",
   "approve / decline / changes-requested from any channel")
el("data-approvals", "DataObject", "Approval Events (requests, decisions)")
el("proc-approve", "BusinessProcess", "Approve EA Repository Change")

# ---------- Implementation & Migration ----------
el("wp1", "WorkPackage", "Scaffold Lab Repository")
el("wp2", "WorkPackage", "Build ADOIT MCP Server")
el("wp3", "WorkPackage", "Implement Pilot Processes")
el("wp4", "WorkPackage", "Evaluate ADOIT 18 Tenant")
el("plateau-1", "Plateau", "Lab Operational")
el("plateau-2", "Plateau", "Pilots Live")

# ---------- Relationships (strictest applicable type; direction = source acts on target) ----------
# motivation / strategy
rel("Influence", "driver-azure", "goal-parity")
rel("Realization", "req-gov", "principle-gw")
rel("Realization", "req-pii", "goal-parity")
rel("Realization", "cap-apa", "goal-parity")
rel("Realization", "coa-cloud", "goal-parity")
rel("Assignment", "res-lab", "cap-apa")
# business
rel("Serving", "svc-auto", "actor-ea")
rel("Realization", "proc-biz", "svc-auto")
rel("Realization", "svc-auto", "cap-apa")
# application core / gateway
rel("Composition", "comp-gw", "if-v1")
rel("Composition", "comp-gw", "if-mcp")
rel("Composition", "comp-gw", "if-a2a")
rel("Realization", "comp-gw", "svc-route")
rel("Realization", "comp-gw", "svc-tools")
rel("Realization", "comp-gw", "svc-a2a")
rel("Realization", "comp-gw", "principle-gw")
rel("Serving", "svc-route", "comp-host")
rel("Serving", "svc-tools", "comp-host")
rel("Serving", "svc-a2a", "comp-host")
rel("Access", "comp-gw", "data-keys", accessType="ReadWrite")
rel("Access", "comp-gw", "data-cards", accessType="Read")
# workflow host + middleware (drawn, not nested — D0)
rel("Composition", "comp-host", "comp-presidio")
rel("Composition", "comp-host", "comp-guard")
rel("Realization", "comp-presidio", "svc-redact")
rel("Serving", "svc-redact", "comp-host")
rel("Realization", "svc-redact", "req-pii")
rel("Realization", "comp-host", "svc-exec")
rel("Serving", "svc-exec", "proc-biz")
# EA tooling
rel("Realization", "comp-adoitmcp", "svc-ea")
rel("Serving", "svc-ea", "actor-ea")
rel("Serving", "comp-adoitmcp", "comp-gw")
rel("Access", "comp-adoitmcp", "data-model", accessType="Write")
# technology — cloud backends
rel("Realization", "node-ollama", "tsvc-infer")
rel("Serving", "tsvc-infer", "comp-gw")
rel("Realization", "node-entra", "tsvc-id")
rel("Serving", "tsvc-id", "comp-gw")
rel("Serving", "tsvc-id", "comp-host")
rel("Composition", "node-jaeger", "if-otlp")
rel("Realization", "node-jaeger", "tsvc-trace")
rel("Serving", "tsvc-trace", "comp-host")
rel("Flow", "comp-host", "node-jaeger")
rel("Composition", "node-adoit", "if-rest")
rel("Realization", "node-adoit", "tsvc-repo")
rel("Serving", "tsvc-repo", "comp-adoitmcp")
# technology — local runtime subcomponents (the honest deployed stack)
rel("Composition", "node-mac", "ss-python")
rel("Composition", "node-mac", "ss-uvicorn")
rel("Composition", "node-mac", "ss-fastmcp")
rel("Composition", "node-mac", "ss-prisma")
rel("Serving", "ss-python", "comp-gw")
rel("Serving", "ss-python", "comp-host")
rel("Serving", "ss-python", "comp-adoitmcp")
rel("Serving", "ss-uvicorn", "comp-gw")
rel("Serving", "ss-uvicorn", "comp-adoitmcp")
rel("Serving", "ss-fastmcp", "comp-adoitmcp")
rel("Serving", "ss-prisma", "comp-gw")
# approval gate + runtime state
rel("Composition", "node-mac", "ss-redis")
rel("Composition", "node-mac", "node-jaeger")
rel("Serving", "ss-redis", "comp-gw")
rel("Realization", "ss-redis", "tsvc-events")
rel("Serving", "tsvc-events", "comp-adoitmcp")
rel("Serving", "tsvc-events", "comp-review")
rel("Serving", "tsvc-events", "comp-telegram")
rel("Realization", "node-neon", "tsvc-keystore")
rel("Serving", "tsvc-keystore", "comp-gw")
rel("Realization", "comp-review", "svc-approval")
rel("Realization", "comp-telegram", "svc-approval")
rel("Serving", "svc-approval", "comp-adoitmcp")
rel("Serving", "svc-approval", "proc-approve")
rel("Assignment", "actor-ea", "proc-approve")
rel("Access", "comp-adoitmcp", "data-approvals", accessType="Write")
rel("Access", "comp-review", "data-approvals", accessType="ReadWrite")
rel("Access", "comp-telegram", "data-approvals", accessType="ReadWrite")
# implementation & roadmap
rel("Triggering", "wp1", "wp2")
rel("Triggering", "wp2", "wp3")
rel("Triggering", "wp3", "wp4")
rel("Realization", "wp2", "plateau-1")
rel("Realization", "wp3", "plateau-2")
rel("Aggregation", "plateau-1", "comp-gw")
rel("Aggregation", "plateau-2", "comp-adoitmcp")

SPEC = {
    "name": "Local Enterprise-Agentic Prototyping Platform",
    "id": "lab-platform",
    "elements": E,
    "relations": R,
    "views": [
        {"id": "governance-plane", "title": "Governance Plane (scoped)",
         "elements": ["comp-gw", "if-v1", "if-mcp", "if-a2a", "svc-route", "svc-tools",
                      "svc-a2a", "comp-host", "comp-presidio", "comp-guard", "svc-redact",
                      "data-keys", "data-cards", "node-ollama", "tsvc-infer",
                      "node-entra", "tsvc-id", "node-jaeger", "if-otlp", "tsvc-trace"]},
        {"id": "tool-plane", "title": "Tool Plane — EA Modelling (scoped)",
         "elements": ["actor-ea", "svc-ea", "comp-adoitmcp", "svc-tools", "comp-gw",
                      "data-model", "node-adoit", "if-rest", "tsvc-repo"]},
        {"id": "runtime-stack", "title": "Local Runtime Stack (scoped)",
         "elements": ["comp-gw", "comp-host", "comp-adoitmcp", "comp-review", "node-mac", "ss-python",
                      "ss-uvicorn", "ss-fastmcp", "ss-prisma", "ss-redis", "node-jaeger",
                      "node-neon", "tsvc-keystore"]},
        {"id": "approval-loop", "title": "Approval Gate — EA Repository Writes (scoped)",
         "elements": ["actor-ea", "proc-approve", "svc-approval", "comp-review", "comp-telegram",
                      "data-approvals", "comp-adoitmcp", "tsvc-events", "ss-redis"]},
    ],
    "standard_views": True,
}

if __name__ == "__main__":
    out = os.path.join(os.path.dirname(__file__), "lab_model.json")
    json.dump(SPEC, open(out, "w"), indent=1)
    print(out, f"— {len(E)} elements, {len(R)} relationships, "
               f"{len(SPEC['views'])} scoped views + standard catalogue")
