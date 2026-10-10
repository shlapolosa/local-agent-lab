"""The steward's gate: a person's answer about the VOCABULARY, applied as curation.

The sibling of `fabric_curator`, which applies a person's answer about one ARTIFACT. Same stream, same runner,
same registry — a second domain is an applier and a `register` line, not a branch in the runner.
"""
import asyncio

import pytest

from lab.platform.contracts import ApprovalTools, ApprovalKind, SemanticTools
from lab.substrate import answer_appliers, fabric_vocabulary as V

CANDIDATE = "urn:fabric:candidate:01J9X5K7QZ3M8N2P4R6T8V0W1Y"
PAYLOAD = {"kind": ApprovalKind.CONCEPT_ADMISSION.value, "candidate": CANDIDATE, "label": "Model card",
           "scheme": "cafe", "proposed_by": "classifier-agent", "used_by": ["urn:fabric:artifact:A"]}


def one(label, value, field="value"):
    return {label: {field: value}}


def test_the_registry_routes_this_kind_here_and_only_this_kind():
    assert answer_appliers.applier_for(ApprovalKind.CONCEPT_ADMISSION.value) is V.apply
    assert V.applies_to(ApprovalKind.CONCEPT_ADMISSION.value)
    assert not V.applies_to(ApprovalKind.DRAFT_REVIEW.value)


def test_admitting_names_the_person_the_scheme_and_the_id():
    calls = V.plan(PAYLOAD, {**one("decision", "admit"), **one("definition", "What a model is for"),
                             **one("module", "Assurance"), **one("concept_id", "ModelCard")}, "steward@doh")
    assert [t for t, _ in calls] == [SemanticTools.vocab_propose, SemanticTools.promote]
    parked = dict(calls[0][1])
    assert parked["scheme"] == "cafe" and parked["concept_id"] == "ModelCard"
    assert parked["definition"] == "What a model is for" and parked["actor"] == "steward@doh"
    assert parked["module"] == "Assurance"      # asked for, so it must reach the concept — not be discarded
    assert calls[1][1]["actor"] == "steward@doh" and "predicate" not in calls[1][1]


def test_a_decision_to_decline_admits_nothing_and_says_so():
    assert V.plan(PAYLOAD, one("decision", "decline"), "steward@doh") == []


def test_a_steward_may_answer_that_it_already_exists_which_is_a_link_not_a_concept():
    """The commonest answer to "this term has no concept": it does, under another name. Admitting a second
    would be the duplicate the vocabulary exists to prevent."""
    calls = V.plan(PAYLOAD, {**one("decision", "existing"), **one("concept_id", "AIAgent")}, "steward@doh")
    assert [t for t, _ in calls] == [SemanticTools.vocab_amend]
    assert calls[0][1] == {"concept_id": "AIAgent", "scheme": "cafe", "alt": "Model card",
                           "actor": "steward@doh", "reason": "a steward said this term means AIAgent"}


def test_settling_a_conflict_retires_the_meaning_the_steward_did_not_keep():
    payload = {"kind": ApprovalKind.CONCEPT_ADMISSION.value, "scheme": "cafe", "term": "Agent",
               "concepts": ["AIAgent", "SoftwareAgent"], "conflict": "urn:fabric:conflict:Agent"}
    calls = V.plan(payload, {**one("decision", "settle"), **one("keep", "AIAgent")}, "steward@doh")
    assert [t for t, _ in calls] == [SemanticTools.vocab_retire]
    assert calls[0][1]["concept_id"] == "SoftwareAgent" and calls[0][1]["resolves_to"] == "AIAgent"
    assert calls[0][1]["actor"] == "steward@doh"


def test_a_kept_meaning_that_is_not_one_of_the_two_is_refused():
    payload = {"kind": ApprovalKind.CONCEPT_ADMISSION.value, "scheme": "cafe", "term": "Agent",
               "concepts": ["AIAgent", "SoftwareAgent"]}
    with pytest.raises(ValueError, match="one of"):
        V.plan(payload, {**one("decision", "settle"), **one("keep", "Elsewhere")}, "steward@doh")


