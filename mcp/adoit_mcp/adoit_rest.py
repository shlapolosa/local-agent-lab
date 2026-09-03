"""ADOIT 18 REST 2.0 client — the read facade the adoit-mcp server exposes as governed tools.

The tenant is a full ADOIT 18 (verified live: GET /rest/2.0/version -> productVersion 18.0.0),
NOT the crippled Community Edition CLAUDE.md once assumed — search, object read, and (Phase 2)
create/patch/delete all work over REST. Credentials (Basic auth, repo id) come from the
environment and live only in this server; agents reach it through the gateway.

Verified endpoints (read):
  GET  /rest/2.0/repos                          -> repositories
  GET  /rest/2.0/repos/{repo}/search?query=<url-encoded JSON>   -> search (see build_query)
  GET  /rest/2.0/repos/{repo}/objects/{objId}   -> one object with attributes + relations
Search query needs a NON-EMPTY filter (empty -> HTTP 400). Filters AND together:
  {"filters":[{"className":"C_APPLICATION_COMPONENT"},
              {"attrName":"NAME","op":"OP_LIKE","value":"portal"}],
   "scope":{"repoObjects":true,"models":true,"modObjects":true}}
Result items: {id, name, type, artefactType(REPOSITORY_OBJECT|DIAGRAM|MODINST), metaName(C_*),
               groupId, modelId, modelName, link, attributes}.
Write endpoints exist too (OPTIONS /objects/{id} -> PATCH,DELETE; POST /objects) — Phase 2.
"""
from __future__ import annotations

import base64
import json
import os
import re
import urllib.parse
import urllib.request

REST = "/rest/2.0"
_CAMEL = re.compile(r"(?<!^)(?=[A-Z])")


def archimate_to_classname(atype: str) -> str:
    """ArchiMate type -> ADOIT className: CamelCase -> C_UPPER_SNAKE (verified for every class in
    the live repo, incl. CourseOfAction -> C_COURSE_OF_ACTION, WorkPackage -> C_WORK_PACKAGE)."""
    return "C_" + _CAMEL.sub("_", atype).upper()


def classname_to_archimate(cn: str) -> str:
    """ADOIT className -> ArchiMate type: C_APPLICATION_COMPONENT -> ApplicationComponent."""
    body = cn[2:] if cn.startswith("C_") else cn
    return "".join(p.capitalize() for p in body.split("_"))


def _cfg():
    base = os.environ["ADOIT_BASE_URL"].rstrip("/")
    repo = os.environ["ADOIT_REPO_ID"]                       # keep the {curly-braces} — ADOIT expects them
    auth = base64.b64encode(f'{os.environ["ADOIT_USERNAME"]}:{os.environ["ADOIT_PASSWORD"]}'.encode()).decode()
    return base, repo, auth


def _get(path: str, timeout: int = 30):
    base, repo, auth = _cfg()
    url = f"{base}{REST}/repos/{urllib.parse.quote(repo, safe='{}')}{path}"
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def build_query(name_like: str = "", class_name: str = "", scope: str = "objects") -> dict:
    """Assemble a valid ADOIT search query. `class_name` may be an ArchiMate type
    (ApplicationComponent) or a raw ADOIT className (C_APPLICATION_COMPONENT). At least one of
    name_like / class_name is required (an empty filter is a 400)."""
    filters = []
    if class_name:
        cn = class_name if class_name.startswith("C_") else archimate_to_classname(class_name)
        filters.append({"className": cn})
    if name_like:
        filters.append({"attrName": "NAME", "op": "OP_LIKE", "value": name_like})
    if not filters:
        raise ValueError("search needs name_like or class_name (an empty filter returns HTTP 400)")
    scopes = {
        "objects": {"repoObjects": True},
        "models": {"models": True},
        "all": {"repoObjects": True, "models": True, "modObjects": True},
    }
    return {"filters": filters, "scope": scopes.get(scope, scopes["objects"])}


def search(name_like: str = "", class_name: str = "", scope: str = "objects", limit: int = 50) -> list[dict]:
    q = urllib.parse.quote(json.dumps(build_query(name_like, class_name, scope)))
    data = _get(f"/search?query={q}")
    out = []
    for it in (data.get("items") or [])[:limit]:
        out.append({
            "id": it.get("id"), "name": it.get("name"),
            "class": classname_to_archimate(it.get("metaName", "")) if it.get("metaName") else it.get("type"),
            "className": it.get("metaName"), "artefactType": it.get("artefactType"),
            "groupId": it.get("groupId"), "modelId": it.get("modelId"), "modelName": it.get("modelName"),
        })
    return out


def _attr_value(a: dict):
    return a.get("value") if a.get("value") not in (None, "") else a.get("values")


def get_object(object_id: str, keep_attrs: int = 12) -> dict:
    """One object: identity + a trimmed set of non-empty attributes + its relations
    ({type, target_id, target_name}). ADOIT returns ~58 attributes; most are empty/system."""
    item = _get(f"/objects/{urllib.parse.quote(object_id, safe='{}')}").get("item", {})
    attrs = []
    for a in item.get("attributes", []):
        v = _attr_value(a)
        if v not in (None, "", []):
            attrs.append({"name": a.get("name"), "value": v})
        if len(attrs) >= keep_attrs:
            break
    # Each relation is a slot {name, metaName(RC_*), targets:[{id, name, type, direction, ...}]};
    # flatten the populated ones (most slots are empty). `name` is the ArchiMate relation label.
    rels = []
    for slot in item.get("relations", []) or []:
        for t in slot.get("targets", []) or []:
            rels.append({
                "type": slot.get("name"), "direction": t.get("direction"),
                "target_id": t.get("id"), "target_name": t.get("name"),
                "target_class": classname_to_archimate(t.get("metaName", "")) if t.get("metaName") else t.get("type"),
            })
    return {
        "id": item.get("id"), "name": item.get("name"),
        "class": classname_to_archimate(item.get("metaName", "")) if item.get("metaName") else item.get("type"),
        "className": item.get("metaName"), "groupId": item.get("groupId"),
        "attributes": attrs, "relations": rels,
    }
