"""Regression suite for evidence_finder against Case 3 — Storage Engines.

**Makes real, billed Anthropic API calls** (all `claude-haiku-4-5`: 11 positive scans, 6
negative scans, 7 edge scans, plus one judge call per returned quote and per summary). The
cheapest of the four billed suites — no Sonnet generation, no Opus judging. Skips entirely when
LLM_API_KEY is unset, so CI stays green.

    cd backend && set -a && source ../.env && set +a && .venv/bin/pytest tests/evidence_geval -v

Ordered by the design doc's failure ranking, not by the shape of the code: the zero-tolerance
invariants first, then the headline span check, then recall, then the two judged checks.
`score_case()` is cached, so every test below shares one pass over the API.
"""

from app.services import evidence_finder

from .support import (
    EXPLANATORY_THRESHOLD,
    FOUND_RECALL_THRESHOLD,
    SPAN_ACCURACY_THRESHOLD,
    SUMMARY_FAITHFUL_THRESHOLD,
    score_case,
)

# --- zero tolerance -------------------------------------------------------------------------


def test_no_evidence_is_invented_for_concepts_the_chapter_never_teaches() -> None:
    """Failure #2. A `found: true` here manufactures chapter provenance for an idea the
    chapter does not contain, and nothing downstream can tell it from the real thing.

    The negatives are adjacent rather than absurd — replication, partitioning, transactions and
    friends are all concepts in *other* cases of the same golden set — so a model matching on
    subject area rather than on content has something to fail on.
    """
    result = score_case()

    assert not result.false_positives, result.false_positive_message()


def test_every_raw_quote_is_verbatim_chapter_text() -> None:
    """Graded on `_propose_raw_evidence`, before the filter, deliberately.

    Post-filter this is 1.00 by construction and measures nothing. The seam shows what the
    model actually returned, so this asserts the prompt is holding rather than that the safety
    net is. `dropped_rate` in the terminal summary is the same signal as a trend.
    """
    result = score_case()

    assert not result.non_verbatim_raw, (
        "the model returned text that is not in the chapter (the verbatim filter caught it, so "
        "nothing leaked — but the prompt is no longer doing its job):\n"
        + "\n".join(f"  - {cid}: {q[:110]!r}" for cid, q in result.non_verbatim_raw)
    )


def test_no_edge_evidence_is_invented_for_unlinked_pairs() -> None:
    """The edge-side counterpart to the first test. This string would reach
    question_generator as a `prerequisite_link` passage — source-text justification for why one
    concept depends on another — so inventing one is the same class of failure."""
    result = score_case()

    assert not result.edge_false_positives, (
        "a justifying quote was returned for concept pairs the chapter never links:\n"
        + "\n".join(f"  - {p} -> {c}: {q[:110]!r}" for p, c, q in result.edge_false_positives)
    )
    assert not result.edge_non_verbatim, result.edge_non_verbatim


def test_the_quote_cap_holds() -> None:
    """Enforced in code as of the tier 0 work, so this is a guard against that enforcement
    being refactored away rather than a test of the model's compliance."""
    result = score_case()

    assert not result.over_cap, (
        f"concepts returned more than _MAX_QUOTES={evidence_finder._MAX_QUOTES}: {result.over_cap}"
    )


# --- the headline check ---------------------------------------------------------------------


def test_quotes_are_about_the_concept_they_were_requested_for() -> None:
    """Failure #1, and the reason this suite exists.

    A quote can be verbatim, contiguous, genuinely in the chapter — and about a *neighbour*.
    It then passes every gate the service has, and feeds question_generator exactly the
    neighbour-weighted evidence that `source_quotes` was built to stop. Nothing else checks it.

    Deterministic: each quote is located in the chapter and tested for containment in a region
    hand-labelled for its own concept (see golden.py). Regions are labelled generously, so a
    failure here means the quote is about something clearly different, not that it straddles a
    debatable boundary.
    """
    result = score_case()

    assert result.span_accuracy >= SPAN_ACCURACY_THRESHOLD, result.span_message()


# --- recall ---------------------------------------------------------------------------------


def test_evidence_is_found_for_concepts_the_chapter_does_teach() -> None:
    """The mild direction (failure #6): a miss leaves the reviewer with their own summary and a
    visible "could not find evidence" notice, which is recoverable. Bar is correspondingly
    loose — this is here to catch a scan that has stopped working, not to chase the last
    concept."""
    result = score_case()

    assert result.found_recall >= FOUND_RECALL_THRESHOLD, result.found_recall_message()


def test_edge_evidence_is_found_for_pairs_the_chapter_links() -> None:
    """Loose for the same reason: a missing edge quote lands on exactly the pre-feature
    behavior (empty evidence, skipped `prerequisite_link` passage)."""
    result = score_case()

    assert len(result.edge_misses) <= 1, (
        f"no justifying quote found for linked pairs: {result.edge_misses}"
    )


# --- judged ---------------------------------------------------------------------------------


def test_quotes_explain_their_concept_rather_than_naming_it() -> None:
    """Failure #3. A passage that mentions the term without teaching anything is verbatim,
    on-target, and still worthless — it burns one of the concept's evidence slots and gives
    question_generator nothing to write a question from."""
    result = score_case()

    assert result.explanatory_rate >= EXPLANATORY_THRESHOLD, result.judged_message(
        "explanatory", result.explanatory, EXPLANATORY_THRESHOLD
    )


def test_proposed_summaries_stay_within_their_quotes() -> None:
    """The service has a known route to overreach: a summary is written against the model's
    whole quote list, and quotes dropped as non-verbatim are removed afterwards, so a surviving
    summary can rest partly on text that was discarded. `find_evidence`'s own docstring
    acknowledges this and leans on human review; this measures how bad it gets."""
    result = score_case()

    assert result.summary_rate >= SUMMARY_FAITHFUL_THRESHOLD, result.judged_message(
        "summary supported", result.summaries, SUMMARY_FAITHFUL_THRESHOLD
    )
