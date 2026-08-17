"""Overrides for the diagnoser regression suite.

These tests exercise the real diagnoser loop end-to-end, so the parent directory's autouse
diagnoser stub is disabled here and real credentials are required.
"""

import pytest

from app.config import get_settings

from .support import (
    ACCURACY_THRESHOLD,
    QUESTION_RELEVANCE_THRESHOLD,
    REASONING_QUALITY_THRESHOLD,
)


@pytest.fixture(autouse=True)
def stub_diagnoser() -> None:
    """No-op override of tests/conftest.py's autouse stub_diagnoser fixture."""


@pytest.fixture(autouse=True)
def stub_evaluator() -> None:
    """No-op override — this suite supplies its own hand-written evaluator findings.

    The stub would never be called anyway (the diagnoser is handed an EvaluationResult
    rather than computing one), but leaving the parent fixture active would suggest the
    evaluator is in the loop here. It deliberately is not: chaining the two services would
    make an evaluator regression and a diagnoser regression indistinguishable.
    """


@pytest.fixture(autouse=True)
def _require_llm_credentials() -> None:
    if not get_settings().llm_api_key:
        pytest.skip("LLM_API_KEY not set — this suite makes real Anthropic API calls")


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    """Print the scored metrics whether or not the assertions passed.

    Same reasoning as question_geval's: a passing assertion prints nothing, so a green run
    would otherwise say only that every metric cleared its bar, not by how much — and for
    the judged checks an exact 1.00 means the judge stopped discriminating, which looks
    identical to a healthy pass. Since a billed run is the only way to learn these numbers,
    always report them.

    Reads `score_all`'s cache rather than calling it, so it never triggers API calls of its
    own and stays silent when the suite was skipped.
    """
    from .support import score_all

    if score_all.cache_info().currsize == 0:
        return  # suite skipped — nothing was scored
    result = score_all()

    w = terminalreporter.write_line
    terminalreporter.write_sep("-", "diagnoser_geval metrics")
    w(f"cases:                {len(result.scores)}")
    w(f"accuracy:             {result.accuracy:.2f} (threshold {ACCURACY_THRESHOLD})")
    w(f"  hit preferred:      {result.preferred_rate:.2f} (reported, not asserted)")
    w(f"  by hop depth:       {result.accuracy_by_hops()}   # (correct, total)")
    w(f"forbidden diagnoses:  {len(result.forbidden_hits)} (must be 0)")
    w(f"invariant violations: {len(result.invariant_violations)} (must be 0)")
    w(
        f"question relevance:   {result.question_relevance_rate:.2f} "
        f"(threshold {QUESTION_RELEVANCE_THRESHOLD})"
    )
    w(
        f"reasoning grounded:   {result.reasoning_quality_rate:.2f} "
        f"(threshold {REASONING_QUALITY_THRESHOLD})"
    )

    recall = result.disclosure_recall
    w(
        f"outside-graph:        {len(result.spurious_disclosures)} spurious (must be 0), "
        f"recall {'n/a' if recall is None else f'{recall:.2f}'} (reported only)"
    )

    turns = [s.trace.turns_used for s in result.scores]
    forced = sum(s.trace.forced_final for s in result.scores)
    rejected = sum(len(s.trace.rejected_submissions) for s in result.scores)
    reused = sum(s.reused_existing_question for s in result.scores)
    w(f"turns used:           min {min(turns)}, max {max(turns)}, mean {sum(turns)/len(turns):.1f}")
    w(f"  forced final turn:  {forced} (hit the budget without converging)")
    w(f"  gate rejections:    {rejected} (certainty gate refused a submission)")
    w(f"reused existing q:    {reused}/{len(result.scores)} (rest generated a new one)")

    # Per-case detail: on a green run this is the only place the trajectory is visible.
    w("")
    w(f"{'case':50} {'hops':>4} {'turns':>5}  diagnosis")
    for s in result.scores:
        mark = "ok " if s.is_acceptable else "MISS"
        star = "*" if s.is_preferred else " "
        flag = "  <-- FORBIDDEN" if s.is_forbidden else ""
        # Judge verdicts belong in the table too: their aggregate can clear the threshold
        # while an individual case fails, and on a green run the failure messages never
        # print — so without this there is no way to see which case the judges rejected.
        notes = "".join(
            [
                "  [outside-graph]" if s.disclosed_outside_graph else "",
                "  [question not relevant]" if not s.question_relevant else "",
                "  [reasoning not grounded]" if not s.reasoning_grounded else "",
            ]
        )
        w(
            f"{mark}{star}{s.case.name:48} {s.case.hops_to_preferred:>4} "
            f"{s.trace.turns_used:>5}  {s.suspect_slug}{flag}{notes}"
        )
