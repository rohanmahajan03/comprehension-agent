"""Free smoke test for the billed tests/diagnoser_geval suite.

That suite only runs with LLM_API_KEY set, so nothing else in the free run ever executes
`score_all()`, the SuiteResult properties, or the failure-message builders. A plain import
check doesn't help: a name referenced only *inside* those functions resolves fine at import
and blows up at call time. That exact bug once cost a 14-minute billed run on
question_geval, which is why its equivalent smoke test exists — and why this one does.

Scope is deliberately narrow: it asserts the code path executes and the checks report on
well-formed input. It says nothing about diagnosis quality — that's the real suite's job.
"""

import json
import re
from types import SimpleNamespace
from typing import Any

import pytest

from app.services import diagnoser
from tests.diagnoser_geval import support


def _text_response(payload: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(payload))])


@pytest.fixture
def fake_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stand in for the orchestrator, its nested calls, and the suite's judges."""

    def fake_diagnoser_call(**kwargs: Any) -> SimpleNamespace:
        # The diagnoser uses one client for three jobs; dispatch the way the real API would.
        if "tools" not in kwargs:
            system = kwargs["system"]
            if "diagnostic question" in system:  # _generate_raw_question
                return _text_response(
                    {
                        "question": "A generated question probing the concept?",
                        "expected_answer": "A model answer long enough to be gradeable by "
                        "the evaluator downstream.",
                        "grounding": "some grounding",
                    }
                )
            return _text_response({"match_question_id": "", "reasoning": "no match"})

        # Orchestrator turn. Diagnose the concept under test itself, parsed out of the
        # opening prompt — always reachable and always has a q1, so every case yields a
        # well-formed result regardless of which case is running.
        opening = kwargs["messages"][0]["content"]
        concept_id = re.search(r"\(id: ([^)]+)\)", opening).group(1)
        return SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="submit_diagnosis",
                    id="tu_1",
                    input={
                        "suspected_gap_concept_id": concept_id,
                        "confidence": "high",
                        "reasoning": "Because of a specific thing the answer omitted.",
                        "evidence_basis": "The finding said X; the evidence says Y.",
                        "question_source": "storage",
                        "question_id": f"{concept_id}:q1",
                    },
                )
            ]
        )

    def fake_judge(**kwargs: Any) -> SimpleNamespace:
        return _text_response({"verdict": True, "reasoning": "fine"})

    monkeypatch.setattr(
        diagnoser, "_client", lambda: SimpleNamespace(messages=SimpleNamespace(create=fake_diagnoser_call))
    )
    monkeypatch.setattr(
        support, "_judge_client", lambda: SimpleNamespace(messages=SimpleNamespace(create=fake_judge))
    )


def test_score_all_path_executes_and_all_checks_report(fake_clients: None) -> None:
    # __wrapped__ bypasses score_all's lru_cache: caching this fake result would otherwise
    # be served to the real suite if both ever run in one process.
    result = support.score_all.__wrapped__()

    assert len(result.scores) == len(support.CASES)
    assert all(s.trace.turns_used >= 1 for s in result.scores)

    # Every metric and every message builder, including the ones only reached on failure.
    assert not result.invariant_violations, result.invariant_violations_message()
    assert 0.0 <= result.accuracy <= 1.0 and result.accuracy_message()
    assert 0.0 <= result.preferred_rate <= 1.0
    assert result.accuracy_by_hops()
    assert result.forbidden_message() is not None
    assert result.question_relevance_rate == 1.0 and result.question_relevance_message()
    assert result.reasoning_quality_rate == 1.0 and result.reasoning_quality_message()


def test_leak_detector_catches_a_restated_summary(fake_clients: None) -> None:
    """Tier 1's load-bearing invariant: a question must not hand over the answer."""
    result = support.score_all.__wrapped__()
    score = result.scores[0]
    suspect = next(
        c for c in result.graph.concepts if c.id == score.result.suspected_gap_concept_id
    )
    # Paraphrase-with-preamble, not an exact copy — the shape a real leak takes.
    score.result.targeted_question.prompt = f"Given that {suspect.summary} — explain it."

    violations = result.invariant_violations
    assert any("leaks the answer" in v for v in violations), violations


def test_reachability_check_catches_an_unrelated_diagnosis(fake_clients: None) -> None:
    """Diagnosing a concept the answered one doesn't depend on is always wrong."""
    result = support.score_all.__wrapped__()
    # write_ahead_log is not reachable from compaction (different branch of the graph).
    score = next(s for s in result.scores if s.case.answered_concept == "compaction")
    score.result.suspected_gap_concept_id = f"{score.case.answered_concept_id.split(':')[0]}:write_ahead_log"

    assert any("not reachable" in v for v in result.invariant_violations)
