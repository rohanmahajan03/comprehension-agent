"""Shared scaffolding for the question_generator regression suite.

Scores the real `question_generator._generate_raw_for_concept()` against the golden
data in golden.py, per concept, five ways — two on the question it writes, two on the
model answer it writes for that question, and one on the grounding quote behind both:

1. Type-set recall (deterministic, set comparison on the `type` label only) — for
   each concept, does the generator produce every question type that's genuinely
   applicable to it (GOLDEN_TYPES in golden.py), or does it default to a lazy subset?
   No question text is involved and no LLM call is needed: question_generator.py's
   own prompt (rule 3) grants it real freedom in framing and which types to use per
   concept, so there's no single "correct" question to compare against — what *is*
   checkable without picking a winner is whether it explores the full space of types
   that genuinely fit, which is exactly GOLDEN_TYPES's editorial judgment. This
   replaced an earlier version that additionally compared generated question *text*
   to one hand-picked reference question per type via an LLM-judged similarity score
   (see conversation/PR history) — dropped because that conflated "phrased
   differently than my example" with "wrong", which the generator's own stated
   freedom makes a poor bar.
2. Source citation and assembly (deterministic, string comparison) — the model cites
   the passages behind each question by `id` and `_generate_raw_for_concept()` joins
   their exact text into `grounding`, so verbatim fidelity holds by construction. This
   checks what can still break: every cited id names a passage that was actually sent,
   at least one is cited, and `grounding` is exactly those passages joined. The last
   clause is the standing guard — it fails loudly if a refactor ever lets model-typed
   text back into that field. (It replaced truncation and token-coverage checks that
   were needed when the model retyped passages itself and reproducibly corrupted the
   same sentence run to run; citing by id removed the failure mode outright rather than
   making it less likely.) Passage construction is imported from
   `question_generator.source_passages()`, not re-derived here, so the suite cannot
   drift from what the generator actually sends.
3. Evidence basis (LLM-judged, `claude-haiku-4-5`) — a lightweight, per-question
   binary check: is the question ITSELF (not its self-reported `grounding` field —
   check 2 already covers that) answerable using only the evidence anchors given, no
   outside domain knowledge required? Deliberately "weak" (a yes/no + one-sentence
   reasoning, not a rubric or a score) and run on every generated question, not just
   ones matched to a golden reference, since there's no golden reference question
   text anymore. **The bar is type-dependent**, and the question's `type` is passed to
   the judge for that reason. For the recall types (conceptual_correctness,
   conceptual_distinction, enumeration_completeness) the answer lives in the evidence,
   so the bar is direct restatement or one obvious inferential step. The constructive
   types (open_ended_example, applied_reasoning) deliberately ask the student to
   produce something the evidence does NOT contain — a live run showed the judge
   faulting an open_ended_example question because "the evidence does not provide a
   concrete scenario", which is a standard that type can never meet — so for those the
   judge asks whether the evidence supplies the *principle* the student reasons from
   (the mechanism, rule, or cause-and-effect a correct answer applies), not the
   finished example. It still fails them when the evidence gives only an outcome or a
   bare definition with no mechanism behind it, which is the real rule-4 violation this
   check exists to catch; the type-awareness narrows the bar, it doesn't remove it.

Checks 4 and 5 cover the *answer* side. `question_generator` doesn't only write
questions — each one carries an `expected_answer`, the model response that becomes
`Question.expected_answer_notes` and is the entire rubric `evaluator.py` grades real
student answers against. A question can be perfectly well-formed and still ship an
unusable rubric, and until these existed nothing tested that half of the output:

4. Expected-answer gradeability (deterministic, string checks) — catches shapes the
   evaluator structurally cannot grade against no matter how good the content is:
   too short to state what an answer contains, deferring to context the evaluator
   never receives ("as the passage states" — it gets the question, the expected
   answer, and the student's answer, and nothing else), or a verbatim copy of the
   `grounding` quote. The last is the regression that motivated the field: before it
   existed, `expected_answer_notes` *was* the source quote, which says where a
   question came from rather than what an answer needs.
5. Answer quality (LLM-judged, `claude-haiku-4-5`) — does the `expected_answer`
   actually and completely answer its own question, consistent with the evidence and
   standing on its own for a grader who never sees that evidence? The judge is told
   two allowances so it doesn't punish correct behavior: describing what any valid
   answer must demonstrate is right for open_ended_example/applied_reasoning (where
   the correct answer is the student's own), and closely restating the evidence is
   right for conceptual_correctness (where the ideal answer largely is that).

score_case() is lru_cache'd so the assertions in test_case3.py share one run (11
question_generator calls + two judge calls per generated question — one for evidence
basis, one for answer quality) instead of re-running the real API per assertion.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache

import anthropic

from app.config import get_settings
from app.models import DependencyGraph
from app.services import question_generator
from app.services.question_generator import RawQuestion, SourcePassage, source_passages

from .golden import CASE_3_QUESTIONS, QuestionGoldenCase

# Aggregate pass/fail bar for type-set recall across all 11 concepts (pooled: total
# golden (concept, type) slots matched / total golden slots, not averaged per-concept).
TYPE_RECALL_THRESHOLD = 0.7
# Aggregate pass/fail bar for the fraction of generated questions judged evidence-based.
EVIDENCE_BASIS_THRESHOLD = 0.85
# Aggregate pass/fail bar for the fraction of expected_answers judged to actually answer
# their own question.
ANSWER_QUALITY_THRESHOLD = 0.9
# An expected_answer shorter than this can't state what a correct answer contains in any
# usable way — it's a label, not a model answer.
MIN_EXPECTED_ANSWER_CHARS = 40

# Prose that defers to context the evaluator never receives. evaluator.py is handed the
# question, this text, and the student's answer — not the source passage and not the
# concept graph — so "as the passage states" is an instruction it cannot follow.
_ANSWER_POINTER_RE = re.compile(
    r"\b(?:the\s+)?(?:evidence|passage|source\s+text|excerpt|grounding)\b"
    r"|\bas\s+(?:described|stated|shown|mentioned)\s+(?:above|below|earlier|previously)\b",
    re.IGNORECASE,
)

_EVIDENCE_BASIS_JUDGE_MODEL = "claude-haiku-4-5"

_EVIDENCE_BASIS_SYSTEM_PROMPT = """You are checking whether a quiz question can be answered using only a given set of evidence passages.

