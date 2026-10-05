"""What the bot does with what Teams sends it — framework-free, so it is tested without Teams.

`service.py` adapts the Teams SDK to these functions; everything that DECIDES lives here. The decision
that matters most is in `on_card`: the speaker form (what each voice SAID) is shown, and an answer is
recorded, only for the meeting's ORGANISER. That is decided on every refresh and every submit from the
registry — who the bot learned was the organiser when it was added — and never from data the client
sends back, which a client controls.

Activities are dicts in the shape the SDK dumps them (`by_alias`): `from.aadObjectId`,
`conversation.id`, `value.action.{verb,data}`. An Action.Execute's data arrives with the card's input
values merged in, which is how the answer reaches `answers.from_card`."""
from __future__ import annotations

import re
from typing import Callable

from lab.platform.contracts import APPROVAL_FINAL, ApprovalKind, continuation_of, speaker_prompts
from lab.substrate import approvals
from lab.substrate.meetingapp import answers, cards, registry
from lab.substrate.meetingapp.registry import Meeting

__all__ = ["CHANNEL", "on_card", "on_install", "on_command", "actor_of", "question_meeting"]

#: How a decision made here is recorded in the audit log — distinct from the review app and the
#: Power Automate card, so "where was this answered" is always answerable.
CHANNEL = "teams-app"


def _chat(activity: dict) -> str:
    return str((activity.get("conversation") or {}).get("id") or "")


def _who(activity: dict) -> str:
    return str((activity.get("from") or {}).get("aadObjectId") or "")


def _lane(payload: dict) -> str:
    cont = continuation_of(payload or {})
    return str(cont.inputs.get("provider") or "") if cont else ""


def question_meeting(st: dict, *, client=None) -> Meeting | None:
    """The registered meeting an approval is a speaker question ABOUT, or None. A question for this
    app is a speaker question whose run names a chat AND whose recording is that chat's meeting
    (`registry.owner_of`). Anything else — another kind of approval, another meeting — is not this
    channel's to show or to decide, whatever id a client sends."""
    if st.get("kind") != ApprovalKind.SPEAKER_MAPPING.value:
        return None
    cont = continuation_of(st.get("payload") or {})
    inputs = cont.inputs if cont else {}
    return registry.owner_of(str(inputs.get("chat_id") or ""), str(inputs.get("recording") or ""), client=client)


def actor_of(member: dict, fallback: str) -> str:
    """Who answered, as the audit log should name them: the directory name Teams reports, else the
    mail address, else the object id — never blank, because `human_decision` refuses an anonymous one."""
    return str(member.get("userPrincipalName") or member.get("email") or fallback or "")


def on_card(activity: dict, *, actor: str, status: Callable = approvals.status,
            decide: Callable = approvals.human_decision, client=None) -> tuple[dict, bool]:
    """The card to show THIS user after an Action.Execute (refresh or submit), and whether the
    question is now CLOSED — in which case the posted card is replaced for everyone, not only here."""
    action = (activity.get("value") or {}).get("action") or {}
    data = action.get("data") or {}
    approval_id = str(data.get("approval_id") or "")
    st = status(approval_id, client=client) or {}
    meeting = question_meeting(st, client=client) if st else None
    if meeting is None or meeting.chat_id != _chat(activity):
        return cards.not_here(), False
    if st.get("status") in APPROVAL_FINAL:
        return cards.recorded(st.get("decided_by") or "someone"), True
    payload = st.get("payload") or {}
    prompts = speaker_prompts(payload)
    if _who(activity) != meeting.organiser_oid:
        return cards.awaiting(approval_id, meeting.organiser_mri, speakers=len(prompts), lane=_lane(payload)), False
    if action.get("verb") != "submit":
        return cards.speaker_form(approval_id, prompts, meeting.organiser_mri), False
    answer = answers.from_card(data, [p.label for p in prompts])
    missing = answers.unanswered(answer)
    if missing:
        return cards.speaker_form(approval_id, prompts, meeting.organiser_mri,
                                  note=f"Name every speaker before submitting — still unnamed: {', '.join(missing)}"), False
    try:
        decide(approval_id, "approve", actor, CHANNEL, answer=answer, client=client)
    except (ValueError, KeyError):
        # answered meanwhile through another surface: show who did, rather than failing the click
        st = status(approval_id, client=client) or {}
        return cards.recorded(st.get("decided_by") or "someone else"), True
    return cards.recorded(str((activity.get("from") or {}).get("name") or actor)), True


def on_install(activity: dict, meeting_info: dict | None, *, client=None) -> dict | None:
    """Register a meeting the app was just added to, and say what it will do. Outside a meeting (a
    personal or group chat) there is nothing to register — the app processes meetings only."""
    channel = activity.get("channelData") or {}
    details = (meeting_info or {}).get("details") or {}
    organiser = (meeting_info or {}).get("organizer") or {}
    if not channel.get("meeting") or not details.get("msGraphResourceId") or not organiser.get("aadObjectId"):
        return None
    registry.save(Meeting(chat_id=_chat(activity), organiser_oid=organiser["aadObjectId"],
                          organiser_mri=str(organiser.get("id") or ""),
                          graph_meeting_id=details["msGraphResourceId"],
                          service_url=str(activity.get("serviceUrl") or ""),
                          tenant_id=str((channel.get("tenant") or {}).get("id")
                                        or (activity.get("conversation") or {}).get("tenantId") or "")),
                  client=client)
    return cards.welcome()


def _command(text: str) -> str:
    """The FIRST word said to the bot. A sentence that merely contains a command word ("status — don't
    pause yet") must not act on it."""
    words = re.sub(r"<at>.*?</at>", " ", str(text or ""), flags=re.S).strip().lower().split()
    return words[0].strip(".,!?:;") if words else ""


def on_command(activity: dict, *, client=None) -> str | None:
    """`pause`, `resume`, `status` — said to the bot with an @mention in the meeting chat."""
    word = _command(activity.get("text"))
    meeting = registry.by_chat(_chat(activity), client=client)
    if meeting is None:
        return "This chat is not a meeting I was added to."
    for command, paused in (("pause", True), ("resume", False)):
        if word == command:
            if _who(activity) != meeting.organiser_oid:
                return f"Only the meeting organiser can {command} processing."
            registry.set_paused(meeting.chat_id, paused, client=client)
            return ("Paused: recordings of this meeting will not be processed." if paused
                    else "Resumed: the next recording will be processed after the meeting.")
    if word == "status":
        return ("Processing is PAUSED for this meeting." if meeting.paused
                else "On: the recording is processed after the meeting ends.")
    return "Say `status`, or — as the organiser — `pause` or `resume`."
