"""Gap diagnosis: walk dependencies to find the root misunderstanding (pipeline 2, steps 3-5).

Unlike the other three services, this one is not a single structured LLM call. It runs a
bounded tool-calling loop: the model investigates the prerequisite chain with `get_prereqs`,
checks for an existing question with `pull_question_from_storage`, synthesizes one with
`generate_question` if needed, and must finish by calling `submit_diagnosis`. See
docs/specs/2026-08-10-diagnoser-agentic-pipeline-design.md for the design rationale.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, TypedDict

import anthropic

from app.config import get_settings
from app.models import (
    Answer,
    Concept,
    DependencyGraph,
    DiagnosisResult,
    EvaluationResult,
    Question,
)
# Diagnostic questions are graded by the same evaluator as pipeline-1 questions, so they
# must render their model answer into expected_answer_notes identically.
from app.services.question_generator import format_answer_notes


class RawQuestion(TypedDict):
    question: str
    expected_answer: str
    grounding: str


@dataclass(frozen=True)
class DiagnosisTrace:
    """How a diagnosis was reached — see `_diagnose_with_trace()`."""

    turns_used: int
    tool_calls: list[tuple[str, dict[str, Any]]]
    #: submit_diagnosis payloads the certainty gate refused
    rejected_submissions: list[dict[str, Any]]
    #: concept ids passed to get_prereqs, in order — the investigation path
    concepts_inspected: list[str]
    #: whether the accepted submission was the forced one on the last turn
    forced_final: bool
    #: whether the diagnosis fell back to general knowledge (see system prompt rule 3)
    gap_outside_graph: bool = False


_ORCHESTRATOR_MODEL = "claude-sonnet-4-6"
_GENERATOR_MODEL = "claude-sonnet-4-6"
# Match/no-match over a handful of candidates is a mechanical judgment, the same tier of task
# as question_geval's judge_similarity() — it doesn't need the orchestrator's model.
_JUDGE_MODEL = "claude-haiku-4-5"

# 4 investigative turns + 1 forced-final turn.
_MAX_TURNS = 5


class _ToolError(Exception):
    """Raised by a tool executor to return an is_error tool_result the model can recover from."""


# --- orchestration ------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a diagnostician for an adaptive tutoring system.

A student answered a question incorrectly. An evaluator has already graded that answer and
stated precisely which elements the rubric required that were missing or wrong — it deliberately
did not speculate about *why*. That is your job: trace the failure to the specific prerequisite
concept the student does not understand, and produce a question that isolates it.

## Your procedure

1. Read the evaluator's finding. That is the deficiency: what the answer failed to show.
2. Use `get_prereqs` to see what the answered concept depends on, along with the source-text
   evidence justifying each dependency. That first call very often already returns the passage
   that explains what the student got wrong — when it does, you have your suspect and you are
   done investigating. Call `get_prereqs` again on a prerequisite's own id only when the
   evidence you already hold does NOT explain the deficiency. The root gap is sometimes deeper
   than one hop, but walking deeper after you can already name the gap costs a turn, changes
   nothing, and leaves you without the turns you need for steps 3 and 4.
3. Once you have a candidate suspect and can state the deficiency in terms of that concept, use
   `pull_question_from_storage` to check whether a question targeting it already exists. If
   nothing targets it, use `generate_question` to create one.
4. Call `submit_diagnosis` with the suspect concept, the question, and your evidence.

## Certainty

Do not submit a diagnosis that merely feels plausible. Submit with confidence "high" only when
you can point to a specific element the evaluator flagged and connect it to specific wording in
the suspect concept's evidence. If you cannot do that yet, keep investigating with `get_prereqs`.
A submission below "high" confidence will be rejected and you will have to continue.

## Budget

You have a limited number of turns and each tool call costs one, including the calls that
select or write the question. Stop investigating the moment you can meet the certainty bar
above: a probe that does not change your answer is pure waste. Reaching the correct diagnosis
in two turns is strictly better than reaching the same diagnosis in four — it is not a
shortcut, it is the goal. On your final turn you will be forced to submit whatever you have,
so never let it come to that by choice.

## Rules

1. Never reveal the answer in the question you select or generate. Probing a concept means
   asking the student to demonstrate it, not showing them what the source text says about it.
2. Prefer a concept from the graph. If the answered concept has no prerequisites of its
   own, it is itself the root gap — diagnose it.
3. Occasionally no concept in the graph explains the deficiency at all: what the student is
   missing is background knowledge the source material simply never teaches. When that is
   genuinely the case — not merely when the fit is imperfect — say so rather than forcing
   the blame onto a prerequisite that does not deserve it. Set `gap_is_outside_graph` to
   true, still set `suspected_gap_concept_id` to whichever graph concept the gap sits
   closest to, and name the missing background plainly in your reasoning. Your question may
   then draw on general knowledge: pass `allow_general_knowledge` to `generate_question`.
   This path is rare. Exhaust the graph first, and do not reach for it merely because the
   deficiency spans several prerequisites.
4. Base your diagnosis on the evaluator's finding, not on your own re-grading of the answer."""

