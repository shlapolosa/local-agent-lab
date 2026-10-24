"""The front door as an OpenAPI (Swagger 2.0) document — the LOW-CODE inbound adapter, generated.

A pro-code caller reaches a process through MCP tools generated from `ProcessSpec`; a low-code caller
(Power Automate, Power Apps, Copilot Studio) reaches the same `/api` routes through a CUSTOM CONNECTOR,
and a connector is imported from exactly this document. Generating it from the same two sources the
other surfaces use — `PROCESSES` for the per-process routes and the gateway's operation table for
everything else — keeps ONE source for the inbound contract: a process registered once appears as an
MCP tool, a REST route and a connector action, and a parity test holds the document to the table.

WHY SWAGGER 2.0. Power Platform custom connectors import OpenAPI 2.0 only (not 3.x), want a unique
`operationId` and a short `summary` per operation, and cap the document at 1 MB. Process operations
take the MCP tool's name as their `operationId`, so an action in a flow and a tool call in a trace
carry the same name.

SECURITY. The document declares Entra sign-in as `oauth2` `accessCode`, the form the connector wizard
recognises on import. Custom connectors have no client-credentials grant, so a connection carries the
signed-in PERSON's delegated token; the gateway accepts it on `/api` when the person holds the
operation's app role, and holds the body's `actor` / `requester` to the token (user decision 24 Oct
2026, `gateway/custom_auth.py`). Flows calling `/api` with an HTTP action and client credentials keep
working unchanged.

The operation table is PASSED IN (`lab.substrate.apipolicy.OPERATIONS`), never imported: the platform
does not import the substrate.
"""
from __future__ import annotations

import re
from typing import Iterable, Protocol
from urllib.parse import urlparse

from lab.platform.contracts import PROCESSES, ProcessSpec, WorkflowTools

__all__ = ["openapi", "path_template"]

SEGMENT = r"[^/]+"            # one path segment, as the operation table writes it
SUMMARY_MAX = 80


class Operation(Protocol):
    name: str
    method: str
    pattern: re.Pattern[str]
    role: str
    description: str


def _singular(word: str) -> str:
    return word[:-2] if word.endswith("sses") else word[:-1] if word.endswith("s") else word


def path_template(pattern: str, prefix: str, segment: str = SEGMENT) -> str:
    """`<escaped prefix>/processes/[^/]+/runs` -> `/processes/{process}/runs`: one parameter per
    segment, named after the collection it indexes, matching exactly what the pattern matches."""
    path = pattern[len(re.escape(prefix)):]
    path = re.sub(r"/([^/]+)/" + re.escape(segment),
                  lambda m: f"/{m.group(1)}/{{{_singular(m.group(1))}}}", path)
    # a literal the pattern had to escape (`openapi\.json`) is a plain character in a URL template
    return re.sub(r"\\(.)", r"\1", path)


#: Query parameters an operation reads, by operation name. Data, not inference: a query string is not
#: in the path pattern, so the table cannot say it.
QUERY: dict[str, tuple[tuple[str, str, str], ...]] = {
    "processes.runs": (("q", "string", "Text to look for in the runs' own fields"),
                       ("limit", "integer", "How many to return")),
    "approvals.list": (("history", "integer", "Instead of what is open, the last N decisions"),
                       ("full", "boolean", "Each open approval in full, as the single read returns it")),
    "board.list": (("limit", "integer", "How many finished runs to return"),),
    "requests.list": (("limit", "integer", "How many submissions to return"),),
    "artifacts.get": (("ref", "string", "The art:// reference to fetch"),),
}

#: Operations whose body is FILES, not JSON — the multipart field the store reads (storage-mcp's
#: `/uploads` takes one or more parts named `files`).
FILE_UPLOADS = {"uploads.put": "files"}
#: Operations that answer BYTES, not JSON.
BINARY = {"artifacts.get"}

#: Request bodies, by operation name. An operation with a body and no entry takes a free object.
DECIDE_BODY = {
    "type": "object", "required": ["decision", "actor"],
    "properties": {
        "decision": {"type": "string", "enum": ["approve", "decline", "update"],
                     "description": "approve | decline | update (= changes requested; stays open)"},
        "actor": {"type": "string", "description": "The signed-in person deciding — never the system"},
        "channel": {"type": "string", "description": "Which client relayed it, recorded as api:<channel>"},
        "comment": {"type": "string", "description": "Why, in the person's words"},
        "answer": {"type": "object", "description": "The answer to the approval's question, keyed by label"},
        "card": {"type": "object", "description": "A card's flat response; the lab shapes it into `answer`"},
    },
}
BODIES = {"approvals.decide": DECIDE_BODY}

SECURITY = {"entra": {
    "type": "oauth2", "flow": "accessCode",
    "authorizationUrl": "https://login.microsoftonline.com/common/oauth2/authorize",
    "tokenUrl": "https://login.microsoftonline.com/common/oauth2/token",
    "scopes": {}}}


