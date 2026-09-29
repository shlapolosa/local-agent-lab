"""Draw one CAFÉ view from the workbook — the command the five `cafe-*` skills run.

    .venv/bin/python scripts/cafe_views.py <view> --input input.json --workbook cafe-artifacts.xlsx \
        --out var/out/views/<use-case>_<view>.html

<view> is one of capability_heatmap · realisation_heatmap · ontology_graph · bpmn ·
scoped_architecture (the last writes `<out stem>.logical.html` and `<out stem>.physical.html`).

The drawing is `lab.core.usecase.views` — the same renderer the pipeline's governed tools call, so
a view drawn here and one on an approval are the same picture. What differs is the source: a run
reads the published corpus under its pin; this reads the workbook the corpus is published FROM,
through the importer's own reader (tables found by their marker, as the corpus names them). The
output is the HTML page; open it in a browser, and print to PDF from there.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from artifacts_workbook import read_all_tables                           # noqa: E402
from lab.core.usecase.views import (bpmn, capability_heatmap, ontology_graph,  # noqa: E402
                                    realisation_heatmap, scoped_architecture, tables)

RENDER = {
    "capability_heatmap": lambda data, inp: capability_heatmap.render(data, inp),
    "realisation_heatmap": lambda data, inp: realisation_heatmap.render(data, inp),
    "ontology_graph": lambda data, inp: ontology_graph.render(data, inp),
    "scoped_architecture": lambda data, inp: scoped_architecture.render(data, inp),
    "bpmn": lambda data, inp: bpmn.render(
        inp, l3={r["id"]: r for r in data["tech"]["tables"]["technology-capability-l3"]}),
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("view", choices=sorted(RENDER))
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--workbook", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args(argv)
    found = read_all_tables(a.workbook)
    data = tables.assemble(a.view, lambda t: ([dict(zip(found[t].headers, r)) for r in found[t].rows]
                                              if t in found else None),
                           lambda t: found[t].meta.get("Version", a.workbook.name) if t in found else "")
    out = RENDER[a.view](data, json.loads(a.input.read_text()))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    written = {}
    for name, page in (out.get("pages") or {"": out["html"]}).items():
        path = a.out.with_suffix(f".{name}.html" if name else ".html")
        path.write_text(page, encoding="utf-8")
        written[name or a.view] = str(path)
    print(json.dumps({"written": written, "summary": out["summary"]}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
