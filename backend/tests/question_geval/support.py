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

Check 6 covers *which concept* a question is about, which nothing else here does:

6. Target focus (LLM-judged, `claude-haiku-4-5`) — does the question assess the concept it
   was written for, or a neighbour that was only supplied as context? `source_passages()`
   deliberately sends prerequisites and siblings so `conceptual_distinction` is possible at
   all, and the prompt's "every evidence passage you may draw on" invites using them, but
   nothing before this asked whether the question stayed on its own concept. Two things
   break when it doesn't: the question wastes one of the target's slots testing a concept
   that already has its own question set, and — worse — it corrupts pipeline 2, where a
   wrong answer on X is taken to mean "the gap may lie in X's prerequisites" and is the
   signal `diagnoser.py` reasons from. Only questions for concepts that actually have
   neighbours are scored; a concept sent nothing but its own summary has nothing to drift
   onto, and including it would pad the rate with guaranteed passes.

   **This check currently fails, and that is the accurate reading, not a miscalibration.**
   First live run: 0.86, 4 of 28 at-risk questions off-target — a `write_ahead_log`
   question asking "how many physical disk writes does a single logical write result in",
   which is its *sibling* write_amplification's question; a `compaction` question that
   tests segmentation and the dependency rather than what compaction does; two more of the
   same shape. The judge is discriminating rather than rubber-stamping (0.86, not 1.00).

   **A prompt rule was tried and reverted.** Adding a rule 10 to `_SYSTEM_PROMPT`
   (prerequisites/siblings are context not subject matter, plus the "could a student answer
   this without understanding the target?" test, explicitly protecting
   conceptual_distinction) moved target focus 0.86 → 0.85 — no change within noise, and the
   *set* of off-target questions turned over almost completely, which says the drift is
   unstable rather than fixed. It also knocked evidence basis 0.94 → 0.82, below its own
   threshold. That is the same destabilization this prompt showed when rules 8-9 were added
   (see the grounding-fidelity history in CLAUDE.md), and the same lesson: a rule competing
   against a structural pull loses. The prompt is back to the exact text the 0.86 baseline
   was measured on.

   The structural read: every concept that drifts (`write_ahead_log`, `compaction`,
   `bloom_filter`, `hash_index`) has a thin summary of its own next to rich neighbour
   passages, so the most substantive question available to the model is grounded in a
   neighbour. The fix is more evidence for the target, not more instructions about the
   neighbours — which is the same conclusion the hand-added-concept problem reaches from
   the other direction.

score_case() is lru_cache'd so the assertions in test_case3.py share one run (11
question_generator calls + up to three judge calls per generated question — evidence
basis, answer quality, and target focus where the concept has neighbours) instead of
re-running the real API per assertion.
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
# Aggregate pass/fail bar for the fraction of questions that actually assess their own
# concept rather than a neighbour supplied as context. Provisional — set before the first
# live run of this check, so it is a guess at what good looks like, not a tightening of
# observed performance.
TARGET_FOCUS_THRESHOLD = 0.9
# An expected_answer shorter than this can't state what a correct answer contains in any
# usable way — it's a label, not a model answer.
MIN_EXPECTED_ANSWER_CHARS = 40
# `required_points` is the minimum bar, and prompt rule 10 asks for usually two to four. More
# than this and it has stopped being a bar and become a summary of expected_answer — which
# is the over-strict grading the field exists to prevent. Enumeration questions are exempt:
# every item in the set is its own point, and a set can legitimately be long.
MAX_REQUIRED_POINTS = 5

# Prose that defers to context the evaluator never receives. evaluator.py is handed the
# question, this text, and the student's answer — not the source passage and not the
# concept graph — so "as the passage states" is an instruction it cannot follow.
_ANSWER_POINTER_RE = re.compile(
    r"\b(?:the\s+)?(?:evidence|passage|source\s+text|excerpt|grounding)\b"
    r"|\bas\s+(?:described|stated|shown|mentioned)\s+(?:above|below|earlier|previously)\b",
    re.IGNORECASE,
)

def _required_points_violations(q: dict, label: str) -> list[str]:
    """Shapes of `required_points` the evaluator can't grade against as a bar.

    Part of check 4, and deterministic for the same reason: these are structural failures
    regardless of content. Whether each point is actually *essential* is a judgment call
    no string check can make; the live eval_geval run is what measures that.
    """
    points = [p.strip() for p in q["required_points"] if p.strip()]
    if not points:
        return [f"{label}: no required_points — the evaluator falls back to guessing the bar"]
    violations = []
    if q["type"] != "enumeration_completeness" and len(points) > MAX_REQUIRED_POINTS:
        violations.append(
            f"{label}: {len(points)} required_points (> {MAX_REQUIRED_POINTS}) — a summary "
            f"of the model answer, not a minimum bar: {points!r}"
        )
    for point in points:
        if _ANSWER_POINTER_RE.search(point):
            violations.append(
                f"{label}: required point defers to context the evaluator cannot see: {point!r}"
            )
        elif _normalize_ws(point) == _normalize_ws(q["expected_answer"]):
            violations.append(
                f"{label}: required point is the whole expected_answer, not one idea: {point!r}"
            )
    return violations


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


