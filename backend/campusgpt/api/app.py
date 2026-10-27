"""FastAPI application factory. Run with: uvicorn campusgpt.api.app:app --reload"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from campusgpt.api import admin, auth, chat, student
from campusgpt.config import get_settings
from campusgpt.db import make_async_engine
from campusgpt.llm import Provider, make_provider


def create_app(database_url: str | None = None, llm: Provider | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.engine = make_async_engine(database_url)
        app.state.llm = llm or make_provider(get_settings())
        yield
        if llm is None:
            await app.state.llm.aclose()
        await app.state.engine.dispose()

    app = FastAPI(title="CampusGPT", lifespan=lifespan)
    app.include_router(auth.router)
    app.include_router(student.router)
    app.include_router(chat.router)
    app.include_router(admin.router)
    app.add_middleware(UncompressedEvents)

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    return app


class UncompressedEvents:
    """Marks event streams "no-transform". The Next.js proxy gzips responses that allow it,
    and a gzipped stream reaches the browser in one piece when it ends, so the chat's
    progress would only show once the answer was complete."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = dict(message["headers"])
                if headers.get(b"content-type", b"").startswith(b"text/event-stream"):
                    message["headers"] = [
                        (k, b"no-cache, no-transform" if k == b"cache-control" else v)
                        for k, v in message["headers"]]
            await send(message)
        await self.app(scope, receive, send_wrapper)


app = create_app()
