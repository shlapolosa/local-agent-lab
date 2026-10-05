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

from typing import Callable

from lab.platform.contracts import APPROVAL_FINAL, continuation_of, speaker_prompts
from lab.substrate import approvals
from lab.substrate.meetingapp import answers, cards, registry
from lab.substrate.meetingapp.registry import Meeting

__all__ = ["CHANNEL", "on_card", "on_install", "on_command"]

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


def on_card(activity: dict, *, actor: str, status: Callable = approvals.status,
            decide: Callable = approvals.human_decision, client=None) -> dict:
    """The card to show THIS user after an Action.Execute (refresh or submit)."""
    action = (activity.get("value") or {}).get("action") or {}
    data = action.get("data") or {}
    approval_id = str(data.get("approval_id") or "")
    st = status(approval_id, client=client) or {}
    if not st:
        return cards.recorded("nobody — this question no longer exists")
    if st.get("status") in APPROVAL_FINAL:
        return cards.recorded(st.get("decided_by") or "someone")
    payload = st.get("payload") or {}
    prompts = speaker_prompts(payload)
    meeting = registry.by_chat(_chat(activity), client=client)
    if meeting is None or _who(activity) != meeting.organiser_oid:
        # The organiser's id may be unknown (a meeting the bot never registered): then nobody sees it.
        return cards.awaiting(approval_id, meeting.organiser_mri if meeting else "",
                              speakers=len(prompts), lane=_lane(payload))
    if action.get("verb") != "submit":
        return cards.speaker_form(approval_id, prompts, meeting.organiser_mri)
    answer = answers.from_card(data, [p.label for p in prompts])
    missing = answers.unanswered(answer)
    if missing:
        return cards.speaker_form(approval_id, prompts, meeting.organiser_mri,
                                  note=f"Name every speaker before submitting — still unnamed: {', '.join(missing)}")
    decide(approval_id, "approve", actor, CHANNEL, answer=answer, client=client)
    return cards.recorded(str((activity.get("from") or {}).get("name") or actor))


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


def on_command(activity: dict, *, client=None) -> str | None:
    """`pause`, `resume`, `status` — said to the bot with an @mention in the meeting chat."""
    text = str(activity.get("text") or "").lower()
    meeting = registry.by_chat(_chat(activity), client=client)
    if meeting is None:
        return "This chat is not a meeting I was added to."
    for word, paused in (("pause", True), ("resume", False)):
        if word in text:
            if _who(activity) != meeting.organiser_oid:
                return f"Only the meeting organiser can {word} processing."
            registry.set_paused(meeting.chat_id, paused, client=client)
            return ("Paused: recordings of this meeting will not be processed." if paused
                    else "Resumed: the next recording will be processed after the meeting.")
    if "status" in text:
        return ("Processing is PAUSED for this meeting." if meeting.paused
                else "On: the recording is processed after the meeting ends.")
    return "Say `status`, or — as the organiser — `pause` or `resume`."
