from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import SessionLocal
from app.errors import register_error_handlers, register_unhandled_error_middleware
from app.http_hardening import BodySizeLimitMiddleware, SecurityHeadersMiddleware, install_access_log_redaction
from app.processing.worker import ProcessingWorker
from app.rate_limit import limiter
from app.routers import auth, dashboard, documents, health, recommendations, sim_s3
from app.storage import get_storage


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Simulated HeadBucket: fail loudly at startup if the store is unusable (doc 09.2).
    get_storage().check()
    settings = get_settings()
    worker = None
    if settings.processing_worker_enabled:  # durable job queue (AM-7)
        worker = ProcessingWorker(
            SessionLocal,
            get_storage(),
            poll_seconds=settings.processing_poll_seconds,
            max_process_bytes=settings.max_process_bytes,
        )
        worker.start()
    try:
        yield
    finally:
        if worker is not None:
            worker.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    # API docs stay public (viva: "automatic API docs").
    app = FastAPI(title="CloudVault API", lifespan=lifespan)
    app.state.limiter = limiter
    register_error_handlers(app)
    # Innermost, next to the routes: its 413 must reach FastAPI's body parsing unwrapped.
    app.add_middleware(BodySizeLimitMiddleware)
    # Added before CORS so CORS still decorates 500 responses.
    register_unhandled_error_middleware(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    # Outermost: headers also reach CORS preflight answers and early 413s.
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_production)
    install_access_log_redaction()
    app.include_router(health.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(documents.router, prefix="/api")
    app.include_router(dashboard.router, prefix="/api")
    app.include_router(recommendations.router, prefix="/api")
    app.include_router(sim_s3.router, prefix="/api")
    return app


app = create_app()
