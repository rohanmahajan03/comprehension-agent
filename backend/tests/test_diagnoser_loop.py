"""Loop mechanics for diagnoser.py — free, no API calls.

The billed tests/diagnoser_geval suite grades *what* the diagnoser concludes. This grades
*how the loop runs*: the turn budget, the forced final turn, the certainty gate, and the
error paths a model recovers from. All of it is deterministic given scripted responses, so
it belongs in the free run where it guards every commit rather than in the suite you pay
to execute.

These are also the mechanics most likely to break silently under refactor — nothing about
a broken turn budget or a certainty gate that stopped rejecting shows up in the returned
DiagnosisResult, which is exactly why diagnoser exposes `_diagnose_with_trace()`.
"""

from types import SimpleNamespace
from typing import Any

import pytest

from app.models import Answer, Concept, DependencyGraph, EvaluationResult, Question
from app.services import diagnoser


def tool_use(name: str, payload: dict[str, Any], block_id: str = "tu_1") -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", name=name, input=payload, id=block_id)


class FakeClient:
    """Returns scripted responses in order and records the request kwargs."""

    def __init__(self, scripted: list[list[SimpleNamespace]]) -> None:
        self._scripted = list(scripted)
        self.calls: list[dict[str, Any]] = []
        self.messages = self

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(content=self._scripted.pop(0))


def _graph() -> DependencyGraph:
    """A → B → C, with one pre-existing question on A and B."""
    return DependencyGraph(
        doc_id="doc1",
        concepts=[
            Concept(
                id="doc1:a", name="A", summary="A summary.",
                depends_on=["doc1:b"], evidence={"doc1:b": "B is needed for A."},
                questions=[Question(id="doc1:a:q1", concept_id="doc1:a",
                                    prompt="What is A?", expected_answer_notes="notes")],
            ),
            Concept(
                id="doc1:b", name="B", summary="B summary.",
                depends_on=["doc1:c"], evidence={"doc1:c": "C is needed for B."},
                questions=[Question(id="doc1:b:q1", concept_id="doc1:b",
                                    prompt="What is B?", expected_answer_notes="notes")],
            ),
            Concept(id="doc1:c", name="C", summary="C summary.", depends_on=[]),
        ],
    )


def _submit(**overrides: Any) -> dict[str, Any]:
    """A well-formed submit_diagnosis payload; override any field per test."""
    return {
        "suspected_gap_concept_id": "doc1:b",
        "confidence": "high",
        "reasoning": "The answer never showed B.",
        "evidence_basis": "Evaluator flagged B; evidence says 'B is needed for A.'",
        "question_source": "storage",
        "question_id": "doc1:b:q1",
    } | overrides


@pytest.fixture
def run(monkeypatch: pytest.MonkeyPatch):
    """Drive the real loop against scripted model responses."""
    graph = _graph()
    concept = graph.concepts[0]

    def _run(scripted: list[list[SimpleNamespace]]) -> tuple[Any, Any, FakeClient]:
        fake = FakeClient(scripted)
        monkeypatch.setattr(diagnoser, "_client", lambda: fake)
        # The judge behind pull_question_from_storage would otherwise be a real call.
        monkeypatch.setattr(
            diagnoser, "_find_matching_question", lambda candidates, focus: candidates[0] if candidates else None
        )
        result, trace = diagnoser._diagnose_with_trace(
            concept,
            graph,
            concept.questions[0],
            Answer(question_id="doc1:a:q1", text="a wrong answer"),
            EvaluationResult(correct=False, explanation="Missing the role of B."),
        )
        return result, trace, fake

    return _run


def _errors_sent(fake: FakeClient) -> list[str]:
    """is_error tool_result contents the loop fed back to the model.

    Every recorded call aliases the same `messages` list (the SDK serializes it at request
    time), so scan it once rather than once per call.
    """
    return [
        block["content"]
        for msg in fake.calls[-1]["messages"]
        if msg["role"] == "user" and isinstance(msg["content"], list)
        for block in msg["content"]
        if isinstance(block, dict) and block.get("is_error")
    ]


def test_investigates_then_submits(run) -> None:
    result, trace, fake = run([
        [tool_use("get_prereqs", {"concept_id": "doc1:a"})],
        [tool_use("pull_question_from_storage", {"concept_id": "doc1:b", "focus": "role of B"})],
        [tool_use("submit_diagnosis", _submit())],
    ])

    assert result.suspected_gap_concept_id == "doc1:b"
    assert result.targeted_question.id == "doc1:b:q1"
    assert trace.turns_used == 3
    assert trace.concepts_inspected == ["doc1:a"]
    assert not trace.rejected_submissions
    assert not trace.forced_final
    # High confidence is the expected path, so it isn't annotated onto the record.
    assert "confidence" not in result.reasoning.lower()


def test_certainty_gate_rejects_below_high_confidence(run) -> None:
    """The gate is code-enforced: the model cannot end the loop by asserting confidence."""
    result, trace, fake = run([
        [tool_use("submit_diagnosis", _submit(confidence="medium"))],
        [tool_use("get_prereqs", {"concept_id": "doc1:b"})],
        [tool_use("submit_diagnosis", _submit(
            suspected_gap_concept_id="doc1:c",
            question_source="generated",
            question_text="Explain the role C plays.",
            expected_answer="C precedes B, so B cannot be stated without it.",
            grounding="C summary.",
        ))],
    ])

    assert result.suspected_gap_concept_id == "doc1:c"
    assert len(trace.rejected_submissions) == 1
    assert trace.rejected_submissions[0]["confidence"] == "medium"
    assert any("confidence must be" in e for e in _errors_sent(fake))