def test_the_gate_refuses_an_anonymous_decision_and_an_unanswerable_one():
    with pytest.raises(ValueError, match="actor"):
        V.plan(PAYLOAD, one("decision", "admit"), "")
    with pytest.raises(ValueError, match="decision"):
        V.plan(PAYLOAD, one("definition", "d"), "steward@doh")
    with pytest.raises(ValueError, match="admit|decline|existing|settle"):
        V.plan(PAYLOAD, one("decision", "maybe"), "steward@doh")
    with pytest.raises(ValueError, match="scheme"):
        V.plan({"kind": "concept-admission", "label": "x"}, one("decision", "admit"), "steward@doh")


def test_apply_makes_the_calls_and_answers_with_what_it_did():
    made = []

    async def call(calls):
        made.extend(calls)
        return [{"iri": CANDIDATE} for _ in calls]

    out = asyncio.run(V.apply({"payload": PAYLOAD, "answer": one("decision", "admit")}, "steward@doh", call=call))
    assert [t for t, _ in out] == [SemanticTools.vocab_propose, SemanticTools.promote]
    # the SECOND call promotes the candidate the FIRST one just parked, never the one in the payload: a gate
    # that admitted the original would admit whatever the asker had left lying there
    assert made[1][1]["subject"] == CANDIDATE


def test_the_question_asks_one_thing_per_label_as_every_other_surface_does():
    """`contracts.answer_value` refuses two fields under one label, so a question that bundled definition and
    module would be unanswerable on every surface at once."""
    q = V.question(PAYLOAD)
    assert [i["label"] for i in q] == ["decision", "concept_id", "definition", "module", "broader"]
    assert "admit" in q[0]["samples"][0] and "existing" in q[0]["samples"][0]
    assert all(isinstance(i["samples"], list) and i["samples"] for i in q)     # every label says what to type


def test_the_steward_is_asked_about_open_conflicts_and_parked_candidates_once_each():
    """Nothing else raises this question, so the sweep is what makes the gate reachable — and asking the same
    thing every fifteen minutes would bury the approvals that need somebody, exactly as a channel backlog does."""
    asked, open_ = [], [{"iri": "urn:fabric:conflict:1", "term": "Agent", "scheme": "cafe",
                         "concepts": ["AIAgent", "SoftwareAgent"]}]
    parked = [{"iri": CANDIDATE, "label": "Model card", "scheme": "cafe", "proposed_by": "classifier-agent"}]

    async def call(calls):
        out = []
        for tool, args in calls:
            if tool == SemanticTools.vocab_conflicts:
                out.append(open_)
            elif tool == SemanticTools.vocab_candidates:
                out.append(parked)
            elif tool == "approvals_ask":
                asked.append(args)
                out.append({"request_id": f"apr-{len(asked)}"})
            else:
                out.append({})
        return out

    # `batch=False` on purpose: the ONE-TERM card is still a real path — it is the detailed form,
    # five fields deep, for a term that deserves care rather than triage. The batch is the default
    # because volume is the common case; this pins that the careful one still works.
    made = asyncio.run(V.ask_open(call=call, seen=set(), batch=False))
    assert len(made) == 2 and {a["kind"] for a in asked} == {ApprovalKind.CONCEPT_ADMISSION.value}
    candidate, conflict = asked                                      # what has NO meaning, then what has two
    assert [i["label"] for i in candidate["items"]][:2] == ["decision", "concept_id"]
    assert candidate["context"]["label"] == "Model card" and "no concept" in candidate["subject"]
    assert [i["label"] for i in conflict["items"]] == ["decision", "keep"]
    assert conflict["context"]["concepts"] == ["AIAgent", "SoftwareAgent"] and "Agent" in conflict["subject"]
    seen = {"urn:fabric:conflict:1", CANDIDATE}
    assert asyncio.run(V.ask_open(call=call, seen=seen)) == []       # asked once, not every tick


