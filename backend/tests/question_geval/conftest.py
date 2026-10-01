"""Overrides for the question_generator regression suite.

Unlike the rest of the test suite (see tests/conftest.py), these tests exercise the
real question_generator LLM call end-to-end (no judge model needed — see support.py
docstring for why), so the parent directory's autouse question_generator stub is
disabled here and real credentials are required.
"""

import pytest

from app.config import get_settings

from .support import (
    ANSWER_QUALITY_THRESHOLD,
    EVIDENCE_BASIS_THRESHOLD,
    TARGET_FOCUS_THRESHOLD,
    TYPE_RECALL_THRESHOLD,
)


@pytest.fixture(autouse=True)
def stub_question_generator() -> None:
    """No-op override of tests/conftest.py's autouse stub_question_generator fixture."""


@pytest.fixture(autouse=True)
def _require_llm_credentials() -> None:
    if not get_settings().llm_api_key:
        pytest.skip("LLM_API_KEY not set — this suite makes real Anthropic API calls")


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    """Print the scored metrics whether or not the assertions passed.

    A passing assertion prints nothing, so a green run used to tell you only that every
    metric cleared its threshold — not whether it cleared by a hair or perfectly. That
    matters most for the LLM-judged checks: a rate of exactly 1.00 is a signal the judge
    has stopped discriminating, which looks identical to a healthy pass otherwise. Since
    a billed run is the only way to learn these numbers, always report them.

    Reads `score_case`'s cache rather than calling it, so this never triggers API calls
    of its own and stays silent when the suite was skipped.
    """
    from .support import POINTS_BAR_JUDGMENTS, score_case

    if score_case.cache_info().currsize == 0:
        return  # suite skipped (no credentials) — nothing was scored
    result = score_case()

    total = len(result.evidence_basis_judgments)
    terminalreporter.write_sep("-", "question_geval metrics")
    terminalreporter.write_line(f"questions generated:  {total}")
    terminalreporter.write_line(
        f"type recall:          {result.type_recall:.2f} "
        f"(threshold {TYPE_RECALL_THRESHOLD}, {len(result.missed_types)} missed)"
    )
    terminalreporter.write_line(
        f"evidence basis:       {result.evidence_basis_rate:.2f} "
        f"(threshold {EVIDENCE_BASIS_THRESHOLD}, {len(result.ungrounded_questions)} ungrounded)"
    )
    terminalreporter.write_line(
        f"answer quality:       {result.answer_quality_rate:.2f} "
        f"(threshold {ANSWER_QUALITY_THRESHOLD}, {len(result.unanswered_questions)} flagged)"
    )
    terminalreporter.write_line(
        f"target focus:         {result.target_focus_rate:.2f} "
        f"(threshold {TARGET_FOCUS_THRESHOLD}, {len(result.off_target_questions)} off-target, "
        f"{len(result.target_focus_judgments)}/{total} scored)"
    )
    terminalreporter.write_line(
        f"deterministic checks: {len(result.grounding_violations)} grounding, "
        f"{len(result.expected_answer_violations)} expected-answer violations"
    )
    # Name what the judges rejected even on a green run: these are the questions worth
    # eyeballing to decide whether the generator or the judge is the thing that's wrong.
    for j in result.ungrounded_questions:
        terminalreporter.write_line(
            f"  ungrounded: {j.concept_id} [{j.question['type']}] {j.question['question'][:70]}…"
        )
    for j in result.unanswered_questions:
        terminalreporter.write_line(
            f"  weak answer: {j.concept_id} [{j.question['type']}]"
        )
    for j in result.off_target_questions:
        terminalreporter.write_line(
            f"  off-target: {j.concept_id} [{j.question['type']}] {j.question['question'][:70]}…"
        )

    # Check 7, report-only until the points judge is calibrated (see judge_case_points).
    if POINTS_BAR_JUDGMENTS:
        judged = [p.judgment for p in POINTS_BAR_JUDGMENTS]
        sound = sum(1 for j in judged if j.sound)
        over = sum(1 for j in judged if j.over_requires)
        under = sum(1 for j in judged if j.under_requires)
        terminalreporter.write_line(
            f"points bar:           {sound}/{len(judged)} sound, {over} over-require, "
            f"{under} under-require (unasserted)"
        )
        for p in POINTS_BAR_JUDGMENTS:
            for i in p.judgment.inessential:
                terminalreporter.write_line(
                    f"  inessential point: {p.concept_id} [{p.question['type']}] "
                    f"{p.question['required_points'][i][:70]}…"
                )
            if p.judgment.under_requires:
                missing = "; ".join(p.judgment.missing) or "(none named)"
                terminalreporter.write_line(
                    f"  bar too low: {p.concept_id} [{p.question['type']}] missing {missing[:90]}"
                )
