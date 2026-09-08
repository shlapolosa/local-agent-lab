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

from lab.platform import config, container
from lab.platform.contracts import TRANSCRIPT_TO_MINUTES
from lab.workloads.identity import agent_headers
from lab.workloads.run import governed_run
from lab.workloads.transcript_to_minutes import agents as A
from lab.workloads.transcript_to_minutes.workflow import make_cfg, run_workflow

SERVICE = "process-transcript-to-minutes"
PROCESS = TRANSCRIPT_TO_MINUTES.name        # the registry names the process; nothing re-types it
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
                   meeting: dict | None = None, recording: str = "", chat_id: str = "",
                   provider: str = "", on_trace=None) -> dict:
    """One governed run: root span -> identity -> workflow -> minutes in the semantic layer.

    The span, the trace headers, the run-log entry and the one way a run is closed are the SHARED
    skeleton (`lab.workloads.run.governed_run`).
    """
    cred = _cred()
    headers = {"traceparent": ""}          # filled per run below; the agent is built with the run's

    def cfg(c):
        headers["traceparent"] = c.traceparent_header
        return make_cfg(credential=cred, traceparent=c.traceparent_header, schema=_schema(),
                        agent=A.make_agent(credential=cred, gateway_url=config.GATEWAY_URL,
                                           model=config.MINUTES_AGENT_MODEL, headers=headers,
                                           store=config.AGENT_RESPONSES_STORE,
                                           # the SAME schema the gate validates against: one
                                           # contract, shown to the model that must satisfy it
                                           schema=_schema()),
                        tracer=c.tracer, root_ctx=c.root_ctx, mcp_url=c.mcp_url, run_id=c.run_id)

    # The meeting's own identity. A `recording` handle names it properly: the handle is
    # collab://recording/<meeting>/<record>, so its SCOPE is the meeting and no lookup is needed.
    # Without one we fall back to the transcript's own label — which is honest but is NOT a meeting
    # id, so anything writing back beside the meeting must check `resolved`.
    meeting = meeting or _meeting_from(recording, transcript, chat_id)
    return await governed_run(
        root, span_name="transcript-to-minutes-run", process=PROCESS, label=_label(transcript),
        on_trace=on_trace,
        # counts and shapes only — a span reaches a collector the gateway's guardrail never sees
        attrs={"minutes.speakers": len(speaker_map or {})},
        cfg=cfg, run=run_workflow, fields=run_fields,
        # `provider` is the LANE this run belongs to, carried from the transcript run across the
        # approval. It changes nothing about how the minutes are written — they are always written
        # by the lab's own model — but it names every artifact this lane delivers, which is the only
        # thing stopping four lanes from overwriting one another beside the recording.
        inputs={"transcript": transcript, "speaker_map": speaker_map, "owner": owner,
                "meeting": meeting, "recording": recording, "provider": provider})


def _meeting_from(recording: str, transcript: str, chat_id: str = "") -> dict:
    """What this run knows about the meeting, given the handle the recording arrived under.

    ONLY a recording/transcript handle names a meeting. `collab://recording/<meeting>/<record>` has
    the meeting in its scope; `collab://item/<drive>/<file>` has a DRIVE there, and calling that a
    meeting would mint `meeting-b!eTA-…` and tell every downstream reader the meeting was known. A
    file-triggered producer (a flow watching a folder) sends the item form, so this is the common
    case, not the exotic one.

    `chat_id` is not derived from either: only the run that resolved the MEETING could know it, so
    it is carried across the approval and simply passed through here.

    `resolved` is the flag every downstream reader must honour: false means the id is a filename
    standing in for a meeting nobody could name — fine for keying a model, useless for putting
    anything back beside the meeting. The handle is carried either way, because even an item handle
    says which drive and which file, which is what a writer needs to find where to write."""
    from lab.core.collab import ContentHandle, HandleKind

    base = {"id": _label(transcript), "subject": _label(transcript), "resolved": False,
            # Where the result is ANNOUNCED, carried across the approval by the run that resolved
            # the meeting. It is independent of `resolved`: the flow that watches a folder sends an
            # ITEM handle, so a run can know exactly which conversation to tell and still have no
            # meeting id of its own. Empty is the honest common case — an ad-hoc recording belongs
            # to no meeting, so there is no conversation to post to.
            "chat_id": chat_id or "",
            "transcript_ref": transcript}
    if not (recording and ContentHandle.is_handle(recording)):
        return base
    try:
        handle = ContentHandle.parse(recording)
    except ValueError:
        return base
    base["recording"] = recording
    if handle.kind in (HandleKind.RECORDING, HandleKind.TRANSCRIPT):
        return base | {"id": handle.scope, "resolved": True}
    return base

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
