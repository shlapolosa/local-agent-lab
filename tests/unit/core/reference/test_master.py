"""The human-readable master, and reading it back.

The round trip is the point. `derived_from = master_sha256` claims the agent-readable form came
FROM the master, and that is only true if the publisher parses the master rather than trusting a
second file somebody emitted alongside it.
"""
import pytest

from lab.core.reference.master import Master, MasterError, parse, render

HEADERS = ["ID", "Trigger", "Rule"]
ROWS = [["G09", "step.effect ∈ {external communication} ∧ step.authorisation ≠ per-action human",
         "Trust-sensitive outputs require explicit human confirmation."],
        ["G17", "step.input.freshness ∈ {dynamic, time-critical}",
         "No all-clear from missing, stale or unavailable grounding."]]
META = {"Artifact": "guardrails", "Version": "2026.09.1", "Owner": "Agent Council"}


def a_master(**kw):
    return render(title="Guardrail set", headers=HEADERS, rows=ROWS, meta=META, **kw)


# ---------------------------------------------------------------- the round trip

def test_a_master_round_trips():
    """The property the hash chain rests on."""
    back = parse(a_master())
    assert back.title == "Guardrail set"
    assert list(back.headers) == HEADERS
    assert [list(r) for r in back.rows] == ROWS
    assert back.meta["Version"] == "2026.09.1"


def test_rendering_is_deterministic():
    assert a_master() == a_master()


def test_a_pipe_inside_a_cell_survives_the_round_trip():
    """A cell containing `|` would otherwise end its column and silently shift every value after
    it into the wrong header."""
    rows = [["G99", "a | b | c", "still one rule"]]
    back = parse(render(title="T", headers=HEADERS, rows=rows))
    assert list(back.rows[0]) == ["G99", "a | b | c", "still one rule"]


def test_a_newline_inside_a_cell_becomes_a_space_rather_than_breaking_the_table():
    back = parse(render(title="T", headers=["A"], rows=[["two\nlines"]]))
    assert list(back.rows[0]) == ["two lines"]


def test_a_short_row_is_padded_to_the_header_width():
    back = parse(render(title="T", headers=HEADERS, rows=[["G01"]]))
    assert len(back.rows[0]) == len(HEADERS)


def test_prose_survives_alongside_a_table():
    back = parse(a_master(prose="These figures are illustrative of the structure."))
    assert "illustrative" in back.prose
    assert back.rows


def test_a_prose_only_master_round_trips_with_no_table():
    body = render(title="Tradeoff catalogue", headers=[], rows=[],
                  prose="## G23 versus at-least-once\n\nIdempotency plus a compensating action.")
    back = parse(body)
    assert back.is_table is False
    assert "compensating" in back.prose


# ---------------------------------------------------------------- what a reader sees

def test_a_master_opens_as_a_readable_document():
    """A citation's master_ref points here, so this is what a reviewer actually gets. A risk
    officer opening the criticality taxonomy should see a table, not JSON."""
    body = a_master()
    assert body.startswith("# Guardrail set")
    assert "**Owner:** Agent Council" in body
    assert "| ID | Trigger | Rule |" in body


def test_the_metadata_a_reader_needs_is_at_the_top():
    body = a_master()
    assert body.index("**Version:**") < body.index("| ID |")


# ---------------------------------------------------------------- refusals

def test_a_master_without_a_title_is_refused():
    with pytest.raises(MasterError):
        render(title="  ", headers=HEADERS, rows=ROWS)


@pytest.mark.parametrize("text", ["", "no heading here", "## not level one"])
def test_a_document_that_is_not_a_master_refuses(text):
    with pytest.raises(MasterError):
        parse(text)


def test_the_parsed_master_reports_whether_it_carries_rows():
    assert parse(a_master()).is_table is True
    assert parse(render(title="T", headers=[], rows=[], prose="just words")).is_table is False
    assert isinstance(parse(a_master()), Master)
