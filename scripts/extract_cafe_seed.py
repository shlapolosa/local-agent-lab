"""Extract the CAFÉ operationalisation artifacts into reviewable seed JSON.

The CAFÉ artifact visualisation (`CAFE_Artifacts_Visualisation_v0_25.html`) is the UPSTREAM
source: the Intake Agent requirements docx *reproduces* it in its annexures "so the development
team can implement the process without a second source". Seeding from upstream means a later CAFÉ
release is a re-extract rather than a re-transcription, and it carries two things the annexures
drop — the machine-evaluable guardrail TRIGGER PREDICATES, and the source register every citation
resolves into.

This is a GENERATOR, not production code (CLAUDE.md exempts scripts/ generators from TDD). Its
output — reviewed, committed JSON under `src/lab/core/usecase/seed/` — is the source of truth
thereafter, because a governed artifact must be diffable and signable. Neither the HTML nor the
docx is a runtime dependency and neither is committed.

Cost and the business case are the SPEC's own additions to the framework, so its Annexure F is the
only source for those — `--spec` extracts them from the docx alongside.

Usage:
    python scripts/extract_cafe_seed.py <html> --out src/lab/core/usecase/seed/
    python scripts/extract_cafe_seed.py <html> --out ... --spec <docx> --crosscheck <docx>

`--crosscheck` re-reads the docx annexures and compares the row counts and identifiers it can
match. A divergence is a real finding — the two are supposed to be the same artifacts at the same
version (the docx's G12 reads "RETIRED v0.25") — so it is reported and exits non-zero.
"""
from __future__ import annotations

import argparse
import html as htmllib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from lab.core.reference import cells
from lab.core.reference.master import render as render_master  # noqa: E402

# ---------------------------------------------------------------- JS literals

_WS = " \t\r\n"


class JsLiteralError(ValueError):
    """The source did not hold the literal we expected, at a position we can name."""


def _skip(src: str, i: int) -> int:
    while i < len(src):
        if src[i] in _WS:
            i += 1
        elif src.startswith("//", i):
            i = src.find("\n", i)
            if i < 0:
                return len(src)
        elif src.startswith("/*", i):
            end = src.find("*/", i)
            i = len(src) if end < 0 else end + 2
        else:
            return i
    return i


def _string(src: str, i: int) -> tuple[str, int]:
    quote = src[i]
    i += 1
    out: list[str] = []
    while i < len(src):
        c = src[i]
        if c == "\\":
            nxt = src[i + 1]
            out.append({"n": "\n", "t": "\t", "r": "\r"}.get(nxt, nxt))
            i += 2
        elif c == quote:
            return "".join(out), i + 1
        else:
            out.append(c)
            i += 1
    raise JsLiteralError(f"unterminated string from {i}")


