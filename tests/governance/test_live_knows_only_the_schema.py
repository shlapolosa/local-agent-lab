"""The live view knows an event's SCHEMA and nothing else about it.

The point of the page is that a workflow can gain, lose or rename a step and the page needs no
change: it renders the rows the frame carries, labelled by what the WORKLOAD declared. The moment
this service names a step, an executor or a record field, that stops being true — the next step
somebody adds renders as an unlabelled id, or worse, renders under a name this file guessed.

So the schema is declared here (`FRAME_FIELDS`, `STEP_FIELDS`) and the CODE is scanned for
workload vocabulary. Docstrings are stripped first: explaining that `receive` appeared twice is
history, and prose that cannot change behaviour is not the thing being guarded against.
"""
import ast
import pathlib

import pytest

from lab.substrate.live import server

SOURCE = pathlib.Path(server.__file__)

#: Every key a frame and a step row carry. The page reads these and only these.
FRAME_FIELDS = {"run_id", "status", "subject", "elapsed", "error", "steps", "settled"}
STEP_FIELDS = {"name", "title", "derived", "status", "at", "elapsed", "error", "key",
               "produced", "artifacts"}

#: Workload vocabulary. Not a blocklist of everything — a sample of the words that would appear if
#: this page ever started knowing what a step MEANS.
WORKLOAD_WORDS = ("step_3", "step_5", "coverage_map", "criticality", "capabilit", "screening",
                  "validate_and_persist", "ask_criticality", "derive_design", "readiness",
                  "feasibility", "realisation", "ontology")


def _code_without_docstrings() -> str:
    """The module's source with every docstring removed — prose may explain the history."""
    tree = ast.parse(SOURCE.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


@pytest.mark.parametrize("word", WORKLOAD_WORDS)
def test_the_live_service_never_names_a_step_or_a_record_field(word):
    assert word not in _code_without_docstrings().lower(), (
        f"{SOURCE.name} names {word!r}. A step's meaning belongs to the workload that declares it; "
        f"this page renders what arrives, or adding a step becomes a change to this file.")


def test_a_step_row_carries_exactly_the_declared_schema():
    rows = server._steps([{"name": "anything-at-all", "status": "done", "ts": "t",
                           "attrs": {"title": "a label this file never heard of"}}])
    assert set(rows[0]) == STEP_FIELDS


def test_a_step_this_file_has_never_heard_of_renders_with_the_label_it_declared():
    """The whole requirement, as one assertion: a brand-new executor, no code change here."""
    rows = server._steps([{"name": "quantify_widgets", "status": "start", "ts": "t",
                           "attrs": {"title": "quantify the widgets"}}])
    assert rows[0]["title"] == "quantify the widgets" and rows[0]["name"] == "quantify_widgets"


def test_the_page_renders_the_label_the_frame_carried_and_composes_none_of_its_own():
    page = server._PAGE
    assert "s.title || s.name" in page, "the declared label leads, the id is the fallback"
