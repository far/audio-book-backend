"""App factory -- the FastAPI-specific wiring lives here, kept out of
main.py so main.py stays a thin entrypoint."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.deps import get_session_store
from app.api.middleware import LoggingMiddleware
from app.api.routers import health, session, tts, upload
from app.infrastructure.session_store import InMemorySessionStore

_CLEANUP_INTERVAL_SECONDS = 60 * 15

logger = logging.getLogger("aireader")


async def _periodic_session_cleanup() -> None:
    # cleanup_expired is a TTL sweep specific to the in-memory implementation
    # -- deliberately not on the SessionStore port, since a future Redis
    # implementation would use native TTL and wouldn't need this at all.
    store = get_session_store()
    if not isinstance(store, InMemorySessionStore):
        return
    while True:
        await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)
        expired = await store.cleanup_expired()
        if expired:
            logger.info("session cleanup: expired %d session(s)", expired)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    task = asyncio.create_task(_periodic_session_cleanup())
    try:
        yield
    finally:
        task.cancel()


def create_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO)

    app = FastAPI(title="AI Reader backend", lifespan=_lifespan)

    app.add_middleware(LoggingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # dev-only, no auth in v1 (see spec/plan.md decisions table)
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(upload.router)
    app.include_router(session.router)
    app.include_router(tts.router)

    return app
