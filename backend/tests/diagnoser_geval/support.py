"""Shared scaffolding for the diagnoser regression suite.

Runs the real `diagnoser._diagnose_with_trace()` against each hand-curated case in
golden.py and scores it in three tiers, cheapest first. Loop mechanics — turn budget,
forced final turn, certainty gate, error recovery — are NOT here: they're deterministic
against a fake client, so they live in the free `tests/test_diagnoser_loop.py` where they
guard every commit instead of costing money.

**Tier 1 — invariants (deterministic, no judge).** Zero tolerance, because each is a
property that is either true or the service is broken:
  a. No answer leak — the suspect's `summary` must not surface in the targeted question's
     prompt. A question that hands the student the answer tests nothing, and this has been
     called load-bearing since the original stub's docstring without ever being checked.
     Verified as an exact substring *and* as a shared word run (`_leaked_span`), since a
     near-verbatim paraphrase leaks just as effectively as a copy.
  b. Reachability — the diagnosed concept must be the answered concept itself or reachable
     from it through `depends_on`. Diagnosing an unrelated concept is wrong no matter how
     convincing the reasoning sounds.
  c. Internal consistency — the targeted question belongs to the diagnosed concept, its id
     follows the `{concept_id}:{suffix}` convention, and it carries usable
     `expected_answer_notes` (the evaluator grades against that field, so the same bar
     question_geval applies to it applies here).
  d. Budget — `turns_used` never exceeds `_MAX_TURNS`.

**Tier 2 — diagnostic accuracy.** The core metric: did it name a concept in
`acceptable_suspects` (aggregate rate) and avoid every `forbidden_suspects` entry (zero
tolerance). Reported split by `hops_to_preferred`, which is the number that says whether
the agentic design earns its cost — if 1-hop cases pass and multi-hop cases fail, the loop
is doing no better than the old `depends_on[0]` stub it replaced.

**Tier 3 — quality (LLM-judged, `claude-haiku-4-5`).** Two narrow binary judgments, the
same tier of model question_geval uses for its mechanical comparisons:
  a. Does the targeted question actually probe the suspect? Guards against a correct
     suspect paired with an irrelevant question.
  b. Is the reasoning evidence-backed or merely plausible? The code gate can only enforce
     that the model *claimed* high confidence; whether the claim was earned needs a judge.
     This is the certainty requirement made observable.

`score_all()` is lru_cache'd so every assertion in test_diagnosis.py shares one execution
— that matters more here than in the other suites, since each case costs up to five
orchestrator turns plus nested generation and matching calls.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache

import anthropic

from app.config import get_settings
from app.models import Answer, Concept, DependencyGraph, DiagnosisResult, EvaluationResult
from app.services import diagnoser
from app.services.diagnoser import DiagnosisTrace

from .golden import CASES, DiagnosisCase, build_graph

# Aggregate share of cases whose diagnosis lands in `acceptable_suspects`.
# PROVISIONAL — set before the first live run and to be recalibrated against it, the way
# every threshold in question_geval was. Do not read the first run as a verdict on the
# diagnoser until this has been checked against what it actually scores.
ACCURACY_THRESHOLD = 0.75
# Aggregate share of targeted questions judged to actually probe their suspect concept.
QUESTION_RELEVANCE_THRESHOLD = 0.85
# Aggregate share of diagnoses whose reasoning is judged evidence-backed rather than generic.
REASONING_QUALITY_THRESHOLD = 0.75
# A shared run of this many words between a concept summary and a question prompt is a
# paraphrase of the answer, not incidental topical overlap.
LEAK_MIN_SHARED_WORDS = 8
# Mirrors question_geval: below this, expected_answer_notes states nothing gradeable.
MIN_EXPECTED_ANSWER_CHARS = 40

_JUDGE_MODEL = "claude-haiku-4-5"

_WORD_RE = re.compile(r"[a-z0-9]+")


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _leaked_span(summary: str, prompt: str, min_words: int = LEAK_MIN_SHARED_WORDS) -> str | None:
    """The longest run of `min_words`+ consecutive words the prompt copies from the summary.

    Word-run rather than bag-of-words on purpose: a question about a concept necessarily
    shares vocabulary with that concept's summary ("compaction", "segment"), so token
    overlap flags correct behavior. A contiguous run of eight words does not occur by
    coincidence — it is the answer being restated.
    """
    s_words, p_words = _words(summary), _words(prompt)
    if len(s_words) < min_words:
        return None
    prompt_joined = " ".join(p_words)
    longest = None
    for i in range(len(s_words) - min_words + 1):
        span = " ".join(s_words[i : i + min_words])
        if span in prompt_joined:
            # Extend greedily so the message shows the whole leak, not just its head.
            end = i + min_words
            while end < len(s_words) and " ".join(s_words[i : end + 1]) in prompt_joined:
                end += 1
            candidate = " ".join(s_words[i:end])
            if longest is None or len(candidate) > len(longest):
                longest = candidate
    return longest


def _reachable_from(concept_id: str, by_id: dict[str, Concept]) -> set[str]:
    """`concept_id` plus everything below it in the dependency chain."""
    seen, stack = {concept_id}, [concept_id]
    while stack:
        node = stack.pop()
        for dep in by_id[node].depends_on if node in by_id else []:
            if dep not in seen:
                seen.add(dep)
                stack.append(dep)
    return seen


@lru_cache
def _judge_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=get_settings().llm_api_key)


_BINARY_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "verdict": {"type": "boolean"},
            "reasoning": {"type": "string"},
        },
        "required": ["verdict", "reasoning"],
        "additionalProperties": False,
    },
}


def _judge(system_prompt: str, user_prompt: str) -> tuple[bool, str]:
    response = _judge_client().messages.create(
        model=_JUDGE_MODEL,
        max_tokens=256,
        temperature=0,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        output_config={"format": _BINARY_SCHEMA},
    )
    text = next(block.text for block in response.content if block.type == "text")
    data = json.loads(text)
    return bool(data["verdict"]), data["reasoning"]


_QUESTION_RELEVANCE_PROMPT = """You are checking whether a diagnostic question actually tests a specific concept.

