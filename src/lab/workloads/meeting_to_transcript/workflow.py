"""The `meeting_to_transcript` graph: a recording becomes a question its organiser can answer.

    fetch_recording [D] -> transcribe [D] -> speaker_digest [D] -> ask_mapping [D, terminal]

FOUR DETERMINISTIC STEPS AND NO AGENT, deliberately. The obvious temptation is an agent that guesses
who each speaker is from self-introductions. It is the wrong call: it anchors the human on exactly
the judgement being asked for, and its failure mode is a confident wrong identity that the organiser
clicks straight through — which is the single thing this gate exists to prevent. If it is ever added
it needs a schema gate and every surface must label it "suggested, unverified".

WHY THE RUN ENDS BY ASKING. The approval gate is terminal by construction in this lab: a run stages
its question, publishes it and finishes. People take hours and runs take minutes, so blocking is not
an option — the answer comes back through whichever channel the person used, and the continuation
runner starts whatever the answer completes.

WHY IT IS TWO PROCESSES AND NOT ONE PAUSED ONE. A paused run would need checkpoint storage, a
rewrite to class-based executors, a non-terminal status, and an exception in the consumer's restart
hygiene so a redeploy stopped killing runs that were waiting on a human. And it would still need
something to consume the decision. Two processes need only that one thing.
"""
from __future__ import annotations

import contextlib

from agent_framework import WorkflowBuilder, WorkflowContext, executor

from lab.platform import runlog
from lab.platform.contracts import (ApprovalTools, CollabTools, Continuation, SpeechTools,
                                    TRANSCRIPT_TO_MINUTES)
from lab.workloads import gateway, workflowviz

# Spelled from the contract, never as bare strings: a renamed tool must break the build, not a run
# twenty minutes in. `tests/governance/test_workload_uses_contracts.py` enforces it.
REQUIRED_TOOLS = (CollabTools.fetch, SpeechTools.transcribe, ApprovalTools.ask)

PROMPT = ("Who is each speaker? For every SPEAKER_nn below, give the person's directory identity "
          "(their email or user principal name) if they are in the organisation, or a free tag "
          "describing them if they are not — a guest, a vendor, anyone external. Use the duration, "
          "the turn count and the sample quotes to tell the voices apart. Answer for every speaker: "
          "an unidentified one stops the minutes being written.")


def make_cfg(*, credential: str = "", mcp_url: str = "", traceparent: str = "",
             languages: tuple[str, ...] = (), tracer=None, root_ctx=None, run_id: str = ""):
    """The ONE config contract for every host of this process (CLI, consumer, DevUI).

    Everything the graph needs arrives here as a VALUE. Nothing below this reads the environment,
    which is what keeps the workload off the env-reader ratchet: modes and addresses are decided by
    the composition root that built the container, not rediscovered in a node.
    """
    from lab.platform import config
    headers = {"Authorization": f"Bearer {credential}"} if credential else {}
    if traceparent:
        headers["traceparent"] = traceparent
    return {"headers": headers, "mcp_url": mcp_url or config.GATEWAY_MCP_URL,
            "languages": tuple(languages), "tracer": tracer, "root_ctx": root_ctx, "run_id": run_id}


def _span(cfg, node: str):
    """One context manager per node: the OTel span joined to the run's root, and the run-log entry
    the Runs board draws. No run id means telemetry only."""
    rid = cfg.get("run_id")
    return runlog.span_node(rid, node) if rid else contextlib.nullcontext()


async def _call(cfg, suffix: str, args: dict):
    """One gateway-MCP tool call. The shared transport resolves by name suffix, so this workload
    stays alias-agnostic."""
    return (await gateway.call_tools(cfg["headers"], cfg["mcp_url"], [(suffix, args)]))[0]


# How many of the organiser's recent meetings to check before giving up. Each costs one extra tool
# call, and the meeting that produced a recording is almost always among the newest few — a bound
# keeps a convenience from turning into a long tail of calls on a busy calendar.
CANDIDATE_MEETINGS = 10


