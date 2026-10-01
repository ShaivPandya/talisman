"""FastAPI application entrypoint."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from longaeva_app.api.routers import (
    evaluation,
    forecasts,
    health,
    jobs,
    observations,
    parameters,
    runs,
    scenarios,
    sources,
)
from longaeva_app.api.schemas import OPENAPI_CONTRACT_SCHEMAS

app = FastAPI(
    title="Longaeva",
    version="0.1.0",
    description="Standalone Visa business-simulation API (hackathon).",
)

app.include_router(health.router)
app.include_router(jobs.router)
app.include_router(sources.router)
app.include_router(observations.router)
app.include_router(parameters.router)
app.include_router(scenarios.router)
app.include_router(runs.router)
app.include_router(forecasts.router)
app.include_router(evaluation.router)


def custom_openapi() -> dict[str, Any]:
    if app.openapi_schema is not None:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    # Ensure Create schemas appear in the published contract before write routes exist.
    for model in OPENAPI_CONTRACT_SCHEMAS:
        model_schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
        defs = model_schema.pop("$defs", {})
        for def_name, def_schema in defs.items():
            components.setdefault(def_name, def_schema)
        components.setdefault(model.__name__, model_schema)
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi  # type: ignore[method-assign]