A tutoring system decided a student's misunderstanding stems from one concept, and wrote a question meant to isolate it. You will be given the CONCEPT (its name and what it means) and the QUESTION.

The question is relevant if answering it correctly would demonstrate understanding of that specific concept — the concept is what the question is really testing, not merely a topic it touches in passing.

The question is NOT relevant if it tests a neighbouring or more general concept instead, if it is so broad that a student could answer it well without understanding this concept in particular, or if it only mentions the concept while actually asking about something else.

Judge relevance ONLY — whether this concept is what the question tests.

Ignore entirely whether the question gives away its own answer, restates the concept, or reuses wording from the description above. Whether a question leaks the answer is a separate check that has already run; it is not yours, and a question that leaks is still relevant if the concept is what it tests. Answer as though you never saw the question's phrasing overlap the concept's.

Also do not penalize a question for being hard, for being phrased as a scenario, or for asking the student to apply the concept rather than define it.

Answer only: does answering this question correctly demonstrate understanding of this concept?

Return only valid JSON, no preamble, no markdown fences:
{"verdict": <true or false>, "reasoning": "<one sentence>"}"""


_REASONING_QUALITY_PROMPT = """You are checking whether a diagnosis is backed by evidence or is merely a plausible assertion.

A tutoring system read an evaluator's finding about what a student's answer was missing, then concluded the misunderstanding stems from a particular prerequisite concept. You will be given the EVALUATOR FINDING, the SUSPECT CONCEPT with its supporting evidence, and the system's REASONING for the diagnosis.

The reasoning is evidence-backed if it connects something specific in the evaluator's finding — a particular element the answer omitted or got wrong — to something specific about the suspect concept. The chain from "the answer was missing X" to "therefore the student does not understand Y" must be visible and use the actual content of both, not just their names.