_GET_PREREQS_TOOL = {
    "name": "get_prereqs",
    "description": (
        "Return the immediate prerequisites of a concept, each with the evidence quote that "
        "justifies the dependency. Call this on a prerequisite's own id to walk one level "
        "deeper into the chain. An empty list means this concept has no further prerequisites "
        "(a leaf)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"concept_id": {"type": "string"}},
        "required": ["concept_id"],
    },
}

_PULL_QUESTION_TOOL = {
    "name": "pull_question_from_storage",
    "description": (
        "Check whether an existing question for this concept already targets the given "
        "deficiency. Call this once you have a candidate suspect concept and can state the "
        "deficiency in terms of it. Returns the matching question if one adequately targets "
        "this exact deficiency, or none if nothing does — in which case use generate_question."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "concept_id": {"type": "string"},
            "focus": {
                "type": "string",
                "description": (
                    "The deficiency to check for, stated in terms of this concept — the same "
                    "content you would pass to generate_question."
                ),
            },
        },
        "required": ["concept_id", "focus"],
    },
}

_GENERATE_QUESTION_TOOL = {
    "name": "generate_question",
    "description": (
        "Generate one new question that isolates a specific understanding gap within a concept, "
        "grounded strictly in that concept's own evidence. Use this only when "
        "pull_question_from_storage has nothing that precisely isolates the gap you suspect."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "concept_id": {"type": "string"},
            "focus": {
                "type": "string",
                "description": (
                    "What specifically to probe — the deficiency you have traced to this "
                    "concept, stated in terms of what the evaluator's finding flagged as "
                    "missing or wrong."
                ),
            },
            "allow_general_knowledge": {
                "type": "boolean",
                "description": (
                    "Set true only alongside a gap_is_outside_graph diagnosis, to let the "
                    "question go beyond what the source material states."
                ),
            },
        },
        "required": ["concept_id", "focus"],
    },
}

_SUBMIT_DIAGNOSIS_TOOL = {
    "name": "submit_diagnosis",
    "description": (
        "Submit your final diagnosis. Only call this with confidence 'high' if you have concrete "
        "evidence — a specific element the evaluator's finding flagged as missing or wrong, "
        "connected to specific wording in the suspect prerequisite's evidence. A gut feeling is "
        "not enough; if you are not certain, keep investigating with get_prereqs instead."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "suspected_gap_concept_id": {"type": "string"},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "reasoning": {
                "type": "string",
                "description": "Why this concept, in plain terms suitable for the diagnosis record.",
            },
            "evidence_basis": {
                "type": "string",
                "description": (
                    "The specific element from the evaluator's finding and the specific wording "
                    "in the suspect's evidence that connect them."
                ),
            },
            "gap_is_outside_graph": {
                "type": "boolean",
                "description": (
                    "True only when no concept in the graph explains the deficiency and the "
                    "diagnosis rests on general background knowledge instead. This is "
                    "surfaced to the student, so do not set it for a merely imperfect fit."
                ),
            },
            "question_source": {"type": "string", "enum": ["storage", "generated"]},
            "question_id": {
                "type": "string",
                "description": "Required when question_source is 'storage'.",
            },
            "question_text": {
                "type": "string",
                "description": (
                    "Required when question_source is 'generated'. Copy generate_question's "
                    "output exactly."
                ),
            },
            "expected_answer": {
                "type": "string",
                "description": (
                    "Required when question_source is 'generated'. Copy generate_question's "
                    "expected_answer exactly — it is what the evaluator grades against."
                ),
            },
            "grounding": {
                "type": "string",
                "description": (
                    "Required when question_source is 'generated'. Copy generate_question's "
                    "grounding exactly."
                ),
            },
        },
        "required": [
            "suspected_gap_concept_id",
            "confidence",
            "reasoning",
            "evidence_basis",
            "question_source",
        ],
    },
}

