"""Split the published intake field GROUPS into typed FIELDS — so a form can be generated.

`intake-fields` publishes eight groups whose `Fields` column is PROSE: "Role, headcount, frequency
per week, current minutes per instance, expected minutes per instance". A person can read that; a
form cannot render it and a validator cannot check it, so the Submit page offered eight free-text
rows and nothing ever said an entry was missing.

This derives one record per field, keeping the group, so the form is generated from the artifact and
adding a field later — ROI, say — is a PUBLISH rather than a change to the app.

The types are the one judgement here, and they are deliberately few: `text`, `number`, `date`,
`yesno`. An intake answer reaches `InputField._mapping`, which requires `{label: {field: "string"}}`
with no numbers and no nesting, so a type is a widget and a hint to the person — never a promise
about the wire format.

    PYTHONPATH=src .venv/bin/python scripts/derive_intake_fields.py
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from lab.core.usecase import seed                                        # noqa: E402

SEED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                    "src", "lab", "core", "usecase", "seed")

#: A field whose name says what it holds. Matched on the NAME, so a new field inherits a sensible
#: type without this table growing — and anything unmatched is `text`, which is always answerable.
TYPES = (
    (re.compile(r"headcount|volume|rate|minutes|frequency|reduction|runs per|users|records", re.I), "number"),
    (re.compile(r"\bdate\b|required-by", re.I), "date"),
    (re.compile(r"^whether |^is |personal data|health data|financial|regulated", re.I), "yesno"),
)

#: Groups whose absence actually stops a number being computed, per the artifact's own "Used by"
#: column. Everything else is optional: a missing entry becomes a requires-input marker the business
#: case carries to the approver, which is the published behaviour and better than an estimate.
REQUIRED_GROUPS = {"Sensitivity flags", "Urgency"}



def _write(stem: str, payload: dict) -> None:
    """Write the seed JSON and its master THROUGH the corpus generator.

    Not `master.render` directly: `tests/unit/core/usecase/test_seed.py` requires every committed
    master to be byte-reproducible by `extract_cafe_seed.masters_for`, because the masters are
    hashed and signed — one the generator cannot reproduce is an input nobody can verify. One
    renderer, therefore, and this file only decides the ROWS.
    """
    import importlib.util

    with open(os.path.join(SEED, f"{stem}.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    spec = importlib.util.spec_from_file_location(
        "_extract", os.path.join(root, "scripts", "extract_cafe_seed.py"))
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    for name, text in generator.masters_for(stem, payload).items():
        with open(os.path.join(SEED, "masters", f"{name}.md"), "w", encoding="utf-8") as fh:
            fh.write(text)


def main() -> int:
    groups = seed.artifact("intake_fields")["field_groups"]
    col = {h: i for i, h in enumerate(groups["headers"])}
    rows, order = [], 0
    for row in groups["rows"]:
        group = str(row[col["Field group"]]).strip()
        used_by = str(row[col["Used by"]]).strip()
        for raw in str(row[col["Fields"]]).split(","):
            name = raw.strip().rstrip(".")
            if not name:
                continue
            kind = next((t for pattern, t in TYPES if pattern.search(name)), "text")
            order += 1
            rows.append([f"{group} · {name}", group, name, kind,
                         "yes" if group in REQUIRED_GROUPS else "no", str(order), used_by])
    headers = ["Field", "Group", "Label", "Type", "Required", "Order", "Used by"]
    payload = {"fields": {"headers": headers, "rows": rows},
               "_source": "derived from intake_fields.json by scripts/derive_intake_fields.py — the "
                          "groups stay the published artifact; these are their fields, typed"}
    _write("intake_field_specs", payload)
    kinds = {}
    for r in rows:
        kinds[r[3]] = kinds.get(r[3], 0) + 1
    print(f"{len(rows)} fields in {len({r[1] for r in rows})} groups; types {kinds}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
