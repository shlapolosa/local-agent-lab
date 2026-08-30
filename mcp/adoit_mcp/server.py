"""adoit-mcp — MCP facade over the ArchiMate engine + the ADOIT:CE repository.

Runs as streamable HTTP so it can register with the LiteLLM MCP gateway (the lab's
governance plane): agents connect to ONE gateway endpoint; this server holds the ADOIT
credentials (injected from the environment, never given to agents) and imports the same
engine library the archimate-adoit skill uses — one implementation, two access paths.

Tools:
  archimate_validate(spec)        -> ArchiMate legality warnings for a model spec
  archimate_render(spec, outdir)  -> .archimate.xml + per-view SVGs + layout report
  adoit_repos()                   -> repositories visible to the lab's ADOIT account (REST, read)
  adoit_import_instructions()     -> the governed write path (ADOIT:CE = UI import)

Model spec (JSON): {
  "name": str, "id": str?,
  "elements":  [{"id","type","name","doc"?}],
  "relations": [{"type","src","tgt","id"?,"accessType"?}],
  "views":     [{"id","title","elements":[...]}],   # scoped views; auto_edges applied
  "standard_views": bool                            # add the mapping-view catalogue
}

Run:  python3 server.py            (port 9100, path /mcp)
"""
import base64
import json
import os
import sys
import urllib.request

from fastmcp import FastMCP

SKILL_SCRIPTS = os.path.join(
    os.path.dirname(__file__), "..", "..", ".claude", "skills", "archimate-adoit", "scripts")
sys.path.insert(0, os.path.abspath(SKILL_SCRIPTS))
from archimate_engine import Model  # noqa: E402

mcp = FastMCP("adoit-mcp")


def _build(spec):
    m = Model(spec["name"], spec.get("id", "model"))
    for e in spec.get("elements", []):
        m.el(e["id"], e["type"], e["name"], e.get("doc"))
    for r in spec.get("relations", []):
        m.rel(r["type"], r["src"], r["tgt"], rid=r.get("id"), accessType=r.get("accessType"))
    for v in spec.get("views", []):
        vw = m.view(v["id"], v["title"])
        vw.place(*v["elements"])
        vw.auto_edges()
    if spec.get("standard_views"):
        m.standard_views()
    return m


@mcp.tool()
def archimate_validate(spec: dict) -> dict:
    """Check a model spec against ArchiMate legality rules (no rendering).
    Returns warnings (semantic) — an empty list means the model is clean."""
    m = _build(spec)
    return {"elements": len(m.elements), "relations": len(m.relations),
            "warnings": m.validate_relations()}


@mcp.tool()
def archimate_render(spec: dict, outdir: str, basename: str) -> dict:
    """Validate, lay out and render a model spec to ADOIT-importable Model Exchange XML
    plus one SVG preview per view. Fails on layout-invariant violations; returns the
    written file paths, per-view canvas sizes and any ArchiMate legality warnings."""
    m = _build(spec)
    report = m.render(outdir, basename, strict=True)
    return report


@mcp.tool()
def adoit_repos() -> dict:
    """List ADOIT repositories visible to the lab's service account (read-only REST call;
    credentials are injected by this server — agents never see them)."""
    base = os.environ["ADOIT_BASE_URL"]
    cred = base64.b64encode(
        f'{os.environ["ADOIT_USERNAME"]}:{os.environ["ADOIT_PASSWORD"]}'.encode()).decode()
    req = urllib.request.Request(f"{base}/rest/2.0/repos",
                                 headers={"Authorization": f"Basic {cred}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


@mcp.tool()
def adoit_import_instructions() -> str:
    """The governed write path into ADOIT:CE (its REST write endpoints are disabled)."""
    return (
        "ADOIT:CE write path (verified Aug 2026): REST 2.0 write endpoints return 403, so "
        "imports go through the UI. 1) Log in at " + os.environ.get("ADOIT_BASE_URL", "") +
        " 2) Menu -> Import/Export -> ArchiMate Model Exchange File -> upload the "
        ".archimate.xml. 3) Decline any auto-layout offer so the generated geometry "
        "survives. 4) Confirm interfaces render as icons (toggle representation to symbol "
        "if not). Re-imports never overwrite: ADOIT places same-named models/objects in new "
        "groups — delete stale import groups after regeneration. Human approval required "
        "before every import (lab approval-gate policy)."
    )


if __name__ == "__main__":
    # .env is loaded by the launcher; fail fast if credentials are missing
    for k in ("ADOIT_BASE_URL", "ADOIT_USERNAME", "ADOIT_PASSWORD"):
        if k not in os.environ:
            sys.exit(f"missing env var {k} — source .env before starting")
    mcp.run(transport="http", host="127.0.0.1", port=9100, path="/mcp")
