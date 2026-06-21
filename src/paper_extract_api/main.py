"""FastAPI application entrypoint."""

from __future__ import annotations

import logging

from fastapi import FastAPI

from paper_extract_api.config import settings
from paper_extract_api.database import init_db
from paper_extract_api.routes import health, jobs

log = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, version="0.1.0")
    app.include_router(health.router, prefix=settings.api_prefix)
    app.include_router(jobs.router, prefix=settings.api_prefix)

    @app.on_event("startup")
    def on_startup() -> None:
        logging.basicConfig(level=logging.DEBUG if settings.debug else logging.INFO)
        init_db()
        log.info("Paper Extract API started; storage=%s", settings.storage_root)

    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run(
        "paper_extract_api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
    )


if __name__ == "__main__":
    run()
