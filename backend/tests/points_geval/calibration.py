"""Calibration fixtures for the points judge: point sets whose right verdict is known.

Every fixture is derived from a question's handwritten points — eval_geval's, taken from
the numbered items of its G-Eval criterion, which is the bar the rulings in rulings.py
were made against — and perturbed in one known direction:

- **ideal** — the handwritten points unchanged. The judge must call every point
  essential and the set sufficient.
- **padded** — the handwritten points plus one the rulings make optional: model-answer
  material outside the criterion's numbered items, and where possible something a
  ruled-correct answer omits. The judge must flag the added point.
- **bundled** — one handwritten point rewritten to carry an optional idea alongside the
  essential one: rule 10's "one idea per point" breaking, which is what points_geval's
  first run found (clocks). The judge must flag the bundled point, since a student
  expressing only its essential half fails it.
- **thinned** — the handwritten points cut down to what a ruled-incorrect answer does
  express. Where an answer is named, these are points that answer would clear, so a judge
  accepting them as sufficient is accepting a bar the rulings say is too low.

The categories guard each other against a degenerate judge. One that flags everything
aces padded, bundled and thinned and fails ideal; one that flags nothing does the
reverse. Only a judge that discriminates passes all of them.

Fixtures are built from the handwritten points by index rather than copying their text,
so an edit to eval_geval's points flows through to every fixture derived from it.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from .judge import PointsJudgment, judge_points
from .rulings import VERDICTS
from .support import RuledAnswer, collect_ruled_answers, generate_points

Kind = Literal["ideal", "padded", "bundled", "thinned"]

# Each rate is asserted on its own: a combined rate would let a judge that flags
# everything (or nothing) average its way past. Loose on purpose — 10 ideal and 10
# thinned fixtures, 9 over-requiring ones, so one call flipping moves a rate by 0.1.
IDEAL_ACCEPTANCE_THRESHOLD = 0.8  # ideal fixtures judged sound
OVER_DETECTION_THRESHOLD = 0.8  # padded + bundled fixtures with the planted point flagged
UNDER_DETECTION_THRESHOLD = 0.8  # thinned fixtures judged insufficient

_FAULT = "ddia:ch1-fault-tolerance:q1"
_RELIABILITY = "ddia:ch1-reliability:q1"
_DATA_MODELS = "ddia:ch2-data-models:q1"
_INDEXING = "ddia:ch3-storage-retrieval:q1"
_ASYNC = "ddia:ch4-encoding-evolution:q1"
_REPLICATION_LAG = "ddia:ch5-replication:q1"
_HOTSPOT = "ddia:ch6-partitioning:q1"
_GSI = "ddia:ch6-secondary-indexes:q1"
_ACID = "ddia:ch7-transactions:q1"
_CLOCKS = "ddia:ch8-distributed-troubles:q1"


@dataclass(frozen=True)
class _Padding:
    name: str
    question_id: str
    point: str
    basis: str
    # A ruled-correct answer that omits the point, when one exists — the strongest
    # evidence it is optional. Otherwise the basis is the criterion alone.
    omitted_by: str | None = None


@dataclass(frozen=True)
class _Bundling:
    name: str
    question_id: str
    index: int  # which handwritten point is replaced
    point: str
    basis: str
    omitted_by: str | None = None


@dataclass(frozen=True)
class _Thinning:
    name: str
    question_id: str
    keep: tuple[int, ...]  # handwritten point indexes kept, in order
    basis: str
    # A ruled-incorrect answer that expresses every kept point, when one exists.
    cleared_by: str | None = None
    # Kept points rewritten to what the answer actually expresses, by kept-index.
    rewrite: tuple[tuple[int, str], ...] = ()


_PADDINGS = (
    _Padding(
        "fault_plus_fault_tolerance_goal", _FAULT,
        "Fault-tolerant systems aim to prevent faults from escalating into failures.",
        "The model answer's closing sentence; the criterion requires only the two "
        "definitions and the causal direction.",
    ),
    _Padding(
        "data_models_plus_join_table", _DATA_MODELS,
        "A relational database models the relationship with a join table, such as an "
        "enrollments table holding student_id and course_id.",
        "An illustration from the model answer; the criterion requires that "
        "many-to-many relationships need joins, not how the join is laid out.",
    ),
    _Padding(
        "indexing_plus_developer_choice", _INDEXING,
        "Choosing what to index is a tradeoff left to the application developer.",
        "The model answer's closing sentence; the criterion requires the definition "
        "and the read/write tradeoff, not who makes the choice.",
    ),
    _Padding(
        "async_plus_sync_contrast", _ASYNC,
        "Synchronous processing, by contrast, blocks the caller until the operation "
        "completes.",
        "The criterion says an answer must not be penalized for defining synchronous "
        "processing — permitted, not required.",
    ),
    _Padding(
        "replication_lag_plus_leader_recorded", _REPLICATION_LAG,
        "The write went to the leader and was successfully recorded there.",
        "Named as elaboration in the criterion and by an explicit ruling.",
        omitted_by="test_ch5_replication_lag_correct_concise_mechanism",
    ),
    _Padding(
        "clocks_plus_slewing", _CLOCKS,
        "NTP can slew a monotonic clock, speeding it up or slowing it down, but cannot "
        "make it jump.",
        "Named as elaboration in the criterion and by an explicit ruling.",
        omitted_by="test_ch8_clocks_correct_omits_slewing_and_cross_machine",
    ),
    _Padding(
        "clocks_plus_cross_machine", _CLOCKS,
        "Monotonic clock values are meaningless in absolute terms and cannot be "
        "compared across machines.",
        "Named as elaboration in the criterion and by an explicit ruling; also the "
        "point points_geval's first run generated.",
        omitted_by="test_ch8_clocks_correct_omits_slewing_and_cross_machine",
    ),
)

_BUNDLINGS = (
    _Bundling(
        "clocks_monotonic_bundles_slewing", _CLOCKS, 1,
        "A monotonic clock only moves forward, so it is suited to measuring durations "
        "such as timeouts, and NTP can slew it but never make it jump.",
        "The essential monotonic point joined to slewing, which the criterion names as "
        "elaboration.",
        omitted_by="test_ch8_clocks_correct_omits_slewing_and_cross_machine",
    ),
    _Bundling(
        "replication_lag_mechanism_bundles_leader", _REPLICATION_LAG, 1,
        "The write appears missing because it was successfully recorded on the leader "
        "but the read was served by a follower that had not yet caught up, due to "
        "replication lag.",
        "The essential mechanism joined to the leader/follower detail the criterion "
        "names as elaboration (\"the system hasn't synced yet\" is sufficient).",
        omitted_by="test_ch5_replication_lag_correct_concise_mechanism",
    ),
)

_THINNINGS = (
    _Thinning(
        "fault_without_causal_link", _FAULT, (0, 1),
        "Drops the causal direction the criterion requires.",
        cleared_by="test_ch1_fault_vs_failure_partially_correct_missing_causal_link",
    ),
    _Thinning(
        "reliability_without_why", _RELIABILITY, (0,),
        "Names the property without the reason.",
        cleared_by="test_ch1_reliability_violation_partially_correct_weak_justification",
    ),
    _Thinning(
        "data_models_without_why", _DATA_MODELS, (0,),
        "Names the model without the reason.",
        cleared_by="test_ch2_relational_vs_document_partially_correct_weak_justification",
    ),
    _Thinning(
        "indexing_without_tradeoff", _INDEXING, (0,),
        "Drops the read/write tradeoff.",
        cleared_by="test_ch3_indexing_partially_correct_misses_tradeoff",
    ),
    _Thinning(
        "async_without_acknowledgement", _ASYNC, (1,),
        "Drops acknowledgement versus completion.",
        cleared_by="test_ch4_async_partially_correct_missing_acknowledgement",
    ),
    _Thinning(
        "replication_lag_without_mechanism", _REPLICATION_LAG, (0,),
        "Keeps the scenario and drops the mechanism, which is the criterion's second "
        "item and the only thing separating the ruled-incorrect answers from the "
        "correct ones.",
    ),
    _Thinning(
        "hotspot_without_why", _HOTSPOT, (1,),
        "Keeps the hotspot and drops why partitioning by user_id causes it.",
        cleared_by="test_ch6_partition_hotspot_partially_correct_missing_why",
    ),
    _Thinning(
        "gsi_without_pointers", _GSI, (0, 1, 3),
        "Drops that GSI entries point to primary keys rather than holding records — "
        "the criterion's third item, and what the local-copy answer gets wrong.",
    ),
    _Thinning(
        "acid_without_durability", _ACID, (0, 1, 2),
        "Drops one of the four properties.",
        cleared_by="test_ch7_acid_partially_correct_missing_durability",
    ),
    _Thinning(
        "clocks_without_jumping", _CLOCKS, (0, 1),
        "Rewrites the time-of-day point to omit that it can jump, which an explicit "
        "ruling makes required.",
        cleared_by="test_ch8_clocks_partially_correct_missing_time_of_day_dangers",
        rewrite=((0, "A time-of-day clock returns the current date and time, "
                     "synchronized across machines via NTP."),),
    ),
)


@dataclass(frozen=True)
class CalibrationFixture:
    name: str
    kind: Kind
    question_id: str
    question_type: str
    prompt: str
    model_answer: str
    points: tuple[str, ...]
    basis: str
    # padded/bundled: the index of the point the judge must flag inessential.
    planted: int | None = None

    def hit(self, judgment: PointsJudgment) -> bool:
        """Did the judge reach this fixture's known verdict?"""
        if self.kind == "ideal":
            return judgment.sound
        if self.kind == "thinned":
            return judgment.under_requires
        return self.planted in judgment.inessential


