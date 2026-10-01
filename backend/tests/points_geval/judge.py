"""The points judge: does a question's `required_points` put the bar in the right place?

points_geval measures that question exactly, but only for the 10 questions that have
ruled answers. Every question question_generator writes for a real chapter — the ~32 in
tests/question_geval, for a start — has points and no rulings, so nothing measures them.
This judge reads a question's points directly and asks the two things a ruling would
have revealed:

- **Is each point essential?** A point that isn't fails a student who answered the
  question as asked — the over-requiring direction, and the one points_geval's first run
  found every miss in (clocks' NTP slewing; a point bundling two ideas).
- **Is the bar high enough?** Points an answer could satisfy while omitting what the
  question demands pass a student who hasn't shown understanding — the under-requiring
  direction.

It deliberately does not reuse question_generator's wording (rule 10, the type
descriptions). A judge that shares the generator's instructions shares its blind spots,
and the question here is whether those instructions produce the right bar, not whether
the generator followed them. The judge model is also not the generator's.

Calibrated against fixtures built from the rulings (calibration.py) before it is trusted
anywhere else — see test_judge_calibration.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

import anthropic

from app.config import get_settings

# Stronger than, and different from, both the generator (claude-sonnet-4-6) whose points
# are judged and the evaluator (claude-haiku-4-5) that grades against them. "Is this
# essential to the question?" is open-ended judgment, the same kind eval_geval uses this
# model for, not the structural matching the cheaper judges elsewhere do.
_JUDGE_MODEL = "claude-opus-4-5"

_SYSTEM_PROMPT = """You are auditing the grading bar for a quiz question in an adaptive tutoring system.

A grader will mark a student's answer correct only if it expresses every one of the REQUIRED POINTS. The MODEL ANSWER is an expert's complete answer and is deliberately more thorough than a passing answer needs to be. Decide whether the required points put the bar in the right place: neither failing a student who has shown they understand what the question asks, nor passing one who has not.

The standard for both checks is the difference between a WRONG answer and a LESS COMPLETE one. A knowledgeable teacher marks an answer wrong when it fails to answer what was asked; an answer that answers it but leaves out detail the expert included is less complete, and still correct. The required points should fail exactly the wrong answers.

First, check each required point. Imagine an answer that expresses every other point but not this one. If a teacher would mark that answer wrong, the point is essential. If the answer would merely be less complete, the point is not essential — typical examples are the particulars of one illustration, a nuance of how a mechanism is implemented, an additional property beyond the ones that answer the question, or a remark about practice. That the model answer states something, or that it is true and relevant, does not make it essential. A point that bundles an essential idea together with an inessential one is not essential as written, because a student who expresses only the essential half would fail it; say which half is inessential.

Then decide whether the points together are sufficient. Imagine an answer that expresses every point and nothing more. If a teacher would mark that answer wrong — because it still lacks the reason or mechanism behind a conclusion, a defining property of the concept, one of the items asked for, or one side of a comparison — the bar is too low; list each missing idea. If that answer would be correct but less complete than the model answer, the points are sufficient: do not list an idea as missing because it would make the answer better, or because the points already imply it.

Judge against the question as asked. The model answer shows what its author had in mind; it is not a list of requirements, and leaving part of it out of the points is correct whenever that part is not needed to answer the question. The question type tells you what kind of answer is being asked for:
- conceptual_correctness: explain what the concept is and how it works.
- conceptual_distinction: explain how two things differ or relate; both sides of the contrast are needed.
- enumeration_completeness: list every item in a fixed set; each item, accurately described, is needed.
- applied_reasoning: reach a conclusion about a scenario and give the reasoning that connects the concept to it.
- open_ended_example: the student supplies their own example. Points must describe what any valid example has to show, never the specifics of one particular example.

Return JSON:
- point_checks: one entry per required point, in the order given, with the point, whether it is essential, and one sentence of reasoning
- missing: each idea the question demands that no point covers (empty if none)
- sufficient: whether the points together are a high enough bar"""

_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            # Per-point checks come first so each point is weighed before the set-level
            # verdict, the same ordering evaluator.py uses for its point_checks.
            "point_checks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "point": {"type": "string"},
                        "essential": {"type": "boolean"},
                        "reasoning": {"type": "string"},
                    },
                    "required": ["point", "essential", "reasoning"],
                    "additionalProperties": False,
                },
            },
            "missing": {"type": "array", "items": {"type": "string"}},
            "sufficient": {"type": "boolean"},
        },
        "required": ["point_checks", "missing", "sufficient"],
        "additionalProperties": False,
    },
}


@dataclass(frozen=True)
class PointCheck:
    point: str
    essential: bool
    reasoning: str


@dataclass(frozen=True)
class PointsJudgment:
    checks: tuple[PointCheck, ...]  # aligned with the points judged, by index
    missing: tuple[str, ...]
    sufficient: bool

    @property
    def inessential(self) -> list[int]:
        """Indexes of points judged inessential — each one fails an answer it shouldn't."""
        return [i for i, c in enumerate(self.checks) if not c.essential]

    @property
    def over_requires(self) -> bool:
        return bool(self.inessential)

    @property
    def under_requires(self) -> bool:
        return not self.sufficient

    @property
    def sound(self) -> bool:
        return not self.over_requires and not self.under_requires


@lru_cache
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=get_settings().llm_api_key)


def judge_points(
    question_type: str, question: str, model_answer: str, points: tuple[str, ...]
) -> PointsJudgment:
    """Judge one question's required points. Takes a tuple so callers can cache on it.

    Raises if the judge returns a different number of point checks than points given:
    checks are read by index, and a misaligned list would attribute a verdict to the
    wrong point — every metric built on it would be silently wrong.
    """
    numbered = "\n".join(f"{i}. {p}" for i, p in enumerate(points, 1))
    prompt = (
        f"QUESTION TYPE: {question_type}\n\n"
        f"QUESTION:\n{question}\n\n"
        f"MODEL ANSWER:\n{model_answer}\n\n"
        f"REQUIRED POINTS:\n{numbered}"
    )
    response = _client().messages.create(
        model=_JUDGE_MODEL,
        max_tokens=2048,
        temperature=0,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        output_config={"format": _SCHEMA},
    )
    text = next(block.text for block in response.content if block.type == "text")
    data = json.loads(text)
    checks = tuple(
        PointCheck(c["point"], bool(c["essential"]), c["reasoning"]) for c in data["point_checks"]
    )
    if len(checks) != len(points):
        raise ValueError(
            f"points judge returned {len(checks)} point checks for {len(points)} points"
        )
    return PointsJudgment(checks, tuple(data["missing"]), bool(data["sufficient"]))
