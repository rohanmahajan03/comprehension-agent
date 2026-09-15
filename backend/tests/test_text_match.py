"""Unit tests for the verbatim-quote rule (app/services/text_match.py).

Free and fast — pure string logic, no API key. This is the check standing between
`evidence_finder`'s model output and a `source_quotes` field the rest of the pipeline
treats as chapter text, so the interesting cases are the near-misses: text that looks like
the source and isn't.
"""

from app.services.text_match import is_verbatim, normalize_ws, verbatim_only

CHAPTER = """Log-structured merge-trees keep recent writes in an in-memory balanced tree
called a memtable. When the memtable grows past some threshold — a few megabytes is
typical — it is written out to disk as an SSTable file.

Compaction runs in the background, merging SSTables and discarding overwritten values.
A Bloom filter lets the engine skip an SSTable that certainly does not hold a given key."""


class TestNormalizeWs:
    def test_collapses_runs_of_whitespace(self) -> None:
        assert normalize_ws("a\n\n  b\tc ") == "a b c"

    def test_leaves_wording_and_punctuation_alone(self) -> None:
        # The forgiveness stops at whitespace, deliberately: an em-dash swapped for a
        # hyphen is exactly the corruption this project has seen models produce.
        assert normalize_ws("a — b") != normalize_ws("a - b")


class TestIsVerbatim:
    def test_exact_substring_passes(self) -> None:
        assert is_verbatim("Compaction runs in the background", CHAPTER)

    def test_a_rewrapped_line_passes(self) -> None:
        """The line break falls mid-sentence in the chapter; a model reproducing the
        passage joins it with a space. Same text, and the only difference this forgives."""
        assert is_verbatim(
            "keep recent writes in an in-memory balanced tree called a memtable", CHAPTER
        )

    def test_an_em_dash_clause_survives_the_line_break_inside_it(self) -> None:
        assert is_verbatim("past some threshold — a few megabytes is typical — it is", CHAPTER)

    def test_a_paraphrase_fails(self) -> None:
        assert not is_verbatim("Compaction runs in the background and merges SSTables.", CHAPTER)

    def test_a_dropped_middle_clause_fails(self) -> None:
        """The specific corruption `write_amplification` reproduced across live runs: the
        sentence's outer words are right and a clause in the middle is gone."""
        assert not is_verbatim("When the memtable grows past some threshold it is", CHAPTER)

    def test_an_em_dash_replaced_by_a_hyphen_fails(self) -> None:
        assert not is_verbatim("past some threshold - a few megabytes is typical", CHAPTER)

    def test_the_empty_string_is_not_a_quote(self) -> None:
        # Substring-wise "" is in everything; as provenance it is nothing.
        assert not is_verbatim("   ", CHAPTER)


class TestVerbatimOnly:
    def test_keeps_the_real_quotes_and_drops_the_rest(self) -> None:
        kept = verbatim_only(
            [
                "Compaction runs in the background",
                "Compaction happens periodically in the background",  # paraphrase
                "A Bloom filter lets the engine skip an SSTable",
            ],
            CHAPTER,
        )
        assert kept == [
            "Compaction runs in the background",
            "A Bloom filter lets the engine skip an SSTable",
        ]

    def test_a_quote_stitched_from_two_distant_sentences_is_dropped(self) -> None:
        """Both halves are verbatim; the join never appears in the chapter. This is why
        quotes are checked whole and never split up first."""
        stitched = (
            "Compaction runs in the background, merging SSTables. "
            "A Bloom filter lets the engine skip an SSTable"
        )
        assert verbatim_only([stitched], CHAPTER) == []

    def test_duplicates_collapse(self) -> None:
        quote = "Compaction runs in the background"
        assert verbatim_only([quote, f"  {quote}  "], CHAPTER) == [quote]

    def test_order_is_preserved(self) -> None:
        kept = verbatim_only(["A Bloom filter lets", "Compaction runs"], CHAPTER)
        assert kept == ["A Bloom filter lets", "Compaction runs"]
