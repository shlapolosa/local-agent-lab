"""Every answer a surface OFFERS must be one the applier accepts.

The defect this exists to stop, measured 19 Oct 2026 by driving the real review app and the real
applier: `samples` meant two different things to two producers. For the use-case questions they are the
answers themselves (`routine | business-critical | safety-of-life`), and the review app accordingly
renders them as the pick list. The artifact intake put PROSE and SCORES there — "project:alpha (0.92)",
"suggested: Requirements specification (0.81)", "Prescription — found in the content; answer keep…".

Picking the offered value then did one of two things, and the second is the dangerous one:
  * document_type / overlap / subject -> the curator REFUSES it and the card re-opens;
  * context / owner -> ACCEPTED, and a rung-H assertion is written with the score inside the IRI
    (`urn:fabric:context:project:alpha (0.92)`), marking a record associated, at the fabric's highest
    rung, under a context that does not exist, with a person's name on it.

So the contract now separates the two meanings: `choices` are answers, `samples` are explanation. This
test walks every item the intake card can produce and asserts the offered answers are legal.
"""
import pytest

from lab.core.semantic.fabric.ontology import DocumentTypes
from lab.platform.contracts import speaker_prompts
from lab.substrate import fabric_curator as C

IRI = "urn:fabric:artifact:1"
ROW = {"iri": IRI, "title": "eRx BRS", "links": []}


def _offered(items):
    """What a person can PICK, as the review app offers it — `choices`, never `samples`."""
    return [(p.label, c) for p in speaker_prompts({"question": {"items": items}}) for c in p.choices]


def test_every_pick_the_intake_card_offers_is_an_answer_the_curator_ACCEPTS():
    doc_type = next(iter(DocumentTypes().types().values()), None)
    items = [
        {"label": "document_type", "samples": ["suggested: Requirements specification (0.81)"],
         "choices": [doc_type["label"]] if doc_type else []},
        {"label": "context", "samples": ["project:alpha (0.92) — the run that produced it"],
         "choices": ["project:alpha", "none"]},
        {"label": "overlap", "samples": ["ADR-14 (0.90) — the near-duplicate"],
         "choices": ["keep", f"duplicate-of:{IRI}"]},
        {"label": "subject:urn:c#Prescription", "samples": ["Prescription — found in the content"],
         "choices": ["keep", "drop"]},
    ]
    offered = _offered(items)
    assert offered, "the card offers picks at all"
    for label, pick in offered:
        # Each pick ALONE must plan without raising: that is what "offered" means to a person.
        C.plan(ROW, {label: {"value": pick}}, "owner@x")


def test_a_pick_carrying_a_SCORE_is_refused_rather_than_stored_as_an_IRI():
    """The silent half. Before the split, this is what the review app offered for `context`, and the
    applier took it — there is no downstream check, because `graph_assert` validates the subject and the
    predicate of a triple and never its object."""
    with pytest.raises(ValueError):
        C.plan(ROW, {"context": {"value": "project:alpha (0.92)"}}, "owner@x")


def test_SAMPLES_are_never_offered_as_answers():
    """The rule that keeps this from coming back: a surface picks from `choices`. A producer who puts
    prose in `samples` can no longer make it selectable, whatever they write."""
    prompts = speaker_prompts({"question": {"items": [
        {"label": "context", "samples": ["project:alpha (0.92) — the run that produced it"],
         "choices": ["project:alpha"]}]}})
    assert prompts[0].choices == ("project:alpha",)
    assert "0.92" in prompts[0].samples[0] and all("0.92" not in c for c in prompts[0].choices)
