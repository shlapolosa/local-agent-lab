"""lab.substrate.meetingapp.bot — what the bot does with what Teams sends it, framework-free.

The security-relevant part is `on_card`: the speaker form (what each voice SAID) is shown, and an
answer recorded, only for the meeting's ORGANISER — decided here on every refresh and every submit
from the registry, never from data a client sends back. Activities are plain dicts in the shape the
Teams SDK dumps them (by_alias), so these tests need no Teams.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/meetingapp/test_bot.py"""
from fixtures.fakes import FakeRedis
from lab.platform.contracts import ApprovalKind
from lab.substrate.meetingapp import bot, registry
from lab.substrate.meetingapp.registry import Meeting

CHAT = "19:meeting_x@thread.v2"
ORG_OID, ORG_MRI = "org-oid", "29:org"
M = Meeting(chat_id=CHAT, organiser_oid=ORG_OID, organiser_mri=ORG_MRI, graph_meeting_id="MSo",
            service_url="https://smba/", tenant_id="t")
RECORDING = "collab://recording/org-oid~MSo/rec-1"
PAYLOAD = {"question": {"items": [{"label": "SPEAKER_00", "samples": ["shall we start"], "seconds": 30, "turns": 2},
                                  {"label": "SPEAKER_01", "samples": ["agreed"], "seconds": 3, "turns": 1}]},
           "continuation": {"process": "transcript_to_minutes",
                            "inputs": {"provider": "soniox-en", "chat_id": CHAT, "recording": RECORDING}}}
OPEN = {"request_id": "apr-1", "status": "pending", "kind": ApprovalKind.SPEAKER_MAPPING.value, "payload": PAYLOAD}


def activity(verb, who=ORG_OID, mri=ORG_MRI, **data):
    return {"conversation": {"id": CHAT}, "from": {"id": mri, "aadObjectId": who, "name": "Maria Perez"},
            "value": {"action": {"type": "Action.Execute", "verb": verb, "data": {"approval_id": "apr-1", **data}}}}


def card(act, st=OPEN):
    decided = []
    r = FakeRedis()
    registry.save(M, client=r)
    out, _closed = bot.on_card(act, actor="maria@contoso.com", status=lambda rid, **kw: st,
                               decide=lambda *a, **kw: decided.append((a, kw)), client=r)
    return out, decided


def test_the_organisers_refresh_shows_the_speaker_form():
    out, decided = card(activity("refresh"))
    assert "shall we start" in str(out) and out["actions"][0]["verb"] == "submit"
    assert decided == []


def test_anyone_else_sees_the_neutral_card_on_refresh_and_on_submit():
    for verb in ("refresh", "submit"):
        out, decided = card(activity(verb, who="someone-else", mri="29:else",
                                     identity_SPEAKER_00="x@y.com", tag_SPEAKER_01="z"))
        assert "shall we start" not in str(out) and "actions" not in out
        assert decided == [], "only the organiser's answer is ever recorded"


def test_the_organisers_submit_records_one_answer_as_them_through_the_human_gate():
    out, decided = card(activity("submit", identity_SPEAKER_00="maria@contoso.com", consent_SPEAKER_00="yes",
                                 tag_SPEAKER_01="TV"))
    (args, kw), = decided
    assert args == ("apr-1", "approve", "maria@contoso.com", bot.CHANNEL)
    assert kw["answer"] == {"SPEAKER_00": {"identity": "maria@contoso.com", "consent": "yes"},
                            "SPEAKER_01": {"tag": "TV", "consent": "no"}}
    assert "Maria Perez" in str(out) and "refresh" not in out


def test_a_submit_that_leaves_a_speaker_unnamed_is_sent_back_saying_which():
    out, decided = card(activity("submit", identity_SPEAKER_00="maria@contoso.com"))
    assert decided == [] and "SPEAKER_01" in str(out) and out["actions"][0]["verb"] == "submit"


def test_an_already_answered_question_shows_who_answered_it_to_everyone():
    out, decided = card(activity("refresh"), st=OPEN | {"status": "approve", "decided_by": "maria@contoso.com"})
    assert "maria@contoso.com" in str(out) and decided == []


def test_a_meeting_the_bot_does_not_know_shows_nobody_the_form():
    decided = []
    out, _ = bot.on_card(activity("refresh"), actor="maria@contoso.com", status=lambda rid, **kw: OPEN,
                         decide=lambda *a, **kw: decided.append(a), client=FakeRedis())
    assert "shall we start" not in str(out) and decided == []


def test_install_in_a_meeting_registers_it_and_says_welcome():
    r = FakeRedis()
    act = {"conversation": {"id": CHAT, "tenantId": "t"}, "serviceUrl": "https://smba/",
           "channelData": {"meeting": {"id": "teams-meeting-id"}, "tenant": {"id": "t"}}}
    info = {"details": {"msGraphResourceId": "MSo"}, "organizer": {"aadObjectId": ORG_OID, "id": ORG_MRI}}
    welcome = bot.on_install(act, info, client=r)
    assert registry.by_meeting(ORG_OID, "MSo", client=r) == M
    assert "consent" in str(welcome).lower()


