"""The MAPPER: gated minutes -> a `meeting-1.0` model spec. Pure, no I/O, tested on its own.

The agent emits minutes in business language and this turns them into the graph. Keeping the two
apart is what stops the model minting its own ids (they are functions of content), naming vocabulary
types (filing an item under decisions IS the type assignment) or seeing a directory address.

Two properties are load-bearing:

  * **Concepts and people carry GLOBAL iris; decisions and actions are scoped to their meeting.**
    The same concept in two meetings is one node — that is the join the whole model rests on — while
    the same sentence said in two meetings is two commitments.
  * **No address reaches the graph.** A person node carries a display label and the KIND of id, and
    the identity itself is only ever hash input. The transcript keeps the addresses; the graph does
    not, because a queryable graph is the wrong place for text nobody can redact later.
"""
from __future__ import annotations

from typing import Any

from lab.core.meetings import ids
from lab.core.meetings.model import Speakers

__all__ = ["minutes_to_spec", "MinutesError"]


class MinutesError(ValueError):
    """The minutes cannot be mapped — the gate should have caught it; say what and where."""


def _person(entry) -> dict[str, Any]:
    """One thin Person element. Label and id KIND only — never the address itself."""
    return {"id": entry.label, "type": "Person", "name": entry.display,
            "iri": ids.person_iri(identity=entry.identity, tag=entry.tag),
            "props": {"idKind": "upn" if entry.identity else "tag",
                      "external": "true" if entry.tag else "false"}}


def _evidence(item: dict) -> dict[str, str]:
    """Transcript OFFSETS, never a quote. Kept as props so a reader can find the moment without the
    graph holding a word of what was said."""
    ev = (item.get("evidence") or [{}])[0]
    out = {}
    if ev.get("speaker"):
        out["evidenceSpeaker"] = str(ev["speaker"])
    for k in ("start", "end"):
        if ev.get(k) is not None:
            out[f"evidence{k.title()}"] = str(ev[k])
    return out


def minutes_to_spec(minutes: dict, meeting: dict, speaker_map: Speakers) -> dict:
    """Gated minutes + this meeting's metadata + the human's answer -> a `meeting-1.0` spec."""
    meeting_id = str(meeting.get("id") or meeting.get("meeting_id") or "")
    if not meeting_id:
        raise MinutesError("the meeting needs an id — it is the scope of every decision and action")

    elements: list[dict] = [{
        "id": "meeting", "type": "Meeting", "name": meeting.get("subject") or meeting_id,
        "iri": ids.meeting_iri(meeting_id),
        "props": {k: str(v) for k, v in (("date", meeting.get("date")),
                                         ("transcript", meeting.get("transcript_ref"))) if v},
    }]
    relations: list[dict] = []

    for entry in speaker_map.entries:
        elements.append(_person(entry))
        relations.append({"src": entry.label, "tgt": "meeting", "type": "Attended"})

    concept_of: dict[str, str] = {}
    for c in minutes.get("concepts") or []:
        elements.append({"id": c["id"], "type": "Concept", "name": c["label"],
                         "iri": ids.concept_iri(c["label"]),
                         **({"doc": c["definition"]} if c.get("definition") else {}),
                         "props": _evidence(c)})
        relations.append({"src": c["id"], "tgt": "meeting", "type": "RaisedIn"})
        concept_of[c["id"]] = c["id"]

    def _concerns(item, local_id):
        for cid in item.get("concerns") or []:
            if cid not in concept_of:
                raise MinutesError(f"{local_id} concerns {cid!r}, which is not a concept in these minutes")
            relations.append({"src": local_id, "tgt": cid, "type": "Concerns"})

    decisions = {d["id"] for d in (minutes.get("decisions") or [])}
    for d in minutes.get("decisions") or []:
        elements.append({"id": d["id"], "type": "Decision", "name": d["statement"],
                         "iri": ids.decision_iri(meeting_id, d["statement"]),
                         **({"doc": d["rationale"]} if d.get("rationale") else {}),
                         "props": {**_evidence(d),
                                   **({"confidence": d["confidence"]} if d.get("confidence") else {})}})
        relations.append({"src": d["id"], "tgt": "meeting", "type": "RaisedIn"})
        _concerns(d, d["id"])
        for label in d.get("decided_by") or []:
            speaker_map.of(label)            # an unmapped speaker fails HERE, naming the label
            relations.append({"src": d["id"], "tgt": label, "type": "DecidedBy"})
        if d.get("resolves"):
            if d["resolves"] not in decisions:
                raise MinutesError(f'{d["id"]} resolves {d["resolves"]!r}, which is not a decision here')
            relations.append({"src": d["id"], "tgt": d["resolves"], "type": "Resolves"})

    for a in minutes.get("actions") or []:
        speaker_map.of(a["owner"])           # every action has an owner, and the owner must be real
        elements.append({"id": a["id"], "type": "ActionItem", "name": a["commitment"],
                         "iri": ids.action_iri(meeting_id, a["commitment"], a["owner"]),
                         "props": {**_evidence(a),
                                   **({"due": a["due"]} if a.get("due") else {}),
                                   **({"confidence": a["confidence"]} if a.get("confidence") else {}),
                                   "status": "open"}})
        relations.append({"src": a["id"], "tgt": "meeting", "type": "RaisedIn"})
        relations.append({"src": a["id"], "tgt": a["owner"], "type": "OwnedBy"})
        _concerns(a, a["id"])
        if a.get("implements"):
            if a["implements"] not in decisions:
                raise MinutesError(f'{a["id"]} implements {a["implements"]!r}, which is not a decision here')
            relations.append({"src": a["id"], "tgt": a["implements"], "type": "Implements"})

    return {"name": meeting.get("subject") or meeting_id, "elements": elements,
            "relations": relations}