def _summary(text: str) -> str:
    first = re.split(r"(?<=[.;—])\s|\s\(", text.strip(), maxsplit=1)[0].rstrip(".;—: ")
    first = first[:1].upper() + first[1:]
    return first if len(first) <= SUMMARY_MAX else first[:SUMMARY_MAX - 1].rstrip() + "…"


def _path_params(path: str) -> list[dict]:
    return [{"name": n, "in": "path", "required": True, "type": "string", "x-ms-summary": n}
            for n in re.findall(r"{(\w+)}", path)]


def _query_params(name: str) -> list[dict]:
    return [{"name": q, "in": "query", "required": False, "type": t, "description": d, "x-ms-summary": q}
            for q, t, d in QUERY.get(name, ())]


def _operation(op_id: str, summary: str, description: str, path: str, *, query: str = "",
               body: dict | None = None, status: str = "200", internal: bool = False,
               files: str = "", binary: bool = False) -> dict:
    params = _path_params(path) + _query_params(query)
    if files:
        params.append({"name": files, "in": "formData", "required": True, "type": "file",
                       "x-ms-summary": files})
    elif body is not None:
        params.append({"name": "body", "in": "body", "required": True, "schema": body})
    response = ({"description": "The bytes", "schema": {"type": "file"}} if binary
                else {"description": "OK", "schema": {"type": "object"}})
    out = {"operationId": op_id, "summary": _summary(summary), "description": description,
           "parameters": params,
           "produces": ["application/octet-stream"] if binary else ["application/json"],
           "responses": {status: response}}
    if files:
        out["consumes"] = ["multipart/form-data"]
    elif body is not None:
        out["consumes"] = ["application/json"]
    if internal:
        # a connector cannot consume server-sent events; documented for parity, hidden from makers
        out["x-ms-visibility"] = "internal"
    return out


def _process_paths(spec: ProcessSpec) -> dict[str, dict]:
    from lab.platform.submit_schema import input_schema
    runs, run = f"/processes/{spec.name}/runs", f"/processes/{spec.name}/runs/{{run}}"
    verbs = WorkflowTools.verbs_for(spec)
    paths: dict[str, dict] = {runs: {}, run: {}, f"{run}/events": {}}
    # Summaries lead with the verb and end with the process NAME: a maker scans a list of actions,
    # and a title is a sentence too long to scan (several exceed the 80-character limit).
    if "submit" in verbs:
        paths[runs]["post"] = _operation(spec.tool("submit"), f"Start a run of {spec.name}",
                                         f"{spec.title}. {spec.description}", runs,
                                         body=input_schema(spec), status="202")
    paths[runs]["get"] = _operation(spec.tool("runs"), f"Find runs of {spec.name}",
                                    f"Runs of {spec.title}, newest first.", runs, query="processes.runs")
    paths[run]["get"] = _operation(spec.tool("status"), f"Get one run of {spec.name}",
                                   f"Status and outputs of one run of {spec.title}.", run)
    paths[f"{run}/events"]["get"] = _operation(f"{spec.name}_events", f"Watch one run of {spec.name}",
                                               "Server-sent events as the run moves.",
                                               f"{run}/events", internal=True)
    return paths


def openapi(base_url: str, operations: Iterable[Operation], *, prefix: str = "/api",
            title: str = "Lab front door", version: str = "1.0") -> dict:
    """The Swagger 2.0 document for the front door at `base_url`.

    Per-process routes come from `PROCESSES` (typed bodies, MCP tool names); every other row of
    `operations` becomes one generic operation. A row whose path indexes `/processes/{process}` is
    covered by the per-process expansion and not repeated."""
    url = urlparse(base_url)
    paths: dict[str, dict] = {}
    for spec in PROCESSES.values():
        for path, item in _process_paths(spec).items():
            paths.setdefault(path, {}).update(item)
    for op in operations:
        path = path_template(op.pattern.pattern, prefix)
        if path.startswith("/processes/{process}"):
            continue
        method = op.method.lower()
        body = BODIES.get(op.name, {"type": "object"}) if method in ("post", "put", "patch") else None
        paths.setdefault(path, {})[method] = _operation(
            op.name.replace(".", "_"), op.description, op.description, path, query=op.name, body=body,
            files=FILE_UPLOADS.get(op.name, ""), binary=op.name in BINARY)
    return {"swagger": "2.0",
            "info": {"title": title, "version": version,
                     "description": "Start and follow the lab's business processes, and answer its "
                                    "human approvals. Generated from the process registry."},
            "host": url.netloc, "basePath": prefix, "schemes": [url.scheme or "https"],
            "consumes": ["application/json"], "produces": ["application/json"],
            "securityDefinitions": SECURITY, "security": [{name: []} for name in SECURITY],
            "paths": {p: item for p, item in paths.items() if item}}