def test_install_outside_a_meeting_registers_nothing():
    r = FakeRedis()
    assert bot.on_install({"conversation": {"id": "a:personal"}, "channelData": {}}, None, client=r) is None


def test_only_the_organiser_can_pause_and_anyone_can_ask_the_status():
    r = FakeRedis()
    registry.save(M, client=r)
    said = bot.on_command({"conversation": {"id": CHAT}, "from": {"aadObjectId": "someone-else"},
                           "text": "<at>Meeting Notes</at> pause"}, client=r)
    assert "organiser" in said.lower() and not registry.by_chat(CHAT, client=r).paused
    bot.on_command({"conversation": {"id": CHAT}, "from": {"aadObjectId": ORG_OID}, "text": "pause"}, client=r)
    assert registry.by_chat(CHAT, client=r).paused
    assert "paused" in bot.on_command({"conversation": {"id": CHAT}, "from": {"aadObjectId": "x"},
                                       "text": "status"}, client=r).lower()


def test_recording_ref_in_these_tests_is_the_adapters_own_encoding():
    from lab.substrate.mcp.graph import graph_map
    assert RECORDING == f"collab://recording/{graph_map.meeting_ref('org-oid', 'MSo')}/rec-1"


def test_an_approval_of_another_meeting_is_neither_shown_nor_decided():
    """The approval id arrives in client data. The organiser of THIS meeting must not see — or answer —
    a question about another meeting's voices by sending its id."""
    other = OPEN | {"payload": PAYLOAD | {"continuation": {"process": "transcript_to_minutes", "inputs": {
        "chat_id": CHAT, "recording": "collab://recording/other~MSo/rec-9"}}}}
    for verb in ("refresh", "submit"):
        out, decided = card(activity(verb, identity_SPEAKER_00="m@x.com", tag_SPEAKER_01="z"), st=other)
        assert "shall we start" not in str(out) and decided == []


def test_an_approval_that_is_not_a_speaker_question_is_never_decided_here():
    """An EA import or an investment authorisation has no speakers, so an empty answer would 'complete'
    it — this channel decides speaker questions and nothing else."""
    ea = OPEN | {"kind": "ea-import", "payload": {"continuation": PAYLOAD["continuation"]}}
    out, decided = card(activity("submit"), st=ea)
    assert decided == []


def test_a_question_answered_meanwhile_elsewhere_shows_who_answered_instead_of_failing():
    r = FakeRedis()
    registry.save(M, client=r)

    def lost_race(*a, **kw):
        raise ValueError("apr-1 is already approve (by someone)")
    out, closed = bot.on_card(activity("submit", identity_SPEAKER_00="m@x.com", tag_SPEAKER_01="z"),
                              actor="m@x.com", status=lambda rid, **kw: OPEN, decide=lost_race, client=r)
    assert "answered" in str(out).lower() and closed


def test_closing_the_card_for_everyone_is_said_explicitly():
    r = FakeRedis()
    registry.save(M, client=r)
    assert bot.on_card(activity("submit", identity_SPEAKER_00="m@x.com", tag_SPEAKER_01="z"),
                       actor="m@x.com", status=lambda rid, **kw: OPEN, decide=lambda *a, **kw: None, client=r)[1]
    assert not bot.on_card(activity("refresh"), actor="", status=lambda rid, **kw: OPEN,
                           decide=lambda *a, **kw: None, client=r)[1]


def test_a_command_is_the_first_word_said_to_the_bot_not_any_word_in_the_sentence():
    r = FakeRedis()
    registry.save(M, client=r)
    bot.on_command({"conversation": {"id": CHAT}, "from": {"aadObjectId": ORG_OID},
                    "text": "<at>Meeting Notes</at> status — don't pause yet"}, client=r)
    assert not registry.by_chat(CHAT, client=r).paused


def test_the_actor_is_the_directory_name_when_teams_gives_one():
    assert bot.actor_of({"userPrincipalName": "m@x.com", "email": "e@x.com"}, "oid") == "m@x.com"
    assert bot.actor_of({"email": "e@x.com"}, "oid") == "e@x.com"
    assert bot.actor_of({}, "oid") == "oid"


def test_install_remembers_what_the_meeting_is_called():
    r = FakeRedis()
    act = {"conversation": {"id": CHAT, "tenantId": "t"}, "serviceUrl": "https://smba/",
           "channelData": {"meeting": {"id": "teams-meeting-id"}, "tenant": {"id": "t"}}}
    info = {"details": {"msGraphResourceId": "MSo", "title": "Portal kickoff"},
            "organizer": {"aadObjectId": ORG_OID, "id": ORG_MRI}}
    bot.on_install(act, info, client=r)
    assert registry.by_chat(CHAT, client=r).title == "Portal kickoff"