async def _attendees(cfg, state: dict) -> list[dict]:
    """The participants of the meeting this recording came from, or []. Never raises.

    Finds the meeting by asking which of the organiser's recent ones OWNS this recording handle,
    which is exact and provider-neutral. `participants` is who was CONNECTED, so it is a starting
    point and not the answer: one device in a room is one participant, and someone can attend and
    never speak. That is precisely why it is offered as a suggestion beside free text.
    """
    try:
        meetings = await _call(cfg, CollabTools.meetings, {"organizer": state.get("owner", ""),
                                                           "limit": CANDIDATE_MEETINGS})
        for m in (meetings or {}).get("items", [])[:CANDIDATE_MEETINGS]:
            recs = await _call(cfg, CollabTools.recordings, {"meeting_id": m.get("id", "")})
            if any(r.get("handle") == state["recording"] for r in (recs or {}).get("items", [])):
                return [{"identity": p, "display": ""} for p in (m.get("participants") or []) if p]
    except Exception as e:                      # noqa: BLE001 — a picker is never worth a failed run
        print(f"[resolve_candidates] no candidates ({type(e).__name__}: {e})", flush=True)
    return []

def build_workflow(cfg):
    """The typed graph. Every node is deterministic, so each one either produces its artifact or
    fails naming what was wrong — there is no 'the model skipped a step' path to defend against."""

    @executor(id="fetch_recording")
    async def fetch_recording(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Stream the recording into the lab's own upload store and keep only the reference.

        The bytes never enter this process: a recording is gigabytes and a workload holds no store
        credentials, so `collab_fetch` writes it and hands back an `art://` reference.
        """
        with _span(cfg, "fetch_recording"):
            got = await _call(cfg, CollabTools.fetch, {"handle": state["recording"]})
            state = state | {"recording_ref": got["ref"], "recording_name": got.get("name", ""),
                             "recording_bytes": got.get("bytes", 0)}
        await ctx.send_message(state)

    @executor(id="transcribe")
    async def transcribe(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Transcribe and separate the speakers, passing EVERY language the meeting uses.

        The language hint is the most important argument in this whole process. Declaring one
        language when two are spoken is what makes an engine translate or transliterate the switched
        span instead of transcribing it, and the result reads as fluent and correct.

        The gate here is the one that matters for an in-person meeting: no speakers at all means the
        audio was transcribed but never separated, and asking an organiser to identify a single
        SPEAKER_00 for an entire meeting is worse than failing, because they would answer it.
        """
        with _span(cfg, "transcribe"):
            got = await _call(cfg, SpeechTools.transcribe,
                              {"audio_ref": state["recording_ref"],
                               "languages": list(cfg["languages"]), "diarize": True})
            if not got.get("speakers"):
                raise RuntimeError(
                    "the recording produced no speaker separation — it was transcribed but not "
                    f"diarized, so there is nobody to ask about. Check {SpeechTools.capabilities}, "
                    "and for a room on one microphone check the recording itself.")
            state = state | {"transcript_ref": got["transcript_ref"], "speech": got}
        await ctx.send_message(state)

    @executor(id="speaker_digest")
    async def speaker_digest(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Turn the speaker digest into the question items a human will read.

        Nothing is invented here: duration, turn count and the sample quotes all come from the
        transcript. The samples are what actually let a person tell one voice from another, and a
        speaker with none is still asked about — an unlabelled voice is exactly the one a human most
        needs to resolve.
        """
        with _span(cfg, "speaker_digest"):
            items = [{"label": s["label"], "seconds": round(float(s.get("seconds") or 0.0), 1),
                      "turns": int(s.get("turns") or 0), "samples": list(s.get("samples") or ())}
                     for s in state["speech"]["speakers"]]
            state = state | {"items": items}
        await ctx.send_message(state)

    @executor(id="resolve_candidates")
    async def resolve_candidates(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Who the provider says attended, offered to the human as a PICK instead of a typed address.

        Why bother: the answer needs a directory identity, and a typed one fails LATE — a mistyped
        address passes the gate and only breaks during attribution, long after the person who could
        correct it has gone.

        BEST EFFORT, and that is a design position rather than laziness. The run must not fail
        because a convenience could not be computed, so every failure here yields an empty list and
        the question still works exactly as before. It is also why the tools it uses are NOT in
        `REQUIRED_TOOLS`: a deployment that does not grant them should degrade, not be refused by
        preflight.

        The match is by HANDLE, never by parsing the recording's filename. A provider's file naming
        is a vendor detail this side of the collaboration port must not know, and a wrong match here
        would put the wrong people in front of the human — worse than offering nobody.
        """
        with _span(cfg, "resolve_candidates"):
            state = state | {"candidates": await _attendees(cfg, state)}
        await ctx.send_message(state)

    @executor(id="ask_mapping")
    async def ask_mapping(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Ask the organiser, once, about every speaker — and finish.

        Terminal by design. What approving releases is carried on the approval itself, so the next
        run starts without this one waiting.
        """
        with _span(cfg, "ask_mapping"):
            speech = state["speech"]
            reported = bool(speech.get("languages"))
            summary = {
                "speakers": len(state["items"]),
                "duration_s": round(float(speech.get("duration") or 0.0), 1),
                "recording": state.get("recording_name", ""),
                "organiser": state["owner"],
                "languages": list(speech.get("languages") or ()),
                "languages_reported": reported,
                # None, not False. A provider that reports no per-segment language cannot tell us
                # whether a switch happened, and rendering that as "no" would quietly answer the
                # question this whole workload exists to ask.
                "code_switched": bool(speech.get("code_switched")) if reported else None,
                "warnings": list(speech.get("warnings") or ()),
            }
            # What approving this RELEASES. It rides on the approval rather than in a registry
            # because a static "A is followed by B" edge cannot carry the transcript reference of
            # THIS run — and it is validated at construction, so a typo fails now rather than hours
            # later as a human approving and nothing happening.
            cont = Continuation(process=TRANSCRIPT_TO_MINUTES.name,
                                inputs={"transcript": state["transcript_ref"],
                                        "owner": state["owner"]},
                                answer_input="speaker_map", requester=state["owner"])
            asked = await _call(cfg, ApprovalTools.ask, {
                "subject": f'{state.get("recording_name") or "meeting"} — who is speaking?',
                "prompt": PROMPT,
                "items": state["items"],
                "candidates": state.get("candidates") or [],
                "continuation": cont.to_dict(),
                "artifacts": {"recording": state["recording_ref"],
                              "transcript": state["transcript_ref"]},
                "requester": state["owner"]})
            out = {"request_id": asked["request_id"], "status": asked.get("status", "pending"),
                   "approval_id": asked["request_id"], "review_app": asked.get("review_app", ""),
                   "recording_ref": state["recording_ref"],
                   "transcript_ref": state["transcript_ref"],
                   "speakers": state["items"],
                   "candidates": state.get("candidates") or [], "summary": summary}
        await ctx.yield_output(out)

    return (WorkflowBuilder(start_executor=fetch_recording)
            .add_chain([fetch_recording, transcribe, speaker_digest, resolve_candidates,
                            ask_mapping]).build())


async def run_workflow(cfg, inputs: dict):
    """Preflight, then run. A version mismatch costs ZERO tokens and zero provider credits."""
    await gateway.preflight(cfg["mcp_url"], cfg["headers"], REQUIRED_TOOLS)
    wf = build_workflow(cfg)
    if cfg.get("run_id"):
        runlog.update(cfg["run_id"], mermaid=workflowviz.mermaid(wf))
    result = await wf.run(dict(inputs))
    outs = result.get_outputs()
    if not outs:
        raise RuntimeError("the run produced no output — no approval was raised")
    return outs[0]