def test_the_eleventh_thing_to_settle_is_not_lost_behind_the_first_ten():
    """Slicing before filtering means that once `limit` rows have been asked about, the next is never reached
    again for the life of the process — and the queue only grows."""
    rows = [{"iri": f"urn:fabric:conflict:{i}", "term": f"t{i}", "scheme": "cafe", "concepts": ["A", "B"]}
            for i in range(12)]

    async def call(calls):
        return [rows if t == SemanticTools.vocab_conflicts
                else [] if t == SemanticTools.vocab_candidates
                else {"asked": True} if t == SemanticTools.vocab_asked   # the register remembers (T2.6)
                else {"request_id": "apr-1"} for t, _ in calls]

    seen = {r["iri"] for r in rows[:10]}
    assert [r["term"] for r in asyncio.run(V.ask_open(call=call, seen=seen))] == ["t10", "t11"]


def test_every_label_the_steward_is_asked_about_is_read_by_the_plan():
    """A question with an item nothing reads asks a person for something that is thrown away — and one that
    reads a label it never offered can never receive it."""
    answered = {"decision": {"value": "admit"}, "concept_id": {"value": "ModelCard"},
                "definition": {"value": "d"}, "module": {"value": "m"}, "broader": {"value": "AIAgent"}}
    asked = {i["label"] for i in V.question(PAYLOAD)}
    assert asked == set(answered)
    parked = dict(V.plan(PAYLOAD, answered, "steward@doh")[0][1])
    assert {parked[k] for k in ("concept_id", "definition", "module", "broader")} == {"ModelCard", "d", "m", "AIAgent"}


# ------------------------------------------------------------------ T2.2: the frequency threshold
def test_a_term_asked_for_ONCE_is_parked_rather_than_put_to_a_steward():
    """`FABRIC_CANDIDATE_THRESHOLD` governs INTERRUPTION, not visibility — the distinction that keeps
    "parked" from becoming "hidden", which is the defect this layer keeps producing in new places.
    `vocab_candidates` still returns everything; only what is PUSHED is bounded.

    Two, decided by the user on the measured distribution (10 Oct 2026): of 37 genuinely-unknown terms,
    29 had been asked for once, 7 twice and one three times. At 3 the steward is asked about ONE term and
    cannot see what the bar silenced; at 2 they are asked about eight — a sitting rather than a queue —
    and can raise it on evidence. Low and tightening beats high and blind, because two thirds of this
    corpus is the lab's own test output and the counts are not yet representative of real demand."""
    asked = []

    async def call(calls):
        out = []
        for name, args in calls:
            if name == SemanticTools.vocab_candidates:
                out.append([{"iri": "urn:fabric:candidate:1", "label": "Transcript", "scheme": "cafe",
                             "proposals": 3, "proposed_for": ["a", "b", "c"]},
                            {"iri": "urn:fabric:candidate:2", "label": "Knowledge Agent", "scheme": "cafe",
                             "proposals": 2, "proposed_for": ["a", "b"]},
                            {"iri": "urn:fabric:candidate:3", "label": "Seen once", "scheme": "cafe",
                             "proposals": 1, "proposed_for": ["a"]}])
            elif name == SemanticTools.vocab_conflicts:
                out.append([])
            elif name == SemanticTools.vocab_asked:
                out.append({"asked": True})            # the register remembers (T2.6)
            else:
                asked.append(args)
                out.append({"request_id": f"apr-{len(asked)}"})
        return out

    made = asyncio.run(V.ask_open(call=call, seen=set(), threshold=2))
    assert {m["label"] for m in made} == {"Transcript", "Knowledge Agent"}
    assert "Seen once" not in str(asked)

    # ...and a threshold of 1 asks about everything, which is what "off" means here
    assert len(asyncio.run(V.ask_open(call=call, seen=set(), threshold=1))) == 3


def test_a_candidate_from_before_the_count_existed_is_still_asked_about():
    """Rows written before `proposals` existed carry none. Reading a missing count as zero would silence
    the entire back catalogue the moment the threshold landed — the quietest possible regression."""
    async def call(calls):
        out = []
        for name, args in calls:
            if name == SemanticTools.vocab_candidates:
                out.append([{"iri": "urn:fabric:candidate:9", "label": "Legacy", "scheme": "cafe"}])
            elif name == SemanticTools.vocab_conflicts:
                out.append([])
            elif name == SemanticTools.vocab_asked:
                out.append({"asked": True})            # the register remembers (T2.6)
            else:
                out.append({"request_id": "apr-9"})
        return out
    assert [m["label"] for m in asyncio.run(V.ask_open(call=call, seen=set(), threshold=2))] == ["Legacy"]