def _value(src: str, i: int, env: dict | None = None):
    env = env or {}
    i = _skip(src, i)
    if i >= len(src):
        raise JsLiteralError("value expected, found end of source")
    c = src[i]
    if c in "\"'":
        return _string(src, i)
    if c == "[":
        items = []
        i = _skip(src, i + 1)
        if src[i] == "]":
            return items, i + 1
        while True:
            if src.startswith("...", i):          # spread of an already-parsed const
                i = _skip(src, i + 3)
                v, i = _value(src, i, env)
                if not isinstance(v, list):
                    raise JsLiteralError(f"spread at {i} is not a list: {type(v).__name__}")
                items.extend(v)
                i = _skip(src, i)
                if src[i] == ",":
                    i = _skip(src, i + 1)
                    if src[i] == "]":
                        return items, i + 1
                    continue
                if src[i] == "]":
                    return items, i + 1
                raise JsLiteralError(f"expected , or ] at {i}: {src[i:i+40]!r}")
            v, i = _value(src, i, env)
            items.append(v)
            i = _skip(src, i)
            if src[i] == ",":
                i = _skip(src, i + 1)
                if src[i] == "]":          # trailing comma
                    return items, i + 1
            elif src[i] == "]":
                return items, i + 1
            else:
                raise JsLiteralError(f"expected , or ] at {i}: {src[i:i+40]!r}")
    if c == "{":
        obj: dict = {}
        i = _skip(src, i + 1)
        if src[i] == "}":
            return obj, i + 1
        while True:
            i = _skip(src, i)
            if src[i] in "\"'":
                key, i = _string(src, i)
            else:
                m = re.compile(r"[A-Za-z_$][\w$]*").match(src, i)
                if not m:
                    raise JsLiteralError(f"expected a key at {i}: {src[i:i+40]!r}")
                key, i = m.group(0), m.end()
            i = _skip(src, i)
            if src[i] != ":":
                raise JsLiteralError(f"expected : after {key!r} at {i}")
            v, i = _value(src, i + 1, env)
            obj[key] = v
            i = _skip(src, i)
            if src[i] == ",":
                i = _skip(src, i + 1)
                if src[i] == "}":
                    return obj, i + 1
            elif src[i] == "}":
                return obj, i + 1
            else:
                raise JsLiteralError(f"expected , or }} at {i}: {src[i:i+40]!r}")
    m = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?").match(src, i)
    if m:
        text = m.group(0)
        return (float(text) if "." in text or "e" in text.lower() else int(text)), m.end()
    for word, val in (("true", True), ("false", False), ("null", None)):
        if src.startswith(word, i):
            return val, i + len(word)
    m = re.compile(r"[A-Za-z_$][\w$]*").match(src, i)
    if m:
        # A bare identifier inside a literal: a reference to a const parsed earlier
        # (M5_COMPS cites M5_ALL). Resolve it, or say which name we could not resolve.
        name = m.group(0)
        if name not in env:
            raise JsLiteralError(f"{name!r} referenced at {i} but not yet extracted; "
                                 f"parse it first (have: {sorted(env)})")
        return env[name], m.end()
    raise JsLiteralError(f"unparsable value at {i}: {src[i:i+40]!r}")


def js_const(src: str, name: str, env: dict | None = None):
    """The value of `const <name> = <literal>` — the literal only, parsed structurally.

    `env` supplies consts already extracted, because these literals cite each other."""
    m = re.search(rf"\b(?:const|let|var)\s+{re.escape(name)}\s*=\s*", src)
    if not m:
        raise JsLiteralError(f"{name}: not declared in this source")
    value, _ = _value(src, m.end(), env or {})
    return value


# ---------------------------------------------------------------- HTML tables

def _text(fragment: str) -> str:
    fragment = re.sub(r"<br\s*/?>", " ", fragment, flags=re.I)
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def tables(src: str) -> list[dict]:
    """Every <table>, with the heading that introduces it, its headers and its rows."""
    heads = [(m.start(), _text(m.group(1))) for m in
             re.finditer(r"<h[1-4][^>]*>(.*?)</h[1-4]>", src, re.S)]
    out = []
    for m in re.finditer(r"<table.*?</table>", src, re.S):
        block = m.group(0)
        prior = [h for h in heads if h[0] < m.start()]
        rows = []
        for tr in re.findall(r"<tr.*?</tr>", block, re.S):
            cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S)
            if cells:
                rows.append([_text(c) for c in cells])
        headers = [_text(c) for c in re.findall(r"<th[^>]*>(.*?)</th>", block, re.S)]
        out.append({"section": prior[-1][1] if prior else "",
                    "headers": headers,
                    "rows": rows[1:] if headers and rows else rows})
    return out


# ---------------------------------------------------------------- the mapping

SOURCE_ID = "CAFE_Artifacts_Visualisation_v0_25.html"

# table index -> (filename, key). Several artifacts are more than one table.
TABLE_FILES: dict[str, list[tuple[int, str]]] = {
    "process_steps":           [(2, "steps")],
    "input_artifacts":         [(3, "artifacts")],
    "output_artifacts":        [(4, "artifacts")],
    "domain_model":            [(5, "concepts")],
    "readiness_gates":         [(6, "gates"), (7, "verdicts")],
    "criticality_taxonomy":    [(8, "classes")],
    "capability_map_rules":    [(9, "definition"), (10, "levels"), (11, "heatmap")],
    "building_block_schema":   [(13, "fields")],
    "quality_attributes":      [(14, "scenario_parts"), (15, "envelope_patterns")],
    "service_contract_schema": [(18, "fields")],
    "tradeoff_catalogue":      [(19, "conflicts")],
    "decision_record_schema":  [(20, "fields")],
    "determinism_criteria":    [(21, "criteria")],
    "facet_schema":            [(22, "facets"), (23, "defaults"), (27, "readers")],
    "risk_derivation":         [(24, "properties"), (25, "classes"), (26, "moves")],
    "guardrail_mapping":       [(29, "mandatory_by_class")],
    "opportunity_obligations": [(30, "obligations")],
    "build_surface":           [(31, "decisions")],
    "surface_enforceability":  [(32, "matrix")],
    "component_families":      [(33, "families"), (34, "modifiers")],
    "composition_moves":       [(35, "moves")],
    "retired_guardrails":      [(36, "retired")],
}

