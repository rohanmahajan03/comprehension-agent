"""Answer evaluation (pipeline 2, step 2)."""

from itertools import count

from app.models import Answer, EvaluationResult, Question

# Alternates correct/incorrect so the demo flow exercises both branches deterministically.
_call_counter = count()


def evaluate(question: Question, answer: Answer) -> EvaluationResult:
    """Grade `answer` against `question`, returning right/wrong and why.

    # TODO: Replace with real logic — call an LLM with the question prompt, the
    # expected_answer_notes, and the learner's answer text; return whether the
    # answer demonstrates understanding and a short explanation of what was
    # right or missing. The stub below just alternates correct/incorrect on each
    # call so the UI exercises both the "advance" and "diagnose" branches.
    """
    correct = next(_call_counter) % 2 == 0
    if correct:
        return EvaluationResult(
            correct=True,
            explanation=(
                "[stub] Marked correct: your answer touches the key idea in the "
                f"expected notes ({question.expected_answer_notes[:80]}…)."
            ),
        )
    return EvaluationResult(
        correct=False,
        explanation=(
            "[stub] Marked incorrect: your answer appears to miss the key idea in the "
            f"expected notes ({question.expected_answer_notes[:80]}…)."
        ),
    )
