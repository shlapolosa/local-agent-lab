"""One approval as an Adaptive Card — pure, payload-driven, and shared by every surface that shows one.

WHY ITS OWN MODULE. The card used to live inside the Teams channel, so the only way to show an
approval as a card was to BE the Teams channel. TO-BE (24 Oct 2026) puts presentation outside the
seam: a Power Automate flow that posts a card and waits for the answer, a Power Apps page, a Teams
tab. They all need the same card, and they reach it through `GET /api/approvals/{id}/card` — so the
rendering moved here, below the seam, and the Teams channel became one more caller of it.

An Adaptive Card because that is what the low-code side consumes natively ("post adaptive card and
wait for a response"), and what Teams renders. The format is Microsoft's; nothing in it names a
vendor's product, and a surface that wants something else renders the approval's own JSON instead.

PAYLOAD-DRIVEN, never kind-driven: an approval carrying a `question` renders as one, an approval
carrying a `summary` as one. A new kind of question reaches every surface without editing any.
"""
from __future__ import annotations

import json
from typing import Any

from lab.platform import contracts
from lab.substrate.approvals import trace_url

__all__ = ["card", "CARD_SCHEMA", "CARD_VERSION", "MAX_SAMPLE"]

MAX_SAMPLE = 160        # a sample is evidence for recognition, not a transcript excerpt
CARD_SCHEMA = "http://adaptivecards.io/schemas/adaptive-card.json"
CARD_VERSION = "1.4"                    # Teams renders up to 1.5; 1.4 is the safe floor everywhere
SUMMARY_FACTS = (("Elements", "elements"), ("Relationships", "relations"), ("Views", "views"),
                 ("Violations", "violations"), ("Warnings", "warnings"))


def _payload(state: dict) -> dict:
    """A stream event carries the payload as JSON text, a status read as a dict — accept both."""
    raw = state.get("payload") or {}
    return (json.loads(raw) if isinstance(raw, str) else dict(raw)) or {}


def card(state: dict, *, review_url: str, jaeger_url: str = "", answers: bool = False) -> dict:
    """The Adaptive Card for one approval. `answers` puts inputs + a Submit on it — only for a surface
    that can RECEIVE the response (a flow that waits); a button that silently does nothing is worse
    than none, which is why it is off by default."""
    payload = _payload(state)
    question = payload.get("question") or {}
    rid = str(state.get("request_id") or "")
    body = [{"type": "TextBlock", "text": f'Approval needed: {state.get("kind", "")}',
             "weight": "Bolder", "size": "Large", "wrap": True},
            {"type": "TextBlock", "text": state.get("subject", ""), "spacing": "None",
             "isSubtle": True, "wrap": True}]
    body += _question_blocks(question, answers) if question else _summary_blocks(state, payload)
    inputs, submit = _answer_inputs(question, rid) if answers and question else ([], [])
    # The deep link carries the request id, and the label says what the reviewer is being asked to
    # do — answering a question and releasing a staged write are different acts.
    actions: list[dict[str, Any]] = [{"type": "Action.OpenUrl",
                                      "title": "Answer in the review app" if question else "Review & decide",
                                      "url": f'{review_url.rstrip("/")}?approval={rid}'}]
    trace = trace_url(state.get("trace_id"), jaeger_url)   # one link construction
    if trace:
        actions.append({"type": "Action.OpenUrl", "title": "Open trace", "url": trace})
    return {"$schema": CARD_SCHEMA, "type": "AdaptiveCard", "version": CARD_VERSION,
            "body": body + inputs, "actions": submit + actions}


def _answer_inputs(question, request_id: str = "") -> tuple[list, list]:
    """Controls that let a person answer ON the card, and the Submit that sends them.

    One control per label, keyed EXACTLY as `check_answer` keys the answer, so what the flow posts is
    what the gate already accepts — no mapping, and nothing to drift. Three choices, not two: a
    steward most often settles a term by making it another name for a concept already held, so
    `existing` rides beside a text box for the id."""
    controls, labels = [], []
    for item in question.get("items") or []:
        label = str(item.get("label") or "")
        if not label:
            continue
        labels.append(label)
        shown = str((item.get("samples") or [label])[0])[:MAX_SAMPLE]
        controls += [
            {"type": "TextBlock", "text": shown, "wrap": True, "weight": "Bolder", "spacing": "Medium"},
            {"type": "Input.ChoiceSet", "id": label, "style": "compact", "value": "decline",
             "choices": [{"title": "Admit it", "value": "admit"},
                         {"title": "It already exists", "value": "existing"},
                         {"title": "Decline", "value": "decline"}]},
            {"type": "Input.Text", "id": f"{label}::id", "spacing": "None",
             "placeholder": "if it already exists, the concept id it means"},
        ]
    if not labels:
        return [], []
    # The approval id rides the SUBMIT, so `POST /api/approvals/{request_id}/decide` is addressable
    # from the answer alone — a flow correlating a response back to a card could lose one.
    return controls, [{"type": "Action.Submit", "title": "Record my answers",
                       "data": {"labels": labels, "request_id": request_id}}]


def _question_blocks(question, answers: bool) -> list:
    """One row per thing a human must identify: how long each spoke, how often, and a line they said."""
    blocks = [{"type": "TextBlock", "text": question.get("prompt", ""), "wrap": True}]
    # A question that is not about voices (one `value` per label) has no timings worth a fact; its
    # samples ARE the choices, so they take the fact's place.
    voices = contracts.answer_fields({"question": question}) != ("value",)
    for item in question.get("items") or []:
        samples = [str(s)[:MAX_SAMPLE] for s in (item.get("samples") or [])]
        said = " · ".join(samples[:2] if voices else samples)
        fact = (f'{round(float(item.get("seconds") or 0))}s · {item.get("turns", 0)} turns'
                if voices else said or "—")
        blocks.append({"type": "Container", "separator": True, "items": [
            {"type": "FactSet", "facts": [{"title": item.get("label", "?"), "value": fact}]},
            *([{"type": "TextBlock", "text": said, "wrap": True, "isSubtle": True,
                "spacing": "None"}] if said and voices else []),
        ]})
    if not answers:
        blocks.append({"type": "TextBlock", "isSubtle": True, "wrap": True,
                       "text": "Answer in the review app, or through a flow that posts this card and "
                               "waits for a response — a webhook card cannot send an answer back."})
    return blocks


def _summary_blocks(state, payload) -> list:
    """The staged-model summary: ONLY what the payload carries — a `?` reads as missing data where the
    truth is not applicable — with violations called out in red."""
    s = payload.get("summary") or {}
    facts = [{"title": "Request", "value": str(state.get("request_id", ""))}]
    if state.get("requester"):
        facts.append({"title": "Requester", "value": str(state["requester"])})
    if s.get("domain"):
        facts.append({"title": "Domain", "value": str(s["domain"])})
    facts += [{"title": t, "value": str(s[k])} for t, k in SUMMARY_FACTS if s.get(k) is not None]
    out: list[dict[str, Any]] = [{"type": "FactSet", "facts": facts}]
    if s.get("violations"):
        out.append({"type": "TextBlock", "color": "Attention", "weight": "Bolder", "wrap": True,
                    "text": f'{s["violations"]} validation violation(s) — review before approving.'})
    if s.get("views"):
        out.append({"type": "TextBlock", "isSubtle": True, "wrap": True,
                    "text": "Diagrams are not shown here — open the review app for the views and "
                            "to decide."})
    return out
