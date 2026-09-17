"""Free smoke test for the billed tests/question_geval suite.

That suite only runs with LLM_API_KEY set, so nothing else in the free test run ever
executes `score_case()` or the CaseResult properties it feeds. A plain import check
doesn't help either: a name that's only referenced *inside* those functions resolves
fine at import time and blows up at call time. This drives the whole path with fake
clients so a wiring break costs a second here instead of a ~14-minute billed run.

Scope is deliberately narrow: it asserts the code path executes and the checks report
on well-formed input. It says nothing about generation quality — that's the real
suite's job.
"""

import json
from types import SimpleNamespace

import pytest

from app.services import question_generator
from tests.question_geval import support


def _fake_response(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(payload))])


@pytest.fixture
def fake_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stand in for both the generator and the judge, with well-formed output."""

    def fake_generate(**kwargs: object) -> SimpleNamespace:
        # Cite the target concept's own passage, which every concept has.
        return _fake_response(
            {
                "concept_id": "x",
                "questions": [
                    {
                        "type": "conceptual_correctness",
                        "question": "What is it?",
                        "expected_answer": "A sufficiently long model answer that states "
                        "the substance of the concept in the student's own voice.",
                        "source_ids": ["s1"],
                    }
                ],
            }
        )

    def fake_judge(**kwargs: object) -> SimpleNamespace:
        # Superset of all three judge schemas; each caller reads only its own key.
        return _fake_response(
            {
                "grounded": True,
                "answers_question": True,
                "on_target": True,
                "reasoning": "fine",
            }
        )

    monkeypatch.setattr(
        question_generator,
        "_client",
        lambda: SimpleNamespace(messages=SimpleNamespace(create=fake_generate)),
    )
    monkeypatch.setattr(
        support,
        "_judge_client",
        lambda: SimpleNamespace(messages=SimpleNamespace(create=fake_judge)),
    )


def test_score_case_path_executes_and_all_checks_report(fake_clients: None) -> None:
    # __wrapped__ bypasses score_case's lru_cache: caching this fake result would
    # otherwise be served to the real suite if both ever run in one process.
    result = support.score_case.__wrapped__()

    assert result.raw_by_concept, "no concepts scored"
    assert result.passages_by_concept.keys() == result.raw_by_concept.keys()

    # Every check's code path, including the message builders used only on failure.
    assert not result.grounding_violations, result.grounding_violations_message()
    assert not result.expected_answer_violations, result.expected_answer_violations_message()
    assert result.type_recall >= 0.0 and result.missed_types_message()
    assert result.evidence_basis_rate == 1.0 and result.evidence_basis_message()
    assert result.answer_quality_rate == 1.0 and result.answer_quality_message()
    assert result.target_focus_rate == 1.0 and result.target_focus_message()
    # Target focus only scores concepts that were sent a neighbour, so this must be a
    # strict subset of the questions generated — if it ever equals the full set, the
    # "nothing to drift onto" skip has stopped working.
    assert 0 < len(result.target_focus_judgments) < len(result.evidence_basis_judgments)


def test_grounding_check_catches_model_typed_text(fake_clients: None) -> None:
    """The standing guard: `grounding` must stay a verbatim join of cited passages."""
    result = support.score_case.__wrapped__()
    concept_id = next(iter(result.raw_by_concept))
    result.raw_by_concept[concept_id][0]["grounding"] = "text the model typed itself"

    violations = result.grounding_violations
    assert any("not the verbatim join" in v for v in violations), violations


# --- the stage 0 premise probe (tests/question_geval/probe.py) ---
#
# The probe is a manual tool, so a typo in it surfaces the moment you run it. Its *fixtures*
# are the part worth guarding for free: THICKENING's quotes are asserted verbatim against the
# Case 3 source text at import, and that assertion is the thing that silently starts mattering
# when someone edits graph_golden_set.md. Catching it here costs milliseconds; catching it by
# running the probe costs a billed run that then measures the effect of invented evidence.


def test_probe_fixtures_are_verbatim_and_cover_every_drifting_concept() -> None:
    """Importing the module runs `_check_fixtures()`; this pins that it actually ran."""
    from tests.question_geval import probe

    probe._check_fixtures()  # explicit, so the assertion is this test's failure, not an ImportError
    assert set(probe.DRIFTING) <= set(probe.THICKENING)


def test_probe_thickens_only_the_target_concept(fake_clients: None) -> None:
    """The isolation that makes a null result meaningful: if neighbours were thickened too,
    an unchanged drift rate would be explained by the imbalance being unchanged rather than by
    the hypothesis being wrong."""
    from tests.question_geval import probe

    graph = probe._graph_with_quotes("write_ahead_log")
    with_quotes = {c.id for c in graph.concepts if c.source_quotes}

    assert with_quotes == {"case3:write_ahead_log"}
    assert probe._graph_with_quotes(None) and not any(
        c.source_quotes for c in probe._graph_with_quotes(None).concepts
    )


def test_probe_variant_path_executes(fake_clients: None) -> None:
    """Drives _run_variant end to end against the fake clients, so a name referenced only
    inside it fails in 0.03s rather than after the first real generation call."""
    from tests.question_geval import probe

    slug = "write_ahead_log"
    baseline = probe._run_variant("baseline", probe._graph_with_quotes(None), slug)
    thickened = probe._run_variant("thickened", probe._graph_with_quotes(slug), slug)

    assert baseline.questions and thickened.questions
    assert len(baseline.on_target) == len(baseline.questions) == len(baseline.grounded)
    # The comparison the probe exists to make has to be non-trivial on the evidence side.
    assert thickened.target_passages > baseline.target_passages
    assert thickened.target_chars > baseline.target_chars
    assert 0.0 <= baseline.focus_rate <= 1.0
    probe._print_variant(thickened)  # the formatter, including its strict zip
