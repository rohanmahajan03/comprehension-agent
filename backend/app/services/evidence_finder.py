"""Targeted chapter re-scan for one concept's own evidence (pipeline 1, graph review).

Design doc: docs/specs/2026-09-13-concept-evidence-generation.md.

A concept a reviewer adds by hand reaches `question_generator` with exactly one evidence
passage — the sentence they typed — while an extracted concept arrives with a chapter-drawn
summary plus the verbatim quote justifying each of its dependencies. Since rules 1 and 4 of
the generator's prompt only permit questions the evidence *fully* supports, that one
sentence caps a hand-added concept at a question or two where an extracted one gets four.
This service closes the gap by going back to the chapter on that concept's behalf.

Extraction, not judgment — the same job `graph_builder` already does well, narrowed to a
single concept, hence the same model and the same `temperature=0`.

**Verbatim fidelity is verified here, not asked for.** `question_generator` spent three
rounds of prompt-strengthening failing to stop the model corrupting passages it retyped,
and only became reliable once the model stopped retyping them (citing ids instead, assembled
in code). That trick is unavailable here: this pass has to pull text *out* of a document, so
the model necessarily reproduces it. The mitigation is `text_match.verbatim_only()` on the
way out — a quote that isn't in the chapter is discarded, never repaired, and the count of
discards is reported so the loss is visible.
"""

import json
from functools import lru_cache
from typing import TypedDict

import anthropic

from app.config import get_settings
from app.models import Concept, EvidenceProposal
from app.services.text_match import verbatim_only


class RawEvidenceProposal(TypedDict):
    """The model's answer before verbatim verification — the internal seam, same pattern as
    `graph_builder._extract_raw_graph()` and `question_generator._generate_raw_for_concept()`,
    so a future regression suite can grade the proposal before it is folded into a
    `Concept`. Not stable public API.
    """

    found: bool
    summary: str
    quotes: list[str]


_MODEL = "claude-haiku-4-5"

# A ceiling on how much of the chapter one concept can claim. Four explanatory passages is
# already more target evidence than any extracted concept has today; past that the model
# starts padding with passages that merely mention the term, which rule 2 exists to exclude.
#
# Asked for in the prompt (rule 6) *and* enforced in code below. Every other invariant in this
# service is verified rather than requested — quotes by `verbatim_only()`, `found` by
# recomputation — and a prompt-only cap was the odd one out in a service whose whole design
# principle is "verify, don't ask". The cap counts *surviving* quotes, applied after the
# verbatim filter, so a model that pads with paraphrases doesn't crowd out real passages.
_MAX_QUOTES = 4

_SYSTEM_PROMPT = f"""You are locating source evidence for a single concept inside a textbook chapter.

## Your task

You will be given the full text of a chapter and one concept — its name, and a short summary someone wrote for it. Find the passages in the chapter that actually explain that concept, and quote them.

## Output format

Return only valid JSON. No preamble, no explanation, no markdown fences.

{{
  "found": true or false,
  "summary": "string (1-2 sentence explanation of the concept, drawn from the passages you quoted; empty string when found is false)",
  "quotes": ["string (a verbatim, contiguous passage from the chapter)"]
}}

## Rules

1. Every quote must be copied from the chapter exactly as it appears there — same words, same punctuation, nothing added, nothing elided, no "..." in the middle. It is checked against the chapter afterwards and silently discarded if it does not match, so an approximation is worth nothing.
2. A quote must be one unbroken run of the chapter, from where it starts to where it ends. Never stitch together sentences from different parts of the chapter into a single quote. If two separate parts are both relevant, return them as two separate quotes.
3. Prefer passages that EXPLAIN the concept — its mechanism, its purpose, what it is used for, what distinguishes it from something else — over passages that merely use the term in a sentence about something else. A student learns nothing from a name-drop, and a question cannot be written from one.
4. If the chapter does not discuss this concept, return {{"found": false, "summary": "", "quotes": []}}. This is an expected outcome, not a failure to work around: a chapter often assumes a concept rather than teaching it, and the person who added it may know that. Do not return the nearest-looking passage to fill the schema.
5. Never invent a definition. If the chapter only names the concept in passing and never explains it on its own terms, that is also found: false.
6. Return at most {_MAX_QUOTES} quotes. Fewer and better beats more and thinner — choose the most explanatory passages rather than everything that touches the topic.
7. Write `summary` in your own words, supported entirely by the quotes you returned. Do not copy a quote into it (the quotes are returned separately) and do not state anything the chapter does not.
8. The summary you are given identifies which concept is meant. It is not evidence. It may be vague or wrong, and your job is to report what the chapter says, not to confirm what it claims."""

