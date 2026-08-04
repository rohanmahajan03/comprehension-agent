"""Shared scaffolding for the graph_builder G-Eval-style regression suite.

Each test scores one golden.GoldenCase by:
1. Running the real `graph_builder._extract_raw_graph()` LLM call on the case's
   source text (concepts + edges, still carrying each edge's evidence quote).
2. Aligning the extracted concepts to the case's gold concepts (and flagging any
   that match a "forbidden" idea instead) via a judge LLM call — needed because the
   system under test picks its own concept-id slugs, which won't string-match the
   golden ids.
3. Deterministically checking every edge's evidence is an actual verbatim quote from
   the source text (no LLM call needed — this is a plain substring check).

score_case() is lru_cache'd per case name so the ~4 assertions per case (concepts
found, forbidden concepts absent, edges found, evidence verbatim) share one
extraction + one alignment call instead of re-running the real API per assertion.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache

import anthropic

from app.config import get_settings
from app.services import graph_builder
from app.services.graph_builder import RawConcept, RawGraph

from .golden import CASES_BY_NAME, GoldenCase

# Judge model for concept alignment below — a different (and stronger) model than
# the extractor under test (`claude-haiku-4-5`, see app/services/graph_builder.py),
# so the suite isn't a model grading its own homework. Sonnet rather than Opus: this
# is a structural matching task (pairing concepts by meaning), not open-ended
# judgment, so the cheaper model is sufficient.
_ALIGN_MODEL = "claude-sonnet-4-5"

CONCEPT_RECALL_THRESHOLD = 0.8
EDGE_RECALL_THRESHOLD = 0.6

_ALIGNMENT_SYSTEM_PROMPT = """You are grading a concept-dependency-graph extraction system for a study tool. You will be given three things:

1. GOLD CONCEPTS — the ideas a human expert says the source text should yield, with a stable id.
2. FORBIDDEN IDEAS — things the source text explicitly should NOT become their own concept node (aliases of a gold concept, anti-patterns, implementation details, etc), each with an index.
3. EXTRACTED CONCEPTS — what the system under test actually produced (its own freely-chosen id, a label, and a summary).

The system under test picks its own concept ids, so they will generally NOT match the gold ids as strings — you must match by meaning.

For every extracted concept, decide exactly one of:
- It refers to the same idea as one gold concept (allow reworded labels/summaries, different slugs, different levels of detail) → return that gold concept's id.
- It is not a gold concept, but is instead one of the forbidden ideas wrongly promoted to its own node → return that forbidden idea's index.
- Neither of the above (a legitimate concept the gold list doesn't cover, or something unrelated) → return empty for both.

Rules:
- Each gold concept should be claimed by at most one extracted concept. If multiple extracted concepts could plausibly match the same gold concept, pick the single best match and leave the others unmatched.
- Only mark a forbidden match if the extracted concept clearly represents that specific forbidden idea, not merely a loosely related one.
- You must include exactly one entry per extracted concept, in the same order as given.

Return only valid JSON matching this schema, no preamble, no markdown fences:
{
  "matches": [
    { "extracted_id": "string, copied from the extracted concept", "gold_id": "string, or empty string if none", "forbidden_index": "integer, or -1 if none" }
  ]
}"""

_ALIGNMENT_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "matches": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "extracted_id": {"type": "string"},
                        "gold_id": {"type": "string"},
                        "forbidden_index": {"type": "integer"},
                    },
                    "required": ["extracted_id", "gold_id", "forbidden_index"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["matches"],
        "additionalProperties": False,
    },
}


@lru_cache
def _align_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=get_settings().llm_api_key)


def _normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _build_alignment_prompt(case: GoldenCase, extracted: list[RawConcept]) -> str:
    gold_lines = "\n".join(f"- id={c.id!r} label={c.label!r}" for c in case.concepts)
    forbidden_lines = (
        "\n".join(f"{i}: {desc}" for i, desc in enumerate(case.forbidden)) or "(none)"
    )
    extracted_lines = "\n".join(
        f"- id={c['id']!r} label={c['label']!r} summary={c['summary']!r}" for c in extracted
    )
    return (
        f"GOLD CONCEPTS:\n{gold_lines}\n\n"
        f"FORBIDDEN IDEAS:\n{forbidden_lines}\n\n"
        f"EXTRACTED CONCEPTS:\n{extracted_lines}"
    )


def _align(case: GoldenCase, extracted: list[RawConcept]) -> dict[str, dict]:
    """Return extracted_id -> {"gold_id": str, "forbidden_index": int} for every
    extracted concept (missing entries in the judge's response default to no match)."""
    response = _align_client().messages.create(
        model=_ALIGN_MODEL,
        max_tokens=2048,
        temperature=0,
        system=_ALIGNMENT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_alignment_prompt(case, extracted)}],
        output_config={"format": _ALIGNMENT_SCHEMA},
    )
    text_block = next(block.text for block in response.content if block.type == "text")
    data = json.loads(text_block)
    by_extracted_id = {m["extracted_id"]: m for m in data["matches"]}
    return {
        c["id"]: by_extracted_id.get(c["id"], {"gold_id": "", "forbidden_index": -1})
        for c in extracted
    }


