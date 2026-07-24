"""Question generation, one set per concept node (pipeline 1, step 3)."""

from app.models import Concept, Question


def generate_questions(concept: Concept) -> list[Question]:
    """Generate a question set that probes understanding of `concept`.

    # TODO: Replace with real logic — call an LLM with the concept's name/summary
    # and the source chapter text to generate several questions of varying depth,
    # each with expected_answer_notes rich enough for the evaluator to grade against.
    # The stub below returns two templated questions per concept.
    """
    return [
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