You will be given EVIDENCE (excerpts about a textbook concept and the concepts it relates to), a QUESTION that is supposed to be answerable from that evidence alone, and the question's TYPE.

The standard depends on the type, because two of the five types deliberately ask the student to produce something the evidence does not contain.

## Recall types — conceptual_correctness, conceptual_distinction, enumeration_completeness

For these the answer itself lives in the evidence.

Grounded if a student who has read *only* this evidence, and nothing else about the topic, could construct a complete answer by direct restatement or a single obvious inferential step from what the evidence explicitly says. Terse evidence is fine — a one-sentence summary can fully ground a question if it directly states the answer, even without rich narrative detail or a worked example.

NOT grounded if answering requires a specific outside domain fact, mechanism, or piece of terminology that the evidence never states and that isn't a direct, obvious consequence of what it does state. In particular, a "why" question is not grounded when the evidence asserts an outcome but never gives the reason behind it.

Example: if the evidence says "a hash index can't answer range queries efficiently" as a stated fact, asking WHAT that limitation is is grounded. Asking WHY it exists is NOT, unless the evidence also explains the mechanism — that hash functions don't preserve key ordering is outside knowledge the evidence never gives.

## Constructive types — open_ended_example, applied_reasoning

These ask the student to supply their own example, or to reason about a scenario they have not seen before. The finished answer is therefore NOT in the evidence by design, and its absence is not a defect. Do not fault such a question for the evidence lacking a worked example, a concrete scenario, or the student's specific conclusion — that is precisely what the student is being asked to produce.

Judge instead whether the evidence supplies the *principle* the student reasons from: the mechanism, rule, or cause-and-effect a correct answer would apply.

Grounded if the evidence states that underlying mechanism and the question asks the student to apply it to a new case. It does not matter that the scenario, example, or phrasing never appears in the evidence.

NOT grounded if the evidence gives only an outcome, a definition, or a bare fact with no mechanism behind it, leaving the student nothing to reason from without importing outside knowledge — or if answering needs a comparison, quantity, or alternative the evidence never supplies.

## Answer

Answer only: is this question grounded per the standard for its type?

