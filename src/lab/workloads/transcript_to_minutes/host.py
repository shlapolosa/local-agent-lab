"""The `transcript_to_minutes` host — the composition root for this process.

Its own OTel service name, so it is traced and audited independently of the transcription run that
produced its input. It is the only place here that reads configuration; the graph takes every value
as an argument.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from opentelemetry import propagate, trace

from lab.platform import config, container, runlog
from lab.workloads.identity import agent_headers
from lab.workloads.transcript_to_minutes import agents as A
from lab.workloads.transcript_to_minutes.workflow import make_cfg, run_workflow

SERVICE = "process-transcript-to-minutes"
AGENT_PREFIX = "MINUTES_AGENT"
SCHEMA = Path(__file__).resolve().parents[3] / "lab" / "core" / "meetings" / "schemas" / "minutes.schema.json"


def _cred() -> str:
    return agent_headers(AGENT_PREFIX)["Authorization"].removeprefix("Bearer ").strip()


def _schema() -> dict:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def run_fields(out: dict) -> dict:
    """What a finished run's board row carries — one mapping for every host of this process."""
    return {"minutes_ref": out.get("minutes_ref"), "model_id": out.get("model_id")}


async def run_once(root, transcript: str, speaker_map: dict, owner: str = "",
                   meeting: dict | None = None, on_trace=None) -> dict:
    """One governed run: root span -> identity -> workflow -> minutes in the semantic layer."""
    tr, r = root.tracer(), root.redis()
    with tr.start_as_current_span("transcript-to-minutes-run") as span:
        trace_id = format(span.get_span_context().trace_id, "032x")
        span.set_attribute("lab.trace_id", trace_id)
        # counts and shapes only — a span reaches a collector the gateway's guardrail never sees
        span.set_attribute("minutes.speakers", len(speaker_map or {}))
        if on_trace:
            on_trace(trace_id)
        traceparent: dict = {}
        propagate.inject(traceparent)
        root_ctx = trace.set_span_in_context(span)
        run_id = trace_id
        runlog.start(run_id, process="transcript_to_minutes", input=_label(transcript),
                     trace_id=trace_id, client=r)

        cred = _cred()
        headers = {"traceparent": traceparent.get("traceparent", "")}
        cfg = make_cfg(credential=cred, traceparent=traceparent.get("traceparent", ""),
                       schema=_schema(),
                       agent=A.make_agent(credential=cred, gateway_url=config.GATEWAY_URL,
                                          model=config.MINUTES_AGENT_MODEL, headers=headers,
                                          store=config.AGENT_RESPONSES_STORE),
                       tracer=tr,
                       root_ctx=root_ctx, mcp_url=root.config.gateway_mcp_url(), run_id=run_id)
        # The meeting's own identity: the transcript reference is what every run of this process is
        # keyed on, so it is the meeting id when nothing better was supplied.
        meeting = meeting or {"id": _label(transcript), "subject": _label(transcript),
                              "transcript_ref": transcript}
        try:
            out = await run_workflow(cfg, {"transcript": transcript, "speaker_map": speaker_map,
                                           "owner": owner, "meeting": meeting})
        except Exception as e:
            runlog.finish_from(run_id, e, client=r)
            raise
        runlog.finish_from(run_id, client=r, **run_fields(out))
    return {**out, "trace_id": trace_id}


def _label(ref: str) -> str:
    return ref.rstrip("/").split("/")[-1]


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 2:
        print("usage: python -m lab.workloads.transcript_to_minutes.host "
              "<art://transcript> '<speaker map json>'", file=sys.stderr)
        return 2
    root = container.build(SERVICE)
    out = asyncio.run(run_once(root, argv[0], json.loads(argv[1]), argv[2] if len(argv) > 2 else ""))
    s = out["summary"]
    print(f'minutes {out["minutes_ref"]}\n  {s["concepts"]} concept(s), {s["decisions"]} decision(s), '
          f'{s["actions"]} action(s) -> {s["triples"]} triples\n  trace: {out["trace_id"]}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