_INVESTIGATIVE_TOOLS = [
    _GET_PREREQS_TOOL,
    _PULL_QUESTION_TOOL,
    _GENERATE_QUESTION_TOOL,
    _SUBMIT_DIAGNOSIS_TOOL,
]


@lru_cache
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=get_settings().llm_api_key)


def _opening_prompt(
    concept: Concept, question: Question, answer: Answer, evaluation: EvaluationResult
) -> str:
    return (
        f"CONCEPT UNDER TEST: {concept.name} (id: {concept.id})\n"
        f"{concept.summary}\n\n"
        f"QUESTION ASKED:\n{question.prompt}\n\n"
        f"STUDENT ANSWER:\n{answer.text}\n\n"
        f"EVALUATOR'S FINDING (what the answer was missing or got wrong):\n"
        f"{evaluation.explanation}\n\n"
        "Diagnose which concept the misunderstanding stems from, and produce a question that "
        "isolates it."
    )


def diagnose(
    concept: Concept,
    graph: DependencyGraph,
    question: Question,
    answer: Answer,
    evaluation: EvaluationResult,
) -> DiagnosisResult:
    """Given a wrong answer on `concept`, find the prerequisite most likely at fault
    and produce a targeted question that probes it.

    Runs a bounded tool-calling loop (`_MAX_TURNS` round-trips). The model investigates the
    prerequisite chain, then must call `submit_diagnosis`; that call is rejected unless it
    carries "high" confidence, except on the final turn, where a submission is forced and
    accepted at whatever confidence it comes back with.
    """
    result, _ = _diagnose_with_trace(concept, graph, question, answer, evaluation)
    return result


def _diagnose_with_trace(
    concept: Concept,
    graph: DependencyGraph,
    question: Question,
    answer: Answer,
    evaluation: EvaluationResult,
) -> tuple[DiagnosisResult, DiagnosisTrace]:
    """`diagnose()` plus a record of how it got there.

    Internal seam, not part of the stable public API — the same pattern as
    `graph_builder._extract_raw_graph()` and `question_generator._generate_raw_for_concept()`.
    Most of this service's contract is trajectory rather than output: that it investigated
    before concluding, that the certainty gate actually held, that it stayed inside its
    budget. None of that is visible in the returned `DiagnosisResult`, so without this seam
    a diagnosis that burned five turns and three rejected submissions is indistinguishable
    from a clean first-turn hit — in tests and in production logs alike.
    """
    by_id = {c.id: c for c in graph.concepts}
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": _opening_prompt(concept, question, answer, evaluation)}
    ]
    tool_calls: list[tuple[str, dict[str, Any]]] = []
    rejected_submissions: list[dict[str, Any]] = []
    concepts_inspected: list[str] = []

    for turn in range(_MAX_TURNS):
        is_final = turn == _MAX_TURNS - 1
        response = _client().messages.create(
            model=_ORCHESTRATOR_MODEL,
            max_tokens=2048,
            temperature=0,
            system=_SYSTEM_PROMPT,
            messages=messages,
            # On the final turn only submit_diagnosis is offered, and it is forced, so the loop
            # always terminates with a real model judgment rather than a code-side fallback.
            tools=[_SUBMIT_DIAGNOSIS_TOOL] if is_final else _INVESTIGATIVE_TOOLS,
            tool_choice=(
                {"type": "tool", "name": "submit_diagnosis"}
                if is_final
                # Sequential investigation: each result should inform the next choice, and one
                # tool call per turn keeps the budget accounting exact.
                else {"type": "any", "disable_parallel_tool_use": True}
            ),
        )
        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            tool_calls.append((block.name, block.input))
            if block.name == "get_prereqs":
                concepts_inspected.append(block.input.get("concept_id", ""))
            if block.name == "submit_diagnosis":
                try:
                    result = _accept_diagnosis(block.input, concept, by_id, is_final)
                except _ToolError as exc:
                    rejected_submissions.append(block.input)
                    tool_results.append(_error_result(block.id, str(exc)))
                else:
                    trace = DiagnosisTrace(
                        turns_used=turn + 1,
                        tool_calls=tool_calls,
                        rejected_submissions=rejected_submissions,
                        concepts_inspected=concepts_inspected,
                        forced_final=is_final,
                        gap_outside_graph=bool(block.input.get("gap_is_outside_graph")),
                    )
                    return result, trace
                continue
            tool_results.append(_run_tool(block.id, block.name, block.input, by_id))

        if not tool_results:
            # tool_choice should make this unreachable, but don't hand the API an empty turn.
            messages.append(
                {"role": "user", "content": "Use one of the available tools to continue."}
            )
            continue
        messages.append({"role": "user", "content": tool_results})

    raise RuntimeError("diagnose() exhausted its turn budget without a forced submission")