# ------------------------------------------- T2.3: one card, N terms — the shape the speaker card proved
def test_the_steward_is_asked_about_many_terms_on_ONE_card():
    """The user's observation, 10 Oct 2026: the meeting owner already tags N speakers on ONE Teams card,
    so a steward should triage N terms the same way. It is the same machinery — `approvals_ask` takes
    `items`, `check_answer` already enforces that every label is answered, and every surface renders a
    form from it — so this is not new plumbing, it is passing a list where a loop used to be.

    It had to change, not merely improve: one card per candidate produced 101 open cards against ~37 of
    everything else, and a steward opening Teams saw a wall of term questions.

    ONE WORD PER TERM, deliberately. The single-term card asks five things (decision, id, definition,
    module, broader); eight of those on one card is forty fields and nobody triages forty fields. So the
    batch asks the only question volume needs — admit, or it already exists, or no — and the detailed
    form stays for a term that deserves care."""
    asked = []

    async def call(calls):
        out = []
        for name, args in calls:
            if name == SemanticTools.vocab_candidates:
                out.append([{"iri": f"urn:fabric:candidate:{i}", "label": label, "scheme": "cafe",
                             "proposals": n, "proposed_for": [f"a{j}" for j in range(n)]}
                            for i, (label, n) in enumerate((("Transcript", 3), ("Knowledge Agent", 2),
                                                            ("Seen once", 1)))])
            elif name == SemanticTools.vocab_conflicts:
                out.append([])
            elif name == SemanticTools.vocab_asked:
                out.append({"asked": True})            # the register remembers (T2.6)
            else:
                asked.append(args)
                out.append({"request_id": "apr-batch"})
        return out

    made = asyncio.run(V.ask_open(call=call, seen=set(), threshold=2, batch=True))
    assert len(asked) == 1, "a steward gets ONE card, not one per term"
    card = asked[0]
    labels = [i["label"] for i in card["items"]]
    assert set(labels) == {"urn:fabric:candidate:0", "urn:fabric:candidate:1"}, "keyed on the candidate"
    assert len(set(labels)) == len(labels)          # check_answer keys on the label: each exactly once
    body = str(card)
    assert "Transcript" in body and "Knowledge Agent" in body and "Seen once" not in body
    assert "3 documents" in body and "2 documents" in body     # the evidence a steward triages on
    assert len(made) == 2                                      # what was asked about, for the caller's `seen`


def test_the_batch_card_offers_the_commonest_answer_as_a_PICK():
    """`vocab_candidates`' own docstring says a steward most often settles a term by making it another
    name for a concept already held. A card that only offered "admit" or "decline" would make the
    commonest answer the hardest to give — the same reason the speaker card offers attendees beside free
    text, and never instead of it."""
    async def call(calls):
        out = []
        for name, args in calls:
            if name == SemanticTools.vocab_candidates:
                out.append([{"iri": "urn:fabric:candidate:0", "label": "Clinical Reviewer",
                             "scheme": "cafe", "proposals": 2, "proposed_for": ["a", "b"]}])
            elif name == SemanticTools.vocab_conflicts:
                out.append([])
            elif name == SemanticTools.vocab_asked:
                out.append({"asked": True})            # the register remembers (T2.6)
            else:
                out.append({"request_id": "apr-batch", "args": args})
                call.card = args
        return out
    asyncio.run(V.ask_open(call=call, seen=set(), threshold=2, batch=True))
    item = call.card["items"][0]
    samples = " ".join(item["samples"])
    for option in ("admit", "existing:", "decline"):
        assert option in samples, f"{option} is not offered"
    assert call.card["fields"] == ["value"]        # one thing to say per term, as every surface renders it


