"""Overrides for the override regression suite.

Runs the real evaluator (so the parent directory's autouse stub is disabled here), the
generator's model, and the triage classifier, so real credentials are required.
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
    _report_cases(terminalreporter)
    _report_triage(terminalreporter)


def _report_cases(terminalreporter: pytest.TerminalReporter) -> None:
    """Rates split the ways §6's gate reads them, on a green run too.

    Direction first — a misgrade still failing and an invalid override newly passing are
    opposite failures, and a combined rate lets a fix for one hide a break in the other.
    Then split, because only `holdout` is an honest number once anything has been tuned.
    Synthetic seeds are reported on their own line and never enter a rate. Reads the cache
    only, so it makes no API calls and stays quiet when the suite was skipped.
    """
    from .support import all_cases, grade, points_for

    if grade.cache_info().currsize == 0:
        return
    graded = [
        (c, mode, grade(c.id, mode)) for c in all_cases() for mode in c.modes
    ]

    def rate(rows: list) -> str:
        agree = sum(1 for c, _, r in rows if r.correct is c.expected_correct)
        return f"{agree}/{len(rows)}" if rows else "-"

    real = [g for g in graded if not g[0].synthetic]
    write = terminalreporter.write_line
    terminalreporter.write_sep("-", "override_geval metrics")
    write(f"{'':<42}{'tune':>8}{'holdout':>10}")
    for label, expected in (("misgrades flipped (want correct)", True),
                            ("invalid overrides held (want incorrect)", False)):
        rows = [g for g in real if g[0].expected_correct is expected]
        write(
            f"{label:<42}"
            f"{rate([g for g in rows if g[0].split == 'tune']):>8}"
            f"{rate([g for g in rows if g[0].split == 'holdout']):>10}"
        )
    synthetic = [g for g in graded if g[0].synthetic]
    if synthetic:
        write(f"synthetic seeds (excluded above): {rate(synthetic)}")

    for c, mode, r in graded:
        if r.correct is c.expected_correct:
            continue
        tag = "seed" if c.synthetic else c.split
        write(f"\nMISS [{tag}] {c.id} {c.category} → {c.component} ({mode}): "
              f"ruled {c.expected_correct}, got {r.correct}")
        write(f"  Q: {c.question_prompt}")
        for point in points_for(c, mode):
            write(f"    - {point}")
        write(f"  evaluator: {r.explanation}")


def _report_triage(terminalreporter: pytest.TerminalReporter) -> None:
    from .test_triage_calibration import calibration_results, proposal_for

    if proposal_for.cache_info().currsize == 0:
        return
    from tests.override_corpus.calibration import rates

    results = calibration_results()
    terminalreporter.write_sep("-", "triage calibration")
    for category, (hit, n) in sorted(rates(results).items()):
        terminalreporter.write_line(f"{category:<20} {hit}/{n}")
    for f, p in results:
        if p.category != f.expected:
            terminalreporter.write_line(f"  MISS {f.name}: expected {f.expected}, got "
                                        f"{p.category} — {p.rationale}")
