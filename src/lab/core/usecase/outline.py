"""A step's output as a bounded OUTLINE — what the run board shows a person watching a run.

Pure and deterministic: the same output always outlines the same way, bounded per string, per list
and overall, and a truncation always says so. Writing it onto the board is the workload's job
(`lab.workloads.usecase.derivation.stamp_shape`); deciding what a row is called is not.
"""
from __future__ import annotations


__all__ = ["LIST_SHOWN", "MAX_BYTES", "MAX_CHARS", "MAX_ITEMS", "outline"]


#: What an outline may carry onto the run log. Every frame the live view sends carries this, so it
#: is bounded three ways — per string, per list, and overall — and a truncation always SAYS so.
MAX_CHARS = 200


#: Sized to the steps that actually run rather than to a round number: step 5 matched THIRTEEN
#: capabilities against a ceiling of twelve, so the page said `truncated` and a reader could not
#: tell whether the one it dropped was the one they were looking for. Still bounded — this rides
#: every frame to every watcher — and a truncation still says so.
MAX_ITEMS = 40


MAX_BYTES = 12000


#: What a record calls itself, in the order a record is likely to use. Records in this corpus name
#: themselves differently by step — a capability by `capability_id`, an element by `name` — and
#: guessing one field would render the rest as an empty label.
#: An ID beats a FUNCTION here, and that ordering was paid for: `capability_label` is optional in
#: the coverage_map schema and the model routinely omits it, so the chain fell through to
#: `function` and a 38-row match rendered as "prepare design pack" seven times — the thing each
#: match was made FROM, repeated once per capability it matched to. An id at least names the thing
#: decided and is distinct per row. `function` stays last so an entry carrying nothing else is
#: still named.
#: `source` is deliberately NOT here. It is PROVENANCE, not a name, and it won over the fields
#: that identify a row: an obligation rendered as "baseline" instead of "G01 · prompt and registry
#: integrity". A field earns a place here only if it NAMES the thing.
_LABELS = ("capability_label", "label", "name", "title", "what", "capability_id", "id", "function")


def _paired(item: dict) -> str:
    """A row that RELATES two things, named by both — or "" for a row that names one.

    One naming field per row made distinct rows render identically (wfr-886957c31872, 29 Sep 2026):
    step 5's matches are (function, capability) PAIRS, and showing the capability alone printed
    "Custom agent hosting" four times for four different functions; step 6's shortlist showed the
    bare L3 id, hiding the route and the product that made each row different."""
    capability = str(item.get("capability_label") or item.get("capability_id") or "").strip()
    if item.get("function") and capability:
        status = str(item.get("status") or "").strip()
        return f"{item['function']} → {capability}" + (f" · {status}" if status else "")
    if item.get("capability_id") and item.get("route") and item.get("realisation"):
        return (f"{item['capability_id']} · {item['route']}: {item['realisation']}"
                + (" (preferred)" if item.get("preferred") else ""))
    # A workflow step: the id joins the graph, the activity is what a person reads (steps 10, 17),
    # and on step 15 the TIER is the decision itself. All three rendered as a bare `n1` before.
    if item.get("id") and item.get("activity"):
        return f"{item['id']} · {item['activity']}"
    if item.get("id") and item.get("tier"):
        return (f"{item['id']} · {item['tier']}"
                + (f" ({item['necessity']})" if item.get("necessity") else ""))
    # A connector, an edge or a facet override: the ends, plus what qualifies them — an edge's
    # data class drives its obligations, and an override without its facet says nothing.
    if item.get("from") and item.get("to"):
        return (f"{item['facet']}: " if item.get("facet") else "") + f"{item['from']} → {item['to']}" \
            + (f" · {item['data_class']}" if item.get("data_class") else "")
    return ""


#: A nested list names this many members and counts the rest.
LIST_SHOWN = 6


#: How a member of a NESTED list is named — the shortest thing that tells two members apart. A
#: full label per member (`G01 · G01 prompt and registry integrity · baseline`) fills the line
#: with the first one and leaves no room for the others, which is the fault this replaced.
_MEMBER_KEYS = ("guardrail", "artifact_id", "capability_id", "id")


def _member(item) -> str:
    if isinstance(item, dict):
        for field in _MEMBER_KEYS:
            if item.get(field):
                return str(item[field]) + (f" {item['version']}" if item.get("version") else "")
    return _label(item)


