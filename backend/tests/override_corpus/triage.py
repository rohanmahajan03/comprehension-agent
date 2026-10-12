"""Triage for answer overrides: an LLM proposes, a human rules, rulings become cases.

Design doc: docs/specs/2026-10-11-override-feedback-loop-design.md §4. Usage, from
backend/ with the env loaded (`set -a && source ../.env && set +a`):

    .venv/bin/python -m tests.override_corpus.triage propose   # new overrides → proposals.jsonl
    .venv/bin/python -m tests.override_corpus.triage review    # interactive → rulings.jsonl
    .venv/bin/python -m tests.override_corpus.triage promote   # rulings → cases.jsonl
    .venv/bin/python -m tests.override_corpus.triage judges    # classifier calibration

`propose` reads overrides through `get_store()`, so it needs `DATABASE_URL` — under
`InMemoryStore` there is nothing to read. `review` and `promote` make no API calls.

**Classification, not clustering.** At tens of rows an embedding cluster has no name and no
owner; the fix step needs a label that names a component to change. So the model picks
from a fixed taxonomy (cases.CATEGORIES) and the "clusters" are the counts per label.

**The proposal never decides.** An override is a claim by someone with a stake in the
outcome, so only a human ruling is promoted. Whether the reviewer accepted the proposal
unchanged is recorded, which measures the classifier on real data for free.

The prompt deliberately shares no wording with question_generator's rule 10 or the
evaluator's prompt, for the reason the points judge gives: a classifier sharing the
generator's instructions shares its blind spots. Its model is also neither of theirs.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

import anthropic

from app.config import get_settings
from app.models import AnswerOverride

from . import cases as C
from .cases import Case

_MODEL = "claude-opus-4-5"

_SYSTEM_PROMPT = """You are reviewing a dispute in an adaptive tutoring system. A student answered a quiz question, an automated grader marked the answer wrong, and the student pressed a button saying the grade was wrong. Decide what most likely went wrong, so a developer knows which part of the system to look at.

You are given the question, an expert's MODEL ANSWER (deliberately more thorough than a passing answer needs to be), the REQUIRED POINTS the grader marked against (every one must be expressed for a pass), the student's answer, the grader's explanation, and optionally the student's note. The question was written by one of two components: "pipeline1" questions come from a question generator, which also writes the required points; "diagnostic" questions are follow-up probes written by a diagnoser, have no required points, and are graded against points the grader picks itself.

Pick exactly one category:
- points_overreach: a required point asks for more than the question does — detail from the model answer, a particular of one illustration, or an optional idea bundled into the same point as an essential one — and the student's answer fails only on that extra material. The student answered what was asked.
- paraphrase_missed: the required points are reasonable and the student's answer does express each of them, in different words or with their own valid example, but the grader did not recognise it.
- type_misread: the answer was judged as though the question asked for something different — e.g. one specific example demanded where the question invites any valid example, or every item of a list demanded where the question asks for one.
- rubric_wrong: the model answer or a required point is factually wrong, or contradicts the question, and the student's answer is right.
- probe_unanswerable: a diagnostic question whose expected answer the student could not reasonably have produced from what was asked.
- override_invalid: the grader was right. The required points are a fair bar and the student's answer genuinely leaves one out, gets it wrong, or only names it without explaining it. Students dispute grades they are disappointed by; a confident note is not evidence.
- unclear: the record does not contain enough to decide.

Then name the component to look at: question_generator (it wrote the points or model answer), evaluator (the grader misread a sound bar), diagnoser (it wrote the probe), or none (override_invalid / unclear).

Also give the question's type as best you can tell from its wording: conceptual_correctness (explain what something is and how it works), conceptual_distinction (contrast two things), enumeration_completeness (list every member of a fixed set), applied_reasoning (reach a conclusion about a scenario), open_ended_example (the student supplies their own example), or unknown.

Decide on the evidence in the record, not on the student's note alone, and judge the required points against the question as asked, not against the model answer.

