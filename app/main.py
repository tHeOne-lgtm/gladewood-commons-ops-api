"""FastAPI application factory."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import sessionmaker

from app.config import Settings, get_settings
from app.db import make_engine, normalize_database_url
from app.routers import demand, financials, health, records, users
from app.routers.crm import (activities, companies, consents, contacts, deals, decisions, imports, notes,
                             pipelines, timeline, today)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not settings.database_url:
            raise RuntimeError("DATABASE_URL is not set")
        engine = make_engine(normalize_database_url(settings.database_url), settings)
        app.state.engine = engine
        app.state.sessionmaker = sessionmaker(bind=engine, expire_on_commit=False)
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(title="Gladewood Commons Operations API", lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.include_router(health.router)
    app.include_router(users.router)
    app.include_router(records.properties)
    app.include_router(records.prospects)
    app.include_router(records.residents)
    app.include_router(records.conflict_log)
    app.include_router(financials.router)
    app.include_router(demand.router)
    for r in (companies, contacts, pipelines, deals, activities, notes, timeline, imports, today, decisions, consents):
        app.include_router(r.router)
    return app


app = create_app()
