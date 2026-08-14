"""Question generation, one set per concept node (pipeline 1, step 3)."""

import json
from functools import lru_cache
from typing import TypedDict

import anthropic

from app.config import get_settings
from app.models import Concept, DependencyGraph, Question


class SourcePassage(TypedDict):
    id: str
    role: str
    concept_name: str
    text: str


class RawQuestion(TypedDict):
    type: str
    question: str
    expected_answer: str
    # Ids the model cited; `grounding` is assembled from them in code, never retyped by
    # the model — see source_passages() for why.
    source_ids: list[str]
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

- target_concept: the concept being assessed (id and name)
- sources: every evidence passage you may draw on, each with a stable `id`, its `text`,
  and a `role` saying how it relates to the target concept:
    - target_concept — the target concept's own evidence
    - prerequisite — a concept the target depends on
    - prerequisite_link — the passage justifying why the target depends on that
      prerequisite
    - sibling — a concept at the same level as the target

## Question types

Assess whether each type is appropriate given the context provided. Only generate a
question if the type genuinely fits — it is better to skip a type than to force one.

1. conceptual_correctness — ask the student to precisely explain the target concept
   Appropriate for: any concept with sufficient explanatory evidence

2. conceptual_distinction — ask the student to differentiate the target concept from
   a prerequisite or sibling concept and explain how they relate
   Appropriate for: when the evidence itself establishes the contrast — it compares
   them, or states how one relates to the other. Two concepts being described
   separately in different passages is NOT a contrast; skip this type rather than
   inventing the comparison yourself.

3. enumeration_completeness — ask the student to list all items in a fixed set
   associated with the target concept
   Appropriate for: when the evidence explicitly defines a complete, bounded list
   (e.g. "there are two approaches...", "the three strategies are...")

4. open_ended_example — ask the student to provide or evaluate an example
   Appropriate for: when the evidence describes a mechanism or pattern that can
   be illustrated with a concrete scenario

5. applied_reasoning — give the student a scenario and ask them to apply the target
   concept to reason through it
   Appropriate for: when the evidence spells out the mechanism — the why behind the
   behavior — so the reasoning can be carried into a new situation. Skip this type
   when the evidence states an outcome without the mechanism producing it; there is
   nothing for the student to reason with.

## Output format

Return only valid JSON. No preamble, no explanation, no markdown fences.

{
  "concept_id": "string",
  "questions": [
    {
      "type": "conceptual_correctness | conceptual_distinction | enumeration_completeness | open_ended_example | applied_reasoning",
      "question": "string",
      "expected_answer": "the ideal student response to this question, in prose",
      "source_ids": ["id of each source passage this question draws on"]
    }
  ]
}

## Rules

1. Only generate questions grounded in the provided evidence text.
2. Do not generate questions about concepts not present in the provided context.
3. Skip any question type that does not genuinely fit — do not force it.
4. Every question must be fully answerable by a student who has read only the provided
   evidence and knows nothing else about the topic. It is not enough that the evidence
   states the fact your question rests on — it must also supply whatever mechanism,
   comparison, or alternative the answer has to invoke. If the evidence says a hash
   index cannot serve range queries efficiently but never says why, nor what structure
   could, then both "why can't it?" and "what would be needed instead?" are out of
   bounds; ask what the limitation is instead. When in doubt, ask for what the evidence
   states rather than what it implies.
5. Each question should target the concept at a level appropriate to its type.
6. Do not reveal the answer in the question itself.
7. List the id of every source passage your question draws on in `source_ids`. Cite
   passages by id only — never retype, quote, paraphrase, or summarize their text
   anywhere in your output. The exact passage text is attached automatically from the
   ids you cite, so copying it yourself can only introduce errors.
8. Write an `expected_answer`: the ideal response to your question, in the student's
   own voice — exactly what the strongest student in the class would write, and nothing
   a student would not write. That student has never seen these source passages and
   cannot refer to them, so words like "the evidence", "the passage", "the source", or
   "the excerpt" must not appear anywhere in it: state the fact itself instead of
   attributing it. Write "A hash index cannot answer range queries efficiently because
   it stores no ordering of keys", never "The evidence states that a hash index cannot
   answer range queries efficiently". A separate evaluator grades real answers by
   checking which parts of this one they cover, and it sees only the question, this
   text, and the student's answer — not the sources — so anything you point at rather
   than state is simply lost. Derive it strictly from the evidence; never require
   anything the evidence does not support.
