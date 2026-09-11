from fixtures.fakes import FakeRedis
from lab.platform import delivery, workflows
from lab.platform.delivery import LabDeliveryContexts, from_run


def test_a_minutes_run_is_filed_under_its_meeting():
    ctx = from_run({"process": "transcript_to_minutes", "request_id": "r1",
                    "inputs": {"recording": "collab://recording/AAMk1/rec-9", "owner": "a@x.org"},
                    "meeting": {"subject": "Weekly EA"}})
    assert ctx.key == "meeting:AAMk1" and ctx.label == "Weekly EA" and ctx.owner == "a@x.org" and ctx.source == "lab"


def test_a_minutes_run_whose_continuation_inputs_lack_a_recording_falls_back_to_its_submission():
    """The narrow real case: an approval staged before `recording` joined the continuation's inputs, or a
    recording that belongs to no meeting. The run is still the container; nothing is left contextless."""
    assert from_run({"process": "transcript_to_minutes", "request_id": "r1", "inputs": {"transcript": "art://a/b"}}).key == "submission:r1"
    assert from_run({"process": "transcript_to_minutes", "inputs": {"transcript": "art://a/b"}}) is None


def test_a_use_case_run_is_filed_under_its_use_case():
    assert from_run({"process": "use_case_screening", "request_id": "r7", "inputs": {"submitter": "s@x.org"}}).key == "usecase:r7"
    assert from_run({"process": "use_case_design", "request_id": "r8", "usecase_id": "UC-42"}).key == "usecase:UC-42"
    assert from_run({"process": "use_case_design", "request_id": "r8"}).key == "submission:r8"


def test_a_diagram_run_is_a_submission():
    assert from_run({"process": "visio_to_archimate", "request_id": "r2", "requester": "b@x.org"}).key == "submission:r2"
    assert from_run({"process": "visio_to_archimate"}) is None


def test_repository_reads_the_request_hash():
    r = FakeRedis()
    r.hset("workflow:req:r2", mapping={"request_id": "r2", "process": "visio_to_archimate", "requester": "b@x.org",
                                       "inputs": '{"diagram": "art://d/x.vsdx"}', "status": "done"})
    repo = LabDeliveryContexts(client=r)
    assert repo.context("submission:r2").owner == "b@x.org"
    assert repo.context("submission:missing") is None
    assert repo.context("meeting:AAMk1").kind == "meeting"
    assert repo.context("workitem:4471") is None, "another adapter's kind"
