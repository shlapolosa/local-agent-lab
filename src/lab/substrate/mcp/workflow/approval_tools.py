"""The APPROVAL GATE as governed MCP tools — the human-in-the-loop surface of workflow-mcp, so a
channel where the reviewers already are (Teams via a Copilot Studio connector; any client, really)
can list, read and DECIDE approvals through the gateway exactly like every other capability: granted
per team, metered, PII-scanned, traced. Until now the only inbound path that carried a real identity
was a Python call (`lab.substrate.channels.teams.TeamsChannel.decide`), so deciding meant leaving
Teams for the review app.

WHY HERE, not on a server of its own: a run PAUSES for an approval. `<process>_status` already hands
back the `approval_id` it raised, so the same connector that submits a run and polls it must be able
to open the approval and answer it — one server, one grant, one connector. The read/decide split that
a separate server would have bought is expressed instead as TWO GRANTS over the one alias
(`ApprovalTools.READ` / `.WRITE` + the gateway's per-tool `mcp_tool_permissions`), which is the lab's
existing ACL mechanism and costs no extra service.

GOVERNANCE — `approvals_decide` records a HUMAN'S decision:
  * `actor` is a REQUIRED argument and must be the signed-in person the calling channel authenticated
    (`maria@contoso.com`), never the agent, never a default. Blank -> refused.
  * the rules live in `lab.substrate.approvals.human_decision` — the SAME function
    `TeamsChannel.decide` calls, so the tool and the channel cannot drift apart.
  * an agent must NEVER call it on its own initiative: an approval is the gate that stands between a
    model and a write into the EA repository (CLAUDE.md: destructive/write tools require human
    approval). The tool description says so to the model, the grant says so to the team.
  * the deciding human's identity is written to the AUDIT LOG (`approvals:decisions`), never to a
    span attribute — traces are the audit *trail*, and this lab's Jaeger is unauthenticated.
  * PROVENANCE is stamped by the SERVER: whatever channel the caller names is recorded as
    `mcp:<channel>`, so a tool call can never be mistaken in the audit log for a decision a person
    made at the review app. What the record still cannot prove is WHICH credential relayed it (the
    gateway authenticates to this server with the one shared MCP secret). Recording the caller
    principal beside the claimed actor — `recorded_by` from the gateway-forwarded key/JWT `oid` —
    is the next step, and is exactly the shape APIM + Entra give for free on Azure.

SCOPE: `approvals_list` answers with EVERY open approval — this is a single-tenant lab. Scoping a
channel to its own team's approvals needs the caller identity above; the `kind` filter is triage,
not a boundary.

CREDENTIALS: Redis only (the same role as the process tools) — approvals are Redis Streams, and the
artifacts a reviewer judges are handed out as `art://` refs, never dereferenced here.
"""
from __future__ import annotations

from typing import Annotated

from pydantic import Field

from lab.platform.contracts import (APPROVAL_FINAL, ApprovalKind, ApprovalStatus, ApprovalTools,
                                    Continuation, Decision, SpeakerPrompt, import_artifacts)
from lab.substrate import approvals
from lab.substrate.mcpserver import LabServer, span

SOURCE = "mcp"        # provenance the SERVER stamps, never the caller (see channel_of below)
MAX_LIST = 200

READ_ONLY = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False}
# destructiveHint: recording an approval RELEASES a repository write downstream — a client that asks
# a human before destructive calls (Copilot Studio does) should ask here too.
HUMAN_WRITE = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False,
               "openWorldHint": False}


def channel_of(claimed: str) -> str:
    """The channel recorded for a decision that arrived through this tool. The SOURCE is the server's
    to state and the caller's to qualify — `teams` -> `mcp:teams` — so the audit log distinguishes a
    connector's relay from a decision taken at the review app itself."""
    claimed = (claimed or "").strip()
    return f"{SOURCE}:{claimed}" if claimed and claimed != SOURCE else SOURCE


def _brief(st: dict, jaeger_url: str) -> dict:
    """What a channel needs to TRIAGE one approval: who wants what, how big it is, where to look."""
    payload = st.get("payload") or {}
    out = {"request_id": st.get("request_id"), "kind": st.get("kind"), "subject": st.get("subject"),
           "requester": st.get("requester"), "status": st.get("status"),
           "created_at": st.get("created_at"), "open": st.get("status") not in APPROVAL_FINAL,
           "summary": payload.get("summary") or {},
           "trace_url": approvals.trace_url(st.get("trace_id"), jaeger_url),
           "decide_with": ApprovalTools.decide}
    if st.get("comment"):                      # a previous "changes requested" is part of the triage
        out |= {"comment": st["comment"], "decided_by": st.get("decided_by"),
                "decided_via": st.get("decided_via")}
    return out


_NOT_ARTIFACTS = ("summary", "import_artifacts", "instructions",
                  "question", "answer_labels", "answer_required", "continuation")


