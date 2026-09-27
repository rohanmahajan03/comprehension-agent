"""Overrides for the required-points suite.

Runs the real evaluator (so the parent directory's autouse stub is disabled here) and the
generator's model directly, so real credentials are required.
"""

import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def stub_evaluator() -> None:
    """No-op override of tests/conftest.py's autouse stub_evaluator fixture."""


@pytest.fixture(autouse=True)
def _require_llm_credentials() -> None:
    if not get_settings().llm_api_key:
        pytest.skip("LLM_API_KEY not set — this suite makes real Anthropic API calls")


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    """Print agreement and every question's generated points, on a green run too.

    The points are what a failure has to be read against — whether they over-required,
    under-required, or were sound and the evaluator erred — and a passing test prints
    nothing. Reads the caches only, so it makes no API calls and stays quiet when the
    suite was skipped.
    """
    from .support import collect_ruled_answers, generate_points, grade

    if grade.cache_info().currsize == 0:
        return
    answers = [a for a in collect_ruled_answers()]
    graded = [(a, grade(a.name)) for a in answers]

    def rate(rows: list) -> str:
        agree = sum(1 for a, r in rows if r.correct is a.expected_correct)
        return f"{agree}/{len(rows)}"

    terminalreporter.write_sep("-", "points_geval metrics")
    terminalreporter.write_line(f"agreement with rulings: {rate(graded)}")
    terminalreporter.write_line(f"  explicit rulings:     {rate([g for g in graded if g[0].explicit])}")
    # The two directions a bar can be wrong in, reported apart: a combined rate hides a
    # fix for one that breaks the other.
    terminalreporter.write_line(
        f"  ruled correct:        {rate([g for g in graded if g[0].expected_correct])}"
        "  (a miss = points over-require)"
    )
    terminalreporter.write_line(
        f"  ruled incorrect:      {rate([g for g in graded if not g[0].expected_correct])}"
        "  (a miss = points under-require)"
    )

    for question_id in dict.fromkeys(a.question_id for a in answers):
        rows = [g for g in graded if g[0].question_id == question_id]
        first = rows[0][0]
        terminalreporter.write_line(f"\n{first.prompt}  [{first.question_type}]  {rate(rows)}")
        for point in generate_points(question_id):
            terminalreporter.write_line(f"    - {point}")
        for a, r in rows:
            if r.correct is not a.expected_correct:
                tag = "explicit" if a.explicit else "label"
                terminalreporter.write_line(
                    f"  MISS ({tag}) {a.name}: ruled {a.expected_correct}, got {r.correct}"
                )