def _question(question_id: str) -> RuledAnswer:
    return next(a for a in collect_ruled_answers() if a.question_id == question_id)


def _fixture(name: str, kind: Kind, q: RuledAnswer, points, basis: str, planted=None):
    return CalibrationFixture(
        name=name, kind=kind, question_id=q.question_id, question_type=q.question_type,
        prompt=q.prompt, model_answer=q.model_answer, points=tuple(points), basis=basis,
        planted=planted,
    )


def _check_ruling(name: str, expected: bool) -> None:
    if VERDICTS.get(name) is not expected:
        raise AssertionError(
            f"calibration cites {name} as ruled {expected}, but rulings.py says "
            f"{VERDICTS.get(name)}"
        )


@lru_cache
def calibration_fixtures() -> tuple[CalibrationFixture, ...]:
    """Every fixture, in kind order. Fails loudly if a cited ruling disagrees or a
    perturbation points past the handwritten points it modifies."""
    question_ids = dict.fromkeys(a.question_id for a in collect_ruled_answers())
    fixtures = [
        _fixture(f"{qid.split(':')[1]}_ideal", "ideal", _question(qid),
                 _question(qid).handwritten_points, "eval_geval's handwritten points.")
        for qid in question_ids
    ]

    for p in _PADDINGS:
        if p.omitted_by:
            _check_ruling(p.omitted_by, True)
        q = _question(p.question_id)
        points = (*q.handwritten_points, p.point)
        fixtures.append(_fixture(p.name, "padded", q, points, p.basis, planted=len(points) - 1))

    for b in _BUNDLINGS:
        if b.omitted_by:
            _check_ruling(b.omitted_by, True)
        q = _question(b.question_id)
        points = list(q.handwritten_points)
        if not 0 <= b.index < len(points):
            raise AssertionError(f"{b.name}: no handwritten point {b.index}")
        points[b.index] = b.point
        fixtures.append(_fixture(b.name, "bundled", q, points, b.basis, planted=b.index))

    for t in _THINNINGS:
        if t.cleared_by:
            _check_ruling(t.cleared_by, False)
        q = _question(t.question_id)
        # A thinning must lower the bar: drop a point, or rewrite one to say less.
        if not set(t.keep) <= set(range(len(q.handwritten_points))):
            raise AssertionError(f"{t.name}: no handwritten point among {t.keep}")
        if len(t.keep) == len(q.handwritten_points) and not t.rewrite:
            raise AssertionError(f"{t.name}: keeps every point and rewrites none")
        points = [q.handwritten_points[i] for i in t.keep]
        for i, text in t.rewrite:
            points[i] = text
        fixtures.append(_fixture(t.name, "thinned", q, points, t.basis))

    return tuple(fixtures)


