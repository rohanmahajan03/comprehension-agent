"""Scoring for the evidence_finder regression suite.

Design doc: docs/specs/2026-09-15-evidence-finder-test-strategy.md.

**Deliberately judge-light.** The other three billed suites lean on a judge model because their
subject generates text with no ground truth to diff against. `evidence_finder` is *extractive*:
the right answer is a set of spans in a document this suite already holds, so span accuracy,
verbatim fidelity, found-precision, contiguity and cap adherence are all arithmetic. Only two
checks here call an LLM, and both are for questions that are genuinely interpretive.

That also makes the suite unusually stable. A judge's opinion of a varying model output varies
twice over; a substring check over a varying output varies once — which is why this suite was
worth building before settling the stage 0 non-determinism question
(docs/specs/2026-09-15-stage0-probe-progress.md, DEFERRED).

`score_case()` is lru_cache'd so the assertions in test_case3.py share one pass over the API
rather than re-running it per assertion, the same pattern as the other three suites.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache

import anthropic

from app.config import get_settings
from app.models import Concept
from app.services import evidence_finder
from app.services.evidence_finder import RawEvidenceProposal
from app.services.text_match import is_verbatim

from . import golden
from .golden import ABSENT, CASE, CONCEPT_LABELS, LINKED_PAIRS, SOURCE, UNLINKED_PAIRS

# --- thresholds ---------------------------------------------------------------------------
#
# Set loose and provisional, per diagnoser_geval's note: with 11 positive fixtures one flip is
# ~9 points, so a bar set flush against a first observed run turns a regression detector into a
# flake generator. The per-concept table in the terminal summary is the real detector; these
# only catch a collapse.

# Fraction of returned quotes that sit inside a region labelled for their own concept.
# The headline check — design doc §2, failure #1.
SPAN_ACCURACY_THRESHOLD = 0.75
# Fraction of concepts the chapter genuinely teaches that come back found: true.
FOUND_RECALL_THRESHOLD = 0.8
# Fraction of returned quotes judged to explain their concept rather than merely name it.
EXPLANATORY_THRESHOLD = 0.7
# Fraction of proposals whose summary is supported by the quotes returned alongside it.
SUMMARY_FAITHFUL_THRESHOLD = 0.8
# Found-precision on ABSENT concepts and raw-quote verbatim fidelity are ZERO TOLERANCE — a
# fabricated quote or invented provenance is a different kind of failure from a weak one, so
# they are asserted as counts, not rates.

_JUDGE_MODEL = "claude-haiku-4-5"

_EXPLANATORY_SYSTEM_PROMPT = """You are checking whether a passage quoted from a textbook actually explains a concept, or merely mentions it.

You will be given a CONCEPT and a PASSAGE quoted verbatim from the chapter that concept came from. The passage was selected as supporting evidence for writing quiz questions about that concept.

Explanatory if the passage conveys ANY of the following about the concept — any single one is enough:
- what it is, or how it works
- what it is for, or what problem it solves
- what distinguishes it from something else
- what it costs, or how it performs
- what its limits are, or what it cannot do

**A passage stating only a limitation, cost, or performance property is explanatory.** It does not also have to define the concept. "The hash table must fit in memory, and range queries are not efficient" teaches a student something real about hash indexes and is explanatory, even though it never says what a hash index is. Do not require a definition.

A single clear sentence counts — terseness is not the issue.

NOT explanatory if the passage only names the concept in passing while discussing something else, or refers to it without conveying anything about it at all. "We can then perform compaction on these segments" names compaction and conveys nothing about it; "Compaction means throwing away duplicate keys" explains it. An attribution — who invented it, which systems use it — conveys nothing about the concept itself.

Judge the passage on its own, as a student who has read nothing else would encounter it. Do not credit it for context you can infer but it does not contain: a passage whose subject is a pronoun with no antecedent inside the passage ("This in-memory tree is...") conveys nothing on its own. Do not penalize it for being short, for lacking an example, or for not covering every aspect of the concept.

Return only valid JSON, no preamble, no markdown fences:
{"explanatory": <true or false>, "reasoning": "<one sentence>"}"""

_SUMMARY_SYSTEM_PROMPT = """You are checking whether a one-or-two sentence summary of a textbook concept is supported by the source passages it was written from.

You will be given a CONCEPT, the PASSAGES quoted from the chapter, and a SUMMARY written to describe that concept.

Supported if everything the summary asserts is stated by the passages or follows directly from them. Rewording, condensing, and combining several passages into one sentence are all fine and expected — the summary is meant to be in its own words.