Return only valid JSON, no preamble, no markdown fences:
{"grounded": <true or false>, "reasoning": "<one sentence>"}"""

_EVIDENCE_BASIS_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "grounded": {"type": "boolean"},
            "reasoning": {"type": "string"},
        },
        "required": ["grounded", "reasoning"],
        "additionalProperties": False,
    },
}

@lru_cache
def _judge_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=get_settings().llm_api_key)


def judge_evidence_basis(
    question_text: str, question_type: str, evidence_context: str
) -> tuple[bool, str]:
    """Ask claude-haiku-4-5 whether `question_text` is answerable using only
    `evidence_context`, judged against the standard for its `question_type`.
    Returns (grounded, one-sentence reasoning)."""
    prompt = (
        f"EVIDENCE:\n{evidence_context}\n\n"
        f"TYPE:\n{question_type}\n\n"
        f"QUESTION:\n{question_text}"
    )
    response = _judge_client().messages.create(
        model=_EVIDENCE_BASIS_JUDGE_MODEL,
        max_tokens=256,
        temperature=0,
        system=_EVIDENCE_BASIS_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        output_config={"format": _EVIDENCE_BASIS_SCHEMA},
    )
    text = next(block.text for block in response.content if block.type == "text")
    data = json.loads(text)
    return bool(data["grounded"]), data["reasoning"]


def _normalize_ws(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    # Claude renders em/en dashes with surrounding spaces; source text in
    # graph_golden_set.md uses them unspaced. Normalize both so that's never the
    # reason a verbatim check fails.
    return re.sub(r"\s*([—–])\s*", r"\1", s)


_ANSWER_QUALITY_SYSTEM_PROMPT = """You are checking whether a model answer correctly and completely answers its own question.

You will be given EVIDENCE (excerpts about a textbook concept), a QUESTION, and the EXPECTED ANSWER a tutor wrote as the ideal student response to that question. This expected answer is later handed to a grader, which sees only the question, the expected answer, and a real student's answer — never the evidence — and grades by checking which parts of the expected answer the student covered.

An expected answer is good if it (a) actually answers the question that was asked, rather than a related one, (b) is consistent with the evidence and adds nothing the evidence does not support, and (c) stands on its own as a statement of what a correct answer contains, so a grader with no access to the evidence could use it.

An expected answer is NOT good if it answers a different question, contradicts or overreaches the evidence, is too vague to distinguish a correct student answer from a wrong one, or merely describes the topic or where the question came from instead of answering it.

Two specific allowances — do not penalize either:
- For questions asking for the student's own example or their reasoning about a new scenario, the correct answer is the student's own and cannot be pinned to one specific response. Describing what any valid answer must demonstrate is the right form here, and is good.
- Restating the evidence closely is fine when the question asks the student to explain the concept, since there the ideal answer largely is the evidence in the student's own words.

Answer only: is this expected answer good per that standard?

