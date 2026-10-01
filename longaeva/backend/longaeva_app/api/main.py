"""FastAPI application entrypoint."""

from __future__ import annotations

from fastapi import FastAPI

from longaeva_app.api.routers import health, jobs

app = FastAPI(
    title="Longaeva",
    version="0.1.0",
    description="Standalone Visa business-simulation API (hackathon skeleton).",
)

app.include_router(health.router)
app.include_router(jobs.router)
