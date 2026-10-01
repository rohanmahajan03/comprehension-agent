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
    _report_verdicts(terminalreporter)
    _report_judge_calibration(terminalreporter)
    _report_judge_vs_observed(terminalreporter)


def _report_verdicts(terminalreporter: pytest.TerminalReporter) -> None:
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


def _report_judge_calibration(terminalreporter: pytest.TerminalReporter) -> None:
    """Print each calibration rate and every fixture the judge got wrong, on a green
    run too — at these fixture counts a passing rate can still hide a pattern."""
    from .calibration import FIXTURE_JUDGMENTS, calibration_fixtures, rate

    if not FIXTURE_JUDGMENTS:
        return
    fixtures = calibration_fixtures()
    terminalreporter.write_sep("-", "points judge calibration")
    for label, kinds in (
        ("ideal accepted:        ", {"ideal"}),
        ("over-requiring flagged:", {"padded", "bundled"}),
        ("under-requiring flagged:", {"thinned"}),
    ):
        if all(f.name in FIXTURE_JUDGMENTS for f in fixtures if f.kind in kinds):
            hits, total = rate(kinds)
            terminalreporter.write_line(f"{label} {hits}/{total}")
    for f in fixtures:
        j = FIXTURE_JUDGMENTS.get(f.name)
        if j is None or f.hit(j):
            continue
        flagged = ", ".join(str(i) for i in j.inessential) or "none"
        planted = "" if f.planted is None else f", planted {f.planted}"
        terminalreporter.write_line(
            f"  WRONG [{f.kind}] {f.name}: inessential {flagged}{planted}, "
            f"sufficient={j.sufficient}"
        )


def _report_judge_vs_observed(terminalreporter: pytest.TerminalReporter) -> None:
    """Set the judge's verdict on each question's generated points beside what those
    points did to that question's ruled answers.

    Observed over-requiring = a ruled-correct answer failed; under-requiring = a
    ruled-incorrect answer passed. Neither is clean ground truth — the evaluator can
    miss against sound points — so this is read, not asserted.
    """
    from .calibration import GENERATED_JUDGMENTS
    from .rulings import VERDICTS
    from .support import collect_ruled_answers, generate_points, grade

    if not GENERATED_JUDGMENTS:
        return
    # Only compare against grading when every answer was graded; grade() is cached, and
    # a partial cache would make the summary issue calls of its own.
    graded = grade.cache_info().currsize == len(VERDICTS)
    terminalreporter.write_sep("-", "points judge vs observed misses")
    terminalreporter.write_line("question                       judge(over/under)  observed(over/under)")

    def yn(flag: bool) -> str:
        return "Y" if flag else "-"

    for question_id, j in GENERATED_JUDGMENTS.items():
        observed = "    (not graded)"
        if graded:
            rows = [(a, grade(a.name)) for a in collect_ruled_answers() if a.question_id == question_id]
            over = any(a.expected_correct and not r.correct for a, r in rows)
            under = any(not a.expected_correct and r.correct for a, r in rows)
            observed = f"    {yn(over)} / {yn(under)}"
        terminalreporter.write_line(
            f"{question_id.split(':')[1]:<30} {yn(j.over_requires)} / {yn(j.under_requires)}"
            f"          {observed}"
        )
        points = generate_points(question_id)
        for i in j.inessential:
            terminalreporter.write_line(f"    inessential: {points[i]}\n      {j.checks[i].reasoning}")
        for idea in j.missing:
            terminalreporter.write_line(f"    missing: {idea}")