The reasoning is NOT evidence-backed if it is generic enough to apply to almost any wrong answer ("the student seems confused about the fundamentals", "this concept is a prerequisite so the gap is probably there"), if it merely restates that one concept depends on another without tying that to what the student actually got wrong, or if it names the concepts without engaging with what the answer omitted.

Judge only whether the reasoning is grounded. Do NOT judge whether the diagnosis is correct — a well-argued diagnosis that names the wrong concept still counts as evidence-backed here, and correctness is measured separately.

Answer only: is this reasoning evidence-backed?

Return only valid JSON, no preamble, no markdown fences:
{"verdict": <true or false>, "reasoning": "<one sentence>"}"""


def judge_question_relevance(question_prompt: str, suspect: Concept) -> tuple[bool, str]:
    return _judge(
        _QUESTION_RELEVANCE_PROMPT,
        f"CONCEPT:\n{suspect.name} — {suspect.summary}\n\nQUESTION:\n{question_prompt}",
    )


def _evidence_visible_for(suspect: Concept, graph: DependencyGraph) -> list[str]:
    """Every evidence quote the diagnoser could have seen concerning `suspect`.

    Evidence *about* a concept lives on its dependents, not on itself: `Concept.evidence`
    maps a concept's own prerequisites to the quote justifying each dependency, so the
    passage explaining why X matters to Y is stored on Y. `get_prereqs(Y)` is what surfaces
    it. Judging a diagnosis of X against only `X.evidence` therefore asks about the wrong
    passages entirely — it would fault the model for quoting text it was genuinely shown.
    """
    quotes = [
        dependent.evidence[suspect.id]
        for dependent in graph.concepts
        if suspect.id in dependent.evidence
    ]
    quotes += list(suspect.evidence.values())  # what suspect itself rests on
    return quotes


def judge_reasoning_quality(
    evaluation_explanation: str, suspect: Concept, reasoning: str, graph: DependencyGraph
) -> tuple[bool, str]:
    quotes = _evidence_visible_for(suspect, graph)
    evidence = "\n".join(f"- {q}" for q in quotes) or "(none)"
    return _judge(
        _REASONING_QUALITY_PROMPT,
        f"EVALUATOR FINDING:\n{evaluation_explanation}\n\n"
        f"SUSPECT CONCEPT:\n{suspect.name} — {suspect.summary}\n"
        f"Evidence passages concerning this concept:\n{evidence}\n\n"
        f"REASONING:\n{reasoning}",
    )


@dataclass(frozen=True)
class CaseScore:
    case: DiagnosisCase
    result: DiagnosisResult
    trace: DiagnosisTrace
    question_relevant: bool
    question_relevance_reasoning: str
    reasoning_grounded: bool
    reasoning_quality_reasoning: str

    @property
    def suspect_slug(self) -> str:
        return self.result.suspected_gap_concept_id.split(":", 1)[1]

    @property
    def is_acceptable(self) -> bool:
        return self.suspect_slug in self.case.acceptable_suspects

    @property
    def is_forbidden(self) -> bool:
        return self.suspect_slug in self.case.forbidden_suspects

    @property
    def is_preferred(self) -> bool:
        return self.suspect_slug == self.case.preferred_suspect

    @property
    def disclosed_outside_graph(self) -> bool:
        return self.trace.gap_outside_graph

    @property
    def reused_existing_question(self) -> bool:
        """Whether it reused a pipeline-1 question rather than generating a new one."""
        return ":diagnostic" not in self.result.targeted_question.id


@dataclass(frozen=True)
class SuiteResult:
    graph: DependencyGraph
    scores: list[CaseScore]

    # --- Tier 1: invariants -------------------------------------------------------------

    @property
    def invariant_violations(self) -> list[str]:
        by_id = {c.id: c for c in self.graph.concepts}
        violations = []
        for s in self.scores:
            label = f"{s.case.name} -> {s.suspect_slug}"
            question = s.result.targeted_question
            suspect = by_id.get(s.result.suspected_gap_concept_id)

            if suspect is None:
                violations.append(f"{label}: diagnosed a concept that is not in the graph")
                continue

            leak = _leaked_span(suspect.summary, question.prompt)
            if leak:
                violations.append(
                    f"{label}: question leaks the answer — it copies {leak!r} from the "
                    f"concept's summary"
                )
            if suspect.summary.strip() and suspect.summary.strip() in question.prompt:
                violations.append(f"{label}: question contains the suspect's summary verbatim")

            reachable = _reachable_from(s.case.answered_concept_id, by_id)
            if suspect.id not in reachable:
                violations.append(
                    f"{label}: suspect is not reachable via depends_on from "
                    f"{s.case.answered_concept}"
                )
            if question.concept_id != suspect.id:
                violations.append(
                    f"{label}: targeted question's concept_id is {question.concept_id!r}, "
                    f"not the diagnosed concept"
                )
            if question.id.rsplit(":", 1)[0] != suspect.id:
                violations.append(
                    f"{label}: question id {question.id!r} does not follow "
                    f"{{concept_id}}:{{suffix}}"
                )
            if len(question.expected_answer_notes.strip()) < MIN_EXPECTED_ANSWER_CHARS:
                violations.append(
                    f"{label}: expected_answer_notes is too short to grade against "
                    f"({len(question.expected_answer_notes.strip())} chars)"
                )
            if s.trace.turns_used > diagnoser._MAX_TURNS:
                violations.append(
                    f"{label}: used {s.trace.turns_used} turns, budget is {diagnoser._MAX_TURNS}"
                )
        return violations

    def invariant_violations_message(self) -> str:
        return "diagnoser invariants broken:\n" + "\n".join(self.invariant_violations)

    # --- Tier 2: accuracy ---------------------------------------------------------------

    @property
    def accuracy(self) -> float:
        return sum(s.is_acceptable for s in self.scores) / len(self.scores)

    @property
    def preferred_rate(self) -> float:
        return sum(s.is_preferred for s in self.scores) / len(self.scores)

    @property
    def forbidden_hits(self) -> list[CaseScore]:
        return [s for s in self.scores if s.is_forbidden]

    def accuracy_by_hops(self) -> dict[int, tuple[int, int]]:
        """hops -> (correct, total). The number that says whether drilling actually works."""
        out: dict[int, tuple[int, int]] = {}
        for s in self.scores:
            hit, total = out.get(s.case.hops_to_preferred, (0, 0))
            out[s.case.hops_to_preferred] = (hit + s.is_acceptable, total + 1)
        return dict(sorted(out.items()))

    def accuracy_message(self) -> str:
        misses = "\n".join(
            f"  - {s.case.name}: diagnosed {s.suspect_slug!r}, "
            f"acceptable were {sorted(s.case.acceptable_suspects)} "
            f"({s.case.hops_to_preferred} hop(s), {s.trace.turns_used} turns)\n"
            f"    reasoning: {s.result.reasoning.splitlines()[0][:160]}"
            for s in self.scores
            if not s.is_acceptable
        )
        return (
            f"diagnostic accuracy {self.accuracy:.2f} < {ACCURACY_THRESHOLD}\n"
            f"by hop depth: {self.accuracy_by_hops()}\n{misses}"
        )

    def forbidden_message(self) -> str:
        return "diagnosed a concept the student's answer demonstrably understood:\n" + "\n".join(
            f"  - {s.case.name}: diagnosed {s.suspect_slug!r}, forbidden are "
            f"{sorted(s.case.forbidden_suspects)}\n    reasoning: {s.result.reasoning[:200]}"
            for s in self.forbidden_hits
        )

    # --- the general-knowledge escape hatch ------------------------------------------

    @property
    def spurious_disclosures(self) -> list[CaseScore]:
        """Cases that claimed the gap was outside the graph when a prerequisite explains it.

        Asserted, unlike the reverse. The disclosure is shown to the student, so a false
        positive is user-visible noise that also teaches them to ignore a warning that is
        supposed to be rare. A false negative just leaves the pre-existing behavior in
        place, so it is reported rather than enforced — see `disclosure_recall`.
        """
        return [
            s for s in self.scores if s.disclosed_outside_graph and not s.case.expects_outside_graph
        ]

    @property
    def disclosure_recall(self) -> float | None:
        """Share of cases that wanted the escape hatch and got it. Reported, not asserted —
        this is a rare path with one case behind it, too thin to gate on."""
        wanted = [s for s in self.scores if s.case.expects_outside_graph]
        if not wanted:
            return None
        return sum(s.disclosed_outside_graph for s in wanted) / len(wanted)

    def spurious_disclosures_message(self) -> str:
        return (
            "diagnosed a gap as 'outside the graph' when a prerequisite explains it — this "
            "notice reaches the student, so it must stay rare:\n"
            + "\n".join(
                f"  - {s.case.name}: diagnosed {s.suspect_slug!r}\n"
                f"    reasoning: {s.result.reasoning[:220]}"
                for s in self.spurious_disclosures
            )
        )

    # --- Tier 3: judged quality ---------------------------------------------------------

    @property
    def question_relevance_rate(self) -> float:
        return sum(s.question_relevant for s in self.scores) / len(self.scores)

    @property
    def reasoning_quality_rate(self) -> float:
        return sum(s.reasoning_grounded for s in self.scores) / len(self.scores)

    def question_relevance_message(self) -> str:
        return (
            f"question relevance {self.question_relevance_rate:.2f} < "
            f"{QUESTION_RELEVANCE_THRESHOLD}\n"
            + "\n".join(
                f"  - {s.case.name} -> {s.suspect_slug} ({s.question_relevance_reasoning})\n"
                f"    question: {s.result.targeted_question.prompt[:150]}"
                for s in self.scores
                if not s.question_relevant
            )
        )

    def reasoning_quality_message(self) -> str:
        return (
            f"reasoning quality {self.reasoning_quality_rate:.2f} < "
            f"{REASONING_QUALITY_THRESHOLD}\n"
            + "\n".join(
                f"  - {s.case.name} -> {s.suspect_slug} ({s.reasoning_quality_reasoning})\n"
                f"    reasoning: {s.result.reasoning[:150]}"
                for s in self.scores
                if not s.reasoning_grounded
            )
        )


def run_case(case: DiagnosisCase, graph: DependencyGraph) -> tuple[DiagnosisResult, DiagnosisTrace]:
    """Drive the real diagnoser for one case. Shared with the standalone probe script."""
    by_id = {c.id: c for c in graph.concepts}
    concept = by_id[case.answered_concept_id]
    question = concept.questions[0]
    return diagnoser._diagnose_with_trace(
        concept,
        graph,
        question,
        Answer(question_id=question.id, text=case.student_answer),
        EvaluationResult(correct=False, explanation=case.evaluation_explanation),
    )


@lru_cache
def score_all() -> SuiteResult:
    graph = build_graph()
    by_id = {c.id: c for c in graph.concepts}
    scores = []
    for case in CASES:
        result, trace = run_case(case, graph)
        suspect = by_id.get(result.suspected_gap_concept_id)
        if suspect is None:
            # Tier 1 reports this; skip the judges rather than crash on a bad id.
            scores.append(
                CaseScore(case, result, trace, False, "suspect not in graph", False, "suspect not in graph")
            )
            continue
        relevant, relevance_why = judge_question_relevance(
            result.targeted_question.prompt, suspect
        )
        grounded, grounded_why = judge_reasoning_quality(
            case.evaluation_explanation, suspect, result.reasoning, graph
        )
        scores.append(
            CaseScore(case, result, trace, relevant, relevance_why, grounded, grounded_why)
        )
    return SuiteResult(graph=graph, scores=scores)