def _members(items: list) -> str:
    """A list inside a value, as its members — `G06, G12` — never `2 × G06`.

    Measured on wfr-6598d006731b (29 Sep 2026): "N × <first>" read as N COPIES and hid every
    member after the first — a family bound to two different guardrails, eleven different pinned
    artifacts, all rendered as one repeated. The count survives as "+k more" once the list is
    longer than a line can hold."""
    if not items:
        return "none"
    shown = [_member(i) for i in items[:LIST_SHOWN]]
    rest = len(items) - len(shown)
    return ", ".join(shown) + (f" +{rest} more" if rest else "")


def outline(out) -> dict:
    """What a step produced, for a reader watching the run: values, and lists of what is in them.

    It used to report TYPES (`problem: str`), on the argument that the run's content belongs behind
    the review app's decision surface. That argument did not survive contact with the page: the
    subject — `frame.problem`, model output — is already its heading, in full. A type name where a
    value would fit protected nothing and cost the reader the only thing they opened the row for.
    So the gate is the control, and this is what it guards.

    Bounded, because this rides every frame to every watcher, and a truncation is always named:
    a partial answer indistinguishable from a complete one is the failure this codebase keeps
    running into.
    """
    if not isinstance(out, dict):
        return {}
    outlined: dict = {}
    for key, value in out.items():
        if isinstance(value, str):
            outlined[key] = _clip(value)
        elif isinstance(value, (list, tuple, set)):
            items = list(value)
            outlined[key] = {"count": len(items),
                             "items": [_label(i) for i in items[:MAX_ITEMS]],
                             **({"truncated": True} if len(items) > MAX_ITEMS else {})}
        elif isinstance(value, dict):
            # `key: value`, not the keys alone. A heat map rendered as
            # "commodity, mature, meets_target, source" is the QUESTION written out — the reader
            # opened the row for the answer, and every one of them was thrown away here.
            outlined[key] = {"count": len(value),
                             "items": [_clip(f"{k}: {_label(v)}")
                                       for k, v in list(value.items())[:MAX_ITEMS]],
                             **({"truncated": True} if len(value) > MAX_ITEMS else {})}
        else:
            outlined[key] = value
    return _fit(outlined)


def _clip(text: str) -> str:
    text = str(text)
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + "\u2026"


def _label(item) -> str:
    """One entry as a READER would name it — the human-facing field first.

    `capability_id` used to lead, so thirteen matched capabilities rendered as `tec-cap-0031` and
    twelve siblings: an id is how a record is joined, not what was decided. The id is still the
    fallback, because naming something badly beats naming it not at all.
    """
    if isinstance(item, (list, tuple, set)):
        # A LIST as a value — `by_step` is `{step: [obligation, ...]}`, a family's guardrails —
        # named by its members; the record holds each member in full.
        return _clip(_members(list(item)))
    if isinstance(item, dict):
        paired = _paired(item)
        if paired:
            return _clip(paired)
        for field in _LABELS:
            if item.get(field):
                return _clip(str(item[field]))
        # No field NAMES the row, so show what it SAYS. This used to join the dict's keys, which
        # rendered fifteen selected components as "capability, component_id, component,
        # rejected_alternatives" fifteen times — the column headings, once per row. Nine
        # array-of-object fields across seven steps land here, so the fallback is what was fixed.
        #
        # Scalars only: a nested list is the row's own detail, and splicing it into a one-line
        # label is how a row stops being readable. A row of nothing but containers says what it
        # holds rather than coming back empty.
        # A number or a flag keeps its NAME: step 18's `n1: 2 · 2` could not say which was exposure.
        # Text names itself, so it goes bare.
        scalars = [str(v).strip() if isinstance(v, str) else f"{k} {v}" for k, v in item.items()
                   if v not in (None, "", [], {}) and not isinstance(v, (list, dict, tuple, set))]
        if scalars:
            return _clip(" · ".join(scalars[:3]))
        return _clip(", ".join(f"{k}({len(v)})" if isinstance(v, (list, tuple, set)) else str(k)
                               for k, v in list(item.items())[:3]))
    return _clip(str(item))


def _fit(outlined: dict) -> dict:
    """Drop whole fields, largest first, until the outline fits. Dropping a FIELD leaves the rest
    readable; trimming inside one would make every value suspect."""
    import json

    while len(json.dumps(outlined)) > MAX_BYTES and outlined:
        biggest = max(outlined, key=lambda k: len(json.dumps(outlined[k])))
        outlined.pop(biggest)
        outlined["…"] = "some fields omitted — the record has them in full"
    return outlined
