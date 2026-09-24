"""Answer evaluation (pipeline 2, step 2)."""

import json
from functools import lru_cache

import anthropic

from app.config import get_settings
from app.models import Answer, EvaluationResult, Question

_MODEL = "claude-haiku-4-5"

_SYSTEM_PROMPT = """You are an answer evaluator for an adaptive tutoring system.

You will be given a question, a rubric, and a student's answer.

The RUBRIC is a model answer written by an expert. It is deliberately more complete than a passing answer needs to be — do not treat each of its sentences as a requirement. Grade whether the student demonstrates the understanding the question asks for, not whether they reproduce the rubric.

A brief answer can still be incorrect. Mark the answer incorrect if it:
- states something factually wrong, or reverses a relationship (e.g. which causes which)
- gets the question's main answer wrong (the wrong property, model, or mechanism)
- only names or restates an idea instead of explaining it: a definition that rephrases the term itself ("a cache stores cached data"), or a justification that restates the outcome ("the query is slow because it takes a long time")
- leaves out one of the items the question asks to list
- gives no reason or mechanism when the question asks why or how

Your job:
1. Determine whether the student's answer is correct
2. If incorrect or incomplete, identify specifically which elements required by the rubric are missing or wrong — stay close to the rubric, do not interpret or diagnose why

Return your response as JSON matching this schema:
{
  "correct": bool,
  "explanation": string
}

If correct, explanation should briefly confirm which rubric elements were satisfied.
If incorrect, explanation should list precisely which rubric elements were absent or wrong. Do not speculate about the student's understanding — that is handled downstream.
In your explanation, do not credit the student with an idea they did not express. An idea expressed in different words, or illustrated with a different valid example, counts as expressed."""

_OUTPUT_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "correct": {"type": "boolean"},
            "explanation": {"type": "string"},
        },
        "required": ["correct", "explanation"],
        "additionalProperties": False,
    },
}


@lru_cache
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=get_settings().llm_api_key)


def evaluate(question: Question, answer: Answer) -> EvaluationResult:
    """Grade `answer` against `question` by asking Claude to check it against the rubric."""
    prompt = (
        f"QUESTION:\n{question.prompt}\n\n"
        f"RUBRIC:\n{question.expected_answer_notes}\n\n"
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
