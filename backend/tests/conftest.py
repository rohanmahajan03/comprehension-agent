"""Shared test fixtures."""

from itertools import count

import pytest

from app.models import Answer, Concept, DependencyGraph, EvaluationResult, Question
from app.services import evaluator, graph_builder, question_generator

# Fixed sample graph shape used by the graph_builder stub: (slug, name, summary, depends_on slugs)
_SAMPLE_CONCEPTS: list[tuple[str, str, str, list[str]]] = [
    ("limits", "Limits", "The value a function approaches as its input approaches a point.", []),
    (
        "continuity",
        "Continuity",
        "A function is continuous when its limit at a point equals its value there.",
        ["limits"],
    ),
    (
        "derivatives",
        "Derivatives",
        "The instantaneous rate of change of a function, defined as a limit of difference quotients.",
        ["limits", "continuity"],
    ),
    (
        "chain-rule",
        "Chain Rule",
        "How to differentiate a composition of functions.",
        ["derivatives"],
    ),
    (
        "implicit-differentiation",
        "Implicit Differentiation",
        "Differentiating relations that are not solved for one variable, using the chain rule.",
        ["chain-rule"],
    ),
]


@pytest.fixture(autouse=True)
def stub_evaluator(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the real LLM call with a deterministic stub so tests never hit the API.

    Alternates correct/incorrect per call so both the "advance" and "diagnose"
    branches of the study-session loop get exercised, mirroring the old stub.
    """
    call_counter = count()

    def _fake_evaluate(question: Question, answer: Answer) -> EvaluationResult:
        correct = next(call_counter) % 2 == 0
        return EvaluationResult(
            correct=correct,
            explanation=f"[test stub] marked {'correct' if correct else 'incorrect'}",
        )

    monkeypatch.setattr(evaluator, "evaluate", _fake_evaluate)


@pytest.fixture(autouse=True)
def stub_graph_builder(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the real LLM call with a fixed calculus graph so tests never hit the API."""

    def _fake_build_graph(doc_id: str, text: str) -> DependencyGraph:
        concepts = [
            Concept(
                id=f"{doc_id}:{slug}",
                name=name,
                summary=summary,
                depends_on=[f"{doc_id}:{dep}" for dep in deps],
            )
            for slug, name, summary, deps in _SAMPLE_CONCEPTS
        ]
        return DependencyGraph(doc_id=doc_id, concepts=concepts)

    monkeypatch.setattr(graph_builder, "build_graph", _fake_build_graph)


@pytest.fixture(autouse=True)
def stub_question_generator(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the real LLM call with two templated questions per concept, set
    in place on each concept, so tests never hit the API.
    """

    def _fake_generate_questions(graph: DependencyGraph) -> None:
        for concept in graph.concepts:
            concept.questions = [
                Question(
                    id=f"{concept.id}:q1",
                    concept_id=concept.id,
                    prompt=f"In your own words, explain what “{concept.name}” means.",
                    expected_answer_notes=f"A correct answer restates the core idea: {concept.summary}",
                ),
                Question(
                    id=f"{concept.id}:q2",
                    concept_id=concept.id,
                    prompt=f"Give an example that illustrates “{concept.name}” and explain why it applies.",
                    expected_answer_notes=(
                        f"A correct answer gives a concrete example consistent with: {concept.summary}"
                    ),
                ),
            ]

    monkeypatch.setattr(question_generator, "generate_questions", _fake_generate_questions)