def _detail(st: dict, jaeger_url: str, review_app: str) -> dict:
    """Everything a human needs to JUDGE one approval — the brief, the staged model BY REFERENCE, and
    the files the repository needs a human to import.

    `import_artifacts` + `instructions` are the repository's own, OPAQUE: each artifact is a
    {ref, label, note} the ADAPTER wrote, and this surface repeats them without interpreting them —
    a spreadsheet, a change-set, or nothing at all on a repository that writes over its own API. The
    normaliser (`lab.platform.contracts.import_artifacts`) also renders approvals staged before that
    shape existed, so an old request still lists every file a reviewer can take."""
    payload = st.get("payload") or {}
    return _brief(st, jaeger_url) | {
        "artifacts": {k: v for k, v in payload.items() if k not in _NOT_ARTIFACTS},
        "import_artifacts": [a.to_dict() for a in import_artifacts(payload)],
        "instructions": payload.get("instructions", ""),
        # A question comes back FLAT — a list of {label, samples, seconds, turns} — because the
        # intended long-term surface is an adaptive card templated by a low-code flow, not our own
        # renderer. A nested tree would be unusable there.
        "question": payload.get("question") or {},
        "answer_required": bool(payload.get("answer_labels")) and payload.get("answer_required", True),
        "trace_id": st.get("trace_id") or None, "decided_at": st.get("decided_at") or None,
        "review_app": review_app}


