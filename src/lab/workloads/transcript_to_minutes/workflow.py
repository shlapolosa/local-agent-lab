"""The `transcript_to_minutes` graph: an attributed transcript becomes knowledge.

    attribute [D] -> minutes [A] -> minutes_gate [D] -> to_spec [D] -> load_semantic [D] -> publish [D]

ONE agent step, gated. Everything either side of it is deterministic, which is the lab's rule: an
agent's output never flows onward un-validated, and the things a model must not decide — ids, IRIs,
vocabulary types, who a speaker is — are decided by code.

The gate is the interesting part. Its order matters and each check earns its place:

  1. **normalise evidence in place**, so the schema sees ONE shape and an error can name the
     offending item rather than saying "not valid under any of the given schemas", which a
     corrective retry cannot act on;
  2. **the schema**;
  3. **completeness**, and the check that matters most is that every speaker the minutes mention is
     one the diarizer actually produced. An invented SPEAKER_09 is the single likeliest failure, and
     it is invisible to a schema.

One corrective retry, re-sending the same content: the client is stateless, so a bare text
correction would run blind.
"""
from __future__ import annotations

import contextlib
import json

from agent_framework import WorkflowBuilder, WorkflowContext, executor
from jsonschema import Draft7Validator

from lab.core.meetings import Speakers, minutes_to_spec
from lab.platform import runlog
from lab.platform.contracts import CollabTools, SemanticTools, StorageTools
from lab.workloads import gateway, workflowviz

REQUIRED_TOOLS = (StorageTools.read_artifact, SemanticTools.store_spec, SemanticTools.load_model,
                  SemanticTools.validate_model)
# NOT required: delivery is best effort, so a deployment that does not grant the collaboration tools
# still writes minutes — it simply cannot put them back. Listing them here would refuse the whole run
# at preflight for want of a convenience, which is the opposite of what best effort means.
DELIVERY_TOOLS = (CollabTools.item, CollabTools.put)

VOCAB = "meeting-1.0"


def make_cfg(*, credential: str = "", mcp_url: str = "", traceparent: str = "", schema: dict | None = None,
             agent=None, tracer=None, root_ctx=None, run_id: str = ""):
    """The ONE config contract for every host of this process. Nothing below reads the environment."""
    from lab.platform import config
    headers = {"Authorization": f"Bearer {credential}"} if credential else {}
    if traceparent:
        headers["traceparent"] = traceparent
    return {"headers": headers, "mcp_url": mcp_url or config.GATEWAY_MCP_URL, "credential": credential,
            "schema": schema or {}, "agent": agent, "tracer": tracer, "root_ctx": root_ctx,
            "run_id": run_id}


def _span(cfg, node: str):
    rid = cfg.get("run_id")
    return runlog.span_node(rid, node) if rid else contextlib.nullcontext()


async def _call(cfg, suffix: str, args: dict):
    return (await gateway.call_tools(cfg["headers"], cfg["mcp_url"], [(suffix, args)]))[0]


def _schema_errors(validator, obj) -> list[str]:
    if not isinstance(obj, dict):
        return ["not valid JSON"]
    return [f'{"/".join(str(p) for p in e.path) or "(root)"}: {e.message}'
            for e in list(validator.iter_errors(obj))[:5]]


def _normalise_evidence(minutes: dict) -> None:
    """Expand the bare-speaker shorthand so the schema validates ONE shape. In place, deliberately —
    the alternative is a schema union whose errors name nothing a retry can act on."""
    for key in ("concepts", "decisions", "actions"):
        for item in minutes.get(key) or []:
            ev = item.get("evidence")
            if isinstance(ev, str):
                item["evidence"] = [{"speaker": ev}]
            elif isinstance(ev, list):
                item["evidence"] = [{"speaker": e} if isinstance(e, str) else e for e in ev]


