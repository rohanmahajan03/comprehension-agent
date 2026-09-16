"""Fixtures for the billed evidence_finder suite.

Two jobs, both of which the suite is silently useless without — see the design doc's §3.
"""

import pytest

from app.config import get_settings

from .support import (
    EXPLANATORY_THRESHOLD,
    FOUND_RECALL_THRESHOLD,
    SPAN_ACCURACY_THRESHOLD,
    SUMMARY_FAITHFUL_THRESHOLD,
    score_case,
)


@pytest.fixture(autouse=True)
def stub_evidence_finder() -> None:
    """Override the parent autouse stub so these tests hit the real API.

    **This is the gotcha that would silently ruin the suite.** `tests/conftest.py` monkeypatches
    `find_evidence` and `find_edge_evidence` wholesale with a sentence matcher. Without this
    override every call here would be the stub, and the suite would pass while measuring
    nothing — worse than failing, because a green run would be taken as evidence the prompt
    works. Same pattern as the other three billed suites.
    """
    return None


@pytest.fixture(autouse=True)
def _require_api_key() -> None:
    if not get_settings().llm_api_key:
        pytest.skip("LLM_API_KEY not set — this suite makes real Anthropic API calls")


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:
    """Print every metric on a green run too, plus a per-concept table.

    A passing assertion prints nothing, and for the two judged checks an exact 1.00 would mean
    the judge had stopped discriminating — indistinguishable from a healthy pass without the
    number. Reads score_case's cache, so it costs nothing and stays quiet when the suite was
    skipped.
    """
    if score_case.cache_info().currsize == 0:
        return  # suite skipped (no credentials) — nothing was scored
    result = score_case()
    w = terminalreporter

    w.write_sep("=", "evidence_finder metrics")
    w.write_line(f"span accuracy    {result.span_accuracy:.2f}  (>= {SPAN_ACCURACY_THRESHOLD})")
    w.write_line(f"found recall     {result.found_recall:.2f}  (>= {FOUND_RECALL_THRESHOLD})")
    w.write_line(f"explanatory      {result.explanatory_rate:.2f}  (>= {EXPLANATORY_THRESHOLD})")
    w.write_line(f"summary supported{result.summary_rate:6.2f}  (>= {SUMMARY_FAITHFUL_THRESHOLD})")
    w.write_line(f"dropped rate     {result.dropped_rate:.2f}  (prompt health — no bar)")
    w.write_line(f"false positives  {len(result.false_positives)}     (zero tolerance)")
    w.write_line(f"non-verbatim raw {len(result.non_verbatim_raw)}     (zero tolerance)")
    w.write_line(
        f"edges            {len(result.edge_misses)} missed, "
        f"{len(result.edge_false_positives)} invented, {len(result.edge_non_verbatim)} non-verbatim"
    )

    w.write_line("")
    w.write_line(f"{'concept':<22} {'found':>5} {'quotes':>6} {'off':>4} {'drop':>4}  summary")
    for r in result.positives:
        w.write_line(
            f"{r.concept_id:<22} {str(r.found):>5} {len(r.quotes):>6} "
            f"{len(r.off_target):>4} {r.dropped:>4}  {r.summary[:44]}"
        )

    for label, items in (
        ("off-target quotes", result.off_target),
        ("non-verbatim raw quotes", result.non_verbatim_raw),
    ):
        if items:
            w.write_line("")
            w.write_line(f"{label}:")
            for cid, quote in items:
                w.write_line(f"  {cid}: {quote[:100]!r}")

    for label, judgments in (("not explanatory", result.explanatory), ("summary unsupported", result.summaries)):
        rejected = [j for j in judgments if not j.passed]
        if rejected:
            w.write_line("")
            w.write_line(f"{label}:")
            for j in rejected:
                w.write_line(f"  {j.concept_id}: {j.subject[:90]!r}")
                w.write_line(f"      {j.reasoning}")