def _run_tool(
    tool_use_id: str, name: str, payload: dict[str, Any], by_id: dict[str, Concept]
) -> dict[str, Any]:
    """Execute one investigative tool call and wrap its output as a tool_result block."""
    try:
        if name == "get_prereqs":
            result: Any = _get_prereqs(payload["concept_id"], by_id)
        elif name == "pull_question_from_storage":
            result = _pull_question_from_storage(payload["concept_id"], payload["focus"], by_id)
        elif name == "generate_question":
            result = _generate_question(
                payload["concept_id"],
                payload["focus"],
                by_id,
                bool(payload.get("allow_general_knowledge")),
            )
        else:
            raise _ToolError(f"Unknown tool '{name}'.")
    except _ToolError as exc:
        return _error_result(tool_use_id, str(exc))
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": json.dumps(result),
    }


def _error_result(tool_use_id: str, message: str) -> dict[str, Any]:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": message,
        "is_error": True,
    }


def _resolve(concept_id: str, by_id: dict[str, Concept]) -> Concept:
    target = by_id.get(concept_id)
    if target is None:
        raise _ToolError(f"Unknown concept id '{concept_id}'. Use ids exactly as returned.")
    return target


# --- tool implementations -----------------------------------------------------------------


def _get_prereqs(concept_id: str, by_id: dict[str, Concept]) -> list[dict[str, str]]:
    """The concept's immediate prerequisites, each with the quote justifying that dependency."""
    target = _resolve(concept_id, by_id)
    return [
        {
            "id": dep_id,
            "name": by_id[dep_id].name,
            "summary": by_id[dep_id].summary,
            "evidence": target.evidence.get(dep_id, ""),
        }
        for dep_id in target.depends_on
        if dep_id in by_id
    ]


def _pull_question_from_storage(
    concept_id: str, focus: str, by_id: dict[str, Concept]
) -> dict[str, Any]:
    """Whether an existing question for this concept already targets `focus`."""
    target = _resolve(concept_id, by_id)
    match = _find_matching_question(target.questions, focus)
    if match is None:
        return {"match": None}
    return {"match": {"id": match.id, "prompt": match.prompt}}


def _generate_question(
    concept_id: str,
    focus: str,
    by_id: dict[str, Concept],
    allow_general_knowledge: bool = False,
) -> RawQuestion:
    target = _resolve(concept_id, by_id)
    return _generate_raw_question(target, focus, allow_general_knowledge)


# --- nested LLM calls ---------------------------------------------------------------------

_MATCH_SYSTEM_PROMPT = """You decide whether an existing assessment question already targets a
specific understanding gap.

You will be given a description of a deficiency — what a student failed to demonstrate — and a
list of candidate questions about the same concept. Return the id of the one question that would
directly surface that specific deficiency if the student still holds it.

Be strict. A question that covers the same concept but tests a different facet of it is NOT a
match: answering it correctly would not rule the deficiency out. Only match when the question
would actually expose this gap. If no candidate does, return an empty string."""

_MATCH_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "match_question_id": {
                "type": "string",
                "description": "Id of the matching question, or an empty string if none matches.",
            },
            "reasoning": {"type": "string"},
        },
        "required": ["match_question_id", "reasoning"],
        "additionalProperties": False,
    },
}


