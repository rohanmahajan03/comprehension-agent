"""Answer evaluation (pipeline 2, step 2)."""

import json
from functools import lru_cache

import anthropic

from app.config import get_settings
from app.models import Answer, EvaluationResult, Question

_MODEL = "claude-haiku-4-5"

_SYSTEM_PROMPT = """You are an answer evaluator for an adaptive tutoring system.

You will be given a question, usually a list of REQUIRED POINTS, a MODEL ANSWER, and a student's answer.

The REQUIRED POINTS are the bar. The MODEL ANSWER is written by an expert and is deliberately more complete than a passing answer needs to be: use it only to understand what each required point means. Anything in it that is not a required point is optional, so never mark an answer incorrect for leaving it out, and never list it as missing.

If no REQUIRED POINTS are given, first identify the few points the question itself requires an answer to express, then grade against those the same way.

A point is expressed if the student states or explains that idea, in any wording or with any valid example of their own. A point is NOT expressed if the student only names the idea or restates the term instead of explaining it (a definition that rephrases the term itself, such as "a cache stores cached data"), or gives a conclusion without the reason or mechanism the point calls for (such as "the query is slow because it takes a long time").

Check every point before deciding. The answer is correct only if it expresses every point and states nothing factually wrong. Mark it incorrect if it states something factually wrong or reverses a relationship (e.g. which causes which), even if every point is otherwise expressed.

Return your response as JSON:
- point_checks: one entry per point, in order, with the point and whether the student expressed it
- correct: your verdict
- explanation: if correct, briefly confirm the points expressed. If incorrect, name the points that are missing or wrong, and any factual error — never optional material. Do not speculate about the student's understanding — that is handled downstream.

In your explanation, do not credit the student with an idea they did not express. An idea expressed in different words, or illustrated with a different valid example, counts as expressed."""

_OUTPUT_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            # Listed before `correct` so the model works through each point before it
            # commits to a verdict. Not returned to callers: EvaluationResult is unchanged.
            "point_checks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "point": {"type": "string"},
                        "expressed": {"type": "boolean"},
                    },
                    "required": ["point", "expressed"],
                    "additionalProperties": False,
                },
            },
            "correct": {"type": "boolean"},
            "explanation": {"type": "string"},
        },
        "required": ["point_checks", "correct", "explanation"],
        "additionalProperties": False,
    },
}


@lru_cache
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=get_settings().llm_api_key)


def evaluate(question: Question, answer: Answer) -> EvaluationResult:
    """Grade `answer` against `question`'s required points, using its model answer
    (`expected_answer_notes`) only to interpret them. A question with no required points
    (written before the field existed, or a diagnostic probe) is graded against points
    the evaluator identifies from the question itself."""
    prompt = f"QUESTION:\n{question.prompt}\n\n"
    if question.required_points:
        points = "\n".join(f"{i}. {p}" for i, p in enumerate(question.required_points, 1))
        prompt += f"REQUIRED POINTS:\n{points}\n\n"
    prompt += (
        f"MODEL ANSWER:\n{question.expected_answer_notes}\n\n"
        f"STUDENT ANSWER:\n{answer.text}"
    )
    response = _client().messages.create(
        model=_MODEL,
        max_tokens=1024,
        temperature=0,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        output_config={"format": _OUTPUT_SCHEMA},
    )
    text = next(block.text for block in response.content if block.type == "text")
    data = json.loads(text)
    return EvaluationResult(correct=data["correct"], explanation=data["explanation"])