# js const -> (filename, key)
JS_FILES: list[tuple[str, str, str]] = [
    ("guards",      "guardrails",         "guardrails"),
    ("capRows",     "ai_capability_map",  "capabilities"),
    ("sources",     "source_register",    "sources"),
    ("archetypes",  "archetypes",         "archetypes"),
    ("cmDomains",   "capability_domains", "domains"),
]

CAPABILITY_FIELDS = ("domain", "capability", "primary", "rationale", "alternative", "sources")
SOURCE_FIELDS = ("id", "title", "url")
DOMAIN_FIELDS = ("domain", "covers")

# Artifacts whose published VALUES are illustrative rather than authoritative. The doc says so of
# the price sheet ("the figures are illustrative of the structure; the live values are held in the
# artifact structured store and versioned"), and a run costed against one must be able to say so.
CAVEATS: dict[str, str] = {
    "price_sheet": "The figures are illustrative of the STRUCTURE; the live values are held in the "
                   "artifact structured store and versioned. Every costed line must cite the sheet "
                   "version it came from, and an estimate against this seed says so.",
    "benefit_drivers": "The formulas are authoritative; the reference VALUES (role rates, cost per "
                       "error) are held in their own registries and are not published here.",
}

#: Artifacts that exist only in the spec's Annexure F, not in the framework artifact set: cost and
#: the business case are this solution's own additions to CAFÉ. Extracted from the docx by table
#: index, the same way and with the same caveats.
SPEC_TABLE_FILES: dict[str, list[tuple[int, str]]] = {
    "price_sheet":            [(58, "lines")],
    "cost_formulas":          [(59, "formulas")],
    "benefit_drivers":        [(60, "drivers")],
    "financial_formulas":     [(61, "formulas")],
    "business_case_sections": [(62, "sections")],
    "intake_fields":          [(63, "field_groups")],
}
SPEC_SOURCE = "Intake_Agent_Requirements_v2_7.docx"


def _rows_as_dicts(rows, fields: tuple[str, ...]) -> list[dict]:
    return [dict(zip(fields, list(r) + [""] * (len(fields) - len(r)))) for r in rows]


def _clean(value):
    """Strip the presentation markup a few JS strings carry (`<b>RETIRED v0.25</b>`, `&mdash;`).

    These literals feed a browser, so a handful are HTML fragments. A governed record must hold the
    text, not the styling: a predicate evaluator comparing against `"<b>D2</b>"` would silently
    never match."""
    if isinstance(value, str):
        return _text(value) if re.search(r"<[a-zA-Z/]|&[a-zA-Z]+;|&#\d+;", value) else value
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    return value


