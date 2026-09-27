"""Unit tests for question_generator's pure logic — no LLM call, no API key.

`source_passages()` is what decides what a question can be grounded in, and until now the
only thing exercising it end-to-end was the billed `tests/question_geval` suite. These
cover the passage-assembly rules directly, in particular the one `Concept.source_quotes`
added (docs/specs/2026-09-13-concept-evidence-generation.md §5).
"""

from app.models import Concept, DependencyGraph
from app.services.question_generator import allowed_question_types, source_passages


def _graph(*concepts: Concept) -> tuple[Concept, dict[str, Concept], DependencyGraph]:
    graph = DependencyGraph(doc_id="d", concepts=list(concepts))
    return concepts[0], {c.id: c for c in concepts}, graph


def test_a_concept_with_no_quotes_and_no_neighbours_gets_only_its_summary() -> None:
    """The floor this feature exists to raise: a hand-added orphan concept reaches the
    generator with exactly one passage, which supports conceptual_correctness and not much
    else."""
    concept, by_id, graph = _graph(Concept(id="d:a", name="A", summary="A is a thing."))

    passages = source_passages(concept, by_id, graph)

    assert passages == [
        {"id": "s1", "role": "target_concept", "concept_name": "A", "text": "A is a thing."}
    ]


def test_source_quotes_become_separate_target_concept_passages() -> None:
    """Separate passages, not one blob folded into the summary: the model cites them
    individually by id, and `grounding` stays the verbatim join of the ids it cited."""
    concept, by_id, graph = _graph(
        Concept(
            id="d:a",
            name="A",
            summary="A is a thing.",
            source_quotes=["A works by doing X.", "A is used when Y."],
        )
    )

    passages = source_passages(concept, by_id, graph)

    assert [(p["id"], p["role"]) for p in passages] == [
        ("s1", "target_concept"),
        ("s2", "target_concept"),
        ("s3", "target_concept"),
    ]
    assert [p["text"] for p in passages[1:]] == ["A works by doing X.", "A is used when Y."]
    assert all(p["concept_name"] == "A" for p in passages)


def test_quotes_are_numbered_before_the_neighbour_passages() -> None:
    """Ids stay stable and contiguous across both sources, since the model cites by id and
    `_generate_raw_for_concept` looks each one up in the same list."""
    a = Concept(
        id="d:a",
        name="A",
        summary="A is a thing.",
        source_quotes=["A works by doing X."],
        depends_on=["d:b"],
        evidence={"d:b": "A builds on B."},
    )
    b = Concept(id="d:b", name="B", summary="B is another thing.")
    concept, by_id, graph = _graph(a, b)

    passages = source_passages(concept, by_id, graph)

    assert [(p["id"], p["role"]) for p in passages] == [
        ("s1", "target_concept"),
        ("s2", "target_concept"),
        ("s3", "prerequisite"),
        ("s4", "prerequisite_link"),
    ]


def test_an_empty_quote_is_skipped_like_an_empty_edge_evidence_entry() -> None:
    concept, by_id, graph = _graph(
        Concept(id="d:a", name="A", summary="A is a thing.", source_quotes=["", "Real quote."])
    )

    assert [p["text"] for p in source_passages(concept, by_id, graph)] == [
        "A is a thing.",
        "Real quote.",
    ]


_RELATIONAL = {"conceptual_distinction", "applied_reasoning"}


def test_thin_target_evidence_rules_out_the_relational_types() -> None:
    """Summary plus one justifying quote is thin: rich prerequisite passages don't count,
    since they are the neighbour's evidence, not the target's."""
    a = Concept(
        id="d:a", name="A", summary="A is a thing.",
        depends_on=["d:b"], evidence={"d:b": "A builds on B."},
    )
    b = Concept(id="d:b", name="B", summary="B is a long, detailed, well-explained thing. " * 20)
    concept, by_id, graph = _graph(a, b)

    types = allowed_question_types(source_passages(concept, by_id, graph))

    assert _RELATIONAL.isdisjoint(types)
    assert "conceptual_correctness" in types


def test_a_third_passage_of_its_own_offers_every_type() -> None:
    concept, by_id, graph = _graph(
        Concept(id="d:a", name="A", summary="A is a thing.",
                source_quotes=["A works by doing X.", "A is used when Y."])
    )

    types = allowed_question_types(source_passages(concept, by_id, graph))

    assert _RELATIONAL <= set(types)
