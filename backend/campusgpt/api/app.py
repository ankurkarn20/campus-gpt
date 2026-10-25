"""FastAPI application factory. Run with: uvicorn campusgpt.api.app:app --reload"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from campusgpt.api import auth, chat, student
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

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
