"""What a PERSON receives: the transcript, the minutes and the provider comparison, as plain text.

Plain text laid out the way Microsoft Teams lays out its own downloadable transcript — title, date,
duration, then one block per turn headed `Name   0:03` — because that is the transcript the people
receiving these already know how to read, and a format they have to learn is friction on every
meeting. Plain text also opens anywhere, quotes into a chat without markup, and diffs cleanly against
Teams' own, which the comparison exploits.

Pure: strings in, strings out. `read_transcript` is the inverse of `transcript`, so the comparison
can score a lane from the file a person was actually given rather than from a second copy that could
drift from it.
"""
from __future__ import annotations

import re
import textwrap
from datetime import datetime, timezone

from lab.core.meetings.naming import Turn

__all__ = ["clock", "length", "stamp", "transcript", "read_transcript", "minutes", "comparison"]

WIDTH = 100


def clock(seconds: float) -> str:
    """`0:03`, `12:40`, `1:02:03` — the offset Teams prints beside every turn."""
    s = int(max(0.0, seconds))
    h, m, sec = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def length(seconds: float) -> str:
    """`2m 8s`, `1h 3m 5s`, `45s` — the duration line under the title."""
    s = int(round(max(0.0, seconds)))
    h, m, sec = s // 3600, s % 3600 // 60, s % 60
    return " ".join(p for p in (f"{h}h" if h else "", f"{m}m" if m or h else "", f"{sec}s") if p)


def stamp(iso: str) -> str:
    """`29 September 2026, 07:20 UTC` from an ISO instant; empty when there is none to show.
    Labelled UTC rather than converted: a time shown without its zone is a time read wrongly."""
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return ""
    return f"{t.day} {t:%B %Y, %H:%M} UTC"


_HEADER = re.compile(r"^(?P<name>.+?) {3}(?P<clock>(?:\d+:)?\d+:\d{2})$")


def transcript(turns: list[Turn], *, title: str, when: str = "", seconds: float = 0.0,
               lane: str = "") -> str:
    """The Teams layout: header lines, a blank line, then `Name   m:ss` over each turn's words."""
    head = [title, stamp(when), length(seconds or max((t.start for t in turns), default=0.0))]
    if lane:
        head.append(f"Transcription: {lane}")
    blocks = [f"{t.name}   {clock(t.start)}\n{t.text}" for t in turns]
    return "\n".join(h for h in head if h) + "\n\n" + "\n\n".join(blocks) + "\n"


def read_transcript(text: str) -> list[Turn]:
    """The turns back out of `transcript()` — the inverse, so a lane is scored from what was delivered."""
    out: list[Turn] = []
    lines = (text or "").splitlines()
    i = 0
    while i < len(lines):
        m = _HEADER.match(lines[i])
        if m and i + 1 < len(lines):
            parts = [int(x) for x in m.group("clock").split(":")]
            start = sum(v * 60 ** k for k, v in enumerate(reversed(parts)))
            body = []
            i += 1
            while i < len(lines) and lines[i].strip() and not _HEADER.match(lines[i]):
                body.append(lines[i].strip())
                i += 1
            out.append(Turn(m.group("name"), float(start), " ".join(body)))
            continue
        i += 1
    return out


def _wrap(text: str, indent: str = "") -> str:
    return textwrap.fill(" ".join(str(text).split()), WIDTH, initial_indent=indent, subsequent_indent=indent)


def _names(value) -> str:
    return ", ".join(value) if isinstance(value, (list, tuple)) else str(value or "")


def minutes(named: dict, *, title: str, when: str = "", lane: str = "", people=()) -> str:
    """The NAMED minutes as a document a person reads top to bottom. Empty sections say so, because
    "no actions" is a finding and a missing heading reads like a missing page."""
    out = [f"{title} — Minutes", " · ".join(p for p in (stamp(when), f"Transcription: {lane}" if lane else "") if p)]
    if people:
        out += ["", f"Speakers: {', '.join(people)}"]
    out += ["", "SUMMARY", _wrap(named.get("summary") or "(none)")]

    out += ["", "DECISIONS"]
    for i, d in enumerate(named.get("decisions") or [], 1):
        out.append(_wrap(f"{i}. {d.get('statement', '')}"))
        detail = [f"Decided by: {_names(d.get('decided_by'))}" if d.get("decided_by") else "",
                  f"confidence: {d['confidence']}" if d.get("confidence") else ""]
        if any(detail):
            out.append("   " + " · ".join(x for x in detail if x))
    if not named.get("decisions"):
        out.append("None recorded.")

    out += ["", "ACTION ITEMS"]
    for i, a in enumerate(named.get("actions") or [], 1):
        out.append(_wrap(f"{i}. {a.get('commitment', '')}"))
        out.append("   " + " · ".join(x for x in (f"Owner: {a.get('owner', '')}",
                                                   f"Due: {a['due']}" if a.get("due") else "") if x))
    if not named.get("actions"):
        out.append("None recorded.")

    concepts = named.get("concepts") or []
    if concepts:
        out += ["", "KEY TOPICS"]
        for c in concepts:
            out.append(_wrap(f"- {c.get('label', '')}" + (f": {c['definition']}" if c.get("definition") else ""), ""))
    if named.get("keywords"):
        out += ["", "KEYWORDS", _wrap(", ".join(named["keywords"]))]
    return "\n".join(out) + "\n"


def _pct(v) -> str:
    return "—" if v is None else f"{round(v * 100)}%"


def comparison(title: str, reference, lanes: dict, *, when: str = "", reference_name: str = "Microsoft Teams") -> str:
    """Every lane's transcript against the tenant's own, as one table a person can read in a chat.

    `reference` and each lane are `lab.core.speech.compare.Score`s. Rows are in the order given."""
    head = ("", "Words", "vs Teams", "Teams words found", "Arabic script", "Speakers")
    rows = [(reference_name, str(reference.words), "100%", "—", _pct(reference.arabic_share), str(reference.speakers))]
    rows += [(lane, str(s.words), _pct(s.of_reference), _pct(s.reference_recall), _pct(s.arabic_share), str(s.speakers))
             for lane, s in lanes.items()]
    widths = [max(len(r[i]) for r in [head, *rows]) for i in range(len(head))]
    line = lambda r: "  ".join(c.ljust(w) if i == 0 else c.rjust(w) for i, (c, w) in enumerate(zip(r, widths)))  # noqa: E731
    out = [f"{title} — transcription compared with {reference_name}"]
    if stamp(when):
        out.append(stamp(when))
    out += ["", line(head), *(line(r) for r in rows), "",
            "How to read this",
            _wrap(f"- vs Teams: this transcript's word count as a share of the word count in {reference_name}.", ""),
            _wrap(f"- Teams words found: of the words {reference_name} wrote down, the share this transcript "
                  "also has. It is agreement, not accuracy: Teams drops speech it cannot handle — on 29 Sep "
                  "2026 it omitted an Arabic sentence entirely — so a transcript can find every Teams word "
                  "and still hold more than Teams did.", ""),
            _wrap("- Arabic script: the share of letters written in Arabic script. A verbatim lane should "
                  "carry the meeting's Arabic; an English rendering should be near 0%.", ""),
            _wrap(f"- Speakers: distinct people named in the transcript. {reference_name} attributes "
                  "everything said in a room to the device's owner.", ""),
            "",
            _wrap("Each lane rewrites this file as it finishes, so a lane still running is not yet listed.", "")]
    return "\n".join(out) + "\n"
