"""lab.substrate.meetingapp.registry — the meetings the app was added to, as the bot learned them.

Microsoft's recording notification names the organiser and the meeting but not its chat, and the
chat is where everything the app says goes. The bot learns both when it is added, so the registry
joins them: meeting -> chat, and chat -> what the bot needs to speak there.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/meetingapp/test_registry.py"""
from fixtures.fakes import FakeRedis
from lab.substrate.meetingapp import registry
from lab.substrate.meetingapp.registry import Meeting

M = Meeting(chat_id="19:meeting_x@thread.v2", organiser_oid="org-oid", organiser_mri="29:org",
            graph_meeting_id="MSoxMTE", service_url="https://smba.trafficmanager.net/ae/t/", tenant_id="t")


def test_a_meeting_is_found_by_its_chat_and_by_its_graph_identity():
    r = FakeRedis()
    registry.save(M, client=r)
    assert registry.by_chat(M.chat_id, client=r) == M
    assert registry.by_meeting("org-oid", "MSoxMTE", client=r) == M
    assert registry.by_meeting("org-oid", "other", client=r) is None


def test_pausing_is_remembered_and_survives_the_app_being_re_added():
    r = FakeRedis()
    registry.save(M, client=r)
    registry.set_paused(M.chat_id, True, client=r)
    assert registry.by_chat(M.chat_id, client=r).paused
    registry.save(M, client=r)                      # a later install event must not resume it
    assert registry.by_chat(M.chat_id, client=r).paused


def test_entries_expire_so_a_meeting_never_seen_again_is_eventually_forgotten():
    r = FakeRedis()
    registry.save(M, client=r)
    assert 0 < r.pttl(registry.chat_key(M.chat_id)) <= registry.TTL_S * 1000


def test_the_card_posted_for_an_approval_is_remembered_so_it_can_be_updated():
    r = FakeRedis()
    registry.remember_card("apr-1", M.chat_id, "activity-9", client=r)
    assert registry.card_of("apr-1", client=r) == (M.chat_id, "activity-9")
    assert registry.card_of("apr-2", client=r) is None
