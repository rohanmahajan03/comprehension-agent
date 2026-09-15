"""Shared test fixtures."""

import re
from itertools import count

import pytest

from app.models import (
    Answer,
    Concept,
    DependencyGraph,
    DiagnosisResult,
    EvaluationResult,
    EvidenceProposal,
    Question,
)
from app.services import (
    diagnoser,
    evaluator,
    evidence_finder,
    graph_builder,
    question_generator,
)

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


@pytest.fixture(autouse=True)
def stub_diagnoser(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the real tool-calling loop with the old deterministic stub so tests never hit
    the API: pick the concept's first listed prerequisite (or the concept itself if it has
    none) and probe it with a templated question.
    """

    def _fake_diagnose(
        concept: Concept,
        graph: DependencyGraph,
        question: Question,
        answer: Answer,
        evaluation: EvaluationResult,
    ) -> DiagnosisResult:
        by_id = {c.id: c for c in graph.concepts}
        suspect = next((by_id[dep] for dep in concept.depends_on if dep in by_id), concept)
        targeted_question = Question(
            id=f"{suspect.id}:diagnostic{sum(1 for q in suspect.questions if ':diagnostic' in q.id) + 1}",
            concept_id=suspect.id,
            prompt=(
                f"Let's check a prerequisite. In your own words, what does “{suspect.name}” "
                "mean, and why does it matter here?"
            ),
            expected_answer_notes=f"A correct answer restates the core idea: {suspect.summary}",
        )
        return DiagnosisResult(
            suspected_gap_concept_id=suspect.id,
            reasoning=(
                f"[test stub] The answer about “{concept.name}” was incorrect, and "
                f"“{suspect.name}” is its first listed prerequisite — probing it to see if the "
                "gap is there."
            ),
            targeted_question=targeted_question,
        )

    monkeypatch.setattr(diagnoser, "diagnose", _fake_diagnose)


# One sentence of chapter text, punctuation included, as a verbatim slice of the original —
# `strip()` only trims the ends, so what comes back is still a contiguous run of the source
# and passes the real `text_match.verbatim_only()` the stubs below hand it to.
_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]?")


def _sentences(text: str) -> list[str]:
    return [m.group().strip() for m in _SENTENCE_RE.finditer(text) if m.group().strip()]


@pytest.fixture(autouse=True)
def stub_evidence_finder(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the chapter re-scan with a deterministic keyword match so tests never hit
    the API: a sentence counts as evidence for a concept when it mentions that concept by
    name, and as evidence for an edge when it mentions both concepts.

    Crude on purpose, but it exercises the real branch structure rather than hard-coding an
    outcome — the `found` / not-found split follows from the chapter text a test uploads.
    conftest's stub chapter ("A sample chapter about calculus.") names no concept, so the
    default everywhere is `found: False`, which is also the behavior that predates this
    feature.
    """

    def _fake_find_evidence(chapter_text: str, concept: Concept) -> EvidenceProposal:
        hits = [s for s in _sentences(chapter_text) if concept.name.lower() in s.lower()][:2]
        if not hits:
            return EvidenceProposal(found=False)
        return EvidenceProposal(
            found=True,
            summary=f"[test stub] Chapter-grounded summary of {concept.name}.",
            quotes=hits,
        )

    def _fake_find_edge_evidence(
        chapter_text: str, concept: Concept, prereq: Concept
    ) -> str | None:
        names = (concept.name.lower(), prereq.name.lower())
        return next(
            (s for s in _sentences(chapter_text) if all(n in s.lower() for n in names)), None
        )

    monkeypatch.setattr(evidence_finder, "find_evidence", _fake_find_evidence)
    monkeypatch.setattr(evidence_finder, "find_edge_evidence", _fake_find_edge_evidence)