def build(html_path: Path) -> dict[str, dict]:
    src = html_path.read_text(encoding="utf-8", errors="replace")
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", src, re.S)
    data_js = max(scripts, key=len)
    tabs = tables(src)

    files: dict[str, dict] = {}

    # These literals cite each other (M5_COMPS names M5_ALL), so parse into a shared environment
    # in dependency order and hand it to every later parse.
    env: dict = {}
    for const in ("M5_ALL", "M5_ZONES", "M5_COLS", "TOPO_TAGS", "M5_GASI",
                  "M5_COMPS", "M5_DETAIL", "TOPO_DETAIL"):
        env[const] = _clean(js_const(data_js, const, env))

    for const, name, key in JS_FILES:
        value = _clean(js_const(data_js, const, env))
        if const == "capRows":
            value = _rows_as_dicts(value, CAPABILITY_FIELDS)
        elif const == "sources":
            value = _rows_as_dicts(value, SOURCE_FIELDS)
        elif const == "cmDomains":
            value = _rows_as_dicts(value, DOMAIN_FIELDS)
        files[name] = {key: value}

    files["reference_architecture"] = {
        "archetypes": env["M5_ALL"],
        "zones": env["M5_ZONES"],
        "components": env["M5_COMPS"],
        "columns": env["M5_COLS"],
        "detail": env["M5_DETAIL"],
        "topologies": env["TOPO_DETAIL"],
        "topology_archetypes": env["TOPO_TAGS"],
        "guardrail_origin": env["M5_GASI"],
    }

    for name, parts in TABLE_FILES.items():
        payload: dict = {}
        for idx, key in parts:
            t = tabs[idx]
            payload[key] = {"section": t["section"], "headers": t["headers"], "rows": t["rows"]}
        files[name] = payload

    for name, payload in files.items():
        payload["_source"] = SOURCE_ID
        if name in CAVEATS:
            payload["_caveat"] = CAVEATS[name]
    return files


# ---------------------------------------------------------------- cross-check

# Divergences between the framework HTML and the spec's annexures that we have investigated and
# understood. Anything NOT listed here fails the extraction, because an unexplained difference
# between the upstream artifact and its reproduction is a defect in one of them.
KNOWN_DIVERGENCE: dict[str, str] = {
    "G09": "LIVE in the framework (ASI09, human confirmation for trust-sensitive effects) but "
           "absent from the spec's Annexure C — while the spec's OWN Annexure E.6 mandates it for "
           "exposure classes E2 and E3. A dangling reference: implementing from the spec alone, "
           "step 19 would resolve G09 to nothing. Seeded from the framework, which has it.",
    "G11": "RETIRED v0.25 (duplicate of G17, obligations merged, identifier not reused). The spec "
           "says two identifiers are retired but reproduces only G12. Benign — nothing cites G11.",
}



# ---------------------------------------------------------------- the human-readable master

#: Which key of a payload holds the rows a reader wants to see, and what to call the artifact.
#: Everything else in the payload is metadata or a second table, rendered after it.
TITLES: dict[str, str] = {
    "guardrails": "Guardrail set", "ai_capability_map": "AI capability map",
    "source_register": "Source register", "archetypes": "Agent archetypes",
    "capability_domains": "Capability domains", "readiness_gates": "Readiness gates",
    "criticality_taxonomy": "Criticality taxonomy",
    "determinism_criteria": "Determinism criteria register", "facet_schema": "Step facet schema",
    "risk_derivation": "Risk classes and derivation",
    "guardrail_mapping": "Risk class to guardrail mapping",
    "reference_architecture": "Reference architecture model",
    "tradeoff_catalogue": "Tradeoff catalogue", "price_sheet": "Reference price sheet",
    "component_families": "Component families", "surface_enforceability": "Surface enforceability",
    "quality_attributes": "Quality attribute patterns", "process_steps": "Process steps",
    "input_artifacts": "Input artifacts", "output_artifacts": "Output artifacts",
    "domain_model": "Domain model", "build_surface": "Build surface decisions",
    "composition_moves": "Composition moves", "retired_guardrails": "Retired identifiers",
    "opportunity_obligations": "Opportunity obligations",
    "building_block_schema": "EA building block schema",
    "service_contract_schema": "Service contract schema",
    "decision_record_schema": "Decision record schema",
    "capability_map_rules": "Business capability map rules", "intake_fields": "Intake fields",
    "cost_formulas": "Cost formulas", "benefit_drivers": "Benefit drivers",
    "financial_formulas": "Financial summary formulas",
    "business_case_sections": "Business case structure", "family_triggers": "Family triggers",
}


#: Columns for a section whose source rows are positional lists — the JS carries the order and not
#: the names, so the names are declared here once rather than guessed per reader.
ROW_COLUMNS = {"components": ("zone", "name", "detail", "archetypes")}

#: Keys that describe where a thing is DRAWN rather than what it is. Dropped from every rendered
#: master: a zone's fill colour is not part of the reference architecture, and carrying it into a
#: governed artifact would put diagram layout under a signature and into an agent's prompt.
LAYOUT_KEYS = frozenset({"x", "y", "w", "h", "fill", "stroke", "col", "row", "span"})