_TARGET_FOCUS_SYSTEM_PROMPT = """You are checking whether a quiz question actually assesses the concept it was written for.

You will be given a TARGET CONCEPT (its name and its own description), the NEIGHBOURING CONCEPTS supplied alongside it as context (its prerequisites, the passages linking them, and sibling concepts), a QUESTION written to assess the target, and the question's TYPE.

Neighbouring concepts are legitimate context. A question may mention one, contrast the target against it, or build on it. What it may not do is make a neighbour the actual subject: every neighbouring concept has its own separate question set, so a question whose correct answer is essentially a statement about a neighbour tests nothing about the target and duplicates questions that already exist elsewhere.

Apply this test: could a student answer this question correctly and completely without demonstrating any understanding of the TARGET concept? If yes, the question is off-target.

conceptual_distinction questions are *supposed* to involve a neighbour — the contrast is the point — and are on-target as long as a correct answer must say something about the target itself, not only about the neighbour.

Answer only: does this question assess the target concept?

Return only valid JSON, no preamble, no markdown fences:
{"on_target": <true or false>, "reasoning": "<one sentence>"}"""

_TARGET_FOCUS_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "on_target": {"type": "boolean"},
            "reasoning": {"type": "string"},
        },
        "required": ["on_target", "reasoning"],
        "additionalProperties": False,
    },
}


def judge_target_focus(
    question_text: str,
    question_type: str,
    target_name: str,
    target_text: str,
    neighbour_text: str,
) -> tuple[bool, str]:
    """Ask claude-haiku-4-5 whether `question_text` assesses the target concept rather
    than one of the neighbours sent as context. Returns (on_target, one-sentence reasoning)."""
    prompt = (
        f"TARGET CONCEPT: {target_name}\n{target_text}\n\n"
        f"NEIGHBOURING CONCEPTS (context only):\n{neighbour_text}\n\n"
        f"TYPE:\n{question_type}\n\n"
        f"QUESTION:\n{question_text}"
    )
    response = _judge_client().messages.create(
        model=_EVIDENCE_BASIS_JUDGE_MODEL,
        max_tokens=256,
        temperature=0,
        system=_TARGET_FOCUS_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        output_config={"format": _TARGET_FOCUS_SCHEMA},
    )
    text = next(block.text for block in response.content if block.type == "text")
    data = json.loads(text)
    return bool(data["on_target"]), data["reasoning"]


def _target_focus_context(passages: list[SourcePassage]) -> tuple[str, str]:
    """Split a concept's passages into (its own text, everything else) for the judge.

    The other checks flatten every passage into one blob, which is fine when the question
    is "is this answerable from the evidence". Here the whole question is *which* passage
    the question is about, so the roles have to survive into the prompt.

    A `prerequisite_link` passage goes on the target's side. It carries the prerequisite's
    name, but it is the chapter's sentence justifying why the *target* depends on that
    prerequisite, and it is very often the sentence that defines the target ("...storage
    engines often use additional Bloom filters"; "This effect ... is known as write
    amplification"). Filed under the neighbour, it made the judge read questions about
    the target's own definition as questions about the neighbour.
    """
    target = "\n".join(
        p["text"] if p["role"] == "target_concept"
        else f"[how it relates to {p['concept_name']}] {p['text']}"
        for p in passages
        if p["role"] in ("target_concept", "prerequisite_link")
    )
    neighbours = "\n".join(
        f"[{p['role']}: {p['concept_name']}] {p['text']}"
        for p in passages
        if p["role"] not in ("target_concept", "prerequisite_link")
    )
    return target, neighbours


@dataclass(frozen=True)
class TargetFocusJudgment:
    concept_id: str
    question: RawQuestion
    on_target: bool
    reasoning: str


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
    target_focus_judgments: list[TargetFocusJudgment]

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
                    continue
                violations.extend(_required_points_violations(q, label))
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

    @property
    def off_target_questions(self) -> list[TargetFocusJudgment]:
        return [j for j in self.target_focus_judgments if not j.on_target]

    @property
    def target_focus_rate(self) -> float:
        if not self.target_focus_judgments:
            return 1.0
        on_target = sum(1 for j in self.target_focus_judgments if j.on_target)
        return on_target / len(self.target_focus_judgments)

    def target_focus_message(self) -> str:
        header = f"target-focus rate {self.target_focus_rate:.2f} < {TARGET_FOCUS_THRESHOLD}"
        lines = "\n".join(
            f"  - {j.concept_id} [{j.question['type']}] ({j.reasoning})\n"
            f"    question: {j.question['question']!r}"
            for j in self.off_target_questions
        )
        return (
            f"{header}\nquestions that assess a neighbouring concept rather than their "
            f"own:\n{lines}"
        )

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

    target_focus_judgments: list[TargetFocusJudgment] = []
    for concept_id, questions in raw_by_concept.items():
        target_text, neighbour_text = _target_focus_context(passages_by_concept[concept_id])
        if not neighbour_text:
            # A concept with no prerequisites and no siblings was sent only its own
            # summary, so there is nothing for a question to drift onto. Scoring those
            # would pad the rate with guaranteed passes and hide movement in the
            # population this check actually exists to watch.
            continue
        for q in questions:
            target_focus_judgments.append(
                TargetFocusJudgment(
                    concept_id,
                    q,
                    *judge_target_focus(
                        q["question"],
                        q["type"],
                        by_id[concept_id].name,
                        target_text,
                        neighbour_text,
                    ),
                )
            )

    return CaseResult(
        case=CASE_3_QUESTIONS,
        graph=graph,
        raw_by_concept=raw_by_concept,
        source_texts_by_concept=source_texts_by_concept,
        passages_by_concept=passages_by_concept,
        evidence_basis_judgments=evidence_basis_judgments,
        answer_quality_judgments=answer_quality_judgments,
        target_focus_judgments=target_focus_judgments,
    )