9. Match the expected_answer to the question type. For enumeration_completeness, name
   every item the answer must include — the evaluator cannot check a set it was never
   given. For open_ended_example and applied_reasoning, the correct answer is the
   student's own novel example or line of reasoning and will NOT appear in the
   evidence: write what any valid answer has to demonstrate rather than committing to
   one specific example, so a different-but-correct answer isn't marked wrong.

## Input

target_concept: {target_concept}
sources: {sources}"""

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
                        "expected_answer": {"type": "string"},
                        "source_ids": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["type", "question", "expected_answer", "source_ids"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["concept_id", "questions"],
        "additionalProperties": False,
    },
}


def format_answer_notes(expected_answer: str, grounding: str) -> str:
    """Render a question's model answer into the `expected_answer_notes` string
    `evaluator.py` grades against.

    Deliberately just the prose model answer, with nothing wrapped around it: that is the
    exact shape `tests/geval` has always fed the evaluator (its `golden_answer` fixtures),
    so production and the suite that validates it stay the same kind of input. `grounding`
    is a fallback only — the schema requires an expected_answer, but a source quote is
    still better than an empty rubric if one ever comes back blank.

    Shared with `diagnoser.py` (whose diagnostic questions the same evaluator grades) so
    both pipelines hand it one consistent shape.
    """
    expected_answer = expected_answer.strip()
    if expected_answer:
        return expected_answer
    return f"A correct answer is grounded in: {grounding.strip()}"


@lru_cache
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=get_settings().llm_api_key)


def source_passages(
    concept: Concept, by_id: dict[str, Concept], graph: DependencyGraph
) -> list[SourcePassage]:
    """Every evidence passage available to the LLM for `concept`, each with a stable id.

    The single source of truth for what grounds a question. `_generate_raw_for_concept()`
    builds its prompt from this list, and the model cites passages by `id` instead of
    retyping them — so a question's `grounding` is assembled in code from these exact
    strings and cannot drift from the source. That replaced an earlier design where the
    model quoted passages back verbatim, which reproducibly corrupted the same sentence
    (a dropped clause, a mangled em-dash) across runs even at `temperature=0`, and which
    three rounds of prompt-strengthening failed to make reliable.

    `tests/question_geval` imports this too, so the suite can never disagree with the
    generator about what was actually sent.
    """
    passages: list[SourcePassage] = [
        {
            "id": "s1",
            "role": "target_concept",
            "concept_name": concept.name,
            "text": concept.summary,
        }
    ]

    def add(role: str, concept_name: str, text: str) -> None:
        if text:
            passages.append(
                {
                    "id": f"s{len(passages) + 1}",
                    "role": role,
                    "concept_name": concept_name,
                    "text": text,
                }
            )

    for dep_id in concept.depends_on:
        if dep_id not in by_id:
            continue
        prereq = by_id[dep_id]
        add("prerequisite", prereq.name, prereq.summary)
        # The quote justifying this specific dependency — distinct from the prerequisite's
        # own summary, and often the sharper anchor for a conceptual_distinction question.
        add("prerequisite_link", prereq.name, concept.evidence.get(dep_id, ""))
    for sibling in _siblings_of(concept, graph):
        add("sibling", sibling.name, sibling.summary)
    return passages


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
    (each still carrying its `type`, prose `expected_answer`, and unwrapped `grounding` quote).

    Internal seam, not part of the stable public API: `generate_questions()` below
    folds each raw item into a `Question` (dropping `type`, rendering `expected_answer`
    into `expected_answer_notes`) — kept separate so tests/question_geval can grade
    question-type coverage, grounding, and the expected answer directly.

    The model returns `source_ids`, not quoted text; each question's `grounding` is
    assembled here from the passages those ids name, so it is verbatim by construction.
    """
    passages = source_passages(concept, by_id, graph)
    text_by_id = {p["id"]: p["text"] for p in passages}
    payload = {
        "target_concept": {"id": concept.id, "name": concept.name},
        "sources": passages,
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
    questions: list[RawQuestion] = json.loads(text)["questions"]
    for q in questions:
        cited = [sid for sid in q["source_ids"] if sid in text_by_id]
        # Fall back to the concept's own evidence rather than shipping an unanchored
        # question if the model cites nothing valid.
        q["source_ids"] = cited or [passages[0]["id"]]
        q["grounding"] = "\n\n".join(text_by_id[sid] for sid in q["source_ids"])
    return questions


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
                expected_answer_notes=format_answer_notes(q["expected_answer"], q["grounding"]),
            )
            for i, q in enumerate(raw_questions)
        ]
