"""Verbatim-quote checking — the one place this project decides whether a piece of text
really came from a source document.

Third home for a rule that had two copies: `tests/graph_geval`'s edge-evidence check and
`docs/specs/2026-09-13-concept-evidence-generation.md` §3's `_verbatim_only`. The rule is
load-bearing wherever a model reproduces source text (`evidence_finder.py`, `graph_builder`'s
edge evidence), so it lives here rather than being re-derived per caller.
"""

import re

_WHITESPACE = re.compile(r"\s+")


def normalize_ws(text: str) -> str:
    """Collapse every run of whitespace to one space and trim the ends.

    The only normalization applied before a quote is compared to its source. It forgives
    the differences a model reliably introduces when reproducing text out of a prompt —
    a rewrapped line, a doubled space, spacing around an em-dash — and nothing else.
    Wording, punctuation and elision all still have to match exactly, which is the point:
    a paraphrase must not pass.
    """
    return _WHITESPACE.sub(" ", text).strip()


def is_verbatim(quote: str, source: str) -> bool:
    """Whether `quote` is a contiguous run of `source`, whitespace-normalized.

    Contiguity is what rules out stitching: a "quote" assembled from two sentences that
    sit paragraphs apart is not a substring of the source, so it fails here even though
    both halves individually would pass. That only holds while quotes are checked whole —
    never split one up and check the pieces.
    """
    quote = normalize_ws(quote)
    return bool(quote) and quote in normalize_ws(source)


def verbatim_only(quotes: list[str], source: str) -> list[str]:
    """Drop any quote that isn't actually in `source`, preserving order and deduplicating.

    Discards rather than repairs. A paraphrase presented as a source quote is worse than
    no quote at all — it launders invention into provenance — and there is no safe way to
    guess which words the model changed. Callers report how many were dropped so the loss
    is visible rather than silent.
    """
    normalized_source = normalize_ws(source)
    kept: list[str] = []
    seen: set[str] = set()
    for quote in quotes:
        normalized = normalize_ws(quote)
        if not normalized or normalized not in normalized_source or normalized in seen:
            continue
        seen.add(normalized)
        kept.append(quote.strip())
    return kept