Return only valid JSON, no preamble, no markdown fences:
{"answers_question": <true or false>, "reasoning": "<one sentence>"}"""

_ANSWER_QUALITY_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "answers_question": {"type": "boolean"},
            "reasoning": {"type": "string"},
        },
        "required": ["answers_question", "reasoning"],
        "additionalProperties": False,
    },
}


def judge_answer_quality(
    question_text: str, expected_answer: str, evidence_context: str
) -> tuple[bool, str]:
    """Ask claude-haiku-4-5 whether `expected_answer` correctly answers `question_text`
    given `evidence_context`. Returns (answers_question, one-sentence reasoning)."""
    prompt = (
        f"EVIDENCE:\n{evidence_context}\n\n"
        f"QUESTION:\n{question_text}\n\n"
        f"EXPECTED ANSWER:\n{expected_answer}"
    )
    response = _judge_client().messages.create(
        model=_EVIDENCE_BASIS_JUDGE_MODEL,
        max_tokens=256,
        temperature=0,
        system=_ANSWER_QUALITY_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        output_config={"format": _ANSWER_QUALITY_SCHEMA},
    )
    text = next(block.text for block in response.content if block.type == "text")
    data = json.loads(text)
    return bool(data["answers_question"]), data["reasoning"]


@dataclass(frozen=True)
class AnswerQualityJudgment:
    concept_id: str
    question: RawQuestion
    answers_question: bool
    reasoning: str


@dataclass(frozen=True)
class EvidenceBasisJudgment:
    concept_id: str
    question: RawQuestion
    grounded: bool
    reasoning: str


@dataclass(frozen=True)
class CaseResult:
    case: QuestionGoldenCase
    graph: DependencyGraph
    raw_by_concept: dict[str, list[RawQuestion]]
    source_texts_by_concept: dict[str, list[str]]
    passages_by_concept: dict[str, list[SourcePassage]]
    evidence_basis_judgments: list[EvidenceBasisJudgment]
    answer_quality_judgments: list[AnswerQualityJudgment]

    @property
    def missed_types(self) -> list[tuple[str, str]]:
        """(concept_id, type) pairs from GOLDEN_TYPES that the generator didn't
        produce for that concept."""
        missed = []
        for slug, golden_types in self.case.golden_types.items():
            concept_id = f"{self.case.doc_id}:{slug}"
            generated_types = {q["type"] for q in self.raw_by_concept.get(concept_id, [])}
            missed.extend((concept_id, t) for t in golden_types if t not in generated_types)
        return missed

    @property
    def type_recall(self) -> float:
        total = sum(len(types) for types in self.case.golden_types.values())
        if total == 0:
            return 1.0
        return (total - len(self.missed_types)) / total

    @property
    def ungrounded_questions(self) -> list[EvidenceBasisJudgment]:
        return [j for j in self.evidence_basis_judgments if not j.grounded]

    @property
    def evidence_basis_rate(self) -> float:
        if not self.evidence_basis_judgments:
            return 1.0
        grounded = sum(1 for j in self.evidence_basis_judgments if j.grounded)
        return grounded / len(self.evidence_basis_judgments)

    @property
    def grounding_violations(self) -> list[str]:
        """Questions whose grounding doesn't correspond to the passages actually sent.

        Deterministic, no LLM call. The model now cites passages by id and
        `_generate_raw_for_concept()` assembles `grounding` from those exact strings, so
        verbatim fidelity is structural rather than probabilistic — the truncation and
        token-coverage checks this used to run cannot fail by construction any more. (They
        existed because the model retyped passages and reproducibly corrupted the same
        sentence across runs; citing by id removed the failure mode rather than reducing
        its odds.) What can still go wrong is selection and assembly, which is what this
        now asserts: every cited id names a real passage, at least one is cited, and the
        assembled text is exactly those passages joined. The assembly clause is the guard
        that matters going forward — it fails loudly if a refactor ever lets model-typed
        text back into this field.
        """
        violations = []
        for concept_id, raws in self.raw_by_concept.items():
            text_by_id = {p["id"]: p["text"] for p in self.passages_by_concept[concept_id]}
            for q in raws:
                label = f"{concept_id} [{q['type']}]"
                unknown = [sid for sid in q["source_ids"] if sid not in text_by_id]
                if unknown:
                    violations.append(
                        f"{label}: cites source id(s) that were never sent: {unknown!r}"
                    )
                    continue
                if not q["source_ids"]:
                    violations.append(f"{label}: cites no source passage at all")
                    continue
                expected = "\n\n".join(text_by_id[sid] for sid in q["source_ids"])
                if q["grounding"] != expected:
                    violations.append(
                        f"{label}: grounding is not the verbatim join of its cited "
                        f"passages {q['source_ids']!r} — got {q['grounding']!r}"
                    )
        return violations

    @property
    def expected_answer_violations(self) -> list[str]:
        """Model answers the evaluator structurally cannot grade against.

        Deterministic, no LLM call. `expected_answer` becomes `Question.expected_answer_notes`
        verbatim (see `question_generator.format_answer_notes`), which evaluator.py labels
        `RUBRIC:` and grades element by element. So this catches the shapes that leave it
        with nothing gradeable, regardless of whether the content is otherwise right:

        - too short to state what an answer contains,
        - deferring to context the evaluator never receives ("as the passage states"),
        - a verbatim copy of the `grounding` quote. That last one is the exact regression
          that motivated this field: before it existed, `expected_answer_notes` *was* the
          source quote, which describes where the question came from rather than what an
          answer needs. A close paraphrase of the evidence is legitimate (for
          conceptual_correctness the ideal answer largely is the evidence restated), so
          this only fires on an exact match after whitespace normalization.
        """
        violations = []
        for concept_id, raws in self.raw_by_concept.items():
            for q in raws:
                answer, label = q["expected_answer"].strip(), f"{concept_id} [{q['type']}]"
                if len(answer) < MIN_EXPECTED_ANSWER_CHARS:
                    violations.append(
                        f"{label}: expected_answer is {len(answer)} chars "
                        f"(< {MIN_EXPECTED_ANSWER_CHARS}): {answer!r}"
                    )
                    continue
                if _ANSWER_POINTER_RE.search(answer):
                    violations.append(
                        f"{label}: expected_answer defers to context the evaluator cannot "
                        f"see: {answer!r}"
                    )
                    continue
                if _normalize_ws(answer) == _normalize_ws(q["grounding"]):
                    violations.append(
                        f"{label}: expected_answer is a verbatim copy of grounding — a "
                        f"source quote, not a model answer: {answer!r}"
                    )
        return violations

    def expected_answer_violations_message(self) -> str:
        return (
            "generated questions whose expected_answer the evaluator could not grade "
            "against:\n" + "\n".join(self.expected_answer_violations)
        )

    @property
    def unanswered_questions(self) -> list[AnswerQualityJudgment]:
        return [j for j in self.answer_quality_judgments if not j.answers_question]

    @property
    def answer_quality_rate(self) -> float:
        if not self.answer_quality_judgments:
            return 1.0
        good = sum(1 for j in self.answer_quality_judgments if j.answers_question)
        return good / len(self.answer_quality_judgments)

    def answer_quality_message(self) -> str:
        header = f"answer-quality rate {self.answer_quality_rate:.2f} < {ANSWER_QUALITY_THRESHOLD}"
        lines = "\n".join(
            f"  - {j.concept_id} [{j.question['type']}] ({j.reasoning})\n"
            f"    question: {j.question['question']!r}\n"
            f"    expected_answer: {j.question['expected_answer']!r}"
            for j in self.unanswered_questions
        )
        return f"{header}\nexpected_answers that don't correctly answer their own question:\n{lines}"

    def missed_types_message(self) -> str:
        lines = ", ".join(f"{cid} ({t})" for cid, t in self.missed_types)
        total = sum(len(types) for types in self.case.golden_types.values())
        return f"type recall {self.type_recall:.2f} < {TYPE_RECALL_THRESHOLD} — missed {len(self.missed_types)}/{total}: {lines}"

    def evidence_basis_message(self) -> str:
        header = f"evidence-basis rate {self.evidence_basis_rate:.2f} < {EVIDENCE_BASIS_THRESHOLD}"
        lines = "\n".join(
            f"  - {j.concept_id} [{j.question['type']}] ({j.reasoning})\n"
            f"    question: {j.question['question']!r}"
            for j in self.ungrounded_questions
        )
        return f"{header}\nquestions judged not answerable from evidence alone:\n{lines}"

    def grounding_violations_message(self) -> str:
        return (
            "generated questions whose cited source passages or assembled grounding are "
            "wrong:\n" + "\n".join(self.grounding_violations)
        )


@lru_cache
def score_case() -> CaseResult:
    graph = CASE_3_QUESTIONS.build_graph()
    by_id = {c.id: c for c in graph.concepts}

    raw_by_concept: dict[str, list[RawQuestion]] = {}
    source_texts_by_concept: dict[str, list[str]] = {}
    passages_by_concept: dict[str, list[SourcePassage]] = {}
    for concept in graph.concepts:
        raw_by_concept[concept.id] = question_generator._generate_raw_for_concept(concept, by_id, graph)
        # Imported from question_generator rather than re-derived here, so the suite can
        # never disagree with the generator about which passages were actually sent.
        passages_by_concept[concept.id] = source_passages(concept, by_id, graph)
        source_texts_by_concept[concept.id] = [p["text"] for p in passages_by_concept[concept.id]]

    evidence_basis_judgments = [
        EvidenceBasisJudgment(
            concept_id,
            q,
            *judge_evidence_basis(
                q["question"], q["type"], " ".join(source_texts_by_concept[concept_id])
            ),
        )
        for concept_id, questions in raw_by_concept.items()
        for q in questions
    ]

    answer_quality_judgments = [
        AnswerQualityJudgment(
            concept_id,
            q,
            *judge_answer_quality(
                q["question"],
                q["expected_answer"],
                " ".join(source_texts_by_concept[concept_id]),
            ),
        )
        for concept_id, questions in raw_by_concept.items()
        for q in questions
    ]

    return CaseResult(
        case=CASE_3_QUESTIONS,
        graph=graph,
        raw_by_concept=raw_by_concept,
        source_texts_by_concept=source_texts_by_concept,
        passages_by_concept=passages_by_concept,
        evidence_basis_judgments=evidence_basis_judgments,
        answer_quality_judgments=answer_quality_judgments,
    )