# What a model calls these fields when it is not copying the schema. Every one of these is a WORD
# CHOICE, not a difference in meaning: `name`/`title` for a concept's label, `description` for its
# definition. Measured, not guessed — a live run emitted `{id: "C1", name, description}` for every
# concept, was told exactly which properties were unexpected, and emitted the same shape again. A
# retry cannot teach vocabulary, so the vocabulary is normalised instead.
_SYNONYMS = {"concepts": {"name": "label", "title": "label", "description": "definition",
                          "meaning": "definition"},
             "decisions": {"decision": "statement", "text": "statement", "why": "rationale",
                           "about": "concerns", "owner": "decided_by"},
             "actions": {"action": "commitment", "task": "commitment", "what": "commitment",
                         "assignee": "owner", "deadline": "due", "about": "concerns"}}
_ID_PREFIX = {"concepts": "c", "decisions": "d", "actions": "a"}


def _normalise_shape(minutes: dict) -> None:
    """Accept the near-misses a model reliably makes, in place, BEFORE the schema sees them.

    Two of them, and both are cosmetic: a synonym for a field name, and an id written `C1` where the
    schema wants `c1`. Neither changes what the minutes SAY, and rejecting a whole run over the case
    of a letter throws away a real transcription and a human's speaker mapping.

    Deliberately conservative — a synonym is only applied when the canonical field is ABSENT, so a
    model that got it right is never overwritten, and an id is only rewritten when it differs from
    the schema's shape purely by case or by a missing prefix. Anything else still fails the gate.
    """
    for key, syn in _SYNONYMS.items():
        for n, item in enumerate(minutes.get(key) or [], start=1):
            if not isinstance(item, dict):
                continue
            for wrong, right in syn.items():
                if wrong in item and not str(item.get(right) or "").strip():
                    item[right] = item.pop(wrong)
            got = str(item.get("id") or "").strip()
            want = _ID_PREFIX[key]
            if got[:1].lower() == want and got[1:].isdigit():
                item["id"] = got.lower()                    # "C1" -> "c1"
            elif got.isdigit():
                item["id"] = f"{want}{got}"                 # "1"  -> "c1"
            elif not got:
                item["id"] = f"{want}{n}"                   # absent -> positional, so the cross
                                                            # references below still have something
    # ...and the references INTO those ids, which must move with them
    for key in ("decisions", "actions"):
        for item in minutes.get(key) or []:
            if isinstance(item, dict) and isinstance(item.get("concerns"), list):
                item["concerns"] = [c.lower() if isinstance(c, str) and c[:1].lower() == "c"
                                    and c[1:].isdigit() else c for c in item["concerns"]]


def _who(name: str) -> str:
    """One speaker name, as this gate compares them: casefolded and stripped.

    Compared as IDENTITY, not as text. A human typed "Motamad" into the mapping card and the model
    wrote "motamad" in the minutes — the same person, and an exact-string gate rejected the whole
    meeting over the case of one letter, after a correct transcription and a correct human answer.
    `casefold` rather than `lower` because these names are not always ASCII: this pipeline exists
    for meetings held in Arabic and English.

    What the reader SEES is still whatever the model wrote; only the comparison is normalised.
    """
    return " ".join(str(name or "").split()).casefold()


def _incomplete(minutes: dict, labels: set[str]) -> list[str]:
    """What a schema cannot see. Ordered by how badly each one misleads a reader."""
    bad: list[str] = []
    concepts = {c["id"] for c in minutes.get("concepts") or []}
    if not concepts:
        bad.append("no concepts — a meeting the minutes cannot say was ABOUT anything is not usable")
    known = {_who(l) for l in labels}
    for key, field in (("decisions", "decided_by"), ("actions", "owner")):
        for item in minutes.get(key) or []:
            named = item.get(field) or []
            for who in ([named] if isinstance(named, str) else named):
                if _who(who) not in known:
                    # the single likeliest hallucination, and invisible to a schema
                    bad.append(f'{item.get("id")} names {who!r}, who is not a speaker in this transcript')
            for cid in item.get("concerns") or []:
                if cid not in concepts:
                    bad.append(f'{item.get("id")} concerns {cid!r}, which is not one of its concepts')
    return bad


