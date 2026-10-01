"""Does question_generator's `required_points` set the bar where the rulings put it?

`tests/eval_geval` hands the evaluator handwritten points derived from the same criteria
its judge grades with, so its score describes grading under ideal points — the trap
CLAUDE.md records for its old 39/42. In production the points come from
question_generator's rule 10. This suite closes that gap: it has the generator's model
write points for each of eval_geval's 10 questions, runs the real evaluator on every
ruled answer against them, and compares the verdict with the ruling. No judge model:
the rulings are the ground truth, so the comparison is exact.

A wrong verdict here has two possible causes, and the terminal summary prints the
generated points so they can be told apart: points that over-require (a correct answer
fails on elaboration) or under-require (a vague answer clears a bar that was too low),
or an evaluator error against sound points.

One deliberate approximation. In production the points are written in the same call as
the question and model answer, from source passages; here the question and model answer
already exist, so the points are written in a call of their own from those. The prompt
is built from question_generator's own text (the question types and rule 10, sliced out
of `_SYSTEM_PROMPT`), so editing rule 10 changes what this suite measures with no edit
here — and a restructured prompt fails loudly in `points_system_prompt()` rather than
silently measuring stale wording.
"""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from functools import lru_cache

from app.models import Answer, EvaluationResult, Question
from app.services import evaluator, question_generator

from .rulings import EXPLICIT_RULINGS, QUESTION_TYPES, VERDICTS

_EVAL_GEVAL_MODULES = [f"tests.eval_geval.test_ch{n}" for n in range(1, 9)]

_POINTS_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {"required_points": {"type": "array", "items": {"type": "string"}}},
        "required": ["required_points"],
        "additionalProperties": False,
    },
}


@dataclass(frozen=True)
class RuledAnswer:
    name: str  # the eval_geval test this answer comes from
    question_id: str
    prompt: str
    question_type: str
    model_answer: str
    # eval_geval's handwritten points, taken from the numbered items of the question's
    # G-Eval criterion — the bar the rulings were made against. The points judge's
    # calibration starts from these (see calibration.py).
    handwritten_points: tuple[str, ...]
    student_answer: str
    expected_correct: bool
    explicit: bool  # decided case by case rather than read off a variant label


@lru_cache
def collect_ruled_answers() -> tuple[RuledAnswer, ...]:
    """Every eval_geval answer, paired with its ruling.

    The answers are read out of eval_geval's own test functions — each is called with its
    module's `assert_evaluator_judgment` swapped for a recorder — rather than copied here,
    so the two suites can never disagree about what a student wrote. Fails loudly if a
    test has no ruling, a ruling names no test, or eval_geval asserts a verdict that
    contradicts the ruling here.
    """
    answers: list[RuledAnswer] = []
    for module_name in _EVAL_GEVAL_MODULES:
        module = importlib.import_module(module_name)
        original = module.assert_evaluator_judgment
        try:
            for name in sorted(vars(module)):
                if not name.startswith("test_"):
                    continue
                recorded: dict = {}
                module.assert_evaluator_judgment = lambda **kw: recorded.update(kw)
                getattr(module, name)()
                if name not in VERDICTS:
                    raise AssertionError(f"eval_geval test {name} has no ruling in rulings.py")
                asserted = recorded.get("expected_correct")
                if asserted is not None and asserted is not VERDICTS[name]:
                    raise AssertionError(
                        f"{name}: eval_geval asserts correct={asserted}, rulings.py says "
                        f"{VERDICTS[name]}"
                    )
                answers.append(
                    RuledAnswer(
                        name=name,
                        question_id=recorded["question_id"],
                        prompt=recorded["prompt"],
                        question_type=QUESTION_TYPES[recorded["question_id"]],
                        model_answer=recorded["golden_answer"],
                        handwritten_points=tuple(recorded["required_points"]),
                        student_answer=recorded["student_answer"],
                        expected_correct=VERDICTS[name],
                        explicit=name in EXPLICIT_RULINGS,
                    )
                )
        finally:
            module.assert_evaluator_judgment = original

    unmatched = set(VERDICTS) - {a.name for a in answers}
    if unmatched:
        raise AssertionError(f"rulings.py names tests eval_geval doesn't have: {sorted(unmatched)}")
    return tuple(answers)


def points_system_prompt() -> str:
    """The generator's question-type descriptions and rule 10, verbatim, around a task
    statement for writing points alone."""
    prompt = question_generator._SYSTEM_PROMPT
    for marker in ("## Question types", "## Output format", "10. Write `required_points`", "## Input"):
        if marker not in prompt:
            raise AssertionError(
                f"question_generator._SYSTEM_PROMPT no longer contains {marker!r}; "
                "update points_system_prompt() to match its new structure"
            )
    types_section = prompt[prompt.index("## Question types"):prompt.index("## Output format")]
    rules_tail = prompt[prompt.index("10. Write `required_points`"):prompt.index("## Input")]
    # Rule 10 runs until the next numbered rule, if one is ever added after it.
    rule_10 = rules_tail.split("\n11.")[0].strip()
    return (
        "You are an expert tutor. A question and its expected_answer (the ideal student "
        "response) have already been written. Write its required_points.\n\n"
        f"{types_section.strip()}\n\n{rule_10}\n\n"
        'Return JSON: {"required_points": ["..."]}'
    )


@lru_cache
def generate_points(question_id: str) -> tuple[str, ...]:
    """Required points for one question, from question_generator's model and settings."""
    answer = next(a for a in collect_ruled_answers() if a.question_id == question_id)
    user = json.dumps(
        {"type": answer.question_type, "question": answer.prompt, "expected_answer": answer.model_answer}
    )
    response = question_generator._client().messages.create(
        model=question_generator._MODEL,
        max_tokens=1024,
        temperature=0,
        system=points_system_prompt(),
        messages=[{"role": "user", "content": user}],
        output_config={"format": _POINTS_SCHEMA},
    )
    text = next(block.text for block in response.content if block.type == "text")
    points = json.loads(text)["required_points"]
    # Same cleanup generate_questions() applies before persisting.
    return tuple(p.strip() for p in points if p.strip())


@lru_cache
def grade(name: str) -> EvaluationResult:
    """The real evaluator's verdict on one ruled answer, against generated points."""
    answer = next(a for a in collect_ruled_answers() if a.name == name)
    question = Question(
        id=answer.question_id,
        concept_id=answer.question_id.rsplit(":", 1)[0],
        prompt=answer.prompt,
        expected_answer_notes=answer.model_answer,
        required_points=list(generate_points(answer.question_id)),
    )
    return evaluator.evaluate(question, Answer(question_id=question.id, text=answer.student_answer))
