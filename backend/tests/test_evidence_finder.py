"""Unit tests for evidence_finder's post-processing, against a fake Anthropic client.

Free and fast — no API key. Tier 0 of docs/specs/2026-09-15-evidence-finder-test-strategy.md.

**This closes a real gap rather than adding depth to a covered area.** Until this file existed,
`find_evidence`'s own body had never executed in any test: `tests/conftest.py`'s
`stub_evidence_finder` monkeypatches the whole function, and `test_graph_review.py` patches it
to raise. `text_match.verbatim_only()` was well covered, but the code that *calls* it — deciding
`found`, counting `dropped`, trimming to `_MAX_QUOTES`, clearing the summary — was not.

Scope is the logic wrapped around the LLM call, which is where the service's guarantees live.
Whether the model picks good passages is a question about the prompt, and belongs to the billed
`tests/evidence_geval` suite.
"""

import json
from types import SimpleNamespace

import pytest

from app.models import Concept
from app.services import evidence_finder

CHAPTER = """Log-structured merge-trees keep recent writes in an in-memory balanced tree
called a memtable. When the memtable grows past some threshold, it is written out to disk
as an SSTable file.

Compaction runs in the background, merging SSTables and discarding overwritten values.
A Bloom filter lets the engine skip an SSTable that certainly does not hold a given key."""

MEMTABLE = Concept(id="d:memtable", name="Memtable", summary="An in-memory balanced tree.")
SSTABLE = Concept(id="d:sstable", name="SSTable", summary="A sorted on-disk segment file.")

# Verbatim slices of CHAPTER, as the model is asked to return them.
Q_MEMTABLE = "Log-structured merge-trees keep recent writes in an in-memory balanced tree called a memtable."
Q_FLUSH = "When the memtable grows past some threshold, it is written out to disk as an SSTable file."
Q_COMPACTION = "Compaction runs in the background, merging SSTables and discarding overwritten values."
Q_BLOOM = "A Bloom filter lets the engine skip an SSTable that certainly does not hold a given key."
# Not in the chapter — the failure `verbatim_only` exists to discard.
PARAPHRASE = "A memtable is an in-memory tree that buffers recent writes before they hit disk."


@pytest.fixture(autouse=True)
def stub_evidence_finder() -> None:
    """Override `tests/conftest.py`'s autouse stub, which monkeypatches `find_evidence` and
    `find_edge_evidence` wholesale.

    Without this every assertion below would be testing conftest's sentence-matching stub
    instead of the service — and would *pass* for several of them, since the stub returns
    plausible-looking proposals. That is the same trap the billed suite has to avoid
    (docs/specs/2026-09-15-evidence-finder-test-strategy.md §3), and it is worth knowing it
    bites here first: an autouse stub silently makes its own service untestable everywhere
    downstream of it.
    """
    return None


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch):
    """Return a setter that pins what the next `_call` sees as the model's JSON reply.

    Patches `_client`, not `_call`, so the response-unwrapping (`content` → first text block →
    `json.loads`) is exercised too rather than skipped over.
    """

    def _set(payload: dict) -> None:
        def _create(**kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text=json.dumps(payload))]
            )

        monkeypatch.setattr(
            evidence_finder,
            "_client",
            lambda: SimpleNamespace(messages=SimpleNamespace(create=_create)),
        )

    return _set