def gate(validator, minutes, labels: set[str]) -> list[str]:
    """Every reason these minutes cannot be used, or an empty list.

    `labels` are the SPEAKER_nn labels, because that is what the schema tells the model to write:
    "Labels only; who they are is the human's answer, not yours." The prose it reads must therefore
    SHOW those labels — see `attribute`, which for a long time showed only display names and so
    demanded a vocabulary the model was never given."""
    m = minutes if isinstance(minutes, dict) else {}
    _normalise_shape(m)
    _normalise_evidence(m)
    errors = _schema_errors(validator, minutes)
    return errors or _incomplete(m, labels)


async def _deliver(cfg, state: dict, handle: str) -> dict:
    """Upload the prose transcript and the minutes into the folder the recording sits in.

    The PROSE transcript, not the structured one: it carries display names only, so what lands in
    the tenant is readable and holds no directory addresses. The structured form stays in the lab as
    the audit trail — publishing it would put a list of who-is-who into a folder whose permissions
    are the recording's, which is a wider audience than the audit needs.
    """
    item = await _call(cfg, CollabTools.item, {"handle": handle})
    folder = item.get("parent_handle")
    if not folder:
        return {"delivery": f'{item.get("name") or handle} names no folder to write beside'}
    # The LANE is in the filename, and this is not cosmetic. `collab_put` REPLACES a file of the
    # same name in the same folder — deliberately, so a re-run corrects its own output — and every
    # lane derives the same stem from the same recording. Four providers would therefore write four
    # files called `<stem>.transcript.md`, the last one to finish would win, the other three would
    # be gone, and nothing anywhere would report an error. A lane-less run keeps the original names,
    # so a deployment running one provider sees no change.
    stem = str(item.get("name") or "meeting").rsplit(".", 1)[0]
    lane = str(state.get("provider") or "").strip()
    if lane:
        stem = f"{stem}.{lane}"

    prose_ref = await _store(cfg, f"{stem}.transcript.md", state["prose"].encode())
    written = []
    for ref, name in ((prose_ref, f"{stem}.transcript.md"),
                      (state["minutes_ref"], f"{stem}.minutes.json")):
        out = await _call(cfg, CollabTools.put, {"folder": folder, "ref": ref, "name": name})
        written.append({"name": out.get("name", name), "handle": out.get("handle", ""),
                        # the address a person opens — without it the meeting gets a notice it
                        # cannot act on, which is the same as no notice
                        "url": out.get("url", ""), "bytes": out.get("bytes", 0)})
    return {"delivered": written, "chat_id": (state.get("meeting") or {}).get("chat_id", ""),
            "delivery": f"{len(written)} file(s) beside the recording"}


async def _store(cfg, name: str, data: bytes) -> str:
    """The prose transcript as an artifact, so the upload reads it the way everything else does —
    by reference through the governed store, never as bytes on a tool argument."""
    return gateway.ref_from(await _call(cfg, SemanticTools.store_spec,
                                       {"spec": {"text": data.decode()}, "name": name}))