Return JSON:
- quoted_point: the single required point (or, with none recorded, the idea) the dispute turns on, quoted exactly; empty if there is none
- rationale: one or two sentences a developer can check quickly against the record
- category, component, question_type"""

_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            # Evidence before verdict, the ordering every other judge here uses.
            "quoted_point": {"type": "string"},
            "rationale": {"type": "string"},
            "category": {"type": "string", "enum": list(C.CATEGORIES)},
            "component": {"type": "string", "enum": list(C.COMPONENTS)},
            "question_type": {"type": "string", "enum": [*C.QUESTION_TYPES, "unknown"]},
        },
        "required": ["quoted_point", "rationale", "category", "component", "question_type"],
        "additionalProperties": False,
    },
}


@dataclass(frozen=True)
class Proposal:
    category: str
    component: str
    question_type: str | None
    quoted_point: str
    rationale: str


def snapshot_from_override(override: AnswerOverride) -> dict:
    """The anonymized record triage works from. Drops the session and document ids (the
    key replaces them), the question id (it embeds the document id), and the timestamp."""
    return {
        "key": C.override_key(override.study_session_id, override.history_seq),
        "concept": override.concept_id.rsplit(":", 1)[-1],
        "question_kind": override.question_kind,
        "question_prompt": override.question_prompt,
        "expected_answer_notes": override.expected_answer_notes,
        "required_points": override.required_points,
        "student_answer": override.student_answer,
        "student_note": override.student_note,
        "evaluator_explanation": override.evaluator_explanation,
        "evaluator_model": override.evaluator_model,
    }


def _points_block(points: list[str] | None) -> str:
    if points is None:
        return "(not recorded — this override predates the field)"
    if not points:
        return "(none — the grader chose its own points)"
    return "\n".join(f"{i}. {p}" for i, p in enumerate(points, 1))


def render(snapshot: dict) -> str:
    """The record as the classifier sees it, and as `review` shows it to the human."""
    note = snapshot.get("student_note") or "(no note)"
    return (
        f"QUESTION KIND: {snapshot.get('question_kind') or 'unknown'}\n\n"
        f"QUESTION:\n{snapshot['question_prompt']}\n\n"
        f"MODEL ANSWER:\n{snapshot['expected_answer_notes']}\n\n"
        f"REQUIRED POINTS:\n{_points_block(snapshot.get('required_points'))}\n\n"
        f"STUDENT ANSWER:\n{snapshot['student_answer']}\n\n"
        f"GRADER'S EXPLANATION:\n{snapshot['evaluator_explanation']}\n\n"
        f"STUDENT'S NOTE:\n{note}"
    )


@lru_cache
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=get_settings().llm_api_key)


def propose(snapshot: dict) -> Proposal:
    response = _client().messages.create(
        model=_MODEL,
        max_tokens=1024,
        temperature=0,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": render(snapshot)}],
        output_config={"format": _SCHEMA},
    )
    text = next(block.text for block in response.content if block.type == "text")
    data = json.loads(text)
    question_type = data["question_type"]
    return Proposal(
        category=data["category"],
        component=data["component"],
        question_type=None if question_type == "unknown" else question_type,
        quoted_point=data["quoted_point"],
        rationale=data["rationale"],
    )


def build_case(snapshot: dict, ruling: dict) -> Case:
    """One confirmed ruling → one case. Raises if the ruling can't be a case."""
    if ruling["category"] in C.UNPROMOTABLE:
        raise ValueError(f"{snapshot['key']}: {ruling['category']!r} rulings are not promoted")
    points = snapshot.get("required_points")
    return Case(
        id=snapshot["key"],
        synthetic=False,
        split=C.split_for(snapshot["key"]),
        category=ruling["category"],
        component=ruling["component"],
        question_kind=snapshot.get("question_kind"),
        question_type=ruling.get("question_type"),
        concept=snapshot["concept"],
        question_prompt=snapshot["question_prompt"],
        expected_answer_notes=snapshot["expected_answer_notes"],
        required_points=tuple(points) if points is not None else None,
        student_answer=snapshot["student_answer"],
        student_note=snapshot.get("student_note"),
        evaluator_explanation=snapshot["evaluator_explanation"],
        evaluator_model=snapshot.get("evaluator_model"),
        reviewer_note=ruling.get("reviewer_note"),
    )


@dataclass(frozen=True)
class Promotion:
    cases: tuple[Case, ...]
    skipped: tuple[tuple[str, str], ...]  # (key, reason) for every ruling not promoted


def promote(proposals: list[dict], rulings: list[dict]) -> Promotion:
    """Pure: every promotable ruling becomes a case; everything else is reported, not
    silently dropped. A later ruling on the same key replaces an earlier one, so a
    reviewer can correct a decision by ruling again."""
    snapshots = {p["key"]: p["snapshot"] for p in proposals}
    latest = {r["key"]: r for r in rulings}
    cases: list[Case] = []
    skipped: list[tuple[str, str]] = []
    for key, ruling in latest.items():
        if key not in snapshots:
            skipped.append((key, "ruling has no proposal/snapshot"))
            continue
        if ruling["category"] in C.UNPROMOTABLE:
            skipped.append((key, f"ruled {ruling['category']}"))
            continue
        case = build_case(snapshots[key], ruling)
        if not case.modes:
            skipped.append((key, "no way to grade it (no recorded points / no question_type)"))
            continue
        cases.append(case)
    return Promotion(tuple(cases), tuple(skipped))


