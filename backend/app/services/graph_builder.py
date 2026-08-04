"""Concept extraction + dependency graph construction (pipeline 1, step 2)."""

import json
from functools import lru_cache
from graphlib import TopologicalSorter
from typing import TypedDict

import anthropic

from app.config import get_settings
from app.models import Concept, DependencyGraph


class RawConcept(TypedDict):
    id: str
    label: str
    summary: str


RawEdge = TypedDict("RawEdge", {"from": str, "to": str, "evidence": str})


class RawGraph(TypedDict):
    concepts: list[RawConcept]
    edges: list[RawEdge]

_MODEL = "claude-haiku-4-5"

_SYSTEM_PROMPT = """You are a knowledge graph builder. Given a section of textbook text, extract a concept dependency graph.

## Your task

Identify the key concepts in the text and the prerequisite relationships between them. A prerequisite edge A → B means "understanding A is required to understand B", and that relationship must be explicitly supported by the text.

## What counts as a concept

Be strict. This tool helps people understand entire chapters, so concepts must be the handful of big ideas a chapter builds — not every term that appears in it. A concept is something the text gives its own sustained explanation to, that a student could reasonably be quizzed on by itself.

Do NOT create a separate node for:
- A property, capability, or consequence of another concept (e.g. "supports range queries" describes an index type — it is not its own concept).
- An operation, query type, or example mentioned only to illustrate what a concept does or doesn't do.
- A term used in passing while explaining a different concept, where the text never stops to teach it on its own terms.
- A sub-step or component that only exists in service of a larger idea, unless the text separately treats it as its own topic with its own explanation.

If in doubt, merge: fold the detail into the summary of the concept it supports instead of giving it a node. As a rough calibration, a few paragraphs of text should usually yield at most one or two concepts, not one per sentence or noun phrase — if your draft has a concept for nearly every term that appears, you are over-segmenting; collapse related terms into fewer, richer concepts.

## Output format

Return only valid JSON. No preamble, no explanation, no markdown fences.

{
  "concepts": [
    { "id": "string (slug, e.g. hash_partitioning)", "label": "string (human readable)", "summary": "string (1-2 sentence explanation of the concept, drawn from the text)" }
  ],
  "edges": [
    {
      "from": "concept_id",
      "to": "concept_id",
      "evidence": "verbatim sentence or phrase from the text that justifies this edge"
    }
  ]
}

## Rules

1. Only extract concepts that meet the bar above — substantial ideas the text meaningfully and independently explains, not terms that are merely mentioned or used in service of explaining something else.
2. Only create an edge if the prerequisite relationship is grounded in the text. The evidence field must be a direct quote from the text.
3. If a concept is referenced from another chapter but not explained here, include it as a concept node but do not create edges to or from it that aren't supported by this text.
4. Do not infer edges from general domain knowledge. If the text doesn't say it, don't edge it.
5. Each concept should appear at most once. If the text uses multiple terms for the same concept, pick the most used term and note the aliases in the label.
6. Concepts should be atomic in scope — prefer "hash partitioning" over "partitioning strategies" as a single node — but not fragmented: don't split one cohesive idea into separate nodes for its components, properties, or the operations it enables."""

_OUTPUT_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "concepts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "label": {"type": "string"},
                        "summary": {"type": "string"},
                    },
                    "required": ["id", "label", "summary"],
                    "additionalProperties": False,
                },
            },
            "edges": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "from": {"type": "string"},
                        "to": {"type": "string"},
                        "evidence": {"type": "string"},
                    },
                    "required": ["from", "to", "evidence"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["concepts", "edges"],
        "additionalProperties": False,
    },
}


@lru_cache
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=get_settings().llm_api_key)


def _reachable(depends_on: dict[str, list[str]], start: str, target: str) -> bool:
    """Whether `target` can be reached from `start` by following depends_on edges."""
    stack = [start]
    seen: set[str] = set()
    while stack:
        node = stack.pop()
        if node == target:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(depends_on.get(node, []))
    return False


def _extract_raw_graph(text: str) -> RawGraph:
    """Call the LLM and return its concepts/edges as-is (un-namespaced slugs, edges
    still carrying their `evidence` quote).

    Internal seam, not part of the stable public API: `build_graph()` below collapses
    `edges` into each concept's `depends_on` and discards `evidence` in the process, so
    this function exists mainly so the graph_geval test suite can grade edge evidence
    directly. Only obviously-invalid edges (self-loops, dangling endpoints) are
    dropped here; cycle-safety is enforced downstream in `build_graph()`.
    """
    response = _client().messages.create(
        model=_MODEL,
        max_tokens=4096,
        temperature=0,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": text}],
        output_config={"format": _OUTPUT_SCHEMA},
    )
    text_block = next(block.text for block in response.content if block.type == "text")
    data = json.loads(text_block)

    # Dedup concepts by slug (LLM is instructed to do this itself, but don't trust it blindly).
    concepts: dict[str, RawConcept] = {}
    for c in data["concepts"]:
        concepts.setdefault(c["id"], c)

    edges = [
        edge
        for edge in data["edges"]
        if edge["from"] != edge["to"] and edge["from"] in concepts and edge["to"] in concepts
    ]
    return {"concepts": list(concepts.values()), "edges": edges}


def build_graph(doc_id: str, text: str) -> DependencyGraph:
    """Extract concepts and prerequisite links from raw chapter text via an LLM call."""
    raw = _extract_raw_graph(text)

    # Build the depends_on adjacency, skipping any edge that would introduce a cycle
    # so the required-DAG invariant (relied on by topological_order) holds.
    depends_on: dict[str, list[str]] = {c["id"]: [] for c in raw["concepts"]}
    for edge in raw["edges"]:
        frm, to = edge["from"], edge["to"]
        if _reachable(depends_on, frm, to):
            continue
        depends_on[to].append(frm)

    concepts = [
        Concept(
            id=f"{doc_id}:{c['id']}",
            name=c["label"],
            summary=c["summary"],
            depends_on=[f"{doc_id}:{dep}" for dep in depends_on[c["id"]]],
        )
        for c in raw["concepts"]
    ]
    return DependencyGraph(doc_id=doc_id, concepts=concepts)


def topological_order(graph: DependencyGraph) -> list[Concept]:
    """Order concepts so every prerequisite comes before the concepts that need it."""
    by_id = {c.id: c for c in graph.concepts}
    sorter = TopologicalSorter({c.id: c.depends_on for c in graph.concepts})
    return [by_id[cid] for cid in sorter.static_order() if cid in by_id]