# -------------------------------------------------- T2.3: applying a batch answer, one verdict per term
def _batch_payload():
    return {"kind": "concept-admission",
            "context": {"candidates": [
                {"iri": "urn:fabric:candidate:0", "label": "Clinical Reviewer", "scheme": "cafe"},
                {"iri": "urn:fabric:candidate:1", "label": "Agentic retrieval", "scheme": "cafe"},
                {"iri": "urn:fabric:candidate:2", "label": "CSV file", "scheme": "cafe"}]}}


def test_one_card_carries_three_verdicts_and_each_lands_where_it_belongs():
    """The steward triages a list; every term gets its own outcome from the one decision. `admit` accepts
    the parked candidate, `existing:<id>` makes the term another name for a concept already there (the
    commonest answer), and `decline` is RECORDED — not merely left on the approval, which is what let a
    restart re-ask 30 declined terms in a single afternoon."""
    answer = {"urn:fabric:candidate:0": {"value": "existing:ClinicalReview"},
              "urn:fabric:candidate:1": {"value": "admit"},
              "urn:fabric:candidate:2": {"value": "decline"}}
    calls = V.plan(_batch_payload(), answer, "steward@x")
    tools = [t for t, _ in calls]
    assert SemanticTools.vocab_amend in tools        # existing: another name for a held concept
    assert SemanticTools.promote in tools            # admit: the candidate becomes a concept
    assert SemanticTools.vocab_decline in tools      # decline: recorded, so nobody is asked again

    amend = next(a for t, a in calls if t == SemanticTools.vocab_amend)
    assert amend["concept_id"] == "ClinicalReview" and amend["alt"] == "Clinical Reviewer"
    promote = next(a for t, a in calls if t == SemanticTools.promote)
    assert promote["subject"] == "urn:fabric:candidate:1" and promote["actor"] == "steward@x"
    decline = next(a for t, a in calls if t == SemanticTools.vocab_decline)
    assert decline["candidate"] == "urn:fabric:candidate:2" and decline["actor"] == "steward@x"


def test_a_batch_verdict_must_be_one_of_the_three_and_name_a_term_on_the_card():
    """`plan` SKIPS what it cannot read and `batch_problems` reports it — so one bad verdict costs that
    one term rather than the nine answered beside it. The sentence names the TERM, because a steward who
    answered ten of them should not have to work out which."""
    cands = _batch_payload()["context"]["candidates"]
    for bad, expect in (({"urn:fabric:candidate:0": {"value": "maybe"}}, "Clinical Reviewer"),
                        ({"urn:fabric:candidate:0": {"value": "existing:"}}, "names no concept"),
                        ({"urn:fabric:candidate:9": {"value": "admit"}}, "not one of the terms")):
        assert V.plan(_batch_payload(), bad, "steward@x") == []
        problems = V.batch_problems(cands, bad)
        assert len(problems) == 1 and expect in problems[0]


def test_the_single_term_card_still_applies_the_way_it_always_did():
    """One card per term is still a real path — the detailed form. Its answer shape is unchanged, which
    is what `context.candidates` being ABSENT selects: the batch is recognised by what it carries, never
    by a flag somebody must remember to set."""
    calls = V.plan({"scheme": "cafe", "label": "Model card"},
                   {"decision": {"value": "admit"}, "concept_id": {"value": "ModelCard"}}, "s@x")
    assert [t for t, _ in calls] == [SemanticTools.vocab_propose, SemanticTools.promote]


