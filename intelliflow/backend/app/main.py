from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.responses import JSONResponse

from .db import close_client, ensure_indexes
from .middleware.request_id import RequestIdMiddleware
from .routers import iflow
from .services.limiter import limiter
from .services.tracing import configure_logging

configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await ensure_indexes()
    try:
        yield
    finally:
        await close_client()


app = FastAPI(
    title="IntelliFlow AI",
    version="0.2.0",
    description="RAG-grounded SAP CPI iFlow generator.",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": f"Rate limit exceeded: {exc.detail}"},
    )


app.include_router(iflow.router, prefix="/api/v1")


@app.get("/health", tags=["meta"])
async def health() -> dict:
    return {"status": "ok"}
