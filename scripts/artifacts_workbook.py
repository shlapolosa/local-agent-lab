"""The governed artifacts as ONE workbook the team can edit, and the masters it turns back into.

    python scripts/artifacts_workbook.py export [out.xlsx]      # masters -> workbook
    python scripts/artifacts_workbook.py import <in.xlsx>       # workbook -> masters (writes them)
    python scripts/artifacts_workbook.py check  <in.xlsx>       # parse and diff, write nothing

**The workbook is an EXCHANGE format and never the source.** DR-02 requires the human-readable
master and the agent-readable form to be the same artifact at the same version — `derived_from =
master_sha256` — and that link is only true if the derivation actually happens. A spreadsheet
transcribed by hand into a master would hash one document and publish another, which is precisely
the assertion DR-02 refuses ("divergence is a defect, not a lag").

So the chain is master -> workbook -> master, mechanically, and what the publisher hashes is the
REGENERATED master. `import` rewrites the masters from the sheets; the existing review-app staging
path then validates them with the publisher's own `derive.records`, shows a row-level diff, and an
operator publishes. The workbook never reaches the corpus.

A spreadsheet was the team's choice, made with that trade-off stated: it is the format EA and
business reviewers actually use, and the converter is what keeps the guarantee intact.

Exempt from the coverage target as a script, but the round trip is tested — a workbook that cannot
become the master it came from is a second source of truth, and that is the failure to catch early.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lab.core.reference import master                              # noqa: E402

#: The sheet that lists every artifact — what the whole ask looks like on one page.
INDEX = "0. index"

#: Rows of the per-sheet header block, before the table. Read back by `header_row_index`, so the
#: shape is data rather than a magic number: an editor who inserts a note row must not break it.
#: The rows the CATALOGUE contributes to a sheet's schema block. Everything else in that block is
#: the master's OWN meta and is written back verbatim — `Section` keys the derived JSON and
#: `Source` is the artifact's provenance, so carrying only `Artifact` published records under the
#: wrong key and lost where they came from. Naming ours is what lets the rest travel untouched.
_CATALOGUE_LABELS = ("Artifact id", "Record type", "Key field(s)", "Owner", "Read as",
                     "What that means", "Master")

_HEAD = Font(bold=True)
_BAND = PatternFill("solid", fgColor="EEEEEE")
_WRAP = Alignment(wrap_text=True, vertical="top")


#: What each read mode MEANS for the content — the difference between a mode and a label. The team
#: is being asked to write these artifacts, and the mode decides what "good" looks like.
RETRIEVAL_NOTE = {
    "whole": "Read IN FULL, every row, every time. Nothing selects "
             "'the relevant rows' — a row omitted here is a rule the process never sees. Keep it "
             "small and complete; if it grows past a prompt it has to become 'vector' instead.",
    "key": "Read by EXACT natural key (the key field below). The key must be unique and stable "
           "across versions — a renamed or reused key reads as one record deleted and another "
           "created, and anything citing the old one breaks.",
    "vector": "SEARCHED for relevance, so the text has to be worth embedding: write prose a person "
              "would recognise the subject from, not codes or abbreviations. Two rows that mean "
              "the same thing in different words are a problem here in a way they are not "
              "elsewhere.",
}


def retrieval_for(artifact_id: str, record_type: str) -> str:
    """How a consumer is meant to READ this artifact, computed the way the publisher computes it.

    Declared modes come from the publisher's own table; an artifact that declares nothing takes the
    kind's default — prose can only be searched, a record keeps its exact read. Computed rather
    than restated, because a second hand-maintained copy would drift from the thing that publishes.
    """
    declared = _retrieval_table().get(artifact_id)
    if declared:
        return str(declared)
    return "key" if record_type else "vector"


def _licensed() -> dict:
    """The vector-mode artifacts published from licensed workbooks — `store id -> workbook stem`."""
    spec = importlib.util.spec_from_file_location(
        "_publish_corpus_w", ROOT / "scripts" / "publish_usecase_corpus.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {str(k): str(v) for k, v in getattr(module, "WORKBOOKS", {}).items()}


def _retrieval_table() -> dict:
    spec = importlib.util.spec_from_file_location(
        "_publish_corpus_r", ROOT / "scripts" / "publish_usecase_corpus.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return dict(getattr(module, "RETRIEVAL", {}))


#: The docx register (what is PRIMARY) and the map from a primary artifact to the corpus tables
#: that realise it. Both committed under docs/artifacts/, so the generator depends on no file
#: outside the repository and both are reviewable in a diff.
REGISTER = ROOT / "docs/artifacts/primary-register.json"
PRIMARY_MAP = ROOT / "docs/artifacts/primary-map.json"

#: Artifacts the register names and the corpus does not realise, by whether anything declares
#: their shape. `schema` -> the team gets columns and no rows; `none` -> no sheet, and the index
#: says so. An invented header is worse than an honest gap: the team would fill it in good faith
#: and nothing could read the result.
MISSING_NOTE = {
    "schema": "NOT YET SUPPLIED. The columns below are the declared schema — fill the rows.",
    "none": "NOT YET SUPPLIED, and no schema is declared anywhere for it. The columns have to be "
            "agreed before the content can be: ask rather than assume.",
}


def register() -> dict:
    return json.loads(REGISTER.read_text())


def primary_map() -> dict:
    return json.loads(PRIMARY_MAP.read_text())


def _slug(name: str) -> str:
    keep = [c.lower() if c.isalnum() else "-" for c in name]
    return "-".join(w for w in "".join(keep).split("-") if w)


def sheet_name(name: str, step: str) -> str:
    """`step-05-ai-capability-map` — the process's order, not the alphabet's.

    An artifact id alone made a reader match names against a 27-step framework in their head.
    Excel refuses a name over 31 characters, so it is trimmed; the index carries the full name
    either way. A step with no number (an artifact nothing reads) is named without a prefix.
    """
    first = str(step or "").split(",")[0].strip()
    prefix = f"step-{first.zfill(2) if first.replace('.', '').isdigit() else first}-" if first else ""
    return (prefix + _slug(name))[:31]


class WorkbookError(ValueError):
    """The workbook is not one these masters can be rebuilt from."""


def catalogue() -> dict:
    """`id -> (record_type, key_fields, owner)` — the publisher's own table, by path because
    `scripts/` is not an importable package."""
    spec = importlib.util.spec_from_file_location(
        "_publish_corpus", ROOT / "scripts" / "publish_usecase_corpus.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return dict(module.ARTIFACTS)


def master_path(artifact_id: str) -> Path:
    return ROOT / "src/lab/core/usecase/seed/masters" / f"{artifact_id.replace('-', '_')}.md"


def sheet_rows(artifact_id: str, parsed: master.Master, entry) -> list[list]:
    """One sheet: the schema a reader needs, then the table they edit.

    Schema first, because a column of values with no schema is a column somebody guesses at — the
    record type, the key fields and the owner are what say which column IDENTIFIES a row and who
    may change it.
    """
    record_type, key_fields, owner = entry
    mode = retrieval_for(artifact_id, record_type)
    return ([[k, v] for k, v in parsed.meta.items()]
            + [["Artifact id", artifact_id],
               ["Record type", record_type],
               ["Key field(s)", key_fields],
               ["Owner", owner],
               ["Read as", mode],
               ["What that means", RETRIEVAL_NOTE[mode]],
               ["Master", master_path(artifact_id).name],
               [],
               list(parsed.headers)]
            + [list(r) for r in parsed.rows])


def header_row_index(sheet) -> int:
    """Which row holds the table's headers: the first non-empty row AFTER the blank separator.

    Located by the SEPARATOR rather than by the row's contents. The first version asked "is this
    row's first cell one of the schema labels?", and four of the 53 real artifacts head their table
    with `Artifact` or `Owner` — the very words the schema block uses. It skipped the header and
    read the first data row as one, and the import refused them. `export` writes exactly one blank
    row, so the separator is a fact about the document rather than a guess about its words.
    """
    seen_blank = False
    for row in sheet.iter_rows(min_row=1, max_row=60):
        empty = not any(c.value is not None and str(c.value).strip() for c in row)
        if empty:
            seen_blank = True
            continue
        if seen_blank:
            return row[0].row
    raise WorkbookError("no header row: the sheet has a schema block and no table under it")


def export(sheets: dict, out: Path) -> Path:
    """`{artifact_id: (Master, entry)}` -> one workbook, a sheet each plus an index."""
    book = openpyxl.Workbook()
    index = book.active
    index.title = INDEX
    index.append(["Artifact", "Read as", "Record type", "Key field(s)", "Owner", "Rows", "Sheet"])
    for cell in index[1]:
        cell.font, cell.fill = _HEAD, _BAND

    for artifact_id, (parsed, entry) in sheets.items():
        # Excel refuses a sheet name over 31 characters; the index carries the full id either way.
        name = artifact_id[:31]
        sheet = book.create_sheet(name)
        for row in sheet_rows(artifact_id, parsed, entry):
            sheet.append(row)
        head = header_row_index(sheet)
        for cell in sheet[head]:
            cell.font, cell.fill = _HEAD, _BAND
        for column in sheet.columns:
            width = max((len(str(c.value or "")) for c in column), default=10)
            sheet.column_dimensions[column[0].column_letter].width = min(max(width + 2, 12), 60)
            for c in column:
                c.alignment = _WRAP
        index.append([artifact_id, retrieval_for(artifact_id, entry[0]),
                      entry[0], entry[1], entry[2], len(parsed.rows), name])
    # The vector-mode artifacts have no sheet: they are licensed capability WORKBOOKS, never files
    # in this repository. Omitting them would tell the team the corpus holds nothing searchable,
    # which is false — so they are listed, with the reason, and no sheet to point at.
    for store_id, stem in _licensed().items():
        index.append([store_id, "vector", "capability", "id",
                      "licensed reference model — not in this repository", "", ""])
    index.freeze_panes = "A2"
    book.save(out)
    return out


def read_sheet(path: Path, artifact_id: str, key_fields=()) -> master.Master:
    """One sheet back into the Master it came from.

    `key_fields` are checked by NAME against the header row: renaming a column silently changes
    what the publisher keys a record on, and a record keyed on a column that no longer exists is
    one it cannot match to its predecessor — it would read as every row removed and re-added.
    """
    book = openpyxl.load_workbook(path, data_only=True)
    name = artifact_id[:31]
    if name not in book.sheetnames:
        raise WorkbookError(f"no sheet {name!r} in {path.name}")
    sheet = book[name]
    head = header_row_index(sheet)
    meta = {str(r[0].value).strip(): str(r[1].value or "").strip()
            for r in sheet.iter_rows(min_row=1, max_row=head - 1)
            if r[0].value and str(r[0].value).strip() not in _CATALOGUE_LABELS}
    # POSITIONAL, and empty cells kept: two masters lead with an unnamed column, and reading only
    # cells that "have a value" dropped it, shifted every row one left and lost the last column —
    # corruption that still looks like a table. Only TRAILING empties are trimmed.
    cells = [("" if c.value is None else str(c.value).strip()) for c in sheet[head]]
    while cells and not cells[-1]:
        cells.pop()
    headers = tuple(cells)
    width = len(headers)
    for field in [f.strip() for f in key_fields if f and f.strip()]:
        if field not in headers:
            raise WorkbookError(
                f"{artifact_id}: key field {field!r} is not a column any more (have {list(headers)})"
                " — a renamed key column makes every row look new to the publisher")
    rows = []
    for row in sheet.iter_rows(min_row=head + 1):
        got = [("" if c.value is None else str(c.value)).strip() for c in row]
        if any(got):                          # a blank row is spacing, not a record
            # Padded to the header width rather than trimmed — see `read_primary_sheet`.
            rows.append(tuple((got + [""] * width)[:width]))
    return master.Master(title=meta.get("Artifact", artifact_id), headers=headers,
                         rows=tuple(rows), meta=meta)


def primary_sheet(name: str, entry: dict, row: dict) -> list[list]:
    """One PRIMARY artifact: what it is, then every corpus table that realises it, in order.

    Grouped because the register is what the team recognises. `Reference architecture model` is one
    artifact there and ten tables in the corpus; a sheet per table asked them to review ten things
    that are one thing.
    """
    ids = list(entry.get("corpus") or ())
    out = [["Artifact", name],
           ["Consumed at step", row.get("Consumed at step", "")],
           ["Owner", row.get("Owner", "")],
           ["Scope", row.get("Scope", "")],
           ["Form", row.get("Form", "")]]
    if entry.get("note"):
        out.append(["Note", entry["note"]])
    if not ids:
        kind = "schema" if entry.get("schema") else "none"
        out.append(["Status", MISSING_NOTE[kind]])
        if entry.get("schema"):
            out += [["Schema declared in", entry.get("schema_from", "")], [],
                    list(entry["schema"])]
        return out

    for artifact_id in ids:
        path = master_path(artifact_id)
        if not path.is_file():
            continue
        parsed = master.parse(path.read_text())
        mode = retrieval_for(artifact_id, catalogue().get(artifact_id, ("", "", ""))[0])
        out += [[],
                [f"— {artifact_id}", parsed.title],
                ["Read as", f"{mode}: {RETRIEVAL_NOTE[mode]}"],
                [],
                list(parsed.headers)]
        out += [list(r) for r in parsed.rows]
    return out


#: How a table inside a grouped sheet names the artifact it belongs to. Written by
#: `primary_sheet` and read by `read_primary_sheet` — the one marker both sides agree on.
_TABLE_MARKER = "— "


def read_primary_sheet(path: Path, title: str) -> dict:
    """One grouped sheet back into `{artifact_id: Master}`.

    Grouping made a sheet hold several tables, and that nearly cost the round trip — the whole
    justification for accepting a spreadsheet at all (DR-02: what publishes must be DERIVED from
    what a person edited, not transcribed beside it). Each table carries its own marker row, so
    the split is exact rather than positional.

    A sheet for an artifact nobody has supplied yields NOTHING. A declared schema with no rows is
    not a master, and writing one would publish an empty artifact over nothing — which reads
    downstream as "the corpus says there are none", the most dangerous answer in this layer.
    """
    book = openpyxl.load_workbook(path, data_only=True)
    if title not in book.sheetnames:
        raise WorkbookError(f"no sheet {title!r} in {path.name}")
    sheet = book[title]
    out, current, headers, rows = {}, "", (), []

    def close():
        if current and headers and rows:
            out[current] = master.Master(title=current, headers=headers, rows=tuple(rows),
                                         meta={"Artifact": current.replace("-", "_")})

    for row in sheet.iter_rows():
        cells = [("" if c.value is None else str(c.value).strip()) for c in row]
        first = cells[0] if cells else ""
        if first.startswith(_TABLE_MARKER):
            close()
            current, headers, rows = first[len(_TABLE_MARKER):].strip(), (), []
            continue
        if not current or first in ("Read as",) or not any(cells):
            continue
        trimmed = list(cells)
        while trimmed and not trimmed[-1]:
            trimmed.pop()
        if not headers:
            headers = tuple(trimmed)          # trailing empties trimmed: the table's real width
        elif trimmed:
            # PADDED to that width, never trimmed: a row may legitimately end in an empty cell,
            # and trimming it returns a row one column short that still looks like a table.
            rows.append(tuple((cells + [""] * len(headers))[:len(headers)]))
    close()
    return out


def build_workbook(out: Path) -> Path:
    """The register, as one workbook: a sheet per PRIMARY input artifact, plus the outputs listed.

    Outputs carry no sheet — they are PRODUCED by a run, so there is no master to edit and nothing
    for the team to supply. They are listed because "what does this process give back" is half of
    what a reviewer is here to check.
    """
    reg, mapping = register(), primary_map()
    inputs = {r[0]: dict(zip(reg["inputs"]["headers"], r)) for r in reg["inputs"]["rows"]}

    book = openpyxl.Workbook()
    index = book.active
    index.title = INDEX
    index.append(["#", "Primary artifact", "Step(s)", "Status", "Corpus tables", "Rows", "Owner",
                  "Sheet"])
    for cell in index[1]:
        cell.font, cell.fill = _HEAD, _BAND

    for n, (name, row) in enumerate(inputs.items(), start=1):
        entry = mapping["inputs"].get(name, {})
        ids = [a for a in (entry.get("corpus") or ()) if master_path(a).is_file()]
        step = row.get("Consumed at step", "")
        status = ("deployed" if ids else
                  "missing — schema declared" if entry.get("schema") else "missing — no schema")
        sheet = book.create_sheet(sheet_name(name, step))
        for line in primary_sheet(name, entry, row):
            sheet.append(line)
        rows_total = 0
        for artifact_id in ids:
            rows_total += len(master.parse(master_path(artifact_id).read_text()).rows)
        for column in sheet.columns:
            width = max((len(str(c.value or "")) for c in column), default=10)
            sheet.column_dimensions[column[0].column_letter].width = min(max(width + 2, 14), 70)
            for c in column:
                c.alignment = _WRAP
        index.append([n, name, step, status, ", ".join(ids), rows_total,
                      row.get("Owner", ""), sheet.title])

    index.append([])
    index.append(["OUTPUTS — produced by the process, no sheet to edit"])
    index[index.max_row][0].font = _HEAD
    index.append(["#", "Artifact", "Produced at step", "Persisted", "Past go-live"])
    for cell in index[index.max_row]:
        cell.font, cell.fill = _HEAD, _BAND
    for n, r in enumerate(reg["outputs"]["rows"], start=1):
        index.append([n] + list(r))

    for column in index.columns:
        width = max((len(str(c.value or "")) for c in column), default=10)
        index.column_dimensions[column[0].column_letter].width = min(max(width + 2, 10), 52)
    index.freeze_panes = "A2"
    book.save(out)
    return out


def main(argv: list[str]) -> int:
    if not argv:
        raise SystemExit(__doc__)
    command, rest = argv[0], argv[1:]

    if command == "export":
        out = Path(rest[0]) if rest else ROOT / "var/out/cafe-artifacts.xlsx"
        out.parent.mkdir(parents=True, exist_ok=True)
        build_workbook(out)
        reg, mapping = register(), primary_map()
        ins = mapping["inputs"]
        deployed = sum(1 for v in ins.values()
                       if any(master_path(a).is_file() for a in v.get("corpus") or ()))
        schema_only = sum(1 for v in ins.values() if not v.get("corpus") and v.get("schema"))
        print(f"{out}")
        print(f"  {len(ins)} primary input artifacts: {deployed} deployed, "
              f"{schema_only} missing with a declared schema, "
              f"{len(ins) - deployed - schema_only} missing with none")
        print(f"  {len(reg['outputs']['rows'])} output artifacts listed (no sheet — produced, "
              f"not supplied)")
        return 0

    if command in ("import", "check"):
        if not rest:
            raise SystemExit("which workbook?")
        path, reg = Path(rest[0]), register()
        mapping = primary_map()["inputs"]
        changed, failed = [], []
        for name, row in ((r[0], dict(zip(reg["inputs"]["headers"], r)))
                          for r in reg["inputs"]["rows"]):
            title = sheet_name(name, row.get("Consumed at step", ""))
            try:
                back = read_primary_sheet(path, title)
            except WorkbookError as e:
                failed.append(f"{name}: {e}")
                continue
            for artifact_id, parsed in back.items():
                target = master_path(artifact_id)
                before = master.parse(target.read_text()) if target.is_file() else None
                if before and before.rows == parsed.rows and before.headers == parsed.headers:
                    continue
                changed.append(f"{artifact_id}: "
                               f"{len(before.rows) if before else 0} -> {len(parsed.rows)} rows")
                if command == "import":
                    # Rendered from the PARSED workbook: derived, never transcribed.
                    keep = before.meta if before else parsed.meta
                    target.write_text(master.render(master.Master(
                        title=parsed.title, headers=parsed.headers, rows=parsed.rows, meta=keep)))
        for line in changed + [f"REFUSED {f}" for f in failed]:
            print(f"  {line}")
        print(f"{'written' if command == 'import' else 'checked'}: "
              f"{len(changed)} changed, {len(failed)} refused")
        return 1 if failed else 0

    raise SystemExit(__doc__)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