# ------------------------------------------------ T2.4: admitting a term reaches the documents that asked
def test_admitting_a_term_links_EXACTLY_the_documents_that_asked_for_it():
    """FR-1.1.5, and the reason T2.1 recorded `proposedFor` rather than a bare count.

    A concept admitted but not propagated changes nothing: the documents whose words prompted it stay
    unlinked until something re-reads them. Re-reading the WHOLE catalogue to find them would be one
    model call per record for a handful of hits; the register already knows which records asked, so the
    propagation is exact — and cheap enough to be unconditional.

    Asserted at rung X, not C: the term WAS found in those documents' content. It had no concept at the
    time, which is a fact about the vocabulary on that day, not about how the fabric came to know it."""
    seen = []

    async def call(calls):
        out = []
        for name, args in calls:
            seen.append((name, args))
            out.append({"concept_id": "ClinicalReviewer", "iri": "urn:lab:semantic:domain:cafe#ClinicalReviewer"}
                       if name == SemanticTools.promote else {})
        return out

    state = {"payload": {"context": {"candidates": [
        {"iri": "urn:fabric:candidate:0", "label": "Clinical Reviewer", "scheme": "cafe",
         "proposed_for": ["urn:fabric:artifact:A", "urn:fabric:artifact:B"]}]}},
        "answer": {"urn:fabric:candidate:0": {"value": "admit"}}}
    asyncio.run(V.apply(state, "steward@x", call=call))

    links = [a for n, a in seen if n == SemanticTools.edge_assert]
    assert {l["subject"] for l in links} == {"urn:fabric:artifact:A", "urn:fabric:artifact:B"}
    assert all(l["object"] == "urn:lab:semantic:domain:cafe#ClinicalReviewer" for l in links)
    assert all(l["rung"] == "X" and l["actor"] == "steward@x" for l in links)
    assert all("admission" in l["method"] for l in links)


def test_a_DECLINED_term_propagates_to_nobody():
    """Nothing was admitted, so there is nothing for a document to link to."""
    seen = []

    async def call(calls):
        for name, args in calls:
            seen.append(name)
        return [{} for _ in calls]

    state = {"payload": {"context": {"candidates": [
        {"iri": "urn:fabric:candidate:0", "label": "Seen once", "scheme": "cafe",
         "proposed_for": ["urn:fabric:artifact:A"]}]}},
        "answer": {"urn:fabric:candidate:0": {"value": "decline"}}}
    asyncio.run(V.apply(state, "steward@x", call=call))
    assert SemanticTools.vocab_decline in seen and SemanticTools.edge_assert not in seen


def test_a_term_nobody_is_recorded_as_having_asked_for_admits_without_propagating():
    """A candidate from before `proposedFor` existed. Admitting it must still work — it simply reaches
    nobody, which is honest: the register does not know who asked, and inventing a list would be worse
    than an empty one."""
    seen = []

    async def call(calls):
        out = []
        for name, args in calls:
            seen.append(name)
            out.append({"concept_id": "Legacy", "iri": "urn:lab:semantic:domain:cafe#Legacy"}
                       if name == SemanticTools.promote else {})
        return out

    state = {"payload": {"context": {"candidates": [
        {"iri": "urn:fabric:candidate:9", "label": "Legacy", "scheme": "cafe"}]}},
        "answer": {"urn:fabric:candidate:9": {"value": "admit"}}}
    asyncio.run(V.apply(state, "steward@x", call=call))
    assert SemanticTools.promote in seen and SemanticTools.edge_assert not in seen


# ------------------------- T2.6: what has already been asked is a FACT in the register, not a memory
def _cands(*rows):
    return [{"iri": f"urn:fabric:candidate:{i}", "label": l, "scheme": "cafe", "proposals": 2,
             "proposed_for": ["a", "b"], "asked": asked} for i, (l, asked) in enumerate(rows)]


def _gw(candidates):
    marked = []

    async def call(calls):
        out = []
        for name, args in calls:
            if name == SemanticTools.vocab_candidates:
                out.append(candidates)
            elif name == SemanticTools.vocab_conflicts:
                out.append([])
            elif name == SemanticTools.vocab_asked:
                marked.append(args["candidate"])
                out.append({"asked": True})
            else:
                out.append({"request_id": "apr-batch"})
        return out
    call.marked = marked
    return call