def _find_matching_question(candidates: list[Question], focus: str) -> Question | None:
    """Judge whether any candidate question already adequately targets `focus`.

    A narrowly-scoped nested LLM call: whether a question "precisely isolates" a deficiency is a
    semantic judgment (a question can share a topic with the deficiency while testing a different
    facet of it entirely), so keyword overlap is not good enough. Returns the matching question,
    or None if no candidate targets the deficiency.
    """
    if not candidates:
        return None
    payload = {
        "deficiency": focus,
        "candidates": [{"id": q.id, "question": q.prompt} for q in candidates],
    }
    response = _client().messages.create(
        model=_JUDGE_MODEL,
        max_tokens=512,
        temperature=0,
        system=_MATCH_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": json.dumps(payload)}],
        output_config={"format": _MATCH_SCHEMA},
    )
    text = next(block.text for block in response.content if block.type == "text")
    matched_id = json.loads(text)["match_question_id"]
    return next((q for q in candidates if q.id == matched_id), None)


_GENERATE_SYSTEM_PROMPT = """You are an expert tutor writing a single diagnostic question.

You will be given a concept, its evidence text, and a specific deficiency a student appears to
have. Write one question that would surface that deficiency: if the student holds the
misunderstanding, they should answer it wrong; if they do not, they should answer it right.

## Output format

Return only valid JSON. No preamble, no explanation, no markdown fences.

{
  "question": "string",
  "expected_answer": "the ideal student response to this question, in prose",
  "grounding": "the evidence text a correct answer is grounded in"
}

## Rules

1. Ground the question strictly in the provided evidence text. Do not draw on general knowledge
   beyond what is stated.
2. Do not reveal the answer in the question itself. Never restate, paraphrase, or quote the
   concept's evidence text inside the question — the student must supply that understanding, and
   a question that contains it tests nothing.
3. Target the stated deficiency specifically, not the concept in general.
4. Ask exactly one question. Do not bundle multiple asks into one prompt.
5. Treat the evidence text as atomic: quote it in the "grounding" field in full, from start to
   end. Never truncate mid-clause or drop a trailing sentence, even if part of it seems
   redundant.
6. Write an "expected_answer": the ideal student response to your question, in prose, as a
   strong student would write it. A separate evaluator grades real answers by checking which
   parts of this one they cover, and it sees only the question, this text, and the student's
   answer — not the evidence. So state the substance in full and never point at something it
   cannot see ("matches the evidence"). Derive it strictly from the evidence, and make it
   target the stated deficiency: a student who writes this answer should not have that gap.
   If a correct answer is the student's own example or reasoning rather than a restatement,
   write what any valid answer must demonstrate instead of one specific expected answer."""

_GENERATE_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "expected_answer": {"type": "string"},
            "grounding": {"type": "string"},
        },
        "required": ["question", "expected_answer", "grounding"],
        "additionalProperties": False,
    },
}


_GENERAL_KNOWLEDGE_ADDENDUM = """

## Override for this request

The gap being probed is background knowledge the source material never teaches, so rules 1
and 5 above do not apply here: draw on general knowledge of the subject, and put a short
plain-language statement of the background being tested in "grounding" instead of a quote.
Everything else still holds — one question, no giveaway, targeted at the stated deficiency."""


def _generate_raw_question(
    concept: Concept, focus: str, allow_general_knowledge: bool = False
) -> RawQuestion:
    """Write one diagnostic question isolating `focus` within `concept`, plus the model answer
    the evaluator will grade real answers against.

    Grounded only in the concept's own evidence anchor (its `summary`), which must not leak into
    the question text — it belongs in `expected_answer_notes` for the evaluator, not in the
    prompt the student sees.
    """
    payload = {
        "concept": {"id": concept.id, "name": concept.name, "evidence": concept.summary},
        "deficiency": focus,
    }
    system = _GENERATE_SYSTEM_PROMPT + (
        _GENERAL_KNOWLEDGE_ADDENDUM if allow_general_knowledge else ""
    )
    response = _client().messages.create(
        model=_GENERATOR_MODEL,
        max_tokens=1024,
        temperature=0,
        system=system,
        messages=[{"role": "user", "content": json.dumps(payload)}],
        output_config={"format": _GENERATE_SCHEMA},
    )
    text = next(block.text for block in response.content if block.type == "text")
    data = json.loads(text)
    return {
        "question": data["question"],
        "expected_answer": data["expected_answer"],
        "grounding": data["grounding"],
    }


# --- diagnosis assembly -------------------------------------------------------------------


