"""The intake answered as a spreadsheet, rather than twenty-one boxes in a browser.

The Submit page generates its form from the published `intake-field-specs` artifact — one record per
field, so adding ROI later is a corpus publish and not a change to this app. A CSV path that
hardcoded those columns would undo exactly that: the template would keep offering the fields the
image was built with, and a stale column would look identical to a typo. So **the template is
generated from the same rows the form is**, and the parser resolves against them.

Two rules the shape of the thing forces:

* **An unrecognised field is REPORTED, never dropped.** Someone filling a spreadsheet in Excel
  wants to know that "Urgancy" went nowhere. Filtering it silently is how a submission arrives half
  empty with no explanation, which is the failure this whole layer keeps refusing to allow.
* **A blank cell is "not answered", not an empty answer.** The published behaviour for an
  unanswered field is a requires-input marker on the business case; an empty string would instead
  be a value a step has to interpret.

Pure: no Streamlit, no corpus client. It is handed rows and bytes and returns an answer and a list
of problems — which is what makes it testable against the same bounds the contract enforces.
"""
from __future__ import annotations

import csv
import io
import re
from typing import Any, Sequence

__all__ = ["COLUMNS", "template", "parse", "MAX_LABELS", "MAX_BYTES"]

#: The template's own columns. `Value` is what a person fills in; the rest are there so nobody has
#: to guess whether a blank is allowed or whether a cell wants a date or a sentence.
COLUMNS = ("Group", "Field", "Type", "Required", "Used by", "Value")

#: `InputField._mapping`'s bounds, restated so a CSV is trimmed HERE with a named reason rather than
#: causing the contract to refuse the whole submission at `workflows.request`.
MAX_LABELS = 64
MAX_BYTES = 8000

#: `capabilities.SEP` by value, not by import: this is a label separator in a human form, and the
#: technology capability map's key separator is a different fact that happens to use the same glyph.
SEP = " · "


def _norm(text: Any) -> str:
    """Casefolded, whitespace-collapsed. A spreadsheet round-trip changes spacing and capitalisation;
    it does not change which field somebody meant."""
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


def _cols(headers: Sequence[str]) -> dict:
    return {name: i for i, name in enumerate(headers)}


def template(rows: Sequence[Sequence[str]], headers: Sequence[str]) -> str:
    """A blank CSV with one row per published field, in the artifact's own order.

    Generated, so a field added by a publish appears in the next download with no change here.
    """
    col = _cols(headers)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    for row in rows:
        def cell(name: str) -> str:
            return str(row[col[name]]).strip() if name in col and col[name] < len(row) else ""
        writer.writerow([cell("Group"), cell("Label"), cell("Type"), cell("Required"),
                         cell("Used by"), ""])
    return out.getvalue()


def _resolve(rows: Sequence[Sequence[str]], headers: Sequence[str]) -> tuple[dict, dict]:
    """`(group, label) -> full label` and `label -> full label`, both normalised.

    The second is how a CSV whose Group column somebody deleted still resolves: a field name unique
    across the whole set identifies itself. A name that is NOT unique resolves to nothing, because
    guessing which group was meant is how a value lands on the wrong step.
    """
    col = _cols(headers)
    pairs: dict[tuple[str, str], str] = {}
    seen: dict[str, list[str]] = {}
    for row in rows:
        group = str(row[col["Group"]]).strip() if "Group" in col else ""
        label = str(row[col["Label"]]).strip() if "Label" in col else ""
        if not label:
            continue
        full = f"{group}{SEP}{label}" if group else label
        pairs[(_norm(group), _norm(label))] = full
        seen.setdefault(_norm(label), []).append(full)
    return pairs, {k: v[0] for k, v in seen.items() if len(v) == 1}


def parse(body: bytes, rows: Sequence[Sequence[str]],
          headers: Sequence[str]) -> tuple[dict, list[str]]:
    """An uploaded CSV as `{label: {"value": text}}` plus everything that did not fit.

    The answer shape is the one `InputKind.MAPPING` means and the form already produces — a flat
    `label -> value` is refused by the contract.
    """
    text = body.decode("utf-8-sig", errors="replace") if body else ""
    reader = csv.DictReader(io.StringIO(text))
    records = [r for r in reader if any(str(v or "").strip() for v in r.values())]
    if not records:                     # an empty file is an empty answer, not an error
        return {}, []

    names = {_norm(n): n for n in (reader.fieldnames or []) if n}
    field_col = next((names[k] for k in ("field", "label", "question") if k in names), None)
    value_col = next((names[k] for k in ("value", "answer", "response") if k in names), None)
    group_col = names.get("group")
    if not field_col or not value_col:
        missing = " and ".join(n for n, got in (("Field", field_col), ("Value", value_col))
                               if not got)
        return {}, [f"the file has no {missing} column — download the template and fill the "
                    f"Value column"]

    pairs, unique = _resolve(rows, headers)
    answer: dict[str, dict] = {}
    problems: list[str] = []
    size = 0
    for record in records:
        raw = str(record.get(field_col) or "").strip()
        group = str(record.get(group_col) or "").strip() if group_col else ""
        if SEP in raw and not group:            # somebody pasted the full key into one cell
            group, raw = (part.strip() for part in raw.split(SEP, 1))
        value = str(record.get(value_col) or "").strip()
        if not raw:
            continue
        label = pairs.get((_norm(group), _norm(raw))) or unique.get(_norm(raw))
        if not label:
            problems.append(f"no published field matches "
                            f"{f'{group}{SEP}{raw}' if group else raw} — it was not submitted")
            continue
        if not value:                           # a blank cell means "not answered"
            continue
        if len(answer) >= MAX_LABELS:
            problems.append(f"only the first {MAX_LABELS} answered fields were kept — the "
                            f"submission contract accepts no more; {label} and any after it "
                            f"were dropped")
            break
        size += len(label.encode()) + len(value.encode())
        if size > MAX_BYTES:
            problems.append(f"the answers exceed the {MAX_BYTES}-byte submission limit — {label} "
                            f"and any after it were dropped; shorten the longer answers")
            break
        answer[label] = {"value": value}
    return answer, problems