NOT supported if the summary asserts something the passages never state: a mechanism they do not describe, a comparison they do not make, a number or name they do not give, or a claim about the concept drawn from general knowledge of the subject rather than from these passages.

Judge only whether the passages support the summary. Do not judge whether the summary is well written, complete, or the best possible description of the concept.

Return only valid JSON, no preamble, no markdown fences:
{"supported": <true or false>, "reasoning": "<one sentence>"}"""

_EXPLANATORY_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "explanatory": {"type": "boolean"},
            "reasoning": {"type": "string"},
        },
        "required": ["explanatory", "reasoning"],
        "additionalProperties": False,
    },
}

_SUMMARY_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "supported": {"type": "boolean"},
            "reasoning": {"type": "string"},
        },
        "required": ["supported", "reasoning"],
        "additionalProperties": False,
    },
}


@lru_cache
def _judge_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=get_settings().llm_api_key)


def _judge(system: str, prompt: str, schema: dict, key: str) -> tuple[bool, str]:
    response = _judge_client().messages.create(
        model=_JUDGE_MODEL,
        max_tokens=256,
        temperature=0,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        output_config={"format": schema},
    )
    text = next(block.text for block in response.content if block.type == "text")
    data = json.loads(text)
    return bool(data[key]), data["reasoning"]


def judge_explanatory(concept_name: str, quote: str) -> tuple[bool, str]:
    """Does this quote teach the concept, or just name it? (design doc §2, failure #3)"""
    return _judge(
        _EXPLANATORY_SYSTEM_PROMPT,
        f"CONCEPT: {concept_name}\n\nPASSAGE:\n{quote}",
        _EXPLANATORY_SCHEMA,
        "explanatory",
    )


def judge_summary_supported(concept_name: str, quotes: list[str], summary: str) -> tuple[bool, str]:
    """Does the proposed summary overreach the quotes it was drawn from?

    Worth checking specifically because the service has a known path to overreach: a summary is
    written against the model's whole quote list, and quotes dropped as non-verbatim are
    removed *afterwards*, so a surviving summary can rest partly on text that was discarded.
    """
    passages = "\n\n".join(f"- {q}" for q in quotes)
    return _judge(
        _SUMMARY_SYSTEM_PROMPT,
        f"CONCEPT: {concept_name}\n\nPASSAGES:\n{passages}\n\nSUMMARY:\n{summary}",
        _SUMMARY_SCHEMA,
        "supported",
    )


# --- results ------------------------------------------------------------------------------


@dataclass(frozen=True)
class ConceptResult:
    concept_id: str
    raw: RawEvidenceProposal
    found: bool
    quotes: list[str]
    dropped: int
    summary: str
    off_target: list[str] = field(default_factory=list)
    non_verbatim_raw: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Judgment:
    concept_id: str
    subject: str
    passed: bool
    reasoning: str


@dataclass(frozen=True)
class CaseResult:
    positives: list[ConceptResult]
    false_positives: list[tuple[str, list[str]]]
    edge_misses: list[tuple[str, str]]
    edge_false_positives: list[tuple[str, str, str]]
    edge_non_verbatim: list[tuple[str, str, str]]
    explanatory: list[Judgment]
    summaries: list[Judgment]

    # --- deterministic ---

    @property
    def all_quotes(self) -> list[tuple[str, str]]:
        return [(r.concept_id, q) for r in self.positives for q in r.quotes]

    @property
    def off_target(self) -> list[tuple[str, str]]:
        return [(r.concept_id, q) for r in self.positives for q in r.off_target]

    @property
    def span_accuracy(self) -> float:
        total = len(self.all_quotes)
        return (total - len(self.off_target)) / total if total else float("nan")

    @property
    def found_recall(self) -> float:
        return sum(1 for r in self.positives if r.found) / len(self.positives)

    @property
    def non_verbatim_raw(self) -> list[tuple[str, str]]:
        return [(r.concept_id, q) for r in self.positives for q in r.non_verbatim_raw]

    @property
    def dropped_rate(self) -> float:
        """Share of raw quotes the verbatim filter had to discard — prompt health, not a
        pass/fail bar. A rise here is the early warning that the prompt has decayed, visible
        long before anything user-facing breaks (design doc §2, failure #5)."""
        raw_total = sum(len(r.raw["quotes"]) for r in self.positives)
        return sum(r.dropped for r in self.positives) / raw_total if raw_total else 0.0

    @property
    def over_cap(self) -> list[str]:
        return [r.concept_id for r in self.positives if len(r.quotes) > evidence_finder._MAX_QUOTES]

    # --- judged ---

    @property
    def explanatory_rate(self) -> float:
        return _rate(self.explanatory)

    @property
    def summary_rate(self) -> float:
        return _rate(self.summaries)

    # --- messages ---

    def span_message(self) -> str:
        lines = [f"  - {cid}: {q[:110]!r}" for cid, q in self.off_target]
        return (
            f"span accuracy {self.span_accuracy:.2f} < {SPAN_ACCURACY_THRESHOLD} — "
            f"{len(self.off_target)}/{len(self.all_quotes)} quotes fall outside their own "
            "concept's labelled regions:\n" + "\n".join(lines)
        )

    def found_recall_message(self) -> str:
        missed = [r.concept_id for r in self.positives if not r.found]
        return (
            f"found recall {self.found_recall:.2f} < {FOUND_RECALL_THRESHOLD} — "
            f"no evidence found for concepts this chapter does teach: {missed}"
        )

    def false_positive_message(self) -> str:
        lines = [f"  - {cid}: {quotes}" for cid, quotes in self.false_positives]
        return (
            "evidence was 'found' for concepts this chapter never teaches — invented "
            "provenance is the failure this check exists for:\n" + "\n".join(lines)
        )

    def judged_message(self, name: str, judgments: list[Judgment], threshold: float) -> str:
        failed = [j for j in judgments if not j.passed]
        lines = [f"  - {j.concept_id}: {j.subject[:100]!r}\n      {j.reasoning}" for j in failed]
        return (
            f"{name} rate {_rate(judgments):.2f} < {threshold} — "
            f"{len(failed)}/{len(judgments)} rejected:\n" + "\n".join(lines)
        )


def _rate(judgments: list[Judgment]) -> float:
    return sum(j.passed for j in judgments) / len(judgments) if judgments else float("nan")


def _concept(concept_id: str) -> Concept:
    return Concept(
        id=f"case3:{concept_id}",
        name=CONCEPT_LABELS[concept_id],
        # graph_builder would have written a summary by now; the scan is told the concept's
        # name and a short description, which is what the review endpoint passes it.
        summary=f"{CONCEPT_LABELS[concept_id]}, as described in this chapter.",
    )


@lru_cache
def score_case() -> CaseResult:
    positives: list[ConceptResult] = []
    for concept in CASE.concepts:
        target = _concept(concept.id)
        raw = evidence_finder._propose_raw_evidence(SOURCE, target)
        proposal = evidence_finder.find_evidence(SOURCE, target)
        positives.append(
            ConceptResult(
                concept_id=concept.id,
                raw=raw,
                found=proposal.found,
                quotes=list(proposal.quotes),
                dropped=proposal.dropped,
                summary=proposal.summary,
                off_target=[q for q in proposal.quotes if not golden.is_on_target(concept.id, q)],
                non_verbatim_raw=[q for q in raw["quotes"] if not is_verbatim(q, SOURCE)],
            )
        )

    false_positives: list[tuple[str, list[str]]] = []
    for slug, name, summary in ABSENT:
        proposal = evidence_finder.find_evidence(
            SOURCE, Concept(id=f"case3:{slug}", name=name, summary=summary)
        )
        if proposal.found:
            false_positives.append((slug, list(proposal.quotes)))

    edge_misses: list[tuple[str, str]] = []
    edge_false_positives: list[tuple[str, str, str]] = []
    edge_non_verbatim: list[tuple[str, str, str]] = []
    for prereq, concept_id in LINKED_PAIRS:
        quote = evidence_finder.find_edge_evidence(SOURCE, _concept(concept_id), _concept(prereq))
        if quote is None:
            edge_misses.append((prereq, concept_id))
        elif not is_verbatim(quote, SOURCE):
            edge_non_verbatim.append((prereq, concept_id, quote))
    for prereq, concept_id in UNLINKED_PAIRS:
        quote = evidence_finder.find_edge_evidence(SOURCE, _concept(concept_id), _concept(prereq))
        if quote is not None:
            edge_false_positives.append((prereq, concept_id, quote))

    explanatory = [
        Judgment(r.concept_id, q, *judge_explanatory(CONCEPT_LABELS[r.concept_id], q))
        for r in positives
        for q in r.quotes
    ]
    summaries = [
        Judgment(
            r.concept_id,
            r.summary,
            *judge_summary_supported(CONCEPT_LABELS[r.concept_id], r.quotes, r.summary),
        )
        for r in positives
        if r.found and r.summary
    ]

    return CaseResult(
        positives=positives,
        false_positives=false_positives,
        edge_misses=edge_misses,
        edge_false_positives=edge_false_positives,
        edge_non_verbatim=edge_non_verbatim,
        explanatory=explanatory,
        summaries=summaries,
    )