#: Whole SECTIONS that describe the drawing rather than the architecture. `columns` is how many
#: columns a zone is rendered in; publishing it would put a signature over a layout hint and invite
#: a reader to treat it as meaning.
LAYOUT_SECTIONS = frozenset({"columns"})

#: The id given to a row the source keys on an empty string.
DEFAULT_ID = "(all)"


def _rows_from(key: str, value: object):
    """(headers, rows) for any shape the seed actually uses, or None if it is not tabular.

    Four shapes appear and only the first was handled, which is why the reference architecture — a
    nested model of zones, components and topologies — could be published only as prose, and prose
    needs an embedder this lab does not have. It is structure, so it should publish as records.
    """
    if isinstance(value, dict) and value and all(isinstance(v, dict) for v in value.values()):
        headers = ["id"]
        for entry in value.values():
            headers += [k for k in entry if k not in headers and k not in LAYOUT_KEYS]
        # An EMPTY key is how the source spells "nothing selected — the whole diagram" (its own
        # title says "All archetypes"). A record needs an id a lookup can name, and a blank one is
        # refused by the publisher, correctly: it is not a key. Naming it is a translation the data
        # supports, not a value invented for it.
        return headers, [[ident or DEFAULT_ID] + [_cell(entry.get(h, "")) for h in headers[1:]]
                         for ident, entry in value.items()]
    if isinstance(value, dict) and value and not any(isinstance(v, dict) for v in value.values()):
        return ["id", "value"], [[k, _cell(v)] for k, v in value.items()]
    if isinstance(value, list) and value and all(isinstance(r, (list, tuple)) for r in value):
        headers = list(ROW_COLUMNS.get(key) or [f"column {i + 1}" for i in range(len(value[0]))])
        return headers, [[_cell(c) for c in row] for row in value]
    if isinstance(value, list) and value and all(isinstance(r, str) for r in value):
        return ["id"], [[r] for r in value]
    return None


#: The ONE encoder, shared with every adapter that has to read these bytes back. It used to live
#: here and be reversed, differently and incompletely, in decision-mcp.
_cell = cells.encode


def _rows_from(key: str, value: object):
    """(headers, rows) for any shape the seed actually uses, or None if it is not tabular.

    Four shapes appear and only the first was handled, which is why the reference architecture — a
    nested model of zones, components and topologies — could be published only as prose, and prose
    needs an embedder this lab does not have. It is structure, so it should publish as records.
    """
    if isinstance(value, dict) and value and all(isinstance(v, dict) for v in value.values()):
        headers = ["id"]
        for entry in value.values():
            headers += [k for k in entry if k not in headers and k not in LAYOUT_KEYS]
        # An EMPTY key is how the source spells "nothing selected — the whole diagram" (its own
        # title says "All archetypes"). A record needs an id a lookup can name, and a blank one is
        # refused by the publisher, correctly: it is not a key. Naming it is a translation the data
        # supports, not a value invented for it.
        return headers, [[ident or DEFAULT_ID] + [_cell(entry.get(h, "")) for h in headers[1:]]
                         for ident, entry in value.items()]
    if isinstance(value, dict) and value and not any(isinstance(v, dict) for v in value.values()):
        return ["id", "value"], [[k, _cell(v)] for k, v in value.items()]
    if isinstance(value, list) and value and all(isinstance(r, (list, tuple)) for r in value):
        headers = list(ROW_COLUMNS.get(key) or [f"column {i + 1}" for i in range(len(value[0]))])
        return headers, [[_cell(c) for c in row] for row in value]
    if isinstance(value, list) and value and all(isinstance(r, str) for r in value):
        return ["id"], [[r] for r in value]
    return None


