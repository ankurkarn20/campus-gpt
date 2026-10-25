"""FastAPI application factory. Run with: uvicorn campusgpt.api.app:app --reload"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from campusgpt.api import auth
from campusgpt.db import make_async_engine


def create_app(database_url: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.engine = make_async_engine(database_url)
        yield
        await app.state.engine.dispose()

    app = FastAPI(title="CampusGPT", lifespan=lifespan)
    app.include_router(auth.router)

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
