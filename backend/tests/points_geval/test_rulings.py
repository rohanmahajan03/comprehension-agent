"""One test per ruled answer: graded against generated required points, does the real
evaluator reach the ruled verdict? See support.py for the design."""

import pytest

from .rulings import VERDICTS
from .support import collect_ruled_answers, generate_points, grade


@pytest.mark.parametrize("name", list(VERDICTS))
def test_verdict_matches_ruling(name: str) -> None:
    answer = next(a for a in collect_ruled_answers() if a.name == name)
    result = grade(name)
    points = "\n".join(f"  - {p}" for p in generate_points(answer.question_id))
    assert result.correct is answer.expected_correct, (
        f"ruled correct={answer.expected_correct}, evaluator said {result.correct}.\n"
        f"generated points:\n{points}\n"
        f"evaluator: {result.explanation}"
    )