_EDGE_SYSTEM_PROMPT = """You are locating the passage in a textbook chapter that justifies one prerequisite relationship between two concepts.

## Your task

You will be given the full text of a chapter and two concepts from it: a TARGET and a PREREQUISITE. Someone has asserted that understanding the prerequisite is required in order to understand the target. Find the passage in the chapter that shows this — text stating that the target is built on, uses, requires, extends, or is defined in terms of the prerequisite.

## Output format

Return only valid JSON. No preamble, no explanation, no markdown fences.

{
  "found": true or false,
  "quote": "string (a verbatim, contiguous sentence or phrase from the chapter; empty string when found is false)"
}

## Rules

1. The quote must be copied from the chapter exactly as it appears there — same words, same punctuation, nothing added, nothing elided. It is checked against the chapter afterwards and discarded if it does not match.
2. It must be one unbroken run of the chapter. Never stitch together text from different parts of it.
3. The passage must connect the two concepts. The chapter describing each of them separately, in different places, is not a justification for the relationship — return found: false instead.
4. Do not infer the relationship from general domain knowledge. If the chapter does not say it, it is not found here.
5. found: false is a normal outcome. A person can legitimately assert a dependency the chapter never spells out, and reporting that honestly is more useful than a passage that only looks relevant."""

_OUTPUT_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "found": {"type": "boolean"},
            "summary": {"type": "string"},
            "quotes": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["found", "summary", "quotes"],
        "additionalProperties": False,
    },
}

_EDGE_OUTPUT_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "found": {"type": "boolean"},
            "quote": {"type": "string"},
        },
        "required": ["found", "quote"],
        "additionalProperties": False,
    },
}


@lru_cache
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=get_settings().llm_api_key)


def _call(system: str, payload: dict, schema: dict) -> dict:
    response = _client().messages.create(
        model=_MODEL,
        max_tokens=2048,
        temperature=0,
        system=system,
        messages=[{"role": "user", "content": json.dumps(payload)}],
        output_config={"format": schema},
    )
    text = next(block.text for block in response.content if block.type == "text")
    return json.loads(text)


def _propose_raw_evidence(chapter_text: str, concept: Concept) -> RawEvidenceProposal:
    """One LLM call for one concept, returned as-is — quotes still unverified.

    Internal seam (see `RawEvidenceProposal`): `find_evidence()` below is what applies the
    verbatim check, so this is the shape a suite would grade to tell a model that quoted
    badly apart from one that found nothing.
    """
    data = _call(
        _SYSTEM_PROMPT,
        {
            "chapter_text": chapter_text,
            "concept": {"name": concept.name, "summary": concept.summary},
        },
        _OUTPUT_SCHEMA,
    )
    return {
        "found": bool(data["found"]),
        "summary": data["summary"],
        "quotes": list(data["quotes"]),
    }


def find_evidence(chapter_text: str, concept: Concept) -> EvidenceProposal:
    """Scan `chapter_text` for passages explaining `concept`, and propose a summary.

    Proposes only — the caller never writes this to the concept. See the design doc's §6
    and `EvidenceProposal`.

    Quotes are filtered to those genuinely present in the chapter, and `found` is recomputed
    from what survives rather than trusted from the model: a proposal whose every quote was
    a paraphrase has found nothing, whatever it claimed. `dropped` reports the discards so a
    reviewer seeing "no evidence found" can tell "the chapter doesn't cover this" apart from
    "the model paraphrased everything it returned".

    At most `_MAX_QUOTES` survive, trimmed after verification. Trimming is deliberately not
    counted in `dropped`, which means only "the model returned text that isn't in the chapter".

    One caveat worth knowing: a surviving `summary` was written against the model's whole
    quote list, so if some of those were dropped the summary may rest partly on text that
    isn't in the chapter. That is precisely why nothing here is applied without review.
    """
    raw = _propose_raw_evidence(chapter_text, concept)
    verified = verbatim_only(raw["quotes"], chapter_text) if raw["found"] else []
    dropped = (len(raw["quotes"]) - len(verified)) if raw["found"] else 0
    # Truncation is not a discard: `dropped` means "the model returned text that isn't in the
    # chapter", which is the prompt-health signal a regression suite watches. Quotes trimmed
    # here were perfectly good, just surplus, and counting them would blur the two.
    quotes = verified[:_MAX_QUOTES]

    if not quotes:
        return EvidenceProposal(found=False, summary="", quotes=[], dropped=dropped)
    return EvidenceProposal(
        found=True, summary=raw["summary"].strip(), quotes=quotes, dropped=dropped
    )


def find_edge_evidence(chapter_text: str, concept: Concept, prereq: Concept) -> str | None:
    """The source quote justifying `concept` depending on `prereq`, or None if the chapter
    doesn't supply one.

    The one thing that makes a hand-drawn edge indistinguishable from an extracted one:
    `graph_builder` records this quote for every edge it extracts, and `source_passages()`
    sends it as a `prerequisite_link` passage — often the sharper anchor for a
    `conceptual_distinction` question than either concept's summary.

    None is an ordinary answer, not an error. A reviewer can assert a dependency the chapter
    never states, and the caller stores `""` for it exactly as it did before this existed —
    `source_passages()` already skips an empty quote.
    """
    data = _call(
        _EDGE_SYSTEM_PROMPT,
        {
            "chapter_text": chapter_text,
            "target": {"name": concept.name, "summary": concept.summary},
            "prerequisite": {"name": prereq.name, "summary": prereq.summary},
        },
        _EDGE_OUTPUT_SCHEMA,
    )
    if not data["found"]:
        return None
    # Same discard-don't-repair rule as find_evidence: an edge quote that isn't in the
    # chapter is worse than no quote, since it would reach the question generator as
    # source-text provenance.
    kept = verbatim_only([data["quote"]], chapter_text)
    return kept[0] if kept else None