def _accept_diagnosis(
    payload: dict[str, Any],
    concept: Concept,
    by_id: dict[str, Concept],
    is_final: bool,
) -> DiagnosisResult:
    """Build the DiagnosisResult, or raise _ToolError to reject the submission.

    The confidence gate lives here rather than in the prompt: below "high" the submission is
    refused outright and the model has to keep investigating. On the final turn nothing is
    rejected — the loop must terminate — so each check degrades to a best-effort repair instead.
    """
    if not is_final and payload.get("confidence") != "high":
        raise _ToolError(
            "Rejected: confidence must be 'high' to submit. Keep investigating with "
            "get_prereqs until you can connect a specific element of the evaluator's finding "
            "to specific wording in a concept's evidence."
        )

    suspect_id = payload.get("suspected_gap_concept_id", "")
    suspect = by_id.get(suspect_id)
    if suspect is None:
        if not is_final:
            raise _ToolError(
                f"Rejected: '{suspect_id}' is not a concept in this graph. Diagnose one of the "
                "ids returned by get_prereqs, or the concept under test itself."
            )
        # Forced turn with an id that isn't in the graph — fall back to the concept under test
        # so the caller still gets a usable result.
        suspect = concept

    return DiagnosisResult(
        suspected_gap_concept_id=suspect.id,
        reasoning=_fold_reasoning(payload),
        targeted_question=_resolve_targeted_question(payload, suspect, is_final),
    )


def _resolve_targeted_question(
    payload: dict[str, Any], suspect: Concept, is_final: bool
) -> Question:
    """Pick the existing question the model chose, or build one from the text it wrote.

    Raises _ToolError when the submission didn't carry a usable question, so the model can fix
    that specific problem. On the final turn one is synthesized instead, since there is no
    further turn in which to ask.
    """
    if payload.get("question_source") == "storage":
        question_id = payload.get("question_id") or ""
        existing = next((q for q in suspect.questions if q.id == question_id), None)
        if existing is not None:
            return existing
        if not is_final:
            raise _ToolError(
                f"Rejected: question_source 'storage' but '{question_id}' is not a question on "
                f"'{suspect.id}'. Use an id from pull_question_from_storage, or generate one."
            )

    prompt = (payload.get("question_text") or "").strip()
    expected_answer = (payload.get("expected_answer") or "").strip()
    grounding = (payload.get("grounding") or "").strip()
    if not prompt:
        if not is_final:
            raise _ToolError(
                "Rejected: question_source 'generated' requires question_text, its "
                "expected_answer, and the grounding it is based on. Call generate_question "
                "first."
            )
        raw = _generate_raw_question(suspect, payload.get("evidence_basis", "") or suspect.name)
        prompt = raw["question"]
        expected_answer, grounding = raw["expected_answer"], raw["grounding"]

    return Question(
        id=_next_diagnostic_id(suspect),
        concept_id=suspect.id,
        prompt=prompt,
        expected_answer_notes=format_answer_notes(expected_answer, grounding or suspect.summary),
    )


def _next_diagnostic_id(suspect: Concept) -> str:
    """Numbered `{concept_id}:diagnosticN` id.

    Numbered rather than a bare `:diagnostic` suffix because a concept can be diagnosed more than
    once in a session with a different gap each time; a fixed suffix would collide, and the
    router dedupes by id — it would silently keep serving the first question's rubric.
    """
    prefix = f"{suspect.id}:diagnostic"
    taken = sum(1 for q in suspect.questions if q.id.startswith(prefix))
    return f"{prefix}{taken + 1}"


_OUTSIDE_GRAPH_NOTICE = (
    "Note: no prerequisite in this chapter accounts for the gap, so the diagnosis below "
    "draws on general background knowledge rather than the chapter's own material."
)


def _fold_reasoning(payload: dict[str, Any]) -> str:
    """Flatten the submission into the single `reasoning` string DiagnosisResult carries.

    `reasoning` is surfaced to the student through the answer endpoint, so it is also where
    a diagnosis discloses that it left the source material — leading with the notice rather
    than burying it, since a student should know when they are being told something the
    chapter never claimed.
    """
    parts = []
    if payload.get("gap_is_outside_graph"):
        parts.append(_OUTSIDE_GRAPH_NOTICE)
    parts.append(payload.get("reasoning", "").strip())
    basis = payload.get("evidence_basis", "").strip()
    if basis:
        parts.append(f"Evidence: {basis}")
    confidence = payload.get("confidence")
    if confidence != "high":
        parts.append(f"(Submitted at {confidence} confidence — turn budget exhausted.)")
    return "\n\n".join(part for part in parts if part)
