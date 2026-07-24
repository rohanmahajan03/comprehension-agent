"""Gap diagnosis: walk dependencies to find the root misunderstanding (pipeline 2, steps 3-5)."""

from app.models import Answer, Concept, DependencyGraph, DiagnosisResult, Question


def diagnose(
    concept: Concept,
    graph: DependencyGraph,
    question: Question,
    answer: Answer,
) -> DiagnosisResult:
    """Given a wrong answer on `concept`, find the prerequisite most likely at fault
    and produce a targeted question that probes it.

    # TODO: Replace with real logic — (1) look at concept.depends_on and the source
    # material, (2) call an LLM with the wrong answer + prerequisite summaries to
    # decide which prerequisite the misunderstanding most likely stems from, and
    # (3) generate a question that isolates that prerequisite. Repeated wrong
    # answers should recurse further down the dependency chain until the root gap
    # is found. The stub below just picks the first listed prerequisite (or the
    # concept itself if it has none).
    """
    by_id = {c.id: c for c in graph.concepts}
    suspect = next(
        (by_id[dep] for dep in concept.depends_on if dep in by_id),
        concept,
    )
    targeted_question = Question(
        id=f"{suspect.id}:diagnostic",
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
            f"[stub] The answer about “{concept.name}” was incorrect, and “{suspect.name}” "
            "is its first listed prerequisite — probing it to see if the gap is there."
        ),
        targeted_question=targeted_question,
    )
