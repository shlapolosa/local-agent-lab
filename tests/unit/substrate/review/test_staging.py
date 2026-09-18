"""Admin replaces a reference artifact's master — validated, diffed, staged. Never published.

The corpus publisher holds the Ed25519 signing seed, deliberately kept out of `.env` and `LAB_ENV`
("it belongs on the publishing workstation only"). Putting it behind a web session would make the
thing that signs the corpus reachable by anyone who reaches the page. So the split is: the app does
the part that prevents a bad corpus — parse, derive, refuse, diff — and an operator does the part
that needs the key.

The validation is NOT re-implemented here. It is `derive.records` with the artifact's own
`key_fields`, which is the same function the publisher runs, so an upload that stages is an upload
that will publish.
"""
import pytest

from lab.substrate.review import staging

MASTER = """# Capability domains

| domain | covers |
| --- | --- |
| Business | capabilities, value streams |
| Semantic | ontology, glossary |
"""


def _stage(body=MASTER, artifact="capability-domains", actor="sme@doh.gov.ae", **kw):
    return staging.stage(artifact, body.encode(), actor=actor, store=kw.pop("store", {}), **kw)


def test_a_good_master_stages_with_its_record_count():
    out = _stage()
    assert out.artifact_id == "capability-domains" and out.records == 2


def test_the_validation_is_the_publishers_own_not_a_second_implementation():
    """A master that stages must be one that publishes. `derive.records` is the function the
    publisher runs; re-implementing the rules here would let the two drift, and the drift would only
    show at release."""
    import inspect
    assert "derive" in inspect.getsource(staging.stage)


def test_a_row_missing_the_natural_key_is_refused_by_name():
    bad = MASTER.replace("| Business | capabilities, value streams |", "|  | orphaned row |")
    with pytest.raises(staging.StagingError) as e:
        _stage(bad)
    assert "domain" in str(e.value)


def test_two_rows_sharing_a_key_are_refused():
    """Returning either silently is worse than failing — the publisher says so, and the app must
    not be a softer door into the same corpus."""
    dup = MASTER + "| Business | a second Business row |\n"
    with pytest.raises(staging.StagingError):
        _stage(dup)


def test_an_empty_master_is_refused_rather_than_staged_as_a_deletion():
    """An artifact that derives nothing would release as an empty register, and every consumer
    reading it whole would see 'nothing is relevant' rather than 'somebody uploaded a blank file'."""
    with pytest.raises(staging.StagingError):
        _stage("# Nothing here\n")


def test_an_unknown_artifact_is_refused_before_anything_is_parsed():
    with pytest.raises(staging.StagingError) as e:
        _stage(artifact="not-an-artifact")
    assert "not-an-artifact" in str(e.value)


# ---------------------------------------------------------------- the diff


def test_the_diff_says_what_would_change_not_merely_that_something_would():
    """Admin is approving a CHANGE, so the reviewable unit is the rows that differ. A count alone
    cannot be checked against intent."""
    released = {"Business": {"domain": "Business", "covers": "capabilities, value streams"},
                "Technology": {"domain": "Technology", "covers": "compute"}}
    out = _stage(store={}, released=released)
    assert [r["domain"] for r in out.added] == ["Semantic"]
    assert [r["domain"] for r in out.removed] == ["Technology"]
    assert out.changed == []


def test_a_changed_row_names_the_field_that_moved():
    released = {"Business": {"domain": "Business", "covers": "something else"},
                "Semantic": {"domain": "Semantic", "covers": "ontology, glossary"}}
    out = _stage(store={}, released=released)
    assert len(out.changed) == 1 and out.changed[0]["domain"] == "Business"
    assert "covers" in out.changed[0]["fields"]


def test_no_released_version_stages_everything_as_added():
    out = _stage(store={}, released={})
    assert len(out.added) == 2 and out.removed == [] and out.changed == []


# ---------------------------------------------------------------- what is kept


def test_staging_records_who_and_what_so_an_operator_is_not_taking_it_on_trust():
    store = {}
    _stage(store=store)
    [cand] = list(store.values())
    assert cand["actor"] == "sme@doh.gov.ae" and cand["artifact_id"] == "capability-domains"
    assert cand["records"] == 2 and cand["staged_at"] and cand["sha256"]


def test_staging_the_same_artifact_twice_replaces_the_candidate():
    """One candidate per artifact: an operator releasing "the staged one" must not have to choose
    between three, and the newest upload is what the admin meant."""
    store = {}
    _stage(store=store)
    _stage(MASTER.replace("ontology, glossary", "ontology"), store=store)
    assert len(store) == 1
    assert "ontology, glossary" not in list(store.values())[0]["master"]


def test_a_staged_candidate_is_never_a_published_one():
    """The whole point of the split: nothing here can write to the corpus, sign anything or reach a
    DSN. Checked on the IMPORTS rather than the text, because the docstrings necessarily discuss
    publishing and releasing — a substring scan would be satisfied by silence about the thing it is
    meant to prevent, which is the wrong way round."""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(staging))
    imported = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    for forbidden in ("psycopg", "lab.substrate.reference.publish", "lab.substrate.artifacts"):
        assert not any(m.startswith(forbidden) for m in imported), forbidden
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "Publisher" not in names and "signing_key" not in names