def test_a_candidate_already_PUT_to_a_steward_is_not_asked_about_again():
    """The leak that took 71 cards to 101 in an afternoon, still breathing after the durable decline
    closed its other half: `seen` was a set in the PROCESS, so a restart forgot every open question and
    raised a second card for the same terms.

    The answer is not to remember harder, it is to stop remembering here. `fab:InReview` is the word the
    lifecycle already had — Pending -> InReview -> Published|Withdrawn is the same ladder the artifacts
    climb — so the register says what has been asked and the register outlives every process.

    NOT derived from the approval surface, which was the first attempt and was wrong: `approvals_list`
    returns a TRIAGE brief with no `context`, so the terms a card covers cannot be read back from it. That
    version passed every test I wrote for it and would have found nothing live — both ends agreeing with
    each other and not with reality."""
    call = _gw(_cands(("Already asked", True), ("Brand new", False)))
    made = asyncio.run(V.ask_open(call=call, threshold=2))
    assert [m["label"] for m in made] == ["Brand new"]
    assert call.marked == ["urn:fabric:candidate:1"]       # and the new one is now remembered


def test_asking_MARKS_every_term_on_the_card_so_a_restart_repeats_none_of_them():
    call = _gw(_cands(("One", False), ("Two", False), ("Three", False)))
    asyncio.run(V.ask_open(call=call, threshold=2))
    assert sorted(call.marked) == [f"urn:fabric:candidate:{i}" for i in range(3)]


def test_when_everything_has_been_asked_no_card_is_raised_at_all():
    call = _gw(_cands(("One", True), ("Two", True)))
    assert asyncio.run(V.ask_open(call=call, threshold=2)) == []
    assert call.marked == []


# ------------------- one bad verdict must not discard nine good ones (measured live, 10 Oct 2026)
def _card3():
    return {"context": {"candidates": [
        {"iri": "c0", "label": "Coding assistance", "scheme": "cafe", "proposed_for": ["a"]},
        {"iri": "c1", "label": "Control", "scheme": "cafe"},
        {"iri": "c2", "label": "Decision Support", "scheme": "cafe"}]}}


def test_a_term_answered_badly_does_not_throw_away_the_ones_answered_well():
    """A steward triaged four terms in Teams, left the id box empty on one, and ALL FOUR were discarded —
    one admit and two declines thrown away with the mistake. For a card whose whole purpose is answering
    ten things at once, all-or-nothing is the wrong failure: the work a person did is the expensive part.

    So the verdicts that can be read are applied, and the ones that cannot are REPORTED. Both verbs are
    idempotent, so re-answering the card after fixing the one term is safe."""
    answer = {"c0": {"value": "admit"}, "c1": {"value": "decline"}, "c2": {"value": "existing"}}
    calls = V.plan(_card3(), answer, "steward@x")
    tools = [t for t, _ in calls]
    assert SemanticTools.promote in tools and SemanticTools.vocab_decline in tools
    assert SemanticTools.vocab_amend not in tools          # the one that could not be read
    assert V.batch_problems(_card3()["context"]["candidates"], answer) == \
        ["'Decision Support': 'existing' names no concept — answer 'existing:<concept id>'"]


def test_an_answer_everything_in_which_is_readable_reports_no_problem():
    answer = {"c0": {"value": "admit"}, "c1": {"value": "decline"},
              "c2": {"value": "existing:DecisionSupport"}}
    assert V.batch_problems(_card3()["context"]["candidates"], answer) == []
    assert len(V.plan(_card3(), answer, "steward@x")) == 3


def test_the_applier_raises_AnswerRejected_so_the_CARD_COMES_BACK():
    """It raised a plain ValueError, so the runner recorded a WRITE failure and redrove it on every
    restart — a decision only a person can change, retried forever. `AnswerRejected` is the typing that
    re-opens the card instead (T2.6), and it was built for the curator this afternoon and never applied
    here."""
    from lab.substrate import answer_appliers
    done = []

    async def call(calls):
        done.extend(n for n, _ in calls)
        return [{} for _ in calls]

    state = {"payload": _card3(),
             "answer": {"c0": {"value": "admit"}, "c1": {"value": "decline"}, "c2": {"value": "existing"}}}
    with pytest.raises(answer_appliers.AnswerRejected, match="Decision Support"):
        asyncio.run(V.apply(state, "steward@x", call=call))
    # ...and the readable verdicts were APPLIED before it asked again, so the person redoes one term
    assert SemanticTools.promote in done and SemanticTools.vocab_decline in done