# Plain dicts rather than lru_cache so the terminal summary can report exactly what a
# run judged — a `-k` run judges a subset, and the summary must never make calls itself.
FIXTURE_JUDGMENTS: dict[str, PointsJudgment] = {}
GENERATED_JUDGMENTS: dict[str, PointsJudgment] = {}


def judge_fixture(name: str) -> PointsJudgment:
    if name not in FIXTURE_JUDGMENTS:
        f = next(f for f in calibration_fixtures() if f.name == name)
        FIXTURE_JUDGMENTS[name] = judge_points(f.question_type, f.prompt, f.model_answer, f.points)
    return FIXTURE_JUDGMENTS[name]


def judge_generated(question_id: str) -> PointsJudgment:
    """The judge's verdict on the points points_geval's generator wrote for a question.

    This is the judge doing its real job — on generated points rather than planted
    ones — on the only questions where what those points actually did to ruled answers
    is known. The terminal summary sets the two side by side.
    """
    if question_id not in GENERATED_JUDGMENTS:
        q = _question(question_id)
        GENERATED_JUDGMENTS[question_id] = judge_points(
            q.question_type, q.prompt, q.model_answer, generate_points(question_id)
        )
    return GENERATED_JUDGMENTS[question_id]


def rate(kinds: set[str]) -> tuple[int, int]:
    """(hits, total) over the fixtures of the given kinds, judging any not yet judged.
    The summary passes only kinds whose fixtures are all in FIXTURE_JUDGMENTS."""
    fixtures = [f for f in calibration_fixtures() if f.kind in kinds]
    return sum(1 for f in fixtures if f.hit(judge_fixture(f.name))), len(fixtures)