def agreement(rulings: list[dict]) -> tuple[int, int]:
    """(proposals accepted unchanged, rulings) — the classifier's accuracy on real data."""
    latest = list({r["key"]: r for r in rulings}.values())
    return sum(1 for r in latest if r.get("accepted_unchanged")), len(latest)


# --- CLI ---------------------------------------------------------------------------------


def _cmd_propose() -> int:
    from app.store import get_store

    if not get_settings().database_url:
        print("DATABASE_URL is not set — InMemoryStore holds no overrides from past runs.")
        return 1
    done = {p["key"] for p in C.read_jsonl(C.PROPOSALS_PATH)}
    fresh = [
        s for s in map(snapshot_from_override, get_store().list_answer_overrides())
        if s["key"] not in done
    ]
    print(f"{len(fresh)} new override(s); {len(done)} already proposed.")
    for snapshot in fresh:
        proposal = propose(snapshot)
        C.append_jsonl(C.PROPOSALS_PATH, {"key": snapshot["key"], "snapshot": snapshot,
                                          "proposal": proposal.__dict__})
        print(f"  {snapshot['key']}  {proposal.category:<20} {proposal.component}")
    return 0


def _choose(label: str, options: tuple[str, ...], default: str | None) -> str | None:
    for i, option in enumerate(options, 1):
        print(f"    {i}. {option}{'  (proposed)' if option == default else ''}")
    while True:
        raw = input(f"  {label} [enter = {default}]: ").strip()
        if not raw:
            return default
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        print(f"  enter a number from 1 to {len(options)}")


def _cmd_review() -> int:
    ruled = {r["key"] for r in C.read_jsonl(C.RULINGS_PATH)}
    pending = [p for p in C.read_jsonl(C.PROPOSALS_PATH) if p["key"] not in ruled]
    print(f"{len(pending)} proposal(s) to review. a=accept, c=change, s=skip, q=quit.\n")
    for record in pending:
        snapshot, proposal = record["snapshot"], record["proposal"]
        print("=" * 80, f"\n{record['key']}  concept: {snapshot['concept']}\n")
        print(render(snapshot))
        print(
            f"\nPROPOSED: {proposal['category']} → {proposal['component']}  "
            f"(type: {proposal['question_type'] or 'unknown'})\n"
            f"  point: {proposal['quoted_point'] or '-'}\n  why:   {proposal['rationale']}"
        )
        action = input("\n[a/c/s/q] ").strip().lower()
        if action == "q":
            break
        if action not in ("a", "c"):
            continue
        ruling = {
            "key": record["key"],
            "category": proposal["category"],
            "component": proposal["component"],
            "question_type": proposal["question_type"],
            "accepted_unchanged": action == "a",
        }
        if action == "c":
            ruling["category"] = _choose("category", C.CATEGORIES, proposal["category"])
            default_component = C.DEFAULT_COMPONENT[ruling["category"]] or proposal["component"]
            ruling["component"] = _choose("component", C.COMPONENTS, default_component)
            ruling["question_type"] = _choose(
                "question type", C.QUESTION_TYPES, proposal["question_type"]
            )
        ruling["reviewer_note"] = input("  note (optional): ").strip() or None
        C.append_jsonl(C.RULINGS_PATH, ruling)
    return 0


def _cmd_promote() -> int:
    result = promote(C.read_jsonl(C.PROPOSALS_PATH), C.read_jsonl(C.RULINGS_PATH))
    C.write_cases(result.cases)
    by_category = Counter(c.category for c in result.cases)
    print(f"wrote {len(result.cases)} case(s) to {C.CASES_PATH}")
    for category, n in by_category.most_common():
        print(f"  {category:<20} {n}")
    for key, reason in result.skipped:
        print(f"  skipped {key}: {reason}")
    accepted, total = agreement(C.read_jsonl(C.RULINGS_PATH))
    if total:
        print(f"triage agreement: {accepted}/{total} proposals accepted unchanged")
    return 0


def _cmd_judges() -> int:
    from .calibration import calibration_fixtures, rates

    fixtures = calibration_fixtures()
    results = [(f, propose(f.snapshot)) for f in fixtures]
    for f, p in results:
        mark = "ok  " if p.category == f.expected else "MISS"
        print(f"  {mark} {f.name:<48} expected {f.expected:<18} got {p.category}")
        if p.category != f.expected:
            print(f"       {p.rationale}")
    for category, (hit, n) in rates(results).items():
        print(f"{category:<20} {hit}/{n}")
    return 0


def main(argv: list[str]) -> int:
    commands = {"propose": _cmd_propose, "review": _cmd_review, "promote": _cmd_promote,
                "judges": _cmd_judges}
    if len(argv) == 2 and argv[1] in commands:
        return commands[argv[1]]()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