class TestFindEvidence:
    def test_all_verbatim_quotes_are_kept(self, fake_llm) -> None:
        fake_llm({"found": True, "summary": "A memtable buffers writes.", "quotes": [Q_MEMTABLE, Q_FLUSH]})

        proposal = evidence_finder.find_evidence(CHAPTER, MEMTABLE)

        assert proposal.found is True
        assert proposal.quotes == [Q_MEMTABLE, Q_FLUSH]
        assert proposal.dropped == 0
        assert proposal.summary == "A memtable buffers writes."

    def test_a_paraphrase_is_dropped_and_counted(self, fake_llm) -> None:
        """The partial case: real quotes survive, the invented one is discarded, and `found`
        stays true because something genuine remains."""
        fake_llm({"found": True, "summary": "A memtable buffers writes.", "quotes": [Q_MEMTABLE, PARAPHRASE]})

        proposal = evidence_finder.find_evidence(CHAPTER, MEMTABLE)

        assert proposal.found is True
        assert proposal.quotes == [Q_MEMTABLE]
        assert proposal.dropped == 1

    def test_found_flips_to_false_when_every_quote_was_invented(self, fake_llm) -> None:
        """The recompute, and the subtlest guarantee this service makes: `found` is derived
        from what survives verification, never taken from the model. A proposal whose every
        quote was a paraphrase has found nothing, whatever it claimed — and the summary goes
        with them, since it was written against text that isn't in the chapter.

        `dropped` still reports the discards, which is exactly what lets the review UI say
        "the model paraphrased everything" rather than "the chapter doesn't cover this".
        """
        fake_llm({"found": True, "summary": "Confidently wrong.", "quotes": [PARAPHRASE]})

        proposal = evidence_finder.find_evidence(CHAPTER, MEMTABLE)

        assert proposal.found is False
        assert proposal.quotes == []
        assert proposal.summary == ""
        assert proposal.dropped == 1

    def test_an_honest_not_found_reports_nothing_dropped(self, fake_llm) -> None:
        """`dropped` means "the model returned text that isn't in the chapter". A model that
        correctly declines has discarded nothing, and conflating the two would make the
        prompt-health signal meaningless."""
        fake_llm({"found": False, "summary": "", "quotes": []})

        proposal = evidence_finder.find_evidence(CHAPTER, MEMTABLE)

        assert proposal.found is False
        assert proposal.dropped == 0

    def test_quotes_are_ignored_when_the_model_says_not_found(self, fake_llm) -> None:
        """A contradictory payload resolves toward `found: false` — the conservative
        direction, since the alternative is storing provenance the model just disclaimed."""
        fake_llm({"found": False, "summary": "", "quotes": [Q_MEMTABLE]})

        proposal = evidence_finder.find_evidence(CHAPTER, MEMTABLE)

        assert proposal.found is False
        assert proposal.quotes == []
        assert proposal.dropped == 0

    def test_duplicate_quotes_collapse(self, fake_llm) -> None:
        fake_llm({"found": True, "summary": "s", "quotes": [Q_MEMTABLE, f"  {Q_MEMTABLE} "]})

        assert evidence_finder.find_evidence(CHAPTER, MEMTABLE).quotes == [Q_MEMTABLE]

    def test_the_quote_cap_is_enforced_in_code(self, fake_llm) -> None:
        """Rule 6 asks for at most `_MAX_QUOTES`; this is the enforcement behind it. Every
        other invariant here is verified rather than requested, and an over-long list crowds
        the neighbour context out of question_generator's prompt."""
        fake_llm(
            {
                "found": True,
                "summary": "s",
                "quotes": [Q_MEMTABLE, Q_FLUSH, Q_COMPACTION, Q_BLOOM, Q_MEMTABLE[:60]],
            }
        )

        proposal = evidence_finder.find_evidence(CHAPTER, MEMTABLE)

        assert len(proposal.quotes) == evidence_finder._MAX_QUOTES
        assert proposal.quotes == [Q_MEMTABLE, Q_FLUSH, Q_COMPACTION, Q_BLOOM]

    def test_trimming_to_the_cap_is_not_counted_as_dropped(self, fake_llm) -> None:
        """`dropped` is prompt health — "the model invented text" — and a quote trimmed for
        being surplus was perfectly good. Counting it would blur the one signal a regression
        suite watches for prompt decay."""
        fake_llm(
            {
                "found": True,
                "summary": "s",
                "quotes": [Q_MEMTABLE, Q_FLUSH, Q_COMPACTION, Q_BLOOM, Q_MEMTABLE[:60]],
            }
        )

        assert evidence_finder.find_evidence(CHAPTER, MEMTABLE).dropped == 0

    def test_the_cap_counts_surviving_quotes_not_attempted_ones(self, fake_llm) -> None:
        """Applied after the verbatim filter, so padding with paraphrases can't squeeze real
        passages out of the list."""
        fake_llm(
            {
                "found": True,
                "summary": "s",
                "quotes": [PARAPHRASE, PARAPHRASE + "!", Q_MEMTABLE, Q_FLUSH],
            }
        )

        proposal = evidence_finder.find_evidence(CHAPTER, MEMTABLE)

        assert proposal.quotes == [Q_MEMTABLE, Q_FLUSH]
        assert proposal.dropped == 2

    def test_a_rewrapped_quote_survives(self, fake_llm) -> None:
        """The chapter wraps this sentence mid-clause; a model reproducing it joins the break
        with a space. That is the one difference the verbatim rule forgives, and the service
        has to inherit it rather than re-implementing a stricter check."""
        fake_llm({"found": True, "summary": "s", "quotes": [Q_MEMTABLE]})

        assert evidence_finder.find_evidence(CHAPTER, MEMTABLE).quotes == [Q_MEMTABLE]

    def test_summary_whitespace_is_trimmed(self, fake_llm) -> None:
        fake_llm({"found": True, "summary": "  A memtable buffers writes.\n", "quotes": [Q_MEMTABLE]})

        assert evidence_finder.find_evidence(CHAPTER, MEMTABLE).summary == "A memtable buffers writes."


class TestProposeRawEvidence:
    """The seam a regression suite grades: the model's answer *before* verification, which is
    the only place "quoted badly" and "found nothing" are still distinguishable."""

    def test_returns_the_model_payload_unfiltered(self, fake_llm) -> None:
        fake_llm({"found": True, "summary": "s", "quotes": [Q_MEMTABLE, PARAPHRASE]})

        raw = evidence_finder._propose_raw_evidence(CHAPTER, MEMTABLE)

        assert raw["quotes"] == [Q_MEMTABLE, PARAPHRASE], "the seam must not filter"
        assert raw["found"] is True


class TestFindEdgeEvidence:
    def test_a_verbatim_quote_is_returned(self, fake_llm) -> None:
        fake_llm({"found": True, "quote": Q_FLUSH})

        assert evidence_finder.find_edge_evidence(CHAPTER, SSTABLE, MEMTABLE) == Q_FLUSH

    def test_a_paraphrased_quote_becomes_none(self, fake_llm) -> None:
        """Same discard-don't-repair rule as find_evidence, and the stakes are the same: this
        string reaches question_generator as a `prerequisite_link` passage, i.e. as source-text
        provenance for why one concept depends on another."""
        fake_llm({"found": True, "quote": PARAPHRASE})

        assert evidence_finder.find_edge_evidence(CHAPTER, SSTABLE, MEMTABLE) is None

    def test_not_found_is_none(self, fake_llm) -> None:
        fake_llm({"found": False, "quote": ""})

        assert evidence_finder.find_edge_evidence(CHAPTER, SSTABLE, MEMTABLE) is None

    def test_an_empty_quote_with_found_true_is_none(self, fake_llm) -> None:
        """Substring-wise "" is in every chapter; as provenance it is nothing, and
        `source_passages()` would skip it anyway. Returning None keeps the caller on the
        single "no quote" path instead of storing an empty string twice over."""
        fake_llm({"found": True, "quote": "   "})

        assert evidence_finder.find_edge_evidence(CHAPTER, SSTABLE, MEMTABLE) is None
