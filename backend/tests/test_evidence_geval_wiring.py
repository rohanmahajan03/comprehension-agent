"""Free smoke test for the billed tests/evidence_geval suite.

Same role as test_question_geval_wiring.py: that suite only runs with LLM_API_KEY set, so
nothing in the free run ever executes `score_case()` or the CaseResult properties it feeds, and
a name referenced only *inside* those functions resolves fine at import and blows up at call
time. This drives the whole path with fake clients so a wiring break costs 0.03s here instead
of a billed run.

It also pins the fixture invariants (span labels resolve, negatives are genuinely absent), which
is the part most likely to rot: they are validated at import of `golden.py`, and that import
only happens inside the billed suite otherwise.

Scope is deliberately narrow — that the code path executes and the checks report on well-formed
input. It says nothing about extraction quality; that is the real suite's job.
"""

import json
from types import SimpleNamespace

import pytest

from app.services import evidence_finder
from tests.evidence_geval import golden, support


@pytest.fixture(autouse=True)
def stub_evidence_finder() -> None:
    """Override the parent autouse stub — this drives the real service against a fake client."""
    return None


@pytest.fixture
def fake_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stand in for the scanner and both judges with well-formed, passing output.

    The scanner returns one genuinely on-target quote per concept, taken from that concept's own
    labelled region, so span accuracy comes out at 1.00 and every property is exercised on the
    happy path.
    """
    first_quote_by_concept = {
        cid: golden.NORM_SOURCE[regions[0].start : regions[0].end]
        for cid, regions in golden.SPANS.items()
    }

    def fake_scan(**kwargs: object) -> SimpleNamespace:
        payload = json.loads(kwargs["messages"][0]["content"])  # type: ignore[index]
        concept_id = payload.get("concept", {}).get("name") if "concept" in payload else None
        if concept_id is None:
            # An edge scan: claim the pair is unlinked, the conservative answer.
            return _response({"found": False, "quote": ""})
        slug = next(
            (cid for cid, label in golden.CONCEPT_LABELS.items() if label == concept_id), None
        )
        if slug is None:  # a negative fixture — must come back not-found
            return _response({"found": False, "summary": "", "quotes": []})
        return _response(
            {"found": True, "summary": f"{concept_id} summary.", "quotes": [first_quote_by_concept[slug]]}
        )

    def fake_judge(**kwargs: object) -> SimpleNamespace:
        system = str(kwargs.get("system", ""))
        key = "explanatory" if "explains a concept" in system else "supported"
        return _response({key: True, "reasoning": "fake judge"})

    monkeypatch.setattr(
        evidence_finder,
        "_client",
        lambda: SimpleNamespace(messages=SimpleNamespace(create=fake_scan)),
    )
    monkeypatch.setattr(
        support,
        "_judge_client",
        lambda: SimpleNamespace(messages=SimpleNamespace(create=fake_judge)),
    )


def _response(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(payload))])


def test_fixtures_validate_and_resolve() -> None:
    """golden.py asserts all of this at import; this makes it a named free test rather than an
    ImportError inside a billed run."""
    golden._validate()

    assert set(golden.SPANS) == {c.id for c in golden.CASE.concepts}
    assert all(regions for regions in golden.SPANS.values()), "a concept has no labelled region"
    for regions in golden.SPANS.values():
        for region in regions:
            assert 0 <= region.start < region.end <= len(golden.NORM_SOURCE)


def test_span_check_discriminates() -> None:
    """The headline check, on inputs whose right answer is known without any model.

    Worth pinning explicitly: if `is_on_target` ever returned True unconditionally the billed
    suite would report perfect span accuracy and measure nothing.
    """
    compaction_quote = "Compaction means throwing away duplicate keys in the log"

    assert golden.is_on_target("compaction", compaction_quote)
    assert not golden.is_on_target("hash_index", compaction_quote), (
        "a compaction sentence must not count as evidence for hash_index"
    )
    assert not golden.is_on_target("compaction", "Compaction discards stale values"), (
        "a paraphrase is not locatable in the chapter and cannot be on-target"
    )


def test_negatives_are_absent_from_the_chapter() -> None:
    """Per-chapter, not global — several of these are concepts in *other* golden cases, so
    reusing them against a different chapter would assert found: false for something that
    chapter teaches."""
    lowered = golden.NORM_SOURCE.lower()
    for slug, _, _ in golden.ABSENT:
        for marker in golden._ABSENCE_MARKERS[slug]:
            assert marker not in lowered, f"{slug} is not absent: {marker!r} is in the chapter"


def test_score_case_path_executes_and_every_check_reports(fake_clients: None) -> None:
    # __wrapped__ bypasses the lru_cache so a fake result is never served to a real run.
    result = support.score_case.__wrapped__()

    assert len(result.positives) == len(golden.CASE.concepts)
    assert not result.false_positives, "negatives were stubbed as not-found"
    assert not result.non_verbatim_raw
    assert not result.over_cap
    assert result.span_accuracy == 1.0
    assert result.found_recall == 1.0
    assert result.explanatory_rate == 1.0
    assert result.summary_rate == 1.0
    assert result.dropped_rate == 0.0
    # The message builders run only on failure, so exercise them here.
    assert result.span_message() and result.found_recall_message()
    assert result.judged_message("explanatory", result.explanatory, 0.7)


def test_edge_checks_report_on_stubbed_output(fake_clients: None) -> None:
    """The fake client calls every pair unlinked, so linked pairs must register as misses and
    unlinked ones must produce no false positives."""
    result = support.score_case.__wrapped__()

    assert len(result.edge_misses) == len(golden.LINKED_PAIRS)
    assert not result.edge_false_positives
    assert not result.edge_non_verbatim
