"""Question generation, one set per concept node (pipeline 1, step 3)."""

import json
from functools import lru_cache
from typing import TypedDict

import anthropic

from app.config import get_settings
from app.models import Concept, DependencyGraph, Question


class RawQuestion(TypedDict):
    type: str
    question: str
    grounding: str


_MODEL = "claude-sonnet-4-6"

_QUESTION_TYPES = [
    "conceptual_correctness",
    "conceptual_distinction",
    "enumeration_completeness",
    "open_ended_example",
    "applied_reasoning",
]

_SYSTEM_PROMPT = """You are an expert tutor generating assessment questions for a single concept from a textbook.

## Your task

Given a target concept and its graph context, generate questions that assess a student's
understanding of the target concept. Questions must be grounded strictly in the provided
evidence text — do not draw on general knowledge beyond what is stated.

## Context you will receive

- target_concept: the concept being assessed, with its evidence anchor
- prerequisites: concepts the target concept depends on, each with their evidence anchor
- siblings: concepts at the same level as the target concept, each with their evidence anchor

## Question types

Assess whether each type is appropriate given the context provided. Only generate a
question if the type genuinely fits — it is better to skip a type than to force one.

1. conceptual_correctness — ask the student to precisely explain the target concept
   Appropriate for: any concept with sufficient explanatory evidence

2. conceptual_distinction — ask the student to differentiate the target concept from
   a prerequisite or sibling concept and explain how they relate
   Appropriate for: when a meaningful contrast exists between the target and a
   prerequisite or sibling, grounded in the evidence

3. enumeration_completeness — ask the student to list all items in a fixed set
   associated with the target concept
   Appropriate for: when the evidence explicitly defines a complete, bounded list
   (e.g. "there are two approaches...", "the three strategies are...")

4. open_ended_example — ask the student to provide or evaluate an example
   Appropriate for: when the evidence describes a mechanism or pattern that can
   be illustrated with a concrete scenario

5. applied_reasoning — give the student a scenario and ask them to apply the target
   concept to reason through it
   Appropriate for: when the evidence describes a mechanism with clear cause-and-effect
   that can be tested in a novel situation

## Output format

Return only valid JSON. No preamble, no explanation, no markdown fences.

{
  "concept_id": "string",
  "questions": [
    {
      "type": "conceptual_correctness | conceptual_distinction | enumeration_completeness | open_ended_example | applied_reasoning",
      "question": "string",
      "grounding": "the specific evidence text this question is based on"
    }
  ]
}

## Rules

1. Only generate questions grounded in the provided evidence text.
2. Do not generate questions about concepts not present in the provided context.
3. Skip any question type that does not genuinely fit — do not force it.
4. Questions should be answerable by a student who has only read the provided evidence.
5. Each question should target the concept at a level appropriate to its type.
6. Do not reveal the answer in the question itself.
7. When evidence spans multiple source passages (e.g. the target concept's own
   evidence plus a prerequisite's or sibling's), treat each passage as atomic — a
   passage is everything given for that source, not a single sentence within it.
   Quote every passage you draw on in full, from start to end: never truncate
   mid-clause, drop a trailing sentence, or compress/shorten a passage because its
   content seems to overlap or repeat what another passage you are also quoting
   already says. Redundancy between passages is never a reason to shorten either
   one — quote both in full anyway.

## Input

target_concept: {target_concept}
prerequisites: {prerequisites}
siblings: {siblings}"""

_OUTPUT_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "concept_id": {"type": "string"},
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": _QUESTION_TYPES},
                        "question": {"type": "string"},
                        "grounding": {"type": "string"},
                    },
                    "required": ["type", "question", "grounding"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["concept_id", "questions"],
        "additionalProperties": False,
    },
}


_GROUNDING_PREFIX = "A correct answer is grounded in: "


@lru_cache
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=get_settings().llm_api_key)


def _describe(concept: Concept, evidence: str) -> dict[str, str]:
    return {"id": concept.id, "name": concept.name, "summary": concept.summary, "evidence": evidence}


def _siblings_of(target: Concept, graph: DependencyGraph) -> list[Concept]:
    """Concepts at the same level as `target`: those sharing at least one direct
    parent (prerequisite) with it. Concepts with no prerequisites of their own have
    no direct parent to share, so they have no siblings.
    """
    target_deps = set(target.depends_on)
    if not target_deps:
        return []
    return [c for c in graph.concepts if c.id != target.id and target_deps & set(c.depends_on)]


def _generate_raw_for_concept(concept: Concept, by_id: dict[str, Concept], graph: DependencyGraph) -> list[RawQuestion]:
    """Call the LLM for a single concept and return its raw question list as-is
    (each still carrying its `type` and unwrapped `grounding` quote).

    Internal seam, not part of the stable public API: `generate_questions()` below
    folds each raw item into a `Question` (dropping `type`, folding `grounding` into
    `expected_answer_notes`) — kept separate so tests/question_geval can grade
    question-type coverage and grounding directly.
    """
    payload = {
        "target_concept": _describe(concept, concept.summary),
        "prerequisites": [
            _describe(by_id[dep_id], concept.evidence.get(dep_id, ""))
            for dep_id in concept.depends_on
            if dep_id in by_id
        ],
        "siblings": [_describe(sibling, sibling.summary) for sibling in _siblings_of(concept, graph)],
    }
    response = _client().messages.create(
        model=_MODEL,
        max_tokens=2048,
        temperature=0,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": json.dumps(payload)}],
        output_config={"format": _OUTPUT_SCHEMA},
    )
    text = next(block.text for block in response.content if block.type == "text")
    data = json.loads(text)
    return data["questions"]


def generate_questions(graph: DependencyGraph) -> None:
    """Generate a question set for every concept in `graph` and store it on that
    concept's `questions` field, in place.

    For each concept, gathers its prerequisites (with the evidence quote that
    justifies each dependency) and same-level siblings as grounding context, then
    asks the LLM to produce evidence-grounded questions for that concept alone (see
    the system prompt for the question taxonomy and grounding rules).
    """
    by_id = {c.id: c for c in graph.concepts}
    for concept in graph.concepts:
        raw_questions = _generate_raw_for_concept(concept, by_id, graph)
        concept.questions = [
            Question(
                id=f"{concept.id}:q{i + 1}",
                concept_id=concept.id,
                prompt=q["question"],
                expected_answer_notes=f"{_GROUNDING_PREFIX}{q['grounding']}",
            )
            for i, q in enumerate(raw_questions)
        ]
