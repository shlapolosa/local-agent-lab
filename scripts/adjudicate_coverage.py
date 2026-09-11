"""DRAFT the expected capability set for an eval case, blind to every matcher — for a person to review.

    set -a && source .env && set +a
    .venv/bin/python scripts/adjudicate_coverage.py --cases var/eval/coverage --scheme healthcare-provider-v2.0
    .venv/bin/python scripts/adjudicate_coverage.py --cases var/eval/coverage-insurance --scheme insurance-v5.0

WHY THIS EXISTS. The first two cases' expected sets were adjudicated from the UNION of two matchers'
outputs, and a set built that way can only ever measure which matcher found more of what one of them
found (`eval_coverage.py`). This asks instead: given the SUBMISSION and the WHOLE leaf list, which
capabilities apply? Two model families answer independently and the draft records where they agree.

WHAT IT IS NOT. It is not the expected set. A model adjudicating a model is the same instrument
twice; the draft is a starting point for a blind human review, and `expected.json` is written by a
person. The output is `expected.draft.json`, never `expected.json`.

Models: `kimi-k3` through the use-case agent key (the matcher's own model — its picks are the ceiling
the matcher could reach) and `claude-sonnet-5` through the master key (a different family, as the
independent second opinion). Operator script: it runs against the gateway like any client.
"""
import argparse
import importlib.util
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

_spec = importlib.util.spec_from_file_location("eval_coverage", HERE / "eval_coverage.py")
_ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ev)
from lab.workloads.usecase import coverage  # noqa: E402

PROMPT = """You are adjudicating an evaluation set for a capability-matching step.

Below is a use-case SUBMISSION and the complete list of LEAF capabilities from a business capability
reference model (id, path, definition). Decide which leaf capabilities the described solution would
REALISE OR DIRECTLY DEPEND ON — the capabilities a capability map would say this use case sits on.

Rules:
- Judge from the submission's functions (what the solution DOES), not from its actors or its data.
- Prefer the most specific leaf; do not add a parent when a leaf applies.
- Include a capability only if a careful architect would defend it; leave out "could be related".
- Aim for completeness: a missed applicable capability is worse than a debated one.

Answer with JSON only: {"applicable": [{"id": "<id>", "label": "<label>", "why": "<one line>"}]}

SUBMISSION:
%s

LEAF CAPABILITIES:
%s
"""


def ask(gateway: str, key: str, model: str, prompt: str, attempts: int = 3) -> dict:
    body = {"model": model, "messages": [{"role": "user", "content": prompt}],
            "temperature": 0, "max_tokens": 4000}
    for attempt in range(attempts):
        req = urllib.request.Request(f"{gateway}/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Authorization": f"Bearer {key}",
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                text = json.load(r)["choices"][0]["message"]["content"]
            start, end = text.find("{"), text.rfind("}")
            return json.loads(text[start:end + 1])
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError) as e:
            print(f"    {model}: {type(e).__name__}: {str(e)[:120]} — retry {attempt + 1}/{attempts}",
                  flush=True)
            time.sleep(30 * (attempt + 1))
    return {"applicable": [], "error": "no answer"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", default="var/eval/coverage")
    ap.add_argument("--scheme", default="healthcare-provider-v2.0")
    ap.add_argument("--models", default="kimi-k3,claude-sonnet-5")
    ap.add_argument("--only", default="", help="comma-separated case names; default all without expected.json")
    args = ap.parse_args()

    gateway = (os.environ.get("EVAL_GATEWAY") or os.environ.get("PUBLIC_GATEWAY_URL")
               or os.environ.get("GATEWAY_URL", "http://127.0.0.1:4000")).rstrip("/")
    keys = {"kimi-k3": os.environ["USECASE_AGENT_KEY"]}
    master = os.environ.get("LITELLM_MASTER_KEY", "")
    corpus = _ev.corpus_for(args.scheme, os.environ.get(
        "REFERENCE_MODELS_DIR", str(Path.home() / "Development/local-agent-lab/var/reference-sources")))
    leaves = coverage.leaves_for(corpus)
    listing = "\n".join(f'{l["id"]} | {l["path"]} | {str(l.get("definition") or "")[:220]}'
                        for l in leaves)
    by_id = {l["id"]: l for l in leaves}
    print(f"scheme {args.scheme}: {len(leaves)} leaves | gateway {gateway}")

    only = {c for c in args.only.split(",") if c}
    cases = sorted(p for p in Path(args.cases).glob("*") if (p / "submission.md").exists()
                   and (p.name in only if only else not (p / "expected.json").exists()))
    for case in cases:
        prompt = PROMPT % ((case / "submission.md").read_text(), listing)
        picks: dict[str, list] = {}
        for model in args.models.split(","):
            key = keys.get(model) or master
            if not key:
                print(f"  {case.name}: no credential for {model} — skipped"); continue
            started = time.time()
            out = ask(gateway, key, model, prompt)
            chosen = []
            for item in out.get("applicable") or []:
                leaf = by_id.get(str(item.get("id") or "").strip())
                if leaf:
                    chosen.append({"id": leaf["id"], "label": leaf["label"], "path": leaf["path"],
                                   "why": str(item.get("why") or "")[:200]})
            picks[model] = chosen
            print(f"  {case.name:26} {model:16} {len(chosen):3} picks  {time.time() - started:4.0f}s",
                  flush=True)
        labels = {m: {c["label"] for c in v} for m, v in picks.items()}
        agreed = sorted(set.intersection(*labels.values())) if labels else []
        either = sorted(set.union(*labels.values())) if labels else []
        draft = {"DRAFT": "blind human review required — promote to expected.json as "
                          '{"applicable": [labels]}; a model adjudicating a model is not an expected set',
                 "scheme": args.scheme, "agreed": agreed, "either": either, "by_model": picks}
        (case / "expected.draft.json").write_text(json.dumps(draft, indent=2, ensure_ascii=False))
        print(f"  {case.name}: agreed {len(agreed)} · either {len(either)} -> expected.draft.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
