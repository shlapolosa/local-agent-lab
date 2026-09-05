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
from lab.platform.contracts import SemanticTools, StorageTools
from lab.workloads import gateway, workflowviz

REQUIRED_TOOLS = (StorageTools.read_document, SemanticTools.store_spec, SemanticTools.load_model,
                  SemanticTools.validate_model)

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


def _incomplete(minutes: dict, labels: set[str]) -> list[str]:
    """What a schema cannot see. Ordered by how badly each one misleads a reader."""
    bad: list[str] = []
    concepts = {c["id"] for c in minutes.get("concepts") or []}
    if not concepts:
        bad.append("no concepts — a meeting the minutes cannot say was ABOUT anything is not usable")
    for key, field in (("decisions", "decided_by"), ("actions", "owner")):
        for item in minutes.get(key) or []:
            named = item.get(field) or []
            for who in ([named] if isinstance(named, str) else named):
                if who not in labels:
                    # the single likeliest hallucination, and invisible to a schema
                    bad.append(f'{item.get("id")} names {who!r}, who is not a speaker in this transcript')
            for cid in item.get("concerns") or []:
                if cid not in concepts:
                    bad.append(f'{item.get("id")} concerns {cid!r}, which is not one of its concepts')
    return bad


def gate(validator, minutes, labels: set[str]) -> list[str]:
    """Every reason these minutes cannot be used, or an empty list."""
    _normalise_evidence(minutes if isinstance(minutes, dict) else {})
    errors = _schema_errors(validator, minutes)
    return errors or _incomplete(minutes, labels)


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
            doc = await _call(cfg, StorageTools.read_document, {"ref": state["transcript"]})
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
            prose = "\n".join(f'{mapping.of(s["speaker"]).display}: {s.get("text", "")}'.rstrip()
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
            minutes_ref = stored["ref"] if isinstance(stored, dict) and "ref" in stored else stored
            spec_stored = await _call(cfg, SemanticTools.store_spec,
                                      {"spec": state["spec"], "name": f"{model_id}.spec.json"})
            spec_ref = spec_stored["ref"] if isinstance(spec_stored, dict) and "ref" in spec_stored else spec_stored
            loaded = await _call(cfg, SemanticTools.load_model,
                                 {"spec_ref": spec_ref, "model_id": model_id, "vocab": VOCAB})
            state = state | {"minutes_ref": minutes_ref, "model_id": model_id, "loaded": loaded}
        await ctx.send_message(state)

    @executor(id="publish")
    async def publish(state: dict, ctx: WorkflowContext[dict]) -> None:
        with _span(cfg, "publish"):
            m = state["minutes"]
            keywords = sorted({c["label"] for c in m.get("concepts") or []}
                              | {k for k in (m.get("keywords") or []) if k})
            out = {"transcript_ref": state["transcript"], "minutes_ref": state["minutes_ref"],
                   "model_id": state["model_id"], "keywords": keywords,
                   "summary": {"concepts": len(m.get("concepts") or []),
                               "decisions": len(m.get("decisions") or []),
                               "actions": len(m.get("actions") or []),
                               "speakers": len(state["map"].entries),
                               "triples": (state["loaded"] or {}).get("triples", 0),
                               "text": m.get("summary", "")}}
        await ctx.yield_output(out)

    return (WorkflowBuilder(start_executor=attribute)
            .add_chain([attribute, minutes, to_spec, load_semantic, publish]).build())


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
