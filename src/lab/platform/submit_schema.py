"""A process's SUBMIT body as a type and as a JSON schema — one derivation for every inbound surface.

Three surfaces describe the same call: the MCP tool `<process>_submit` (fastmcp derives its schema from a
signature), the REST route `POST /api/processes/<name>/runs`, and the generated OpenAPI document a
low-code client imports as a custom connector. Each used to be able to derive its own; now
`submit_parameters` is the one parameter list, the MCP server builds its signature from it, and
`input_schema` renders the same list as a self-contained JSON schema. A parity test holds the two
equal.

Not imported by `lab.platform.contracts` itself: pydantic is needed only by whoever renders a schema,
and the contract package must stay importable without it.
"""
from __future__ import annotations

import inspect
from typing import Annotated, Any, Literal

from lab.platform.contracts import InputKind, ProcessSpec

__all__ = ["ANNOTATION", "row_model", "annotation_of", "submit_parameters", "input_schema",
           "REQUIRED", "inline"]

#: Marks a parameter with no default — the caller must supply it.
REQUIRED = inspect.Parameter.empty

# an input field's kind -> the Python annotation its parameter declares. One table: a new kind is one
# line here and one in InputField.coerce.
ANNOTATION: dict[InputKind, Any] = {InputKind.REF: str, InputKind.REF_LIST: list[str],
                                    InputKind.HANDLE: str, InputKind.IDENTITY: str,
                                    InputKind.CONVERSATION: str, InputKind.TITLE: str,
                                    InputKind.MAPPING: dict[str, dict[str, str]],
                                    InputKind.CHOICE: str,
                                    # the fabric's kinds: a pointer is a small object, the rest are opaque ids
                                    InputKind.POINTER: dict[str, str], InputKind.EVENT: str,
                                    InputKind.CONTEXT: str, InputKind.ARTIFACT: str, InputKind.APPROVAL: str,
                                    # NUMBER is a figure, not prose for a formula to parse. TABLE's
                                    # annotation is BUILT per field from its declared columns —
                                    # `list[dict]` would teach a caller no more than an opaque bag —
                                    # so the entry here is only the fallback shape.
                                    InputKind.NUMBER: float, InputKind.TABLE: list[dict]}

REQUESTER = ("Who is asking (agent name, user principal or channel) — recorded on the request for "
             "audit.")
IDEMPOTENCY_KEY = ("Optional key that makes this call SAFE TO RETRY: submitting again with the SAME key "
                   "returns the SAME request_id (with duplicate: true) instead of queueing a second "
                   "run, for 24 hours. Use a stable id you already have for this piece of work (the "
                   "message, ticket or correlation id that asked for it) — never a fresh random value "
                   "per attempt. Omit it and every call is a new run, deliberately: re-submitting the "
                   "same diagram is a legitimate re-run.")


def row_model(field) -> Any:
    """A pydantic model for ONE row of a TABLE, built from the field's declared columns — so the schema
    carries named, typed columns with the required ones marked, the same reason a CHOICE becomes a
    `Literal` rather than a bare string."""
    import pydantic
    fields: dict[str, Any] = {}
    for column in field.columns:
        ann = (Literal[tuple(column.choices)] if column.kind is InputKind.CHOICE
               else ANNOTATION[column.kind])
        fields[column.name] = ((ann, ...) if column.required else (ann | None, None))
    return pydantic.create_model(f"{field.name}_row", **fields)


def annotation_of(field) -> Any:
    """The annotation of one input field.

    An OPTIONAL single reference also accepts `null`: LLM clients routinely fill every declared
    parameter, and pydantic would reject `None` against a bare `str` before `coerce` ever sees it.
    A CHOICE becomes a real `Literal`, so its members reach the schema as an `enum` a caller can SEE.
    """
    if field.kind is InputKind.TABLE:
        ann: Any = list[row_model(field)]          # type: ignore[valid-type]
    elif field.kind is InputKind.CHOICE:
        ann = Literal[tuple(field.choices)]
    else:
        ann = ANNOTATION[field.kind]
    return ann if field.required or field.kind is InputKind.REF_LIST else ann | None


def submit_parameters(spec: ProcessSpec) -> list[tuple[str, Any, str, Any]]:
    """`(name, annotation, description, default)` for every parameter of the submit call, inputs first
    and the two envelope fields last. `default` is `REQUIRED` for a field the caller must supply."""
    out = [(f.name, annotation_of(f), f.description,
            REQUIRED if f.required else ([] if f.kind is InputKind.REF_LIST else None))
           for f in spec.inputs]
    out.append(("requester", str, REQUESTER, "mcp"))
    out.append(("idempotency_key", str | None, IDEMPOTENCY_KEY, None))
    return out


def inline(schema: dict) -> dict:
    """A JSON schema with every `$ref` replaced by its definition and `title`s removed — the shape
    fastmcp hands an MCP client, and the shape a connector importer accepts without a definitions
    table."""
    defs = schema.get("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].rsplit("/", 1)[-1]])
            # `title` is dropped as a schema KEYWORD only; under `properties` the keys are field
            # names, and a field may well be called `title`.
            return {k: ({name: walk(sub) for name, sub in v.items()} if k == "properties" else walk(v))
                    for k, v in node.items() if k not in ("title", "$defs")}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node
    return walk(schema)


def input_schema(spec: ProcessSpec) -> dict:
    """The submit body of `spec` as a self-contained JSON schema."""
    import pydantic
    fields = {name: (Annotated[ann, pydantic.Field(description=desc)],
                     ... if default is REQUIRED else default)
              for name, ann, desc, default in submit_parameters(spec)}
    model = pydantic.create_model(f"{spec.name}_submit", __config__=pydantic.ConfigDict(extra="forbid"),
                                  **fields)
    return inline(model.model_json_schema())
