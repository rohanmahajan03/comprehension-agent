"""Answer evaluation (pipeline 2, step 2)."""

import json
from functools import lru_cache

import anthropic

from app.config import get_settings
from app.models import Answer, EvaluationResult, Question

_MODEL = "claude-haiku-4-5"

_SYSTEM_PROMPT = """You are an answer evaluator for an adaptive tutoring system.

You will be given a question, rubric notes describing what a correct answer should contain, and a student's answer.

Your job:
1. Determine whether the student's answer is correct
2. If incorrect or incomplete, identify specifically which elements required by the rubric are missing or wrong — stay close to the rubric, do not interpret or diagnose why

Return your response as JSON matching this schema:
{
  "correct": bool,
  "explanation": string
}

If correct, explanation should briefly confirm which rubric elements were satisfied.
If incorrect, explanation should list precisely which rubric elements were absent or wrong. Do not speculate about the student's understanding — that is handled downstream."""

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
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        output_config={"format": _OUTPUT_SCHEMA},
    )
    text = next(block.text for block in response.content if block.type == "text")
    data = json.loads(text)
    return EvaluationResult(correct=data["correct"], explanation=data["explanation"])