def _cell(value: object) -> str:
    """One cell of a rendered table.

    A list becomes `a; b` and a nested object becomes its JSON — both so the value SURVIVES into
    the master rather than being rendered as a Python repr a parser cannot read back. Where a
    consumer needs the structure, its adapter parses this back; where a person reads it, it is
    still legible. `;` because the values here (topology ids, guardrail ids) never contain one.
    """
    if isinstance(value, (list, tuple)):
        return "; ".join(str(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return "" if value is None else str(value)


def _tabular(payload: dict) -> list[tuple[str, list[str], list[list]]]:
    """(section, headers, rows) for every part of a payload that is a table.

    Two shapes reach here: an extracted HTML table (`{headers, rows}`) and a list of dicts from the
    JS data. Both render as a table; a reader should not have to know which one they are looking at.
    """
    out = []
    for key, value in payload.items():
        if key.startswith("_") or key in LAYOUT_SECTIONS:
            continue
        if isinstance(value, dict) and "headers" in value:
            out.append((key, list(value["headers"]), [list(r) for r in value["rows"]]))
        elif (shaped := _rows_from(key, value)) and not (
                isinstance(value, list) and value and isinstance(value[0], dict)):
            out.append((key, shaped[0], shaped[1]))
        elif isinstance(value, list) and value and isinstance(value[0], dict):
            # The UNION of every row's keys, in first-seen order — not the first row's keys. One
            # family in fourteen carries a `topology` the others do not, and taking the first row's
            # keys dropped it from the master silently. The master is what `derived_from` asserts
            # the agent form came from, so a column missing here is a fact missing from the corpus
            # with a signature over it saying nothing is wrong.
            headers: list[str] = []
            for row in value:
                headers += [h for h in row if h not in headers]
            out.append((key, headers, [[_cell(row.get(h, "")) for h in headers] for row in value]))
    return out


def master_for(name: str, payload: dict) -> str:
    """The document a citation opens.

    Rendered rather than authored, and the metadata says so — "human-readable" here means "rendered
    for a person to read", not "typed by one". Claiming otherwise would be the kind of quiet
    overstatement the signature is supposed to make impossible.
    """
    title = TITLES.get(name, name.replace("_", " ").capitalize())
    meta = {"Artifact": name, "Source": payload.get("_source", ""),
            "Rendered": "generated from the source above by scripts/extract_cafe_seed.py"}
    if payload.get("_caveat"):
        meta["Caveat"] = payload["_caveat"]

    tables = _tabular(payload)
    if not tables:
        return render_master(title=title, headers=[], rows=[], meta=meta,
                             prose=json.dumps({k: v for k, v in payload.items()
                                               if not k.startswith("_")}, indent=2,
                                              ensure_ascii=False))
    section, headers, rows = tables[0]
    body = render_master(title=title, headers=headers, rows=rows, meta=meta)
    for section, headers, rows in tables[1:]:
        body += "\n" + render_master(title=f"{title} — {section}", headers=headers, rows=rows)
    return body


def masters_for(name: str, payload: dict) -> dict[str, str]:
    """One master per SECTION, because that is what the corpus can publish.

    A seed file often carries several tables — `facet_schema` holds the nine facets, the per-
    activity defaults, and which step reads which facet. They are three different things with three
    different shapes, and concatenating them into one document produced a record set whose natural
    key collided ("Activity" is a facet AND a defaults row), which the publisher correctly refused.

    So a multi-table artifact publishes as several: `facet-schema`, `facet-schema-defaults`,
    `facet-schema-readers`. A person still gets one document per table, each with its own heading
    and its own metadata, and a citation opens the table it actually came from rather than a
    three-table document with the relevant rows somewhere inside it.
    """
    tables = _tabular(payload)
    if len(tables) <= 1:
        return {name: master_for(name, payload)}
    title = TITLES.get(name, name.replace("_", " ").capitalize())
    meta = {"Artifact": name, "Source": payload.get("_source", ""),
            "Rendered": "generated from the source above by scripts/extract_cafe_seed.py"}
    if payload.get("_caveat"):
        meta["Caveat"] = payload["_caveat"]
    out = {}
    for index, (section, headers, rows) in enumerate(tables):
        key = name if index == 0 else f"{name}_{section}"
        out[key] = render_master(
            title=title if index == 0 else f"{title} — {section}",
            headers=headers, rows=rows, meta=dict(meta, Section=section))
    return out


def build_spec(docx_path: Path) -> dict[str, dict]:
    """The Annexure F artifacts, which exist only in the spec — cost and the business case are this
    solution's own additions to the framework."""
    try:
        from docx import Document  # type: ignore[import-not-found]
    except ImportError:                                    # pragma: no cover - dev convenience
        raise SystemExit("python-docx is required to extract the spec annexures")

    doc = Document(str(docx_path))
    files: dict[str, dict] = {}
    for name, parts in SPEC_TABLE_FILES.items():
        payload: dict = {}
        for idx, key in parts:
            table = doc.tables[idx]
            rows = [[c.text.strip() for c in r.cells] for r in table.rows]
            payload[key] = {"headers": rows[0], "rows": rows[1:]}
        payload["_source"] = SPEC_SOURCE
        if name in CAVEATS:
            payload["_caveat"] = CAVEATS[name]
        files[name] = payload
    return files


def crosscheck(files: dict[str, dict], docx_path: Path) -> list[str]:
    """Compare what we extracted against the docx annexures. An UNEXPLAINED divergence is a finding.

    They are meant to be the same artifacts at the same version (the docx's G12 reads
    "RETIRED v0.25"), so a difference is either a transcription error in the reproduction or a
    change upstream that the reproduction has not caught up with. Either way somebody must look.
    """
    try:
        from docx import Document  # type: ignore[import-not-found]
    except ImportError:                                    # pragma: no cover - dev convenience
        return ["python-docx is not installed; cannot cross-check"]

    doc = Document(str(docx_path))
    problems: list[str] = []

    def rows(i: int) -> list[list[str]]:
        return [[c.text.strip() for c in r.cells] for r in doc.tables[i].rows][1:]

    guard_ids = {g["id"] for g in files["guardrails"]["guardrails"]}
    docx_ids = {r[0] for r in rows(45) if re.fullmatch(r"G\d+", r[0])}
    for gid in sorted(guard_ids - docx_ids):
        if gid not in KNOWN_DIVERGENCE:
            problems.append(f"guardrails: {gid} is in the framework but not in the docx annexure, "
                            f"and is not a known divergence")
    for gid in sorted(docx_ids - guard_ids):
        problems.append(f"guardrails: {gid} is in the docx annexure but not in the framework")

    pairs = [("criticality_taxonomy", "classes", 48), ("determinism_criteria", "criteria", 49),
             ("tradeoff_catalogue", "conflicts", 57), ("guardrail_mapping", "mandatory_by_class", 54),
             ("readiness_gates", "gates", 47)]
    for name, key, idx in pairs:
        ours, theirs = len(files[name][key]["rows"]), len(rows(idx))
        if ours != theirs:
            problems.append(f"{name}.{key}: {ours} rows from html, {theirs} from docx T{idx}")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("html", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--crosscheck", type=Path, default=None)
    ap.add_argument("--spec", type=Path, default=None,
                    help="also extract the spec's Annexure F artifacts (price sheet, formulas, "
                         "business case structure, intake fields) from this docx")
    args = ap.parse_args(argv)

    files = build(args.html)
    if args.spec:
        files |= build_spec(args.spec)
    args.out.mkdir(parents=True, exist_ok=True)
    masters_dir = args.out / "masters"
    masters_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in sorted(files.items()):
        # `masters_for`, not `master_for`: a multi-table artifact publishes as one master per
        # SECTION, because the corpus is one record type per artifact. This was the ad-hoc path for
        # a while and the CLI still wrote the concatenated form — so 15 of the 50 committed masters
        # could not be reproduced by the documented entry point, and re-running it would have
        # overwritten their parents back into a shape the publisher refuses. The masters are signed
        # inputs; a generator that cannot regenerate them is not a generator.
        for stem, text in masters_for(name, payload).items():
            (masters_dir / f"{stem}.md").write_text(text, encoding="utf-8")
        path = args.out / f"{name}.json"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
                        encoding="utf-8")
        size = sum(len(v) if isinstance(v, list) else 1
                   for k, v in payload.items() if not k.startswith("_"))
        print(f"{path}  ({size} top-level entries)")

    if args.crosscheck:
        problems = crosscheck(files, args.crosscheck)
        if problems:
            print("\nCROSS-CHECK FAILED — unexplained divergence between the framework and the "
                  "spec's annexures:", file=sys.stderr)
            for p in problems:
                print(f"  - {p}", file=sys.stderr)
            return 1
        print("\ncross-check against the docx annexures: agree, with known divergences:")
        for gid, why in sorted(KNOWN_DIVERGENCE.items()):
            print(f"  {gid}: {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
