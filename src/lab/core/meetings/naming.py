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

import re

from lab.core.meetings.model import Speakers

__all__ = ["transcript_for_people", "named_minutes"]

#: The one field whose value is a LIST of speakers (`decisions[].decided_by`). It is named not to
#: decide where substitution happens — that is everywhere — but because a list of people needs
#: de-duplicating once two labels turn out to be one person.
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

    EVERYWHERE, not in the fields the schema names. The schema puts a label in three places
    (`decisions[].decided_by`, `actions[].owner`, `evidence[].speaker`) and substituting only those
    plus the summary was measured live 9 Sep 2026 to leave this behind, in a field nobody had thought
    of: `concepts[].definition` — "The outstanding items being tracked from previous work; speaker_0
    recalled only two remained". Two of three lanes leaked it. The model writes prose wherever the
    schema allows prose, and it refers to speakers there by the only name it was given, so the rule
    has to be about the LABEL rather than about the field it sits in.

    Substituting every string also subsumes the structured fields: a value that IS a label is
    replaced whole, and a sentence that merely mentions one is rewritten in place, by one rule.

    Longest-first: `speaker_0` is a prefix of `speaker_01`, so replacing in declaration order turns
    the latter into "<name of speaker_0>1" — a silent corruption that names the WRONG person, which
    is worse than leaving the label. A label nobody identified is left exactly as it is: `gate`
    already refuses minutes that name one, and if that guard is ever wrong, a reader is better served
    by one un-named label than by no minutes at all.

    Returns a NEW structure throughout: the labelled minutes are the audit artifact and the key the
    semantic model is built on, so this must never rewrite them under their own readers.
    """
    if not isinstance(minutes, dict):
        return {}
    names = _name_of(speakers)
    if not names:
        return {k: v for k, v in minutes.items()}
    pattern = re.compile("|".join(re.escape(l) for l in sorted(names, key=len, reverse=True)))

    def rewrite(node):
        if isinstance(node, str):
            return pattern.sub(lambda m: names[m.group(0)], node)
        if isinstance(node, list):
            return [rewrite(x) for x in node]
        if isinstance(node, dict):
            out = {}
            for key, value in node.items():
                named = rewrite(value)
                if key in _MANY and isinstance(named, list):
                    # a person named twice reads as two people agreeing with each other
                    named = list(dict.fromkeys(named))
                out[key] = named
            return out
        return node

    return rewrite(minutes)
