"""Regression cases promoted from triaged answer overrides — the data model and its files.

Design doc: docs/specs/2026-10-11-override-feedback-loop-design.md. An override is a
student's *claim* the evaluator misgraded them; a case is that claim after a human has
ruled on it (triage.py's `review`), in either direction. A confirmed misgrade expects
`correct: true`; a confirmed `override_invalid` expects `correct: false` and is the only
real-user evidence of where the bar should *stay* (§5).

Three files under `data/`, all gitignored because they hold real student writing (§5's
privacy note — commit `cases.jsonl` only with its writers' permission):

- `proposals.jsonl` — triage's LLM proposals, each beside the snapshot it was made from
- `rulings.jsonl`   — the human's decision on each proposal, the only input to promotion
- `cases.jsonl`     — what tests/override_geval runs, rebuilt whole by `promote`

Synthetic cases (seeds.py) never touch these files; they are built in memory and flagged
`synthetic`, so every reported number can exclude them.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

DATA_DIR = Path(__file__).parent / "data"
PROPOSALS_PATH = DATA_DIR / "proposals.jsonl"
RULINGS_PATH = DATA_DIR / "rulings.jsonl"
CASES_PATH = DATA_DIR / "cases.jsonl"

Category = Literal[
    "points_overreach",
    "paraphrase_missed",
    "type_misread",
    "rubric_wrong",
    "probe_unanswerable",
    "override_invalid",
    "unclear",
]
Component = Literal["evaluator", "question_generator", "diagnoser", "none"]
Split = Literal["tune", "holdout"]
Mode = Literal["snapshot", "regenerated"]

CATEGORIES: tuple[str, ...] = Category.__args__  # type: ignore[attr-defined]
COMPONENTS: tuple[str, ...] = Component.__args__  # type: ignore[attr-defined]
QUESTION_TYPES = (
    "conceptual_correctness",
    "conceptual_distinction",
    "enumeration_completeness",
    "applied_reasoning",
    "open_ended_example",
)

#: The student was right: the case expects `correct: true`.
MISGRADE_CATEGORIES = frozenset(
    {"points_overreach", "paraphrase_missed", "type_misread", "rubric_wrong", "probe_unanswerable"}
)
#: Never promoted — a case nobody can rule on can't be a regression test.
UNPROMOTABLE = frozenset({"unclear"})

#: The component each category blames by default (§4). `type_misread` has none: it can be
#: either the evaluator or the generator, so the reviewer decides per case.
DEFAULT_COMPONENT: dict[str, str | None] = {
    "points_overreach": "question_generator",
    "paraphrase_missed": "evaluator",
    "type_misread": None,
    "rubric_wrong": "question_generator",
    "probe_unanswerable": "diagnoser",
    "override_invalid": "none",
    "unclear": "none",
}


def override_key(study_session_id: str, history_seq: int) -> str:
    """A stable, anonymous id for one override.

    Hashes the attempt's identity (the table's own unique key) rather than carrying the
    session id, so a committed case can't be joined back to a session. Stable, so triage
    can tell which overrides it has already seen and the split never moves.
    """
    digest = hashlib.sha256(f"{study_session_id}:{history_seq}".encode()).hexdigest()
    return f"ov-{digest[:12]}"


def split_for(key: str) -> Split:
    """Fixed at promotion and never recomputed from anything that can change (§5).

    A hash of the key rather than a running alternation, so adding a case never moves an
    existing one between `tune` and `holdout` — which would leak holdout cases into tuning.
    """
    return "tune" if int(hashlib.sha256(key.encode()).hexdigest(), 16) % 2 == 0 else "holdout"


@dataclass(frozen=True)
class Case:
    id: str
    synthetic: bool
    split: Split
    category: str
    component: str
    question_kind: str | None  # "pipeline1" | "diagnostic" | None (not recorded)
    question_type: str | None  # set by the reviewer; production never stores it
    concept: str  # the concept's slug only — readable, and carries no document id
    question_prompt: str
    expected_answer_notes: str
    # None = not recorded (an override older than the snapshot columns); () = the
    # evaluator chose its own points. Kept distinct for the same reason the column is.
    required_points: tuple[str, ...] | None
    student_answer: str
    student_note: str | None
    evaluator_explanation: str
    evaluator_model: str | None
    reviewer_note: str | None = None

    @property
    def expected_correct(self) -> bool:
        return self.category in MISGRADE_CATEGORIES

    @property
    def modes(self) -> tuple[Mode, ...]:
        """How this case is graded — which part of the pipeline it holds fixed (§5).

        `snapshot` grades against the points the evaluator actually saw: the rubric is
        held fixed and the evaluator is under test. `regenerated` writes fresh points with
        question_generator's model and rule 10 first: the generator is under test.

        A misgrade runs only in the mode its component dictates. An `override_invalid`
        case guards the bar against *any* fix, so it runs in every mode it can — a rule-10
        change only shows up in `regenerated`, an evaluator change only in `snapshot`.
        """
        can_snapshot = self.required_points is not None
        can_regenerate = self.question_type is not None and self.question_kind != "diagnostic"
        if self.category == "override_invalid":
            return tuple(
                m for m, ok in (("snapshot", can_snapshot), ("regenerated", can_regenerate)) if ok
            )
        if self.component == "question_generator":
            return ("regenerated",) if can_regenerate else ()
        return ("snapshot",) if can_snapshot else ()


def validate(cases: Iterable[Case]) -> None:
    """Raise on anything that would make a case silently untestable or mis-reported.

    Run at load, so a malformed `cases.jsonl` fails collection rather than a test.
    """
    seen: set[str] = set()
    for case in cases:
        problems = []
        if case.id in seen:
            problems.append("duplicate id")
        seen.add(case.id)
        if case.category not in CATEGORIES or case.category in UNPROMOTABLE:
            problems.append(f"category {case.category!r} can't be a case")
        if case.component not in COMPONENTS:
            problems.append(f"unknown component {case.component!r}")
        if case.question_type is not None and case.question_type not in QUESTION_TYPES:
            problems.append(f"unknown question_type {case.question_type!r}")
        if case.split not in ("tune", "holdout"):
            problems.append(f"unknown split {case.split!r}")
        if not case.synthetic and case.split != split_for(case.id):
            problems.append("split doesn't match split_for(id) — it was moved by hand")
        if not case.modes:
            problems.append(
                f"no way to grade it: component {case.component!r} needs "
                + ("a question_type" if case.component == "question_generator"
                   else "recorded required_points")
            )
        if problems:
            raise ValueError(f"case {case.id}: " + "; ".join(problems))


def _to_json(case: Case) -> dict:
    data = asdict(case)
    data["required_points"] = (
        list(case.required_points) if case.required_points is not None else None
    )
    return data


def _from_json(data: dict) -> Case:
    points = data.get("required_points")
    return Case(**{**data, "required_points": tuple(points) if points is not None else None})


def load_cases(path: Path = CASES_PATH) -> tuple[Case, ...]:
    """The promoted cases, or none if nothing has been promoted yet."""
    if not path.exists():
        return ()
    cases = tuple(
        _from_json(json.loads(line)) for line in path.read_text().splitlines() if line.strip()
    )
    validate(cases)
    return cases


def write_cases(cases: Iterable[Case], path: Path = CASES_PATH) -> None:
    """Rewrite the whole file, sorted by id, so a re-promotion produces a clean diff."""
    ordered = sorted(cases, key=lambda c: c.id)
    validate(ordered)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(_to_json(c), ensure_ascii=False) + "\n" for c in ordered))


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