def register(server: LabServer) -> None:
    """The three approval tools on `server` (workflow-mcp). Redis comes from the server's container."""

    cfg = server.container.config                 # addresses from the container, not module globals

    def _client():
        return server.container.redis()

    def _state(request_id: str) -> dict:
        st = approvals.status(request_id, client=_client())
        if not st:
            raise ValueError(f"unknown request {request_id!r} — no such approval")
        span().set_attributes({"approval.request_id": request_id, "approval.kind": st.get("kind", ""),
                               "approval.status": st.get("status", "")})
        return st

    @server.tool(annotations=READ_ONLY)
    def approvals_list(
        kind: Annotated[str | None, Field(description="Only approvals of this kind — the kinds in "
                                                      f"use are {[k.value for k in ApprovalKind]}; "
                                                      "omit for all.")] = None,
        limit: Annotated[int, Field(ge=1, le=MAX_LIST, description="Most approvals to return "
                                                                   "(oldest first).")] = 50,
    ) -> dict:
        """Every approval still awaiting a human — what is blocked right now, oldest first. Each entry
        carries the request id, its kind and subject, who asked, when, the model summary (elements,
        relationships, views, violations, warnings, target domain), a link to the review app for the
        diagrams and a link to the trace of the run that produced it. A request whose reviewer asked
        for CHANGES stays open and carries their comment. Read-only: it decides nothing. Use
        approvals_get for the full detail of one, and approvals_decide to record a HUMAN's answer."""
        items = [_brief(s, cfg.jaeger_ui_url()) for s in approvals.pending(client=_client())]
        if kind:
            items = [i for i in items if i["kind"] == kind]
        span().set_attributes({"approvals.open": len(items)})
        return {"count": min(len(items), limit), "open_total": len(items),
                "approvals": items[:limit], "review_app": cfg.review_app_url()}

    @server.tool(annotations=READ_ONLY)
    def approvals_get(
        request_id: Annotated[str, Field(description="The approval id (`apr-…`), from approvals_list "
                                                     "or a run's `approval_id`.")],
    ) -> dict:
        """One approval in full, so a human can judge it: the summary counts, the current status and
        any reviewer comment, the trace of the run that produced it, the staged model as
        `art://<id>/<name>` references (`artifacts`: the views XML and its SVG previews), and
        `import_artifacts` — the files a human must import into the EA repository, each as
        {ref, label, note} written by the repository's own adapter, plus its `instructions`. Do not
        interpret those: show the label and the note, offer the ref. A repository that writes over its
        own API after the approval stages none. The references are handles, not content: open the
        review app link to see the diagrams. Read-only: it decides nothing."""
        return _detail(_state(request_id), cfg.jaeger_ui_url(), cfg.review_app_url())

    @server.tool()
    def approvals_ask(
        subject: Annotated[str, Field(description="What this question is about, in a few words — "
                                                  "a person sees it before they open anything, e.g. "
                                                  "the meeting's title.")],
        prompt: Annotated[str, Field(description="The question itself, in plain language, as the "
                                                 "person answering will read it.")],
        items: Annotated[list[dict], Field(description="One entry per thing that must be answered: "
                                                       "{label, samples, seconds, turns}. `label` is "
                                                       "the key the answer is given under and must be "
                                                       "unique; `samples` are verbatim quotes that "
                                                       "help a human recognise which is which.")],
        continuation: Annotated[dict | None, Field(description="What approving this should START, as "
                                                               "{process, inputs, answer_input, "
                                                               "requester}. Omit when approving "
                                                               "releases nothing.")] = None,
        artifacts: Annotated[dict | None, Field(description="`art://` references a reviewer may open "
                                                            "while deciding, as {name: ref}.")] = None,
        requester: Annotated[str, Field(description="Which process is asking.")] = "",
    ) -> dict:
        """Ask a HUMAN a question this run cannot answer itself, and finish.

        This is how a business process reaches the human-in-the-loop gate. It PUBLISHES the question
        to every approval channel and returns immediately, writing nothing else: runs take minutes,
        people take hours, so a run asks and ends rather than blocking. The answer arrives later,
        through whichever channel the person used, and what approving releases is carried by
        `continuation` — so the next step starts by itself.

        Ask about everything at once. One decision covering every item is far better than a person
        being asked the same kind of question repeatedly, and the completeness rule below enforces
        it: every label declared here must be answered before the approval can be approved.

        You may ASK. You may not ANSWER — `approvals_decide` requires a signed-in person and is a
        separate grant you do not hold. Never approve your own question; that defeats the entire
        control."""
        prompts = [SpeakerPrompt.from_dict(i) for i in (items or []) if isinstance(i, dict)]
        if not prompts:
            raise ValueError("ask about at least one thing — an empty question cannot be answered")
        labels = [p.label for p in prompts]
        if len(set(labels)) != len(labels):
            dupes = sorted({l for l in labels if labels.count(l) > 1})
            raise ValueError(f"duplicate labels {dupes} — the answer is keyed on the label, so each "
                             "must appear exactly once")
        payload = {"question": {"prompt": prompt, "items": [p.to_dict() for p in prompts],
                                "fields": ["identity", "tag"]},
                   # the completeness contract the gate will enforce, DECLARED by the asker — which
                   # is what keeps `check_answer` generic and the approval kind free of dispatch
                   "answer_labels": labels, "answer_required": True}
        if continuation:
            payload["continuation"] = Continuation.from_dict(continuation).to_dict()   # validated NOW
        payload |= dict(artifacts or {})          # refs a reviewer may open; no store is reached
        rid = approvals.request(kind=ApprovalKind.SPEAKER_MAPPING.value, subject=subject,
                                payload=payload, requester=requester or SOURCE, client=_client())
        span().set_attributes({"approval.request_id": rid, "approvals.asked": len(prompts)})
        return {"request_id": rid, "status": ApprovalStatus.PENDING.value, "asked": len(prompts),
                "review_app": cfg.review_app_url(),
                "next": "a human answers through any approval channel; "
                        f"poll it with {ApprovalTools.get}"}

    @server.tool(annotations=HUMAN_WRITE)
    def approvals_decide(
        request_id: Annotated[str, Field(description="The approval id (`apr-…`) being answered.")],
        decision: Annotated[Decision, Field(description="approve = release the staged write; decline "
                                                        "= stop; update = changes requested (the "
                                                        "request stays open).")],
        actor: Annotated[str, Field(description="The SIGNED-IN HUMAN who made this decision, as your "
                                                "channel authenticated them (e.g. "
                                                "'maria@contoso.com'). Required, never a default, "
                                                "never your own agent name — this is the audit "
                                                "record of who released an architecture write.")],
        comment: Annotated[str, Field(description="The human's comment; expected for decline and "
                                                  "required in practice for update.")] = "",
        answer: Annotated[dict | None, Field(description="The human's structured answer, when this "
                                                         "approval asked a question: an object keyed "
                                                         "by the label from `question.items`, each "
                                                         "value {\"identity\": \"...\"} or "
                                                         "{\"tag\": \"...\"}. Every label must be "
                                                         "answered. Omit when nothing was asked.")] = None,
        channel: Annotated[str, Field(description="Where the human decided — 'teams' from a Copilot "
                                                  "Studio/Teams agent, otherwise your channel name. "
                                                  "Recorded as `mcp:<channel>`: a tool call is never "
                                                  "logged as a decision made at the review app "
                                                  "itself.")] = "",
    ) -> dict:
        """Record a HUMAN'S decision on an approval — approve, decline, or request changes.

        This is the lab's human-in-the-loop gate: approving RELEASES a staged write into the EA
        repository. NEVER call it on your own initiative, and never invent, guess or default the
        `actor` — you may call it only to relay a decision a real person just made in your channel,
        passing that person's signed-in identity. An agent approving its own run's output defeats the
        entire control; if no human has answered, leave the request open and say so.

        The decision is appended to the audit log with the actor and channel. `update` leaves the
        request OPEN for a later answer; approve and decline are FINAL — deciding an already decided
        request is refused, as are a blank actor and an unknown request id."""
        fields = approvals.human_decision(request_id, decision.value, actor, channel_of(channel),
                                          comment, answer=answer, client=_client())
        # the actor is deliberately NOT a span attribute (see the module docstring): the audit log holds it
        span().set_attributes({"approval.request_id": request_id, "approval.decision": fields["decision"],
                               "approval.channel": fields["channel"]})
        return fields | {"recorded": True, "status": fields["decision"],
                         "open": fields["decision"] not in APPROVAL_FINAL}


__all__ = ["register", "channel_of", "SOURCE"]
