"""A completed intake form IS a submission — a conversation does not produce a document.

Measured against the real M42 Microsoft Forms export (62 submissions, 32 questions). The contract
required exactly one of `submission` (an `art://` ref) or `submission_handle`, and a Copilot
Studio agent can produce neither: it holds no collab grant, the connector deliberately does not
upload, and the front door has no upload route. So an agent walked a user through all 32 questions
and the submit was refused for a field the conversation never had.

The answers ARE the prose: "describe the task and what triggers it", "the biggest value this
would deliver", "what the systems are used for", "what should happen to the results". Step 2's
requirement is a readable document, and a rendered intake is one.

The document path is unchanged — a person with a .docx still uploads it. What changes is that
supplying NEITHER document is no longer a refusal when the intake itself carries the case.
"""
import pytest

from lab.platform import contracts

SPEC = contracts.PROCESSES["use_case_screening"]
ANSWERS = {
    "Describe the task or process you want to automate": {
        "value": "Triggered after every change to a RAG pipeline; we run the curated query set "
                 "and score retrieval relevance."},
    "In your own words, what is the biggest value": {
        "value": "Retrieval quality measured the same way every time, so regressions are caught "
                 "before a pipeline change reaches users."},
    "Which systems does this process currently utilise?": {"value": "AI Workbench;Azure DevOps"},
}


def test_an_intake_alone_is_accepted():
    out = SPEC.validate({"submitter": "oalhashmi@malaffi.ae", "intake": ANSWERS})
    assert out["intake"] and not out.get("submission")


def test_a_document_is_still_accepted_on_its_own():
    out = SPEC.validate({"submitter": "o@m.ae", "submission": "art://abc/use-case.md"})
    assert out["submission"] == "art://abc/use-case.md"


def test_supplying_a_document_AND_an_intake_is_fine_because_they_are_not_alternatives():
    """The intake is structured evidence; the document is prose. A submitter with both is the
    richest case, not an ambiguous one."""
    out = SPEC.validate({"submitter": "o@m.ae", "submission": "art://abc/u.md",
                         "intake": ANSWERS})
    assert out["submission"] and out["intake"]


def test_two_DOCUMENTS_are_still_refused_because_those_are_alternatives():
    with pytest.raises(ValueError, match="submission"):
        SPEC.validate({"submitter": "o@m.ae", "submission": "art://a/u.md",
                       "submission_handle": "abc123"})


def test_a_submission_with_no_case_at_all_is_still_refused():
    """Relaxing the rule must not accept an empty submit — that is a run with nothing to assess."""
    with pytest.raises(ValueError, match="submission|intake"):
        SPEC.validate({"submitter": "o@m.ae"})
