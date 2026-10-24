"""One approval as a surface reads it — ONE projection for the MCP tools and the REST door.

`approvals_get` (MCP, for an agent or a Copilot Studio connector) and `GET /api/approvals/{id}` (REST,
for a flow, a Power Apps page or the review app) describe the same approval to the same kind of reader.
They used to carry two projections that had already drifted — one honoured `answer_required`, the other
ignored it; one listed every staged reference, the other only bare strings — so a reader's answer
depended on which door it used. Both now call this module, beside `approval_card` (the same approval
as an Adaptive Card).

The full `payload` is part of the detail because the contract helpers every renderer uses
(`import_artifacts`, `speaker_prompts`, `continuation_of`) interpret a payload, not a projection of
one. What it carries: references, counts, the question and its samples, and the continuation's inputs
(opaque provider ids, never a credential or a document's content). A READ role is the power to judge
an approval, and judging needs exactly that.
"""
from __future__ import annotations

from lab.platform.contracts import (APPROVAL_FINAL, import_artifacts, speaker_candidates,
                                    speaker_prompts)
from lab.substrate.approvals import trace_url

__all__ = ["brief", "detail", "NOT_ARTIFACTS"]

#: Payload keys that describe the question or the run, not a staged artifact.
NOT_ARTIFACTS = ("summary", "import_artifacts", "instructions", "question", "answer_labels",
                 "answer_required", "continuation", "context")

_BRIEF = ("request_id", "kind", "subject", "requester", "status", "created_at", "trace_id",
          # what an approval RELEASED, or why it could not
          "released_request_id", "released_process", "continuation_error")


def brief(state: dict, *, jaeger_url: str = "", **extra) -> dict:
    """What a reader needs to TRIAGE one approval: who wants what, how big, where to look. Keys a state
    does not carry are left out rather than sent empty. `extra` is a door's own addition (a tool name
    to decide with, a review-app link)."""
    payload = state.get("payload") or {}
    out = {k: state[k] for k in _BRIEF if state.get(k)}
    out |= {"open": state.get("status") not in APPROVAL_FINAL, "summary": payload.get("summary") or {},
            "trace_url": trace_url(state.get("trace_id"), jaeger_url)}
    if state.get("comment"):            # a previous "changes requested" is part of the triage
        out |= {"comment": state["comment"], "decided_by": state.get("decided_by"),
                "decided_via": state.get("decided_via")}
    return out | extra


def detail(state: dict, *, jaeger_url: str = "", **extra) -> dict:
    """Everything a human needs to JUDGE one approval: the brief, the staged artifacts BY REFERENCE, the
    repository's own import files and instructions (opaque — repeated, never interpreted), and the
    question FLAT, because the intended long-term renderer is a low-code card template."""
    payload = state.get("payload") or {}
    return brief(state, jaeger_url=jaeger_url, **extra) | {
        "artifacts": {k: v for k, v in payload.items() if k not in NOT_ARTIFACTS},
        "import_artifacts": [a.to_dict() for a in import_artifacts(payload)],
        "instructions": payload.get("instructions", ""),
        "question": payload.get("question") or {},
        "speakers": [p.to_dict() for p in speaker_prompts(payload)],
        # who may be PICKED instead of typed — a suggestion: a client must still offer free text
        "candidates": [c.to_dict() for c in speaker_candidates(payload)],
        "answer_labels": list(payload.get("answer_labels") or []),
        "answer_required": bool(payload.get("answer_labels")) and payload.get("answer_required", True),
        "decided_at": state.get("decided_at") or None,
        "payload": payload,
    }
