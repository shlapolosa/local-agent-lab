"""ADOIT REST 2.0 client — the read facade the adoit-mcp server exposes as governed tools, plus a
DORMANT write facade.

What the tenant allows (the same truth as src/lab/platform/config.py `ADOIT_REST_WRITE`, which owns the
policy — do not restate it elsewhere): the hosted Community Edition (adoit-ce.boc-cloud.com)
runs ADOIT 18 (GET /rest/2.0/version -> productVersion 18.0.0) and serves the READ endpoints
below; its edge proxy BLOCKS the write verbs (POST/PATCH/DELETE -> a "URL not available" page).
So `search`/`get_object`/`object_impact` are live tools, while `create_object`/`patch_object`/
`delete_object`/`create_relation` are grounded (verified against the tenant OpenAPI + OPTIONS)
but stay unused until ADOIT_REST_WRITE=true on a write-capable tenant — today the write path is
the human-gated two-file import (Excel objects + ArchiMate XML views). Credentials (Basic auth,
repo id) come from the environment and live only in this server; agents reach it through the
gateway.

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

Write endpoints (dormant behind ADOIT_REST_WRITE — shapes verified against the tenant's OpenAPI +
BOC developer-examples; OPTIONS advertises /objects -> POST and /objects/{id} -> PATCH,DELETE,
but the hosted CE edge refuses the calls):
  POST   /objects                              create_object  body {name, metaName:C_*, attributes:[{metaName:A_*, value}]}
  PATCH  /objects/{id}                         patch_object   body {name?, attributes:[{metaName:A_*, value}]}
  DELETE /objects/{id}                         delete_object
  POST   /objects/{src}/relations/{dir}/{RC_*} create_relation body {toId:<tgt>}   (dir = outgoing|incoming)
Attributes are keyed by their machine metaName (A_DESCRIPTION, A_APPL_CATEGORY, ...) with a typed
value (STRING/ENUM/INTEGER/UTC), NOT the display name. Relation classes are RC_<UPPER_SNAKE> — every
ArchiMate relation we emit maps 1:1 onto a class present in the tenant metamodel (RC_COMPOSITION,
RC_SERVING, RC_REALIZATION, RC_ASSIGNMENT, RC_ACCESS, RC_AGGREGATION, RC_ASSOCIATION, RC_TRIGGERING,
RC_FLOW, RC_INFLUENCE, RC_SPECIALIZATION). Objects are natively versioned (A_OBJECT_VERSION,
A_OBJECT_VERSION_HISTORY, A_LIFECYCLE_STATE, A_OBJECT_STATE, A_VALID_FROM/UNTIL_UTC) and SHARED —
a repository-object write propagates to EVERY view that places it (only geometry is per-diagram), so
object writes are high-blast-radius and stay human-gated in the server. When enabled, writes run ONLY
inside the server's approval-gated import tool after a human decision, never from an agent directly.
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


def _req(method: str, path: str, body: dict | None = None, timeout: int = 30):
    """One ADOIT REST call under /repos/{repo}. GET/POST/PATCH/DELETE; body is JSON-encoded.
    Returns parsed JSON, or {} for an empty (e.g. 204) response. Raises urllib HTTPError on 4xx/5xx
    so the caller (the server's approval-gated tool) surfaces the real ADOIT error."""
    base, repo, auth = _cfg()
    url = f"{base}{REST}/repos/{urllib.parse.quote(repo, safe='{}')}{path}"
    headers = {"Authorization": f"Basic {auth}", "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode().strip()
    if raw.startswith("<"):
        # The hosted CE edge answers a blocked verb with an HTML page (HTTP 200, "URL not available on
        # this server"), not JSON — name the cause instead of failing with a JSONDecodeError at char 0.
        text = " ".join(re.sub(r"<[^>]+>", " ", raw).split())[:160]
        raise ValueError(f"ADOIT {method} {path}: response is not JSON but an HTML page — the hosted CE "
                         f"edge blocks REST write verbs: {text!r}")
    return json.loads(raw) if raw else {}


def _get(path: str, timeout: int = 30):
    return _req("GET", path, timeout=timeout)


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


# --------------------------------------------------------------------------------------------------
# Phase 2 — write facade (create / update / relate / delete). Every function here is a raw REST call;
# governance (approval gate, ACL, tracing) lives in the server tools that call these, never here.
# --------------------------------------------------------------------------------------------------

def archimate_to_relclass(rtype: str) -> str:
    """ArchiMate relation type -> ADOIT relation className: RC_<UPPER_SNAKE>. Verified 1:1 against the
    tenant metamodel for Composition/Aggregation/Assignment/Realization/Serving/Access/Association/
    Triggering/Flow/Influence/Specialization."""
    return "RC_" + _CAMEL.sub("_", rtype).upper()


def _obj_path(object_id: str) -> str:
    return f"/objects/{urllib.parse.quote(object_id, safe='{}')}"


def create_object(name: str, class_name: str, attributes: list[dict] | None = None,
                  description: str | None = None) -> dict:
    """POST /objects — create a repository object. `class_name` may be an ArchiMate type
    (ApplicationComponent) or a raw className (C_APPLICATION_COMPONENT). `attributes` are
    [{metaName: A_*, value}] pairs; `description` is a convenience for A_DESCRIPTION. Returns the
    created object's REST payload (carries the new id)."""
    cn = class_name if class_name.startswith("C_") else archimate_to_classname(class_name)
    attrs = list(attributes or [])
    if description and not any(a.get("metaName") == "A_DESCRIPTION" for a in attrs):
        attrs.append({"metaName": "A_DESCRIPTION", "value": description})
    body: dict = {"name": name, "metaName": cn}
    if attrs:
        body["attributes"] = attrs
    return _req("POST", "/objects", body)


def patch_object(object_id: str, name: str | None = None,
                 attributes: list[dict] | None = None) -> dict:
    """PATCH /objects/{id} — partial in-place update. Send ONLY what changed: an optional new `name`
    and/or a list of [{metaName: A_*, value}] attributes. ADOIT bumps A_OBJECT_VERSION natively and the
    change propagates to every view placing this object."""
    body: dict = {}
    if name is not None:
        body["name"] = name
    if attributes:
        body["attributes"] = attributes
    if not body:
        raise ValueError("patch_object needs a name and/or attributes to change")
    return _req("PATCH", _obj_path(object_id), body)


def delete_object(object_id: str) -> dict:
    """DELETE /objects/{id} — remove a repository object. HIGH BLAST RADIUS: removes it from every
    view. Called only after explicit human approval (server enforces this)."""
    return _req("DELETE", _obj_path(object_id))


def create_relation(src_id: str, rel_type: str, target_id: str, direction: str = "outgoing") -> dict:
    """POST /objects/{src}/relations/{direction}/{RC_*} body {toId: target} — link two objects.
    `rel_type` may be an ArchiMate relation (Composition) or a raw className (RC_COMPOSITION);
    `direction` is outgoing|incoming (from the source object's perspective)."""
    rc = rel_type if rel_type.startswith("RC_") else archimate_to_relclass(rel_type)
    d = direction.lower()
    if d not in ("outgoing", "incoming"):
        raise ValueError("direction must be 'outgoing' or 'incoming'")
    path = f"{_obj_path(src_id)}/relations/{d}/{rc}"
    return _req("POST", path, {"toId": target_id})


def object_impact(object_id: str, name: str = "", limit: int = 50) -> list[dict]:
    """Read-only blast-radius probe: the diagrams (views) that place this object, so a reviewer sees
    what an object write/delete will touch. Searches modObjects by the object's name and collects the
    distinct hosting models; falls back to reading the object's name when not supplied."""
    if not name:
        name = get_object(object_id).get("name", "")
    if not name:
        return []
    q = urllib.parse.quote(json.dumps({
        "filters": [{"attrName": "NAME", "op": "OP_LIKE", "value": name}],
        "scope": {"modObjects": True},
    }))
    data = _get(f"/search?query={q}")
    views: dict[str, dict] = {}
    for it in (data.get("items") or [])[:limit]:
        if it.get("artefactType") == "MODINST" and it.get("modelId"):
            views.setdefault(it["modelId"], {"view_id": it["modelId"], "view_name": it.get("modelName")})
    return list(views.values())
