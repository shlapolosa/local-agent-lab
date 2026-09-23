"""A copilot must be able to LEARN the questions, and relearn them when they change.

Measured against the real M42 Microsoft Forms intake. Today `intake` reaches an agent as
`dict[str, dict[str, str]]` — an opaque bag — plus a prose description that names the groups in a
sentence and enumerates no label, no type, no choice, no required-ness. So an agent asked to
"gather the intake fields" invents its own labels, and the mapping it sends matches nothing the
corpus published. Nothing anywhere reports that: the API path has no equivalent of the CSV
parser's "no published field matches".

The questions must therefore be DISCOVERABLE and the discovery must be DERIVED, so that adding or
removing a field is a corpus publish and never an edit here. The published `intake-field-specs`
artifact is the single source: the review app's form, the CSV template and the agent's
conversation all become renderings of one list.
"""
import pytest

from lab.platform.contracts import PROCESSES, WorkflowTools

SPEC = PROCESSES["use_case_screening"]


def test_a_process_that_takes_a_questionnaire_offers_a_way_to_read_it():
    """The verb is generated from the spec like every other, so a new process with a mapping input
    gets it for free and one without never advertises it."""
    assert "fields" in WorkflowTools.verbs_for(SPEC)


def test_a_process_with_no_questionnaire_does_not_advertise_one():
    """`verbs_for` already drops `submit` for a continuation-only process. A tool that answers
    'this process has no questions' is worse than no tool: a grant could name it."""
    minutes = PROCESSES["transcript_to_minutes"]
    assert "fields" not in WorkflowTools.verbs_for(minutes)


def test_the_tool_name_follows_the_same_shape_as_the_others():
    assert SPEC.tool("fields") == "use_case_screening_fields"


def test_every_generated_verb_is_in_the_catalogue():
    """Otherwise the gateway grant cannot name it and the tool exists and is unreachable."""
    assert SPEC.tool("fields") in WorkflowTools.names()


def test_the_questionnaire_field_is_the_one_declared_on_the_spec():
    """Derived, not named in a second place: the tool serves whichever field carries the
    questionnaire, so renaming it is one edit."""
    assert SPEC.questionnaire == "intake"
    assert PROCESSES["transcript_to_minutes"].questionnaire is None


def test_the_questions_live_in_the_corpus_so_adding_one_is_a_publish():
    """The whole point: the field names the ARTIFACT that publishes its questions, so a new
    question changes the agent's interview, the review app's form and the CSV template at once,
    and changes no code anywhere."""
    assert SPEC.field("intake").questions == "intake-field-specs"


def test_a_field_that_is_not_a_questionnaire_names_no_artifact():
    minutes = PROCESSES["transcript_to_minutes"]
    assert all(not f.questions for f in minutes.inputs)


def test_the_rest_catalogue_points_at_the_questions_too():
    """A flow author reads the catalogue; an agent reads the tool. Both have to find the questions,
    and neither should have to know the artifact's name by heart."""
    from lab.substrate.mcp.workflow import rest
    import asyncio, json
    body = asyncio.run(rest._index(None)).body
    spec = next(p for p in json.loads(body)["processes"] if p["name"] == "use_case_screening")
    intake = next(f for f in spec["inputs"] if f["name"] == "intake")
    assert intake["questions"] == "intake-field-specs"
    assert intake["questions_tool"] == "use_case_screening_fields"


def test_a_field_with_no_questionnaire_says_nothing_about_one():
    from lab.substrate.mcp.workflow import rest
    import asyncio, json
    body = asyncio.run(rest._index(None)).body
    spec = next(p for p in json.loads(body)["processes"] if p["name"] == "use_case_screening")
    submitter = next(f for f in spec["inputs"] if f["name"] == "submitter")
    assert "questions" not in submitter


# ------------------------------------------------- the generated schema teaches the new kinds

def test_a_table_input_reaches_an_agent_as_a_real_row_schema():
    """`dict[str, dict[str, str]]` taught an agent nothing. A TABLE must arrive as an array of
    objects with NAMED, TYPED columns and its required ones marked, or the agent is back to
    guessing — which is the whole reason the kind exists."""
    from lab.platform.contracts import Column, InputField, InputKind
    from lab.substrate.mcp.workflow.server import annotation_of
    field = InputField("effort", InputKind.TABLE, "who does this today", required=False,
                       columns=(Column("role", InputKind.CHOICE, required=True,
                                       choices=("mid", "senior")),
                                Column("headcount", InputKind.NUMBER, required=True),
                                Column("notes", InputKind.CHOICE, choices=("a", "b"))))
    import pydantic
    model = pydantic.create_model("T", effort=(annotation_of(field), None))
    schema = model.model_json_schema()
    rows = schema["$defs"]["effort_row"] if "$defs" in schema else None
    assert rows, schema
    assert set(rows["properties"]) == {"role", "headcount", "notes"}
    assert rows["required"] == ["role", "headcount"]
    assert rows["properties"]["headcount"]["type"] == "number"
    assert rows["properties"]["role"]["enum"] == ["mid", "senior"]


def test_a_number_input_is_a_number_not_a_string():
    from lab.platform.contracts import InputField, InputKind
    from lab.substrate.mcp.workflow.server import ANNOTATION
    assert ANNOTATION[InputKind.NUMBER] is float