def test_budget_exhaustion_forces_a_final_submission(run) -> None:
    """The loop always terminates with a real model judgment, never a code-side default."""
    result, trace, fake = run(
        [[tool_use("get_prereqs", {"concept_id": "doc1:a"})]] * (diagnoser._MAX_TURNS - 1)
        + [[tool_use("submit_diagnosis", _submit(
            confidence="low",
            question_source="generated",
            question_text="Describe B.",
            expected_answer="B consumes C and produces what A relies on.",
            grounding="B summary.",
        ))]]
    )

    assert trace.turns_used == diagnoser._MAX_TURNS
    assert trace.forced_final
    # Low confidence is accepted here, but recorded honestly on the diagnosis.
    assert "low confidence" in result.reasoning

    final_call = fake.calls[-1]
    assert final_call["tool_choice"] == {"type": "tool", "name": "submit_diagnosis"}
    assert [t["name"] for t in final_call["tools"]] == ["submit_diagnosis"]
    # Ordinary turns stay sequential so one tool call == one turn.
    assert fake.calls[0]["tool_choice"] == {"type": "any", "disable_parallel_tool_use": True}


def test_rejections_state_their_actual_reason(run) -> None:
    """A generic rejection would send the model off fixing the wrong thing."""
    _, trace, fake = run([
        [tool_use("submit_diagnosis", _submit(suspected_gap_concept_id="doc1:ghost"))],
        [tool_use("submit_diagnosis", _submit(question_id="doc1:a:q1"))],
        [tool_use("submit_diagnosis", _submit(question_source="generated"))],
        [tool_use("submit_diagnosis", _submit())],
    ])

    reasons = _errors_sent(fake)
    assert len(reasons) == 3, reasons
    assert "not a concept in this graph" in reasons[0]
    assert "not a question on" in reasons[1]
    assert "requires question_text" in reasons[2]
    assert not any("confidence must be" in r for r in reasons), (
        "confidence was high on all three — the gate should not be the stated reason"
    )
    assert len(trace.rejected_submissions) == 3


def test_unknown_concept_id_is_recoverable(run) -> None:
    _, trace, fake = run([
        [tool_use("get_prereqs", {"concept_id": "doc1:nope"})],
        [tool_use("submit_diagnosis", _submit())],
    ])

    errors = _errors_sent(fake)
    assert len(errors) == 1
    assert "Unknown concept id" in errors[0]
    assert trace.turns_used == 2


def test_outside_graph_diagnosis_is_disclosed(run) -> None:
    """The general-knowledge escape hatch must announce itself.

    When no prerequisite explains the deficiency the diagnoser may fall back to background
    knowledge the source material never taught — but `reasoning` is what the answer endpoint
    surfaces to the student, so the disclosure leads there rather than being implied. A
    student should know when they are being told something the chapter never claimed.
    """
    result, trace, _ = run([
        [tool_use("submit_diagnosis", _submit(
            gap_is_outside_graph=True,
            reasoning="The student is missing what a hash function is, which this chapter "
                      "never explains.",
        ))],
    ])

    assert trace.gap_outside_graph
    assert result.reasoning.startswith("Note:"), result.reasoning
    assert "general background knowledge" in result.reasoning
    # The original reasoning survives underneath the notice.
    assert "never explains" in result.reasoning


def test_ordinary_diagnosis_carries_no_disclosure(run) -> None:
    """The notice must not appear on the normal path, or it stops meaning anything."""
    result, trace, _ = run([[tool_use("submit_diagnosis", _submit())]])

    assert not trace.gap_outside_graph
    assert "Note:" not in result.reasoning
    assert "general background knowledge" not in result.reasoning


def test_general_knowledge_mode_relaxes_the_question_generator(monkeypatch) -> None:
    """`allow_general_knowledge` has to reach the nested generator, or the escape hatch
    produces a question still bound to evidence that doesn't cover the gap."""
    captured: dict[str, str] = {}

    def fake_create(**kwargs):
        captured["system"] = kwargs["system"]
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=(
                '{"question": "q?", "expected_answer": "a", "grounding": "g"}'
            ))]
        )

    monkeypatch.setattr(
        diagnoser, "_client", lambda: SimpleNamespace(messages=SimpleNamespace(create=fake_create))
    )
    concept = Concept(id="d:c", name="C", summary="C summary.")

    diagnoser._generate_raw_question(concept, "focus", allow_general_knowledge=False)
    assert "Override for this request" not in captured["system"]

    diagnoser._generate_raw_question(concept, "focus", allow_general_knowledge=True)
    assert "Override for this request" in captured["system"]
    assert "draw on general knowledge" in captured["system"]


def test_diagnostic_question_ids_increment(run) -> None:
    """A concept can be diagnosed more than once per session with a different gap each
    time; a fixed `:diagnostic` suffix would collide and the router dedupes by id, so it
    would keep serving the first question's rubric against the second question's prompt.
    """
    suspect = Concept(id="d:c", name="C", summary="s", questions=[])
    assert diagnoser._next_diagnostic_id(suspect) == "d:c:diagnostic1"

    suspect.questions.append(
        Question(id="d:c:diagnostic1", concept_id="d:c", prompt="p", expected_answer_notes="n")
    )
    assert diagnoser._next_diagnostic_id(suspect) == "d:c:diagnostic2"
