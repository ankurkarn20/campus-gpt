"""Chat endpoint: streams the answer as Server-Sent Events over POST."""
from collections.abc import AsyncIterable
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from campusgpt import chat
from campusgpt.api.student import get_now
from campusgpt.auth import CurrentUser, require_role
from campusgpt.db import get_db
from campusgpt.llm import Provider

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: int | None = None


def get_provider(request: Request) -> Provider:
    return request.app.state.llm


async def checked_request(body: ChatRequest,
                          user: CurrentUser = Depends(require_role("student")),
                          db: AsyncSession = Depends(get_db)) -> ChatRequest:
    """Reject a conversation id that belongs to someone else before streaming starts."""
    if body.conversation_id is not None and not await chat.owns_conversation(
            db, user, body.conversation_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return body


@router.post("", response_class=EventSourceResponse)
async def ask(body: ChatRequest = Depends(checked_request),
              user: CurrentUser = Depends(require_role("student")),
              db: AsyncSession = Depends(get_db),
              provider: Provider = Depends(get_provider),
              now: datetime = Depends(get_now)) -> AsyncIterable[ServerSentEvent]:
    async for event in chat.run(db, provider, user, body.message, body.conversation_id, now):
        yield ServerSentEvent(event=event.kind, data=event.data)