@dataclass(frozen=True)
class CaseResult:
    case: GoldenCase
    raw: RawGraph
    matches: dict[str, dict]  # extracted_id -> {"gold_id", "forbidden_index"}

    @property
    def extracted_by_id(self) -> dict[str, RawConcept]:
        return {c["id"]: c for c in self.raw["concepts"]}

    @property
    def matched_gold_ids(self) -> set[str]:
        return {m["gold_id"] for m in self.matches.values() if m["gold_id"]}

    @property
    def missed_concepts(self) -> list:
        return [c for c in self.case.concepts if c.id not in self.matched_gold_ids]

    @property
    def concept_recall(self) -> float:
        if not self.case.concepts:
            return 1.0
        return len(self.matched_gold_ids) / len(self.case.concepts)

    @property
    def forbidden_hits(self) -> list[tuple[RawConcept, str]]:
        hits = []
        for extracted_id, m in self.matches.items():
            if m["forbidden_index"] is not None and m["forbidden_index"] >= 0:
                hits.append((self.extracted_by_id[extracted_id], self.case.forbidden[m["forbidden_index"]]))
        return hits

    @property
    def extracted_to_gold(self) -> dict[str, str]:
        return {eid: m["gold_id"] for eid, m in self.matches.items() if m["gold_id"]}

    @property
    def produced_edges_in_gold_space(self) -> set[tuple[str, str]]:
        mapping = self.extracted_to_gold
        edges = set()
        for edge in self.raw["edges"]:
            frm, to = mapping.get(edge["from"]), mapping.get(edge["to"])
            if frm and to:
                edges.add((frm, to))
        return edges

    @property
    def gold_edges(self) -> set[tuple[str, str]]:
        return {(e.frm, e.to) for e in self.case.edges}

    @property
    def missed_edges(self) -> set[tuple[str, str]]:
        return self.gold_edges - self.produced_edges_in_gold_space

    @property
    def edge_recall(self) -> float:
        if not self.gold_edges:
            return 1.0
        return len(self.gold_edges & self.produced_edges_in_gold_space) / len(self.gold_edges)

    @property
    def evidence_violations(self) -> list[str]:
        normalized_source = _normalize_ws(self.case.source_text)
        violations = []
        for edge in self.raw["edges"]:
            if _normalize_ws(edge["evidence"]) not in normalized_source:
                violations.append(f"{edge['from']} -> {edge['to']}: {edge['evidence']!r}")
        return violations

    def missed_concepts_message(self) -> str:
        names = ", ".join(f"{c.id} ({c.label})" for c in self.missed_concepts)
        return (
            f"concept recall {self.concept_recall:.2f} < {CONCEPT_RECALL_THRESHOLD} — "
            f"missed {len(self.missed_concepts)}/{len(self.case.concepts)}: {names}"
        )

    def forbidden_hits_message(self) -> str:
        lines = [f"  - {c['label']!r} (id={c['id']!r}) matches: {desc}" for c, desc in self.forbidden_hits]
        return "forbidden ideas leaked as their own nodes:\n" + "\n".join(lines)

    def missed_edges_message(self) -> str:
        return (
            f"edge recall {self.edge_recall:.2f} < {EDGE_RECALL_THRESHOLD} — "
            f"missed {len(self.missed_edges)}/{len(self.gold_edges)}: {sorted(self.missed_edges)}"
        )

    def evidence_violations_message(self) -> str:
        return "edges whose evidence isn't a verbatim quote from the source text:\n" + "\n".join(
            self.evidence_violations
        )


@lru_cache
def score_case(case_name: str) -> CaseResult:
    case = CASES_BY_NAME[case_name]
    raw = graph_builder._extract_raw_graph(case.source_text)
    matches = _align(case, raw["concepts"])
    return CaseResult(case=case, raw=raw, matches=matches)