def build_workflow(cfg):
    validator = Draft7Validator(cfg["schema"]) if cfg.get("schema") else None

    @executor(id="attribute")
    async def attribute(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Rewrite the transcript with the people a human identified.

        Two artifacts, and the split is load-bearing: the structured one keeps the directory
        addresses for the audit trail, and the prose one — the only one the model reads — carries
        display names only. The gateway pseudonymises addresses, so a transcript full of them
        reaches the model as placeholders and degrades the moment it paraphrases one.
        """
        with _span(cfg, "attribute"):
            doc = await _call(cfg, StorageTools.read_artifact, {"ref": state["transcript"]})
            segments = _segments(doc)
            # translate the APPROVAL's answer into the domain's own idea of a speaker:
            # the mapper should not care that it arrived through a human gate
            mapping = Speakers.from_answer(state["speaker_map"])
            used = {s.get("speaker") for s in segments if s.get("speaker")}
            mapped = {e.label for e in mapping.entries}
            if used - mapped:
                raise RuntimeError(
                    f"the transcript uses {sorted(used - mapped)}, which nobody identified — the "
                    "minutes would name an anonymous label as a person")
            if mapped - used:
                raise RuntimeError(f"{sorted(mapped - used)} were identified but never speak in this "
                                   "transcript — the answer does not match the recording")
            # BOTH: the LABEL the schema tells the model to write back, and the NAME that makes the
            # transcript readable to a person. Showing only the name demanded a vocabulary the model
            # never saw — every run failed with "'motamad' is not a speaker in this transcript" while
            # Motamad plainly was one. Showing only the label would leave a human with SPEAKER_01.
            prose = "\n".join(
                f'{s["speaker"]} ({mapping.of(s["speaker"]).display}): {s.get("text", "")}'.rstrip()
                for s in segments if s.get("text", "").strip())
            state = state | {"segments": segments, "labels": used, "map": mapping, "prose": prose}
        await ctx.send_message(state)

    @executor(id="minutes")
    async def minutes(state: dict, ctx: WorkflowContext[dict]) -> None:
        """OUR model, through OUR gateway. One corrective retry, re-sending the same content."""
        with _span(cfg, "minutes"):
            agent, prose = cfg["agent"], state["prose"]
            reply = await agent.run(prose)
            got = _json(reply)
            problems = gate(validator, got, state["labels"]) if validator else []
            if problems:
                # the client is stateless, so the correction must carry the transcript again
                reply = await agent.run(
                    f"{prose}\n\nYour previous answer was rejected:\n- " + "\n- ".join(problems) +
                    "\n\nEmit corrected JSON only.")
                got = _json(reply)
                problems = gate(validator, got, state["labels"])
                if problems:
                    raise RuntimeError("minutes rejected after retry: " + "; ".join(problems))
            state = state | {"minutes": got}
        await ctx.send_message(state)

    @executor(id="to_spec")
    async def to_spec(state: dict, ctx: WorkflowContext[dict]) -> None:
        """The pure mapper, then the vocabulary's own validation. Two independent gates: shape, then
        semantics — an illegal edge fails here rather than inside the store."""
        with _span(cfg, "to_spec"):
            spec = minutes_to_spec(state["minutes"], state["meeting"], state["map"])
            check = await _call(cfg, SemanticTools.validate_model, {"spec": spec, "vocab": VOCAB})
            if check.get("illegal"):
                raise RuntimeError(f"the mapped model is illegal against {VOCAB}: {check['illegal'][:3]}")
            state = state | {"spec": spec}
        await ctx.send_message(state)

    @executor(id="load_semantic")
    async def load_semantic(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Store the minutes durably, then load the model so it can be queried.

        The order matters: the artifact is the source of truth and the graph is derived. The store is
        in-memory today, so what is loaded here answers questions for the life of that server and is
        rebuilt from the artifact when it is needed again.
        """
        with _span(cfg, "load_semantic"):
            model_id = f'meeting-{state["meeting"]["id"]}'
            stored = await _call(cfg, SemanticTools.store_spec,
                                 {"spec": state["minutes"], "name": f"{model_id}.minutes.json"})
            minutes_ref = gateway.ref_from(stored)
            spec_stored = await _call(cfg, SemanticTools.store_spec,
                                      {"spec": state["spec"], "name": f"{model_id}.spec.json"})
            spec_ref = gateway.ref_from(spec_stored)
            loaded = await _call(cfg, SemanticTools.load_model,
                                 {"spec_ref": spec_ref, "model_id": model_id, "vocab": VOCAB})
            state = state | {"minutes_ref": minutes_ref, "model_id": model_id, "loaded": loaded}
        await ctx.send_message(state)

    @executor(id="deliver")
    async def deliver(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Put the outputs back where the meeting is, so a person can find them without the lab.

        BEST EFFORT, and deliberately so. The minutes are already written, stored and loaded by the
        time this runs; failing the run because a tenant would not take a copy would throw away the
        work over its delivery. Every failure yields an empty `delivered` and a reason, which the
        outputs carry — so it is visible without being fatal, the same shape as the speaker picker.

        The destination is the FOLDER the recording sits in, which is what "beside the recording"
        means: a person who goes looking for the recording finds these next to it, and the provider
        indexes them for search. Without a recording handle there is nowhere to put them, and that
        is the honest end of it rather than a guess at some default folder.
        """
        with _span(cfg, "deliver"):
            state = state | {"delivered": [], "chat_id": "", "delivery": ""}
            handle = (state.get("meeting") or {}).get("recording") or ""
            if not handle:
                state["delivery"] = "no recording handle: nowhere to put the outputs"
            else:
                try:
                    state = state | await _deliver(cfg, state, handle)
                except Exception as e:              # noqa: BLE001 — delivery never costs the minutes
                    state["delivery"] = f"{type(e).__name__}: {e}"
                    print(f"[deliver] not delivered ({state['delivery']})", flush=True)
        await ctx.send_message(state)

    @executor(id="publish")
    async def publish(state: dict, ctx: WorkflowContext[dict]) -> None:
        with _span(cfg, "publish"):
            m = state["minutes"]
            keywords = sorted({c["label"] for c in m.get("concepts") or []}
                              | {k for k in (m.get("keywords") or []) if k})
            out = {"transcript_ref": state["transcript"], "minutes_ref": state["minutes_ref"],
                   "model_id": state["model_id"], "keywords": keywords,
                   # WHICH lane produced these minutes. Four lanes deliver four sets of files from
                   # one meeting, and a set of minutes that cannot name its provider cannot be
                   # compared with the others — which is the entire point of running four.
                   "provider": state.get("provider", ""),
                   # what reached the tenant, and where a notifier should announce it
                   "delivered": state.get("delivered") or [], "chat_id": state.get("chat_id", ""),
                   "delivery": state.get("delivery", ""),
                   "summary": {"concepts": len(m.get("concepts") or []),
                               "decisions": len(m.get("decisions") or []),
                               "actions": len(m.get("actions") or []),
                               "speakers": len(state["map"].entries),
                               "triples": (state["loaded"] or {}).get("triples", 0),
                               "text": m.get("summary", "")}}
        await ctx.yield_output(out)

    return (WorkflowBuilder(start_executor=attribute)
            .add_chain([attribute, minutes, to_spec, load_semantic, deliver, publish]).build())


def _segments(doc) -> list[dict]:
    """The diarized segments out of whatever the store handed back (a dict, or JSON as text)."""
    if isinstance(doc, str):
        doc = json.loads(doc)
    if isinstance(doc, dict) and "text" in doc and "segments" not in doc:
        doc = json.loads(doc["text"])
    segs = doc.get("segments") if isinstance(doc, dict) else doc
    if not isinstance(segs, list) or not segs:
        raise RuntimeError("the transcript has no segments — nothing to write minutes from")
    return segs


def _json(reply):
    """The agent's JSON, however the framework wrapped it."""
    text = getattr(reply, "text", None) or str(reply)
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1].removeprefix("json").strip()
    try:
        return json.loads(text)
    except ValueError:
        return None


async def run_workflow(cfg, inputs: dict):
    """Preflight, then run. A version mismatch costs zero tokens."""
    await gateway.preflight(cfg["mcp_url"], cfg["headers"], REQUIRED_TOOLS)
    wf = build_workflow(cfg)
    if cfg.get("run_id"):
        runlog.update(cfg["run_id"], mermaid=workflowviz.mermaid(wf))
    result = await wf.run(dict(inputs))
    outs = result.get_outputs()
    if not outs:
        raise RuntimeError("the run produced no minutes")
    return outs[0]
