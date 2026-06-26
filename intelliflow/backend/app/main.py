from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import close_client, ensure_indexes
from .routers import iflow

logging.basicConfig(level=logging.INFO, format="%(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    await ensure_indexes()
    try:
        yield
    finally:
        await close_client()


app = FastAPI(
    title="IntelliFlow AI",
    version="0.1.0",
    description="Convert plain-English business requirements into SAP CPI iFlow designs.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(iflow.router, prefix="/api/v1")


@app.get("/health", tags=["meta"])
async def health() -> dict:
    return {"status": "ok"}
