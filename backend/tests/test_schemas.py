import pytest
from pydantic import ValidationError

from sage import config
from sage.schemas.guide import GRADE_SCHEMA, STUDY_SECTION_SCHEMA, TOPIC_MAP_SCHEMA, GradeOut, StudySection, TopicMap
from sage.schemas.questions import TYPE_EXTRA_PROPS, generation_schema, parse_question, question_json_schema

from .samples import SAMPLES, sample


def walk_objects(schema):
    """Yield every object schema nested anywhere in `schema`."""
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            yield schema
        for v in schema.values():
            yield from walk_objects(v)
    elif isinstance(schema, list):
        for v in schema:
            yield from walk_objects(v)


UNSUPPORTED_KEYS = {"minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems", "multipleOf", "pattern"}


def walk_keys(schema):
    if isinstance(schema, dict):
        for k, v in schema.items():
            yield k
            yield from walk_keys(v)
    elif isinstance(schema, list):
        for v in schema:
            yield from walk_keys(v)


@pytest.mark.parametrize("schema", [generation_schema(), TOPIC_MAP_SCHEMA, GRADE_SCHEMA, STUDY_SECTION_SCHEMA])
def test_schemas_follow_structured_output_rules(schema):
    objects = list(walk_objects(schema))
    assert objects
    for o in objects:
        assert o["additionalProperties"] is False
        assert set(o["required"]) == set(o["properties"])
    assert not UNSUPPORTED_KEYS & set(walk_keys(schema))


def test_every_question_type_has_a_schema_and_sample():
    assert set(TYPE_EXTRA_PROPS) == set(config.QUESTION_TYPE_IDS)
    assert set(SAMPLES) == set(config.QUESTION_TYPE_IDS)
    assert len(generation_schema()["properties"]["questions"]["items"]["anyOf"]) == 13


@pytest.mark.parametrize("type_id", config.QUESTION_TYPE_IDS)
def test_sample_matches_json_schema_keys_and_parses(type_id):
    q = sample(type_id)
    assert set(q) == set(question_json_schema(type_id)["properties"])
    parsed = parse_question(q)
    assert parsed.type == type_id


@pytest.mark.parametrize("bad", [
    sample("multiple_choice", correct_index=4),
    sample("multiple_choice", options=["A", "A", "B"]),
    sample("multiple_choice", options=["A", "B"]),
    sample("select_all", correct_indices=[]),
    sample("select_all", correct_indices=[0, 0]),
    sample("select_all", correct_indices=[9]),
    sample("fill_blank", prompt="No blanks here"),
    sample("fill_blank", blanks=[{"accepted_answers": ["100"]}]),
    sample("fill_blank", blanks=[{"accepted_answers": [" "]}, {"accepted_answers": ["x"]}]),
    sample("matching", pairs=[{"left": "a", "right": "b"}]),
    sample("ordering", items=["only", "two"]),
    sample("short_response", rubric={"criteria": [], "model_answer": "x"}),
    sample("short_response", rubric={"criteria": [{"criterion": "c", "points": 0}], "model_answer": "x"}),
    sample("error_analysis", flawed_work="  "),
    sample("true_false", difficulty=6),
    sample("true_false", extra_field=1),
    {**sample("true_false"), "type": "essay"},
])
def test_invalid_questions_are_rejected(bad):
    with pytest.raises(ValidationError):
        parse_question(bad)


def test_topic_map_validation():
    ok = {"title": "T", "summary": "S", "subtopics": [{"name": "A", "description": "a"}, {"name": "B", "description": "b"}]}
    assert len(TopicMap.model_validate(ok).subtopics) == 2
    with pytest.raises(ValidationError):
        TopicMap.model_validate({**ok, "subtopics": ok["subtopics"][:1]})
    with pytest.raises(ValidationError):
        TopicMap.model_validate({**ok, "subtopics": [{"name": "A", "description": ""}, {"name": "a", "description": ""}]})


def test_grade_validation():
    base = {"score": 90, "verdict": "correct", "feedback": "f", "model_answer": "m", "misconception": "", "criteria_results": []}
    assert GradeOut.model_validate(base).score == 90
    with pytest.raises(ValidationError):
        GradeOut.model_validate({**base, "score": 120})
    with pytest.raises(ValidationError):
        GradeOut.model_validate({**base, "score": 30})  # 'correct' with a failing score
    with pytest.raises(ValidationError):
        GradeOut.model_validate({**base, "verdict": "incorrect", "score": 80})


def _section(**over):
    s = {
        "title": "T", "explanation": "E",
        "key_formulas": [{"latex": "E=mc^2", "description": "energy"}],
        "diagram": {"include": True, "kind": "flowchart", "mermaid": "flowchart TD\nA-->B", "caption": "c"},
        "chart": {"include": False, "chart_type": "line", "title": "", "x_label": "", "y_label": "", "series": [], "caption": ""},
        "worked_example": {"problem": "p", "steps": ["s1"], "answer": "a"},
        "common_mistakes": [{"mistake": "m", "why": "w", "fix": "f", "from_your_answers": True}],
        "practice_questions": [{"question": "q1", "answer": "a1"}, {"question": "q2", "answer": "a2"}],
    }
    s.update(over)
    return s


def test_study_section_requires_a_graphic_and_practice():
    StudySection.model_validate(_section())
    no_graphic = _section(diagram={"include": False, "kind": "other", "mermaid": "", "caption": ""})
    with pytest.raises(ValidationError):
        StudySection.model_validate(no_graphic)
    chart_only = _section(
        diagram={"include": False, "kind": "other", "mermaid": "", "caption": ""},
        chart={"include": True, "chart_type": "line", "title": "t", "x_label": "x", "y_label": "y",
               "series": [{"name": "s", "points": [{"label": "", "x": 0, "y": 1}]}], "caption": ""},
    )
    StudySection.model_validate(chart_only)
    with pytest.raises(ValidationError):
        StudySection.model_validate(_section(practice_questions=[{"question": "q", "answer": "a"}]))
