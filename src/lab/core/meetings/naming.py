"""The rendering a PERSON receives: the same minutes and transcript, with speakers NAMED.

An anonymous label is a model-internal key and nothing else. Three separate things depend on it and
all three are right: the minutes schema tells the model "Labels only; who they are is the human's
answer, not yours", `gate` validates what the model wrote against exactly those labels, and the prose
the model reads therefore has to show them (a name-only prose once failed every run with "'motamad'
is not a speaker in this transcript" — it demanded a vocabulary the model was never given).

What was missing is the other end. Measured live 9 Sep 2026, after a human had tagged every speaker:
the file delivered into the meeting's own folder read `SPEAKER_01 (socrateshlapolosa): …` and the
summary read "speaker_0 opened the meeting". The tagging worked and the naming never happened, so
the one thing a person is asked for — who is speaking — bought them nothing.

So the label is translated AT THE EDGE, here, on the way out. Everything upstream keeps its labels:
they are what the gate validated, what the graph is keyed on, and what an auditor needs to trace a
sentence back to a diarizer's decision. This module builds the SECOND rendering, and never touches
the first.

Pure: dicts and dataclasses in, dicts and strings out. No I/O, no gateway, no store.
"""
from __future__ import annotations

import copy
import re

from lab.core.meetings.model import Speakers

__all__ = ["transcript_for_people", "named_minutes"]

#: Where the model is told to write a speaker label. Read from the schema's own descriptions rather
#: than guessed: `decisions[].decided_by` (a list), `actions[].owner`, `evidence[].speaker`.
_ONE = ("owner", "speaker")
_MANY = ("decided_by",)


def _name_of(speakers: Speakers) -> dict[str, str]:
    return {e.label: e.display for e in speakers.entries}


def transcript_for_people(segments, speakers: Speakers) -> str:
    """The transcript as a conversation between PEOPLE — one paragraph per turn, no labels.

    Consecutive segments by the same person are joined, because a diarizer breaks a turn wherever it
    hears a pause: those breaks are an artefact of the analysis, not of the conversation, and keeping
    them gives a reader one sentence chopped into pieces under a repeated name. It also merges the
    case that made this visible — two labels a human identified as the SAME person, which otherwise
    reads as a dialogue that never took place.

    Silent segments are dropped: a diarizer attributes breaths and keyboards, and a segment with no
    words is not a turn (`Transcript.spoken` states the same rule for the domain's own model).
    """
    names = _name_of(speakers)
    turns: list[list[str]] = []
    who: list[str] = []
    for s in segments or ():
        text = str(s.get("text") or "").strip()
        if not text:
            continue
        label = str(s.get("speaker") or "")
        name = names.get(label, label)
        if who and who[-1] == name:
            turns[-1].append(text)
        else:
            who.append(name)
            turns.append([text])
    return "\n".join(f"{name}: {' '.join(parts)}" for name, parts in zip(who, turns))


def named_minutes(minutes, speakers: Speakers) -> dict:
    """The minutes with every speaker label replaced by the person a human identified.

    A DEEP COPY, always: the labelled minutes are the audit artifact and the key the semantic model
    is built on, so this must not rewrite them under their own readers.

    Labels are substituted longest-first. `speaker_0` is a prefix of `speaker_01`, so replacing in
    declaration order turns the latter into "<name of speaker_0>1" — a silent corruption that names
    the wrong person, which is worse than leaving the label. A label nobody identified is left
    exactly as it is: `gate` already refuses minutes that name one, and if that guard is ever wrong,
    a reader is better served by one un-named label than by no minutes at all.
    """
    out = copy.deepcopy(minutes) if isinstance(minutes, dict) else {}
    names = _name_of(speakers)
    if not names:
        return out

    def one(value):
        return names.get(str(value), value)

    def many(values):
        seen, kept = set(), []
        for v in values or ():                # a person named twice reads as two people agreeing
            name = one(v)
            if name not in seen:
                seen.add(name)
                kept.append(name)
        return kept

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for key, value in node.items():
                if key in _ONE and isinstance(value, str):
                    node[key] = one(value)
                elif key in _MANY and isinstance(value, list):
                    node[key] = many(value)
                else:
                    walk(value)

    walk(out)
    # ...and the free text, which is the part anybody actually reads
    if isinstance(out.get("summary"), str) and out["summary"]:
        pattern = re.compile("|".join(re.escape(l) for l in sorted(names, key=len, reverse=True)))
        out["summary"] = pattern.sub(lambda m: names[m.group(0)], out["summary"])
    return out
