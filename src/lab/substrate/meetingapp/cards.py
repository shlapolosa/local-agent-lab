"""The Adaptive Cards the meeting app posts, as plain data — pure, so each is tested on its own.

ONE speaker card, two audiences. Everyone in the meeting chat sees `awaiting`; the organiser's client
REFRESHES it into `speaker_form`, because what a voice said is the organiser's to see before it is
anyone's. Two rules measured on 5 Oct 2026 shape every card here:

* `refresh.userIds` holds the TEAMS user id (`29:…`). An Entra object id there matches nobody, so the
  organiser silently gets the neutral card too.
* The refresh action carries the approval id and nothing else; who may see the form is decided by the
  bot on every refresh, never by data a client sends back.
"""
from __future__ import annotations

from typing import Iterable

from lab.platform.contracts import SpeakerPrompt

__all__ = ["welcome", "awaiting", "speaker_form", "recorded", "minutes"]

VERSION = "1.5"


def _card(body: list, **extra) -> dict:
    return {"type": "AdaptiveCard", "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": VERSION, "body": body} | extra


def _text(text: str, **kw) -> dict:
    return {"type": "TextBlock", "text": text, "wrap": True} | kw


def _refresh(approval_id: str, organiser_mri: str) -> dict:
    return {"action": {"type": "Action.Execute", "verb": "refresh", "data": {"approval_id": approval_id}},
            "userIds": [organiser_mri]}


def welcome() -> dict:
    return _card([
        _text("Meeting Notes is on for this meeting", weight="Bolder", size="Medium"),
        _text("After the meeting, its recording is transcribed — Arabic and English — and the minutes "
              "are posted here. Only meetings this app was added to are ever read."),
        _text("Press **Record** in the meeting (with transcription on) for it to work."),
        _text("The organiser is then asked to name each speaker. A voice is kept for recognising the "
              "speaker next time ONLY when its consent box is ticked.", isSubtle=True),
    ])


def awaiting(approval_id: str, organiser_mri: str, *, speakers: int, lane: str = "") -> dict:
    """What everyone sees: a count and who it is waiting for — never a word anybody said."""
    lane_note = f" · {lane}" if lane else ""
    return _card([_text(f"Transcript ready{lane_note}", weight="Bolder"),
                  _text(f"{speakers} speaker(s) heard. Waiting for the organiser to name them.")],
                 refresh=_refresh(approval_id, organiser_mri))


def _row(p: SpeakerPrompt) -> list[dict]:
    said = " · ".join(f"“{s}”" for s in p.samples) or "(no words were captured)"
    suggestion = p.suggestion or {}
    identity = {"type": "Input.Text", "id": f"identity_{p.label}", "label": "Directory identity",
                "placeholder": "name@organisation.com"}
    tag = {"type": "Input.Text", "id": f"tag_{p.label}", "label": "…or a name (not in the directory)"}
    if suggestion.get("identity"):
        identity["value"] = suggestion["identity"]
    elif suggestion.get("tag"):
        tag["value"] = suggestion["tag"]
    rows = [_text(f"**{p.label}** — {round(p.seconds)} s, {p.turns} turn(s)", separator=True),
            _text(said, isSubtle=True)]
    if suggestion.get("display") or suggestion.get("identity") or suggestion.get("tag"):
        who = suggestion.get("display") or suggestion.get("identity") or suggestion.get("tag")
        rows.append(_text(f"Sounds like **{who}** — check before submitting.", color="Accent"))
    # Never pre-ticked, even for a recognised voice: consent is the person's to give each time it is asked.
    consent = {"type": "Input.Toggle", "id": f"consent_{p.label}", "valueOn": "yes", "valueOff": "no",
               "title": "They consent to their voice being kept for recognition"}
    return rows + [identity, tag, consent]


def speaker_form(approval_id: str, prompts: Iterable[SpeakerPrompt], organiser_mri: str, *,
                 note: str = "") -> dict:
    body = [_text("Who is speaking?", weight="Bolder", size="Medium"),
            _text("Name each voice — a directory identity, or a name for anyone outside it.")]
    if note:
        body.append(_text(note, color="Attention", weight="Bolder"))
    for p in prompts:
        body += _row(p)
    return _card(body, refresh=_refresh(approval_id, organiser_mri),
                 actions=[{"type": "Action.Execute", "verb": "submit", "title": "Submit",
                           "data": {"approval_id": approval_id}}])


def recorded(actor_display: str) -> dict:
    """After the answer: for everyone, with no refresh — the question is closed."""
    return _card([_text("Speakers named", weight="Bolder"),
                  _text(f"Answered by {actor_display}. The minutes will be posted here.")])


def minutes(*, summary: str, decisions: int, actions: int, files: list[str], lane: str = "") -> dict:
    lane_note = f" · {lane}" if lane else ""
    body = [_text(f"Minutes{lane_note}", weight="Bolder", size="Medium"),
            _text(summary or "(no summary)"),
            {"type": "FactSet", "facts": [{"title": "Decisions", "value": str(decisions)},
                                         {"title": "Actions", "value": str(actions)}]}]
    if files:
        body.append(_text("Files: " + ", ".join(files), isSubtle=True))
    return _card(body)
