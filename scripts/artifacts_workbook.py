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
    for field in [f.strip() for f in key_fields if f and f.strip()]:
        if field not in headers:
            raise WorkbookError(
                f"{artifact_id}: key field {field!r} is not a column any more (have {list(headers)})"
                " — a renamed key column makes every row look new to the publisher")
    rows = []
    for row in sheet.iter_rows(min_row=head + 1):
        values = tuple(("" if c.value is None else str(c.value)).strip()
                       for c in row[:len(headers)])
        if any(values):                       # a blank row is spacing, not a record
            rows.append(values)
    return master.Master(title=meta.get("Artifact", artifact_id), headers=headers,
                         rows=tuple(rows), meta=meta)


def main(argv: list[str]) -> int:
    if not argv:
        raise SystemExit(__doc__)
    command, rest = argv[0], argv[1:]
    table = catalogue()

    if command == "export":
        out = Path(rest[0]) if rest else ROOT / "var/out/cafe-artifacts.xlsx"
        out.parent.mkdir(parents=True, exist_ok=True)
        sheets, missing = {}, []
        for artifact_id, entry in sorted(table.items()):
            path = master_path(artifact_id)
            if not path.is_file():
                missing.append(artifact_id)
                continue
            sheets[artifact_id] = (master.parse(path.read_text()), entry)
        export(sheets, out)
        print(f"{out}  —  {len(sheets)} artifacts, "
              f"{sum(len(m.rows) for m, _ in sheets.values()):,} rows")
        if missing:
            print(f"  no master on disk (nothing to share yet): {missing}")
        return 0

    if command in ("import", "check"):
        if not rest:
            raise SystemExit("which workbook?")
        path = Path(rest[0])
        book = openpyxl.load_workbook(path, data_only=True)
        changed, failed = [], []
        for artifact_id, entry in sorted(table.items()):
            if artifact_id[:31] not in book.sheetnames:
                continue
            try:
                back = read_sheet(path, artifact_id, key_fields=str(entry[1]).split(","))
            except WorkbookError as e:
                failed.append(f"{artifact_id}: {e}")
                continue
            target = master_path(artifact_id)
            before = master.parse(target.read_text()) if target.is_file() else None
            if before and before.rows == back.rows and before.headers == back.headers:
                continue
            was = len(before.rows) if before else 0
            changed.append(f"{artifact_id}: {was} -> {len(back.rows)} rows")
            if command == "import":
                # Rendered from the PARSED workbook, so what is published is derived rather than
                # transcribed — the whole point of the round trip.
                target.write_text(master.render(back))
        for line in changed:
            print(f"  {line}")
        for line in failed:
            print(f"  REFUSED {line}")
        print(f"{'written' if command == 'import' else 'checked'}: "
              f"{len(changed)} changed, {len(failed)} refused")
        return 1 if failed else 0

    raise SystemExit(__doc__)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
