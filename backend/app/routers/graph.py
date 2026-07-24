from fastapi import APIRouter, HTTPException

from app.models import DependencyGraph
from app.store import get_store

router = APIRouter(prefix="/api", tags=["graph"])


@router.get("/graph/{doc_id}", response_model=DependencyGraph)
def get_graph(doc_id: str) -> DependencyGraph:
    graph = get_store().get_graph(doc_id)
    if graph is None:
        raise HTTPException(status_code=404, detail=f"No graph found for doc '{doc_id}'")
    return graph
