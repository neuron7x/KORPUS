from typing import Annotated

from fastapi import APIRouter, Depends

from korpus.application.answer_query import AnswerPolicy, AnswerQuery
from korpus.config import Settings, get_settings
from korpus.domain.models import Answer, Query
from korpus.infrastructure.in_memory import (
    EvidenceBoundStubGenerator,
    InMemoryAuditSink,
    InMemoryRetriever,
)

router = APIRouter()


SettingsDependency = Annotated[Settings, Depends(get_settings)]


def answer_service(settings: SettingsDependency) -> AnswerQuery:
    return AnswerQuery(
        retriever=InMemoryRetriever(),
        generator=EvidenceBoundStubGenerator(),
        audit=InMemoryAuditSink(),
        policy=AnswerPolicy(minimum_score=settings.min_retrieval_score),
    )


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/v1/answers", response_model=Answer)
async def create_answer(
    query: Query,
    service: Annotated[AnswerQuery, Depends(answer_service)],
) -> Answer:
    return await service.execute(query)
