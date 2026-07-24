from fastapi import APIRouter, HTTPException

from app.models import Question
from app.store import get_store

router = APIRouter(prefix="/api", tags=["questions"])


@router.get("/questions/{concept_id:path}", response_model=list[Question])
def get_questions(concept_id: str) -> list[Question]:
    questions = get_store().get_questions(concept_id)
    if questions is None:
        raise HTTPException(status_code=404, detail=f"No questions found for concept '{concept_id}'")
    return questions
